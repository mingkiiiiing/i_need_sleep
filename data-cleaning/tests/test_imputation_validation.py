from __future__ import annotations

import csv
import json

from pipeline.imputation_validation import run_imputation_validation


def _write_fixture(path) -> None:
    fields = [
        "source_id", "station_id", "scene_id", "observed_at", "variable_code",
        "clean_value", "observed_value", "raw_value", "is_imputed", "quality_flags",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(24):
            timestamp = f"2026-01-01T{index:02d}:00:00+00:00"
            writer.writerow({
                "source_id": "fixture_station", "station_id": "S1", "scene_id": "",
                "observed_at": timestamp, "variable_code": "water_temperature",
                "clean_value": float(index), "observed_value": float(index), "raw_value": float(index),
                "is_imputed": "False", "quality_flags": "[]",
            })
            writer.writerow({
                "source_id": "fixture_station", "station_id": "S1", "scene_id": "",
                "observed_at": timestamp, "variable_code": "chlorophyll_a",
                "clean_value": float(index + 1), "observed_value": float(index + 1), "raw_value": float(index + 1),
                "is_imputed": "False", "quality_flags": "[]",
            })
        writer.writerow({
            "source_id": "remote", "station_id": "", "scene_id": "SCENE",
            "observed_at": "2026-01-01T00:00:00+00:00", "variable_code": "cloud_cover",
            "clean_value": 10.0, "observed_value": 10.0, "raw_value": 10.0,
            "is_imputed": "False", "quality_flags": "[]",
        })
        writer.writerow({
            "source_id": "remote", "station_id": "", "scene_id": "SCENE",
            "observed_at": "2026-01-01T01:00:00+00:00", "variable_code": "cloud_cover",
            "clean_value": 20.0, "observed_value": 20.0, "raw_value": 20.0,
            "is_imputed": "False", "quality_flags": "[]",
        })


def test_masked_validation_is_variable_specific_and_policy_explicit(tmp_path) -> None:
    input_path = tmp_path / "complete.csv"
    output_path = tmp_path / "validation.csv"
    summary_path = tmp_path / "summary.json"
    database = tmp_path / "validation.sqlite"
    _write_fixture(input_path)
    summary = run_imputation_validation(
        input_path, output_path, summary_path=summary_path, database=database,
        mask_rates=(0.10, 0.20), seed=7, min_series_length=10,
    )
    assert summary["status"] == "completed"
    rows = list(csv.DictReader(output_path.open("r", encoding="utf-8-sig", newline="")))
    assert len(rows) == 6
    water = [row for row in rows if row["variable_code"] == "water_temperature"]
    assert all(row["status"] == "evaluated" for row in water)
    assert all(float(row["coverage"]) > 0 for row in water)
    assert all(float(row["mae"]) == 0.0 for row in water)
    protected = [row for row in rows if row["variable_code"] == "chlorophyll_a"]
    assert all(row["status"] == "policy_blocked" for row in protected)
    short = [row for row in rows if row["variable_code"] == "cloud_cover"]
    assert all(row["status"] == "skipped_no_complete_series" for row in short)
    assert json.loads(summary_path.read_text(encoding="utf-8"))["result_rows"] == 6
