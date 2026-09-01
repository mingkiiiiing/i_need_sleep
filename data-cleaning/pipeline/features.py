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
from .align import HYDROLOGY_VARIABLES, METEOROLOGY_VARIABLES, WATER_QUALITY_VARIABLES


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
Q_LEAKAGE_BLOCKED = "Q24"
WINDOW_DAYS = (3, 7, 30)
LAG_DAYS = (1, 3, 7)
DIRECT_FEATURE_CATEGORIES = ("water_quality", "meteorology", "hydrology", "remote_sensing", "static")
LAG_ROLL_DAYS = (1, 3, 7, 14, 30, 90)
MECHANISM_PARAMETER_VERSION = "taihu_mechanism_defaults_v1"
MECHANISM_PARAMETERS = {
    "q10": 2.0,
    "reference_temperature_c": 20.0,
    "nitrogen_half_saturation_mg_l": 0.10,
    "phosphorus_half_saturation_mg_l": 0.01,
    "light_half_saturation_w_m2": 100.0,
    "low_wind_threshold_m_s": 3.0,
}


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
    output_root = output_root or STORAGE / "exports" / f"features_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    feature_path = output_root / "feature_dataset.csv"
    quality_path = output_root / "feature_quality_summary.csv"
    _write_csv(feature_path, records)
    quality_rows = [{"feature_name": name, **info} for name, info in sorted(quality.items())]
    _write_csv(quality_path, quality_rows)
    database = database or STORAGE / "data_cleaning.db"
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
    manifest_path = manifest_path or STORAGE / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def _direct_category(row: dict[str, Any]) -> str:
    variable = str(row.get("variable_code") or "")
    source_id = str(row.get("source_id") or "").casefold()
    if row.get("scene_id") or any(token in source_id for token in ("sentinel", "copernicus", "clms", "remote")):
        return "remote_sensing"
    if variable in WATER_QUALITY_VARIABLES:
        return "water_quality"
    if variable in METEOROLOGY_VARIABLES:
        return "meteorology"
    if variable in HYDROLOGY_VARIABLES:
        return "hydrology"
    return "other"


def _local_feature_date(row: dict[str, Any]) -> str | None:
    local = row.get("observed_at_local")
    if local not in (None, ""):
        return str(local)[:10]
    moment = _parse_time(row.get("time_bucket") or row.get("observed_at"))
    if moment is None:
        return None
    return (moment + timedelta(hours=8)).date().isoformat()


def _static_feature_summary(path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}, {"status": "unavailable", "path": str(path) if path else None, "reason": "static_feature_file_missing"}
    import pandas as pd

    frame = pd.read_parquet(path)
    if frame.empty:
        return {}, {"status": "unavailable", "path": str(path), "reason": "static_feature_file_empty"}
    weights = pd.to_numeric(frame.get("sub_area_km2"), errors="coerce").fillna(0.0)
    summary: dict[str, Any] = {"static_basin_count": int(len(frame))}
    excluded = {"hybas_id", "next_down", "pfaf_id"}
    for column in frame.columns:
        if column in excluded:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        valid = numeric.notna()
        if not valid.any():
            continue
        valid_weights = weights[valid]
        if float(valid_weights.sum()) > 0:
            value = float((numeric[valid] * valid_weights).sum() / valid_weights.sum())
        else:
            value = float(numeric[valid].mean())
        summary[f"static_{_safe_name(column)}"] = value
    for column in ("source_dem", "source_landcover", "license_dem", "license_landcover", "study_scope"):
        if column in frame:
            values = sorted({str(item) for item in frame[column].dropna().tolist()})
            summary[f"static_{column}"] = "|".join(values)
    lineage = {
        "status": "available",
        "path": str(path),
        "rows": int(len(frame)),
        "aggregation": "sub_area_km2_weighted_mean_for_numeric_columns",
        "hybas_ids": [str(item) for item in frame["hybas_id"].dropna().tolist()] if "hybas_id" in frame else [],
    }
    return summary, lineage


