"""10% 提升门禁比较表生成器（唯一来源；禁止任何硬编码比较数）。

扫描 runs/*/：run_config.json + selection_manifest.json + test_metrics_by_family.json，
按 (task, variant, 时效) 生成"融合 vs 同任务时效 RF/XGBoost 较优者"的明细：
融合值 = validation 选中的融合族（若选中族本身是 RF/XGB，则取 validation 最优融合族）。
n_test < GATE_MIN_TEST_ROWS → NA（reason=test_n_below_minimum_15）。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts_real import GATE_MIN_TEST_ROWS, HORIZON_MAP_V3, TASK_LABELS_ZH

FUSION_FAMILIES = ("mechanism_feature", "residual", "constrained_blend")
SINGLE_AI_FAMILIES = ("random_forest", "xgboost")
HONESTY_NOTE = (
    "本比较表由真实冻结测试集评估实时生成（gate.py 扫描 runs/*/test_metrics_by_family.json），"
    "无任何硬编码比较数；n_test<15 的行按主理人裁定记为 N.A. 并披露原因；"
    "测试集行数以 evaluation_manifest 为准，禁止挑选子集或调整口径。"
)
# R5-01（2026-09-13）：二分类/概率任务的行必须披露测试段类别支持。全正例或全负例的
# 测试段上 brier 退化为 mean(p²)，uplift 是"预测压缩程度"的平凡可比值，不构成 10%
# 硬指标的判别力证据。本字段只做诚实披露，不改变既有 PASS/FAIL 机械状态——状态语义
# 是否降级由主理人拍板，本表不替决策。
SINGLE_CLASS_DISCLOSURE = (
    "single_class_test=true 的行：测试段无正类（或无负类）样本，uplift 为单类别平凡比较，"
    "不构成 10% 达标证据（口径 F1/F3）；机械状态保持原值，是否降级由主理人裁定。"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _test_class_support(run_dir: Path) -> dict[str, Any] | None:
    """统计 runs/<run>/test_predictions.csv 的测试段类别分布（R5-01）。

    仅对二分类/概率任务有意义（actual ∈ {0,1}）；CSV 缺失或无 actual 列时返回 None，
    绝不猜测。类别判定：actual>0 记正类，actual==0 记负类。
    """
    csv_path = run_dir / "test_predictions.csv"
    if not csv_path.is_file():
        return None
    positives = negatives = unreadable = 0
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                raw = (row.get("actual") or "").strip()
                if not raw:
                    unreadable += 1
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    unreadable += 1
                    continue
                if value > 0:
                    positives += 1
                elif value == 0:
                    negatives += 1
                else:
                    unreadable += 1
    except OSError:
        return None
    return {
        "basis": "holdout_rows_test_predictions",
        "positives_test": positives,
        "negatives_test": negatives,
        "unreadable_rows": unreadable,
        "single_class_test": positives == 0 or negatives == 0,
    }


def _better(value_a: float, value_b: float, direction: str) -> float:
    if direction == "max":
        return max(value_a, value_b)
    return min(value_a, value_b)


def build_gate_table(runs_dir: str | Path) -> dict[str, Any]:
    runs = Path(runs_dir)
    rows: list[dict[str, Any]] = []
    if runs.is_dir():
        for run_dir in sorted(p for p in runs.iterdir() if p.is_dir()):
            config_path = run_dir / "run_config.json"
            metrics_path = run_dir / "test_metrics_by_family.json"
            selection_path = run_dir / "selection_manifest.json"
            if not (config_path.is_file() and metrics_path.is_file() and selection_path.is_file()):
                continue
            config = _read_json(config_path)
            selection = _read_json(selection_path)
            test_metrics = _read_json(metrics_path)
            primary = str(config["primary_metric"])
            direction = "max" if primary in {"macro_f1", "accuracy", "roc_auc", "pr_auc"} else "min"
            validation_by_family = selection.get("validation_metrics_by_family", {})

            def _vp(family: str) -> float | None:
                metrics = validation_by_family.get(family, {})
                value = metrics.get(primary)
                if value is None and primary == "macro_f1":
                    value = metrics.get("accuracy")
                return float(value) if value is not None and value == value else None

            fusion_candidates = [
                family for family in FUSION_FAMILIES
                if family in test_metrics and _vp(family) is not None
            ]
            single_candidates = [
                family for family in SINGLE_AI_FAMILIES
                if family in test_metrics and _vp(family) is not None
            ]
            selected = str(selection.get("selected_family"))
            fusion_family = selected if selected in FUSION_FAMILIES else (
                (max if direction == "max" else min)(fusion_candidates, key=_vp)
                if fusion_candidates else None
            )
            single_family = (
                (max if direction == "max" else min)(single_candidates, key=_vp)
                if single_candidates else None
            )
            test_n = int(test_metrics.get(selected, {}).get("n") or 0)
            row: dict[str, Any] = {
                "task_id": config["task_id"],
                "task_label": TASK_LABELS_ZH.get(config["task_id"], config["task_id"]),
                "variant": config["variant"],
                "horizon_days": int(config["horizon_days"]),
                "month_offset": int(config["month_offset"]),
                "granularity_tier": config.get("granularity_tier"),
                "target": config.get("problem_type"),
                "primary_metric": primary,
                "metric_direction": direction,
                "n_test": test_n,
                "selected_family": selected,
                "fusion_family": fusion_family,
                "single_family": single_family,
                # 评估记录绑定身份：run_id + 数据版本 + 训练协议，消费方据此对齐当前模型产物
                "run_id": config.get("run_id"),
                "data_version": config.get("data_version"),
                "training_protocol": (
                    config.get("training_protocol")
                    or (config.get("split_protocol") or {}).get("protocol_id")
                    or "frozen_split"
                ),
            }
            # R5-01：二分类/概率任务披露测试段类别支持；其余任务类型无类别含义，不加字段。
            if config.get("problem_type") in {"binary", "probability"}:
                row["class_support"] = _test_class_support(run_dir)
            if fusion_family is None or single_family is None:
                row.update({
                    "status": "NA",
                    "na_reason": "missing_fusion_or_single_family_test_metrics",
                    "fusion_value": None,
                    "best_single_value": None,
                    "uplift": None,
                })
            elif test_n < GATE_MIN_TEST_ROWS:
                row.update({
                    "status": "NA",
                    "na_reason": f"test_n_below_minimum_{GATE_MIN_TEST_ROWS}",
                    "fusion_value": float(test_metrics[fusion_family][primary]),
                    "best_single_value": float(test_metrics[single_family][primary]),
                    "uplift": None,
                })
            else:
                fusion_value = float(test_metrics[fusion_family][primary])
                single_value = float(test_metrics[single_family][primary])
                if direction == "max":
                    uplift = (fusion_value - single_value) / single_value if single_value else None
                else:
                    uplift = (single_value - fusion_value) / single_value if single_value else None
                status = "PASS" if (uplift is not None and uplift >= 0.10) else "FAIL"
                row.update({
                    "status": status,
                    "na_reason": None,
                    "fusion_value": fusion_value,
                    "best_single_value": single_value,
                    "uplift": uplift,
                })
            rows.append(row)
    counts = {"PASS": 0, "FAIL": 0, "NA": 0}
    for row in rows:
        counts[row["status"]] += 1
    comparisons = counts["PASS"] + counts["FAIL"]
    if comparisons == 0:
        overall = "NOT_APPLICABLE"
        overall_note = "真实数据下可评估比较数为 0（测试集行数均低于 15 或缺融合/单一族指标），门禁无法判定，如实披露。"
    else:
        pass_ratio = counts["PASS"] / comparisons
        overall = "PASS" if pass_ratio >= 0.9 else "FAIL"
        overall_note = f"可评估比较 {comparisons} 条，PASS 比例 {pass_ratio:.2%}，门禁阈值 90%。"
    return {
        "gate_version": "v1_real_2026",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison_rule": "fusion vs 同任务同时效 RF/XGBoost 较优者（validation 选族，冻结测试集同口径评估）",
        "uplift_threshold": 0.10,
        "min_test_rows": GATE_MIN_TEST_ROWS,
        "summary": {
            "comparison_rows": len(rows),
            "evaluable_comparisons": comparisons,
            "pass": counts["PASS"],
            "fail": counts["FAIL"],
            "not_applicable": counts["NA"],
            "status": overall,
            "note": overall_note,
        },
        "rows": rows,
        "single_class_disclosure": SINGLE_CLASS_DISCLOSURE,
        "honesty_note": HONESTY_NOTE,
    }
