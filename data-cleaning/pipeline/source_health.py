"""Source health persistence and metrics for every ingestion run."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


HEALTH_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    success_rate REAL NOT NULL,
    last_success_at_utc TEXT,
    latest_observed_at_utc TEXT,
    freshness_lag_hours REAL,
    freshness_status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    field_coverage REAL,
    field_coverage_json TEXT,
    missing_rate REAL,
    authorization_status TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    PRIMARY KEY(source_id, run_id)
)
"""

FORECAST_SWITCH_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS forecast_source_switches (
    switch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,
    environment TEXT NOT NULL,
    selected_source_id TEXT NOT NULL,
    selected_model_name TEXT NOT NULL,
    selected_rank INTEGER NOT NULL,
    selection_reason TEXT NOT NULL,
    fallback_from_source_id TEXT,
    candidate_status_json TEXT NOT NULL
)
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source health timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def ensure_source_health_table(connection: sqlite3.Connection) -> None:
    connection.execute(HEALTH_TABLE_SQL)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_health_checked ON source_health(source_id, checked_at_utc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_health_status ON source_health(status, freshness_status)"
    )


def ensure_forecast_switch_table(connection: sqlite3.Connection) -> None:
    """Create the auditable forecast-source failover log."""

    connection.execute(FORECAST_SWITCH_TABLE_SQL)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_forecast_switch_checked ON forecast_source_switches(checked_at_utc)"
    )


