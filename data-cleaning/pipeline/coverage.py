from __future__ import annotations

"""Audit source coverage against the short-term Taihu forecast requirements."""

import csv
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .provenance import manifest_root


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))

# A short-term forecast needs at least one high-frequency target and the
# following physical/ecological drivers. The target requirement is expressed
# as alternatives because chlorophyll-a, algae density and bloom area are
# different observable labels for the same forecast task.
REQUIREMENTS: dict[str, dict[str, Any]] = {
    "chlorophyll_a": {"role": "target", "target_alternative": True, "max_interval_hours": 6.0, "max_gap_hours": 24.0, "observed_required": True},
    "algae_density": {"role": "target", "target_alternative": True, "max_interval_hours": 6.0, "max_gap_hours": 24.0, "observed_required": True},
    "bloom_area_km2": {"role": "target", "target_alternative": True, "max_interval_hours": 6.0, "max_gap_hours": 24.0, "observed_required": False},
    "water_temperature": {"role": "driver", "target_alternative": False, "max_interval_hours": 6.0, "max_gap_hours": 24.0, "observed_required": True},
    "total_nitrogen": {"role": "driver", "target_alternative": False, "max_interval_hours": 72.0, "observed_required": True},
    "total_phosphorus": {"role": "driver", "target_alternative": False, "max_interval_hours": 72.0, "observed_required": True},
    "air_temperature": {"role": "driver", "target_alternative": False, "max_interval_hours": 24.0, "observed_required": False},
    "wind_speed": {"role": "driver", "target_alternative": False, "max_interval_hours": 24.0, "observed_required": False},
    "wind_direction": {"role": "driver", "target_alternative": False, "max_interval_hours": 24.0, "observed_required": False},
    "precipitation": {"role": "driver", "target_alternative": False, "max_interval_hours": 24.0, "observed_required": False},
    "shortwave_radiation": {"role": "driver", "target_alternative": False, "max_interval_hours": 24.0, "observed_required": False},
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


def _frequency(rows: list[dict[str, Any]]) -> tuple[str, float | None, float | None]:
    explicit = [str(row.get("frequency") or "").lower() for row in rows if row.get("frequency")]
    counts: dict[str, int] = defaultdict(int)
    for value in explicit:
        counts[value] += 1
    if counts:
        chosen = max(counts, key=counts.get)
    else:
        chosen = "unknown"
    series: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for row in rows:
        timestamp = _parse_time(row.get("time_bucket") or row.get("observed_at"))
        if timestamp is not None:
            series[(str(row.get("source_id") or ""), str(row.get("station_id") or ""))].append(timestamp)
    intervals: list[float] = []
    for timestamps in series.values():
        ordered = sorted(set(timestamps))
        intervals.extend((right - left).total_seconds() / 3600.0 for left, right in zip(ordered, ordered[1:]))
    interval = median(intervals) if intervals else None
    max_gap = max(intervals) if intervals else None
    if not counts and interval is not None:
        if interval <= 1.5:
            chosen = "hourly"
        elif interval <= 36:
            chosen = "daily"
        elif interval <= 192:
            chosen = "weekly"
        elif interval <= 960:
            chosen = "monthly"
        elif interval <= 2400:
            chosen = "quarterly"
        else:
            chosen = "annual_or_sparse"
    return chosen, interval, max_gap


def _status(variable: str, rows: list[dict[str, Any]], median_interval_hours: float | None, max_gap_hours: float | None) -> tuple[str, str]:
    requirement = REQUIREMENTS[variable]
    if not rows:
        return "missing", "no standard observation rows"
    valid = [row for row in rows if _float(row.get("clean_value") or row.get("observed_value") or row.get("target_clean_value")) is not None]
    if not valid:
        return "invalid_only", "rows exist but no numeric values"
    origins = {str(row.get("value_origin") or "observed").lower() for row in valid}
    proxy_only = origins and origins <= {"proxy", "remote_sensing", "derived", "imputed"}
    if requirement["observed_required"] and proxy_only:
        return "proxy_only", "target requires observed values"
    if median_interval_hours is None:
        return "frequency_unknown", "timestamps are insufficient to estimate cadence"
    if median_interval_hours > float(requirement["max_interval_hours"]):
        return "low_frequency", f"median interval {median_interval_hours:.1f}h exceeds {requirement['max_interval_hours']}h"
    allowed_gap = requirement.get("max_gap_hours")
    if allowed_gap is not None and max_gap_hours is not None and max_gap_hours > float(allowed_gap):
        return "low_frequency", f"maximum gap {max_gap_hours:.1f}h exceeds {allowed_gap}h"
    if proxy_only:
        return "proxy_available", "frequency is adequate but all values are proxy/derived"
    return "ready", "frequency and value origin meet requirement"


def build_coverage_audit(rows: list[dict[str, Any]], *, as_of: datetime | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(UTC)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        variable = str(row.get("variable_code") or row.get("target_variable_code") or "").strip()
        if variable in REQUIREMENTS:
            grouped[variable].append(row)
    matrix: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for variable, requirement in REQUIREMENTS.items():
        variable_rows = grouped.get(variable, [])
        valid_rows = [row for row in variable_rows if _float(row.get("clean_value") or row.get("observed_value") or row.get("target_clean_value")) is not None]
        timestamps = [_parse_time(row.get("time_bucket") or row.get("observed_at") or row.get("target_time_bucket")) for row in variable_rows]
        timestamps = [value for value in timestamps if value is not None]
        frequency, interval, max_gap = _frequency(variable_rows)
        status, reason = _status(variable, variable_rows, interval, max_gap)
        sources = sorted({str(row.get("source_id") or row.get("target_source_id") or "") for row in variable_rows if row.get("source_id") or row.get("target_source_id")})
        stations = sorted({str(row.get("station_id") or row.get("target_station_id") or "") for row in variable_rows if row.get("station_id") or row.get("target_station_id")})
        origins = sorted({str(row.get("value_origin") or "observed") for row in valid_rows})
        latest = max(timestamps) if timestamps else None
        staleness = (as_of - latest).total_seconds() / 86400.0 if latest else None
        freshness_status = "missing" if latest is None else "fresh" if staleness is not None and staleness <= 30.0 else "stale"
        record = {
            "variable_code": variable,
            "role": requirement["role"],
            "target_alternative": requirement["target_alternative"],
            "observed_required": requirement["observed_required"],
            "max_interval_hours": requirement["max_interval_hours"],
            "max_allowed_gap_hours": requirement.get("max_gap_hours"),
            "row_count": len(variable_rows),
            "valid_value_count": len(valid_rows),
            "source_count": len(sources),
            "source_ids": ",".join(sources),
            "station_count": len(stations),
            "station_ids": ",".join(stations),
            "value_origins": ",".join(origins),
            "min_time": min(timestamps).isoformat() if timestamps else None,
            "max_time": latest.isoformat() if latest else None,
            "staleness_days": staleness,
            "freshness_status": freshness_status,
            "frequency": frequency,
            "median_interval_hours": interval,
            "max_gap_hours": max_gap,
            "status": status,
            "status_reason": reason,
        }
        matrix.append(record)
        if status not in {"ready", "proxy_available"}:
            gaps.append({"variable_code": variable, "role": requirement["role"], "priority": "P0" if requirement["role"] == "target" or requirement["observed_required"] else "P1", "status": status, "gap": reason, "recommended_action": "接入高频浮标/自动站或授权的官方实时接口" if requirement["role"] == "target" else "接入小时级水文气象或数值预报驱动"})
        elif freshness_status == "stale":
            gaps.append({"variable_code": variable, "role": requirement["role"], "priority": "P1", "status": "stale", "gap": f"latest observation is {staleness:.1f} days before as_of", "recommended_action": "配置准实时增量更新或授权的预报接口"})
    target_ready = any(row["role"] == "target" and row["status"] == "ready" for row in matrix)
    required_drivers_ready = all(row["status"] in {"ready", "proxy_available"} for row in matrix if row["role"] == "driver" and row["observed_required"])
    operational_target_ready = any(row["role"] == "target" and row["status"] == "ready" and row["freshness_status"] == "fresh" for row in matrix)
    operational_required_drivers_ready = all(row["status"] in {"ready", "proxy_available"} and row["freshness_status"] == "fresh" for row in matrix if row["role"] == "driver" and row["observed_required"])
    return {"matrix": matrix, "gaps": gaps, "target_ready": target_ready, "required_drivers_ready": required_drivers_ready, "short_term_ready": target_ready and required_drivers_ready, "operational_target_ready": operational_target_ready, "operational_required_drivers_ready": operational_required_drivers_ready, "operational_short_term_ready": operational_target_ready and operational_required_drivers_ready, "as_of": as_of.isoformat()}


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


def _write_sqlite(path: Path, matrix: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS coverage_matrix")
        connection.execute("DROP TABLE IF EXISTS coverage_gaps")
        def write_table(name: str, rows: list[dict[str, Any]]) -> None:
            if not rows:
                connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                return
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
            connection.execute(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            quoted = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(f"INSERT INTO {name} ({quoted}) VALUES ({placeholders})", [[row.get(column) for column in columns] for row in rows])
        write_table("coverage_matrix", matrix)
        write_table("coverage_gaps", gaps)
        connection.commit()
    finally:
        connection.close()


def run_coverage(input_path: Path, output_root: Path | None = None, database: Path | None = None, *, as_of: datetime | None = None, manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    rows = _read_rows(input_path)
    result = build_coverage_audit(rows, as_of=as_of)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / f"coverage_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {"matrix": output_root / "coverage_matrix.csv", "gaps": output_root / "coverage_gaps.csv", "audit": output_root / "coverage_audit.json"}
    _write_csv(files["matrix"], result["matrix"])
    _write_csv(files["gaps"], result["gaps"])
    files["audit"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or STORAGE / "data_cleaning.db"
    _write_sqlite(database, result["matrix"], result["gaps"])
    manifest = {"run_id": run_id or f"coverage_{stamp}", "status": "completed", "input": str(input_path), "rows": len(rows), "short_term_ready": result["short_term_ready"], "operational_short_term_ready": result["operational_short_term_ready"], "target_ready": result["target_ready"], "required_drivers_ready": result["required_drivers_ready"], "files": {key: str(value) for key, value in {**files, "database": database}.items()}, "gap_count": len(result["gaps"]), "as_of": result["as_of"]}
    manifest_path = manifest_path or manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
