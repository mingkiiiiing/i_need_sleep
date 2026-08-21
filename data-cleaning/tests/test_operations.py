import os
from pathlib import Path

import pytest

from pipeline.operations import batch_lock, evaluate_health, retry_decision, run_historical_replay


def test_auth_is_not_retried_and_429_is():
    assert retry_decision(http_status=401)["classification"] == "auth_stop"
    assert retry_decision(http_status=401)["retry"] is False
    assert retry_decision(http_status=429, attempt=2)["delay_seconds"] == 4


def test_batch_lock_blocks_concurrent_writer(tmp_path: Path):
    with batch_lock(tmp_path, "source", "window"):
        with pytest.raises(RuntimeError):
            with batch_lock(tmp_path, "source", "window"):
                pass
    assert not list(tmp_path.glob("*.lock"))


def test_health_alerts_and_replay(tmp_path: Path):
    alerts = evaluate_health({"freshness_lag_hours": 5, "consecutive_failures": 3, "field_coverage": .5, "row_count": 0}, official_frequency_hours=2)
    assert set(alerts) == {"STALE_OR_MISSING", "REPEATED_FAILURE", "FIELD_COVERAGE_DROP", "EMPTY_RESPONSE"}
    result = run_historical_replay(tmp_path / "replay.json")
    assert result["stable_version_preserved_during_faults"]
    assert result["recovery_verified"]
