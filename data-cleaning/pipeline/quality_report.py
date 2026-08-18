from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from .provenance import manifest_root


UTC = timezone.utc


def _read_csv(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _time(value: Any) -> datetime | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "null", "nan", "NaN"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value in (None, "", "[]", "None", "null"):
        return []
    try:
        parsed = json.loads(str(value))
        return [str(item) for item in parsed] if isinstance(parsed, list) else [str(value)]
    except json.JSONDecodeError:
        return [str(value)]


def _group_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("source_id") or "__missing__"), str(row.get("variable_code") or "__missing__"), str(row.get("unit") or "__missing__"))


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row.get("source_id") or ""),
        str(row.get("station_id") or ""),
        str(row.get("scene_id") or ""),
        str(row.get("observed_at") or ""),
        str(row.get("variable_code") or ""),
        str(row.get("unit") or ""),
    )


def _median_interval(rows: list[dict[str, Any]]) -> float | None:
    series: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for row in rows:
        moment = _time(row.get("observed_at"))
        if moment is not None:
            series[(str(row.get("station_id") or ""), str(row.get("variable_code") or ""))].append(moment)
    intervals: list[float] = []
    for moments in series.values():
        ordered = sorted(set(moments))
        intervals.extend((right - left).total_seconds() / 3600.0 for left, right in zip(ordered, ordered[1:]))
    return median(intervals) if intervals else None


def build_quality_report(
    cleaned_rows: list[dict[str, Any]],
    *,
    rejected_rows: list[dict[str, Any]] | None = None,
    pending_rows: list[dict[str, Any]] | None = None,
    issue_rows: list[dict[str, Any]] | None = None,
    as_of: datetime | None = None,
    max_staleness_days: float = 30.0,
    low_frequency_hours: float = 24.0,
) -> dict[str, Any]:
    rejected_rows = rejected_rows or []
    pending_rows = pending_rows or []
    issue_rows = issue_rows or []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in cleaned_rows:
        groups[_group_key(row)].append(row)
    for row in rejected_rows + pending_rows:
        groups.setdefault(_group_key(row), [])
    for row in issue_rows:
        groups.setdefault((str(row.get("source_id") or "__missing__"), str(row.get("variable_code") or "__missing__"), "__issue__"), [])

    duplicate_counts = Counter()
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in cleaned_rows:
        key = _row_key(row)
        if key in seen:
            duplicate_counts[_group_key(row)] += 1
        seen.add(key)
    rejected_counts = Counter(_group_key(row) for row in rejected_rows)
    pending_counts = Counter(_group_key(row) for row in pending_rows)
    issue_counts = Counter((str(row.get("source_id") or "__missing__"), str(row.get("variable_code") or "__missing__"), "__issue__") for row in issue_rows)
    rows: list[dict[str, Any]] = []
    for key in sorted(groups):
        source_id, variable_code, unit = key
        current = groups[key]
        values = [_number(row.get("clean_value") if row.get("clean_value") not in (None, "") else row.get("observed_value")) for row in current]
        values = [value for value in values if value is not None]
        moments = [_time(row.get("observed_at")) for row in current]
        moments = [moment for moment in moments if moment is not None]
        latest = max(moments) if moments else None
        staleness_days = (as_of - latest).total_seconds() / 86400.0 if as_of and latest else None
        origin_counts = Counter(str(row.get("value_origin") or "unknown") for row in current)
        flag_count = sum(bool(_flags(row.get("quality_flags"))) for row in current)
        interval = _median_interval(current)
        frequency_status = "low_frequency" if interval is not None and interval > low_frequency_hours else "available" if interval is not None else "unknown"
        freshness_status = "stale" if staleness_days is not None and staleness_days > max_staleness_days else "fresh" if staleness_days is not None else "unknown"
        if not current and unit == "__issue__":
            status = "issue_only"
        elif not values:
            status = "missing"
        elif frequency_status == "low_frequency" and freshness_status == "stale":
            status = "stale_low_frequency"
        elif freshness_status == "stale":
            status = "stale"
        elif frequency_status == "low_frequency":
            status = "low_frequency"
        else:
            status = "available"
        rows.append({
            "source_id": source_id,
            "variable_code": variable_code,
            "unit": unit,
            "cleaned_rows": len(current),
            "valid_value_rows": len(values),
            "missing_value_rows": len(current) - len(values),
            "missing_rate": round((len(current) - len(values)) / len(current), 6) if current else 1.0,
            "min_value": min(values) if values else None,
            "max_value": max(values) if values else None,
            "mean_value": mean(values) if values else None,
            "station_count": len({str(row.get("station_id")) for row in current if row.get("station_id") not in (None, "")}),
            "time_start": min(moments).isoformat() if moments else None,
            "time_end": latest.isoformat() if latest else None,
            "median_interval_hours": interval,
            "frequency_status": frequency_status,
            "staleness_days": round(staleness_days, 6) if staleness_days is not None else None,
            "freshness_status": freshness_status,
            "duplicate_key_rows": duplicate_counts[key],
            "rejected_rows": rejected_counts[key],
            "pending_imputation_rows": pending_counts[key],
            "issue_rows": issue_counts[key],
            "quality_flagged_rows": flag_count,
            "imputed_rows": sum(1 for row in current if str(row.get("is_imputed")).casefold() in {"true", "1"}),
            "proxy_rows": sum(count for origin, count in origin_counts.items() if origin in {"proxy", "forecast_proxy"}),
            "value_origins": json.dumps(dict(origin_counts), ensure_ascii=False, sort_keys=True),
            "status": status,
        })
    overall = {
        "cleaned_rows": len(cleaned_rows),
        "variable_groups": len(rows),
        "sources": len({row["source_id"] for row in rows}),
        "rejected_rows": len(rejected_rows),
        "pending_imputation_rows": len(pending_rows),
        "issue_rows": len(issue_rows),
        "duplicate_key_rows": sum(duplicate_counts.values()),
        "available_groups": sum(1 for row in rows if row["status"] == "available"),
        "low_frequency_groups": sum(1 for row in rows if row["frequency_status"] == "low_frequency"),
        "stale_groups": sum(1 for row in rows if row["freshness_status"] == "stale"),
        "missing_groups": sum(1 for row in rows if row["status"] == "missing"),
        "issue_only_groups": sum(1 for row in rows if row["status"] == "issue_only"),
        "as_of": as_of.isoformat() if as_of else None,
        "max_staleness_days": max_staleness_days,
        "low_frequency_hours": low_frequency_hours,
    }
    return {"rows": rows, "overall": overall}


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if columns:
            writer.writeheader()
            writer.writerows(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]], overall: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS quality_report")
        connection.execute("DROP TABLE IF EXISTS quality_report_overall")
        if rows:
            columns = list(rows[0])
            definitions = ",".join(f'"{column}" TEXT' for column in columns)
            quoted_columns = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            connection.execute(f"CREATE TABLE quality_report ({definitions})")
            connection.executemany(f"INSERT INTO quality_report ({quoted_columns}) VALUES ({placeholders})", [[row.get(column) for column in columns] for row in rows])
        else:
            connection.execute("CREATE TABLE quality_report (source_id TEXT, variable_code TEXT, unit TEXT, status TEXT)")
        connection.execute("CREATE TABLE quality_report_overall (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO quality_report_overall VALUES (?, ?)", [(key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value) if value is not None else None) for key, value in overall.items()])
        connection.commit()
    finally:
        connection.close()


