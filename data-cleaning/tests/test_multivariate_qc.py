from __future__ import annotations

from pipeline.qc import quality_control


def _row(time: str, variable: str, value: float, row_no: int) -> dict[str, object]:
    return {
        "source_id": "multivariate_fixture",
        "source_file": "multivariate.csv",
        "source_row": str(row_no),
        "station_id": "S1",
        "scene_id": None,
        "depth_m": 0.5,
        "observed_at": time,
        "variable_code": variable,
        "observed_value": value,
        "raw_value": value,
        "clean_value": value,
        "quality_flags": [],
    }


def test_cross_variable_rules_mark_all_participants_without_rejection() -> None:
    time = "2026-08-18T12:00:00Z"
    rows = [
        _row(time, "water_temperature", 25.0, 1),
        _row(time, "dissolved_oxygen", 20.0, 2),
        _row(time, "conductivity", 100.0, 3),
        _row(time, "tds", 500.0, 4),
        _row(time, "total_nitrogen", 1.0, 5),
        _row(time, "ammonia_nitrogen", 0.8, 6),
        _row(time, "nitrate_nitrogen", 0.6, 7),
        _row(time, "precipitation", 80.0, 8),
        _row(time, "inflow_discharge", 0.0, 9),
        _row(time, "cloud_cover", 95.0, 10),
        _row(time, "shortwave_radiation", 800.0, 11),
    ]

    result = quality_control(rows, max_rate_per_hour={})

    assert result["rejected"] == []
    assert result["multivariate_issue_counts"] == {"Q25": 2, "Q26": 2, "Q27": 3, "Q28": 2, "Q29": 2}
    assert len(result["suspect"]) == len(rows)
    assert all(row["raw_value"] is not None for row in result["suspect"])
    assert all(any(flag in row["quality_flags"] for flag in ("Q25", "Q26", "Q27", "Q28", "Q29")) for row in result["suspect"])


def test_plausible_cross_variable_values_are_not_flagged() -> None:
    time = "2026-08-18T12:00:00Z"
    rows = [
        _row(time, "water_temperature", 25.0, 1),
        _row(time, "dissolved_oxygen", 8.0, 2),
        _row(time, "conductivity", 500.0, 3),
        _row(time, "tds", 250.0, 4),
        _row(time, "total_nitrogen", 2.0, 5),
        _row(time, "ammonia_nitrogen", 0.3, 6),
        _row(time, "nitrate_nitrogen", 0.4, 7),
        _row(time, "precipitation", 5.0, 8),
        _row(time, "inflow_discharge", 2.0, 9),
        _row(time, "cloud_cover", 20.0, 10),
        _row(time, "shortwave_radiation", 600.0, 11),
    ]

    result = quality_control(rows, max_rate_per_hour={})

    assert result["multivariate_issue_counts"] == {}
    assert result["suspect"] == []
    assert len(result["cleaned"]) == len(rows)
