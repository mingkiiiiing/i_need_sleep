from __future__ import annotations

"""Leakage-audited experiment dataset splitting for Taihu feature tables."""

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
CN_TZ = timezone(timedelta(hours=8))


def _parse_time(value: Any) -> datetime | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _time_group(timestamp: datetime | None, granularity: str = "day") -> str | None:
    if timestamp is None:
        return None
    local = timestamp.astimezone(CN_TZ)
    if granularity == "month":
        return local.strftime("%Y-%m")
    if granularity == "year":
        return local.strftime("%Y")
    return local.strftime("%Y-%m-%d")


def _target_key(row: dict[str, Any], index: int) -> str:
    existing = row.get("target_feature_row_key")
    if existing:
        return str(existing)
    return "|".join(str(row.get(key) or "") for key in ("target_source_id", "target_station_id", "target_scene_id", "target_variable_code", "target_time_bucket")) + f"|row{index}"


def _assign_time_splits(groups: list[str], train_fraction: float, validation_fraction: float) -> dict[str, str]:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise ValueError("train_fraction and validation_fraction must be positive and sum to less than one")
    if len(groups) < 3:
        return {group: "train" for group in groups}
    train_count = max(1, min(len(groups) - 2, int(len(groups) * train_fraction)))
    validation_count = max(1, min(len(groups) - train_count - 1, int(len(groups) * validation_fraction)))
    train_end = train_count
    validation_end = train_count + validation_count
    return {
        group: "train" if index < train_end else "validation" if index < validation_end else "test"
        for index, group in enumerate(groups)
    }


def _assign_group_splits(groups: list[str], validation_groups: set[str], test_groups: set[str]) -> dict[str, str]:
    overlap = validation_groups & test_groups
    if overlap:
        raise ValueError(f"validation and test groups overlap: {sorted(overlap)}")
    return {group: "test" if group in test_groups else "validation" if group in validation_groups else "train" for group in groups}


def _audit(rows: list[dict[str, Any]], split_mapping: dict[str, str], time_mapping: dict[str, str | None], group_field: str, strategy: str) -> dict[str, Any]:
    key_to_split: dict[str, str] = {}
    duplicate_keys: list[str] = []
    split_counts: Counter[str] = Counter()
    time_sets: dict[str, set[str]] = defaultdict(set)
    group_sets: dict[str, set[str]] = defaultdict(set)
    leakage_status: Counter[str] = Counter()
    future_status_count = 0
    for index, row in enumerate(rows):
        key = _target_key(row, index)
        split = split_mapping.get(key, "excluded")
        if key in key_to_split:
            duplicate_keys.append(key)
        key_to_split[key] = split
        split_counts[split] += 1
        time_group = time_mapping.get(key)
        if time_group:
            time_sets[split].add(time_group)
        group_value = str(row.get(group_field) or "__MISSING__")
        group_sets[split].add(group_value)
        status = str(row.get("leakage_check") or "unknown")
        leakage_status[status] += 1
        for column, value in row.items():
            if column.endswith("_match_status") and value == "future_blocked":
                future_status_count += 1
    ordered_time_sets = {name: sorted(values) for name, values in time_sets.items()}
    time_order_ok = True
    if strategy == "time":
        train_times, validation_times, test_times = (time_sets.get(name, set()) for name in ("train", "validation", "test"))
        if train_times and validation_times and max(train_times) >= min(validation_times):
            time_order_ok = False
        if validation_times and test_times and max(validation_times) >= min(test_times):
            time_order_ok = False
    duplicate_keys = sorted(set(duplicate_keys))
    return {
        "split_counts": dict(split_counts),
        "time_groups": ordered_time_sets,
        "group_sets": {name: sorted(values) for name, values in group_sets.items()},
        "duplicate_target_keys": duplicate_keys,
        "duplicate_target_key_count": len(duplicate_keys),
        "time_order_ok": time_order_ok,
        "leakage_status_counts": dict(leakage_status),
        "future_blocked_status_count": future_status_count,
        "feature_future_acceptance": 0,
    }


