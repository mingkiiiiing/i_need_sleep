"""V0.3 站点留出（spatial holdout）验收：leave-one-zone-out CV。

背景：冻结划分是纯时间留出，8 个太湖分区站的 576 行真实标签（2005-02..2020-11）
全部落在 train 期，"模型能否泛化到未见站点"从未被度量过。本脚本在 serving 契约下
对站间响应任务做 8 折留一分区站交叉验证：

* 每折：留出 1 个分区站的全部 train 期行，在其余 7 站的早 70% 月份上拟合候选族，
  以晚 30% 月份做族选择（与补训 CV 协议同一时间分块口径），再在留出站全部
  train 期月份上评估主指标；
* 对照：同折同评估集上的 simple_baseline（训练期均值常数）；
* 汇总：各折 primary 指标均值、优于基线的折数比例。

诚实边界：评估集仍在 train 期（2005-2020），该协议只度量「跨站点空间泛化」，
不度量时间外推；结果如实写入 evaluation/station_cv.json，不参与任何选择。

用法：
  python backend/model_runtime_v0_3/code/modeling_real/station_cv.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from modeling_real.contracts_real import (  # noqa: E402
    DATA_VERSION_V3,
    DEFAULT_SEED_V3,
    HORIZON_MAP_V3,
    SERVING_FEATURE_COLUMNS_V2,
    TASK_SPECS_REAL,
    package_root,
)
from modeling_real.data_real import RealPreprocessor, StationMonthSource  # noqa: E402
from modeling_real.target_builder import (  # noqa: E402
    build_availability_matrix,
    build_supervised_base,
)
from modeling_real.training_real import (  # noqa: E402
    _metric_direction,
    _primary_value,
    candidate_factories_real,
    evaluate_real,
)

SEED = DEFAULT_SEED_V3
TIME_BLOCK_FRACTION = 0.7
# 只对「站点响应已实测为真」的任务做空间留出；常数基线胜出的任务没有可泛化的
# 站点响应，空间留出无意义（如实记录在 skipped 中）。
CV_TASKS = (("T3", "density", 1), ("T4", "biomass", 1))
ZONE_PREFIX = "TAIHU_"


def _zones_of(frame: pd.DataFrame) -> list[str]:
    ids = [
        s for s in frame["station_id"].unique()
        if str(s).startswith(ZONE_PREFIX) and str(s) != "TAIHU_WHOLE"
    ]
    return sorted(ids)


def _eval_family(candidate, features: pd.DataFrame, spec) -> tuple[np.ndarray, np.ndarray]:
    out = candidate.predict_frame(features)
    prob = (
        out["probability"].to_numpy(dtype=float)
        if spec.problem_type in {"binary", "probability"}
        else None
    )
    pred = out["prediction"].to_numpy(dtype=float)
    return pred, prob


def cv_task(task_id: str, variant: str, horizon_days: int, base: pd.DataFrame, labels: pd.DataFrame) -> dict:
    spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
    offset = HORIZON_MAP_V3.month_offset(horizon_days)
    _entries, tables = build_availability_matrix(base, labels)
    table = tables[f"{task_id}-{variant}-{offset}m"].copy()
    table = table[table["dataset_split_frozen"] == "train"].copy()
    months = sorted(table["month"].unique())
    if len(months) < 6:
        return {"task_id": task_id, "variant": variant, "status": "skipped", "reason": "months<6"}
    cut = months[int(len(months) * TIME_BLOCK_FRACTION)]
    zones = _zones_of(table)
    source = StationMonthSource(
        table, tuple(c for c in SERVING_FEATURE_COLUMNS_V2 if c in table.columns)
    )
    folds = []
    for held in zones:
        fit_frame = table[(table["station_id"] != held) & (table["month"] <= cut)]
        select_frame = table[(table["station_id"] != held) & (table["month"] > cut)]
        eval_frame = table[table["station_id"] == held].copy()
        if not len(fit_frame) or not len(select_frame) or not len(eval_frame):
            folds.append({"held_out_zone": held, "status": "skipped_empty_fold"})
            continue
        # 防泄漏：preprocessor 只在拟合折上 fit
        pre = RealPreprocessor.fit(fit_frame, source.feature_columns)
        fit_f = pre.transform(fit_frame).assign(actual=fit_frame["actual"].to_numpy())
        sel_f = pre.transform(select_frame).assign(actual=select_frame["actual"].to_numpy())
        eval_f = pre.transform(eval_frame)
        actual = pd.to_numeric(eval_frame["actual"], errors="coerce").to_numpy()
        factories = candidate_factories_real(spec, SEED)
        scored = {}
        candidates = {}
        for name, factory in factories.items():
            try:
                cand = factory(fit_f, None)
                pred, prob = _eval_family(cand, sel_f.loc[:, list(pre.output_columns)], spec)
                metrics = evaluate_real(spec, pd.to_numeric(select_frame["actual"], errors="coerce").to_numpy(), pred, prob)
                primary = _primary_value(metrics, spec)
                if primary is not None:
                    scored[name] = primary
                    candidates[name] = cand
            except Exception:  # noqa: BLE001 — 单候选失败不阻断折
                continue
        if not candidates:
            folds.append({"held_out_zone": held, "status": "skipped_no_candidate"})
            continue
        direction = _metric_direction(spec.primary_metric)
        selected = (max if direction == "max" else min)(scored, key=lambda n: scored[n])
        pred, prob = _eval_family(candidates[selected], eval_f.loc[:, list(pre.output_columns)], spec)
        model_metrics = evaluate_real(spec, actual, pred, prob)
        base_cand = candidates.get("simple_baseline") or factories["simple_baseline"](fit_f, None)
        base_pred, _ = _eval_family(base_cand, eval_f.loc[:, list(pre.output_columns)], spec)
        base_metrics = evaluate_real(spec, actual, base_pred, None)
        folds.append({
            "held_out_zone": held,
            "n_eval_rows": int(len(eval_frame)),
            "selected_family": selected,
            "model_primary": model_metrics.get(spec.primary_metric),
            "baseline_primary": base_metrics.get(spec.primary_metric),
            "model_mae": model_metrics.get("mae"),
            "baseline_mae": base_metrics.get("mae"),
            "beats_baseline": bool(
                model_metrics.get("mae") is not None
                and base_metrics.get("mae") is not None
                and model_metrics["mae"] < base_metrics["mae"]
            ),
        })
    usable = [f for f in folds if f.get("beats_baseline") is not None]
    wins = sum(1 for f in usable if f["beats_baseline"])
    return {
        "task_id": task_id,
        "variant": variant,
        "horizon_days": horizon_days,
        "protocol": "leave_one_zone_out_within_train_period",
        "time_block_fraction": TIME_BLOCK_FRACTION,
        "feature_contract": "serving",
        "primary_metric": spec.primary_metric,
        "n_folds": len(usable),
        "wins_vs_simple_baseline": wins,
        "win_rate": round(wins / len(usable), 4) if usable else None,
        "mean_model_mae": round(float(np.mean([f["model_mae"] for f in usable])), 4) if usable else None,
        "mean_baseline_mae": round(float(np.mean([f["baseline_mae"] for f in usable])), 4) if usable else None,
        "folds": folds,
    }


def main() -> int:
    base, labels = build_supervised_base()
    results = [cv_task(t, v, h, base, labels) for t, v, h in CV_TASKS]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_version": DATA_VERSION_V3,
        "seed": SEED,
        "disclosure": (
            "站点留出协议只度量跨站点空间泛化，评估集仍在冻结 train 期（2005-2020）；"
            "结果不参与任何模型选择，仅作为验收证据披露。"
        ),
        "tasks": results,
    }
    out = package_root() / "evaluation" / "station_cv.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(
            f"[station-cv] {r.get('task_id')}-{r.get('variant')}: folds={r.get('n_folds')} "
            f"wins={r.get('wins_vs_simple_baseline')} mean_mae={r.get('mean_model_mae')} "
            f"vs baseline={r.get('mean_baseline_mae')}"
        )
    print(f"[station-cv] → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
