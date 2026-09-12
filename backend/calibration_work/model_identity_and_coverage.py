# -*- coding: utf-8 -*-
"""K1 第一步证据：固定 T5-chla 模型身份 + 用模型内嵌分位数复算测试覆盖率。

只读输入：
  - backend/model_runtime_v0_3/manifest.json
  - backend/model_runtime_v0_3/models/T5-chla-*.joblib
  - backend/model_runtime_v0_3/runs/T5-chla-*/{run_config,evaluation_manifest,uncertainty,selection_manifest,test_metrics_by_family}.json
  - backend/model_runtime_v0_3/runs/T5-chla-*/test_predictions.csv
  - ../不确定性专项审查_20260912/evidence.json （仅读取，不改动）
只写输出：backend/calibration_work/model_identity.{csv,json} / coverage_recheck.json

不改训练代码、不改模型、不改台账/看板/快照。
"""
from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PKG = BACKEND / "model_runtime_v0_3"
AUDIT = BACKEND.parent.parent / "不确定性专项审查_20260912"
sys.path.insert(0, str(PKG / "code"))

import joblib  # noqa: E402

warnings.filterwarnings("ignore")

# (horizon_days, month_offset, run_dir, model_file, evidence_variant, evidence_horizon)
TARGETS = [
    (1, 0, "T5-chla-1d-0m-cv", "T5-chla-0m-s20260907-1d.joblib", "chla", 1),
    (90, 3, "T5-chla-90d-3m-cv", "T5-chla-3m-s20260907-90d.joblib", "chla", 90),
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def coverage_for(model_file: str, run_dir: str) -> dict:
    path = PKG / "models" / model_file
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    bundle = joblib.load(path)
    run = PKG / "runs" / run_dir
    test = pd.read_csv(run / "test_predictions.csv")
    lo = float(bundle.intervals.residual_p05)
    hi = float(bundle.intervals.residual_p95)
    pred = test["prediction"].to_numpy(dtype=float)
    actual = test["actual"].to_numpy(dtype=float)
    covered = (actual >= pred + lo) & (actual <= pred + hi)
    # serving 物理裁剪口径（chla 无上界，仅下界 0）
    clipped_lo = np.maximum(pred + lo, 0.0)
    clipped_covered = (actual >= clipped_lo) & (actual <= pred + hi)
    return {
        "model_file": model_file,
        "sha256_disk": sha,
        "run_dir": run_dir,
        "n_test": int(len(test)),
        "residual_p05": lo,
        "residual_p95": hi,
        "calibration_n": int(bundle.intervals.calibration_n),
        "covered": int(covered.sum()),
        "coverage": float(covered.mean()),
        "covered_serving_clipped": int(clipped_covered.sum()),
        "coverage_serving_clipped": float(clipped_covered.mean()),
        "bundle_uncertainty_meta": bundle.uncertainty_meta,
        "selected_family": bundle.selected_family,
        "validation_value": bundle.validation_value,
        "created_at": bundle.created_at,
    }


def identity_row(horizon: int, offset: int, run_dir: str, model_file: str) -> dict:
    manifest = _load_json(PKG / "manifest.json")
    entry = next(
        m for m in manifest["models"]
        if m.get("task_id") == "T5" and m.get("variant") == "chla"
        and m.get("month_offset") == offset and m.get("horizon_days") == horizon
    )
    run = PKG / "runs" / run_dir
    rc = _load_json(run / "run_config.json")
    em = _load_json(run / "evaluation_manifest.json")
    um = _load_json(run / "uncertainty.json")
    sm = _load_json(run / "selection_manifest.json")
    tm = _load_json(run / "test_metrics_by_family.json")
    path = PKG / "models" / model_file
    bundle = joblib.load(path)
    sha_disk = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "task_id": "T5",
        "variant": "chla",
        "horizon_days": horizon,
        "month_offset": offset,
        "artifact_id": entry["artifact_id"],
        "manifest_file": entry["file"],
        "manifest_sha256": entry["sha256"],
        "sha256_disk": sha_disk,
        "sha256_match": entry["sha256"] == sha_disk,
        "manifest_run_id": entry["run_id"],
        "run_config_run_id": rc["run_id"],
        "bundle_run_id": bundle.run_id,
        "protocol": entry["protocol"],
        "run_config_protocol": rc.get("protocol"),
        "bundle_split_protocol": (bundle.uncertainty_meta or {}).get("split_protocol"),
        "selected_family_manifest": entry["selected_family"],
        "selected_family_run_selection": sm["selected_family"],
        "selected_family_bundle": bundle.selected_family,
        "validation_value_run": sm["validation_value"],
        "validation_value_bundle": bundle.validation_value,
        "test_n_manifest": entry["test_metrics"]["n"],
        "test_n_eval_manifest": em["test_rows"],
        "test_n_uncertainty": um["test_n"],
        "test_primary_metric": entry["test_metrics"]["mae"],
        "test_primary_metric_eval_manifest": em["test_value"],
        "empirical_coverage_recorded": um["empirical_coverage_test"],
        "bundle_empirical_coverage": bundle.uncertainty_meta.get("empirical_coverage_test"),
        "bundle_calibration_n": int(bundle.intervals.calibration_n),
        "uncertainty_calibration_n": um["calibration_n"],
        "bundle_residual_p05": float(bundle.intervals.residual_p05),
        "bundle_residual_p95": float(bundle.intervals.residual_p95),
        "label_provenance": entry["label_provenance"],
        "label_provenance_breakdown": json.dumps(entry["label_provenance_breakdown"], ensure_ascii=False),
        "split_block_bounds": json.dumps(rc.get("split_block_bounds"), ensure_ascii=False),
        "split_counts_internal": json.dumps(rc.get("split_counts_internal"), ensure_ascii=False),
        "split_key": rc.get("split_key"),
        "feature_contract_mode": manifest.get("feature_contract_mode"),
        "data_version": manifest.get("data_version"),
        "data_sha256": manifest.get("data_sha256"),
        "test_metrics_by_family_keys": "|".join(sorted(tm.keys())),
    }


