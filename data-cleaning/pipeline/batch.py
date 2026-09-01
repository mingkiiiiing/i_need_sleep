from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clean import run_cleaning
from .quality_report import run_quality_report
from .run_context import RunContext
from .resample import run_resampling
from .align import run_alignment
from .features import run_feature_engineering
from .coverage import run_coverage
from .forecast_labels import run_horizon_labels
from .experiment import run_split
from .training_gate import run_training_gate
from .remediation import run_remediation


UTC = timezone.utc
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def run_data_cleaning_batch(
    raw_root: Path | None = None,
    *,
    runs_root: Path | None = None,
    run_id: str | None = None,
    as_of: datetime | None = None,
    through: str = "quality",
    target_variable: str = "phytoplankton_biomass",
    split_strategy: str = "time",
    train_fraction: float = 0.7,
    validation_fraction: float = 0.15,
) -> dict[str, Any]:
    """Run an isolated, auditable batch through a selected downstream stage.

    ``through`` is intentionally opt-in so the stable clean/quality path keeps
    its previous behavior. Every executed stage writes into the same run
    directory and SQLite database; a blocked downstream stage is recorded as a
    warning rather than being misreported as an execution failure.
    """

    stage_order = ("quality", "resample", "align", "features", "coverage", "labels", "split", "gate", "remediation")
    if through not in stage_order:
        raise ValueError(f"through must be one of {stage_order}")

    raw_root = Path(raw_root) if raw_root is not None else STORAGE / "raw"
    if not raw_root.exists():
        raise FileNotFoundError(raw_root)
    context = RunContext.create(run_id=run_id, runs_root=runs_root)
    stage_manifest_root = context.run_root / "manifests"
    stage_manifest_root.mkdir(parents=True, exist_ok=True)
    context.write_metadata(status="running", raw_root=raw_root, rules_version="qc_rules:1.0.0")
    started_at = datetime.now(UTC).isoformat()
    try:
        cleaning = run_cleaning(
            raw_root,
            context.stages_root / "cleaning",
            context.database,
            manifest_path=stage_manifest_root / "cleaning.json",
            run_id=f"{context.run_id}_cleaning",
        )
        context.write_metadata(status="cleaned", raw_root=raw_root, rules_version="qc_rules:1.0.0")
        cleaned_path = Path(cleaning["files"]["cleaned_observations"])
        quality = run_quality_report(
            cleaned_path,
            context.stages_root / "quality",
            context.database,
              rejected_path=Path(cleaning["files"]["rejected_records"]),
              pending_path=Path(cleaning["files"]["imputation_candidates"]),
              issues_path=Path(cleaning["files"]["qc_issues"]),
              normalized_path=Path(cleaning["files"]["normalized_observations"]),
              suspect_path=Path(cleaning["files"]["suspect_records"]),
              pending_conflicts_path=Path(cleaning["files"]["pending_conflicts"]),
              duplicate_audit_path=Path(cleaning["files"]["duplicate_audit"]),
            as_of=as_of or datetime.now(UTC),
            manifest_path=stage_manifest_root / "quality_report.json",
            run_id=f"{context.run_id}_quality_report",
        )
        stages: dict[str, Any] = {"cleaning": cleaning, "quality_report": quality}
        files: dict[str, str] = {
            "cleaned_observations": str(cleaned_path),
            "quality_report": quality["files"]["quality_report"],
            "quality_overall": quality["files"]["overall"],
            "database": str(context.database),
        }
        warning = cleaning["status"] != "completed"

        def execute_stage(name: str, callback) -> Any:
            nonlocal warning
            try:
                value = callback()
                stages[name] = value
                warning = warning or value.get("status") not in {"completed"}
                return value
            except Exception as exc:  # keep the batch auditable and diagnosable
                value = {"status": "blocked", "error_type": type(exc).__name__, "error": str(exc)}
                stages[name] = value
                warning = True
                return value

        resampled_path: Path | None = None
        feature_path: Path | None = None
        if stage_order.index(through) >= stage_order.index("resample"):
            resample = execute_stage("resample", lambda: run_resampling(
                cleaned_path, context.stages_root / "resample", context.database,
                manifest_path=stage_manifest_root / "resample.json", run_id=f"{context.run_id}_resample",
            ))
            if resample.get("status") != "blocked":
                resampled_path = Path(resample["files"]["resampled_observations"])
                files["resampled_observations"] = str(resampled_path)
                files["resample_gaps"] = resample["files"]["resample_gaps"]
        if stage_order.index(through) >= stage_order.index("align") and resampled_path is not None:
            aligned = execute_stage("align", lambda: run_alignment(
                resampled_path, context.stages_root / "align", context.database,
                manifest_path=stage_manifest_root / "align.json", run_id=f"{context.run_id}_align",
            ))
            alignment_path = Path(aligned["output"]) if aligned.get("status") != "blocked" else None
            if alignment_path is not None:
                files["temporal_alignments"] = str(alignment_path)
        else:
            alignment_path = None
            if stage_order.index(through) >= stage_order.index("align"):
                stages["align"] = {"status": "blocked", "reason": "resample_output_unavailable"}
                warning = True
        if stage_order.index(through) >= stage_order.index("features") and alignment_path is not None and resampled_path is not None:
            features = execute_stage("features", lambda: run_feature_engineering(
                alignment_path, resampled_path, context.stages_root / "features", context.database,
                manifest_path=stage_manifest_root / "features.json", run_id=f"{context.run_id}_features",
            ))
            if features.get("status") != "blocked":
                feature_path = Path(features["files"]["feature_dataset"])
                files["feature_dataset"] = str(feature_path)
                files["feature_quality_summary"] = features["files"]["feature_quality_summary"]
        elif stage_order.index(through) >= stage_order.index("features"):
            stages["features"] = {"status": "blocked", "reason": "alignment_output_unavailable"}
            warning = True
        if stage_order.index(through) >= stage_order.index("coverage") and resampled_path is not None:
            coverage = execute_stage("coverage", lambda: run_coverage(
                resampled_path, context.stages_root / "coverage", context.database,
                as_of=as_of or datetime.now(UTC), manifest_path=stage_manifest_root / "coverage.json",
                run_id=f"{context.run_id}_coverage",
            ))
            files["coverage_matrix"] = coverage.get("files", {}).get("matrix", "")
            files["coverage_gaps"] = coverage.get("files", {}).get("gaps", "")
        elif stage_order.index(through) >= stage_order.index("coverage"):
            stages["coverage"] = {"status": "blocked", "reason": "resample_output_unavailable"}
            warning = True
        if stage_order.index(through) >= stage_order.index("labels"):
            if feature_path is None:
                stages["labels"] = {"status": "blocked", "reason": "feature_output_unavailable"}
                warning = True
            else:
                labels = execute_stage("labels", lambda: run_horizon_labels(
                    feature_path, context.stages_root / "labels", context.database,
                    target_variable=target_variable, manifest_path=stage_manifest_root / "labels.json",
                    run_id=f"{context.run_id}_labels",
                ))
                if labels.get("selected_rows", 0) == 0:
                    labels["status"] = "blocked_no_labels"
                    warning = True
                elif any(item.get("overall_status") != "ready" for item in labels.get("summary", [])):
                    labels["status"] = "completed_with_warnings"
                    warning = True
                for key in ("dataset", "summary", "audit"):
                    if key in labels.get("files", {}):
                        files[f"forecast_{key}"] = labels["files"][key]
        experiment_path: Path | None = None
        if stage_order.index(through) >= stage_order.index("split"):
            if feature_path is None or "labels" not in stages or stages["labels"].get("status") in {"blocked", "blocked_no_labels"}:
                stages["split"] = {"status": "blocked", "reason": "label_output_unavailable"}
                warning = True
            else:
                label_dataset = stages["labels"].get("files", {}).get("dataset")
                if not label_dataset:
                    stages["split"] = {"status": "blocked", "reason": "label_dataset_missing"}
                    warning = True
                else:
                    split = execute_stage("split", lambda: run_split(
                        Path(label_dataset), context.stages_root / "split", context.database,
                        strategy=split_strategy, train_fraction=train_fraction, validation_fraction=validation_fraction,
                        manifest_path=stage_manifest_root / "split.json", run_id=f"{context.run_id}_split",
                    ))
                    if split.get("status") != "blocked":
                        experiment_path = Path(split["files"]["experiment_dataset"])
                        for key in ("experiment_dataset", "train", "validation", "test", "excluded", "summary", "audit"):
                            if key in split.get("files", {}):
                                files["experiment_dataset" if key == "experiment_dataset" else f"experiment_{key}"] = split["files"][key]
        if stage_order.index(through) >= stage_order.index("gate"):
            coverage_stage = stages.get("coverage", {})
            labels_stage = stages.get("labels", {})
            split_stage = stages.get("split", {})
            coverage_audit = coverage_stage.get("files", {}).get("audit")
            label_summary = labels_stage.get("files", {}).get("summary")
            split_audit = split_stage.get("files", {}).get("audit")
            split_summary = split_stage.get("files", {}).get("summary")
            if not all((coverage_audit, label_summary, split_audit, split_summary)):
                stages["gate"] = {"status": "blocked", "reason": "upstream_audit_output_unavailable"}
                warning = True
            else:
                gate = execute_stage("gate", lambda: run_training_gate(
                    Path(coverage_audit), Path(label_summary), Path(split_audit), Path(split_summary),
                    context.stages_root / "gate", context.database,
                    manifest_path=stage_manifest_root / "gate.json", run_id=f"{context.run_id}_gate",
                ))
                for key in ("summary", "checks"):
                    if key in gate.get("files", {}):
                        files[f"training_gate_{key}"] = gate["files"][key]
        if stage_order.index(through) >= stage_order.index("remediation"):
            gate_summary = stages.get("gate", {}).get("files", {}).get("summary")
            if not gate_summary:
                stages["remediation"] = {"status": "blocked", "reason": "training_gate_output_unavailable"}
                warning = True
            else:
                remediation = execute_stage("remediation", lambda: run_remediation(
                    Path(gate_summary), context.stages_root / "remediation", context.database,
                    manifest_path=stage_manifest_root / "remediation.json", run_id=f"{context.run_id}_remediation",
                    next_run_command=f"python -m pipeline run-batch --raw-root {raw_root} --runs-root {context.run_root.parent} --through gate",
                ))
                for key in ("summary", "requests"):
                    if key in remediation.get("files", {}):
                        files[f"p0_{key}"] = remediation["files"][key]
        status = "completed_with_warnings" if warning else "completed"
        context.write_metadata(status=status, raw_root=raw_root, rules_version="qc_rules:1.0.0")
        result: dict[str, Any] = {
            "run_id": context.run_id,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "raw_root": str(raw_root),
            "database": str(context.database),
            "through": through,
            "target_variable": target_variable,
            "split_strategy": split_strategy,
            "training_gate_status": stages.get("gate", {}).get("gate_status") if "gate" in stages else None,
            "stages": stages,
            "files": files,
        }
    except Exception as exc:
        context.write_metadata(status="failed", raw_root=raw_root, rules_version="qc_rules:1.0.0")
        result = {
            "run_id": context.run_id,
            "status": "failed",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "raw_root": str(raw_root),
            "database": str(context.database),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    result["manifest"] = str(context.write_manifest(result))
    if result["status"] != "failed":
        latest = context.run_root.parent / "latest.json"
        latest.write_text(json.dumps({"run_id": context.run_id, "manifest": str(context.manifest_path), "updated_at": datetime.now(UTC).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
