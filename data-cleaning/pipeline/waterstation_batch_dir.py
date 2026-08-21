from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clean import run_cleaning
from .provenance import manifest_root, staging_root
from .sources.common import sha256_file
from .station_validate import run_station_validation
from .waterstation_batch import _stage_water_station_file


SUPPORTED_SUFFIXES = {".json", ".csv", ".tsv", ".xlsx"}


def _write_inventory(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["input_path", "suffix", "sha256", "status", "staged_path", "rows", "variables", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = dict(row)
            if isinstance(output.get("variables"), list):
                output["variables"] = ",".join(str(value) for value in output["variables"])
            writer.writerow(output)


def run_water_station_batch_directory(
    input_root: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    source_id: str = "taihu_water_station_batch",
    max_median_interval_hours: float = 6.0,
    max_gap_hours: float = 24.0,
) -> dict[str, Any]:
    """Process a directory of authorized station exports as one auditable batch."""

    input_root = Path(input_root)
    if not input_root.is_dir():
        raise NotADirectoryError(input_root)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or root / "storage" / "exports" / f"waterstation_batch_dir_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    staging_run_root = staging_root(root) / f"waterstation_dir_{stamp}"
    files = sorted(path for path in input_root.rglob("*") if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES)
    inventory: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    staged_count = 0
    for index, input_path in enumerate(files, start=1):
        digest = sha256_file(input_path)
        base = {"input_path": str(input_path), "suffix": input_path.suffix.casefold(), "sha256": digest}
        if digest in seen_hashes:
            inventory.append({**base, "status": "duplicate_hash_skipped", "staged_path": None, "rows": 0, "variables": [], "error": f"same_content_as:{seen_hashes[digest]}"})
            continue
        seen_hashes[digest] = str(input_path)
        staged_path = staging_run_root / source_id / f"{index:05d}_{input_path.stem}_standardized.csv"
        try:
            staged = _stage_water_station_file(input_path, staged_path, source_id=source_id)
            inventory.append({**base, "status": "parsed" if staged["rows"] else "parsed_empty", "staged_path": staged["staged"], "rows": staged["rows"], "variables": staged["variables"], "error": None})
            if staged["rows"]:
                staged_count += 1
        except Exception as exc:
            inventory.append({**base, "status": "parse_failed", "staged_path": None, "rows": 0, "variables": [], "error": str(exc)})

    inventory_path = output_root / "input_inventory.csv"
    _write_inventory(inventory_path, inventory)
    parsed = [item for item in inventory if item["status"] == "parsed" and item["rows"]]
    if not parsed:
        result: dict[str, Any] = {
            "run_id": f"waterstation_batch_dir_{stamp}",
            "status": "blocked_no_valid_files",
            "input_root": str(input_root),
            "files_discovered": len(files),
            "files_parsed": 0,
            "duplicate_files_skipped": sum(1 for item in inventory if item["status"] == "duplicate_hash_skipped"),
            "parse_failures": sum(1 for item in inventory if item["status"] == "parse_failed"),
            "inventory": str(inventory_path),
            "staging_root": str(staging_run_root),
        }
        return _write_batch_manifest(result, output_root)

    cleaning = run_cleaning(staging_run_root)
    validation = run_station_validation(
        Path(cleaning["files"]["cleaned_observations"]),
        output_root / "validation",
        Path(database) if database else Path(cleaning["files"]["database"]),
        max_median_interval_hours=max_median_interval_hours,
        max_gap_hours=max_gap_hours,
    )
    result = {
        "run_id": f"waterstation_batch_dir_{stamp}",
        "status": "ready" if validation["validation_status"] == "ready" else "blocked_by_quality_gate",
        "input_root": str(input_root),
        "files_discovered": len(files),
        "files_parsed": len(parsed),
        "duplicate_files_skipped": sum(1 for item in inventory if item["status"] == "duplicate_hash_skipped"),
        "parse_failures": sum(1 for item in inventory if item["status"] == "parse_failed"),
        "inventory": str(inventory_path),
        "staging_root": str(staging_run_root),
        "cleaning": cleaning,
        "validation": validation,
        "next_step": "resample -> align -> features -> coverage -> horizon-labels" if validation["validation_status"] == "ready" else "fix input files or obtain missing P0 target/drivers, then rerun",
    }
    return _write_batch_manifest(result, output_root)


def _write_batch_manifest(result: dict[str, Any], output_root: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    manifest_path = manifest_root(root) / f"{result['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "batch_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
