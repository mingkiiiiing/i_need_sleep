from __future__ import annotations

"""Construct future supervised labels for multi-horizon forecasting.

Labels are outcomes, not model inputs. A candidate must belong to the exact
same source/station/scene/variable series and occur strictly after the current
target time. No interpolation or forward filling is performed. Every
accepted label keeps its actual time gap and split provenance.
"""

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import manifest_root


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
HORIZON_WINDOWS: dict[str, tuple[float, float]] = {
    "horizon_1_3d": (1.0, 3.0),
    "horizon_7_15d": (7.0, 15.0),
    "horizon_30_90d": (30.0, 90.0),
}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_time(value: Any) -> datetime | None:
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
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _series_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(key) or "") for key in ("target_source_id", "target_station_id", "target_scene_id", "target_variable_code"))


def _target_key(row: dict[str, Any], index: int) -> str:
    return str(row.get("target_feature_row_key") or f"row_{index}")


def _choose_future(current: dict[str, Any], candidates: list[dict[str, Any]], lower: float, upper: float) -> tuple[dict[str, Any] | None, str, float | None]:
    current_time = _parse_time(current.get("target_time_bucket"))
    if current_time is None:
        return None, "current_time_invalid", None
    future_exists = False
    valid_candidates: list[tuple[float, float, dict[str, Any]]] = []
    for candidate in candidates:
        candidate_time = _parse_time(candidate.get("target_time_bucket"))
        if candidate_time is None or candidate_time <= current_time:
            continue
        future_exists = True
        gap_days = (candidate_time - current_time).total_seconds() / 86400.0
        value = _float(candidate.get("target_clean_value"))
        if lower <= gap_days <= upper and value is not None:
            midpoint = (lower + upper) / 2.0
            valid_candidates.append((abs(gap_days - midpoint), gap_days, candidate))
    if valid_candidates:
        _, gap_days, selected = min(valid_candidates, key=lambda item: (item[0], item[1], str(item[2].get("target_time_bucket") or "")))
        return selected, "accepted", gap_days
    if not future_exists:
        return None, "no_future_observation", None
    invalid_in_window = False
    for candidate in candidates:
        candidate_time = _parse_time(candidate.get("target_time_bucket"))
        if candidate_time is None or candidate_time <= current_time:
            continue
        gap_days = (candidate_time - current_time).total_seconds() / 86400.0
        if lower <= gap_days <= upper and _float(candidate.get("target_clean_value")) is None:
            invalid_in_window = True
            break
    return None, "future_target_invalid" if invalid_in_window else "no_observation_in_window", None


