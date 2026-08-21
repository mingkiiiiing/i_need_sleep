"""Stage-2 source connectivity checks.

The script only verifies metadata/sample responses. It does not download the
925 MB THQBCA archive or Sentinel-2 imagery by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class SourceCheck:
    source_id: str
    url: str
    status: str
    http_status: int | None
    content_type: str | None
    sample: dict[str, Any]
    error: str | None = None


def get_json(url: str, timeout: int = 30) -> tuple[int, str, Any]:
    request = Request(url, headers={"User-Agent": "A23-Taihu-data-cleaning/0.1"})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        body = response.read()
    return response.status, content_type, json.loads(body.decode("utf-8"))


def check_sentinel2() -> SourceCheck:
    params = {
        "collections": "sentinel-2-l2a",
        "bbox": "119.9,30.9,120.7,31.5",
        "datetime": "2025-06-01T00:00:00Z/2025-06-30T23:59:59Z",
        "limit": "1",
    }
    url = "https://catalogue.dataspace.copernicus.eu/stac/search?" + urlencode(params)
    try:
        status, content_type, payload = get_json(url)
        features = payload.get("features", [])
        first = features[0] if features else {}
        properties = first.get("properties", {})
        return SourceCheck(
            "copernicus_sentinel2_stac",
            url,
            "verified" if status == 200 and features else "warning_no_feature",
            status,
            content_type,
            {
                "feature_count": len(features),
                "scene_id": first.get("id"),
                "datetime": properties.get("datetime"),
                "cloud_cover": properties.get("eo:cloud_cover"),
                "assets": sorted(first.get("assets", {}).keys()),
                "metadata_missing_rate": {
                    "scene_id": 1.0 if first.get("id") is None else 0.0,
                    "datetime": 1.0 if properties.get("datetime") is None else 0.0,
                    "eo:cloud_cover": 1.0 if properties.get("eo:cloud_cover") is None else 0.0,
                },
            },
        )
    except Exception as exc:  # pragma: no cover - exercised by network failure
        return SourceCheck("copernicus_sentinel2_stac", url, "failed", None, None, {}, str(exc))


def check_nasa_power() -> SourceCheck:
    params = {
        "parameters": "T2M,WS10M,WD10M,PRECTOTCORR,ALLSKY_SFC_SW_DWN",
        "community": "RE",
        "longitude": "120.30",
        "latitude": "31.20",
        "start": "20240601",
        "end": "20240602",
        "format": "JSON",
    }
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point?" + urlencode(params)
    try:
        status, content_type, payload = get_json(url)
        parameters = payload.get("properties", {}).get("parameter", {})
        t2m = parameters.get("T2M", {})
        keys = sorted(t2m.keys())
        first_key = keys[0] if keys else None
        missing_rates = {}
        for name, values in parameters.items():
            missing = sum(value is None or value == -999 for value in values.values())
            missing_rates[name] = missing / len(values) if values else 1.0
        return SourceCheck(
            "nasa_power_hourly",
            url,
            "verified" if status == 200 and keys else "warning_no_records",
            status,
            content_type,
            {
                "location": payload.get("geometry", {}).get("coordinates"),
                "parameters": sorted(parameters.keys()),
                "record_count": len(keys),
                "first_time": first_key,
                "first_values": {
                    name: parameters.get(name, {}).get(first_key)
                    for name in sorted(parameters)
                } if first_key else {},
                "missing_rates": missing_rates,
            },
        )
    except Exception as exc:  # pragma: no cover - exercised by network failure
        return SourceCheck("nasa_power_hourly", url, "failed", None, None, {}, str(exc))


def check_zenodo() -> SourceCheck:
    url = "https://zenodo.org/api/records/13917285"
    try:
        status, content_type, payload = get_json(url)
        files = payload.get("files", [])
        return SourceCheck(
            "taihu_thqbca_zenodo",
            url,
            "verified" if status == 200 and files else "warning_no_file",
            status,
            content_type,
            {
                "title": payload.get("metadata", {}).get("title"),
                "doi": payload.get("metadata", {}).get("doi"),
                "files": [
                    {
                        "key": item.get("key"),
                        "size": item.get("size"),
                        "checksum": item.get("checksum"),
                        "download": item.get("links", {}).get("self"),
                    }
                    for item in files
                ],
            },
        )
    except Exception as exc:  # pragma: no cover - exercised by network failure
        return SourceCheck("taihu_thqbca_zenodo", url, "failed", None, None, {}, str(exc))


def write_manifest(checks: list[SourceCheck], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "checks": [asdict(check) for check in checks],
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_sample_payloads(checks: list[SourceCheck], output_dir: Path) -> None:
    """Save small metadata/sample responses, never the large source archives."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for check in checks:
        try:
            status, content_type, payload = get_json(check.url)
            path = output_dir / f"{check.source_id}.json"
            path.write_text(
                json.dumps(
                    {
                        "source_id": check.source_id,
                        "request_url": check.url,
                        "http_status": status,
                        "content_type": content_type,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - exercised by network failure
            (output_dir / f"{check.source_id}.error.txt").write_text(str(exc), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify A23 Taihu source endpoints")
    parser.add_argument(
        "--output",
        default="data-cleaning/storage/manifests/source_verification.json",
        help="JSON manifest output path",
    )
    parser.add_argument(
        "--sample-dir",
        default="data-cleaning/samples/source_samples",
        help="Directory for small JSON response samples",
    )
    args = parser.parse_args()
    checks = [check_sentinel2(), check_nasa_power(), check_zenodo()]
    write_manifest(checks, Path(args.output))
    write_sample_payloads(checks, Path(args.sample_dir))
    for check in checks:
        print(json.dumps(asdict(check), ensure_ascii=False))
    return 0 if all(check.status == "verified" for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
