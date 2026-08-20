from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from pipeline.normalize import normalize_open_meteo_payload
from pipeline.time_contract import parse_time
from pipeline.clean import _write_sqlite


ROOT = Path(__file__).resolve().parents[1]


def test_aware_timestamp_stores_utc_and_asia_shanghai() -> None:
    parsed = parse_time("2026-08-18T00:00:00+08:00")
    assert parsed["status"] == "accepted"
    assert parsed["utc"] == "2026-08-17T16:00:00+00:00"
    assert parsed["local"] == "2026-08-18T00:00:00+08:00"


def test_naive_timestamp_is_pending_without_explicit_source_timezone() -> None:
    parsed = parse_time("2026-08-18T00:00:00")
    assert parsed["status"] == "pending_timezone"
    assert parsed["utc"] is None
    assert parsed["local"] is None


def test_naive_timestamp_is_accepted_only_with_explicit_timezone() -> None:
    parsed = parse_time("2026-08-18T00:00:00", source_timezone="Asia/Shanghai")
    assert parsed["status"] == "accepted"
    assert parsed["utc"] == "2026-08-17T16:00:00+00:00"
    assert parsed["source_timezone"] == "Asia/Shanghai"


def test_forecast_payload_keeps_reference_context_and_rejects_missing_timezone() -> None:
    payload = {
        "longitude": 120.3,
        "latitude": 31.2,
        "timezone": "Asia/Shanghai",
        "hourly_units": {"temperature_2m": "°C"},
        "hourly": {
            "time": ["2026-08-18T00:00"],
            "temperature_2m": [28.0],
            "wind_speed_10m": [2.0],
            "wind_direction_10m": [180],
            "precipitation": [0.0],
            "shortwave_radiation": [0.0],
        },
    }
    rows = normalize_open_meteo_payload(Path("forecast.json"), {"payload": payload})
    row = rows[0]
    assert row["observed_at"] == "2026-08-17T16:00:00+00:00"
    assert row["observed_at_utc"] == row["observed_at"]
    assert row["observed_at_local"] == "2026-08-18T00:00:00+08:00"
    assert row["time_status"] == "accepted"
    assert row["source_timezone"] == "Asia/Shanghai"

    payload.pop("timezone")
    pending_rows = normalize_open_meteo_payload(Path("forecast.json"), {"payload": payload})
    assert pending_rows[0]["observed_at"] is None
    assert pending_rows[0]["time_status"] == "pending_timezone"


def test_variable_dictionary_declares_forecast_reference_and_valid_time_separately() -> None:
    config = yaml.safe_load((ROOT / "config" / "variables.yml").read_text(encoding="utf-8"))
    contract = config["time_contract"]
    codes = {item["code"] for item in config["variables"]}
    assert contract["storage_timezone"] == "UTC"
    assert contract["local_timezone"] == "Asia/Shanghai"
    assert contract["naive_input_policy"] == "pending_timezone"
    assert {"forecast_reference_time", "valid_time", "forecast_reference_time_local", "valid_time_local"}.issubset(codes)


def test_cleaned_sqlite_retains_utc_local_and_time_status_fields(tmp_path: Path) -> None:
    database = tmp_path / "clean.db"
    row = {
        "source_id": "time_fixture",
        "source_file": "fixture.csv",
        "source_row": "1",
        "station_id": "S1",
        "scene_id": None,
        "observed_at": "2026-08-17T16:00:00+00:00",
        "observed_at_utc": "2026-08-17T16:00:00+00:00",
        "observed_at_local": "2026-08-18T00:00:00+08:00",
        "time_status": "accepted",
        "source_timezone": "Asia/Shanghai",
        "longitude": 120.3,
        "latitude": 31.2,
        "variable_code": "water_temperature",
        "source_parameter": "water_temperature",
        "observed_value": 28.0,
        "clean_value": 28.0,
        "unit": "degC",
        "source_unit": "degC",
        "value_origin": "observed",
        "conversion_rule": None,
        "is_imputed": False,
        "imputation_method": None,
        "imputation_confidence": None,
        "quality_flags": [],
    }
    _write_sqlite(database, [row], [], [], [], [], [])
    with sqlite3.connect(database) as connection:
        columns = {item[1] for item in connection.execute("PRAGMA table_info(cleaned_observations)")}
        values = connection.execute("SELECT observed_at_utc, observed_at_local, time_status, source_timezone FROM cleaned_observations").fetchone()
    assert {"observed_at_utc", "observed_at_local", "time_status", "source_timezone"}.issubset(columns)
    assert values == (row["observed_at_utc"], row["observed_at_local"], row["time_status"], row["source_timezone"])
