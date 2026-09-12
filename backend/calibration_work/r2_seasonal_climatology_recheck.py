# -*- coding: utf-8 -*-
"""R2（任务包 R2 / 台账 L-cal-07）：T+30/60 季节基线覆盖率从原始样本独立复算。

背景：区间校准专项台账 L-cal-07 记"T+30/60 季节基线接口覆盖率 71.97%（n=132）——本轮只核对
API，未从季节基线原始样本独立复算"。该 71.97% 是 2026-09-12 审查时点旧产物的接口读数；
R1 冻结重跑（2026-09-13，commit e698d0a）后 evaluation/seasonal_climatology.json 已按 v4
产物重新生成（训练侧 seasonal_climatology.write_seasonal_climatology 由 cli_real_cv.py all
重跑），本脚本对**当前 v4 产物**做从原始样本出发的逐行独立复算。

独立边界（对账有效性）：
  - 输入同源：监督表用与产物相同的 build_supervised_table(base, labels, spec, 0)（原始样本
    逐行 target_month + actual），这是"对应监督表"的权威来源；
  - 计算独立：三段切段、按目标月气候态均值、全段 fallback、校准段残差分位数、独立测试段
    逐行覆盖率（含物理裁剪与闭区间判定）全部在本脚本内按产物口径重写实现，
    **不调用** modeling_real.seasonal_climatology 的任何计算函数；
  - 对账对象：产物 JSON 内记录的 by_month / fallback / residual_quantiles /
    empirical_coverage / coverage_n / test_positive_n / test_negative_n /
    class_support_sufficient。

产物算法口径（modeling_real/seasonal_climatology.py，本脚本按其语义独立重写）：
  唯一目标月排序 → 前 60% 拟合气候态、中 20% 只出残差分位数、末 20% 只做独立测试；
  预测 = by_month[目标月号]（缺月回退拟合段总体均值 fallback）；
  覆盖 = clip(pred+p05, lower=0) <= actual <= clip(pred+p95, ratio 类上界 1)（闭区间）。

T+30/60 与该回测的关系：季节基线回测是任务级的（按目标月），与具体时效无关；运行层在
T+30/T+60 无评估充分的逐站模型时回退消费同一份 backtest 记录（algorithm_models.py
_climatology_result 直接透传 empirical_coverage/coverage_n）。因此逐行复算任务级回测
即覆盖 T+30/60 的接口覆盖率口径。

输出（只写 backend/calibration_work/，r2_ 前缀）：
  r2_seasonal_climatology_recheck.json   5 任务对账总表
  r2_seasonal_coverage_rows.csv          独立测试段逐行覆盖明细
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PKG = BACKEND / "model_runtime_v0_3"
sys.path.insert(0, str(PKG / "code"))

warnings.filterwarnings("ignore")

from modeling_real.contracts_real import TASK_SPECS_REAL  # noqa: E402
from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402

CLIMATOLOGY_PATH = PKG / "evaluation" / "seasonal_climatology.json"
# 比值型输出的上界裁剪口径（与运行层/训练侧一致）
RATIO_VARIANTS = {"bloom", "coverage", "density", "probability", "spatial"}
CANDIDATE_TASKS = (("T1", "bloom"), ("T3", "density"), ("T4", "biomass"), ("T5", "chla"), ("T6", "probability"))


def _month_num(month: str) -> int:
    return int(str(month)[5:7])


def _clip(value: float, variant: str, *, lower: bool) -> float:
    if lower:
        return float(max(value, 0.0))
    return float(min(value, 1.0)) if variant in RATIO_VARIANTS else float(value)


def independent_backtest(frame: pd.DataFrame, variant: str):
    """独立重写三段回测核心：切段 → 气候态 → 校准段残差分位 → 测试段逐行覆盖。"""
    months = sorted(frame["target_month"].unique())
    total = len(months)
    fit_cut = int(total * 0.6)
    calib_cut = int(total * 0.8)
    fit_months = months[:fit_cut]
    calib_months = months[fit_cut:calib_cut]
    test_months = months[calib_cut:]

    fit_frame = frame.loc[frame["target_month"].isin(set(fit_months))]
    by_month = {
        str(_month_num(m)): float(fit_frame.loc[fit_frame["target_month"] == m, "actual_num"].mean())
        for m in fit_months
        if len(fit_frame.loc[fit_frame["target_month"] == m])
    }
    fallback = float(fit_frame["actual_num"].mean()) if len(fit_frame) else 0.0

    def _predict(seg: pd.DataFrame) -> np.ndarray:
        return np.asarray([
            by_month.get(str(_month_num(m)), fallback) for m in seg["target_month"]
        ], dtype=float)

    calib = frame.loc[frame["target_month"].isin(set(calib_months))]
    residual = calib["actual_num"].to_numpy(dtype=float) - _predict(calib)
    p05 = float(np.quantile(residual, 0.05))
    p95 = float(np.quantile(residual, 0.95))

    test = frame.loc[frame["target_month"].isin(set(test_months))].copy()
    pred_test = _predict(test)
    lo = np.asarray([_clip(float(v) + p05, variant, lower=True) for v in pred_test])
    hi = np.asarray([_clip(float(v) + p95, variant, lower=False) for v in pred_test])
    actual_test = test["actual_num"].to_numpy(dtype=float)
    covered = (actual_test >= lo) & (actual_test <= hi)
    test = test.assign(prediction=pred_test, interval_p05=lo, interval_p95=hi, covered=covered,
                       segment="independent_test")
    return {
        "segments": {
            "fit_months": fit_months, "calib_months": calib_months, "test_months": test_months,
        },
        "by_month": by_month,
        "fallback": fallback,
        "residual_quantiles": {"p05": p05, "p95": p95},
        "calibration_n": int(len(calib)),
        "coverage": {
            "covered": int(covered.sum()),
            "coverage_n": int(len(actual_test)),
            "rate": float(np.mean(covered)) if len(actual_test) else None,
        },
        "test_frame": test,
    }


def recheck_task(payload_task: dict, base: pd.DataFrame, labels: pd.DataFrame) -> dict:
    task_id, variant = payload_task["task_id"], payload_task["variant"]
    spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
    table = build_supervised_table(base, labels, spec, 0)
    frame = table.loc[:, ["target_month", "actual"]].copy()
    frame["actual_num"] = pd.to_numeric(frame["actual"], errors="coerce")
    frame = frame.loc[frame["actual_num"].notna()].reset_index(drop=True)

    replay = independent_backtest(frame, variant)
    bt = payload_task.get("backtest") or {}

    diffs = {
        "by_month_max_abs_diff": float(np.max(np.abs([
            replay["by_month"].get(k, np.nan) - float(v)
            for k, v in (payload_task.get("by_month") or {}).items()
        ]))) if payload_task.get("by_month") else None,
        "fallback_abs_diff": abs(replay["fallback"] - float(payload_task["fallback"])),
        "p05_abs_diff": abs(replay["residual_quantiles"]["p05"] - float(bt["residual_quantiles"]["p05"])),
        "p95_abs_diff": abs(replay["residual_quantiles"]["p95"] - float(bt["residual_quantiles"]["p95"])),
        "coverage_count_match": replay["coverage"]["covered"] == int(round(float(bt["empirical_coverage"]) * float(bt["coverage_n"])))
        if bt.get("empirical_coverage") is not None and bt.get("coverage_n") else False,
        "coverage_n_match": replay["coverage"]["coverage_n"] == int(bt.get("coverage_n") or -1),
        "coverage_rate_abs_diff": abs(
            replay["coverage"]["rate"] - float(bt["empirical_coverage"])
        ) if replay["coverage"]["rate"] is not None and bt.get("empirical_coverage") is not None else None,
        "calibration_n_match": replay["calibration_n"] == int(bt.get("interval_calibration_n") or -1),
        "segments_match": (
            max(replay["segments"]["fit_months"]) == bt.get("train_max_month")
            and min(replay["segments"]["calib_months"]) == bt.get("interval_calibration_min_month")
            and max(replay["segments"]["calib_months"]) == bt.get("interval_calibration_max_month")
            and min(replay["segments"]["test_months"]) == bt.get("test_min_month")
            and max(replay["segments"]["test_months"]) == bt.get("test_max_month")
        ),
    }
    pos = int(np.sum(replay["test_frame"]["actual_num"].to_numpy() > 0.5))
    neg = int(len(replay["test_frame"]) - pos)
    diffs["class_support_match"] = (
        pos == int(bt.get("test_positive_n") or 0) and neg == int(bt.get("test_negative_n") or 0)
        and (pos > 0 and neg > 0) == bool(bt.get("class_support_sufficient"))
    ) if bt.get("test_positive_n") is not None else None

    all_match = (
        diffs["by_month_max_abs_diff"] is not None and diffs["by_month_max_abs_diff"] < 1e-12
        and diffs["fallback_abs_diff"] < 1e-12
        and diffs["p05_abs_diff"] < 1e-12 and diffs["p95_abs_diff"] < 1e-12
        and diffs["coverage_count_match"] and diffs["coverage_n_match"]
        and (diffs["coverage_rate_abs_diff"] is None or diffs["coverage_rate_abs_diff"] < 1e-12)
        and diffs["calibration_n_match"] and diffs["segments_match"]
        and (diffs["class_support_match"] is None or diffs["class_support_match"])
    )
    return {
        "task_id": task_id,
        "variant": variant,
        "problem_type": payload_task.get("problem_type"),
        "artifact_record": {
            "empirical_coverage": bt.get("empirical_coverage"),
            "coverage_n": bt.get("coverage_n"),
            "covered_implied": int(float(bt["empirical_coverage"]) * float(bt["coverage_n"]))
            if bt.get("empirical_coverage") is not None and bt.get("coverage_n") else None,
            "test_window": [bt.get("test_min_month"), bt.get("test_max_month")],
            "interval_calibration_n": bt.get("interval_calibration_n"),
            "residual_quantiles": bt.get("residual_quantiles"),
            "test_positive_n": bt.get("test_positive_n"),
            "test_negative_n": bt.get("test_negative_n"),
            "class_support_sufficient": bt.get("class_support_sufficient"),
        },
        "recomputed": {
            "n_rows_total": int(len(frame)),
            "n_unique_target_months": int(frame["target_month"].nunique()),
            "fit_months_range": [min(replay["segments"]["fit_months"]), max(replay["segments"]["fit_months"])],
            "calib_months_range": [min(replay["segments"]["calib_months"]), max(replay["segments"]["calib_months"])],
            "test_months_range": [min(replay["segments"]["test_months"]), max(replay["segments"]["test_months"])],
            "covered": replay["coverage"]["covered"],
            "coverage_n": replay["coverage"]["coverage_n"],
            "coverage_rate": replay["coverage"]["rate"],
            "test_positive_n": pos,
            "test_negative_n": neg,
        },
        "diffs": diffs,
        "all_match": bool(all_match),
        "consumed_by": "运行层 T+30/T+60（及未被逐站模型覆盖的时效）回退季节基线时，"
                       "uncertainty.empirical_coverage 直接透传本 backtest 记录"
                       "（algorithm_models._climatology_result）。",
    }


def main() -> None:
    payload = json.loads(CLIMATOLOGY_PATH.read_text(encoding="utf-8"))
    assert payload.get("artifact_version") == "seasonal_climatology_v4", (
        f"unexpected artifact version: {payload.get('artifact_version')}"
    )
    base, labels = build_supervised_base()
    results = []
    rows_all = []
    for entry in payload["tasks"]:
        if (entry["task_id"], entry["variant"]) not in CANDIDATE_TASKS:
            continue
        res = recheck_task(entry, base, labels)
        results.append(res)
        # 逐行明细
        spec = next(s for s in TASK_SPECS_REAL if s.task_id == res["task_id"] and s.variant == res["variant"])
        table = build_supervised_table(base, labels, spec, 0)
        frame = table.loc[:, ["target_month", "actual"]].copy()
        frame["actual_num"] = pd.to_numeric(frame["actual"], errors="coerce")
        frame = frame.loc[frame["actual_num"].notna()].reset_index(drop=True)
        rep = independent_backtest(frame, res["variant"])
        test_frame = rep["test_frame"]
        for _, r in test_frame.iterrows():
            rows_all.append({
                "task_id": res["task_id"], "variant": res["variant"],
                "target_month": r["target_month"], "actual": r["actual_num"],
                "point_prediction": r["prediction"], "interval_p05": r["interval_p05"],
                "interval_p95": r["interval_p95"], "covered": bool(r["covered"]),
            })
        print(f"[{res['task_id']}-{res['variant']}] recomputed "
              f"{res['recomputed']['covered']}/{res['recomputed']['coverage_n']}"
              f" = {res['recomputed']['coverage_rate']:.6f} | artifact "
              f"{res['artifact_record']['empirical_coverage']}"
              f" | all_match={res['all_match']}")

    out_rows = pd.DataFrame(rows_all)
    out_rows.to_csv(HERE / "r2_seasonal_coverage_rows.csv", index=False, encoding="utf-8-sig")
    summary = {
        "artifact": str(CLIMATOLOGY_PATH),
        "artifact_version": payload.get("artifact_version"),
        "artifact_generated_at": payload.get("generated_at"),
        "replay_code": f"workspace modeling_real @ git HEAD e698d0a（监督表构建同源；回测计算独立重写）",
        "cal_07_note": (
            "台账 L-cal-07 的 71.97%（n=132）为 2026-09-12 审查时点旧产物的接口读数；"
            "R1 冻结重跑后 v4 产物已重新生成，本轮对当前产物从原始监督表逐行独立复算。"
        ),
        "tasks": results,
        "all_tasks_match": all(r["all_match"] for r in results),
    }
    (HERE / "r2_seasonal_climatology_recheck.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("[done] all_tasks_match:", summary["all_tasks_match"])


if __name__ == "__main__":
    main()
