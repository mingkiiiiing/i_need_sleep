"""Create the reference SQLite schema for the Taihu data-cleaning pipeline."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .schema_migrations import migrate_database


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
DEFAULT_SCHEMA_PATH = STORAGE / "databases" / "schema_reference.sqlite"

CORE_TABLES = (
    "source_registry",
    "ingestion_runs",
    "raw_assets",
    "stations",
    "observations_long",
    "forecast_values",
    "remote_scenes",
    "remote_zonal_stats",
    "qc_issues",
    "imputations",
    "feature_values",
    "target_values",
    "dataset_versions",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_registry (
            source_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            provider TEXT NOT NULL,
            dataset TEXT NOT NULL,
            access_mode TEXT NOT NULL,
            endpoint_or_url TEXT,
            auth TEXT,
            license_tag TEXT,
            redistribution_allowed TEXT,
            commercial_use TEXT,
            priority INTEGER,
            update_frequency TEXT,
            temporal_coverage TEXT,
            spatial_resolution TEXT,
            automation_status TEXT NOT NULL,
            verification TEXT,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            started_at_utc TEXT NOT NULL,
            finished_at_utc TEXT,
            status TEXT NOT NULL,
            http_status INTEGER,
            request_url TEXT,
            request_checksum_sha256 TEXT,
            error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
        );

        CREATE TABLE IF NOT EXISTS raw_assets (
            asset_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            run_id TEXT,
            request_url TEXT,
            local_path TEXT NOT NULL,
            start_time_utc TEXT,
            end_time_utc TEXT,
            checksum_sha256 TEXT NOT NULL,
            size_bytes INTEGER,
            license_tag TEXT,
            redistribution_allowed TEXT,
            commercial_use TEXT,
            retrieved_at_utc TEXT NOT NULL,
            UNIQUE(source_id, asset_id, checksum_sha256),
            FOREIGN KEY(source_id) REFERENCES source_registry(source_id),
            FOREIGN KEY(run_id) REFERENCES ingestion_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS stations (
            station_id TEXT PRIMARY KEY,
            station_name TEXT,
            longitude REAL NOT NULL,
            latitude REAL NOT NULL,
            depth_m REAL,
            station_type TEXT NOT NULL,
            management_unit TEXT,
            crs_epsg INTEGER NOT NULL DEFAULT 4326,
            valid_from_utc TEXT,
            valid_to_utc TEXT
        );

        CREATE TABLE IF NOT EXISTS observations_long (
            source_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            variable_code TEXT NOT NULL,
            depth_m REAL NOT NULL DEFAULT 0,
            value REAL,
            unit TEXT,
            raw_value TEXT,
            quality_code TEXT,
            imputation_code TEXT,
            value_origin TEXT NOT NULL DEFAULT 'observed',
            source_file TEXT,
            PRIMARY KEY(source_id, station_id, observed_at_utc, variable_code, depth_m),
            FOREIGN KEY(station_id) REFERENCES stations(station_id)
        );

        CREATE TABLE IF NOT EXISTS forecast_values (
            source_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            reference_time_utc TEXT NOT NULL,
            valid_time_utc TEXT NOT NULL,
            variable_code TEXT NOT NULL,
            lead_hours REAL,
            value REAL,
            unit TEXT,
            quality_code TEXT,
            value_origin TEXT NOT NULL DEFAULT 'forecast',
            PRIMARY KEY(source_id, station_id, reference_time_utc, valid_time_utc, variable_code)
        );

        CREATE TABLE IF NOT EXISTS remote_scenes (
            source_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            acquisition_at_utc TEXT NOT NULL,
            cloud_fraction REAL,
            water_coverage_fraction REAL,
            bbox_west REAL,
            bbox_south REAL,
            bbox_east REAL,
            bbox_north REAL,
            product_path TEXT,
            checksum_sha256 TEXT,
            quality_flags TEXT,
            PRIMARY KEY(source_id, scene_id)
        );

        CREATE TABLE IF NOT EXISTS remote_zonal_stats (
            source_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            zone_id TEXT NOT NULL,
            variable_code TEXT NOT NULL,
            acquisition_at_utc TEXT NOT NULL,
            mean_value REAL,
            median_value REAL,
            p05_value REAL,
            p95_value REAL,
            valid_fraction REAL,
            unit TEXT,
            PRIMARY KEY(source_id, scene_id, zone_id, variable_code),
            FOREIGN KEY(source_id, scene_id) REFERENCES remote_scenes(source_id, scene_id)
        );

        CREATE TABLE IF NOT EXISTS qc_issues (
            issue_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            station_id TEXT,
            observed_at_utc TEXT,
            variable_code TEXT,
            rule_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            raw_value TEXT,
            clean_value REAL,
            issue_message TEXT NOT NULL,
            action TEXT,
            evidence_path TEXT,
            created_at_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS imputations (
            imputation_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            station_id TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            variable_code TEXT NOT NULL,
            method TEXT NOT NULL,
            original_value REAL,
            imputed_value REAL NOT NULL,
            confidence REAL,
            model_version TEXT,
            evidence_path TEXT,
            UNIQUE(source_id, station_id, observed_at_utc, variable_code)
        );

        CREATE TABLE IF NOT EXISTS feature_values (
            entity_id TEXT NOT NULL,
            feature_time_utc TEXT NOT NULL,
            feature_code TEXT NOT NULL,
            value REAL,
            unit TEXT,
            data_age_hours REAL,
            source_combination TEXT,
            quality_mask TEXT,
            feature_version TEXT NOT NULL,
            PRIMARY KEY(entity_id, feature_time_utc, feature_code, feature_version)
        );

        CREATE TABLE IF NOT EXISTS target_values (
            entity_id TEXT NOT NULL,
            target_time_utc TEXT NOT NULL,
            target_code TEXT NOT NULL,
            value REAL,
            unit TEXT,
            target_origin TEXT NOT NULL,
            lower_confidence REAL,
            upper_confidence REAL,
            quality_code TEXT,
            source_id TEXT,
            PRIMARY KEY(entity_id, target_time_utc, target_code)
        );

        CREATE TABLE IF NOT EXISTS dataset_versions (
            dataset_version_id TEXT PRIMARY KEY,
            dataset_name TEXT NOT NULL,
            version_label TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            source_manifest_json TEXT,
            row_count INTEGER,
            status TEXT NOT NULL,
            checksum_sha256 TEXT,
            notes TEXT,
            UNIQUE(dataset_name, version_label)
        );
        """
    )