def build_horizon_labels(rows: list[dict[str, Any]], *, target_variable: str) -> dict[str, Any]:
    selected = [row for row in rows if str(row.get("target_variable_code") or "") == target_variable]
    series: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        if _parse_time(row.get("target_time_bucket")) is not None:
            series[_series_key(row)].append(row)
    for items in series.values():
        items.sort(key=lambda item: _parse_time(item.get("target_time_bucket")) or datetime.max.replace(tzinfo=UTC))
    output_rows: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []
    for index, row in enumerate(selected):
        output = dict(row)
        output["forecast_label_target_key"] = _target_key(row, index)
        for horizon, (lower, upper) in HORIZON_WINDOWS.items():
            selected_future, status, gap_days = _choose_future(row, series.get(_series_key(row), []), lower, upper)
            output[f"{horizon}_value"] = selected_future.get("target_clean_value") if selected_future else None
            output[f"{horizon}_time"] = selected_future.get("target_time_bucket") if selected_future else None
            output[f"{horizon}_gap_days"] = gap_days
            output[f"{horizon}_status"] = status
            output[f"{horizon}_source_id"] = selected_future.get("target_source_id") if selected_future else None
            output[f"{horizon}_station_id"] = selected_future.get("target_station_id") if selected_future else None
            output[f"{horizon}_scene_id"] = selected_future.get("target_scene_id") if selected_future else None
            output[f"{horizon}_split"] = selected_future.get("dataset_split") if selected_future else None
        output_rows.append(output)
    for horizon, (lower, upper) in HORIZON_WINDOWS.items():
        statuses = Counter(str(row.get(f"{horizon}_status") or "unknown") for row in output_rows)
        accepted_gaps = [_float(row.get(f"{horizon}_gap_days")) for row in output_rows if row.get(f"{horizon}_status") == "accepted"]
        accepted_gaps = [value for value in accepted_gaps if value is not None]
        split_boundary_count = sum(1 for row in output_rows if row.get(f"{horizon}_status") == "accepted" and row.get("dataset_split") not in (None, "", row.get(f"{horizon}_split")))
        accepted = statuses.get("accepted", 0)
        summary.append({
            "target_variable": target_variable,
            "horizon": horizon,
            "lower_days": lower,
            "upper_days": upper,
            "input_rows": len(output_rows),
            "accepted_rows": accepted,
            "availability_rate": accepted / len(output_rows) if output_rows else 0.0,
            "mean_gap_days": sum(accepted_gaps) / len(accepted_gaps) if accepted_gaps else None,
            "min_gap_days": min(accepted_gaps) if accepted_gaps else None,
            "max_gap_days": max(accepted_gaps) if accepted_gaps else None,
            "status_counts": json.dumps(dict(statuses), ensure_ascii=False),
            "split_boundary_count": split_boundary_count,
            "overall_status": "ready" if accepted else "blocked_no_labels",
        })
    return {"rows": output_rows, "summary": summary, "selected_rows": len(selected), "series_count": len(series)}


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
            writer.writerow(row)
    return len(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS forecast_label_dataset")
        connection.execute("DROP TABLE IF EXISTS forecast_label_summary")
        if rows:
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            definitions = []
            for column in columns:
                values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
                numeric = sum(_float(value) is not None for value in values)
                definitions.append(f'"{column}" {"REAL" if values and numeric / len(values) >= 0.8 else "TEXT"}')
            connection.execute(f'CREATE TABLE forecast_label_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            quoted = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(f"INSERT INTO forecast_label_dataset ({quoted}) VALUES ({placeholders})", [[row.get(column) for column in columns] for row in rows])
        else:
            connection.execute("CREATE TABLE forecast_label_dataset (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        connection.execute("CREATE TABLE forecast_label_summary (target_variable TEXT, horizon TEXT, lower_days REAL, upper_days REAL, input_rows INTEGER, accepted_rows INTEGER, availability_rate REAL, mean_gap_days REAL, min_gap_days REAL, max_gap_days REAL, status_counts TEXT, split_boundary_count INTEGER, overall_status TEXT)")
        connection.executemany("INSERT INTO forecast_label_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [[row.get(column) for column in ("target_variable", "horizon", "lower_days", "upper_days", "input_rows", "accepted_rows", "availability_rate", "mean_gap_days", "min_gap_days", "max_gap_days", "status_counts", "split_boundary_count", "overall_status")] for row in summary])
        connection.commit()
    finally:
        connection.close()


def run_horizon_labels(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, target_variable: str = "phytoplankton_biomass", manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    rows = _read_rows(input_path)
    result = build_horizon_labels(rows, target_variable=target_variable)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / f"horizon_labels_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {
        "dataset": output_root / "forecast_label_dataset.csv",
        "summary": output_root / "forecast_label_summary.csv",
        "audit": output_root / "forecast_label_audit.json",
    }
    _write_csv(files["dataset"], result["rows"])
    _write_csv(files["summary"], result["summary"])
    audit = {"target_variable": target_variable, "selected_rows": result["selected_rows"], "series_count": result["series_count"], "summary": result["summary"]}
    files["audit"].write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or STORAGE / "data_cleaning.db"
    _write_sqlite(database, result["rows"], result["summary"])
    manifest = {"run_id": run_id or f"horizon_labels_{stamp}", "status": "completed", "input": str(input_path), "target_variable": target_variable, "selected_rows": result["selected_rows"], "series_count": result["series_count"], "files": {key: str(value) for key, value in {**files, "database": database}.items()}, "summary": result["summary"]}
    manifest_path = manifest_path or manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
