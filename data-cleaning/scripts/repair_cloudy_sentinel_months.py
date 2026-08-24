from __future__ import annotations

import calendar
import json
import shutil
from datetime import date
from pathlib import Path

from pipeline.sources.sentinel2_process_monthly import run_cdse_monthly

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "storage" / "manifests" / "sentinel2_monthly_2022_2026_cdse.json"
RASTER_ROOT = ROOT / "storage" / "rasters" / "sentinel2_monthly_30m_cdse"


def main() -> None:
    manifest = json.loads(CANONICAL.read_text(encoding="utf-8"))
    targets = manifest["clear_lake_fraction"]["below_0_50_months"]
    for period in targets:
        year, month = map(int, period.split("-"))
        folder = RASTER_ROOT / period
        backup = folder / "exact_day_backup"
        backup.mkdir(parents=True, exist_ok=True)
        for path in folder.glob("*.tif"):
            target = backup / path.name
            if not target.exists():
                shutil.copy2(path, target)
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        result = run_cdse_monthly(
            start,
            end,
            manifest_path=ROOT / "storage" / "manifests" / f"sentinel2_cdse_repair_{period}.json",
            monthly_composite=True,
            force=True,
        )
        row = result["months"][0]
        print(period, row["status"], row.get("clear_lake_fraction"), flush=True)


if __name__ == "__main__":
    main()
