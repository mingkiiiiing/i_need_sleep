from __future__ import annotations

"""Read-only preflight for authorized water-station exports.

Unlike ``waterstation-batch-dir``, this command does not run the main cleaner
and does not write the global cleaning database. It inventories files, removes
exact hash duplicates, parses supported formats, and runs the P0 station gate
on the combined standardized rows before an official batch is accepted.
"""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import manifest_root
from .sources.common import sha256_file
from .sources.water_station import normalize_water_station_file
from .station_validate import validate_station_rows


SUPPORTED_SUFFIXES = {".json", ".csv", ".tsv", ".xlsx"}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_sqlite(path: Path, inventory: list[dict[str, Any]], issues: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS preflight_inventory")
        connection.execute("DROP TABLE IF EXISTS preflight_issues")
        connection.execute("DROP TABLE IF EXISTS preflight_summary")
        connection.execute("CREATE TABLE preflight_inventory (input_path TEXT PRIMARY KEY, suffix TEXT, sha256 TEXT, status TEXT, row_count INTEGER, variables TEXT, error TEXT)")
        connection.executemany("INSERT INTO preflight_inventory VALUES (?,?,?,?,?,?,?)", [tuple(row.get(key) for key in ("input_path", "suffix", "sha256", "status", "row_count", "variables", "error")) for row in inventory])
        connection.execute("CREATE TABLE preflight_issues (source_row TEXT, station_id TEXT, variable_code TEXT, observed_at TEXT, issues TEXT, quality_flags TEXT)")
        connection.executemany("INSERT INTO preflight_issues VALUES (?,?,?,?,?,?)", [tuple(row.get(key) for key in ("source_row", "station_id", "variable_code", "observed_at", "issues", "quality_flags")) for row in issues])
        connection.execute("CREATE TABLE preflight_summary (status TEXT, files_discovered INTEGER, files_parsed INTEGER, duplicate_files_skipped INTEGER, parse_failures INTEGER, valid_rows INTEGER, issue_rows INTEGER, validation_status TEXT)")
        connection.execute("INSERT INTO preflight_summary VALUES (?,?,?,?,?,?,?,?)", (summary["status"], summary["files_discovered"], summary["files_parsed"], summary["duplicate_files_skipped"], summary["parse_failures"], summary["valid_rows"], summary["issue_rows"], summary["validation_status"]))
        connection.commit()
    finally:
        connection.close()


def run_water_station_preflight(
    input_root: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    source_id: str = "taihu_water_station_preflight",
    max_median_interval_hours: float = 6.0,
    max_gap_hours: float = 24.0,
    manifest_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    input_root = Path(input_root)
    if not input_root.is_dir():
        raise NotADirectoryError(input_root)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or root / "storage" / "exports" / f"waterstation_preflight_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in input_root.rglob("*") if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES)
    inventory: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    for input_path in files:
        digest = sha256_file(input_path)
        base = {"input_path": str(input_path), "suffix": input_path.suffix.casefold(), "sha256": digest}
        if digest in seen_hashes:
            inventory.append({**base, "status": "duplicate_hash_skipped", "row_count": 0, "variables": "", "error": f"same_content_as:{seen_hashes[digest]}"})
            continue
        seen_hashes[digest] = str(input_path)
        try:
            rows = normalize_water_station_file(input_path, source_id=source_id)
            all_rows.extend(rows)
            inventory.append({**base, "status": "parsed" if rows else "parsed_empty", "row_count": len(rows), "variables": ",".join(sorted({str(row.get("variable_code")) for row in rows if row.get("variable_code")})), "error": None})
        except Exception as exc:
            inventory.append({**base, "status": "parse_failed", "row_count": 0, "variables": "", "error": str(exc)})

    parsed_count = sum(row["status"] == "parsed" and row["row_count"] > 0 for row in inventory)
    duplicate_count = sum(row["status"] == "duplicate_hash_skipped" for row in inventory)
    parse_failures = sum(row["status"] == "parse_failed" for row in inventory)
    validation = validate_station_rows(all_rows, max_median_interval_hours=max_median_interval_hours, max_gap_hours=max_gap_hours) if all_rows else {"rows": [], "issues": [], "summary": {"status": "blocked_no_valid_files", "valid_rows": 0, "issue_rows": 0}}
    validation_summary = validation["summary"]
    status = "ready" if validation_summary.get("status") == "ready" else "blocked_by_quality_gate" if all_rows else "blocked_no_valid_files"
    summary = {
        "status": status,
        "files_discovered": len(files),
        "files_parsed": parsed_count,
        "duplicate_files_skipped": duplicate_count,
        "parse_failures": parse_failures,
        "valid_rows": validation_summary.get("valid_rows", 0),
        "issue_rows": validation_summary.get("issue_rows", 0),
        "validation_status": validation_summary.get("status", "blocked_no_valid_files"),
    }
    inventory_path = output_root / "preflight_inventory.csv"
    issues_path = output_root / "preflight_issues.csv"
    summary_path = output_root / "preflight_summary.json"
    _write_csv(inventory_path, inventory)
    _write_csv(issues_path, validation.get("issues", []))
    summary_path.write_text(json.dumps({**summary, "validation": validation_summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    database = database or output_root / "preflight.db"
    _write_sqlite(database, inventory, validation.get("issues", []), summary)
    manifest = {"run_id": run_id or f"waterstation_preflight_{stamp}", "status": status, "input_root": str(input_root), "source_id": source_id, "files": {"inventory": str(inventory_path), "issues": str(issues_path), "summary": str(summary_path), "database": str(database)}, "summary": summary, "validation": validation_summary, "next_step": "waterstation-batch-dir -> run-batch --through remediation" if status == "ready" else "fix or obtain authorized P0 station files, then rerun preflight"}
    manifest_path = manifest_path or manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
