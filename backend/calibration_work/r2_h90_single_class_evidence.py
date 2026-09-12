# -*- coding: utf-8 -*-
"""R2 附带（供 R5 与评委引用）：新 gate_table 两条 PASS 行（T1-bloom h90 / T6-probability h90）
的单类别测试段证据包。

新 gate_table（R1 冻结重跑产物，commit e698d0a）仅有的 2 条 PASS：
    T1-bloom-90d-3m-cv 与 T6-probability-90d-3m-cv：n_test=28、fusion uplift 0.5619。
两条 PASS 的比较均在同一测试段（2024-11..2026-03 的 T+90 目标月）上核算，而该段
actual 全为 0（全阴性）——本脚本从 runs/*/test_predictions.csv 与 test_metrics_by_family.json
逐行确认，并收集"该 PASS 是否应标 single_class/weak"的证据：
  ① 测试段标签唯一值 = {0.0}，正例数 = 0；
  ② 预测决策全部为负类（prediction 全 0），无判别行为可评估；
  ③ brier 在全阴性段退化为 mean(prob²)：任何"概率都低"的模型都拿低分；
     常量基线（simple_baseline 训练先验、climatology_global 月气候概率）的 brier 同段给出，
     供对照"融合 vs 单模型"的 0.5619 uplift 在该段上是否仍具判别力语义；
  ④ 单类段上 roc_auc / pr_auc 不可定义（probability_metrics 中 roc/pr 需 0/1 双类）；
  ⑤ gate.py 判 PASS 仅依据 test_n>=15 且 uplift>=0.10，无类别支持检查——
     而运行层 algorithm_models._calibration_verdict 对同类情形有 class_support 判定
     （single_class_test），两层口径不一致，正是应补 single_class/weak 标记的依据。

输出：backend/calibration_work/r2_h90_single_class_evidence.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "model_runtime_v0_3"

CASES = [
    ("T1", "bloom", "probability", "T1-bloom-90d-3m-cv"),
    ("T6", "probability", "probability", "T6-probability-90d-3m-cv"),
]
GATE_PATH = PKG / "evaluation" / "gate_table.json"


def _js(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    gate = _js(GATE_PATH)
    pass_rows = [r for r in gate["rows"] if r["status"] == "PASS"]
    evidence_cases = []
    for task_id, variant, problem_type, run_dir in CASES:
        run = PKG / "runs" / run_dir
        pred = pd.read_csv(run / "test_predictions.csv")
        metrics = _js(run / "test_metrics_by_family.json")
        selection = _js(run / "selection_manifest.json")
        config = _js(run / "run_config.json")

        actual = pred["actual"].to_numpy(dtype=float)
        prob = pred["probability"].to_numpy(dtype=float)
        decision = pred["prediction"].to_numpy(dtype=float)
        positives = int(np.sum(actual > 0.5))
        negatives = int(np.sum(actual <= 0.5))
        brier_fusion = float(np.mean((actual - prob) ** 2))

        # 常量对照（同段重算）：训练先验（simple_baseline 在该 run 的测试 brier 直接取记录）
        const_briers = {
            name: (float(m["brier_score"]) if m.get("brier_score") is not None else None)
            for name, m in metrics.items()
        }
        # 单类段判别力指标可定义性
        roc_defined = bool(positives > 0 and negatives > 0)

        gate_row = next(
            (r for r in pass_rows if r["run_id"] == config.get("run_id") and r["horizon_days"] == config.get("horizon_days")),
            None,
        )
        evidence_cases.append({
            "task_id": task_id,
            "variant": variant,
            "run_dir": run_dir,
            "run_id": config.get("run_id"),
            "protocol": config.get("protocol"),
            "split_key": config.get("split_key"),
            "test_window": {
                "month_min": str(pred["month"].min()),
                "month_max": str(pred["month"].max()),
                "n_rows": int(len(pred)),
            },
            "class_support": {
                "n_positive": positives,
                "n_negative": negatives,
                "unique_actual_values": sorted(set(np.round(actual, 12).tolist())),
                "single_class_test": bool(positives == 0 or negatives == 0),
                "n_unique_predictions": int(len(set(decision.tolist()))),
                "all_negative_decision": bool(np.all(decision <= 0.5)),
            },
            "probability_distribution": {
                "min": float(np.min(prob)), "max": float(np.max(prob)),
                "mean": float(np.mean(prob)),
                "n_unique": int(len(set(np.round(prob, 12).tolist()))),
            },
            "brier_on_this_segment": {
                "recomputed_from_rows": brier_fusion,
                "by_family_from_run_metrics": const_briers,
                "fusion_value_in_gate": gate_row.get("fusion_value") if gate_row else None,
                "best_single_value_in_gate": gate_row.get("best_single_value") if gate_row else None,
                "uplift_in_gate": gate_row.get("uplift") if gate_row else None,
            },
            "discriminative_metrics_definable": {
                "roc_auc_pr_auc_defined_on_single_class": roc_defined,
                "note": "probability_metrics 仅在测试段同时含 0/1 两类时才给出 roc_auc/pr_auc"
                        "（training_real.probability_metrics:117），单类段为 None。",
            },
            "gate_row_status": gate_row.get("status") if gate_row else None,
            "selected_family": selection.get("selected_family"),
        })

    payload = {
        "gate_table": str(GATE_PATH),
        "gate_summary": gate.get("summary"),
        "conclusion": (
            "两条 PASS（T1-bloom h90 与 T6-probability h90）的比较均在 28 行全阴性测试段上核算："
            "actual 唯一值 {0.0}，预测决策全部为负类，brier 退化为 mean(prob²)，roc/pr-AUC 不可定义。"
            "该 uplift=0.5619 属平凡比较（single_class_test / weak evidence），不构成融合族判别力证据；"
            "建议 gate 层比照运行层 _calibration_verdict 的 class_support 口径补 single_class 标记。"
        ),
        "gate_layer_gap": (
            "gate.py build_gate_table 只判 test_n>=GATE_MIN_TEST_ROWS(15) 与 uplift>=0.10"
            "（gate.py:109-124），无类别支持检查；运行层 algorithm_models._calibration_verdict "
            "对 binary/probability 已有 class_support → single_class_test 判定。两层口径不一致。"
        ),
        "cases": evidence_cases,
    }
    out = HERE / "r2_h90_single_class_evidence.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for c in evidence_cases:
        print(f"[{c['task_id']}-{c['variant']}] n={c['test_window']['n_rows']} "
              f"pos={c['class_support']['n_positive']} neg={c['class_support']['n_negative']} "
              f"single_class={c['class_support']['single_class_test']} "
              f"uplift={c['brier_on_this_segment']['uplift_in_gate']}")
    print("[done] ->", out)


if __name__ == "__main__":
    main()
