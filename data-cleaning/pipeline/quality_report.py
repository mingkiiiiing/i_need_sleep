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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
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
    suspect_rows: list[dict[str, Any]] | None = None,
    conflict_rows: list[dict[str, Any]] | None = None,
    duplicate_audit_rows: list[dict[str, Any]] | None = None,
    normalized_rows: list[dict[str, Any]] | None = None,
    as_of: datetime | None = None,
    max_staleness_days: float = 30.0,
    low_frequency_hours: float = 24.0,
) -> dict[str, Any]:
    rejected_rows = rejected_rows or []
    pending_rows = pending_rows or []
    issue_rows = issue_rows or []
    suspect_rows = suspect_rows or []
    conflict_rows = conflict_rows or []
    duplicate_audit_rows = duplicate_audit_rows or []

    # ``normalized_rows`` is the denominator for coverage and missingness when
    # available.  This preserves records rejected or held for review instead of
    # making the report silently describe only the model-ready table.
    if normalized_rows is not None:
        all_rows = list(normalized_rows)
    else:
        all_rows = list(cleaned_rows)
        for collection in (rejected_rows, pending_rows, suspect_rows, conflict_rows):
            all_rows.extend(collection)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        groups[_group_key(row)].append(row)
    # Keep explicit downstream-only groups even when a supplied normalized file
    # does not contain an issue row (for example a manually created rejection).
    for row in cleaned_rows + rejected_rows + pending_rows + suspect_rows + conflict_rows:
        groups.setdefault(_group_key(row), [])
    for row in issue_rows:
        source = str(row.get("source_id") or "__missing__")
        variable = str(row.get("variable_code") or "__missing__")
        matching = [key for key in groups if key[0] == source and key[1] == variable]
        if not matching:
            groups.setdefault((source, variable, "__issue__"), [])

    duplicate_counts = Counter()
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for row in cleaned_rows:
        key = _row_key(row)
        if key in seen:
            duplicate_counts[_group_key(row)] += 1
        seen.add(key)
    rejected_counts = Counter(_group_key(row) for row in rejected_rows)
    pending_counts = Counter(_group_key(row) for row in pending_rows)
    suspect_counts = Counter(_group_key(row) for row in suspect_rows)
    conflict_counts = Counter(_group_key(row) for row in conflict_rows)
    cleaned_counts = Counter(_group_key(row) for row in cleaned_rows)
    issue_counts_by_source_variable = Counter((str(row.get("source_id") or "__missing__"), str(row.get("variable_code") or "__missing__")) for row in issue_rows)
    issue_code_counts_by_source_variable: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for issue in issue_rows:
        issue_code_counts_by_source_variable[(str(issue.get("source_id") or "__missing__"), str(issue.get("variable_code") or "__missing__"))][str(issue.get("issue_code") or "unknown")] += 1
    audit_exact = Counter()
    audit_conflict = Counter()
    for audit in duplicate_audit_rows:
        key = (str(audit.get("source_id") or "__missing__"), str(audit.get("variable_code") or "__missing__"))
        action = str(audit.get("action") or "")
        if action == "deduplicated_exact":
            audit_exact[key] += 1
        elif action == "pending_conflict":
            audit_conflict[key] += 1
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
        source_variable = (source_id, variable_code)
        issue_count = issue_counts_by_source_variable[source_variable]
        issue_code_counts = issue_code_counts_by_source_variable.get(source_variable, Counter())
        input_count = len(current)
        missing_count = input_count - len(values)
        imputed_count = sum(1 for row in current if str(row.get("is_imputed")).casefold() in {"true", "1", "yes"})
        proxy_count = sum(count for origin, count in origin_counts.items() if origin in {"proxy", "forecast_proxy"})
        anomaly_rate = issue_count / input_count if input_count else 1.0 if issue_count else 0.0
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
            "input_rows": input_count,
            "raw_rows": input_count,
            "cleaned_rows": cleaned_counts[key],
            "suspect_rows": suspect_counts[key],
            "rejected_rows": rejected_counts[key],
            "pending_conflict_rows": conflict_counts[key],
            "valid_value_rows": len(values),
            "missing_value_rows": missing_count,
            "missing_rate": round(missing_count / input_count, 6) if input_count else 1.0,
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
            "pending_imputation_rows": pending_counts[key],
            "issue_rows": issue_count,
            "anomaly_rows": issue_count,
            "anomaly_rate": round(anomaly_rate, 6),
            "quality_flagged_rows": flag_count,
            "imputed_rows": imputed_count,
            "imputation_rate": round(imputed_count / input_count, 6) if input_count else 0.0,
            "proxy_rows": proxy_count,
            "proxy_rate": round(proxy_count / input_count, 6) if input_count else 0.0,
            "exact_duplicates_removed": audit_exact[source_variable],
            "conflict_audit_rows": audit_conflict[source_variable],
            "issue_code_counts": json.dumps(dict(sorted(issue_code_counts.items())), ensure_ascii=False, sort_keys=True),
            "value_origins": json.dumps(dict(origin_counts), ensure_ascii=False, sort_keys=True),
            "status": status,
        })
    source_coverage = {
        source: {
            "variable_groups": sum(1 for row in rows if row["source_id"] == source),
            "input_rows": sum(row["input_rows"] for row in rows if row["source_id"] == source),
            "cleaned_rows": sum(row["cleaned_rows"] for row in rows if row["source_id"] == source),
            "valid_value_rows": sum(row["valid_value_rows"] for row in rows if row["source_id"] == source),
            "missing_rate": round(sum(row["missing_value_rows"] for row in rows if row["source_id"] == source) / max(sum(row["input_rows"] for row in rows if row["source_id"] == source), 1), 6),
        }
        for source in sorted({row["source_id"] for row in rows})
    }
    freshness_counts = Counter(row["freshness_status"] for row in rows)
    total_input = len(all_rows)
    total_missing = sum(row["missing_value_rows"] for row in rows)
    total_imputed = sum(row["imputed_rows"] for row in rows)
    total_proxy = sum(row["proxy_rows"] for row in rows)
    overall = {
        "input_rows": total_input,
        "raw_rows": total_input,
        "cleaned_rows": len(cleaned_rows),
        "suspect_rows": len(suspect_rows),
        "variable_groups": len(rows),
        "sources": len({row["source_id"] for row in rows}),
        "rejected_rows": len(rejected_rows),
        "pending_imputation_rows": len(pending_rows),
        "pending_conflict_rows": len(conflict_rows),
        "missing_value_rows": total_missing,
        "missing_rate": round(total_missing / total_input, 6) if total_input else 1.0,
        "issue_rows": len(issue_rows),
        "anomaly_rows": len(issue_rows),
        "anomaly_rate": round(len(issue_rows) / total_input, 6) if total_input else 1.0 if issue_rows else 0.0,
        "imputed_rows": total_imputed,
        "imputation_rate": round(total_imputed / total_input, 6) if total_input else 0.0,
        "proxy_rows": total_proxy,
        "proxy_rate": round(total_proxy / total_input, 6) if total_input else 0.0,
        "duplicate_key_rows": sum(duplicate_counts.values()),
        "exact_duplicates_removed": sum(audit_exact.values()),
        "conflict_audit_rows": sum(audit_conflict.values()),
        "available_groups": sum(1 for row in rows if row["status"] == "available"),
        "low_frequency_groups": sum(1 for row in rows if row["frequency_status"] == "low_frequency"),
        "stale_groups": sum(1 for row in rows if row["freshness_status"] == "stale"),
        "missing_groups": sum(1 for row in rows if row["status"] == "missing"),
        "issue_only_groups": sum(1 for row in rows if row["status"] == "issue_only"),
        "source_coverage": source_coverage,
        "freshness_status_counts": dict(sorted(freshness_counts.items())),
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
    normalized_path: Path | None = None,
    suspect_path: Path | None = None,
    pending_conflicts_path: Path | None = None,
    duplicate_audit_path: Path | None = None,
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
    normalized_path = normalized_path or cleaned_path.parent / "normalized_observations.csv"
    suspect_path = suspect_path or cleaned_path.parent / "suspect_records.csv"
    pending_conflicts_path = pending_conflicts_path or cleaned_path.parent / "pending_conflicts.csv"
    duplicate_audit_path = duplicate_audit_path or cleaned_path.parent / "duplicate_audit.csv"
    result = build_quality_report(
        _read_csv(cleaned_path),
        rejected_rows=_read_csv(rejected_path),
        pending_rows=_read_csv(pending_path),
        issue_rows=_read_csv(issues_path),
        suspect_rows=_read_csv(suspect_path),
        conflict_rows=_read_csv(pending_conflicts_path),
        duplicate_audit_rows=_read_csv(duplicate_audit_path),
        normalized_rows=_read_csv(normalized_path) or None,
        as_of=as_of,
        max_staleness_days=max_staleness_days,
        low_frequency_hours=low_frequency_hours,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "quality_report.csv"
    overall_path = output_root / "quality_report_overall.json"
    _write_csv(report_path, result["rows"])
    overall_path.write_text(json.dumps(result["overall"], ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or root / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["rows"], result["overall"])
    overall = result["overall"]
    warning = any(overall.get(key, 0) for key in ("issue_rows", "suspect_rows", "rejected_rows", "pending_imputation_rows", "pending_conflict_rows"))
    manifest = {
        "run_id": run_id or f"quality_report_{stamp}",
        "status": "completed_with_warnings" if warning else "completed",
        "input": str(cleaned_path),
        "inputs": {
            "normalized": str(normalized_path) if normalized_path.exists() else None,
            "cleaned": str(cleaned_path),
            "rejected": str(rejected_path) if rejected_path.exists() else None,
            "suspect": str(suspect_path) if suspect_path.exists() else None,
            "pending_imputation": str(pending_path) if pending_path.exists() else None,
            "pending_conflicts": str(pending_conflicts_path) if pending_conflicts_path.exists() else None,
            "issues": str(issues_path) if issues_path.exists() else None,
            "duplicate_audit": str(duplicate_audit_path) if duplicate_audit_path.exists() else None,
        },
        "files": {"quality_report": str(report_path), "overall": str(overall_path), "database": str(database)},
        "coverage": overall.get("source_coverage", {}),
        "overall": overall,
    }
    manifest_path = Path(manifest_path) if manifest_path is not None else manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
