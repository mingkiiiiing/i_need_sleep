from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from pipeline.clean import resolve_duplicates, run_cleaning


def _row(source_id: str, row_no: str, *, value: float, observed_at: str = "2026-08-18T00:00:00Z", variable: str = "water_temperature") -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_file": "fixture.csv",
        "source_row": row_no,
        "station_id": "S1",
        "scene_id": None,
        "observed_at": observed_at,
        "variable_code": variable,
        "observed_value": value,
        "raw_value": value,
        "clean_value": value,
        "unit": "degC",
        "raw_unit": "degC",
        "longitude": 120.3,
        "latitude": 31.2,
        "quality_flags": [],
    }


def test_exact_duplicates_are_collapsed_and_conflicts_are_pending() -> None:
    exact_a = _row("source_a", "1", value=20.0)
    exact_b = _row("source_a", "2", value=20.0)
    conflict_a = _row("source_a", "3", value=0.10, observed_at="2026-08-18T01:00:00Z", variable="total_phosphorus")
    conflict_b = _row("source_a", "4", value=0.20, observed_at="2026-08-18T01:00:00Z", variable="total_phosphorus")
    other_source = _row("source_b", "5", value=21.0)

    result = resolve_duplicates([exact_a, exact_b, conflict_a, conflict_b, other_source])

    assert len(result["records"]) == 2  # exact source_a row + independent source_b row
    assert result["exact_duplicates_removed"] == 1
    assert result["conflict_groups"] == 1
    assert len(result["pending_conflicts"]) == 2
    assert {row["source_id"] for row in result["records"]} == {"source_a", "source_b"}
    assert all(row["record_status"] == "pending_conflict" for row in result["pending_conflicts"])
    assert all("Q41" in row["quality_flags"] for row in result["pending_conflicts"])
    assert {row["action"] for row in result["duplicate_audit"]} == {"retained_first", "deduplicated_exact", "pending_conflict"}


def test_run_cleaning_exports_pending_conflicts_and_duplicate_audit(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "station"
    raw_root.mkdir(parents=True)
    source = raw_root / "conflicts.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["observed_at", "station_id", "variable_code", "value", "unit"])
        writer.writeheader()
        writer.writerow({"observed_at": "2026-08-18T00:00:00Z", "station_id": "S1", "variable_code": "water_temperature", "value": "20", "unit": "degC"})
        writer.writerow({"observed_at": "2026-08-18T00:00:00Z", "station_id": "S1", "variable_code": "water_temperature", "value": "20", "unit": "degC"})
        writer.writerow({"observed_at": "2026-08-18T01:00:00Z", "station_id": "S1", "variable_code": "total_phosphorus", "value": "0.10", "unit": "mg/L"})
        writer.writerow({"observed_at": "2026-08-18T01:00:00Z", "station_id": "S1", "variable_code": "total_phosphorus", "value": "0.20", "unit": "mg/L"})

    output = tmp_path / "out"
    result = run_cleaning(raw_root.parent, output, tmp_path / "dedup.db", run_id="dedup_fixture")

    assert result["exact_duplicates_removed"] == 1
    assert result["conflict_groups"] == 1
    assert result["pending_conflict_rows"] == 2
    assert result["rejected_rows"] == 0
    assert Path(result["files"]["pending_conflicts"]).exists()
    assert Path(result["files"]["duplicate_audit"]).exists()
    with sqlite3.connect(tmp_path / "dedup.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM pending_conflicts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM duplicate_audit WHERE action='deduplicated_exact'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM qc_issues WHERE issue_code='Q41'").fetchone()[0] == 2
