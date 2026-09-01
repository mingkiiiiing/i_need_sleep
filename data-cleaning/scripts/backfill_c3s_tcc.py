"""Backfill C3S total_cloud_cover (tcc) into the existing Taihu silver CSVs.

The original C3S archive downloaded 5 variables; tcc was not requested.  This
script retrieves tcc-only hindcasts (shared per init month) and forecasts, then
merges the parsed rows into the existing c3s_seasonal_{year}_{month}.csv files
without touching their other variables.  Raw gribs use a ``_tcc`` suffix so the
original 5-variable files are preserved.
"""

from __future__ import annotations

import csv
import json
import sys
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

SILVER = STORAGE / "silver" / "forecast" / "c3s_seasonal"
RAW = STORAGE / "raw" / "meteorology" / "c3s_seasonal"
PROGRESS = STORAGE / "manifests" / "c3s_tcc_backfill.json"
HINDCAST_YEARS = list(range(1993, 2017))


def _atomic_rewrite(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tcc.tmp")
    fields = list(rows[0]) if rows else []
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _retrieve(client, kind: str, request: dict, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    client.retrieve(DATASET, {key: value for key, value in request.items() if key != "kind"}, str(target))


def main() -> int:
    import cdsapi

    client = cdsapi.Client()
    existing = sorted(SILVER.glob("c3s_seasonal_*.csv"))
    if not existing:
        raise SystemExit("no silver CSVs found")
    month_keys = sorted({path.stem.rsplit("_", 1)[1] for path in existing})
    outcomes: list[dict] = []
    hindcast_cache: dict[str, list[dict]] = {}
    for month_key in month_keys:
        init_month = int(month_key)
        request = build_c3s_request(
            kind="hindcast", years=HINDCAST_YEARS, init_month=init_month,
            variables=["total_cloud_cover"], lead_months=DEFAULT_LEAD_MONTHS, bbox=DEFAULT_BBOX,
        )
        raw = RAW / f"c3s_hindcast_{init_month:02d}_system51_tcc.grib"
        try:
            _retrieve(client, "hindcast", request, raw)
            parsed = parse_c3s_dataset(raw, kind="hindcast", init_month=init_month, bbox=DEFAULT_BBOX)
            hindcast_cache[month_key] = parsed["rows"]
            outcomes.append({"kind": "hindcast", "month": init_month, "status": "completed", "records": parsed["record_count"]})
        except Exception as exc:
            outcomes.append({"kind": "hindcast", "month": init_month, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})

    for path in existing:
        year, month_key = path.stem.rsplit("_", 2)[1], path.stem.rsplit("_", 1)[1]
        forecast_year = int(year)
        init_month = int(month_key)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            original = list(csv.DictReader(handle))
        fields = list(original[0]) if original else []
        if any(row.get("source_parameter") == "total_cloud_cover" for row in original):
            outcomes.append({"kind": "merge", "file": path.name, "status": "skipped_already_has_tcc", "rows_before": len(original), "rows_after": len(original)})
            continue
        merged = original[:]
        hindcast_rows = hindcast_cache.get(month_key)
        if hindcast_rows:
            merged.extend({key: row.get(key, "") for key in fields} for row in hindcast_rows)
        if forecast_year >= 2017:
            request = build_c3s_request(
                kind="forecast", years=[forecast_year], init_month=init_month,
                variables=["total_cloud_cover"], lead_months=DEFAULT_LEAD_MONTHS, bbox=DEFAULT_BBOX,
            )
            raw = RAW / f"c3s_forecast_{forecast_year}_{init_month:02d}_system51_tcc.grib"
            try:
                _retrieve(client, "forecast", request, raw)
                parsed = parse_c3s_dataset(raw, kind="forecast", init_year=forecast_year, init_month=init_month, bbox=DEFAULT_BBOX)
                merged.extend({key: row.get(key, "") for key in fields} for row in parsed["rows"])
                status = "completed"
            except Exception as exc:
                status = f"failed: {type(exc).__name__}: {exc}"
        else:
            status = "completed"
        _atomic_rewrite(path, merged)
        outcomes.append({"kind": "merge", "file": path.name, "status": status, "rows_before": len(original), "rows_after": len(merged)})
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(json.dumps({"updated_at_utc": datetime.now(timezone.utc).isoformat(), "outcomes": outcomes}, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in outcomes if item["status"] != "completed"]
    print(f"done: {len(outcomes)} units, {len(failures)} failures")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