def record_forecast_source_switch(
    database: Path,
    *,
    run_id: str,
    environment: str,
    selected_source_id: str,
    selected_model_name: str,
    selected_rank: int,
    selection_reason: str,
    fallback_from_source_id: str | None,
    candidate_statuses: Iterable[dict[str, object]],
    checked_at_utc: str | None = None,
) -> dict[str, object]:
    """Persist one primary/backup selection without altering forecast rows."""

    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    checked = checked_at_utc or _utc_now()
    _parse_utc(checked)
    candidate_list = list(candidate_statuses)
    candidate_json = json.dumps(candidate_list, ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(database) as connection:
        ensure_source_health_table(connection)
        ensure_forecast_switch_table(connection)
        cursor = connection.execute(
            """
            INSERT INTO forecast_source_switches(
                run_id, checked_at_utc, environment, selected_source_id,
                selected_model_name, selected_rank, selection_reason,
                fallback_from_source_id, candidate_status_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, checked, environment, selected_source_id,
                selected_model_name, int(selected_rank), selection_reason,
                fallback_from_source_id, candidate_json,
            ),
        )
        connection.commit()
        switch_id = int(cursor.lastrowid)
    return {
        "switch_id": switch_id,
        "run_id": run_id,
        "checked_at_utc": checked,
        "environment": environment,
        "selected_source_id": selected_source_id,
        "selected_model_name": selected_model_name,
        "selected_rank": int(selected_rank),
        "selection_reason": selection_reason,
        "fallback_from_source_id": fallback_from_source_id,
        "candidate_statuses": candidate_list,
    }


def _field_coverage(expected_fields: Iterable[str] | None, actual_fields: Iterable[str] | None) -> tuple[float | None, str | None]:
    expected = sorted({str(item) for item in (expected_fields or []) if str(item)})
    actual = sorted({str(item) for item in (actual_fields or []) if str(item)})
    if not expected:
        return None, json.dumps({"expected": expected, "actual": actual, "missing": []}, ensure_ascii=False)
    missing = sorted(set(expected) - set(actual))
    return len(set(expected) & set(actual)) / len(expected), json.dumps(
        {"expected": expected, "actual": actual, "missing": missing}, ensure_ascii=False
    )


def update_source_health(
    database: Path,
    *,
    source_id: str,
    run_id: str,
    success: bool,
    checked_at_utc: str | None = None,
    latest_observed_at_utc: str | None = None,
    row_count: int = 0,
    expected_fields: Iterable[str] | None = None,
    actual_fields: Iterable[str] | None = None,
    missing_values: int = 0,
    total_values: int = 0,
    authorization_status: str = "unknown",
    freshness_threshold_hours: float = 72.0,
    error_message: str | None = None,
) -> dict[str, object]:
    """Insert or update one source/run health record and derived metrics."""

    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    checked = checked_at_utc or _utc_now()
    checked_dt = _parse_utc(checked)
    latest_dt = _parse_utc(latest_observed_at_utc) if latest_observed_at_utc else None
    freshness_lag = None if latest_dt is None else max(0.0, (checked_dt - latest_dt).total_seconds() / 3600.0)
    freshness_status = "missing" if freshness_lag is None else "fresh" if freshness_lag <= freshness_threshold_hours else "stale"
    coverage, coverage_json = _field_coverage(expected_fields, actual_fields)
    missing_rate = None if total_values <= 0 else max(0.0, min(1.0, float(missing_values) / float(total_values)))
    status = "success" if success else "failed"
    row_count = max(0, int(row_count))

    with sqlite3.connect(database) as connection:
        ensure_source_health_table(connection)
        previous = connection.execute(
            """
            SELECT status, consecutive_failures, last_success_at_utc
            FROM source_health
            WHERE source_id=? AND run_id<>?
            ORDER BY checked_at_utc DESC
            LIMIT 1
            """,
            (source_id, run_id),
        ).fetchone()
        totals = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(CASE WHEN status='success' THEN 1 ELSE 0 END), 0)
            FROM source_health WHERE source_id=? AND run_id<>?
            """,
            (source_id, run_id),
        ).fetchone()
        prior_total, prior_successes = int(totals[0]), int(totals[1])
        success_rate = (prior_successes + int(success)) / (prior_total + 1)
        if success:
            consecutive_failures = 0
            last_success = checked
        else:
            prior_failures = int(previous[1]) if previous and previous[0] == "failed" else 0
            consecutive_failures = prior_failures + 1
            last_success = previous[2] if previous else None
        connection.execute(
            """
            INSERT INTO source_health(
                source_id, run_id, checked_at_utc, status, success_rate,
                last_success_at_utc, latest_observed_at_utc, freshness_lag_hours,
                freshness_status, row_count, field_coverage, field_coverage_json,
                missing_rate, authorization_status, consecutive_failures, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, run_id) DO UPDATE SET
                checked_at_utc=excluded.checked_at_utc,
                status=excluded.status,
                success_rate=excluded.success_rate,
                last_success_at_utc=excluded.last_success_at_utc,
                latest_observed_at_utc=excluded.latest_observed_at_utc,
                freshness_lag_hours=excluded.freshness_lag_hours,
                freshness_status=excluded.freshness_status,
                row_count=excluded.row_count,
                field_coverage=excluded.field_coverage,
                field_coverage_json=excluded.field_coverage_json,
                missing_rate=excluded.missing_rate,
                authorization_status=excluded.authorization_status,
                consecutive_failures=excluded.consecutive_failures,
                error_message=excluded.error_message
            """,
            (
                source_id,
                run_id,
                checked,
                status,
                success_rate,
                last_success,
                latest_observed_at_utc,
                freshness_lag,
                freshness_status,
                row_count,
                coverage,
                coverage_json,
                missing_rate,
                authorization_status,
                consecutive_failures,
                error_message,
            ),
        )
        connection.commit()
    return {
        "source_id": source_id,
        "run_id": run_id,
        "status": status,
        "success_rate": success_rate,
        "last_success_at_utc": last_success,
        "latest_observed_at_utc": latest_observed_at_utc,
        "freshness_lag_hours": freshness_lag,
        "freshness_status": freshness_status,
        "row_count": row_count,
        "field_coverage": coverage,
        "missing_rate": missing_rate,
        "authorization_status": authorization_status,
        "consecutive_failures": consecutive_failures,
        "error_message": error_message,
    }
