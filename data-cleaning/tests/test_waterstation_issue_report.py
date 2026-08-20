from __future__ import annotations

import csv
from pathlib import Path

from pipeline.waterstation_issue_report import run_water_station_issue_report
from pipeline.waterstation_preflight import run_water_station_preflight


def _write_station_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["observed_at", "station_id", "variable_code", "value", "unit", "longitude", "latitude"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_empty_preflight_returns_explicit_authorization_gap(tmp_path):
    input_root = tmp_path / "inbox"
    input_root.mkdir()
    preflight_root = tmp_path / "preflight"
    run_water_station_preflight(input_root, preflight_root)
    result = run_water_station_issue_report(
        preflight_root,
        input_root=input_root,
        output_path=tmp_path / "issues.csv",
        summary_path=tmp_path / "summary.json",
    )
    assert result["status"] == "blocked"
    assert result["summary"]["issue_counts"]["authorization_gap"] == 1
    rows = list(csv.DictReader((tmp_path / "issues.csv").open(encoding="utf-8-sig", newline="")))
    assert rows[0]["field"] == "authorization"
    assert rows[0]["input_path"]


def test_issue_report_locates_time_unit_coordinate_and_station_errors(tmp_path):
    input_root = tmp_path / "inbox"
    station_file = input_root / "bad.csv"
    _write_station_csv(
        station_file,
        [
            {"observed_at": "not-a-time", "station_id": "", "variable_code": "water_temperature", "value": "20", "unit": "mg/L", "longitude": "200", "latitude": "91"},
            {"observed_at": "2026-08-19T00:00:00+00:00", "station_id": "T01", "variable_code": "water_temperature", "value": "21", "unit": "mg/L", "longitude": "120.1", "latitude": "31.1"},
        ],
    )
    preflight_root = tmp_path / "preflight"
    run_water_station_preflight(input_root, preflight_root)
    result = run_water_station_issue_report(
        preflight_root,
        input_root=input_root,
        output_path=tmp_path / "issues.csv",
        summary_path=tmp_path / "summary.json",
    )
    assert result["status"] == "blocked"
    issue_types = {row["issue_type"] for row in result["issue_rows"]}
    assert {"missing_or_invalid_time", "missing_station_id", "unit_mismatch", "coordinate_error"} <= issue_types
    assert all(row["input_path"] and row["field"] for row in result["issue_rows"])


def test_ready_preflight_has_empty_issue_return(tmp_path):
    input_root = tmp_path / "inbox"
    station_file = input_root / "station.csv"
    rows = []
    for hour in (0, 6, 12):
        for variable, value, unit in (
            ("chlorophyll_a", "12", "ug/L"),
            ("water_temperature", "25", "degC"),
            ("total_nitrogen", "1.2", "mg/L"),
            ("total_phosphorus", "0.08", "mg/L"),
        ):
            rows.append({"observed_at": f"2026-08-18T{hour:02d}:00:00+00:00", "station_id": "T01", "variable_code": variable, "value": value, "unit": unit, "longitude": "", "latitude": ""})
    _write_station_csv(station_file, rows)
    preflight_root = tmp_path / "preflight"
    preflight = run_water_station_preflight(input_root, preflight_root)
    assert preflight["status"] == "ready"
    result = run_water_station_issue_report(
        preflight_root,
        input_root=input_root,
        output_path=tmp_path / "issues.csv",
        summary_path=tmp_path / "summary.json",
    )
    assert result["status"] == "ready"
    assert result["issue_rows"] == []
    assert (tmp_path / "issues.csv").read_text(encoding="utf-8-sig").splitlines() == [
        "issue_id,severity,gate,issue_type,input_path,source_row,station_id,variable_code,observed_at,field,value,message,impact,likely_cause,recommended_action,evidence_source"
    ]
