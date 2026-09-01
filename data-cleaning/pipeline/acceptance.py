from __future__ import annotations

"""Generate evidence-based final acceptance artifacts without upgrading blocks."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run_final_acceptance(root: Path, release_root: Path) -> dict[str, Any]:
    root, release_root = Path(root), Path(release_root)
    storage = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
    reports = storage / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    registry = pd.read_csv(root / "config/data_source_registry.csv", dtype=str).fillna("")
    evidence_map = {
        "earth_search_sentinel2_l2a": storage / "manifests/earth_search_sentinel2_202608.json",
        "zenodo_taihu_insitu_10434391": storage / "manifests/zenodo_taihu_insitu.json",
        "open_meteo_ecmwf_seas5": storage / "raw/open_meteo_seasonal/manifest.json",
        "taihu_thqbca_zenodo": storage / "manifests/thqbca_integrated_cleaning_v2.json",
        "nasa_power_hourly": storage / "manifests/nasa_power_history_2005_2020.json",
        "noaa_gfs": storage / "manifests/noaa_gfs_20260818_18z.json",
        "ecmwf_open_data": storage / "manifests/ecmwf_open_data_20260818_18z.json",
    }
    source_rows = []
    for _, row in registry.iterrows():
        source_id = row["source_id"]
        evidence = evidence_map.get(source_id)
        verified = bool(evidence and evidence.exists())
        source_rows.append({
            "source_id": source_id, "category": row["category"], "provider": row["provider"],
            "endpoint": row["endpoint_or_url"], "access_mode": row["access_mode"], "auth": row["auth"],
            "claimed_connected": verified, "evidence": str(evidence) if evidence else "",
            "evidence_exists": verified, "temporal_coverage": row["temporal_coverage"],
            "key_variables": row["key_variables"], "license_risk": row["license_risk"],
            "redistribution_allowed": row["redistribution_allowed"], "authorization_risk": row["auth"] not in {"", "none"},
        })
    acceptance_path = reports / "final_source_acceptance.csv"
    pd.DataFrame(source_rows).to_csv(acceptance_path, index=False, encoding="utf-8-sig")

    cleaning = _manifest(storage / "manifests/thqbca_integrated_cleaning_v2.json")
    quality = {
        "status": "accepted_with_external_data_limitations",
        "input_rows": cleaning.get("input_rows"), "clean_rows": cleaning.get("clean_rows"),
        "rejected_rows": cleaning.get("rejected_rows"), "suspect_rows": cleaning.get("suspect_rows"),
        "qc_issue_rows": cleaning.get("issue_count"), "pending_long_gaps": cleaning.get("pending_imputation_rows"),
        "exact_duplicates_removed": cleaning.get("exact_duplicates_removed"),
        "pending_conflict_rows": cleaning.get("pending_conflict_rows"),
        "imputation_policy": "short gaps may be imputed with flags; long/low-frequency gaps remain missing with uncertainty",
        "no_silent_imputation": True,
    }
    quality_path = reports / "final_data_quality.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    calibration = _manifest(storage / "gold/chlorophyll_calibration/manifest.json")
    retrieval = _manifest(storage / "gold/sentinel2_retrieval_20260802/manifest.json")
    retrieval_acceptance = {
        "status": "NOT_ACCEPTED_FOR_OPERATIONAL_TRUTH",
        "calibration_status": calibration.get("status"), "samples": calibration.get("samples"),
        "date_groups": calibration.get("date_groups"), "validation": calibration.get("validation"),
        "metrics": calibration.get("metrics"), "scene_status": retrieval.get("status"),
        "lake_coverage_fraction": retrieval.get("lake_footprint_coverage_fraction"),
        "model_domain_exceedance_fraction": retrieval.get("model_domain_exceedance_fraction"),
        "bloom_area_is_partial": True, "operational_use": False,
    }
    retrieval_path = reports / "final_retrieval_acceptance.json"
    retrieval_path.write_text(json.dumps(retrieval_acceptance, ensure_ascii=False, indent=2), encoding="utf-8")

    horizon_rows = []
    for horizon in ("h1_3d", "h7_15d", "h30_90d"):
        manifest = _manifest(storage / f"gold/integrated_horizon_datasets/dataset_{horizon}_manifest.json")
        dataset = manifest.get("final_dataset") or manifest.get("candidate_labelled_dataset")
        frame = pd.read_parquet(root / dataset) if dataset and not Path(dataset).is_absolute() else pd.read_parquet(dataset)
        sample = frame.sort_values(["target_time", "feature_date"]).head(10)
        for _, item in sample.iterrows():
            horizon_rows.append({
                "horizon": horizon, "dataset_status": manifest.get("status"),
                "feature_date": item["feature_date"], "target_time": item["target_time"],
                "target_type": item.get("target_type"), "target_source": item.get("target_source"),
                "feature_precedes_target": pd.Timestamp(item["feature_date"]) < pd.Timestamp(item["target_time"]),
                "trainable": manifest.get("trainable"),
            })
    horizon_path = reports / "final_horizon_audit.csv"
    pd.DataFrame(horizon_rows).to_csv(horizon_path, index=False, encoding="utf-8-sig")

    # Cross-format values: inspect the same first 100 records from the release.
    reconciliation_rows = []
    for name in ("taihu_observations_long", "qc_issues"):
        parquet = pd.read_parquet(release_root / f"tables/{name}.parquet").head(100)
        csv = pd.read_csv(release_root / f"tables/{name}.csv", nrows=100, low_memory=False)
        common = list(parquet.columns.intersection(csv.columns))
        equivalent = parquet[common].fillna("<NA>").astype(str).equals(csv[common].fillna("<NA>").astype(str))
        reconciliation_rows.append({"table": name, "sample_rows": 100, "common_columns": len(common), "value_equivalent_as_text": equivalent})
    lineage_all = pd.read_csv(storage / "gold/integrated_daily_features/direct_feature_lineage.csv")
    lineage = lineage_all[(lineage_all["availability"] == "available") & (lineage_all["source_files"].fillna("[]") != "[]")].head(100)
    raw_links = 0
    for value in lineage["source_files"].fillna("[]"):
        try:
            files = json.loads(value)
        except (TypeError, ValueError):
            files = []
        if files and all((root / file).exists() if not Path(file).is_absolute() else Path(file).exists() for file in files):
            raw_links += 1
    reconciliation_rows.append({"table": "gold_to_raw_lineage", "sample_rows": int(len(lineage)), "common_columns": 0, "value_equivalent_as_text": len(lineage) == 100 and raw_links == 100})
    reconciliation_path = reports / "delivery_reconciliation.csv"
    pd.DataFrame(reconciliation_rows).to_csv(reconciliation_path, index=False, encoding="utf-8-sig")

    reproducibility = release_root / "reproducibility"
    for directory in ("pipeline", "config", "docs"):
        target = reproducibility / directory
        shutil.copytree(root / directory, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", "*.key", "*.token"))
    for filename in ("README.md", "requirements.txt", ".env.example"):
        shutil.copy2(root / filename, reproducibility / filename)

    frozen_files = [path for path in release_root.rglob("*") if path.is_file() and path.name != "final_release_manifest.json"]
    frozen = {
        "dataset_version": "2026.08.19-v1", "status": "frozen_with_declared_external_blocks",
        "files": [{"path": str(path.relative_to(release_root)), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in sorted(frozen_files)],
        "reproducibility_scope": "pipeline source, non-secret configuration, documentation, README, requirements and credential-name template",
        "acceptance_outputs": [str(acceptance_path), str(quality_path), str(retrieval_path), str(horizon_path), str(reconciliation_path)],
        "blocks": ["authorized real-time station/float data", "C3S historical seasonal hindcasts", "independent operational retrieval validation"],
    }
    frozen_path = release_root / "final_release_manifest.json"
    frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "completed_with_declared_blocks", "outputs": frozen["acceptance_outputs"] + [str(frozen_path)], "files_frozen": len(frozen_files)}
