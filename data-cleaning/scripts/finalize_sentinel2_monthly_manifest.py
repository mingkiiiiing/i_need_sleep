from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = [
    ROOT / "storage" / "manifests" / "sentinel2_cdse_2022_2025_retry.json",
    ROOT / "storage" / "manifests" / "sentinel2_cdse_2026.json",
]
OUTPUT = ROOT / "storage" / "manifests" / "sentinel2_monthly_2022_2026_cdse.json"
RASTER_ROOT = ROOT / "storage" / "rasters" / "sentinel2_monthly_30m_cdse"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    sources = [json.loads(path.read_text(encoding="utf-8")) for path in MANIFESTS]
    by_month = {month["month"]: month for source in sources for month in source["months"]}
    repair_paths = sorted((ROOT / "storage" / "manifests").glob("sentinel2_cdse_repair_20??-??.json"))
    for path in repair_paths:
        repair = json.loads(path.read_text(encoding="utf-8"))
        for month in repair.get("months", []):
            if month.get("status") == "completed":
                by_month[month["month"]] = month
    months = [by_month[key] for key in sorted(by_month)]
    for month in months:
        folder = RASTER_ROOT / month["month"]
        month["derived_indices"] = {
            name: {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for name in ("NDCI", "MCI", "FAI", "NDWI")
            if (path := folder / f"taihu_s2_l2a_{month['month']}_{name}_30m.tif").exists()
        }
    files = list(RASTER_ROOT.glob("20??-??/*.tif"))
    clear = [float(month["clear_lake_fraction"]) for month in months if month.get("clear_lake_fraction") is not None]
    result = {
        "run_id": f"sentinel2_monthly_final_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed" if len(months) == 56 and all(month["status"] == "completed" and len(month["derived_indices"]) == 4 for month in months) else "completed_with_gaps",
        "source_id": "copernicus_sentinel2_l2a_cdse_process_api",
        "period": ["2022-01-01", "2026-08-23"],
        "month_count": len(months),
        "completed_months": sum(month["status"] == "completed" for month in months),
        "raster_file_count": len(files),
        "raster_bytes": sum(path.stat().st_size for path in files),
        "clear_lake_fraction": {
            "minimum": min(clear),
            "median": statistics.median(clear),
            "maximum": max(clear),
            "below_0_50_months": [month["month"] for month in months if float(month.get("clear_lake_fraction", 1)) < 0.5],
        },
        "grid": sources[0]["grid"],
        "bands": ["B03", "B04", "B05", "B08", "B11", "SCL"],
        "indices": ["NDCI", "MCI", "FAI", "NDWI"],
        "oauth_secret_recorded": False,
        "source_manifests": [str(path) for path in MANIFESTS + repair_paths],
        "canonical_root": str(RASTER_ROOT),
        "months": months,
        "license_note": "Contains modified Copernicus Sentinel data.",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT, result["status"], result["month_count"], result["raster_file_count"])


if __name__ == "__main__":
    main()
