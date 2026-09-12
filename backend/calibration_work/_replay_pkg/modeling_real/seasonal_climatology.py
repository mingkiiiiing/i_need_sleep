"""季节气候态基线产物：中长期（30/60 天）唯一能在真实数据上成立的预测。

为什么需要它（2026-09-11）：
    历史水质面板是**季度**采样（2/5/8/11 月）。月度平移的监督表要求在 (M, M+offset)
    两月都取到标签；offset=3 恰好与季度网格同余 → 567 行可训；offset=1/2 与网格不同余
    → 配对为空（T3/T4/T5）或只剩 2024 年以后 37 行（T1/T6 的月度代理标签）。
    也就是说 T+30/T+60 在真实标签上**不存在可训练的逐站模型**，硬训只会得到一个在
    0 正例验证集上以 brier=0 胜出的常量查表。

    此时能在真实数据上成立的只有「季节气候态」：按目标月给出历史同期均值/众数。
    它逐月变化、可用留出段回测、可给出经验残差区间，但不含站点分辨——如实披露。

产物写成 evaluation/seasonal_climatology.json，运行层在 (任务, 时效) 没有交付模型时
回退读取；有模型时一律用模型，气候态只补空缺，绝不覆盖。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts_real import GATE_MIN_TEST_ROWS, TASK_SPECS_REAL, package_root
from .data_real import bundle_slot_filename, load_bundle
from .training_real import evaluate_real

# 产物版本与路径：运行层按同一常量读取，版本不符即视为不可用（不猜测新字段语义）
# v2（2026-09-11）：新增留出段经验覆盖率、逐行标签来源汇总、按「评估充分性」判定的
# fallback_horizons。旧版 v1 只有残差分位数、无覆盖率记录，运行层会硬编码
# empirical_coverage=None 却仍返回 decision_usable=true——那是确定的逻辑错误。
ARTIFACT_VERSION = "seasonal_climatology_v2"
SEASONAL_CLIMATOLOGY_PATH = "evaluation/seasonal_climatology.json"

# 留出回测：按「唯一目标月」的时间顺序，末尾这一段完全不参与气候态拟合
BACKTEST_HOLDOUT_FRACTION = 0.2
# 气候态下限样本量：低于此不做回测，只给点值并如实标注无证据
MIN_BACKTEST_MONTHS = 6

# 区间覆盖率的验收线：标称 90% 区间的留出段实测覆盖率允许有有限样本容差，
# 低于 88% 即判定欠覆盖。定这条线的依据：
#   * 留出段 n≈117、标称 0.90 时，二项标准误 ≈ 2.8 个百分点；2 个百分点的容差在 1 个标准误内，
#     89.74% 这种"实质校准良好"的结果不应被误判为不合格；
#   * 80.30%（T5 T+1）与 85.47%（T5 T+90）明显超出容差，必须如实标为欠覆盖，
#     不得再返回 decision_usable=true——那正是本轮要修的虚假可信度。
COVERAGE_TARGET = 0.90
COVERAGE_TOLERANCE = 0.02
COVERAGE_ACCEPTANCE_MIN = round(COVERAGE_TARGET - COVERAGE_TOLERANCE, 6)

CANDIDATE_TASKS = (
    ("T1", "bloom"),
    ("T3", "density"),
    ("T4", "biomass"),
    ("T5", "chla"),
    ("T6", "probability"),
)

# 比值型输出：区间端点裁剪到 [0, 1]（与运行层 _clip_interval 同一口径）
RATIO_OUTPUT_VARIANTS = {"bloom", "coverage", "density", "probability", "spatial"}

DISCLOSURE = (
    "季节气候态基线：由该任务历史标签序列按目标月聚合成均值（分类任务取众数概率）得到，"
    "反映真实季节循环。它不含站点分辨——同一目标月全湖同值，不得据此做站间比较。"
    "留出回测把时间上最后 20% 的目标月完全排除在拟合之外，指标、经验残差区间与经验覆盖率"
    "都在该段核算。仅当 (任务, 时效) 没有评估充分的逐站模型时，运行层才回退到本基线。"
)


def _month_num(month: str) -> int:
    return int(str(month)[5:7])


def _clip(value: float, variant: str, *, lower: bool) -> float:
    if lower:
        return float(max(value, 0.0))
    return float(min(value, 1.0)) if variant in RATIO_OUTPUT_VARIANTS else float(value)


def slot_evidence(task_id: str, variant: str, offset: int, horizon: int, seed: int) -> dict:
    """该槽位已交付模型的评估证据摘要（不加载模型权重，只读 uncertainty_meta）。

    返回 {"artifact_exists", "test_n", "empirical_coverage", "evidence_sufficient"}。
    "评估充分" = 留出测试样本数 ≥ GATE_MIN_TEST_ROWS。T+30/T+60 的持久性模型只有 5 条
    测试样本，属于 insufficient_test_evidence，不得因为"文件存在"就优先于季节基线使用。
    """
    from .contracts_real import DEFAULT_SEED_V3

    seed = DEFAULT_SEED_V3 if seed is None else seed
    path = package_root() / "models" / bundle_slot_filename(task_id, variant, offset, horizon, seed)
    if not path.is_file():
        return {
            "artifact_exists": False, "test_n": 0, "empirical_coverage": None,
            "evidence_sufficient": False, "reason": "model_artifact_missing",
        }
    try:
        bundle = load_bundle(path)
        meta = bundle.uncertainty_meta or {}
        test_n = int(meta.get("test_n") or 0)
        coverage = meta.get("empirical_coverage_test")
    except Exception as exc:  # noqa: BLE001 — 读不出证据即视为没有证据
        return {
            "artifact_exists": True, "test_n": 0, "empirical_coverage": None,
            "evidence_sufficient": False, "reason": f"model_meta_unreadable:{exc}",
        }
    sufficient = test_n >= GATE_MIN_TEST_ROWS
    return {
        "artifact_exists": True,
        "test_n": test_n,
        "empirical_coverage": coverage,
        "evidence_sufficient": sufficient,
        "reason": None if sufficient else f"insufficient_test_evidence(n_test={test_n}<{GATE_MIN_TEST_ROWS})",
    }


def _slot_exists(task_id: str, variant: str, offset: int, horizon: int, seed: int) -> bool:
    return slot_evidence(task_id, variant, offset, horizon, seed)["evidence_sufficient"]


def build_seasonal_climatology(
    base: pd.DataFrame, labels: pd.DataFrame, *, seed: int | None = None
) -> dict:
    """构建季节气候态产物（不落盘）；返回 dict，调用方负责写文件。"""
    from .contracts_real import DEFAULT_SEED_V3
    from .target_builder import build_supervised_table, LABEL_FAMILY_COLUMNS

    seed = DEFAULT_SEED_V3 if seed is None else seed
    tasks: list[dict] = []
    for task_id, variant in CANDIDATE_TASKS:
        spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
        table = build_supervised_table(base, labels, spec, 0)
        if not len(table):
            continue
        frame = table.loc[:, ["target_month", "actual"]].copy()
        frame["actual_num"] = pd.to_numeric(frame["actual"], errors="coerce")
        frame = frame.loc[frame["actual_num"].notna()]
        if not len(frame):
            continue
        months = sorted(frame["target_month"].unique())
        cut_index = int(len(months) * (1 - BACKTEST_HOLDOUT_FRACTION))
        can_backtest = len(months) >= MIN_BACKTEST_MONTHS and 0 < cut_index < len(months)
        if can_backtest:
            fit_months = set(months[:cut_index])
            holdout_months = set(months[cut_index:])
            fit_frame = frame.loc[frame["target_month"].isin(fit_months)]
        else:
            fit_months, holdout_months = set(months), set()
            fit_frame = frame

        is_ordinal = spec.problem_type == "ordinal"
        by_month: dict[str, float | str] = {}
        for month in sorted(fit_months):
            values = fit_frame.loc[fit_frame["target_month"] == month, "actual"]
            if not len(values):
                continue
            if is_ordinal:
                mode = values.astype(str).mode()
                if len(mode):
                    by_month[str(_month_num(month))] = str(mode.iloc[0])
            else:
                by_month[str(_month_num(month))] = float(pd.to_numeric(values, errors="coerce").mean())
        if is_ordinal:
            mode = fit_frame["actual"].astype(str).mode() if len(fit_frame) else pd.Series(dtype=object)
            fallback: float | str = str(mode.iloc[0]) if len(mode) else "none"
        else:
            fallback = float(fit_frame["actual_num"].mean()) if len(fit_frame) else 0.0

        backtest: dict = {"protocol": "time_block_holdout_tail_months", "holdout_fraction": BACKTEST_HOLDOUT_FRACTION}
        empirical_coverage = None
        coverage_n = 0
        if can_backtest and holdout_months:
            holdout = frame.loc[frame["target_month"].isin(holdout_months)]
            predicted = np.asarray(
                [by_month.get(str(_month_num(m)), fallback) for m in holdout["target_month"]],
                dtype=object,
            )
            residual_quantiles = None
            if is_ordinal:
                metrics = evaluate_real(spec, holdout["actual"].to_numpy(), predicted)
            else:
                numeric_pred = np.asarray(predicted, dtype=float)
                metrics = evaluate_real(spec, holdout["actual_num"].to_numpy(), numeric_pred)
                residual = holdout["actual_num"].to_numpy() - numeric_pred
                residual_quantiles = {
                    "p05": float(np.quantile(residual, 0.05)),
                    "p95": float(np.quantile(residual, 0.95)),
                }
                # 留出段经验覆盖率：用与运行层完全一致的"点值 + 残差分位数 + 物理边界裁剪"
                # 口径回算，否则产物里记的覆盖率和线上区间对不上，等于没有证据。
                p05 = np.asarray([
                    _clip(float(v) + residual_quantiles["p05"], variant, lower=True) for v in numeric_pred
                ])
                p95 = np.asarray([
                    _clip(float(v) + residual_quantiles["p95"], variant, lower=False) for v in numeric_pred
                ])
                actual_holdout = holdout["actual_num"].to_numpy(dtype=float)
                covered = (actual_holdout >= p05) & (actual_holdout <= p95)
                empirical_coverage = float(np.mean(covered))
                coverage_n = int(len(actual_holdout))
            backtest.update({
                "train_max_month": max(fit_months),
                "test_min_month": min(holdout_months),
                "n": int(len(holdout)),
                "metrics": metrics,
                "residual_quantiles": residual_quantiles,
                "empirical_coverage": empirical_coverage,
                "coverage_n": coverage_n,
                "coverage_target": COVERAGE_TARGET,
                "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
            })
        else:
            backtest.update({"n": 0, "metrics": None, "residual_quantiles": None,
                             "empirical_coverage": None, "coverage_n": 0,
                             "coverage_target": COVERAGE_TARGET,
                             "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
                             "reason": "holdout_months_insufficient_for_backtest"})

        # 该任务在哪些情景时效上需要回退到本基线：没有「评估充分」的逐站模型的那些。
        # 判据从"文件是否存在"改为"评估是否充分"，因为 T+30/T+60 存在持久性模型文件、
        # 但只有 5 条测试样本，把这种模型当成有效交付会得到虚假的中长期趋势。
        slot_evidence_map = {}
        fallback_horizons = []
        for horizon in (30, 60, 90):
            evidence = slot_evidence(task_id, variant, horizon // 30, horizon, seed)
            slot_evidence_map[str(horizon)] = evidence
            if not evidence["evidence_sufficient"]:
                fallback_horizons.append(horizon)

        provenance_breakdown = {}
        if "actual_provenance" in table.columns:
            provenance_breakdown = {
                str(k): int(v) for k, v in table["actual_provenance"].dropna().value_counts().items()
            }
        observed_provenance = (
            spec.label_provenance if not provenance_breakdown
            else (next(iter(provenance_breakdown)) if len(provenance_breakdown) == 1
                  else "mixed(" + "|".join(sorted(provenance_breakdown)) + ")")
        )

        tasks.append({
            "task_id": task_id,
            "variant": variant,
            "label_family": spec.label_family,
            "task_label": spec.task_id,
            "problem_type": spec.problem_type,
            "primary_metric": spec.primary_metric,
            "metric_direction": "max" if spec.primary_metric in {"macro_f1", "accuracy", "roc_auc", "pr_auc"} else "min",
            # 权威来源 = 逐行 actual_provenance 汇总；declared 另存供审计
            "label_provenance": observed_provenance,
            "label_provenance_declared": spec.label_provenance,
            "label_provenance_breakdown": provenance_breakdown,
            "station_resolution": False,
            "horizons": [30, 60, 90],
            "fallback_horizons": fallback_horizons,
            "slot_evidence": slot_evidence_map,
            "history": {
                "rows": int(len(frame)),
                "months": int(len(months)),
                "window": [months[0], months[-1]],
            },
            "by_month": by_month,
            "fallback": fallback,
            "backtest": backtest,
        })
    return {
        "artifact_version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "per_target_month_climatology_with_time_block_holdout_backtest",
        "disclosure": DISCLOSURE,
        "station_resolution_note": "同一目标月全湖同值；站间比较请改用有逐站模型支撑的时效。",
        "coverage_target": COVERAGE_TARGET,
        "coverage_tolerance": COVERAGE_TOLERANCE,
        "coverage_acceptance_min": COVERAGE_ACCEPTANCE_MIN,
        "tasks": tasks,
    }


def write_seasonal_climatology(
    payload: dict | None = None, *, base: pd.DataFrame | None = None, labels: pd.DataFrame | None = None
) -> dict:
    if payload is None:
        if base is None:
            from .target_builder import build_supervised_base

            base, labels = build_supervised_base()
        payload = build_seasonal_climatology(base, labels)
    path: Path = package_root() / SEASONAL_CLIMATOLOGY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[climatology] tasks={len(payload['tasks'])} → {path}")
    return payload
