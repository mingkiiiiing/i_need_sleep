from __future__ import annotations

from pipeline.qc import quality_control


def _row(time: str, value: float, row_no: int, variable: str = "water_temperature") -> dict[str, object]:
    return {
        "source_id": "univariate_fixture",
        "source_file": "univariate.csv",
        "source_row": str(row_no),
        "station_id": "S1",
        "scene_id": None,
        "observed_at": time,
        "variable_code": variable,
        "observed_value": value,
        "raw_value": value,
        "clean_value": value,
        "unit": "degC",
        "raw_unit": "degC",
        "quality_flags": [],
    }


def test_hampel_mad_outlier_is_suspect_and_retained() -> None:
    rows = [_row(f"2026-08-18T0{i}:00:00Z", value, i + 1, variable="water_level") for i, value in enumerate([10, 10, 10, 100, 10, 10, 10])]
    result = quality_control(rows, hampel_radius=2, hampel_min_points=5, max_rate_per_hour={})
    assert result["univariate_issue_counts"]["Q18"] == 1
    assert result["rejected"] == []
    assert len(result["suspect"]) == 1
    assert result["suspect"][0]["source_row"] == "4"
    assert result["suspect"][0]["raw_value"] == 100


def test_rate_of_change_is_suspect_and_not_deleted() -> None:
    result = quality_control([
        _row("2026-08-18T00:00:00Z", 20, 1),
        _row("2026-08-18T01:00:00Z", 30, 2),
    ], max_rate_per_hour={"water_temperature": 5.0})
    assert result["univariate_issue_counts"]["Q19"] == 1
    assert result["rejected"] == []
    assert len(result["suspect"]) == 1
    assert result["suspect"][0]["source_row"] == "2"
