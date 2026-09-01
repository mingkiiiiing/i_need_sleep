from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import rasterio

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def expected_months(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start + "-01")
    end_date = date.fromisoformat(end + "-01")
    values = []
    while cursor <= end_date:
        values.append(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return values


def main() -> None:
    s2_root = STORAGE / "rasters" / "sentinel2_monthly_30m_cdse"
    expected_s2 = expected_months("2022-01", "2026-08")
    raster_errors = []
    month_rows = []
    for month in expected_s2:
        folder = s2_root / month
        files = sorted(folder.glob("*.tif")) if folder.exists() else []
        shapes, crs_values = set(), set()
        for path in files:
            try:
                with rasterio.open(path) as dataset:
                    shapes.add((dataset.count, dataset.height, dataset.width))
                    crs_values.add(str(dataset.crs))
            except Exception as exc:
                raster_errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        month_rows.append({"month": month, "file_count": len(files), "complete": len(files) == 11 and not any(item["path"].startswith(str(folder)) for item in raster_errors), "shapes": sorted(shapes), "crs": sorted(crs_values)})

    pdf_root = STORAGE / "raw" / "mee_surface_water_monthly"
    pdfs = sorted(pdf_root.glob("*.pdf"))
    bad_pdfs = []
    for path in pdfs:
        with path.open("rb") as handle:
            signature = handle.read(4)
        if path.stat().st_size == 0 or signature != b"%PDF":
            bad_pdfs.append(str(path))
    csv_path = STORAGE / "silver" / "mee_taihu_monthly" / "mee_taihu_monthly_2022_2026.csv"
    report_rows = []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            report_rows = list(csv.DictReader(handle))
    expected_reports = expected_months("2022-01", "2026-06")
    report_periods = {row.get("period") for row in report_rows if row.get("status", "").startswith("completed")}
    structured_fields = ["monitoring_point_count", "whole_lake_status", "main_exceedance_indicators", "tn_assessment", "trophic_assessment"]
    field_coverage = {field: sum(bool(row.get(field)) for row in report_rows) for field in structured_fields}

    result = {
        "audit_date": "2026-08-23",
        "sentinel2": {
            "expected_months": len(expected_s2),
            "complete_months": sum(row["complete"] for row in month_rows),
            "missing_or_incomplete_months": [row["month"] for row in month_rows if not row["complete"]],
            "raster_errors": raster_errors,
            "months": month_rows,
            "canonical_root": str(s2_root),
            "note": "Each complete month contains one 7-band Process API response, six lake-masked bands, and NDCI/MCI/FAI/NDWI.",
        },
        "mee_monthly_reports": {
            "expected_months": len(expected_reports),
            "raw_pdf_count": len(pdfs),
            "bad_pdfs": bad_pdfs,
            "structured_rows": len(report_rows),
            "missing_months": sorted(set(expected_reports) - report_periods),
            "field_coverage": field_coverage,
            "structured_csv": str(csv_path),
        },
        "realtime_station": {
            "status": "BLOCKED_POLICY_NO_DOCUMENTED_PUBLIC_EXPORT",
            "manifest": str(STORAGE / "reports" / "realtime_station_resolution_20260823.json"),
            "note": "No private Ajax reverse engineering, access-control bypass, or invented historical backfill was performed.",
        },
    }
    result["competition_ready"] = result["sentinel2"]["complete_months"] == len(expected_s2) and not result["mee_monthly_reports"]["missing_months"]
    output = STORAGE / "reports" / "competition_acquisition_audit_20260823.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "competition_ready": result["competition_ready"], "sentinel_complete": result["sentinel2"]["complete_months"], "reports": len(report_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
