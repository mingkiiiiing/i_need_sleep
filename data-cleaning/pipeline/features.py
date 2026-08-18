from __future__ import annotations

"""Leakage-safe feature construction for the Taihu first-release data set.

The module consumes the relation table emitted by :mod:`pipeline.align` and
returns one wide, model-ready row per target observation.  It keeps the
alignment audit columns beside every driver and never accepts a driver from
after the target timestamp.  Future nearest-neighbour matches remain visible
as ``future_blocked`` with ``Q24`` instead of being silently used.
"""

import csv
import json
import math
import re
import sqlite3
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .resample import _float_or_none, _json_or_empty, _parse_time, read_observation_csv


UTC = timezone.utc
Q_LEAKAGE_BLOCKED = "Q24"
WINDOW_DAYS = (3, 7, 30)
LAG_DAYS = (1, 3, 7)


def _safe_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_]+", "_", str(value)).strip("_")
    return value or "unknown"


def _read_alignment_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for key in ("target_clean_value", "feature_clean_value", "time_gap_hours", "space_gap_m"):
                row[key] = _float_or_none(row.get(key))
            row["quality_flags"] = _json_or_empty(row.get("quality_flags"))
            row["target_time"] = _parse_time(row.get("target_time_bucket"))
            row["feature_time"] = _parse_time(row.get("feature_time_bucket"))
            rows.append(row)
    return rows


def _series_key(source_id: Any, station_id: Any, scene_id: Any, variable_code: Any) -> tuple[Any, ...]:
    return (source_id or None, station_id or None, scene_id or None, variable_code or None)


def _series_from_rows(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], tuple[list[datetime], list[float]]]:
    grouped: dict[tuple[Any, ...], list[tuple[datetime, float]]] = defaultdict(list)
    for row in rows:
        timestamp = _parse_time(row.get("time_bucket") or row.get("observed_at"))
        value = _float_or_none(row.get("clean_value"))
        if timestamp is None or value is None:
            continue
        grouped[_series_key(row.get("source_id"), row.get("station_id"), row.get("scene_id"), row.get("variable_code"))].append((timestamp, value))
    result: dict[tuple[Any, ...], tuple[list[datetime], list[float]]] = {}
    for key, values in grouped.items():
        values.sort(key=lambda item: item[0])
        # A source sequence should already be unique after QC.  Keep the last
        # value if a user supplies a duplicate file rather than averaging it.
        deduplicated: dict[datetime, float] = {timestamp: value for timestamp, value in values}
        ordered = sorted(deduplicated.items())
        result[key] = ([item[0] for item in ordered], [item[1] for item in ordered])
    return result


def _asof_value(series: tuple[list[datetime], list[float]] | None, target_time: datetime, *, max_age_hours: float | None = None) -> float | None:
    if not series:
        return None
    times, values = series
    index = bisect_right(times, target_time) - 1
    if index < 0:
        return None
    if max_age_hours is not None and (target_time - times[index]).total_seconds() / 3600.0 > max_age_hours:
        return None
    return values[index]


def _rolling_values(series: tuple[list[datetime], list[float]] | None, end_time: datetime, window_days: int) -> list[float]:
    if not series:
        return []
    times, values = series
    start_time = end_time - timedelta(days=window_days)
    right = bisect_right(times, end_time)
    left = bisect_right(times, start_time - timedelta(microseconds=1))
    return values[left:right]


def _past_lag(series: tuple[list[datetime], list[float]] | None, target_time: datetime, lag_days: int) -> float | None:
    # A lag is anchored to the requested historical time, never to a future
    # nearest neighbour.  A two-day tolerance accommodates daily source gaps.
    return _asof_value(series, target_time - timedelta(days=lag_days), max_age_hours=48.0)


