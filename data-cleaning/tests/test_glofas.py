from __future__ import annotations

import json
from pathlib import Path

from pipeline.sources.glofas import (
    DEFAULT_AREA,
    DATASET,
    aggregate_glofas_ensemble,
    build_glofas_request,
    parse_glofas_tabular,
    run_glofas,
)


CSV = (
    "forecast_reference_time,valid_time,latitude,longitude,ensemble_member,variable,value,unit\n"
    "2026-08-19T00:00:00Z,2026-08-20T00:00:00Z,31.1,120.2,1,river_discharge_in_the_last_24_hours,10,m3/s\n"
    "2026-08-19T00:00:00Z,2026-08-20T00:00:00Z,31.1,120.2,2,river_discharge_in_the_last_24_hours,14,m3/s\n"
    "2026-08-19T00:00:00Z,2026-08-20T00:00:00Z,31.1,120.2,3,river_discharge_in_the_last_24_hours,12,m3/s\n"
    "2026-08-19T00:00:00Z,2026-08-20T00:00:00Z,31.1,120.2,1,runoff,2,mm\n"
)


def test_request_matches_official_ewds_glofas_shape():
    request = build_glofas_request("2026-08-19", lead_hours=[24, 48])
    assert DATASET == "cems-glofas-forecast"
    assert request["system_version"] == "operational"
    assert request["hydrological_model"] == "lisflood"
    assert request["product_type"] == "control_forecast"
    assert request["variable"] == "river_discharge_in_the_last_24_hours"
    assert request["leadtime_hour"] == ["24", "48"]
    assert request["area"] == list(DEFAULT_AREA)
    assert request["data_format"] == "grib2"
    assert request["download_format"] == "zip"


def test_tabular_parser_and_ensemble_summary_keep_proxy_flag():
    # Use a temporary export through the public file parser.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "glofas.csv"
        path.write_text(CSV, encoding="utf-8")
        parsed = parse_glofas_tabular(path)
    assert parsed["record_count"] == 4
    assert all(row["proxy_flag"] == 1 for row in parsed["rows"])
    assert all(row["value_origin"] == "forecast_proxy" for row in parsed["rows"])
    summary = aggregate_glofas_ensemble(parsed["rows"])
    discharge = next(row for row in summary if row["variable_code"] == "river_discharge")
    assert discharge["ensemble_count"] == 3
    assert discharge["ensemble_mean"] == 12.0
    assert discharge["ensemble_p10"] == 10.0
    assert discharge["ensemble_p90"] == 14.0
    assert discharge["proxy_flag"] == 1


def test_no_credentials_stops_at_official_request_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("TAIHU_CDS_API_KEY", raising=False)
    result = run_glofas(run_date="2026-08-19", manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["data_truth"] == "official_request_plan_only"
    assert result["request"]["area"] == list(DEFAULT_AREA)
    assert result["records"] == 0
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["proxy_flag_policy"] == 1


def test_authorized_local_export_writes_proxy_values_and_stats(tmp_path):
    input_path = tmp_path / "glofas.csv"
    input_path.write_text(CSV, encoding="utf-8")
    evidence = tmp_path / "ewds_terms.txt"
    evidence.write_text("authorized EWDS export terms record", encoding="utf-8")
    result = run_glofas(
        run_date="2026-08-19",
        input_path=input_path,
        output_root=tmp_path / "silver",
        raw_root=tmp_path / "raw",
        manifest_path=tmp_path / "manifest.json",
        authorization_evidence_path=evidence,
    )
    assert result["status"] == "completed"
    assert result["records"] == 4
    assert result["ensemble_summary_records"] == 2
    assert result["proxy_values_csv"]
    assert result["ensemble_stats_csv"]
    assert "forecast_proxy" in (tmp_path / "silver" / Path(result["proxy_values_csv"]).name).read_text(encoding="utf-8-sig")
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["proxy_flag_policy"] == 1
