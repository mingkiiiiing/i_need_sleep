"""Assemble forecast rows and local-day summaries for ECMWF predictions.

The assembly keeps forecast reference time (the information-availability
boundary) separate from valid time (the time being predicted).  It does not
fill missing forecast steps or turn a low-frequency forecast into an observed
series.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")


def _float(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _time(value: Any) -> datetime:
    if value in (None, ""):
        raise ValueError("forecast time is required")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"forecast time must include timezone: {value}")
    return parsed


def _percentile(values: list[float], probability: float) -> float | None:
    values = sorted(value for value in values if value is not None and math.isfinite(value))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def _read_forecast_csv(path: Path) -> list[dict[str, Any]]:
    required = {"forecast_reference_time", "valid_time", "lead_hours", "variable_code", "value", "unit"}
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            missing = required - set(row)
            if missing:
                raise ValueError(f"{path}:{line_number} missing forecast fields {sorted(missing)}")
            reference = _time(row["forecast_reference_time"])
            valid = _time(row["valid_time"])
            if valid < reference:
                raise ValueError(f"{path}:{line_number} valid_time precedes forecast_reference_time")
            lead = _float(row["lead_hours"])
            expected_lead = (valid - reference).total_seconds() / 3600.0
            if lead is None or abs(lead - expected_lead) > 1e-6:
                raise ValueError(f"{path}:{line_number} lead_hours does not match reference/valid time")
            value = _float(row["value"])
            rows.append({
                **row,
                "forecast_reference_time": reference.isoformat(),
                "valid_time": valid.isoformat(),
                "lead_hours": lead,
                "value": value,
                "station_id": row.get("station_id") or "TAIHU_AREA_MEAN",
                "ensemble_member": int(_float(row.get("ensemble_member")) or 0),
                "model_name": row.get("model_name") or "ECMWF",
                "source_id": row.get("source_id") or "ecmwf_open_ifs_aifs",
            })
    return rows


def _daily_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # ECMWF total precipitation is accumulated from the forecast reference
    # time; derive non-negative step increments before daily totals.
    accumulation_groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["variable_code"] == "precipitation":
            accumulation_groups[(row["source_id"], row["model_name"], row["forecast_reference_time"], int(row.get("ensemble_member", 0)))].append(row)
    for group in accumulation_groups.values():
        previous: float | None = None
        for row in sorted(group, key=lambda item: _time(item["valid_time"])):
            current = row["value"]
            row["_precip_increment"] = None if current is None else (current if previous is None else max(current - previous, 0.0))
            if current is not None:
                previous = current
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        local_date = _time(row["valid_time"]).astimezone(LOCAL_ZONE).date().isoformat()
        grouped[(row["source_id"], row["model_name"], row["forecast_reference_time"], local_date, row["variable_code"])].append(row)
    summaries: list[dict[str, Any]] = []
    for (source_id, model_name, reference, local_date, variable), items in sorted(grouped.items()):
        numeric = [row["value"] for row in items if row["value"] is not None]
        unit = next((row.get("unit") for row in items if row.get("unit")), None)
        members = sorted({int(row.get("ensemble_member", 0)) for row in items})
        member_values: dict[int, list[float]] = defaultdict(list)
        for row in items:
            if row["value"] is not None:
                member_values[int(row.get("ensemble_member", 0))].append(row["value"])
        if variable == "precipitation":
            member_daily_map: dict[int, float] = defaultdict(float)
            for row in items:
                if row.get("_precip_increment") is not None:
                    member_daily_map[int(row.get("ensemble_member", 0))] += row["_precip_increment"]
            member_daily = list(member_daily_map.values())
            cumulative = sum(row["_precip_increment"] for row in items if row.get("_precip_increment") is not None)
        else:
            member_daily = [sum(values) / len(values) for values in member_values.values() if values]
            cumulative = None
        summaries.append({
            "source_id": source_id,
            "model_name": model_name,
            "forecast_reference_time": reference,
            "valid_date_local": local_date,
            "variable_code": variable,
            "unit": unit,
            "sample_count": len(numeric),
            "ensemble_member_count": len(members),
            "mean_value": sum(numeric) / len(numeric) if numeric else None,
            "max_value": max(numeric) if numeric else None,
            "min_value": min(numeric) if numeric else None,
            "cumulative_value": cumulative,
            "p05_value": _percentile(member_daily, 0.05),
            "p50_value": _percentile(member_daily, 0.50),
            "p95_value": _percentile(member_daily, 0.95),
            "aggregation_timezone": "Asia/Shanghai",
        })
    return summaries


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            DROP TABLE IF EXISTS forecast_values;
            DROP TABLE IF EXISTS forecast_daily_summary;
            CREATE TABLE forecast_values (
                source_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                station_id TEXT NOT NULL,
                reference_time_utc TEXT NOT NULL,
                valid_time_utc TEXT NOT NULL,
                variable_code TEXT NOT NULL,
                lead_hours REAL NOT NULL,
                ensemble_member INTEGER NOT NULL,
                value REAL,
                unit TEXT,
                quality_code TEXT,
                value_origin TEXT NOT NULL,
                source_parameter TEXT,
                source_file TEXT,
                PRIMARY KEY(source_id, model_name, station_id, reference_time_utc, valid_time_utc, variable_code, ensemble_member)
            );
            CREATE TABLE forecast_daily_summary (
                source_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                forecast_reference_time TEXT NOT NULL,
                valid_date_local TEXT NOT NULL,
                variable_code TEXT NOT NULL,
                unit TEXT,
                sample_count INTEGER NOT NULL,
                ensemble_member_count INTEGER NOT NULL,
                mean_value REAL,
                max_value REAL,
                min_value REAL,
                cumulative_value REAL,
                p05_value REAL,
                p50_value REAL,
                p95_value REAL,
                aggregation_timezone TEXT NOT NULL,
                PRIMARY KEY(source_id, model_name, forecast_reference_time, valid_date_local, variable_code)
            );
            CREATE INDEX idx_forecast_values_valid ON forecast_values(valid_time_utc);
            CREATE INDEX idx_forecast_values_reference ON forecast_values(reference_time_utc);
            """
        )
        connection.executemany(
            "INSERT INTO forecast_values VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(row["source_id"], row["model_name"], row["station_id"], row["forecast_reference_time"], row["valid_time"], row["variable_code"], row["lead_hours"], row["ensemble_member"], row["value"], row.get("unit"), row.get("quality_code"), "forecast", row.get("source_parameter"), row.get("raw_grib_path")) for row in rows],
        )
        connection.executemany(
            "INSERT INTO forecast_daily_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [tuple(item.get(key) for key in ("source_id", "model_name", "forecast_reference_time", "valid_date_local", "variable_code", "unit", "sample_count", "ensemble_member_count", "mean_value", "max_value", "min_value", "cumulative_value", "p05_value", "p50_value", "p95_value", "aggregation_timezone")) for item in summaries],
        )
        connection.commit()