def _calm_duration_hours(series: tuple[list[datetime], list[float]] | None, target_time: datetime, threshold_mps: float = 2.0) -> float | None:
    if not series:
        return None
    times, values = series
    index = bisect_right(times, target_time) - 1
    if index < 0:
        return None
    duration = 0.0
    previous_time: datetime | None = None
    for position in range(index, -1, -1):
        timestamp, value = times[position], values[position]
        if value >= threshold_mps:
            break
        if previous_time is None:
            duration = 1.0 if position == 0 else max(1.0, (target_time - timestamp).total_seconds() / 3600.0)
        else:
            step_hours = (previous_time - timestamp).total_seconds() / 3600.0
            if step_hours <= 0 or step_hours > 36:
                break
            duration += step_hours
        previous_time = timestamp
    return round(duration, 6) if duration > 0 else 0.0


def _target_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("target_source_id"), row.get("target_station_id"), row.get("target_scene_id"),
        row.get("target_variable_code"), row.get("target_time_bucket"), row.get("target_clean_value"),
    )


def _append_flags(row: dict[str, Any], *flags: str) -> None:
    current = set(_json_or_empty(row.get("quality_flags")))
    current.update(flag for flag in flags if flag)
    row["quality_flags"] = sorted(current)


def _build_rows(
    alignment_rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    series = _series_from_rows(observation_rows)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in alignment_rows:
        grouped[_target_key(row)].append(row)

    feature_rows: list[dict[str, Any]] = []
    quality: dict[str, dict[str, Any]] = defaultdict(lambda: {"observed_count": 0, "missing_count": 0, "future_blocked_count": 0, "basis": "aligned_driver"})
    leakage = {"accepted_future_values": 0, "blocked_future_values": 0, "rows_with_blocked_future": 0}

    for target_key, alignments in grouped.items():
        first = alignments[0]
        target_time = first.get("target_time") or _parse_time(first.get("target_time_bucket"))
        if target_time is None:
            continue
        output: dict[str, Any] = {
            "target_source_id": first.get("target_source_id"),
            "target_station_id": first.get("target_station_id"),
            "target_scene_id": first.get("target_scene_id"),
            "target_variable_code": first.get("target_variable_code"),
            "target_time_bucket": first.get("target_time_bucket"),
            "target_clean_value": first.get("target_clean_value"),
            "target_category": first.get("target_category"),
            "target_feature_row_key": "|".join("" if item is None else str(item) for item in target_key),
            "feature_observed_count": 0,
            "feature_missing_count": 0,
            "future_blocked_count": 0,
            "quality_flags": sorted(set(flag for row in alignments for flag in _json_or_empty(row.get("quality_flags")))),
        }
        selected_series: dict[str, tuple[list[datetime], list[float]] | None] = {}
        selected_meta: dict[str, dict[str, Any]] = {}
        for alignment in alignments:
            variable = str(alignment.get("feature_variable_code") or "")
            if not variable:
                continue
            name = _safe_name(variable)
            candidate_value = alignment.get("feature_clean_value")
            feature_time = alignment.get("feature_time") or _parse_time(alignment.get("feature_time_bucket"))
            is_future = bool(feature_time and target_time and feature_time > target_time)
            status = str(alignment.get("match_status") or "unmatched")
            if is_future and candidate_value is not None:
                status = "future_blocked"
                candidate_value = None
                output["future_blocked_count"] += 1
                leakage["blocked_future_values"] += 1
                _append_flags(output, Q_LEAKAGE_BLOCKED)
            elif candidate_value is not None and status.startswith("matched"):
                output["feature_observed_count"] += 1
                leakage["accepted_future_values"] += 0
            else:
                output["feature_missing_count"] += 1
            output[f"feature_{name}"] = candidate_value
            output[f"feature_{name}_time_gap_hours"] = alignment.get("time_gap_hours") if candidate_value is not None else None
            output[f"feature_{name}_space_gap_m"] = alignment.get("space_gap_m") if candidate_value is not None else None
            output[f"feature_{name}_match_status"] = status
            output[f"feature_{name}_source_id"] = alignment.get("feature_source_id") if candidate_value is not None else None
            output[f"feature_{name}_station_id"] = alignment.get("feature_station_id") if candidate_value is not None else None
            output[f"feature_{name}_scene_id"] = alignment.get("feature_scene_id") if candidate_value is not None else None
            if candidate_value is not None:
                key = _series_key(alignment.get("feature_source_id"), alignment.get("feature_station_id"), alignment.get("feature_scene_id"), variable)
                selected_series[variable] = series.get(key)
                selected_meta[variable] = alignment
            info = quality[name]
            if candidate_value is None:
                info["missing_count"] += 1
            else:
                info["observed_count"] += 1
            if status == "future_blocked":
                info["future_blocked_count"] += 1

        if output["future_blocked_count"]:
            leakage["rows_with_blocked_future"] += 1

        # Historical values of the target itself are computed from its source
        # sequence and are causal by construction.
        target_series = series.get(_series_key(first.get("target_source_id"), first.get("target_station_id"), first.get("target_scene_id"), first.get("target_variable_code")))
        for lag_days in LAG_DAYS:
            output[f"target_lag_{lag_days}d"] = _past_lag(target_series, target_time, lag_days)
        for window_days in WINDOW_DAYS:
            values = _rolling_values(target_series, target_time, window_days)
            output[f"target_rolling_mean_{window_days}d"] = sum(values) / len(values) if values else None
            output[f"target_rolling_n_{window_days}d"] = len(values)

        # Causal lag and window features for each aligned driver.
        for variable, driver_series in selected_series.items():
            name = _safe_name(variable)
            if not driver_series:
                continue
            for lag_days in LAG_DAYS:
                output[f"{name}_lag_{lag_days}d"] = _past_lag(driver_series, target_time, lag_days)
            for window_days in WINDOW_DAYS:
                values = _rolling_values(driver_series, target_time, window_days)
                output[f"{name}_rolling_mean_{window_days}d"] = sum(values) / len(values) if values else None
                output[f"{name}_rolling_n_{window_days}d"] = len(values)

        # Nutrient features use same-time target values where applicable and
        # aligned values otherwise.  No unit conversion is performed here;
        # standardize_units already enforces canonical mg/L.
        def current_value(variable: str) -> float | None:
            if first.get("target_variable_code") == variable:
                return _float_or_none(first.get("target_clean_value"))
            return _float_or_none(output.get(f"feature_{_safe_name(variable)}"))

        tn = current_value("total_nitrogen")
        tp = current_value("total_phosphorus")
        output["tn_tp_ratio"] = tn / tp if tn is not None and tp is not None and tp > 0 else None
        nh4 = current_value("ammonia_nitrogen")
        no3 = current_value("nitrate_nitrogen")
        no2 = current_value("nitrite_nitrogen")
        output["dissolved_inorganic_nitrogen"] = sum(value for value in (nh4, no3, no2) if value is not None) if all(value is not None for value in (nh4, no3, no2)) else None

        temperature_variable = "water_temperature" if output.get("feature_water_temperature") is not None else "air_temperature"
        temperature_series = selected_series.get(temperature_variable)
        temperature_values = _rolling_values(temperature_series, target_time, 7)
        output["temperature_degree_days_7d"] = sum(max(value, 0.0) for value in temperature_values) if temperature_values else None
        output["temperature_degree_days_basis"] = temperature_variable if temperature_values else None
        wind_series = selected_series.get("wind_speed")
        output["wind_calm_duration_h"] = _calm_duration_hours(wind_series, target_time)
        output["leakage_check"] = "passed" if output["future_blocked_count"] == 0 else "future_values_blocked"
        output["quality_flags"] = sorted(set(output["quality_flags"]))
        feature_rows.append(output)

    for name, info in quality.items():
        total = int(info["observed_count"]) + int(info["missing_count"])
        info["total_count"] = total
        info["missing_rate"] = round(info["missing_count"] / total, 6) if total else None
    return feature_rows, dict(quality), leakage


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
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    return len(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]], quality: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS feature_dataset")
        connection.execute("DROP TABLE IF EXISTS feature_quality_summary")
        if rows:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            definitions = []
            text_columns = {
                "target_source_id", "target_station_id", "target_scene_id", "target_variable_code",
                "target_time_bucket", "target_category", "target_feature_row_key", "quality_flags",
                "leakage_check", "temperature_degree_days_basis",
            }
            for column in columns:
                if column in text_columns or column.endswith("_id") or column.endswith("_status"):
                    definitions.append(f'"{column}" TEXT')
                else:
                    definitions.append(f'"{column}" REAL')
            connection.execute(f'CREATE TABLE feature_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            sql = f'INSERT INTO feature_dataset ({",".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({",".join("?" for _ in columns)})'
            connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if isinstance(row.get(column), (list, dict)) else row.get(column) for column in columns) for row in rows])
        else:
            connection.execute(
                "CREATE TABLE feature_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT, target_source_id TEXT, target_station_id TEXT, target_scene_id TEXT, target_variable_code TEXT, target_time_bucket TEXT, target_clean_value REAL, quality_flags TEXT, leakage_check TEXT)"
            )
        connection.execute("CREATE TABLE feature_quality_summary (feature_name TEXT PRIMARY KEY, observed_count INTEGER, missing_count INTEGER, future_blocked_count INTEGER, total_count INTEGER, missing_rate REAL, basis TEXT)")
        connection.executemany("INSERT INTO feature_quality_summary VALUES (?,?,?,?,?,?,?)", [(name, info.get("observed_count"), info.get("missing_count"), info.get("future_blocked_count"), info.get("total_count"), info.get("missing_rate"), info.get("basis")) for name, info in quality.items()])
        connection.commit()
    finally:
        connection.close()


