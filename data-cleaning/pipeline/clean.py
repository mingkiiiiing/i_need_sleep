from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .normalize import normalize_raw_file
from .provenance import manifest_root
from .qc import quality_control
from .impute import impute_short_gaps
from .units import standardize_units


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not materialized:
        path.write_text("", encoding="utf-8")
        return 0
    columns: list[str] = []
    for row in materialized:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    return len(materialized)


def _write_sqlite(path: Path, cleaned: list[dict[str, Any]], imputation_candidates: list[dict[str, Any]], rejected: list[dict[str, Any]], issues: list[dict[str, Any]], catalog: list[dict[str, Any]], archives: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The SQLite file is a materialized result for one cleaning run. Rebuild
    # it so rerunning the same raw inputs cannot silently append duplicates.
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS cleaned_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_row TEXT NOT NULL,
                station_id TEXT,
                scene_id TEXT,
                observed_at TEXT,
                longitude REAL,
                latitude REAL,
                variable_code TEXT NOT NULL,
                source_parameter TEXT,
                observed_value REAL,
                clean_value REAL,
                unit TEXT,
                source_unit TEXT,
                value_origin TEXT NOT NULL,
                conversion_rule TEXT,
                is_imputed INTEGER NOT NULL,
                imputation_method TEXT,
                imputation_confidence REAL,
                quality_flags TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rejected_records AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS imputation_candidates AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS qc_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                source_file TEXT,
                source_row TEXT,
                variable_code TEXT,
                issue_code TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                observed_value REAL
            );
            CREATE TABLE IF NOT EXISTS remote_scene_catalog (
                source_id TEXT,
                source_file TEXT,
                source_row TEXT,
                scene_id TEXT,
                acquisition_at TEXT,
                longitude REAL,
                latitude REAL,
                cloud_cover REAL,
                asset_names TEXT,
                product_href TEXT
            );
            CREATE TABLE IF NOT EXISTS source_archives (
                source_id TEXT,
                source_file TEXT,
                source_row TEXT,
                title TEXT,
                doi TEXT,
                file_key TEXT,
                file_size_bytes INTEGER,
                checksum TEXT,
                download_url TEXT,
                archive_downloaded INTEGER
            );
            """
        )

        observation_columns = [
            "source_id", "source_file", "source_row", "station_id", "scene_id", "observed_at",
            "longitude", "latitude", "variable_code", "source_parameter", "observed_value", "clean_value",
            "unit", "source_unit", "value_origin", "conversion_rule", "is_imputed", "imputation_method", "imputation_confidence", "quality_flags",
        ]
        placeholders = ",".join("?" for _ in observation_columns)
        values = [
            tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in observation_columns)
            for row in cleaned
        ]
        if values:
            connection.executemany(
                f"INSERT INTO cleaned_observations ({','.join(observation_columns)}) VALUES ({placeholders})",
                values,
            )
        imputation_values = [
            tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in observation_columns)
            for row in imputation_candidates
        ]
        if imputation_values:
            connection.executemany(
                f"INSERT INTO imputation_candidates ({','.join(observation_columns)}) VALUES ({placeholders})",
                imputation_values,
            )
        rejected_values = [
            tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in observation_columns)
            for row in rejected
        ]
        if rejected_values:
            connection.executemany(
                f"INSERT INTO rejected_records ({','.join(observation_columns)}) VALUES ({placeholders})",
                rejected_values,
            )
        if issues:
            connection.executemany(
                "INSERT INTO qc_issues (source_id,source_file,source_row,variable_code,issue_code,severity,message,observed_value) VALUES (?,?,?,?,?,?,?,?)",
                [tuple(issue.get(key) for key in ["source_id", "source_file", "source_row", "variable_code", "issue_code", "severity", "message", "observed_value"]) for issue in issues],
            )
        if catalog:
            connection.executemany(
                "INSERT INTO remote_scene_catalog VALUES (?,?,?,?,?,?,?,?,?,?)",
                [tuple(row.get(key) if key != "asset_names" else json.dumps(row.get(key), ensure_ascii=False) for key in ["source_id", "source_file", "source_row", "scene_id", "acquisition_at", "longitude", "latitude", "cloud_cover", "asset_names", "product_href"]) for row in catalog],
            )
        if archives:
            connection.executemany(
                "INSERT INTO source_archives VALUES (?,?,?,?,?,?,?,?,?,?)",
                [tuple(row.get(key) for key in ["source_id", "source_file", "source_row", "title", "doi", "file_key", "file_size_bytes", "checksum", "download_url", "archive_downloaded"]) for row in archives],
            )
        connection.commit()
    finally:
        connection.close()


def run_cleaning(
    raw_root: Path | None = None,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    manifest_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    raw_root = raw_root or PACKAGE_ROOT / "storage" / "raw"
    supported_suffixes = {".json", ".csv", ".tsv", ".xlsx"}
    files = sorted(path for path in raw_root.glob("*/*") if path.is_file() and path.suffix.casefold() in supported_suffixes)
    observations: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    source_files: list[str] = []
    for path in files:
        normalized = normalize_raw_file(path)
        observations.extend(normalized["observations"])
        catalog.extend(normalized["catalog"])
        archives.extend(normalized["archives"])
        source_files.append(str(path))

    observations = standardize_units(observations)["records"]
    qc = quality_control(observations)
    imputation = impute_short_gaps(qc["cleaned"] + qc["imputation_candidates"])
    cleaned_records = [row for row in imputation["records"] if row.get("clean_value") is not None]
    pending_records = imputation["pending"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_root = Path(output_root) if output_root is not None else PACKAGE_ROOT / "storage" / "exports" / f"cleaning_{stamp}"
    normalized_root = PACKAGE_ROOT / "storage" / "silver" if output_root is None else export_root
    database_path = Path(database) if database is not None else PACKAGE_ROOT / "storage" / "data_cleaning.db"
    files_out = {
        "normalized_observations": str(normalized_root / "normalized_observations.csv"),
        "cleaned_observations": str(export_root / "cleaned_observations.csv"),
        "rejected_records": str(export_root / "rejected_records.csv"),
        "qc_issues": str(export_root / "qc_issues.csv"),
        "remote_scene_catalog": str(export_root / "remote_scene_catalog.csv"),
        "source_archives": str(export_root / "source_archives.csv"),
        "database": str(database_path),
    }
    _write_csv(Path(files_out["normalized_observations"]), observations)
    _write_csv(Path(files_out["cleaned_observations"]), cleaned_records)
    files_out["imputation_candidates"] = str(export_root / "imputation_candidates.csv")
    _write_csv(Path(files_out["imputation_candidates"]), pending_records)
    _write_csv(Path(files_out["rejected_records"]), qc["rejected"])
    _write_csv(Path(files_out["qc_issues"]), qc["issues"])
    _write_csv(Path(files_out["remote_scene_catalog"]), catalog)
    _write_csv(Path(files_out["source_archives"]), archives)
    _write_sqlite(database_path, cleaned_records, pending_records, qc["rejected"], qc["issues"], catalog, archives)

    result = {
        "run_id": run_id or f"cleaning_{stamp}",
        "status": "completed_with_warnings" if qc["issues"] else "completed",
        "input_files": source_files,
        "input_rows": len(observations),
        "clean_rows": len(cleaned_records),
        "imputed_rows": len(imputation["imputed"]),
        "pending_imputation_rows": len(pending_records),
        "rejected_rows": len(qc["rejected"]),
        "issue_count": len(qc["issues"]),
        "catalog_rows": len(catalog),
        "archive_rows": len(archives),
        "flag_counts": qc["flag_counts"],
        "files": files_out,
    }
    manifest = Path(manifest_path) if manifest_path is not None else manifest_root(PACKAGE_ROOT) / f"{result['run_id']}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = str(manifest)
    return result