def assemble_forecast_values(input_csv: Path, output_root: Path | None = None, database: Path | None = None) -> dict[str, Any]:
    """Create forecast_values and daily summaries from P05-01 area means."""
    input_csv = Path(input_csv)
    rows = _read_forecast_csv(input_csv)
    output_root = Path(output_root) if output_root else input_csv.parent
    output_root.mkdir(parents=True, exist_ok=True)
    summaries = _daily_summary(rows)
    values_path = output_root / "forecast_values.csv"
    daily_path = output_root / "forecast_daily_summary.csv"
    database = Path(database) if database else output_root / "ecmwf_forecast_values.sqlite"
    _write_csv(values_path, rows)
    _write_csv(daily_path, summaries)
    _write_sqlite(database, rows, summaries)
    reference_times = sorted({row["forecast_reference_time"] for row in rows})
    valid_times = sorted({row["valid_time"] for row in rows})
    return {
        "status": "completed", "input": str(input_csv), "forecast_values": str(values_path),
        "daily_summary": str(daily_path), "database": str(database), "input_rows": len(rows),
        "daily_rows": len(summaries), "reference_times": reference_times, "valid_time_start": valid_times[0] if valid_times else None,
        "valid_time_end": valid_times[-1] if valid_times else None, "max_lead_hours": max((row["lead_hours"] for row in rows), default=0),
        "ensemble_members": sorted({row["ensemble_member"] for row in rows}),
    }


__all__ = ["assemble_forecast_values"]
