from __future__ import annotations

from copy import deepcopy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .qc import quality_control
from .provenance import manifest_root


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def _base_row(source_row: str, variable_code: str, observed_at: str, value: Any) -> dict[str, Any]:
    return {
        "source_id": "fault_fixture",
        "source_file": "fault_fixture.json",
        "source_row": source_row,
        "station_id": "T01",
        "scene_id": None,
        "observed_at": observed_at,
        "variable_code": variable_code,
        "observed_value": value,
        "clean_value": value,
        "unit": "degC" if variable_code == "air_temperature" else "m/s",
        "value_origin": "observed",
        "is_imputed": False,
        "imputation_method": None,
        "imputation_confidence": None,
        "quality_flags": [],
    }


def build_fault_fixture() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build a small labelled fixture for regression testing QC rules."""
    rows = [
        _base_row("valid_1", "air_temperature", "2025-06-01T00:00:00+00:00", 25.0),
        _base_row("valid_2", "wind_speed", "2025-06-01T01:00:00+00:00", 3.0),
    ]
    missing = _base_row("fault_missing", "air_temperature", "2025-06-01T02:00:00+00:00", None)
    missing["observed_value"] = None
    outlier = _base_row("fault_outlier", "wind_speed", "2025-06-01T03:00:00+00:00", 80.0)
    duplicate = deepcopy(rows[0])
    duplicate["source_row"] = "fault_duplicate"
    invalid_time = _base_row("fault_timestamp", "air_temperature", "2025-06-01T04:00:00+00:00", 25.0)
    invalid_time["observed_at"] = None
    rows.extend([missing, outlier, duplicate, invalid_time])
    expected = {
        "fault_missing": "Q01",
        "fault_outlier": "Q04",
        "fault_duplicate": "Q08",
        "fault_timestamp": "Q03",
    }
    return rows, expected


def evaluate_fault_fixture() -> dict[str, Any]:
    records, expected = build_fault_fixture()
    result = quality_control(records)
    by_source_row: dict[str, set[str]] = {}
    for issue in result["issues"]:
        by_source_row.setdefault(str(issue.get("source_row")), set()).add(str(issue.get("issue_code")))
    detected = {row: code for row, code in expected.items() if code in by_source_row.get(row, set())}
    false_negatives = sorted(set(expected) - set(detected))
    return {
        "expected_faults": expected,
        "detected_faults": detected,
        "false_negatives": false_negatives,
        "recall": len(detected) / len(expected) if expected else 1.0,
        "qc_flag_counts": result["flag_counts"],
        "rejected_rows": len(result["rejected"]),
        "issue_rows": len(result["issues"]),
    }


def run_fault_injection(output_root: Path | None = None) -> dict[str, Any]:
    """Persist the labelled QC fixture result as an auditable run artifact."""

    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or STORAGE / "exports" / f"fault_injection_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    result = evaluate_fault_fixture()
    result.update({"run_id": f"fault_injection_{stamp}", "status": "passed" if result["recall"] == 1.0 else "failed"})
    result["output"] = str(output_root / "fault_injection_result.json")
    Path(result["output"]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = manifest_root(root) / f"{result['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
