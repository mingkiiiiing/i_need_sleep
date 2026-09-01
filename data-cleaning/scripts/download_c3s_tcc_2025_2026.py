"""Download C3S total_cloud_cover for 2025-01 to 2026-08 (monthly inits).

Fills the gap in the 30-90 day seasonal meteorological variables.
Uses CDS API with existing ~/.cdsapirc credentials.
ECMWF system 51, lead months 1-3, Taihu bbox.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.sources.c3s_seasonal import (
    DEFAULT_BBOX,
    DEFAULT_LEAD_MONTHS,
    DATASET,
    build_c3s_request,
    parse_c3s_dataset,
)

UTC = timezone.utc
RAW = STORAGE / "raw" / "meteorology" / "c3s_seasonal"
SILVER = STORAGE / "silver" / "forecast" / "c3s_seasonal"
PROGRESS = STORAGE / "manifests" / "c3s_tcc_2025_2026.json"


def main():
    import cdsapi
    client = cdsapi.Client()

    months = []
    for y in range(2025, 2027):
        for m in range(1, 13):
            if y == 2025 and m < 1:
                continue
            if y == 2026 and m > 8:
                break
            months.append((y, m))

    print(f"C3S total_cloud_cover: {len(months)} month-inits to download")
    print(f"Period: 2025-01 to 2026-08, system 51, lead months {DEFAULT_LEAD_MONTHS}")

    outcomes = []
    for year, month in months:
        raw = RAW / f"c3s_forecast_{year}_{month:02d}_system51_tcc.grib"

        if raw.exists() and raw.stat().st_size > 1000:
            print(f"  {year}-{month:02d}: raw exists, skip download")
            outcomes.append({"year": year, "month": month, "status": "skipped_raw_exists"})
            continue

        raw_request = build_c3s_request(
            kind="forecast",
            years=[year],
            init_month=month,
            variables=["total_cloud_cover"],
            lead_months=DEFAULT_LEAD_MONTHS,
            bbox=DEFAULT_BBOX,
        )
        request = {k: v for k, v in raw_request.items() if k != "kind"}
        if "format" in request:
            request["data_format"] = request.pop("format")

        try:
            print(f"  {year}-{month:02d}: downloading...", flush=True)
            raw.parent.mkdir(parents=True, exist_ok=True)
            client.retrieve(DATASET, request, str(raw))
            size = raw.stat().st_size if raw.exists() else 0
            print(f"    -> OK ({size} bytes)")

            parsed = parse_c3s_dataset(
                raw, kind="forecast",
                init_year=year, init_month=month,
                bbox=DEFAULT_BBOX,
            )

            silver_out = SILVER / f"c3s_seasonal_{year}_{month:02d}_tcc.csv"
            silver_out.parent.mkdir(parents=True, exist_ok=True)
            if parsed["rows"]:
                import csv
                tmp = silver_out.with_suffix(".csv.part")
                with tmp.open("w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(parsed["rows"][0]))
                    w.writeheader()
                    w.writerows(parsed["rows"])
                tmp.replace(silver_out)

            outcomes.append({
                "year": year, "month": month,
                "status": "completed",
                "records": parsed["record_count"],
                "raw_bytes": size,
            })
        except Exception as e:
            print(f"    -> FAILED: {type(e).__name__}: {e}")
            outcomes.append({
                "year": year, "month": month,
                "status": "failed",
                "error": f"{type(e).__name__}: {e}",
            })

        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(json.dumps({
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "outcomes": outcomes,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        time.sleep(1)

    completed = sum(1 for o in outcomes if o["status"] == "completed")
    skipped = sum(1 for o in outcomes if "skipped" in o.get("status", ""))
    failed = sum(1 for o in outcomes if o["status"] == "failed")
    print(f"\nDone: {completed} completed, {skipped} skipped, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