def split_dataset(rows: list[dict[str, Any]], *, strategy: str = "time", train_fraction: float = 0.7, validation_fraction: float = 0.15, group_field: str = "target_station_id", validation_groups: set[str] | None = None, test_groups: set[str] | None = None, time_granularity: str = "day") -> dict[str, Any]:
    if strategy not in {"time", "group"}:
        raise ValueError("strategy must be time or group")
    usable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    target_time_by_key: dict[str, str | None] = {}
    for index, row in enumerate(rows):
        timestamp = _parse_time(row.get("target_time_bucket"))
        key = _target_key(row, index)
        group = _time_group(timestamp, time_granularity)
        target_time_by_key[key] = group
        if group is None:
            excluded_row = dict(row)
            excluded_row.update({"dataset_split": "excluded_missing_time", "split_reason": "target_time_bucket_missing_or_invalid"})
            excluded.append(excluded_row)
        else:
            usable.append(row)
    if strategy == "time":
        time_groups = sorted({_time_group(_parse_time(row.get("target_time_bucket")), time_granularity) for row in usable})
        mapping = _assign_time_splits([group for group in time_groups if group is not None], train_fraction, validation_fraction)
        group_mapping: dict[str, str] = {}
        split_reason = "chronological_time_block"
    else:
        group_values = sorted({str(row.get(group_field) or "__MISSING__") for row in usable})
        validation_groups = validation_groups or set()
        test_groups = test_groups or set()
        if not validation_groups and not test_groups and len(group_values) >= 3:
            test_groups = {group_values[-1]}
            validation_groups = {group_values[-2]}
        group_mapping = _assign_group_splits(group_values, validation_groups, test_groups)
        mapping = {}
        split_reason = f"group_holdout:{group_field}"
    result_rows: list[dict[str, Any]] = []
    split_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(usable):
        output = dict(row)
        key = _target_key(row, index)
        time_group = target_time_by_key.get(key)
        if strategy == "time":
            split = mapping[str(time_group)]
            split_group = str(row.get(group_field) or "__MISSING__")
        else:
            split_group = str(row.get(group_field) or "__MISSING__")
            split = group_mapping[split_group]
        output.update({"dataset_split": split, "split_time_group": time_group, "split_group": split_group, "split_reason": split_reason})
        result_rows.append(output)
        split_rows[split].append(output)
    audit = _audit(result_rows, { _target_key(row, index): row.get("dataset_split", "excluded") for index, row in enumerate(result_rows)}, { _target_key(row, index): row.get("split_time_group") for index, row in enumerate(result_rows)}, group_field, strategy)
    audit["excluded_missing_time_count"] = len(excluded)
    audit["input_rows"] = len(rows)
    audit["usable_rows"] = len(result_rows)
    return {"rows": result_rows, "excluded": excluded, "split_rows": dict(split_rows), "audit": audit}


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


def _sqlite_type(column: str, rows: list[dict[str, Any]]) -> str:
    if column.endswith("_id") or column.endswith("_status") or column in {"target_source_id", "target_station_id", "target_scene_id", "target_variable_code", "target_time_bucket", "target_category", "target_feature_row_key", "quality_flags", "leakage_check", "dataset_split", "split_time_group", "split_group", "split_reason", "temperature_degree_days_basis"}:
        return "TEXT"
    values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
    numeric = 0
    for value in values:
        try:
            float(value)
            numeric += 1
        except (TypeError, ValueError):
            pass
    return "REAL" if values and numeric / len(values) >= 0.8 else "TEXT"