def main() -> None:
    rows = [identity_row(*t[:2], t[2], t[3]) for t in TARGETS]
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "model_identity.csv", index=False, encoding="utf-8-sig")
    (HERE / "model_identity.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cov = {f"{t[3]}|h{t[0]}": coverage_for(t[3], t[2]) for t in TARGETS}

    # 与审查 evidence.json 的独立复算对账（只读）
    evidence = _load_json(AUDIT / "evidence.json")
    ev = {
        (r["variant"], r["horizon"]): r for r in evidence["recomputed"]
    }
    audit_cmp = []
    for (variant, horizon), rec in ev.items():
        if variant != "chla" or horizon not in (1, 90):
            continue
        key = f"T5-chla-{'0m-s20260907-1d' if horizon == 1 else '3m-s20260907-90d'}.joblib|h{horizon}"
        mine = cov[key]
        audit_cmp.append({
            "horizon": horizon,
            "audit_recorded_coverage": rec["coverage"],
            "audit_covered": rec["covered"],
            "audit_n": rec["n"],
            "audit_sha256": rec["sha256"],
            "audit_residual_p05": rec["residual_p05"],
            "audit_residual_p95": rec["residual_p95"],
            "my_sha256": mine["sha256_disk"],
            "sha256_match": rec["sha256"] == mine["sha256_disk"],
            "my_coverage": mine["coverage"],
            "my_covered": mine["covered"],
            "my_n": mine["n_test"],
            "coverage_match": abs(rec["coverage"] - mine["coverage"]) < 1e-12,
            "p05_match": abs(rec["residual_p05"] - mine["residual_p05"]) < 1e-12,
            "p95_match": abs(rec["residual_p95"] - mine["residual_p95"]) < 1e-12,
        })

    (HERE / "coverage_recheck.json").write_text(
        json.dumps({"coverage_from_bundle": cov, "audit_comparison": audit_cmp},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"identity": rows, "coverage": {k: {kk: vv for kk, vv in v.items()
                                                          if kk != "bundle_uncertainty_meta"}
                                                     for k, v in cov.items()},
                      "audit_comparison": audit_cmp}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