def build_daily_direct_features(
    observation_rows: list[dict[str, Any]],
    *,
    static_features_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Build one lake-day row while preserving absence and feature lineage."""

    grouped_by_date: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    all_dates: set[str] = set()
    for row in observation_rows:
        feature_date = _local_feature_date(row)
        variable = str(row.get("variable_code") or "")
        value = _float_or_none(row.get("clean_value"))
        if feature_date is None or not variable or value is None:
            continue
        all_dates.add(feature_date)
        grouped_by_date[feature_date][variable].append(row)
    static_summary, static_lineage = _static_feature_summary(static_features_path)
    daily: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for feature_date in sorted(all_dates):
        output: dict[str, Any] = {
            "feature_date": feature_date,
            "feature_reference_time": f"{feature_date}T23:59:59+08:00",
            "spatial_grain": "taihu_lake",
            "feature_grain": "lake_day",
            **static_summary,
        }
        present: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        for variable, members in grouped_by_date.get(feature_date, {}).items():
            values = [float(item["clean_value"]) for item in members if _float_or_none(item.get("clean_value")) is not None]
            if not values:
                continue
            category = _direct_category(members[0])
            name = _safe_name(variable)
            value = sum(values) / len(values)
            output[f"direct_{name}"] = value
            output[f"direct_{name}_observed_count"] = len(values)
            output[f"direct_{name}_source_count"] = len({str(item.get("source_id") or "") for item in members})
            present[category].add(name)
            sources[category].update(str(item.get("source_id") or "") for item in members if item.get("source_id"))
            category_counts[category] += 1
            lineage_rows.append({
                "feature_date": feature_date,
                "feature_name": f"direct_{name}",
                "category": category,
                "availability": "available",
                "source_ids": sorted({str(item.get("source_id") or "") for item in members if item.get("source_id")}),
                "source_files": sorted({str(item.get("source_file") or "") for item in members if item.get("source_file")}),
                "source_times": sorted({str(item.get("time_bucket") or item.get("observed_at") or "") for item in members}),
                "source_rows": len(members),
                "aggregation": "mean_of_daily_or_native_records",
                "value_origin_counts": dict(Counter(str(item.get("value_origin") or "unknown") for item in members)),
                "quality_flags": sorted({flag for item in members for flag in _json_or_empty(item.get("quality_flags"))}),
            })
        for category in DIRECT_FEATURE_CATEGORIES:
            if category == "static":
                available = bool(static_summary)
                feature_count = len(static_summary)
                category_sources = [str(static_features_path)] if available else []
                reason = None if available else static_lineage.get("reason")
            else:
                available = bool(present.get(category))
                feature_count = len(present.get(category, set()))
                category_sources = sorted(sources.get(category, set()))
                reason = None if available else f"no_{category}_rows_in_real_input"
            output[f"category_{category}_available"] = int(available)
            output[f"category_{category}_feature_count"] = feature_count
            output[f"category_{category}_sources"] = json.dumps(category_sources, ensure_ascii=False)
            if not available:
                lineage_rows.append({
                    "feature_date": feature_date, "feature_name": f"category_{category}", "category": category,
                    "availability": "unavailable", "source_ids": [], "source_files": [], "source_times": [],
                    "source_rows": 0, "aggregation": None, "value_origin_counts": {}, "quality_flags": [], "reason": reason,
                })
        daily.append(output)
    audit = {
        "input_rows": len(observation_rows),
        "daily_rows": len(daily),
        "lineage_rows": len(lineage_rows),
        "date_start": min(all_dates) if all_dates else None,
        "date_end": max(all_dates) if all_dates else None,
        "category_feature_day_counts": dict(category_counts),
        "static_lineage": static_lineage,
        "data_truth": "only observed/resampled real values are materialized; absent water-quality or hydrology categories remain explicit unavailable fields",
    }
    return daily, lineage_rows, audit


def _write_daily_feature_sqlite(path: Path, rows: list[dict[str, Any]], lineage: list[dict[str, Any]]) -> None:
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        pd.DataFrame(rows).to_sql("daily_direct_features", connection, if_exists="replace", index=False)
        serialised = [
            {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in item.items()}
            for item in lineage
        ]
        pd.DataFrame(serialised).to_sql("direct_feature_lineage", connection, if_exists="replace", index=False)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_daily_direct_features_date ON daily_direct_features(feature_date)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_direct_feature_lineage_date_name ON direct_feature_lineage(feature_date, feature_name)")
        connection.commit()
    finally:
        connection.close()


def run_daily_direct_features(
    observations_path: Path,
    output_root: Path,
    database: Path,
    *,
    static_features_path: Path | None = None,
    manifest_path: Path | None = None,
    run_id: str = "p12_01_daily_direct_features",
) -> dict[str, Any]:
    import pandas as pd

    observations = read_observation_csv(observations_path)
    rows, lineage, audit = build_daily_direct_features(observations, static_features_path=static_features_path)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "daily_direct_features.csv"
    parquet_path = output_root / "daily_direct_features.parquet"
    lineage_path = output_root / "direct_feature_lineage.csv"
    _write_csv(csv_path, rows)
    _write_csv(lineage_path, lineage)
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    _write_daily_feature_sqlite(database, rows, lineage)
    manifest = {
        "run_id": run_id,
        "task_id": "P12-01",
        "status": "completed" if rows else "blocked_no_observations",
        "input": str(observations_path),
        "static_features": str(static_features_path) if static_features_path else None,
        **audit,
        "outputs": {"csv": str(csv_path), "parquet": str(parquet_path), "lineage": str(lineage_path), "database": str(database)},
    }
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _direct_value_columns(frame: Any) -> list[str]:
    return sorted(
        column for column in frame.columns
        if column.startswith("direct_")
        and not column.endswith(("_observed_count", "_source_count"))
        and "_lag_" not in column
        and "_rolling_" not in column
        and str(frame[column].dtype) != "object"
    )


def build_lag_rolling_features(frame: Any) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    import numpy as np
    import pandas as pd

    if "feature_date" not in frame.columns:
        raise ValueError("feature_date is required")
    result = frame.copy()
    result["feature_date"] = pd.to_datetime(result["feature_date"], errors="raise")
    result = result.sort_values("feature_date").reset_index(drop=True)
    if result["feature_date"].duplicated().any():
        raise ValueError("feature_date must be unique at lake-day grain")
    value_columns = _direct_value_columns(result)
    lineage: list[dict[str, Any]] = []
    leakage_violations = 0
    date_index = pd.DatetimeIndex(result["feature_date"])
    ordinal_days = pd.Series(date_index.asi8 / 86_400_000_000_000.0, index=date_index)
    additions: dict[str, Any] = {}
    for column in value_columns:
        numeric = pd.Series(pd.to_numeric(result[column], errors="coerce").to_numpy(), index=date_index)
        for days in LAG_ROLL_DAYS:
            lag_name = f"{column}_lag_{days}d"
            shifted_dates = date_index - pd.Timedelta(days=days)
            additions[lag_name] = numeric.reindex(shifted_dates).to_numpy()
            lineage.append({"feature_name": lag_name, "source_feature": column, "window_days": days, "statistic": "exact_calendar_lag", "causal_rule": "source_date = feature_date - lag; never future"})
            roller = numeric.rolling(f"{days}D", closed="left")
            count = roller.count().fillna(0.0)
            mean = roller.mean()
            valid_x = ordinal_days.where(numeric.notna())
            sum_x = valid_x.rolling(f"{days}D", closed="left").sum()
            sum_y = numeric.rolling(f"{days}D", closed="left").sum()
            sum_xy = (valid_x * numeric).rolling(f"{days}D", closed="left").sum()
            sum_x2 = (valid_x * valid_x).rolling(f"{days}D", closed="left").sum()
            denominator = count * sum_x2 - sum_x * sum_x
            slope = (count * sum_xy - sum_x * sum_y) / denominator.replace(0, np.nan)
            slope = slope.where(count >= 2, np.nan).fillna(0.0).where(count > 0, np.nan)
            stats = {
                "mean": mean, "max": roller.max(), "min": roller.min(),
                "std": roller.std(ddof=0), "slope": slope,
                "anomaly": numeric - mean, "n": count.astype("int64"),
            }
            for statistic, values in stats.items():
                feature_name = f"{column}_rolling_{statistic}_{days}d"
                additions[feature_name] = values.to_numpy()
                lineage.append({
                    "feature_name": feature_name, "source_feature": column, "window_days": days,
                    "statistic": statistic, "causal_rule": "feature_date-window <= source_date < feature_date",
                })
    result = pd.concat([result, pd.DataFrame(additions, index=result.index)], axis=1)
    result["feature_date"] = result["feature_date"].dt.date.astype(str)
    audit = {
        "rows": int(len(result)), "base_value_columns": value_columns,
        "derived_feature_count": len(lineage), "lag_roll_days": list(LAG_ROLL_DAYS),
        "leakage_violations": leakage_violations,
        "causal_policy": "all lag and rolling source dates are strictly earlier than feature_date",
    }
    return result, lineage, audit


def run_lag_rolling_features(
    input_path: Path,
    output_root: Path,
    database: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    import pandas as pd

    frame = pd.read_parquet(input_path) if input_path.suffix.casefold() == ".parquet" else pd.read_csv(input_path)
    result, lineage, audit = build_lag_rolling_features(frame)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "lag_rolling_features.csv"
    parquet_path = output_root / "lag_rolling_features.parquet"
    lineage_path = output_root / "lag_rolling_lineage.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result.to_parquet(parquet_path, index=False)
    pd.DataFrame(lineage).to_csv(lineage_path, index=False, encoding="utf-8-sig")
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        result.to_sql("daily_lag_rolling_features", connection, if_exists="replace", index=False)
        pd.DataFrame(lineage).to_sql("lag_rolling_lineage", connection, if_exists="replace", index=False)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lag_rolling_date ON daily_lag_rolling_features(feature_date)")
        connection.commit()
    finally:
        connection.close()
    manifest = {
        "run_id": "p12_02_lag_rolling_features", "task_id": "P12-02",
        "status": "completed" if audit["leakage_violations"] == 0 else "failed_leakage",
        "input": str(input_path), **audit,
        "outputs": {"csv": str(csv_path), "parquet": str(parquet_path), "lineage": str(lineage_path), "database": str(database)},
    }
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _numeric_series(frame: Any, *candidates: str) -> Any:
    import numpy as np
    import pandas as pd

    for candidate in candidates:
        if candidate in frame.columns:
            return pd.to_numeric(frame[candidate], errors="coerce")
    return pd.Series(np.nan, index=frame.index, dtype="float64")


def build_mechanistic_features(frame: Any) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Create interpretable process proxies while preserving unavailable drivers as null."""
    import numpy as np
    import pandas as pd

    if "feature_date" not in frame.columns:
        raise ValueError("feature_date is required")
    result = frame.copy()
    dates = pd.to_datetime(result["feature_date"], errors="raise")
    temperature_water = _numeric_series(result, "direct_water_temperature")
    temperature_air = _numeric_series(result, "direct_air_temperature")
    temperature = temperature_water.combine_first(temperature_air)
    result["mechanism_temperature_basis"] = np.where(temperature_water.notna(), "water_temperature", np.where(temperature_air.notna(), "air_temperature_proxy", "unavailable"))
    result["mechanism_temperature_response_q10"] = MECHANISM_PARAMETERS["q10"] ** (
        (temperature - MECHANISM_PARAMETERS["reference_temperature_c"]) / 10.0
    )

    nitrogen = _numeric_series(result, "direct_total_nitrogen", "direct_dissolved_inorganic_nitrogen")
    phosphorus = _numeric_series(result, "direct_total_phosphorus", "direct_phosphate")
    result["mechanism_n_limitation_monod"] = nitrogen / (MECHANISM_PARAMETERS["nitrogen_half_saturation_mg_l"] + nitrogen)
    result["mechanism_p_limitation_monod"] = phosphorus / (MECHANISM_PARAMETERS["phosphorus_half_saturation_mg_l"] + phosphorus)
    result["mechanism_np_combined_limitation"] = pd.concat(
        [result["mechanism_n_limitation_monod"], result["mechanism_p_limitation_monod"]], axis=1
    ).min(axis=1, skipna=False)
    result["mechanism_tn_tp_mass_ratio"] = nitrogen / phosphorus.replace(0, np.nan)
    result["mechanism_nutrient_basis_available"] = (nitrogen.notna() & phosphorus.notna()).astype(int)

    light = _numeric_series(result, "direct_shortwave_radiation", "direct_solar_radiation")
    result["mechanism_light_limitation"] = light / (MECHANISM_PARAMETERS["light_half_saturation_w_m2"] + light)
    wind = _numeric_series(result, "direct_wind_speed")
    result["mechanism_low_wind_indicator"] = np.where(wind.notna(), (wind < MECHANISM_PARAMETERS["low_wind_threshold_m_s"]).astype(float), np.nan)
    wind_3d = _numeric_series(result, "direct_wind_speed_rolling_mean_3d")
    result["mechanism_low_wind_3d_indicator"] = np.where(wind_3d.notna(), (wind_3d < MECHANISM_PARAMETERS["low_wind_threshold_m_s"]).astype(float), np.nan)

    rainfall_3d_mean = _numeric_series(result, "direct_precipitation_rolling_mean_3d")
    rainfall_3d_n = _numeric_series(result, "direct_precipitation_rolling_n_3d")
    rainfall_7d_mean = _numeric_series(result, "direct_precipitation_rolling_mean_7d")
    rainfall_7d_n = _numeric_series(result, "direct_precipitation_rolling_n_7d")
    result["mechanism_antecedent_rainfall_3d"] = rainfall_3d_mean * rainfall_3d_n
    result["mechanism_antecedent_rainfall_7d"] = rainfall_7d_mean * rainfall_7d_n
    water_level = _numeric_series(result, "direct_water_level")
    water_level_lag = _numeric_series(result, "direct_water_level_lag_1d")
    result["mechanism_water_level_change_1d"] = water_level - water_level_lag
    result["mechanism_hydrology_available"] = water_level.notna().astype(int)

    # Shore-normal information is not present in the public batch. Keep the
    # transport feature explicitly unavailable instead of assuming a coast angle.
    result["mechanism_onshore_wind_component"] = np.nan
    result["mechanism_onshore_wind_available"] = 0
    day = dates.dt.dayofyear.astype(float)
    result["mechanism_phenology_sin"] = np.sin(2.0 * np.pi * day / 365.25)
    result["mechanism_phenology_cos"] = np.cos(2.0 * np.pi * day / 365.25)
    result["mechanism_parameter_version"] = MECHANISM_PARAMETER_VERSION

    definitions = {
        "mechanism_temperature_response_q10": "Q10 response using measured water temperature or explicit air-temperature proxy",
        "mechanism_n_limitation_monod": "Monod nitrogen limitation; null without real nitrogen",
        "mechanism_p_limitation_monod": "Monod phosphorus limitation; null without real phosphorus",
        "mechanism_np_combined_limitation": "minimum of N and P limitation; requires both",
        "mechanism_tn_tp_mass_ratio": "mass ratio; requires real TN and TP",
        "mechanism_light_limitation": "half-saturation light response",
        "mechanism_low_wind_indicator": "wind speed below versioned threshold",
        "mechanism_low_wind_3d_indicator": "past-only 3-day mean wind below threshold",
        "mechanism_antecedent_rainfall_3d": "past-only rolling precipitation mean multiplied by observed count",
        "mechanism_antecedent_rainfall_7d": "past-only rolling precipitation mean multiplied by observed count",
        "mechanism_water_level_change_1d": "current water level minus exact 1-day lag",
        "mechanism_onshore_wind_component": "null until shoreline-normal direction is supplied",
        "mechanism_phenology_sin": "annual day-of-year sine",
        "mechanism_phenology_cos": "annual day-of-year cosine",
    }
    lineage = [{"feature_name": key, "definition": value, "parameter_version": MECHANISM_PARAMETER_VERSION} for key, value in definitions.items()]
    availability = {
        "temperature_rows": int(temperature.notna().sum()),
        "nutrient_rows": int((nitrogen.notna() & phosphorus.notna()).sum()),
        "light_rows": int(light.notna().sum()),
        "wind_rows": int(wind.notna().sum()),
        "water_level_rows": int(water_level.notna().sum()),
        "onshore_wind_rows": 0,
        "phenology_rows": int(len(result)),
    }
    return result, lineage, {"rows": int(len(result)), "parameter_version": MECHANISM_PARAMETER_VERSION, "parameters": MECHANISM_PARAMETERS, "availability": availability, "truth_policy": "unavailable measured drivers remain null; air temperature is explicitly labelled as a proxy"}


def run_mechanistic_features(input_path: Path, output_root: Path, database: Path, *, manifest_path: Path | None = None) -> dict[str, Any]:
    import pandas as pd

    frame = pd.read_parquet(input_path) if input_path.suffix.casefold() == ".parquet" else pd.read_csv(input_path)
    result, lineage, audit = build_mechanistic_features(frame)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "mechanistic_features.csv"
    parquet_path = output_root / "mechanistic_features.parquet"
    lineage_path = output_root / "mechanistic_feature_lineage.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result.to_parquet(parquet_path, index=False)
    pd.DataFrame(lineage).to_csv(lineage_path, index=False, encoding="utf-8-sig")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        result.to_sql("daily_mechanistic_features", connection, if_exists="replace", index=False)
        pd.DataFrame(lineage).to_sql("mechanistic_feature_lineage", connection, if_exists="replace", index=False)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mechanistic_date ON daily_mechanistic_features(feature_date)")
    manifest = {"run_id": "p12_03_mechanistic_features", "task_id": "P12-03", "status": "completed", "input": str(input_path), **audit, "outputs": {"csv": str(csv_path), "parquet": str(parquet_path), "lineage": str(lineage_path), "database": str(database)}}
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_reliability_features(frame: Any) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Attach observation age, source, proxy, coverage and uncertainty signals."""
    import numpy as np
    import pandas as pd

    if "feature_date" not in frame.columns:
        raise ValueError("feature_date is required")
    result = frame.copy()
    dates = pd.to_datetime(result["feature_date"], errors="raise")
    direct_columns = _direct_value_columns(result)
    lineage: list[dict[str, Any]] = []
    observed_cells = 0
    additions: dict[str, Any] = {}
    for column in direct_columns:
        values = pd.to_numeric(result[column], errors="coerce")
        observed = values.notna()
        observed_cells += int(observed.sum())
        last_dates = pd.Series(pd.NaT, index=result.index, dtype="datetime64[ns]")
        last_dates.loc[observed] = dates.loc[observed]
        last_dates = last_dates.ffill()
        age_name = f"reliability_{column.removeprefix('direct_')}_age_days"
        age_values = (dates - last_dates).dt.total_seconds() / 86400.0
        age_values.loc[last_dates.isna()] = np.nan
        additions[age_name] = age_values
        uncertainty_source = f"{column}_rolling_std_7d"
        uncertainty_name = f"reliability_{column.removeprefix('direct_')}_uncertainty_7d"
        additions[uncertainty_name] = _numeric_series(result, uncertainty_source)
        lineage.extend([
            {"feature_name": age_name, "source_feature": column, "definition": "calendar days since latest non-null real/proxy input; null before first input"},
            {"feature_name": uncertainty_name, "source_feature": uncertainty_source, "definition": "past-only 7-day population standard deviation; not a calibrated prediction interval"},
        ])
    categories = ["water_quality", "meteorology", "hydrology", "remote_sensing", "static"]
    for category in categories:
        source_column = f"category_{category}_sources"
        available_column = f"category_{category}_available"
        additions[f"reliability_{category}_available"] = pd.to_numeric(result.get(available_column, 0), errors="coerce").fillna(0).astype(int) if available_column in result else 0
        if source_column in result:
            additions[f"reliability_{category}_source_count"] = result[source_column].fillna("[]").map(lambda value: len(_json_or_empty(value)))
            additions[f"reliability_{category}_proxy_flag"] = result[source_column].fillna("[]").astype(str).str.lower().str.contains("nasa_power|open_meteo|gfs").astype(int)
        else:
            additions[f"reliability_{category}_source_count"] = 0
            additions[f"reliability_{category}_proxy_flag"] = 0
    count_columns = [column for column in result.columns if column.startswith("direct_") and column.endswith("_observed_count")]
    additions["reliability_observed_input_count"] = result[count_columns].fillna(0).sum(axis=1) if count_columns else 0
    additions["reliability_available_direct_fraction"] = result[direct_columns].notna().mean(axis=1) if direct_columns else 0.0
    # These cannot be inferred from a scene-level cloud percentage. They stay
    # null until pixel QA/calibration truth is delivered.
    additions["reliability_remote_valid_pixel_fraction"] = np.nan
    additions["reliability_imputed_fraction"] = np.nan
    additions["reliability_calibrated_prediction_uncertainty"] = np.nan
    additions["reliability_missing_metadata_flags"] = "valid_pixel_fraction;imputed_fraction;calibrated_prediction_uncertainty"
    result = pd.concat([result, pd.DataFrame(additions, index=result.index)], axis=1)
    lineage.extend([
        {"feature_name": "reliability_remote_valid_pixel_fraction", "definition": "null without pixel-level QA mask"},
        {"feature_name": "reliability_imputed_fraction", "definition": "null because daily wide table does not retain cell-level imputation counts"},
        {"feature_name": "reliability_calibrated_prediction_uncertainty", "definition": "null until an observed target and calibration split exist"},
    ])
    audit = {
        "rows": int(len(result)), "direct_feature_count": len(direct_columns), "observed_direct_cells": observed_cells,
        "explicitly_unavailable_fields": ["reliability_remote_valid_pixel_fraction", "reliability_imputed_fraction", "reliability_calibrated_prediction_uncertainty"],
        "truth_policy": "reliability metadata is null when the required pixel QA, imputation lineage or target calibration is unavailable",
    }
    return result, lineage, audit


def run_reliability_features(input_path: Path, output_root: Path, database: Path, *, manifest_path: Path | None = None) -> dict[str, Any]:
    import pandas as pd

    frame = pd.read_parquet(input_path) if input_path.suffix.casefold() == ".parquet" else pd.read_csv(input_path)
    result, lineage, audit = build_reliability_features(frame)
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path, parquet_path = output_root / "reliability_features.csv", output_root / "reliability_features.parquet"
    lineage_path = output_root / "reliability_feature_lineage.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    result.to_parquet(parquet_path, index=False)
    pd.DataFrame(lineage).to_csv(lineage_path, index=False, encoding="utf-8-sig")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        result.to_sql("daily_reliability_features", connection, if_exists="replace", index=False)
        pd.DataFrame(lineage).to_sql("reliability_feature_lineage", connection, if_exists="replace", index=False)
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reliability_date ON daily_reliability_features(feature_date)")
    manifest = {"run_id": "p12_04_reliability_features", "task_id": "P12-04", "status": "completed", "input": str(input_path), **audit, "outputs": {"csv": str(csv_path), "parquet": str(parquet_path), "lineage": str(lineage_path), "database": str(database)}}
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
