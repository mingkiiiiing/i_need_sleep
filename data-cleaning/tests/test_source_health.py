import sqlite3

from pipeline.source_health import update_source_health


def test_source_health_records_success_metrics_and_authorization(tmp_path):
    database = tmp_path / "health.db"
    result = update_source_health(
        database,
        source_id="nasa_power_hourly",
        run_id="run-001",
        success=True,
        checked_at_utc="2026-08-19T00:00:00Z",
        latest_observed_at_utc="2026-08-18T23:00:00Z",
        row_count=120,
        expected_fields=["air_temperature", "wind_speed", "precipitation"],
        actual_fields=["air_temperature", "wind_speed"],
        missing_values=6,
        total_values=120,
        authorization_status="public_api",
    )
    assert result["status"] == "success"
    assert result["success_rate"] == 1.0
    assert result["freshness_status"] == "fresh"
    assert result["field_coverage"] == 2 / 3
    assert result["missing_rate"] == 0.05
    assert result["authorization_status"] == "public_api"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_health").fetchone() == (1,)


def test_source_health_tracks_failures_and_freshness(tmp_path):
    database = tmp_path / "health.db"
    update_source_health(
        database,
        source_id="source_a",
        run_id="run-001",
        success=True,
        checked_at_utc="2026-08-19T00:00:00Z",
        latest_observed_at_utc="2026-08-19T00:00:00Z",
    )
    failed = update_source_health(
        database,
        source_id="source_a",
        run_id="run-002",
        success=False,
        checked_at_utc="2026-08-19T01:00:00Z",
        latest_observed_at_utc="2026-08-10T00:00:00Z",
        error_message="HTTP 503",
    )
    failed_again = update_source_health(
        database,
        source_id="source_a",
        run_id="run-003",
        success=False,
        checked_at_utc="2026-08-19T02:00:00Z",
    )
    assert failed["success_rate"] == 0.5
    assert failed["consecutive_failures"] == 1
    assert failed["freshness_status"] == "stale"
    assert failed_again["success_rate"] == 1 / 3
    assert failed_again["consecutive_failures"] == 2
    assert failed_again["freshness_status"] == "missing"


def test_same_run_update_is_idempotent(tmp_path):
    database = tmp_path / "health.db"
    update_source_health(
        database,
        source_id="source_b",
        run_id="run-001",
        success=True,
        checked_at_utc="2026-08-19T00:00:00Z",
    )
    second = update_source_health(
        database,
        source_id="source_b",
        run_id="run-001",
        success=False,
        checked_at_utc="2026-08-19T00:05:00Z",
        error_message="reprocessed",
    )
    assert second["success_rate"] == 0.0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_health").fetchone() == (1,)
