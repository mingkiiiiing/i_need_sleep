from __future__ import annotations

from datetime import datetime, timezone

from pipeline.qc import quality_control


def _row(time: str, value: float, *, row_no: int, variable: str = "water_temperature") -> dict[str, object]:
    return {
        "source_id": "temporal_fixture",
        "source_file": "temporal.csv",
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


def test_duplicate_and_out_of_order_timestamps_are_rejected() -> None:
    result = quality_control([
        _row("2026-08-18T00:00:00Z", 20, row_no=1),
        _row("2026-08-18T02:00:00Z", 21, row_no=2),
        _row("2026-08-18T01:00:00Z", 22, row_no=3),
        _row("2026-08-18T01:00:00Z", 23, row_no=4),
    ])
    assert result["temporal_issue_counts"]["Q14"] == 1
    assert result["temporal_issue_counts"]["Q13"] == 2
    assert len(result["rejected"]) == 2
    assert result["flag_counts"]["Q13"] == 2
    assert result["flag_counts"]["Q14"] == 1


def test_future_timestamp_is_rejected_against_explicit_as_of() -> None:
    result = quality_control(
        [_row("2026-08-19T00:00:00Z", 20, row_no=1)],
        as_of=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    assert result["temporal_issue_counts"] == {"Q15": 1}
    assert len(result["rejected"]) == 1
    assert "Q15" in result["rejected"][0]["quality_flags"]


def test_large_gap_is_suspect_not_deleted() -> None:
    result = quality_control([
        _row("2026-08-18T00:00:00Z", 20, row_no=1),
        _row("2026-08-19T00:00:00Z", 21, row_no=2),
    ], max_gap_hours=6)
    assert result["temporal_issue_counts"]["Q16"] == 1
    assert result["rejected"] == []
    assert len(result["suspect"]) == 1
    assert result["suspect"][0]["source_row"] == "2"
    assert result["suspect"][0]["record_status"] == "suspect"


def test_interval_jump_is_detected_against_series_median() -> None:
    result = quality_control([
        _row("2026-08-18T00:00:00Z", 20, row_no=1),
        _row("2026-08-18T01:00:00Z", 20.1, row_no=2),
        _row("2026-08-18T02:00:00Z", 20.2, row_no=3),
        _row("2026-08-18T12:00:00Z", 20.3, row_no=4),
    ])
    assert result["temporal_issue_counts"]["Q16"] == 1
    assert result["suspect"][0]["source_row"] == "4"


def test_regular_monthly_series_is_not_flagged_as_sensor_gap() -> None:
    result = quality_control([
        _row("2020-01-01T00:00:00Z", 1.0, row_no=1, variable="total_phosphorus"),
        _row("2020-02-01T00:00:00Z", 1.1, row_no=2, variable="total_phosphorus"),
        _row("2020-03-01T00:00:00Z", 1.2, row_no=3, variable="total_phosphorus"),
        _row("2020-04-01T00:00:00Z", 1.3, row_no=4, variable="total_phosphorus"),
        _row("2020-05-01T00:00:00Z", 1.4, row_no=5, variable="total_phosphorus"),
    ])
    assert result["temporal_issue_counts"].get("Q16", 0) == 0
    assert len(result["cleaned"]) == 5


def test_constant_sensor_run_is_suspect() -> None:
    rows = [_row(f"2026-08-18T0{i}:00:00Z", 20, row_no=i + 1) for i in range(4)]
    result = quality_control(rows, stuck_min_points=3)
    assert result["temporal_issue_counts"]["Q17"] == 4
    assert result["rejected"] == []
    assert len(result["suspect"]) == 4


def test_invalid_timestamp_is_hard_time_quality_issue() -> None:
    result = quality_control([_row("not-a-time", 20, row_no=1)])
    assert result["flag_counts"]["Q03"] == 1
    assert len(result["rejected"]) == 1
