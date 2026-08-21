from __future__ import annotations

"""Build leakage-safe, inspectable data releases from validated Gold assets."""

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_by_target_time(frame: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Chronologically split while keeping one sampling event in one partition."""
    if "target_time" not in frame:
        raise ValueError("target_time is required")
    source = frame.copy()
    source["target_time"] = pd.to_datetime(source["target_time"], errors="raise")
    times = pd.Series(source["target_time"].dropna().unique()).sort_values().tolist()
    if len(times) < 3:
        raise ValueError("at least three distinct target times are required")
    train_end = max(1, int(len(times) * 0.70))
    validation_end = max(train_end + 1, int(len(times) * 0.85))
    validation_end = min(validation_end, len(times) - 1)
    time_sets = {
        "train": set(times[:train_end]),
        "validation": set(times[train_end:validation_end]),
        "test": set(times[validation_end:]),
    }
    splits = {name: source[source["target_time"].isin(values)].copy() for name, values in time_sets.items()}
    intersections = {
        "train_validation": len(time_sets["train"] & time_sets["validation"]),
        "train_test": len(time_sets["train"] & time_sets["test"]),
        "validation_test": len(time_sets["validation"] & time_sets["test"]),
    }
    feature_leakage = 0
    if "feature_date" in source:
        feature_leakage = int((pd.to_datetime(source["feature_date"]) >= source["target_time"]).sum())
    audit = {
        "strategy": "chronological 70/15/15 by distinct target_time; sampling events are atomic groups",
        "distinct_target_times": len(times),
        "rows": {name: int(len(part)) for name, part in splits.items()},
        "target_time_overlap": intersections,
        "feature_target_time_violations": feature_leakage,
    }
    return splits, audit


def _missing_rate(frame: pd.DataFrame) -> float:
    return float(frame.isna().sum().sum() / frame.size) if frame.size else 0.0


def prepare_horizon_release(dataset: Path, output_root: Path, horizon: str, *, status: str = "READY") -> dict[str, Any]:
    frame = pd.read_parquet(dataset)
    splits, audit = split_by_target_time(frame)
    target = output_root / ("horizons" if status == "READY" else "candidates") / horizon
    target.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for name, part in splits.items():
        path = target / f"{name}.parquet"
        part.to_parquet(path, index=False)
        outputs[name] = str(path)
    card = {
        "horizon": horizon,
        "status": status,
        "source_dataset": str(dataset),
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "date_range": [str(frame["feature_date"].min()), str(frame["feature_date"].max())],
        "target_variables": sorted(frame.get("target_variable", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "target_types": sorted(frame.get("target_type", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "target_sources": sorted(frame.get("target_source", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "missing_cell_rate": _missing_rate(frame),
        "split_audit": audit,
        "license": "mixed-source derived dataset; consult source_licenses.csv before redistribution",
        "known_biases": [
            "observed phytoplankton biomass is sparse and mainly monthly/quarterly",
            "rows sharing a target sampling event are correlated and therefore kept in one split",
            "authorized real-time station/float observations are not present",
        ],
        "operational_training_allowed": status == "READY",
    }
    card_path = target / "data_card.json"
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["data_card"] = str(card_path)
    return {"horizon": horizon, "outputs": outputs, **audit}


def _sqlite_projection(frame: pd.DataFrame, *, limit: int = 1800) -> tuple[pd.DataFrame, list[str]]:
    if len(frame.columns) <= limit:
        return frame, []
    identifiers = [column for column in frame.columns if column in {"feature_date", "feature_reference_time", "target_time", "lake_id", "station_id", "latitude", "longitude"}]
    targets = [column for column in frame.columns if column.startswith("target_")]
    direct_base = [column for column in frame.columns if column.startswith("direct_") and "_lag_" not in column and "_rolling_" not in column]
    mechanism = [column for column in frame.columns if column.startswith("mechanism_")]
    reliability = [column for column in frame.columns if column.startswith("reliability_")]
    selected = list(dict.fromkeys(identifiers + targets + direct_base + mechanism + reliability + list(frame.columns)))[:limit]
    omitted = [column for column in frame.columns if column not in selected]
    return frame[selected], omitted


def _write_table(connection: sqlite3.Connection, name: str, path: Path) -> tuple[int, list[str]]:
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)
    projected, omitted = _sqlite_projection(frame)
    projected.to_sql(name, connection, if_exists="replace", index=False, chunksize=5000)
    return int(len(frame)), omitted


def build_release(
    package_root: Path,
    output_root: Path,
    *,
    version: str,
) -> dict[str, Any]:
    """Create SQLite, CSV/Parquet exports, raster index and checksummed manifest."""
    package_root, output_root = Path(package_root), Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    exports = output_root / "tables"
    exports.mkdir(exist_ok=True)
    inputs = {
        "taihu_observations_long": package_root / "storage/runs/thqbca_integrated_cleaning_v2/cleaned_observations.csv",
        "taihu_daily_features": package_root / "storage/gold/integrated_reliability_features/reliability_features.parquet",
        "qc_issues": package_root / "storage/runs/thqbca_integrated_cleaning_v2/qc_issues.csv",
        "dataset_h1_3d": package_root / "storage/gold/integrated_horizon_datasets/dataset_h1_3d.parquet",
        "dataset_h7_15d": package_root / "storage/gold/integrated_horizon_datasets/dataset_h7_15d.parquet",
        "candidate_h30_90d": package_root / "storage/gold/integrated_horizon_datasets/candidate_dataset_h30_90d.parquet",
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing release inputs: " + ", ".join(missing))
    database = output_root / f"taihu_clean_{version}.sqlite"
    table_rows: dict[str, int] = {}
    sqlite_omitted_columns: dict[str, list[str]] = {}
    with sqlite3.connect(database) as connection:
        for name, source in inputs.items():
            table_rows[name], omitted = _write_table(connection, name, source)
            if omitted:
                sqlite_omitted_columns[name] = omitted
            connection.execute(f'CREATE INDEX IF NOT EXISTS "idx_{name}_date" ON "{name}"("feature_date")') if "dataset_" in name or name == "taihu_daily_features" else None
        connection.execute("CREATE TABLE IF NOT EXISTS schema_metadata(schema_version TEXT, dataset_version TEXT, created_at_utc TEXT)")
        connection.execute("DELETE FROM schema_metadata")
        connection.execute("INSERT INTO schema_metadata VALUES(?,?,?)", ("1.0.0", version, datetime.now(timezone.utc).isoformat()))
        connection.commit()
    export_paths: list[Path] = [database]
    for name, source in inputs.items():
        frame = pd.read_parquet(source) if source.suffix.lower() == ".parquet" else pd.read_csv(source, low_memory=False)
        parquet_path = exports / f"{name}.parquet"
        if source.suffix.lower() == ".parquet":
            if source.resolve() != parquet_path.resolve():
                shutil.copy2(source, parquet_path)
        else:
            frame.to_parquet(parquet_path, index=False)
        export_paths.append(parquet_path)
        # Human-readable CSV is required for core tables. Very wide model
        # matrices stay Parquet-first and receive a compact sample CSV.
        csv_path = exports / (f"{name}.csv" if len(frame.columns) <= 200 else f"{name}_sample.csv")
        (frame if len(frame.columns) <= 200 else frame.head(200)).to_csv(csv_path, index=False, encoding="utf-8-sig")
        export_paths.append(csv_path)

    raster_dir = package_root / "storage/gold/sentinel2_retrieval_20260802"
    raster_rows = []
    for raster in sorted(raster_dir.glob("*.tif")):
        raster_rows.append({"asset": raster.stem, "path": str(raster), "sha256": sha256_file(raster), "operational": False, "note": "partial-lake experimental retrieval"})
    raster_index = exports / "remote_raster_index.csv"
    pd.DataFrame(raster_rows).to_csv(raster_index, index=False, encoding="utf-8-sig")
    export_paths.append(raster_index)

    registry_path = package_root / "config/data_source_registry.csv"
    registry = pd.read_csv(registry_path, dtype=str).fillna("")
    internal = registry.copy()
    shareable = registry[registry["redistribution_allowed"].str.lower().isin({"yes", "true", "allowed"})].copy()
    internal_path, shareable_path = exports / "source_inventory_internal.csv", exports / "source_inventory_shareable.csv"
    internal.to_csv(internal_path, index=False, encoding="utf-8-sig")
    shareable.to_csv(shareable_path, index=False, encoding="utf-8-sig")
    export_paths.extend([internal_path, shareable_path])

    manifest = {
        "status": "completed_with_declared_blocks",
        "run_id": f"release_{version}",
        "rows_read": int(sum(table_rows.values())),
        "rows_written": int(sum(table_rows.values())),
        "rows_rejected": 0,
        "dataset_version": version,
        "tables": table_rows,
        "sqlite_omitted_columns": sqlite_omitted_columns,
        "outputs": [str(path) for path in export_paths],
        "checksums": {str(path.relative_to(output_root)): sha256_file(path) for path in export_paths},
        "warnings": [
            "30-90d is a candidate only until seasonal hindcasts are authorized and retrieved",
            "satellite chlorophyll is experimental because independent validation failed and coverage is partial",
            "shareable inventory is conservative; pending-review assets are excluded",
            "very wide model matrices are complete in Parquet; SQLite uses a documented projection to stay below its column limit",
        ],
        "next_action": "supply authorized station/float files and CDS credentials to remove the remaining external-data blocks",
    }
    manifest_path = output_root / "release_manifest.json"
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
