"""Download MODIS Aqua daily Chl-a L3 (9km) from NASA OB.DAAC.

Uses curl with .netrc for Earthdata authentication through the local proxy,
since Python's SSL stack has issues with the proxy CONNECT tunnel.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
OUTPUT_DIR = STORAGE / "raw" / "ocean_color" / "modis_aqua_chla"
MANIFEST_PATH = STORAGE / "manifests" / "modis_aqua_chla_download.json"
NETRC_PATH = Path.home() / "_netrc"

BASE_URL = "https://obdaac-tea.earthdatacloud.nasa.gov/ob-cumulus-prod-public"
FILE_PATTERN = "AQUA_MODIS.{date}.L3m.DAY.CHL.chlor_a.9km.nc"


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def download_one(day: date, output_dir: Path, timeout: int = 120) -> dict:
    date_str = day.strftime("%Y%m%d")
    filename = FILE_PATTERN.format(date=date_str)
    out_path = output_dir / filename
    if out_path.exists() and out_path.stat().st_size > 100_000:
        return {"date": day.isoformat(), "status": "exists", "size": out_path.stat().st_size}

    url = f"{BASE_URL}/{filename}"
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
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 100_000:
            return {"date": day.isoformat(), "status": "ok", "size": out_path.stat().st_size}
        else:
            stderr = result.stderr.strip()[:200]
            if out_path.exists():
                out_path.unlink()
            return {"date": day.isoformat(), "status": "failed", "error": stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        if out_path.exists():
            out_path.unlink()
        return {"date": day.isoformat(), "status": "timeout"}
    except Exception as exc:
        if out_path.exists():
            out_path.unlink()
        return {"date": day.isoformat(), "status": "error", "error": str(exc)[:200]}


def run_download(start: date, end: date, workers: int = 4, timeout: int = 120) -> dict:
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = MANIFEST_PATH

    days = list(date_range(start, end))
    done = {}
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in prev.get("days", []):
                if entry.get("status") in ("ok", "exists"):
                    done[entry["date"]] = entry
        except Exception:
            pass

    pending = [d for d in days if d.isoformat() not in done]
    print(f"total days: {len(days)}, done: {len(done)}, pending: {len(pending)}", flush=True)

    outcomes = list(done.values())
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(download_one, d, output_dir, timeout): d for d in pending}
        for future in as_completed(futures):
            result = future.result()
            outcomes.append(result)
            ok_count = sum(1 for o in outcomes if o.get("status") in ("ok", "exists"))
            fail_count = sum(1 for o in outcomes if o.get("status") in ("failed", "error", "timeout"))
            print(
                f"[{ok_count + fail_count}/{len(days)}] {result['date']} {result['status']}"
                f"{' size=' + str(result.get('size', '')) if result['status'] in ('ok', 'exists') else ''}"
                f"{' err=' + str(result.get('error', ''))[:80] if result['status'] in ('failed', 'error') else ''}",
                flush=True,
            )
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps({
                    "status": "running",
                    "period": [start.isoformat(), end.isoformat()],
                    "days_total": len(days),
                    "days_completed": len(outcomes),
                    "days_ok": ok_count,
                    "days_failed": fail_count,
                    "days": outcomes,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    summary = {
        "status": "completed",
        "period": [start.isoformat(), end.isoformat()],
        "days_total": len(days),
        "days_completed": len(outcomes),
        "days_ok": sum(1 for o in outcomes if o.get("status") in ("ok", "exists")),
        "days_failed": sum(1 for o in outcomes if o.get("status") in ("failed", "error", "timeout")),
        "failed_dates": [o["date"] for o in outcomes if o.get("status") in ("failed", "error", "timeout")],
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    summary = run_download(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        workers=args.workers,
        timeout=args.timeout,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
