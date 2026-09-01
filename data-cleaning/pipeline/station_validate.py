from __future__ import annotations

"""Quality gate for high-frequency Taihu water-station observations."""

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .provenance import manifest_root

from .units import standardize_units


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
TARGET_ALTERNATIVES = {"chlorophyll_a", "algae_density", "bloom_area_km2"}
REQUIRED_DRIVERS = {"water_temperature", "total_nitrogen", "total_phosphorus"}
UNIT_EXPECTED = {
    "chlorophyll_a": "ug/L",
    "algae_density": "cells/L",
    "bloom_area_km2": "km2",
    "water_temperature": "degC",
    "total_nitrogen": "mg/L",
    "total_phosphorus": "mg/L",
}
RANGES = {
    "chlorophyll_a": (0.0, 10000.0),
    "algae_density": (0.0, 1.0e12),
    "bloom_area_km2": (0.0, 2338.0),
    "water_temperature": (0.0, 45.0),
    "total_nitrogen": (0.0, 1000.0),
    "total_phosphorus": (0.0, 1000.0),
}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _time(row: dict[str, Any]) -> datetime | None:
    value = row.get("observed_at") or row.get("time_bucket") or row.get("target_time_bucket")
    if value in (None, "", "None", "null"):
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(UTC)


def _float(value: Any) -> float | None:
    if value in (None, "", "None", "null", "nan", "NaN"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _variable(row: dict[str, Any]) -> str:
    return str(row.get("variable_code") or row.get("target_variable_code") or "").strip()


def _station(row: dict[str, Any]) -> str:
    return str(row.get("station_id") or row.get("target_station_id") or "").strip()


def _value(row: dict[str, Any]) -> float | None:
    return _float(row.get("clean_value") if row.get("clean_value") not in (None, "") else row.get("observed_value"))


def _cadence(rows: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    series: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for row in rows:
        timestamp = _time(row)
        if timestamp is not None:
            series[(_station(row), _variable(row))].append(timestamp)
    intervals: list[float] = []
    for timestamps in series.values():
        ordered = sorted(set(timestamps))
        intervals.extend((right - left).total_seconds() / 3600.0 for left, right in zip(ordered, ordered[1:]))
    if not intervals:
        return None, None
    return median(intervals), max(intervals)


def validate_station_rows(rows: list[dict[str, Any]], *, max_median_interval_hours: float = 6.0, max_gap_hours: float = 24.0) -> dict[str, Any]:
    # Normalize configured units before applying the canonical unit gate. This
    # converts protocol Chl-a mg/L to the internal ug/L representation and
    # preserves source_unit/conversion_rule/Q21.
    standardized_all = standardize_units([dict(row) for row in rows])["records"]
    standardized = [row for row in standardized_all if _variable(row) in UNIT_EXPECTED]
    ignored_rows = len(standardized_all) - len(standardized)
    counts = Counter()
    issue_rows: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, row in enumerate(standardized, start=1):
        variable = _variable(row)
        timestamp = _time(row)
        station = _station(row)
        value = _value(row)
        issues: list[str] = []
        if variable not in UNIT_EXPECTED:
            issues.append("unsupported_variable")
        if timestamp is None:
            issues.append("missing_or_invalid_time")
        if not station:
            issues.append("missing_station_id")
        if value is None:
            issues.append("missing_or_invalid_value")
        expected_unit = UNIT_EXPECTED.get(variable)
        if expected_unit and str(row.get("unit") or "") != expected_unit:
            issues.append("unit_mismatch")
        if variable in RANGES and value is not None:
            low, high = RANGES[variable]
            if value < low or value > high:
                issues.append("out_of_range")
        key = (str(row.get("source_id") or ""), station, timestamp.isoformat() if timestamp else "", variable)
        if key in seen:
            issues.append("duplicate_key")
        seen.add(key)
        if issues:
            counts.update(issues)
            issue_rows.append(
                {
                    "source_file": row.get("source_file"),
                    "source_row": row.get("source_row") or str(index),
                    "station_id": station,
                    "variable_code": variable,
                    "observed_at": timestamp.isoformat() if timestamp else None,
                    "longitude": row.get("longitude"),
                    "latitude": row.get("latitude"),
                    "unit": row.get("unit"),
                    "observed_value": row.get("observed_value"),
                    "issues": ",".join(issues),
                    "quality_flags": json.dumps(row.get("quality_flags") or [], ensure_ascii=False),
                }
            )
        else:
            valid_rows.append(row)
    by_variable = Counter(_variable(row) for row in valid_rows)
    median_interval, max_gap = _cadence(valid_rows)
    target_present = bool(TARGET_ALTERNATIVES & set(by_variable))
    drivers_present = REQUIRED_DRIVERS <= set(by_variable)
    cadence_ready = median_interval is not None and median_interval <= max_median_interval_hours and max_gap <= max_gap_hours
    status = "ready" if target_present and drivers_present and cadence_ready and not issue_rows else "blocked_missing_target" if not target_present else "blocked_missing_drivers" if not drivers_present else "blocked_low_frequency" if not cadence_ready else "blocked_quality_issues"
    summary = {
        "input_rows": len(rows),
        "considered_rows": len(standardized),
        "ignored_non_p0_rows": ignored_rows,
        "valid_rows": len(valid_rows),
        "issue_rows": len(issue_rows),
        "issue_counts": dict(counts),
        "variable_counts": dict(by_variable),
        "target_present": target_present,
        "required_drivers_present": drivers_present,
        "median_interval_hours": median_interval,
        "max_interval_hours": max_gap,
        "max_median_interval_hours": max_median_interval_hours,
        "max_gap_hours": max_gap_hours,
        "cadence_ready": cadence_ready,
        "status": status,
    }
    return {"rows": valid_rows, "issues": issue_rows, "summary": summary}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _write_sqlite(path: Path, valid_rows: list[dict[str, Any]], issues: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        for table in ("station_validation_rows", "station_validation_issues", "station_validation_summary"):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        def table(name: str, rows: list[dict[str, Any]]) -> None:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            if not columns:
                connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                return
            definitions = [f'"{column}" TEXT' for column in columns]
            connection.execute(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            quoted = ",".join(f'"{column}"' for column in columns)
            connection.executemany(f"INSERT INTO {name} ({quoted}) VALUES ({','.join('?' for _ in columns)})", [[row.get(column) for column in columns] for row in rows])
        table("station_validation_rows", valid_rows)
        table("station_validation_issues", issues)
        connection.execute("CREATE TABLE station_validation_summary (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO station_validation_summary VALUES (?,?)", [(key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value) if value is not None else None) for key, value in summary.items()])
        connection.commit()
    finally:
        connection.close()


def run_station_validation(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, max_median_interval_hours: float = 6.0, max_gap_hours: float = 24.0) -> dict[str, Any]:
    result = validate_station_rows(_read_rows(input_path), max_median_interval_hours=max_median_interval_hours, max_gap_hours=max_gap_hours)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / f"station_validation_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {"valid": output_root / "station_validated_rows.csv", "issues": output_root / "station_validation_issues.csv", "summary": output_root / "station_validation_summary.json"}
    _write_csv(files["valid"], result["rows"])
    _write_csv(files["issues"], result["issues"])
    files["summary"].write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or STORAGE / "data_cleaning.db"
    _write_sqlite(database, result["rows"], result["issues"], result["summary"])
    manifest = {"run_id": f"station_validation_{stamp}", "status": "completed", "input": str(input_path), "validation_status": result["summary"]["status"], "files": {key: str(value) for key, value in {**files, "database": database}.items()}, "summary": result["summary"]}
    manifest_path = manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
