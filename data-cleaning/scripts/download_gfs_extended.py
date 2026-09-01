"""Download GFS 7-15 day extended forecasts (f168-f360) from NOAA AWS.

Complements the existing 0-72h download. Uses .idx HTTP Range requests
(~5 MB/step instead of ~460 MB full GRIB). Resumable via manifest.

Time range: 2021-02-26 to 2026-08-27
Forecast hours: 168, 174, 180, ..., 360 (6h interval)
Cycles: 0, 6, 12, 18 (4 per day)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORAGE_ROOT = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))

import requests
from requests.adapters import HTTPAdapter

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
SESSION.trust_env = False
SESSION.headers["User-Agent"] = "Taihu-bloom-project/1.0 (research)"
_adapter = HTTPAdapter(pool_connections=12, pool_maxsize=24)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)
PARSE_LOCK = threading.Lock()


def _retry_get(url, *, range_header=None, timeout=120):
    last_err = None
    for attempt in range(7):
        try:
            headers = {"Range": range_header} if range_header else {}
            r = SESSION.get(url, headers=headers, timeout=timeout)
            if r.status_code in {429, 500, 502, 503, 504}:
                last_err = requests.HTTPError(f"transient {r.status_code}")
            else:
                return r
        except Exception as e:
            last_err = e
        time.sleep(min(3 ** attempt, 30) + 0.5 * attempt)
    raise last_err


def _parse_idx(content):
    all_recs, target_idxs = [], []
    for line in content.splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            continue
        try:
            offset = int(parts[1])
        except ValueError:
            continue
        var = parts[3].upper()
        level = parts[4].strip().lower()
        all_recs.append({"offset": offset, "variable": var, "level": parts[4]})
        if var in TARGET_LEVELS and level in tuple(t.lower() for t in TARGET_LEVELS[var]):
            target_idxs.append(len(all_recs) - 1)
    return all_recs, target_idxs


def _extract_grib(idx_url, all_recs, target_idxs, target):
    chunks = []
    for pos, idx in enumerate(target_idxs):
        start = all_recs[idx]["offset"]
        next_off = all_recs[idx + 1]["offset"] if idx + 1 < len(all_recs) else None
        if next_off is not None:
            r = _retry_get(idx_url.replace(".idx", ""), range_header=f"bytes={start}-{next_off - 1}")
        else:
            r = _retry_get(idx_url.replace(".idx", ""), range_header=f"bytes={start}-{start + 8 * 1024 * 1024 - 1}")
            if r.status_code != 206:
                raise RuntimeError(f"Range fail HTTP {r.status_code}")
            term = r.content.find(b"7777")
            if term == -1:
                raise RuntimeError("no GRIB terminator")
            chunks.append((idx, r.content[:term + 4]))
            continue
        if r.status_code == 206:
            chunks.append((idx, r.content))
        else:
            raise RuntimeError(f"Range fail HTTP {r.status_code}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as f:
        for _, chunk in sorted(chunks):
            f.write(chunk)


def _download_day(run_date, cycle, steps, bbox, silver_root, raw_ext_root):
    run_time = f"{run_date}T{cycle:02d}:00:00+00:00"
    rows, errors = [], []
    dc = run_date.replace("-", "")
    idx_base = f"{BUCKET}/gfs.{dc}/{cycle:02d}/atmos/gfs.t{cycle:02d}z.pgrb2.0p25"
    idx_fb = f"{BUCKET}/gfs.{dc}/{cycle:02d}/gfs.t{cycle:02d}z.pgrb2.0p25"
    tmp_gribs = []

    day_out = silver_root / f"gfs_ext_{run_date}_{cycle:02d}z.csv"
    if day_out.exists() and day_out.stat().st_size > 100:
        return {"run_date": run_date, "cycle": cycle, "rows": [], "errors": [],
                "record_count": 0, "output": str(day_out), "skipped": True}

    try:
        for step in steps:
            idx_url = f"{idx_base}.f{step:03d}.idx"
            r = _retry_get(idx_url)
            if r.status_code == 404:
                idx_url = f"{idx_fb}.f{step:03d}.idx"
                r = _retry_get(idx_url)
            if r.status_code != 200:
                errors.append({"step": step, "error": f"idx HTTP {r.status_code}"})
                continue
            all_recs, target_idxs = _parse_idx(r.text)
            if not target_idxs:
                errors.append({"step": step, "error": "no target vars"})
                continue
            grib = raw_ext_root / f".tmp_gfs_ext_{run_date}_{cycle:02d}z_f{step:03d}.grib2"
            try:
                _extract_grib(idx_url, all_recs, target_idxs, grib)
                tmp_gribs.append(grib)
                with PARSE_LOCK:
                    parsed = parse_gfs_grib(grib, run_time=run_time,
                                            fallback_lead_hours=float(step), bbox=bbox)
                if parsed["status"] != "completed":
                    errors.append({"step": step, "error": parsed.get("error")})
                    continue
                rows.extend(parsed.pop("rows", []))
            except Exception as e:
                errors.append({"step": step, "error": f"{type(e).__name__}: {e}"})
            finally:
                if grib.exists():
                    grib.unlink()
    finally:
        for p in tmp_gribs:
            if p.exists():
                p.unlink()

    if rows:
        day_out.parent.mkdir(parents=True, exist_ok=True)
        tmp = day_out.with_suffix(".csv.part")
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        tmp.replace(day_out)

    return {"run_date": run_date, "cycle": cycle, "rows": rows, "errors": errors,
            "record_count": len(rows), "output": str(day_out) if rows else None}


def run_extended(*, start, end, cycles=(0, 6, 12, 18),
                 step_min=168, step_max=360, step_interval=6,
                 bbox=DEFAULT_BBOX, workers=8):
    silver_root = STORAGE_ROOT / "silver" / "forecast" / "noaa_gfs_extended"
    raw_ext_root = STORAGE_ROOT / "raw" / "meteorology" / "noaa_gfs_extended"
    silver_root.mkdir(parents=True, exist_ok=True)
    raw_ext_root.mkdir(parents=True, exist_ok=True)

    steps = list(range(step_min, step_max + 1, step_interval))
    manifest_path = STORAGE_ROOT / "manifests" / "noaa_gfs_extended_2021_2026.json"

    days = []
    cur = start
    while cur <= end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    done_set = set()
    if manifest_path.exists():
        mf = json.loads(manifest_path.read_text("utf-8"))
        done_set = {d["run_date"] for d in mf.get("days", [])
                    if not d.get("errors") and d.get("record_count", 0) > 0}

    outcomes = []
    pending = [d for d in days if d not in done_set]
    print(f"GFS extended: total={len(days)}, done={len(done_set)}, pending={len(pending)}")
    print(f"Steps: f{step_min}-f{step_max} every {step_interval}h, cycles={cycles}")

    def proc(day):
        day_rows = []
        day_errors = []
        for cyc in cycles:
            try:
                res = _download_day(day, cyc, steps, bbox, silver_root, raw_ext_root)
                day_rows.extend(res["rows"])
                day_errors.extend(res["errors"])
            except Exception as e:
                day_errors.append({"cycle": cyc, "error": f"{type(e).__name__}: {e}"})
            time.sleep(1)
        if day_rows:
            combined = silver_root / f"gfs_ext_{day}_combined.csv"
            tmp = combined.with_suffix(".csv.part")
            with tmp.open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(day_rows[0]))
                w.writeheader()
                w.writerows(day_rows)
            tmp.replace(combined)
        return {"run_date": day, "record_count": len(day_rows),
                "errors": day_errors, "output": str(combined) if day_rows else None}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(proc, d): d for d in pending}
        for fut in as_completed(futs):
            try:
                res = fut.result()
            except Exception as e:
                day = futs[fut]
                res = {"run_date": day, "record_count": 0,
                       "errors": [{"error": f"FATAL: {type(e).__name__}: {e}"}],
                       "output": None}
            outcomes.append(res)
            total_done = len(done_set) + len(outcomes)
            print(f"[{total_done}/{len(days)}] {res['run_date']} "
                  f"records={res['record_count']} errors={len(res['errors'])}",
                  flush=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({
                "status": "running",
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "requested": {"start": start.isoformat(), "end": end.isoformat(),
                              "cycles": list(cycles), "steps": steps},
                "days": [o for o in outcomes]
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "status": "completed",
        "period": [start.isoformat(), end.isoformat()],
        "cycles": list(cycles), "steps": steps,
        "bbox": list(bbox),
        "days_total": len(days), "days_completed": len(outcomes),
        "days_with_records": sum(1 for o in outcomes if o["record_count"]),
        "total_records": sum(o["record_count"] for o in outcomes),
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2021-02-26")
    ap.add_argument("--end", default="2026-08-27")
    ap.add_argument("--cycles", default="0,6,12,18")
    ap.add_argument("--step-min", type=int, default=168)
    ap.add_argument("--step-max", type=int, default=360)
    ap.add_argument("--step-interval", type=int, default=6)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    s = run_extended(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        cycles=tuple(int(c) for c in args.cycles.split(",") if c),
        step_min=args.step_min, step_max=args.step_max,
        step_interval=args.step_interval, workers=args.workers,
    )
    print(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
