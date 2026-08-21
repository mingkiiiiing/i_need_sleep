from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from pipeline.forecast_assembly import assemble_forecast_values


def _write_input(path: Path) -> None:
    fields = ["source_id", "model_name", "station_id", "forecast_reference_time", "valid_time", "lead_hours", "ensemble_member", "variable_code", "value", "unit", "source_parameter", "raw_grib_path"]
    rows = []
    for member, temp_values, rain_values in ((0, (20.0, 22.0), (1.0, 2.0)), (1, (24.0, 26.0), (3.0, 4.0))):
        for lead, temperature, rainfall in ((0, temp_values[0], rain_values[0]), (12, temp_values[1], rain_values[1])):
            valid = f"2026-08-19T{lead:02d}:00:00+00:00" if lead < 24 else "2026-08-20T00:00:00+00:00"
            rows.extend([
                {"source_id": "ecmwf_open_ifs_aifs", "model_name": "ECMWF", "station_id": "TAIHU_AREA_MEAN", "forecast_reference_time": "2026-08-19T00:00:00+00:00", "valid_time": valid, "lead_hours": lead, "ensemble_member": member, "variable_code": "air_temperature", "value": temperature, "unit": "degC", "source_parameter": "2t", "raw_grib_path": "x.grib2"},
                {"source_id": "ecmwf_open_ifs_aifs", "model_name": "ECMWF", "station_id": "TAIHU_AREA_MEAN", "forecast_reference_time": "2026-08-19T00:00:00+00:00", "valid_time": valid, "lead_hours": lead, "ensemble_member": member, "variable_code": "precipitation", "value": rainfall, "unit": "mm", "source_parameter": "tp", "raw_grib_path": "x.grib2"},
            ])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_assembly_keeps_reference_valid_lead_and_member(tmp_path: Path) -> None:
    source = tmp_path / "area_mean.csv"
    _write_input(source)
    result = assemble_forecast_values(source, tmp_path / "silver", tmp_path / "forecast.sqlite")
    assert result["status"] == "completed"
    assert result["input_rows"] == 8
    assert result["max_lead_hours"] == 12
    assert result["ensemble_members"] == [0, 1]
    with sqlite3.connect(tmp_path / "forecast.sqlite") as connection:
        rows = connection.execute("SELECT reference_time_utc, valid_time_utc, lead_hours, ensemble_member FROM forecast_values ORDER BY valid_time_utc, ensemble_member").fetchall()
        assert len(rows) == 8
        assert all(reference <= valid for reference, valid, _, _ in rows)
        assert {row[3] for row in rows} == {0, 1}


def test_daily_summary_has_extrema_cumulative_and_member_percentiles(tmp_path: Path) -> None:
    source = tmp_path / "area_mean.csv"
    _write_input(source)
    result = assemble_forecast_values(source, tmp_path / "silver", tmp_path / "forecast.sqlite")
    with sqlite3.connect(result["database"]) as connection:
        rain = connection.execute("SELECT sample_count, ensemble_member_count, mean_value, max_value, min_value, cumulative_value, p05_value, p50_value, p95_value FROM forecast_daily_summary WHERE variable_code='precipitation'").fetchone()
    assert rain[0] == 4
    assert rain[1] == 2
    assert rain[2] == 2.5
    assert rain[3] == 4.0
    assert rain[4] == 1.0
    assert rain[5] == 6.0
    assert rain[6] < rain[7] < rain[8]


def test_lead_mismatch_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    _write_input(source)
    text = source.read_text(encoding="utf-8").replace(",12,", ",13,", 1)
    source.write_text(text, encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="lead_hours"):
        assemble_forecast_values(source, tmp_path / "silver", tmp_path / "forecast.sqlite")
