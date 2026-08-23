from __future__ import annotations

"""Resumable Taihu time-series download for the CLMS LWQ 300 m V2 product."""

import argparse
import csv
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .clms_lwq_byoc import (
    PROCESS_API_URL,
    _request_token,
    build_clms_process_request,
    load_taihu_geometry,
)
from .common import PACKAGE_ROOT, sha256_file, utc_now


BANDS = ("CHLAMEAN", "CHLAUNC", "FCBPROB", "QFLAG")
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["CHLAMEAN", "CHLAUNC", "FCBPROB", "QFLAG"]}],
    output: {bands: 4, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(sample) {
  return [sample.CHLAMEAN, sample.CHLAUNC, sample.FCBPROB, sample.QFLAG];
}
"""


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _catalog_rows(catalog: Path, start: datetime, end: datetime) -> list[dict[str, str]]:
    with catalog.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    selected = [
        row
        for row in rows
        if start <= _parse_date(row["nominal_date"]) <= end
    ]
    return sorted(selected, key=lambda row: _parse_date(row["nominal_date"]))


def _is_tiff(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 8:
        return False
    with path.open("rb") as handle:
        return handle.read(4) in {b"II*\x00", b"MM\x00*"}


def _download_one(
    row: dict[str, str],
    *,
    token: str,
    geometry: dict[str, Any] | None,
    output_root: Path,
    width: int,
    height: int,
    retries: int,
) -> dict[str, Any]:
    nominal = _parse_date(row["nominal_date"])
    date_key = nominal.strftime("%Y%m%d")
    output = output_root / nominal.strftime("%Y") / f"taihu_lwq300_v2_{date_key}.tif"
    output.parent.mkdir(parents=True, exist_ok=True)
    if _is_tiff(output):
        return {
            "date": nominal.date().isoformat(),
            "status": "existing",
            "path": str(output),
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        }

    body = build_clms_process_request(
        start=row["content_date_start"],
        end=row["content_date_end"],
        geometry=geometry,
        width=width,
        height=height,
        evalscript=EVALSCRIPT,
    )
    payload = json.dumps(body).encode("utf-8")
    last_error = "unknown"
    for attempt in range(retries + 1):
        request = Request(
            PROCESS_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "image/tiff",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=180) as response:
                raster = response.read()
            if raster[:4] not in {b"II*\x00", b"MM\x00*"}:
                raise ValueError("response is not a TIFF")
            temporary = output.with_suffix(".tif.part")
            temporary.write_bytes(raster)
            temporary.replace(output)
            return {
                "date": nominal.date().isoformat(),
                "status": "completed",
                "path": str(output),
                "bytes": len(raster),
                "sha256": sha256_file(output),
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError, ValueError) as exc:
            last_error = type(exc).__name__
        if attempt < retries:
            time.sleep(2**attempt)
    return {
        "date": nominal.date().isoformat(),
        "status": "failed",
        "path": str(output),
        "error": last_error,
    }


def run_batch(
    *,
    catalog: Path,
    start: str,
    end: str,
    output_root: Path,
    manifest: Path,
    width: int = 320,
    height: int = 320,
    workers: int = 4,
) -> dict[str, Any]:
    _load_env_file(PACKAGE_ROOT / ".env.cdse")
    token = _request_token(timeout=30)
    if not token:
        raise RuntimeError("CDSE OAuth credentials are missing or invalid")

    rows = _catalog_rows(catalog, _parse_date(start), _parse_date(end))
    geometry = load_taihu_geometry()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(
                _download_one,
                row,
                token=token,
                geometry=geometry,
                output_root=output_root,
                width=width,
                height=height,
                retries=3,
            )
            for row in rows
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["date"])
    summary = {
        "source_id": "clms_lwq_300m_v2_taihu_batch",
        "status": "completed" if all(item["status"] != "failed" for item in results) else "completed_with_failures",
        "retrieved_at_utc": utc_now(),
        "requested_range": {"start": start, "end": end},
        "actual_catalog_range": {
            "start": results[0]["date"] if results else None,
            "end": results[-1]["date"] if results else None,
        },
        "bands": list(BANDS),
        "band_order": {str(index): band for index, band in enumerate(BANDS, start=1)},
        "nodata_conventions": {
            "CHLAMEAN_CHLAUNC_FCBPROB": "values >= 1e30 or non-finite",
            "QFLAG": "65535",
        },
        "official_documentation": "https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/water-bodies/lake-water-quality/lwq-nrt_global_300m_10daily_v2.html",
        "resolution_m": 300,
        "temporal_resolution": "10-daily",
        "width": width,
        "height": height,
        "records": len(results),
        "downloaded": sum(item["status"] == "completed" for item in results),
        "existing": sum(item["status"] == "existing" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "total_bytes": sum(int(item.get("bytes", 0)) for item in results),
        "output_root": str(output_root),
        "catalog": str(catalog),
        "results": results,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--start", default="2022-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-12-31T23:59:59Z")
    parser.add_argument("--output-root", type=Path, default=PACKAGE_ROOT / "storage" / "rasters" / "clms_lwq_300m_v2")
    parser.add_argument("--manifest", type=Path, default=PACKAGE_ROOT / "storage" / "manifests" / "clms_lwq_300m_v2_batch.json")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=320)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = run_batch(
        catalog=args.catalog,
        start=args.start,
        end=args.end,
        output_root=args.output_root,
        manifest=args.manifest,
        width=args.width,
        height=args.height,
        workers=args.workers,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
