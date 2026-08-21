from __future__ import annotations

import csv
import sqlite3

from pipeline.forecast_failover import evaluate_forecast_candidates, load_forecast_priority, run_forecast_failover


FIELDS = ["source_id", "model_name", "forecast_reference_time", "valid_time", "lead_hours", "variable_code", "value", "unit"]


def _write_csv(path, source_id, model_name, max_lead=72.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "source_id": source_id,
            "model_name": model_name,
            "forecast_reference_time": "2026-08-18T18:00:00Z",
            "valid_time": "2026-08-21T18:00:00Z",
            "lead_hours": str(max_lead),
            "variable_code": "air_temperature",
            "value": "25.0",
            "unit": "degC",
        }
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_priority_config_orders_ecmwf_gfs_then_development_fallback():
    config = load_forecast_priority()
    assert [item["source_id"] for item in config["sources"]] == ["ecmwf_open_ifs_aifs", "noaa_gfs", "open_meteo_forecast"]
    assert config["sources"][0]["model_name"] == "ECMWF"
    assert config["sources"][1]["model_name"] == "NOAA_GFS"


def test_primary_ecmwf_is_selected_without_mixing(tmp_path):
    ecmwf = tmp_path / "ecmwf.csv"
    gfs = tmp_path / "gfs.csv"
    _write_csv(ecmwf, "ecmwf_open_ifs_aifs", "ECMWF")
    _write_csv(gfs, "noaa_gfs", "NOAA_GFS")
    result = evaluate_forecast_candidates(
        {"ecmwf_open_ifs_aifs": ecmwf, "noaa_gfs": gfs},
        health_database=tmp_path / "health.sqlite",
        run_id="primary-test", checked_at_utc="2026-08-19T00:00:00Z",
    )
    assert result["status"] == "selected"
    assert result["selected"]["source_id"] == "ecmwf_open_ifs_aifs"
    assert result["selected"]["model_name"] == "ECMWF"
    assert {row["source_id"] for row in result["rows"]} == {"ecmwf_open_ifs_aifs"}
    assert {row["model_name"] for row in result["rows"]} == {"ECMWF"}
    with sqlite3.connect(tmp_path / "health.sqlite") as connection:
        assert connection.execute("SELECT selected_source_id, selection_reason FROM forecast_source_switches").fetchone() == ("ecmwf_open_ifs_aifs", "primary_selected")


def test_gfs_is_selected_and_switch_is_logged_when_ecmwf_missing(tmp_path):
    gfs = tmp_path / "gfs.csv"
    _write_csv(gfs, "noaa_gfs", "NOAA_GFS")
    health = tmp_path / "health.sqlite"
    result = evaluate_forecast_candidates(
        {"ecmwf_open_ifs_aifs": tmp_path / "missing.csv", "noaa_gfs": gfs},
        health_database=health, run_id="fallback-test", checked_at_utc="2026-08-19T00:00:00Z",
    )
    assert result["status"] == "selected"
    assert result["selected"]["source_id"] == "noaa_gfs"
    assert result["selection_reason"] == "primary_unavailable_fallback_selected"
    assert result["switch"]["fallback_from_source_id"] == "ecmwf_open_ifs_aifs"
    assert {row["model_name"] for row in result["rows"]} == {"NOAA_GFS"}
    with sqlite3.connect(health) as connection:
        rows = connection.execute("SELECT source_id, status FROM source_health ORDER BY source_id").fetchall()
        assert rows == [("ecmwf_open_ifs_aifs", "failed"), ("noaa_gfs", "success")]


def test_production_does_not_select_open_meteo_development_fallback(tmp_path):
    result = evaluate_forecast_candidates(
        {"open_meteo_forecast": tmp_path / "missing.csv"},
        environment="production", health_database=tmp_path / "health.sqlite",
        run_id="production-no-proxy", checked_at_utc="2026-08-19T00:00:00Z",
    )
    assert result["status"] == "no_source"
    open_meteo = next(item for item in result["candidates"] if item["source_id"] == "open_meteo_forecast")
    assert open_meteo["reason"] == "not_allowed_in_production"


def test_cli_service_writes_selected_output_and_manifest(tmp_path):
    ecmwf = tmp_path / "ecmwf.csv"
    _write_csv(ecmwf, "ecmwf_open_ifs_aifs", "ECMWF")
    result = run_forecast_failover(
        {"ecmwf_open_ifs_aifs": ecmwf},
        output=tmp_path / "selected.csv", health_database=tmp_path / "health.sqlite",
        manifest_path=tmp_path / "manifest.json", run_id="cli-test", checked_at_utc="2026-08-19T00:00:00Z",
    )
    assert result["status"] == "completed"
    assert result["selected_output"] == str(tmp_path / "selected.csv")
    assert (tmp_path / "manifest.json").exists()
