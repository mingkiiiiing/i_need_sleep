from __future__ import annotations

"""Source-grain aware temporal resampling for the Taihu data set.

The module deliberately does not upsample quarterly/monthly/annual observations.
Only observations whose inferred source grain is hourly or daily are aggregated
to a canonical bucket.  Native low-frequency observations are copied with
``frequency=native`` so a downstream model can distinguish a real observation
from a value repeated by a feature-engineering step.
"""

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc
CN_TZ = timezone(timedelta(hours=8))
Q_RESAMPLE = "Q22"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_or_empty(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, "", "null"):
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return [str(value)]
    return [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_observation_csv(path: Path) -> list[dict[str, Any]]:
    """Read a cleaned or pending-observation CSV without changing its audit fields."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            row["clean_value"] = _float_or_none(row.get("clean_value"))
            row["observed_value"] = _float_or_none(row.get("observed_value"))
            row["longitude"] = _float_or_none(row.get("longitude"))
            row["latitude"] = _float_or_none(row.get("latitude"))
            row["quality_flags"] = _json_or_empty(row.get("quality_flags"))
            row["is_imputed"] = str(row.get("is_imputed", "")).casefold() in {"true", "1", "yes"}
            rows.append(row)
    return rows


def _infer_granularity(group: list[dict[str, Any]]) -> str:
    source_id = str(group[0].get("source_id") or "")
    variable = str(group[0].get("variable_code") or "")
    if source_id == "nasa_power_hourly":
        return "hourly"
    if source_id.startswith("copernicus_") or group[0].get("scene_id"):
        return "overpass"
    if variable == "algae_density":
        return "annual"
    times = sorted(_parse_time(row.get("observed_at")) for row in group)
    positive_days = [
        (right - left).total_seconds() / 86400
        for left, right in zip(times, times[1:])
        if left and right and right > left
    ]
    if not positive_days:
        return "scene_or_singleton"
    positive_days.sort()
    median = positive_days[len(positive_days) // 2]
    if median <= 0.0625:  # 90 minutes, including sub-hourly data
        return "hourly"
    if median <= 1.5:
        return "daily"
    if median <= 45:
        return "monthly"
    if median <= 120:
        return "quarterly"
    if median <= 400:
        return "annual"
    return "irregular"


def _local_day_bucket(timestamp: datetime) -> datetime:
    local = timestamp.astimezone(CN_TZ)
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


def _hour_bucket(timestamp: datetime) -> datetime:
    return timestamp.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _circular_mean(values: list[float]) -> float | None:
    if not values:
        return None
    radians = [math.radians(value % 360.0) for value in values]
    x = sum(math.cos(angle) for angle in radians) / len(radians)
    y = sum(math.sin(angle) for angle in radians) / len(radians)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None
    result = round(math.degrees(math.atan2(y, x)) % 360.0, 6)
    # 360° and 0° describe the same compass direction; use one canonical value.
    return 0.0 if abs(result - 360.0) < 1e-6 else result


def _aggregation_method(variable_code: str) -> str:
    if variable_code == "precipitation":
        return "sum"
    if variable_code == "wind_direction":
        return "circular_mean"
    return "mean"


def _aggregate_value(variable_code: str, values: list[float]) -> float | None:
    if not values:
        return None
    method = _aggregation_method(variable_code)
    if method == "sum":
        return sum(values)
    if method == "circular_mean":
        return _circular_mean(values)
    return sum(values) / len(values)


def _time_bucket(row: dict[str, Any], granularity: str) -> str | None:
    timestamp = _parse_time(row.get("observed_at"))
    if timestamp is None:
        return None
    if granularity == "hourly":
        return _hour_bucket(timestamp).isoformat()
    if granularity == "daily":
        return _local_day_bucket(timestamp).isoformat()
    return timestamp.isoformat()


def _with_resample_fields(
    row: dict[str, Any],
    *,
    time_bucket: str,
    frequency: str,
    source_granularity: str,
    aggregation_method: str,
    n_obs: int,
    values: list[float],
    source_rows: list[str],
    flags: list[str],
) -> dict[str, Any]:
    value = _aggregate_value(str(row.get("variable_code") or ""), values)
    output = dict(row)
    output["observed_at"] = time_bucket
    output["time_bucket"] = time_bucket
    output["frequency"] = frequency
    output["source_granularity"] = source_granularity
    output["aggregation_method"] = aggregation_method
    output["n_obs"] = n_obs
    output["clean_value"] = value
    output["observed_value"] = value
    output["source_row"] = "aggregate:" + ",".join(source_rows[:100])
    # The row has passed the canonical hourly/daily bucket step even when the
    # source already supplied one observation per bucket.
    output["quality_flags"] = sorted(set(flags + [Q_RESAMPLE]))
    output["missing_flag"] = 1 if value is None else 0
    output["aggregation_coverage"] = None
    if n_obs > 1:
        output["value_origin"] = "derived"
        output["is_imputed"] = any(bool(item.get("is_imputed")) for item in [row])
        output["conversion_rule"] = "temporal_aggregation:" + aggregation_method
    return output


def _union_flags(group: Iterable[dict[str, Any]]) -> list[str]:
    flags: set[str] = set()
    for row in group:
        flags.update(_json_or_empty(row.get("quality_flags")))
    return sorted(flags)


def _group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("source_id"),
        row.get("station_id"),
        row.get("scene_id"),
        row.get("variable_code"),
        row.get("unit"),
    )


def _make_gap_rows(group: list[dict[str, Any]], granularity: str, existing: set[str]) -> list[dict[str, Any]]:
    if granularity not in {"hourly", "daily"}:
        return []
    timestamps = [_parse_time(row.get("observed_at")) for row in group]
    timestamps = [value for value in timestamps if value]
    if len(timestamps) < 2:
        return []
    start = _hour_bucket(min(timestamps)) if granularity == "hourly" else _local_day_bucket(min(timestamps))
    end = _hour_bucket(max(timestamps)) if granularity == "hourly" else _local_day_bucket(max(timestamps))
    step = timedelta(hours=1) if granularity == "hourly" else timedelta(days=1)
    template = dict(group[0])
    gaps: list[dict[str, Any]] = []
    current = start
    while current <= end:
        bucket = current.isoformat()
        if bucket not in existing:
            gap = dict(template)
            gap.update(
                {
                    "observed_at": bucket,
                    "time_bucket": bucket,
                    "frequency": granularity,
                    "source_granularity": granularity,
                    "aggregation_method": "none_missing_bucket",
                    "n_obs": 0,
                    "clean_value": None,
                    "observed_value": None,
                    "source_row": "missing_bucket:" + bucket,
                    "missing_flag": 1,
                    "aggregation_coverage": 0.0,
                    "quality_flags": ["Q01", Q_RESAMPLE],
                    "value_origin": "derived",
                    "is_imputed": False,
                }
            )
            gaps.append(gap)
        current += step
    return gaps


def resample_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate hourly/daily groups and return missing-bucket masks."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _parse_time(row.get("observed_at")) is not None:
            groups[_group_key(row)].append(row)

    output: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    grain_counter: Counter[str] = Counter()
    for group in groups.values():
        group = sorted(group, key=lambda item: _parse_time(item.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        granularity = _infer_granularity(group)
        grain_counter[granularity] += len(group)
        if granularity not in {"hourly", "daily"}:
            for row in group:
                bucket = _time_bucket(row, granularity) or str(row.get("observed_at") or "")
                flags = _json_or_empty(row.get("quality_flags"))
                native = dict(row)
                native["time_bucket"] = bucket
                native["frequency"] = "native"
                native["source_granularity"] = granularity
                native["aggregation_method"] = "none"
                native["n_obs"] = 1
                native["missing_flag"] = 1 if row.get("clean_value") is None else 0
                native["aggregation_coverage"] = 1.0 if row.get("clean_value") is not None else 0.0
                native["quality_flags"] = flags
                output.append(native)
            continue

        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in group:
            bucket = _time_bucket(row, granularity)
            if bucket:
                buckets[bucket].append(row)
        existing: set[str] = set()
        for bucket, bucket_rows in sorted(buckets.items()):
            existing.add(bucket)
            values = [float(row["clean_value"]) for row in bucket_rows if row.get("clean_value") is not None]
            base = dict(bucket_rows[0])
            flags = _union_flags(bucket_rows)
            aggregate = _with_resample_fields(
                base,
                time_bucket=bucket,
                frequency=granularity,
                source_granularity=granularity,
                aggregation_method=_aggregation_method(str(base.get("variable_code") or "")),
                n_obs=len(bucket_rows),
                values=values,
                source_rows=[str(item.get("source_row") or "") for item in bucket_rows],
                flags=flags,
            )
            aggregate["is_imputed"] = any(bool(item.get("is_imputed")) for item in bucket_rows)
            confidences = [
                float(item["imputation_confidence"])
                for item in bucket_rows
                if item.get("imputation_confidence") not in (None, "")
            ]
            aggregate["imputation_confidence"] = min(confidences) if confidences else None
            aggregate["aggregation_coverage"] = len(values) / len(bucket_rows) if bucket_rows else 0.0
            output.append(aggregate)
        gaps.extend(_make_gap_rows(group, granularity, existing))

    return {
        "records": output,
        "gaps": gaps,
        "row_count": len(output),
        "gap_count": len(gaps),
        "granularity_counts": dict(grain_counter),
    }


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


def _write_sqlite(path: Path, records: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS resampled_observations;
            DROP TABLE IF EXISTS resample_gaps;
            CREATE TABLE resampled_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT, station_id TEXT, scene_id TEXT,
                observed_at TEXT, time_bucket TEXT NOT NULL,
                longitude REAL, latitude REAL, variable_code TEXT,
                clean_value REAL, observed_value REAL, unit TEXT, source_unit TEXT,
                frequency TEXT NOT NULL, source_granularity TEXT NOT NULL,
                aggregation_method TEXT NOT NULL, n_obs INTEGER NOT NULL,
                aggregation_coverage REAL, value_origin TEXT,
                is_imputed INTEGER, quality_flags TEXT
            );
            CREATE TABLE resample_gaps AS SELECT * FROM resampled_observations WHERE 0;
            """
        )
        columns = [
            "source_id", "station_id", "scene_id", "observed_at", "time_bucket",
            "longitude", "latitude", "variable_code", "clean_value", "observed_value",
            "unit", "source_unit", "frequency", "source_granularity", "aggregation_method",
            "n_obs", "aggregation_coverage", "value_origin", "is_imputed", "quality_flags",
        ]
        sql = f"INSERT INTO resampled_observations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in columns) for row in records])
        gap_sql = f"INSERT INTO resample_gaps ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        connection.executemany(gap_sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in columns) for row in gaps])
        connection.commit()
    finally:
        connection.close()