def run_feature_engineering(alignment_path: Path, observations_path: Path, output_root: Path | None = None, database: Path | None = None, *, manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    alignment_rows = _read_alignment_csv(alignment_path)
    observation_rows = read_observation_csv(observations_path)
    records, quality, leakage = _build_rows(alignment_rows, observation_rows)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    package_root = Path(__file__).resolve().parents[1]
    output_root = output_root or package_root / "storage" / "exports" / f"features_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    feature_path = output_root / "feature_dataset.csv"
    quality_path = output_root / "feature_quality_summary.csv"
    _write_csv(feature_path, records)
    quality_rows = [{"feature_name": name, **info} for name, info in sorted(quality.items())]
    _write_csv(quality_path, quality_rows)
    database = database or package_root / "storage" / "data_cleaning.db"
    _write_sqlite(database, records, quality)
    status = "completed" if leakage["accepted_future_values"] == 0 else "completed_with_leakage"
    manifest: dict[str, Any] = {
        "run_id": run_id or f"features_{stamp}",
        "status": status,
        "alignment_input": str(alignment_path),
        "observation_input": str(observations_path),
        "feature_rows": len(records),
        "alignment_rows": len(alignment_rows),
        "feature_columns": sorted({key for row in records for key in row}),
        "quality_summary_rows": len(quality_rows),
        "leakage_check": leakage,
        "rules": {
            "lag_days": list(LAG_DAYS),
            "rolling_windows_days": list(WINDOW_DAYS),
            "nutrient_units": "canonical mg/L only",
            "temperature_degree_days": "sum(max(temperature,0)) over causal 7-day window",
            "calm_threshold_mps": 2.0,
            "future_matches": "blocked and marked Q24",
        },
        "files": {"feature_dataset": str(feature_path), "feature_quality_summary": str(quality_path), "database": str(database)},
    }
    manifest_path = manifest_path or package_root / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
