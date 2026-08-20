from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRUTH_CLASSES = {"real_external", "official_metadata", "synthetic_fixture", "demo"}
ROOTS = (Path("storage/raw"), Path("storage/runs"), Path("samples"), Path("tests/fixtures"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def source_basis_for_run(path: Path) -> list[str]:
    run_dir = path
    while run_dir != run_dir.parent and run_dir.name not in {"runs", "storage"}:
        manifest = run_dir / "run_manifest.json"
        if manifest.exists():
            payload = read_json(manifest) or {}
            inputs = json.dumps(payload.get("stages", {}), ensure_ascii=False)
            basis = []
            for marker in (
                "taihu_thqbca",
                "nasa_power",
                "open_meteo",
                "copernicus",
                "waterstation",
            ):
                if marker in inputs:
                    basis.append(marker)
            return basis or ["local_pipeline_inputs"]
        run_dir = run_dir.parent
    return ["local_pipeline_inputs"]


def classify(relative_path: str, path: Path) -> tuple[str, str, str, str, str]:
    normalized = relative_path.replace("\\", "/")
    lower = normalized.lower()
    if lower.startswith("tests/fixtures/"):
        return (
            "synthetic_fixture",
            "test_fixture",
            "no",
            "test fixture; excluded from formal training",
            "tests/fixtures",
        )
    if lower.startswith("storage/raw/authorized_waterstation/"):
        return (
            "synthetic_fixture",
            "authorization_template_or_dropzone_document",
            "no",
            "template or intake instructions; no authorized observation file present",
            "authorized_waterstation_dropzone",
        )
    if lower.startswith("storage/raw/lake_geodata_probe/"):
        return (
            "official_metadata",
            "public_metadata_probe",
            "no",
            "metadata/page snapshot, not a numeric observation table",
            "lake_geodata_probe",
        )
    if lower.startswith("storage/raw/copernicus_sentinel2_stac/"):
        return (
            "official_metadata",
            "official_catalog_snapshot",
            "no",
            "STAC catalog metadata; product pixels not present",
            "copernicus_sentinel2_stac",
        )
    if lower.startswith("storage/raw/taihu_thqbca_zenodo/"):
        if path.suffix.lower() == ".rar":
            return (
                "real_external",
                "raw_archive",
                "yes",
                "Zenodo external archive; use according to record license",
                "taihu_thqbca_zenodo",
            )
        return (
            "official_metadata",
            "official_record_or_download_manifest",
            "no",
            "Zenodo record/download metadata; not the observation table itself",
            "taihu_thqbca_zenodo",
        )
    if lower.startswith("storage/raw/taihu_thqbca_parsed/"):
        return (
            "real_external",
            "parsed_external_observations",
            "yes",
            "parsed from the verified THQBCA external archive",
            "taihu_thqbca_zenodo",
        )
    if lower.startswith("storage/raw/nasa_power_hourly/"):
        return (
            "real_external",
            "raw_api_response",
            "yes",
            "NASA POWER response; delayed analysis, not a lake sensor",
            "nasa_power_hourly",
        )
    if lower.startswith("storage/raw/open_meteo_forecast/"):
        return (
            "real_external",
            "raw_forecast_response",
            "review_required",
            "external forecast proxy; not final CMA/ECMWF authority",
            "open_meteo_forecast",
        )
    if lower.startswith("samples/source_samples/"):
        if "nasa_power" in lower:
            return (
                "real_external",
                "sample_api_response",
                "no",
                "small source snapshot; not a complete training period",
                "nasa_power_hourly",
            )
        return (
            "official_metadata",
            "sample_source_envelope",
            "no",
            "small source envelope; not a complete training period",
            path.stem,
        )
    if lower.startswith("storage/runs/"):
        if path.name == "latest.json" or "/manifests/" in lower or path.name.endswith("manifest.json"):
            return (
                "official_metadata",
                "pipeline_manifest",
                "no",
                "pipeline lineage/quality metadata; not a direct observation table",
                "pipeline_run_manifest",
            )
        basis = source_basis_for_run(path)
        if "open_meteo" in basis:
            return (
                "real_external",
                "derived_pipeline_output",
                "review_required",
                "derived output includes an Open-Meteo development proxy; review before formal training",
                "+".join(basis),
            )
        return (
            "real_external",
            "derived_pipeline_output",
            "review_required",
            "derived output from external-source inputs; verify target/source lineage before training",
            "+".join(basis),
        )
    return (
        "synthetic_fixture",
        "unclassified_candidate",
        "no",
        "not covered by a trusted source rule; manual review required",
        "unclassified",
    )


def build_inventory(workspace: Path, output_csv: Path, output_summary: Path) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    missing_roots: list[str] = []
    for root in ROOTS:
        absolute_root = workspace / root
        if not absolute_root.exists():
            missing_roots.append(root.as_posix())
            continue
        for path in sorted(absolute_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace).as_posix()
            truth_class, role, training_use, exclusion_reason, source_id = classify(relative, path)
            if truth_class not in TRUTH_CLASSES:
                raise ValueError(f"Unknown truth class for {relative}: {truth_class}")
            rows.append(
                {
                    "asset_path": relative,
                    "asset_root": root.as_posix(),
                    "asset_type": path.suffix.lower().lstrip(".") or "no_extension",
                    "asset_role": role,
                    "truth_class": truth_class,
                    "training_use": training_use,
                    "source_id_or_basis": source_id,
                    "exclusion_reason": exclusion_reason,
                    "size_bytes": path.stat().st_size,
                    "modified_at_utc": utc_iso(path.stat().st_mtime),
                    "sha256": sha256_file(path),
                    "generated_at_utc": generated_at,
                }
            )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "asset_path", "asset_root", "asset_type", "asset_role", "truth_class",
        "training_use", "source_id_or_basis", "exclusion_reason", "size_bytes",
        "modified_at_utc", "sha256", "generated_at_utc",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "task_id": "P00-03",
        "generated_at_utc": generated_at,
        "inventory_path": output_csv.relative_to(workspace).as_posix(),
        "candidate_file_count": len(rows),
        "missing_roots": missing_roots,
        "truth_class_counts": dict(Counter(row["truth_class"] for row in rows)),
        "training_use_counts": dict(Counter(row["training_use"] for row in rows)),
        "asset_role_counts": dict(Counter(row["asset_role"] for row in rows)),
        "synthetic_training_eligible_count": sum(
            1 for row in rows if row["truth_class"] == "synthetic_fixture" and row["training_use"] == "yes"
        ),
        "real_external_count": sum(1 for row in rows if row["truth_class"] == "real_external"),
        "official_metadata_count": sum(1 for row in rows if row["truth_class"] == "official_metadata"),
        "notes": [
            "truth_class describes evidence basis; derived outputs retain the external-source basis",
            "review_required outputs are not automatically eligible for formal training",
            "missing tests/fixtures is recorded rather than silently treated as empty data",
        ],
    }
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    result = build_inventory(
        root,
        root / "storage/exports/asset_truth_inventory.csv",
        root / "storage/reports/p00_03_summary.json",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