def run_quality_report(
    cleaned_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    rejected_path: Path | None = None,
    pending_path: Path | None = None,
    issues_path: Path | None = None,
    as_of: datetime | None = None,
    max_staleness_days: float = 30.0,
    low_frequency_hours: float = 24.0,
    manifest_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    cleaned_path = Path(cleaned_path)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or root / "storage" / "exports" / f"quality_report_{stamp}"
    rejected_path = rejected_path or cleaned_path.parent / "rejected_records.csv"
    pending_path = pending_path or cleaned_path.parent / "imputation_candidates.csv"
    issues_path = issues_path or cleaned_path.parent / "qc_issues.csv"
    result = build_quality_report(_read_csv(cleaned_path), rejected_rows=_read_csv(rejected_path), pending_rows=_read_csv(pending_path), issue_rows=_read_csv(issues_path), as_of=as_of, max_staleness_days=max_staleness_days, low_frequency_hours=low_frequency_hours)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "quality_report.csv"
    overall_path = output_root / "quality_report_overall.json"
    _write_csv(report_path, result["rows"])
    overall_path.write_text(json.dumps(result["overall"], ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or root / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["rows"], result["overall"])
    manifest = {"run_id": run_id or f"quality_report_{stamp}", "status": "completed", "input": str(cleaned_path), "files": {"quality_report": str(report_path), "overall": str(overall_path), "database": str(database)}, "overall": result["overall"]}
    manifest_path = Path(manifest_path) if manifest_path is not None else manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
