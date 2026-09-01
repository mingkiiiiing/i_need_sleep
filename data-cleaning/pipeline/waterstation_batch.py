from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clean import run_cleaning
from .provenance import manifest_root, staging_root
from .sources.water_station import _payload_rows, normalize_water_station_file, normalize_water_station_rows, write_water_station_csv
from .station_validate import run_station_validation


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def _stage_water_station_file(input_path: Path, staged_path: Path, *, source_id: str) -> dict[str, Any]:
    """Parse a user file or a raw ``waterstation-fetch`` envelope into CSV."""

    if input_path.suffix.casefold() == ".json":
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and "payload" in payload:
            rows = normalize_water_station_rows(input_path, _payload_rows(payload.get("payload", {})), source_id=source_id)
        else:
            rows = normalize_water_station_file(input_path, source_id=source_id)
    else:
        rows = normalize_water_station_file(input_path, source_id=source_id)
    count = write_water_station_csv(staged_path, rows)
    return {"input": str(input_path), "staged": str(staged_path), "rows": count, "variables": sorted({row.get("variable_code") for row in rows if row.get("variable_code")})}


def run_water_station_batch(
    input_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    source_id: str = "taihu_water_station_batch",
    max_median_interval_hours: float = 6.0,
    max_gap_hours: float = 24.0,
) -> dict[str, Any]:
    """Run parse -> clean -> P0 validation for one authorized station file.

    The staged raw root contains only this input, so the batch result cannot
    silently mix the user's station export with unrelated historical files.
    The staging copy is retained for provenance and can be inspected before
    downstream resampling/alignment.
    """

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or STORAGE / "exports" / f"waterstation_batch_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    staging_run_root = staging_root(root) / f"waterstation_{stamp}"
    staged_path = staging_run_root / source_id / f"{input_path.stem}_standardized.csv"
    staged = _stage_water_station_file(input_path, staged_path, source_id=source_id)

    cleaning = run_cleaning(staging_run_root)
    cleaned_path = Path(cleaning["files"]["cleaned_observations"])
    validation = run_station_validation(
        cleaned_path,
        output_root / "validation",
        Path(database) if database else Path(cleaning["files"]["database"]),
        max_median_interval_hours=max_median_interval_hours,
        max_gap_hours=max_gap_hours,
    )
    status = "ready" if validation["validation_status"] == "ready" else "blocked_by_quality_gate"
    result: dict[str, Any] = {
        "run_id": f"waterstation_batch_{stamp}",
        "status": status,
        "input": str(input_path),
        "source_id": source_id,
        "staging": staged,
        "cleaning": cleaning,
        "validation": validation,
        "next_step": "resample -> align -> features -> coverage -> horizon-labels" if status == "ready" else "obtain missing P0 target/drivers or correct source quality, then rerun",
    }
    manifest_path = manifest_root(root) / f"{result['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest"] = str(manifest_path)
    (output_root / "batch_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