def _create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_ingestion_source_status ON ingestion_runs(source_id, status);
        CREATE INDEX IF NOT EXISTS idx_raw_assets_source_checksum ON raw_assets(source_id, checksum_sha256);
        CREATE INDEX IF NOT EXISTS idx_stations_lon_lat ON stations(longitude, latitude);
        CREATE INDEX IF NOT EXISTS idx_observations_time ON observations_long(observed_at_utc);
        CREATE INDEX IF NOT EXISTS idx_observations_station_time ON observations_long(station_id, observed_at_utc);
        CREATE INDEX IF NOT EXISTS idx_forecast_valid_time ON forecast_values(valid_time_utc);
        CREATE INDEX IF NOT EXISTS idx_forecast_reference_valid ON forecast_values(reference_time_utc, valid_time_utc);
        CREATE INDEX IF NOT EXISTS idx_remote_scenes_acquisition ON remote_scenes(acquisition_at_utc);
        CREATE INDEX IF NOT EXISTS idx_remote_zonal_zone_time ON remote_zonal_stats(zone_id, acquisition_at_utc);
        CREATE INDEX IF NOT EXISTS idx_qc_issues_time ON qc_issues(observed_at_utc);
        CREATE INDEX IF NOT EXISTS idx_imputations_time ON imputations(observed_at_utc);
        CREATE INDEX IF NOT EXISTS idx_features_time ON feature_values(feature_time_utc);
        CREATE INDEX IF NOT EXISTS idx_targets_time ON target_values(target_time_utc);
        """
    )


def create_schema_reference(output_path: Path = DEFAULT_SCHEMA_PATH) -> dict[str, object]:
    """Create or upgrade the reference database without dropping existing tables."""

    output_path = Path(output_path)
    migration = migrate_database(output_path)
    with sqlite3.connect(output_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_tables(connection)
        _create_indexes(connection)
        connection.commit()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        index_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
    return {
        "database": str(output_path),
        "status": "created",
        "schema_version": migration["current_version"],
        "tables": sorted(table_names),
        "indexes": sorted(index_names),
        "core_table_count": len(set(CORE_TABLES) & table_names),
        "created_at_utc": _utc_now(),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(create_schema_reference(), ensure_ascii=False, indent=2))