def run_resampling(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    rows = read_observation_csv(input_path)
    result = resample_records(rows)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or Path(__file__).resolve().parents[1] / "storage" / "exports" / f"resample_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {
        "resampled_observations": str(output_root / "resampled_observations.csv"),
        "resample_gaps": str(output_root / "resample_gaps.csv"),
    }
    _write_csv(Path(files["resampled_observations"]), result["records"])
    _write_csv(Path(files["resample_gaps"]), result["gaps"])
    database = database or Path(__file__).resolve().parents[1] / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["records"], result["gaps"])
    manifest = {
        "run_id": run_id or f"resample_{stamp}",
        "status": "completed_with_gap_masks" if result["gaps"] else "completed",
        "input": str(input_path),
        "input_rows": len(rows),
        "resampled_rows": result["row_count"],
        "gap_rows": result["gap_count"],
        "granularity_counts": result["granularity_counts"],
        "timezone": "Asia/Shanghai for daily buckets; UTC for storage",
        "rules": {
            "precipitation": "sum",
            "wind_direction": "circular_mean",
            "other_numeric": "mean",
            "low_frequency": "native_only_no_upsampling",
            "missing_buckets": "separate resample_gaps.csv with Q01+Q22",
        },
        "files": {**files, "database": str(database)},
    }
    manifest_path = manifest_path or Path(__file__).resolve().parents[1] / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
