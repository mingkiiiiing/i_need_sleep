from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .normalize import normalize_raw_file, standardize_observation_rows
from .provenance import manifest_root
from .qc import DUPLICATE_KEY_FIELDS, quality_control
from .impute import impute_short_gaps


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
DEDUPLICATION_RULES = {}
try:
    with (PACKAGE_ROOT / "config" / "qc_rules.yml").open("r", encoding="utf-8") as _rules_handle:
        DEDUPLICATION_RULES = (yaml.safe_load(_rules_handle) or {}).get("deduplication") or {}
except (OSError, TypeError, yaml.YAMLError):  # keep cleaning importable in minimal environments
    DEDUPLICATION_RULES = {}
DUPLICATE_CONFLICT_CODE = str(DEDUPLICATION_RULES.get("conflict_issue_code") or "Q41")
DUPLICATE_IGNORED_FIELDS = {
    "source_file", "source_row", "source_record_id", "quality_flags", "record_status",
    "duplicate_count", "duplicate_source_rows", "duplicate_group_id", "conflict_group_id",
}


def _stable_token(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _business_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_stable_token(row.get(field)) for field in DUPLICATE_KEY_FIELDS)


def _value_fingerprint(row: dict[str, Any]) -> str:
    payload = {key: row.get(key) for key in sorted(row) if key not in DUPLICATE_IGNORED_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_duplicates(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve exact duplicates while isolating same-key value conflicts.

    The configured business key includes ``source_id``. Therefore records
    from different sources are deliberately kept as separate observations;
    this function never overwrites one source with another. Exact duplicates
    retain the first row and a provenance audit, while any same-key group with
    more than one value fingerprint is held in ``pending_conflicts``.
    """

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[_business_key(row)].append(row)

    retained: list[dict[str, Any]] = []
    pending_conflicts: list[dict[str, Any]] = []
    duplicate_audit: list[dict[str, Any]] = []
    exact_duplicates_removed = 0
    conflict_groups = 0

    for key, group in groups.items():
        fingerprints = {_value_fingerprint(row) for row in group}
        group_id = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:16]
        if len(fingerprints) == 1:
            first = group[0]
            if len(group) > 1:
                first["duplicate_count"] = len(group)
                first["duplicate_source_rows"] = [row.get("source_row") for row in group]
                first["duplicate_group_id"] = group_id
                exact_duplicates_removed += len(group) - 1
                for row in group:
                    duplicate_audit.append({
                        "duplicate_group_id": group_id,
                        "action": "retained_first" if row is first else "deduplicated_exact",
                        "source_id": row.get("source_id"),
                        "source_file": row.get("source_file"),
                        "source_row": row.get("source_row"),
                        "station_id": row.get("station_id"),
                        "observed_at": row.get("observed_at"),
                        "variable_code": row.get("variable_code"),
                        "fingerprint": _value_fingerprint(row),
                        "conflict_fingerprints": "",
                        "message": "exact canonical duplicate; first row retained" if row is first else "exact canonical duplicate removed from model table",
                    })
            retained.append(first)
            continue

        conflict_groups += 1
        fingerprint_text = ",".join(sorted(fingerprints))
        for row in group:
            row["record_status"] = "pending_conflict"
            row["conflict_group_id"] = group_id
            flags = list(row.get("quality_flags") or [])
            if DUPLICATE_CONFLICT_CODE not in flags:
                flags.append(DUPLICATE_CONFLICT_CODE)
            row["quality_flags"] = flags
            pending_conflicts.append(row)
            duplicate_audit.append({
                "duplicate_group_id": group_id,
                "action": "pending_conflict",
                "source_id": row.get("source_id"),
                "source_file": row.get("source_file"),
                "source_row": row.get("source_row"),
                "station_id": row.get("station_id"),
                "observed_at": row.get("observed_at"),
                "variable_code": row.get("variable_code"),
                "fingerprint": _value_fingerprint(row),
                "conflict_fingerprints": fingerprint_text,
                "message": "same source/station/time/variable has conflicting canonical values; manual review required",
            })

    return {
        "records": retained,
        "pending_conflicts": pending_conflicts,
        "duplicate_audit": duplicate_audit,
        "exact_duplicates_removed": exact_duplicates_removed,
        "conflict_groups": conflict_groups,
    }


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


def _write_sqlite(
    path: Path,
    cleaned: list[dict[str, Any]],
    imputation_candidates: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    archives: list[dict[str, Any]],
    suspect: list[dict[str, Any]] | None = None,
    pending_conflicts: list[dict[str, Any]] | None = None,
    duplicate_audit: list[dict[str, Any]] | None = None,
    wind_uv_audit: list[dict[str, Any]] | None = None,
) -> None:
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
                observed_at_utc TEXT,
                observed_at_local TEXT,
                time_status TEXT,
                source_timezone TEXT,
                longitude REAL,
                latitude REAL,
                variable_code TEXT NOT NULL,
                source_parameter TEXT,
                observed_value REAL,
                raw_value TEXT,
                clean_value REAL,
                unit TEXT,
                source_unit TEXT,
                raw_unit TEXT,
                value_origin TEXT NOT NULL,
                conversion_rule TEXT,
                is_imputed INTEGER NOT NULL,
                imputation_method TEXT,
                imputation_confidence REAL,
                quality_flags TEXT NOT NULL,
                missing_mechanism TEXT,
                missing_mechanism_detail TEXT,
                missing_mechanism_confidence TEXT,
                missing_imputation_policy TEXT,
                gap_class TEXT,
                imputation_status TEXT,
                imputation_block_reason TEXT,
                imputation_donor_left TEXT,
                imputation_donor_right TEXT,
                imputation_source_left TEXT,
                imputation_source_right TEXT,
                imputation_left_observed_at TEXT,
                imputation_right_observed_at TEXT,
                imputation_left_value REAL,
                imputation_right_value REAL,
                imputation_gap_start_at TEXT,
                imputation_gap_end_at TEXT,
                imputation_gap_start TEXT,
                imputation_gap_end TEXT,
                imputation_gap_steps INTEGER,
                imputation_interval_minutes REAL,
                imputation_donor_count INTEGER,
                observed_flag INTEGER,
                imputation_flag INTEGER,
                uncertainty_model TEXT,
                uncertainty_method TEXT,
                uncertainty_status TEXT,
                uncertainty_center REAL,
                uncertainty_lower REAL,
                uncertainty_upper REAL,
                uncertainty_width REAL,
                native_frequency TEXT,
                native_frequency_minutes REAL,
                native_frequency_source TEXT,
                preserved_native_frequency INTEGER,
                low_frequency_status TEXT,
                data_age_hours REAL,
                data_age_status TEXT,
                latest_observed_at TEXT,
                latest_observed_value REAL,
                latest_value_age_hours REAL,
                 feature_value REAL,
                 feature_value_observed_at TEXT,
                 feature_value_age_hours REAL,
                 feature_value_semantics TEXT,
                 wind_u_component REAL,
                 wind_v_component REAL,
                 wind_uv_status TEXT,
                 wind_uv_block_reason TEXT,
                 wind_uv_method TEXT,
                 wind_uv_direction_convention TEXT,
                 wind_uv_calm_threshold_mps REAL,
                 wind_uv_donor_left TEXT,
                 wind_uv_donor_right TEXT,
                 wind_uv_gap_steps INTEGER,
                 wind_uv_interval_minutes REAL,
                 wind_uv_speed_from_vector REAL
             );
            CREATE TABLE IF NOT EXISTS rejected_records AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS imputation_candidates AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS suspect_records AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS pending_conflicts AS SELECT * FROM cleaned_observations WHERE 0;
            CREATE TABLE IF NOT EXISTS duplicate_audit (
                duplicate_group_id TEXT NOT NULL,
                action TEXT NOT NULL,
                source_id TEXT,
                source_file TEXT,
                source_row TEXT,
                station_id TEXT,
                observed_at TEXT,
                variable_code TEXT,
                fingerprint TEXT,
                conflict_fingerprints TEXT,
                message TEXT NOT NULL
            );
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
            CREATE TABLE IF NOT EXISTS wind_uv_audit (
                record_id TEXT,
                source_id TEXT,
                station_id TEXT,
                scene_id TEXT,
                observed_at TEXT,
                variable_code TEXT,
                wind_uv_status TEXT,
                wind_uv_block_reason TEXT,
                wind_uv_method TEXT,
                wind_uv_donor_left TEXT,
                wind_uv_donor_right TEXT,
                wind_uv_gap_steps INTEGER,
                wind_uv_interval_minutes REAL,
                wind_uv_speed_from_vector REAL,
                wind_uv_direction_convention TEXT,
                wind_uv_calm_threshold_mps REAL,
                observed_flag INTEGER,
                imputation_flag INTEGER,
                clean_value REAL
            );
            """
        )

        observation_columns = [
            "source_id", "source_file", "source_row", "station_id", "scene_id", "observed_at", "observed_at_utc", "observed_at_local", "time_status", "source_timezone",
            "longitude", "latitude", "variable_code", "source_parameter", "observed_value", "raw_value", "clean_value",
            "unit", "source_unit", "raw_unit", "value_origin", "conversion_rule", "is_imputed", "imputation_method", "imputation_confidence", "quality_flags",
            "missing_mechanism", "missing_mechanism_detail", "missing_mechanism_confidence", "missing_imputation_policy", "gap_class",
            "imputation_status", "imputation_block_reason", "imputation_donor_left", "imputation_donor_right", "imputation_source_left", "imputation_source_right",
            "imputation_left_observed_at", "imputation_right_observed_at", "imputation_left_value", "imputation_right_value",
            "imputation_gap_start_at", "imputation_gap_end_at", "imputation_gap_start", "imputation_gap_end", "imputation_gap_steps", "imputation_interval_minutes", "imputation_donor_count",
            "observed_flag", "imputation_flag", "uncertainty_model", "uncertainty_method", "uncertainty_status", "uncertainty_center", "uncertainty_lower", "uncertainty_upper", "uncertainty_width",
            "native_frequency", "native_frequency_minutes", "native_frequency_source", "preserved_native_frequency", "low_frequency_status",
            "data_age_hours", "data_age_status", "latest_observed_at", "latest_observed_value", "latest_value_age_hours",
            "feature_value", "feature_value_observed_at", "feature_value_age_hours", "feature_value_semantics",
            "wind_u_component", "wind_v_component", "wind_uv_status", "wind_uv_block_reason", "wind_uv_method",
            "wind_uv_direction_convention", "wind_uv_calm_threshold_mps", "wind_uv_donor_left", "wind_uv_donor_right",
            "wind_uv_gap_steps", "wind_uv_interval_minutes", "wind_uv_speed_from_vector",
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
        suspect_values = [
            tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in observation_columns)
            for row in (suspect or [])
        ]
        if suspect_values:
            connection.executemany(
                f"INSERT INTO suspect_records ({','.join(observation_columns)}) VALUES ({placeholders})",
                suspect_values,
            )
        pending_conflict_values = [
            tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in observation_columns)
            for row in (pending_conflicts or [])
        ]
        if pending_conflict_values:
            connection.executemany(
                f"INSERT INTO pending_conflicts ({','.join(observation_columns)}) VALUES ({placeholders})",
                pending_conflict_values,
            )
        if duplicate_audit:
            connection.executemany(
                "INSERT INTO duplicate_audit (duplicate_group_id,action,source_id,source_file,source_row,station_id,observed_at,variable_code,fingerprint,conflict_fingerprints,message) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [tuple(row.get(key) for key in ["duplicate_group_id", "action", "source_id", "source_file", "source_row", "station_id", "observed_at", "variable_code", "fingerprint", "conflict_fingerprints", "message"]) for row in duplicate_audit],
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
        if wind_uv_audit:
            wind_columns = [
                "record_id", "source_id", "station_id", "scene_id", "observed_at", "variable_code",
                "wind_uv_status", "wind_uv_block_reason", "wind_uv_method", "wind_uv_donor_left",
                "wind_uv_donor_right", "wind_uv_gap_steps", "wind_uv_interval_minutes",
                "wind_uv_speed_from_vector", "wind_uv_direction_convention", "wind_uv_calm_threshold_mps",
                "observed_flag", "imputation_flag", "clean_value",
            ]
            connection.executemany(
                f"INSERT INTO wind_uv_audit ({','.join(wind_columns)}) VALUES ({','.join('?' for _ in wind_columns)})",
                [tuple(row.get(key) for key in wind_columns) for row in wind_uv_audit],
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
    raw_root = raw_root or STORAGE / "raw"
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

    observations = standardize_observation_rows(observations)["records"]
    deduplication = resolve_duplicates(observations)
    deduplicated_observations = deduplication["records"]
    pending_conflicts = deduplication["pending_conflicts"]
    duplicate_audit = deduplication["duplicate_audit"]
    qc = quality_control(deduplicated_observations)
    conflict_issues = [
        {
            "source_id": row.get("source_id"),
            "source_file": row.get("source_file"),
            "source_row": row.get("source_row"),
            "variable_code": row.get("variable_code"),
            "issue_code": DUPLICATE_CONFLICT_CODE,
            "severity": "medium",
            "message": f"pending conflict group {row.get('conflict_group_id')}: same canonical key has conflicting values",
            "observed_value": row.get("observed_value"),
            "raw_value": row.get("raw_value", row.get("observed_value")),
            "raw_unit": row.get("raw_unit", row.get("unit")),
        }
        for row in pending_conflicts
    ]
    if conflict_issues:
        qc["issues"].extend(conflict_issues)
        qc["flag_counts"][DUPLICATE_CONFLICT_CODE] = len(conflict_issues)
    imputation = impute_short_gaps(qc["cleaned"] + qc["imputation_candidates"])
    cleaned_records = [row for row in imputation["records"] if row.get("clean_value") is not None]
    pending_records = imputation["pending"]
    suspect_records = qc.get("suspect", [])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_root = Path(output_root) if output_root is not None else STORAGE / "exports" / f"cleaning_{stamp}"
    normalized_root = STORAGE / "silver" if output_root is None else export_root
    database_path = Path(database) if database is not None else STORAGE / "data_cleaning.db"
    files_out = {
        "normalized_observations": str(normalized_root / "normalized_observations.csv"),
        "cleaned_observations": str(export_root / "cleaned_observations.csv"),
        "rejected_records": str(export_root / "rejected_records.csv"),
        "suspect_records": str(export_root / "suspect_records.csv"),
        "qc_issues": str(export_root / "qc_issues.csv"),
        "remote_scene_catalog": str(export_root / "remote_scene_catalog.csv"),
        "source_archives": str(export_root / "source_archives.csv"),
        "pending_conflicts": str(export_root / "pending_conflicts.csv"),
        "duplicate_audit": str(export_root / "duplicate_audit.csv"),
        "imputation_audit": str(export_root / "imputation_audit.csv"),
        "long_gap_uncertainty_audit": str(export_root / "long_gap_uncertainty_audit.csv"),
        "low_frequency_latest_values": str(export_root / "low_frequency_latest_values.csv"),
        "wind_uv_audit": str(export_root / "wind_uv_audit.csv"),
        "database": str(database_path),
    }
    _write_csv(Path(files_out["normalized_observations"]), observations)
    _write_csv(Path(files_out["cleaned_observations"]), cleaned_records)
    files_out["imputation_candidates"] = str(export_root / "imputation_candidates.csv")
    _write_csv(Path(files_out["imputation_candidates"]), pending_records)
    _write_csv(Path(files_out["rejected_records"]), qc["rejected"])
    _write_csv(Path(files_out["suspect_records"]), suspect_records)
    _write_csv(Path(files_out["qc_issues"]), qc["issues"])
    _write_csv(Path(files_out["remote_scene_catalog"]), catalog)
    _write_csv(Path(files_out["source_archives"]), archives)
    _write_csv(Path(files_out["pending_conflicts"]), pending_conflicts)
    _write_csv(Path(files_out["duplicate_audit"]), duplicate_audit)
    _write_csv(Path(files_out["imputation_audit"]), imputation.get("imputation_audit", []))
    _write_csv(Path(files_out["long_gap_uncertainty_audit"]), (imputation.get("long_gap_uncertainty") or {}).get("audit", []))
    _write_csv(Path(files_out["low_frequency_latest_values"]), (imputation.get("low_frequency_nutrients") or {}).get("latest_value_table", []))
    _write_csv(Path(files_out["wind_uv_audit"]), (imputation.get("wind_uv") or {}).get("audit", []))
    _write_sqlite(
        database_path,
        cleaned_records,
        pending_records,
        qc["rejected"],
        qc["issues"],
        catalog,
        archives,
        suspect_records,
        pending_conflicts=pending_conflicts,
        duplicate_audit=duplicate_audit,
        wind_uv_audit=(imputation.get("wind_uv") or {}).get("audit", []),
    )

    result = {
        "run_id": run_id or f"cleaning_{stamp}",
        "status": "completed_with_warnings" if qc["issues"] or pending_conflicts else "completed",
        "input_files": source_files,
        "input_rows": len(observations),
        "deduplicated_rows": len(deduplicated_observations),
        "exact_duplicates_removed": deduplication["exact_duplicates_removed"],
        "conflict_groups": deduplication["conflict_groups"],
        "pending_conflict_rows": len(pending_conflicts),
        "clean_rows": len(cleaned_records),
        "imputed_rows": len(imputation["imputed"]),
        "pending_imputation_rows": len(pending_records),
        "rejected_rows": len(qc["rejected"]),
        "suspect_rows": len(suspect_records),
        "issue_count": len(qc["issues"]),
        "catalog_rows": len(catalog),
        "archive_rows": len(archives),
        "flag_counts": qc["flag_counts"],
        "rules_version": qc.get("rules_version"),
        "temporal_issue_counts": qc.get("temporal_issue_counts", {}),
        "univariate_issue_counts": qc.get("univariate_issue_counts", {}),
        "multivariate_issue_counts": qc.get("multivariate_issue_counts", {}),
        "missing_mechanism_counts": imputation.get("missing_mechanism_counts", {}),
        "missing_mechanism_by_source_variable": imputation.get("missing_mechanism_by_source_variable", {}),
        "imputation_audit_rows": len(imputation.get("imputation_audit", [])),
        "imputation_method": imputation.get("imputation_method"),
        "high_frequency_max_interval_minutes": imputation.get("high_frequency_max_interval_minutes"),
        "long_gap_rows": (imputation.get("long_gap_uncertainty") or {}).get("long_gap_rows", 0),
        "long_gap_bounded_rows": (imputation.get("long_gap_uncertainty") or {}).get("bounded_rows", 0),
        "long_gap_unbounded_rows": (imputation.get("long_gap_uncertainty") or {}).get("unbounded_rows", 0),
        "long_gap_uncertainty_audit_rows": len((imputation.get("long_gap_uncertainty") or {}).get("audit", [])),
        "low_frequency_nutrient_rows": (imputation.get("low_frequency_nutrients") or {}).get("nutrient_row_count", 0),
        "low_frequency_series": (imputation.get("low_frequency_nutrients") or {}).get("low_frequency_series", 0),
        "low_frequency_frequency_counts": (imputation.get("low_frequency_nutrients") or {}).get("frequency_counts", {}),
        "wind_uv_imputed_rows": (imputation.get("wind_uv") or {}).get("imputed_rows", 0),
        "wind_uv_pending_rows": (imputation.get("wind_uv") or {}).get("pending_rows", 0),
        "wind_uv_observed_pair_count": (imputation.get("wind_uv") or {}).get("observed_pair_count", 0),
        "wind_uv_calm_rows": (imputation.get("wind_uv") or {}).get("calm_rows", 0),
        "wind_uv_boundary_checks": (imputation.get("wind_uv") or {}).get("boundary_checks", 0),
        "spatial_issue_counts": qc.get("spatial_issue_counts", {}),
        "spatial_boundary_status": qc.get("spatial_boundary_status"),
        "spatial_boundary_path": qc.get("spatial_boundary_path"),
        "temporal_as_of_utc": qc.get("temporal_as_of_utc"),
        "temporal_max_gap_hours": qc.get("temporal_max_gap_hours"),
        "files": files_out,
    }
    manifest = Path(manifest_path) if manifest_path is not None else manifest_root(PACKAGE_ROOT) / f"{result['run_id']}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = str(manifest)
    return result
