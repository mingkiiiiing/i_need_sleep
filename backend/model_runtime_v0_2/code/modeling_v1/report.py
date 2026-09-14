"""Task/horizon completeness, 10% gate, and acceptance report builder."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .contracts import build_run_matrix, target_column


_RUN_SEED_SUFFIX = re.compile(r"-s\d+$")


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"required report file missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid report JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"report JSON must contain an object: {path}")
    return value


def _base_run_id(run_id: str) -> str:
    return str(_RUN_SEED_SUFFIX.sub("", run_id))


def _run_directories(run_root: Path) -> list[Path]:
    if not run_root.is_dir():
        raise ValueError(f"run root missing: {run_root}")
    return sorted(
        path
        for path in run_root.iterdir()
        if path.is_dir()
        and (path / "selection_manifest.json").is_file()
        and (path / "test_metrics_by_family.json").is_file()
    )


def _improvement(baseline: float, fusion: float, higher_is_better: bool) -> float:
    if baseline == 0:
        return float("nan")
    return (
        (fusion - baseline) / abs(baseline)
        if higher_is_better
        else (baseline - fusion) / abs(baseline)
    )


def _primary_higher_is_better(primary: str) -> bool:
    return primary in {"pr_auc", "roc_auc", "macro_f1", "area_weighted_iou", "iou"}


def _pure_ai_baseline(
    metrics_by_family: dict, higher_is_better: bool
) -> float | None:
    candidates = [
        metrics_by_family[name].get("primary_metric")
        for name in ("random_forest", "xgboost")
        if isinstance(metrics_by_family.get(name), dict)
        and metrics_by_family[name].get("primary_metric") is not None
    ]
    if not candidates:
        return None
    return float(max(candidates) if higher_is_better else min(candidates))


def build_acceptance_report(run_root: str | Path) -> dict:
    """Build the task/horizon completeness and 10% acceptance report."""
    root = Path(run_root)
    matrix = build_run_matrix()
    expected = set(matrix["run_id"])
    runs = _run_directories(root)
    by_run: dict[str, list[Path]] = {}
    for directory in runs:
        selection = _read_json(directory / "selection_manifest.json")
        base = _base_run_id(str(selection.get("run_id", "")))
        if base:
            by_run.setdefault(base, []).append(directory)
    missing = sorted(expected - set(by_run))
    if missing:
        raise ValueError("missing run combinations: " + ", ".join(missing))

    rows = []
    gate_rows = []
    fail_count = 0
    for _, matrix_row in matrix.iterrows():
        base = str(matrix_row["run_id"])
        directories = by_run[base]
        representative = directories[0]
        selection = _read_json(representative / "selection_manifest.json")
        family_metrics = _read_json(
            representative / "test_metrics_by_family.json"
        )
        higher = _primary_higher_is_better(matrix_row["primary_metric"])
        baseline = _pure_ai_baseline(family_metrics, higher)
        selected_metric = family_metrics.get(selection.get("selected_family", ""), {}).get(
            "primary_metric"
        )
        fusion_names = ("mechanism_feature", "residual", "constrained_blend")
        for fusion_name in fusion_names:
            fusion_metric = family_metrics.get(fusion_name, {}).get("primary_metric")
            if baseline is None or fusion_metric is None:
                status = "NOT_APPLICABLE"
                improvement = None
            else:
                improvement = _improvement(baseline, float(fusion_metric), higher)
                status = (
                    "PASS"
                    if improvement is not None
                    and improvement >= 0.10
                    and not (isinstance(improvement, float) and improvement != improvement)
                    else "FAIL"
                )
            if status == "FAIL":
                fail_count += 1
            gate_rows.append(
                {
                    "task_id": matrix_row["task_id"],
                    "variant": matrix_row["variant"],
                    "horizon_days": int(matrix_row["horizon_days"]),
                    "fusion_family": fusion_name,
                    "pure_ai_baseline": baseline,
                    "fusion_metric": fusion_metric,
                    "relative_improvement": improvement,
                    "status": status,
                }
            )
        rows.append(
            {
                "run_id": base,
                "task_id": matrix_row["task_id"],
                "variant": matrix_row["variant"],
                "horizon_days": int(matrix_row["horizon_days"]),
                "target_column": target_column(
                    matrix_row["target_family"], int(matrix_row["horizon_days"])
                ),
                "selected_family": selection.get("selected_family"),
                "selected_test_metric": selected_metric,
                "seed_count": len(directories),
                "claim_boundary": selection.get("claim_boundary")
                or "synthetic_development_only",
            }
        )
    return {
        "status": "PASS" if not missing else "FAIL",
        "task_horizon_matrix": rows,
        "ten_percent_gate": {
            "rows": gate_rows,
            "PASS": sum(row["status"] == "PASS" for row in gate_rows),
            "FAIL": fail_count,
            "NOT_APPLICABLE": sum(
                row["status"] == "NOT_APPLICABLE" for row in gate_rows
            ),
        },
        "claim_boundary": "synthetic_development_only",
    }