def _write_sqlite(path: Path, rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS experiment_dataset")
        connection.execute("DROP TABLE IF EXISTS experiment_split_summary")
        if rows:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            definitions = [f'"{column}" {_sqlite_type(column, rows)}' for column in columns]
            connection.execute(f'CREATE TABLE experiment_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            sql = f'INSERT INTO experiment_dataset ({",".join(chr(34)+column+chr(34) for column in columns)}) VALUES ({",".join("?" for _ in columns)})'
            connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if isinstance(row.get(column), (list, dict)) else row.get(column) for column in columns) for row in rows])
        else:
            connection.execute("CREATE TABLE experiment_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        connection.execute("CREATE TABLE experiment_split_summary (dataset_split TEXT PRIMARY KEY, row_count INTEGER, min_time_group TEXT, max_time_group TEXT, unique_groups INTEGER, unique_target_variables INTEGER, missing_feature_rate REAL)")
        connection.executemany("INSERT INTO experiment_split_summary VALUES (?,?,?,?,?,?,?)", [(row["dataset_split"], row["row_count"], row["min_time_group"], row["max_time_group"], row["unique_groups"], row["unique_target_variables"], row["missing_feature_rate"]) for row in summary])
        connection.commit()
    finally:
        connection.close()


def _summary(split_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for split in ("train", "validation", "test", "excluded_missing_time"):
        rows = split_rows.get(split, [])
        times = sorted(str(row.get("split_time_group") or "") for row in rows if row.get("split_time_group"))
        groups = {str(row.get("split_group") or "__MISSING__") for row in rows}
        variables = {str(row.get("target_variable_code") or "") for row in rows}
        missing = [float(row.get("feature_missing_count") or 0) for row in rows]
        observed = [float(row.get("feature_observed_count") or 0) + float(row.get("feature_missing_count") or 0) for row in rows]
        missing_rate = sum(missing) / sum(observed) if sum(observed) else None
        output.append({"dataset_split": split, "row_count": len(rows), "min_time_group": times[0] if times else None, "max_time_group": times[-1] if times else None, "unique_groups": len(groups), "unique_target_variables": len(variables), "missing_feature_rate": missing_rate})
    return output


def run_split(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, strategy: str = "time", train_fraction: float = 0.7, validation_fraction: float = 0.15, group_field: str = "target_station_id", validation_groups: set[str] | None = None, test_groups: set[str] | None = None, time_granularity: str = "day", manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    rows = _read_rows(input_path)
    result = split_dataset(rows, strategy=strategy, train_fraction=train_fraction, validation_fraction=validation_fraction, group_field=group_field, validation_groups=validation_groups, test_groups=test_groups, time_granularity=time_granularity)
    if result["audit"]["duplicate_target_key_count"] > 0 or not result["audit"]["time_order_ok"]:
        raise ValueError("experiment split audit failed: duplicate target keys or non-chronological time split")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or root / "storage" / "exports" / f"experiment_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {"experiment_dataset": output_root / "experiment_dataset.csv", "train": output_root / "train.csv", "validation": output_root / "validation.csv", "test": output_root / "test.csv", "excluded": output_root / "excluded_missing_time.csv", "summary": output_root / "experiment_split_summary.csv", "audit": output_root / "experiment_leakage_audit.json"}
    _write_csv(files["experiment_dataset"], result["rows"])
    for split in ("train", "validation", "test"):
        _write_csv(files[split], result["split_rows"].get(split, []))
    excluded = result["excluded"]
    for row in excluded:
        row.setdefault("dataset_split", "excluded_missing_time")
    _write_csv(files["excluded"], excluded)
    summaries = _summary({**result["split_rows"], "excluded_missing_time": excluded})
    _write_csv(files["summary"], summaries)
    files["audit"].write_text(json.dumps(result["audit"], ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or root / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["rows"], summaries)
    manifest: dict[str, Any] = {"run_id": run_id or f"experiment_{stamp}", "status": "completed", "input": str(input_path), "strategy": strategy, "group_field": group_field, "time_granularity": time_granularity, "fractions": {"train": train_fraction, "validation": validation_fraction, "test": 1 - train_fraction - validation_fraction}, "audit": result["audit"], "summary": summaries, "files": {key: str(value) for key, value in {**files, "database": database}.items()}}
    manifest_path = manifest_path or root / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
