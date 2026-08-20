from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from pipeline.clean import run_cleaning
from pipeline.qc import RULES_VERSION, quality_control


def _row(variable: str, value: object, *, unit: str = "degC") -> dict[str, object]:
    return {
        "source_id": "range_fixture",
        "source_file": "fixture.csv",
        "source_row": "1",
        "station_id": "S1",
        "observed_at": "2026-08-18T00:00:00+00:00",
        "variable_code": variable,
        "observed_value": value,
        "raw_value": value,
        "clean_value": value,
        "unit": unit,
        "raw_unit": unit,
        "quality_flags": [],
    }


def test_hard_range_is_rejected_and_soft_range_is_suspect() -> None:
    result = quality_control([
        _row("wind_speed", 80, unit="m/s"),
        _row("water_temperature", 50),
    ])

    assert result["rules_version"] == RULES_VERSION == "1.0.0"
    assert len(result["rejected"]) == 1
    assert "Q04" in result["rejected"][0]["quality_flags"]
    assert len(result["suspect"]) == 1
    assert result["suspect"][0]["variable_code"] == "water_temperature"
    assert "Q12" in result["suspect"][0]["quality_flags"]
    assert len(result["cleaned"]) == 0
    assert result["suspect"][0]["raw_value"] == 50


def test_soft_range_does_not_delete_source_value() -> None:
    row = _row("total_phosphorus", 25, unit="mg/L")
    result = quality_control([row])
    assert result["rejected"] == []
    assert result["suspect"][0]["raw_value"] == 25
    assert result["suspect"][0]["clean_value"] == 25
    assert result["issues"][0]["issue_code"] == "Q12"
    assert result["issues"][0]["raw_unit"] == "mg/L"


def test_cleaning_exports_suspect_records_and_sqlite_table(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "station"
    raw_root.mkdir(parents=True)
    source = raw_root / "range.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["observed_at", "station_id", "variable_code", "value", "unit"])
        writer.writeheader()
        writer.writerow({"observed_at": "2026-08-18T00:00:00Z", "station_id": "S1", "variable_code": "water_temperature", "value": "50", "unit": "degC"})
    output = tmp_path / "out"
    result = run_cleaning(raw_root.parent, output, tmp_path / "qc.db", run_id="physical_range_fixture")
    assert result["suspect_rows"] == 1
    assert Path(result["files"]["suspect_records"]).exists()
    with sqlite3.connect(tmp_path / "qc.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM suspect_records").fetchone()[0] == 1

