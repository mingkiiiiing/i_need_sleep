"""Download MODIS Aqua+Terra L3m daily Chl-a 4km from NASA OceanColor.

Extended coverage: 2002-07 to 2026-08 (Aqua) and 2000-02 to 2026-08 (Terra).
Uses earthaccess library for Earthdata Login authentication.
Resumable — skips files that already exist with valid size.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import earthaccess

ROOT = Path(__file__).resolve().parents[1]
STORAGE_ROOT = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
BASE = STORAGE_ROOT / "raw" / "ocean_color"
PROGRESS = STORAGE_ROOT / "manifests" / "modis_extended_download.json"

SATELLITES = {
    "aqua": {
        "prefix": "AQUA_MODIS",
        "start": "2002-07-04",
    },
    "terra": {
        "prefix": "TERRA_MODIS",
        "start": "2000-02-24",
    },
}

GETFILE_BASE = "https://oceandata.sci.gsfc.nasa.gov/getfile"

_lock = threading.Lock()
_stats = {"ok": 0, "skip": 0, "miss": 0, "fail": 0}
_thread_local = threading.local()


def get_session():
    if not hasattr(_thread_local, "session"):
        auth = earthaccess.login(strategy="netrc", persist=True)
        if not auth.authenticated:
            raise RuntimeError("Earthdata Login failed")
        s = auth.get_session()
        s.trust_env = False
        retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _thread_local.session = s
    return _thread_local.session


def download_one(url, fpath, min_size=10000):
    if os.path.exists(fpath) and os.path.getsize(fpath) > min_size:
        with _lock:
            _stats["skip"] += 1
        return "skip"
    session = get_session()
    try:
        resp = session.get(url, timeout=180, stream=True)
        if resp.status_code == 200:
            with open(fpath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            if os.path.getsize(fpath) > min_size:
                with _lock:
                    _stats["ok"] += 1
                return "ok"
            else:
                os.remove(fpath)
                with _lock:
                    _stats["fail"] += 1
                return "fail_size"
        with _lock:
            _stats["fail"] += 1
        return f"fail_http_{resp.status_code}"
    except Exception as e:
        with _lock:
            _stats["fail"] += 1
        return f"fail_{type(e).__name__}"


def download_satellite(sat_name, sat_cfg, start_date, end_date, workers):
    raw_dir = BASE / f"modis_{sat_name}_chla"
    raw_dir.mkdir(parents=True, exist_ok=True)

    prefix = sat_cfg["prefix"]
    sat_start = max(datetime.strptime(sat_cfg["start"], "%Y-%m-%d"), start_date)

    total_days = (end_date - sat_start).days + 1
    print(f"\n=== {sat_name.upper()} MODIS L3m Chl-a 4km ===")
    print(f"Period: {sat_start.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Total days: {total_days}, workers: {workers}")
    print(f"Output: {raw_dir}")

    _stats.update({"ok": 0, "skip": 0, "miss": 0, "fail": 0})

    tasks = []
    current = sat_start
    while current <= end_date:
        date_str = current.strftime("%Y%m%d")
        fname = f"{prefix}.{date_str}.L3m.DAY.CHL.chlor_a.4km.nc"
        fpath = raw_dir / fname
        url = f"{GETFILE_BASE}/{fname}"
        tasks.append((url, str(fpath), fname))
        current += timedelta(days=1)

    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, url, fpath): fname
                   for url, fpath, fname in tasks}
        for fut in as_completed(futures):
            done += 1
            if done % 50 == 0 or done == len(tasks):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(tasks) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(tasks)}] {rate:.1f} files/min "
                      f"eta={eta/60:.0f}min "
                      f"ok={_stats['ok']} skip={_stats['skip']} "
                      f"fail={_stats['fail']}", flush=True)

    return dict(_stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    start_date = datetime(2002, 7, 1)
    end_date = datetime(2026, 8, 27)

    all_stats = {}
    for sat_name, sat_cfg in SATELLITES.items():
        stats = download_satellite(sat_name, sat_cfg, start_date, end_date, args.workers)
        all_stats[sat_name] = stats

    progress = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
        "stats": all_stats,
    }
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== Summary ===")
    for sat, st in all_stats.items():
        print(f"  {sat}: downloaded={st['ok']}, skipped={st['skip']}, "
              f"missing={st['miss']}, failed={st['fail']}")
    return 0


if __name__ == "__main__":
    main()
