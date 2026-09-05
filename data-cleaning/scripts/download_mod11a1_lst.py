"""Download MOD11A1 daily LST from NASA LP-DAAC.

Queries CMR for granule URLs, then downloads HDF files via curl with .netrc auth.
Tile is selectable; h28v05 does NOT cover Taihu — use h30v05 for the lake.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
OUTPUT_DIR = STORAGE / "raw" / "land_surface" / "modis_lst"
MANIFEST_PATH = STORAGE / "manifests" / "mod11a1_lst_download.json"
NETRC_PATH = Path.home() / "_netrc"

CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
COLLECTION_ID = "C1748058432-LPCLOUD"
TILE = "h30v05"
BBOX = "119.9,30.9,120.75,31.65"


def query_cmr_granules(start: date, end: date, tile: str = TILE, page_size: int = 200) -> list[dict]:
    """Query CMR for MOD11A1 granule URLs covering the date range."""
    granules = []
    page_num = 1
    temporal = f"{start.isoformat()}T00:00:00Z,{end.isoformat()}T23:59:59Z"
    while True:
        params = (
            f"collection_concept_id={COLLECTION_ID}"
            f"&short_name=MOD11A1"
            f"&temporal={temporal}"
            f"&bounding_box={BBOX}"
            f"&page_size={page_size}"
            f"&page_num={page_num}"
        )
        url = f"{CMR_URL}?{params}"
        cmd = ["curl", "-sS", "--connect-timeout", "30", "--max-time", "60", url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if result.returncode != 0:
                print(f"  CMR query error page {page_num}: {result.stderr.strip()[:200]}", flush=True)
                break
            data = json.loads(result.stdout)
        except Exception as exc:
            print(f"  CMR query error page {page_num}: {exc}", flush=True)
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            native_id = item.get("meta", {}).get("native-id", "")
            if tile not in native_id:
                continue
            umm = item.get("umm", {})
            data_url = None
            for url_info in umm.get("RelatedUrls", []):
                u = url_info.get("URL", "")
                if "lp-prod-protected" in u and u.endswith(".hdf"):
                    data_url = u
                    break
            if data_url:
                acq_date = native_id.split(".")[1] if "." in native_id else ""
                if acq_date.startswith("A"):
                    acq_date = acq_date[1:]
                granules.append({"native_id": native_id, "url": data_url, "acq_date": acq_date})

        hits = int(data.get("hits", 0))
        if page_num * page_size >= hits:
            break
        page_num += 1
        time.sleep(0.5)

    return granules


def download_one(granule: dict, output_dir: Path, timeout: int = 180) -> dict:
    filename = granule["native_id"] + ".hdf"
    out_path = output_dir / filename
    if out_path.exists() and out_path.stat().st_size > 50_000:
        return {"date": granule["acq_date"], "native_id": granule["native_id"], "status": "exists", "size": out_path.stat().st_size}

    url = granule["url"]
    netrc_flag = f"--netrc-file={NETRC_PATH}" if NETRC_PATH.exists() else "--netrc"
    cookie_jar = output_dir / ".curl_cookies"
    cmd = [
        "curl", "-sS", "-L", "-f",
        "--connect-timeout", "30",
        "--max-time", str(timeout),
        netrc_flag,
        "--cookie-jar", str(cookie_jar),
        "--cookie", str(cookie_jar),
        "-o", str(out_path),
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 50_000:
            return {"date": granule["acq_date"], "native_id": granule["native_id"], "status": "ok", "size": out_path.stat().st_size}
        else:
            stderr = result.stderr.strip()[:200]
            if out_path.exists():
                out_path.unlink()
            return {"date": granule["acq_date"], "native_id": granule["native_id"], "status": "failed", "error": stderr}
    except subprocess.TimeoutExpired:
        if out_path.exists():
            out_path.unlink()
        return {"date": granule["acq_date"], "native_id": granule["native_id"], "status": "timeout"}
    except Exception as exc:
        if out_path.exists():
            out_path.unlink()
        return {"date": granule["acq_date"], "native_id": granule["native_id"], "status": "error", "error": str(exc)[:200]}


def run_download(start: date, end: date, workers: int = 4, timeout: int = 180, tile: str = TILE) -> dict:
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFEST_PATH

    prev_done = {}
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in prev.get("days", []):
                if entry.get("status") in ("ok", "exists"):
                    prev_done[entry["native_id"]] = entry
        except Exception:
            pass

    print("Querying CMR for MOD11A1 granules...", flush=True)
    granules = query_cmr_granules(start, end, tile=tile)
    print(f"Found {len(granules)} granules for tile {tile}", flush=True)

    pending = [g for g in granules if g["native_id"] not in prev_done]
    outcomes = list(prev_done.values())
    print(f"already done: {len(prev_done)}, pending: {len(pending)}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(download_one, g, output_dir, timeout): g for g in pending}
        for future in as_completed(futures):
            result = future.result()
            outcomes.append(result)
            ok_count = sum(1 for o in outcomes if o.get("status") in ("ok", "exists"))
            fail_count = sum(1 for o in outcomes if o.get("status") in ("failed", "error", "timeout"))
            print(
                f"[{ok_count + fail_count}/{len(granules)}] {result['date']} {result['status']}"
                f"{' size=' + str(result.get('size', '')) if result['status'] in ('ok', 'exists') else ''}"
                f"{' err=' + str(result.get('error', ''))[:80] if result['status'] in ('failed', 'error') else ''}",
                flush=True,
            )
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps({
                    "status": "running",
                    "period": [start.isoformat(), end.isoformat()],
                    "granules_total": len(granules),
                    "granules_completed": len(outcomes),
                    "granules_ok": ok_count,
                    "granules_failed": fail_count,
                    "days": outcomes,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    summary = {
        "status": "completed",
        "tile": tile,
        "period": [start.isoformat(), end.isoformat()],
        "granules_total": len(granules),
        "granules_completed": len(outcomes),
        "granules_ok": sum(1 for o in outcomes if o.get("status") in ("ok", "exists")),
        "granules_failed": sum(1 for o in outcomes if o.get("status") in ("failed", "error", "timeout")),
        "failed_dates": [o["date"] for o in outcomes if o.get("status") in ("failed", "error", "timeout")],
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--tile", default=TILE, help="MODIS sinusoidal tile; Taihu needs h30v05")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    summary = run_download(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        workers=args.workers,
        timeout=args.timeout,
        tile=args.tile,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
