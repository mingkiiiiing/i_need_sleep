from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline.sources.hydrology_consistency import run_hydrology_consistency


def _write_input(path: Path) -> None:
    rows = [
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-01T00:00:00Z", "variable_code": "water_level", "clean_value": 1.0, "unit": "m", "value_origin": "observed"},
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "water_level", "clean_value": 1.5, "unit": "m", "value_origin": "observed"},
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-01T00:00:00Z", "variable_code": "precipitation", "clean_value": 0.0, "unit": "mm", "value_origin": "observed"},
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "precipitation", "clean_value": 100.0, "unit": "mm", "value_origin": "observed"},
        {"source_id": "mwr_hfc", "station_id": "S1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "water_level", "clean_value": 150.0, "unit": "cm", "value_origin": "web_snapshot"},
        {"source_id": "glofas_forecast", "station_id": "grid_1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "discharge", "clean_value": 12.0, "unit": "m3/s", "value_origin": "forecast_proxy"},
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "inflow_discharge", "clean_value": 2.0, "unit": "m3/s", "value_origin": "observed"},
        {"source_id": "taihu_thqbca_history", "station_id": "S1", "observed_at": "2020-01-02T00:00:00Z", "variable_code": "outflow_discharge", "clean_value": 3.0, "unit": "m3/s", "value_origin": "observed"},
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def test_missing_input_returns_blocked_data(tmp_path):
    result = run_hydrology_consistency(input_paths=[tmp_path / "missing.csv"], manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_DATA"
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["status"] == "BLOCKED_DATA"


def test_consistency_checks_keep_observed_web_and_proxy_separate(tmp_path):
    input_path = tmp_path / "hydrology.csv"
    output = tmp_path / "hydrology_consistency.csv"
    report = tmp_path / "report.json"
    _write_input(input_path)
    result = run_hydrology_consistency(input_paths=[input_path], output_csv=output, report_path=report, manifest_path=tmp_path / "manifest.json", jump_threshold_m_per_day=0.3)
    assert result["status"] == "completed"
    frame = pd.read_csv(output)
    observations = frame[frame["check_type"] == "observation"]
    assert observations.loc[observations["source_id"] == "taihu_thqbca_history", "observed_value"].notna().any()
    assert observations.loc[observations["source_id"] == "mwr_hfc", "web_value"].notna().all()
    assert observations.loc[observations["source_id"] == "glofas_forecast", "proxy_value"].notna().all()
    assert observations.loc[observations["source_id"] == "glofas_forecast", "proxy_flag"].eq(1).all()
    assert observations.loc[observations["variable_code"] == "water_level", "water_level_jump_flag"].fillna(False).astype(bool).any()
    assert int(result["checks"]["flow_sign"]["sign_flags"]) == 1
    assert json.loads(report.read_text(encoding="utf-8"))["proxy_policy"].startswith("GloFAS")


def test_unit_conversion_and_unavailable_source_inventory(tmp_path):
    input_path = tmp_path / "hydrology.csv"
    _write_input(input_path)
    result = run_hydrology_consistency(input_paths=[input_path], output_csv=tmp_path / "out.csv", report_path=tmp_path / "report.json", manifest_path=tmp_path / "manifest.json")
    frame = pd.read_csv(tmp_path / "out.csv")
    web = frame[(frame["check_type"] == "observation") & (frame["source_id"] == "mwr_hfc")].iloc[0]
    assert web["canonical_value"] == 1.5
    inventory = frame[frame["check_type"] == "source_availability"]
    assert inventory.loc[inventory["source_id"] == "tba_current_level", "source_status"].iloc[0] == "BLOCKED_POLICY"
    assert inventory.loc[inventory["source_id"] == "glofas_forecast", "source_status"].iloc[0] == "BLOCKED_AUTH"
