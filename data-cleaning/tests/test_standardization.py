from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pipeline.normalize import standardize_observation_rows
from pipeline.sources.local_files import normalize_local_file


def test_standardization_preserves_raw_pair_and_applies_explicit_unit_time_contract(tmp_path: Path) -> None:
    rows = [{
        "source_id": "station_export",
        "source_file": "station.csv",
        "source_row": "2",
        "station_id": "S-01",
        "observed_at": "2026-08-18 08:00:00",
        "source_timezone": "Asia/Shanghai",
        "longitude": "120.30",
        "latitude": "31.20",
        "variable_code": "chlorophyll_a",
        "observed_value": "2.5",
        "clean_value": "2.5",
        "unit": "mg/m³",
        "source_unit": "mg/m³",
        "value_origin": "observed",
    }]

    result = standardize_observation_rows(rows)
    row = result["records"][0]
    assert row["raw_value"] == "2.5"
    assert row["raw_unit"] == "mg/m³"
    assert row["unit"] == "ug/L"
    assert row["clean_value"] == pytest.approx(2.5)
    assert row["observed_at_utc"] == "2026-08-18T00:00:00+00:00"
    assert row["time_status"] == "accepted"
    assert row["longitude"] == pytest.approx(120.30)
    assert row["latitude"] == pytest.approx(31.20)
    assert row["coordinate_status"] == "accepted"
    assert row["station_mapping_status"] == "identity"


def test_standardization_keeps_naive_time_pending_without_timezone() -> None:
    row = {
        "source_id": "fixture",
        "source_file": "x.csv",
        "source_row": "2",
        "station_id": "S1",
        "observed_at": "2026-08-18 08:00:00",
        "variable_code": "water_temperature",
        "observed_value": 25,
        "clean_value": 25,
        "unit": "degC",
        "source_unit": "degC",
    }
    standardize_observation_rows([row])
    assert row["time_status"] == "pending_timezone"
    assert row["observed_at_utc"] is None


def test_standardization_uses_explicit_station_master_and_fills_coordinates(tmp_path: Path) -> None:
    mapping = tmp_path / "stations.csv"
    with mapping.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source_station_id", "station_id", "station_name", "longitude", "latitude"])
        writer.writeheader()
        writer.writerow({"source_station_id": "旧站A", "station_id": "TAI-001", "station_name": "湖心", "longitude": "120.4", "latitude": "31.3"})
    row = {
        "source_id": "station",
        "source_file": "x.csv",
        "source_row": "2",
        "station_id": "旧站A",
        "station_name": "旧站A",
        "observed_at": "2026-08-18T00:00:00Z",
        "variable_code": "water_temperature",
        "observed_value": 25,
        "clean_value": 25,
        "unit": "degC",
        "source_unit": "degC",
    }
    result = standardize_observation_rows([row], station_mapping_path=mapping)
    mapped = result["records"][0]
    assert mapped["station_id"] == "TAI-001"
    assert mapped["station_mapping_status"] == "mapped"
    assert mapped["longitude"] == pytest.approx(120.4)
    assert mapped["latitude"] == pytest.approx(31.3)
    assert result["station_mapping_count"] == 1


def test_local_file_normalization_retains_raw_unit_and_explicit_timezone(tmp_path: Path) -> None:
    source = tmp_path / "water.csv"
    source.write_text(
        "time,station_code,variable,value,unit,source_timezone\n"
        "2026-08-18 08:00:00,S1,TN,1.2,mg/L,Asia/Shanghai\n",
        encoding="utf-8",
    )
    result = normalize_local_file(source)
    row = result["observations"][0]
    assert row["variable_code"] == "total_nitrogen"
    assert row["raw_value"] == "1.2"
    assert row["raw_unit"] == "mg/L"
    assert row["time_status"] == "accepted"
    assert row["observed_at_utc"] == "2026-08-18T00:00:00+00:00"

