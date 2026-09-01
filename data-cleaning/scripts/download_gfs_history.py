"""Download NOAA GFS 0.25-degree history from the AWS public archive.

The NOMADS filter CGI only retains ~10 days, so historical runs are fetched
from ``noaa-gfs-bdp-pds``.  Each step file is ~460 MB; the matching ``.idx``
record offsets are used to request only the Taihu variables via HTTP Range
(~5 MB/step).  Parsed rows are written to silver CSVs and raw GRIB segments are
discarded, keeping disk usage negligible.

Path layout changed in the archive (``atmos/`` was added), so both variants are
tried.  Default scope is the 00Z cycle at 6-hourly steps to 72 h; pass
``--cycles`` / ``--step-max`` / ``--step-interval`` to widen it.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from pipeline.sources.noaa_gfs import GFS_PARAMETER_MAP, parse_gfs_grib

UTC = timezone.utc
BUCKET = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
TARGET_LEVELS = {
    "TMP": ("2 m above ground",),
    "UGRD": ("10 m above ground",),
    "VGRD": ("10 m above ground",),
    "APCP": ("surface",),
    "DSWRF": ("surface",),
    "SDSWRF": ("surface",),
    "TCDC": ("entire atmosphere",),
    "PRMSL": ("mean sea level",),
}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "Taihu-bloom-project/1.0 (research; contact-email omitted)"
# eccodes/cfgrib is not thread-safe; serialise GRIB decoding across workers.
PARSE_LOCK = threading.Lock()


def _retry_get(url: str, *, range_header: str | None = None, timeout: int = 120) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            headers = {"Range": range_header} if range_header else {}
            response = SESSION.get(url, headers=headers, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = requests.HTTPError(f"transient HTTP {response.status_code}")
            else:
                return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
        time.sleep(2**attempt)
    assert last_error is not None
    raise last_error


def _parse_idx(content: str) -> tuple[list[dict[str, Any]], list[int]]:
    """Return every record offset plus the indices of the requested variables.

    The byte range for one GRIB message is the gap to the *next* record of any
    variable; skipping other records inflates the range by tens of MB.
    """

    all_records: list[dict[str, Any]] = []
    target_indices: list[int] = []
    for line in content.splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            continue
        try:
            offset = int(parts[1])
        except ValueError:
            continue
        variable = parts[3].upper()
        level = parts[4].strip().lower()
        all_records.append({"offset": offset, "variable": variable, "level": parts[4], "raw_line": line})
        if variable in TARGET_LEVELS and level in tuple(item.lower() for item in TARGET_LEVELS[variable]):
            target_indices.append(len(all_records) - 1)
    return all_records, target_indices


def _extract_step_grib(
    idx_url: str,
    all_records: list[dict[str, Any]],
    target_indices: list[int],
    target: Path,
) -> None:
    chunks: list[tuple[int, bytes]] = []
    for position, index in enumerate(target_indices):
        start = all_records[index]["offset"]
        next_offset = all_records[index + 1]["offset"] if index + 1 < len(all_records) else None
        if next_offset is not None:
            end = next_offset
        else:
            # Last needed message: fetch a window and cut at the GRIB terminator.
            response = _retry_get(idx_url.replace(".idx", ""), range_header=f"bytes={start}-{start + 8 * 1024 * 1024 - 1}")
            if response.status_code != 206:
                raise RuntimeError(f"Range request failed for {all_records[index]['variable']} at {start}: HTTP {response.status_code}")
            terminator = response.content.find(b"7777")
            if terminator == -1:
                raise RuntimeError(f"no GRIB terminator for {all_records[index]['variable']} at {start}")
            chunks.append((index, response.content[: terminator + 4]))
            continue
        response = _retry_get(idx_url.replace(".idx", ""), range_header=f"bytes={start}-{end - 1}")
        if response.status_code == 206:
            chunks.append((index, response.content))
        else:
            raise RuntimeError(f"Range request failed for {all_records[index]['variable']} at {start}: HTTP {response.status_code}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        for _, chunk in sorted(chunks):
            handle.write(chunk)


def _download_day(run_date: str, cycle: int, steps: list[int], bbox: tuple[float, float, float, float], silver_root: Path) -> dict[str, Any]:
    run_time = f"{run_date}T{cycle:02d}:00:00+00:00"
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    date_compact = run_date.replace("-", "")
    idx_base = f"{BUCKET}/gfs.{date_compact}/{cycle:02d}/atmos/gfs.t{cycle:02d}z.pgrb2.0p25"
    idx_fallback = f"{BUCKET}/gfs.{date_compact}/{cycle:02d}/gfs.t{cycle:02d}z.pgrb2.0p25"
    temporary_gribs: list[Path] = []
    try:
        for step in steps:
            idx_url = f"{idx_base}.f{step:03d}.idx"
            response = _retry_get(idx_url)
            if response.status_code == 404:
                idx_url = f"{idx_fallback}.f{step:03d}.idx"
                response = _retry_get(idx_url)
            if response.status_code != 200:
                errors.append({"step": step, "error": f"idx HTTP {response.status_code}"})
                continue
            all_records, target_indices = _parse_idx(response.text)
            if not target_indices:
                errors.append({"step": step, "error": "no target variables in idx"})
                continue
            grib = Path(silver_root) / f".tmp_gfs_{run_date}_{cycle:02d}z_f{step:03d}.grib2"
            try:
                _extract_step_grib(idx_url, all_records, target_indices, grib)
                temporary_gribs.append(grib)
                with PARSE_LOCK:
                    parsed = parse_gfs_grib(grib, run_time=run_time, fallback_lead_hours=float(step), bbox=bbox)
                if parsed["status"] != "completed":
                    errors.append({"step": step, "error": parsed.get("error")})
                    continue
                rows.extend(parsed.pop("rows", []))
            except Exception as exc:
                errors.append({"step": step, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                if grib.exists():
                    grib.unlink()
    finally:
        for path in temporary_gribs:
            if path.exists():
                path.unlink()
    return {"run_date": run_date, "cycle": cycle, "rows": rows, "errors": errors, "record_count": len(rows)}


def run_gfs_history(
    *,
    start: date,
    end: date,
    cycles: tuple[int, ...] = (0,),
    step_interval: int = 6,
    step_max: int = 72,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    workers: int = 8,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    silver_root = STORAGE / "silver" / "forecast" / "noaa_gfs"
    silver_root.mkdir(parents=True, exist_ok=True)
    steps = list(range(0, step_max + 1, step_interval))
    manifest_path = manifest_path or STORAGE / "manifests" / "noaa_gfs_history_2021_2026.json"
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    payload = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"days": []}
    done_days = {item["run_date"] for item in payload.get("days", []) if not item["errors"] and item["record_count"]}
    outcomes: list[dict[str, Any]] = [item for item in payload.get("days", []) if item["run_date"] in done_days]

    def process(day: str) -> dict[str, Any]:
        for cycle in cycles:
            result = _download_day(day, cycle, steps, bbox, silver_root)
            if result["rows"]:
                output = silver_root / f"noaa_gfs_{day}_{cycle:02d}z_area_mean.csv"
                columns = list(result["rows"][0])
                temporary = output.with_suffix(".csv.part")
                with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = __import__("csv").DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(result["rows"])
                temporary.replace(output)
                result["output"] = str(output)
            else:
                result["output"] = None
            return result
        return {"run_date": day, "cycle": cycles[0], "errors": [{"error": "no cycles"}], "record_count": 0, "rows": []}

    pending = [day for day in days if day not in done_days]
    print(f"total days: {len(days)}, done: {len(done_days)}, pending: {len(pending)}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process, day): day for day in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            compact = {key: result[key] for key in ("run_date", "cycle", "record_count", "errors", "output")}
            outcomes.append(compact)
            print(f"[{len(outcomes)}/{len(days)}] {result['run_date']} records={result['record_count']} errors={len(result['errors'])}", flush=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps({"status": "running", "updated_at_utc": datetime.now(UTC).isoformat(), "requested": {"start": start.isoformat(), "end": end.isoformat(), "cycles": list(cycles), "steps": steps}, "days": outcomes}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    summary = {
        "status": "completed",
        "period": [start.isoformat(), end.isoformat()],
        "cycles": list(cycles),
        "steps": steps,
        "bbox": list(bbox),
        "days_total": len(days),
        "days_completed": len(outcomes),
        "days_with_records": sum(1 for item in outcomes if item["record_count"]),
        "total_records": sum(item["record_count"] for item in outcomes),
        "failed_days": [item["run_date"] for item in outcomes if item["errors"] and not item["record_count"]],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2021-02-25")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--cycles", default="0", help="comma-separated cycles (0,6,12,18)")
    parser.add_argument("--step-max", type=int, default=72)
    parser.add_argument("--step-interval", type=int, default=6)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    summary = run_gfs_history(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        cycles=tuple(int(item) for item in args.cycles.split(",") if item),
        step_interval=args.step_interval,
        step_max=args.step_max,
        workers=args.workers,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed_days"] == [] else 1


if __name__ == "__main__":
    raise SystemExit(main())
