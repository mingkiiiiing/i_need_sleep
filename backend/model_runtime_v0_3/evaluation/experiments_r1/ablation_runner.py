# -*- coding: utf-8 -*-
"""T3a 同切分消融脚手架（ablation runner，实验子目录 experiments_r1 专用）。

三种模式：
  offline   对既有 runs/*/ 产物做离线复算：同一冻结评估帧上逐族（机理-only / RF-only /
            XGB-only / 机理特征级联 / 残差融合 / 受约束混合 + 对照基线）重算主指标与
            uplift，行结构对齐 gate_table 字段，并与 gate_table.json 交叉核对。
            不重训练、不写 models/、不改 gate_table。
  selftest  合成小样例面板（synthetic，明确标注非证据），走 retrain 同一条代码路径，
            证明「同切分、同 seed、五消融族、统一 JSON」链路可用（T3a dry-run）。
  retrain   T3b 用：重建监督表 →（可选）套用 T1 审计切分 → 同 seed 重训消融族 →
            同一冻结评估帧统一输出 JSON。数据审计未交付前不得作为证据使用。

复用优先：全部拟合/评估逻辑复用 modeling_real.training_real 的既有实现
（_fit_ai / _fit_mechanism / _fit_fusion / evaluate_real / candidate_factories_real），
本脚本只做编排与口径核算，不重造模型。

本目录内产物一律为实验草案（draft），不得直接顶替 gate_table.json；
最终门禁仍由 gate.py 在 T3b 冻结评估后生成。

用法（工程根目录）：
  python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py offline \
      [--runs-dir PATH] [--out PATH] [--only NAME,SUBSTR]
  python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py selftest [--out PATH]
  python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
      --task T3 --variant density --horizons 1,3,7,15 [--split-source PATH.json] \
      [--seed N] [--families a,b,c] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent           # .../evaluation/experiments_r1
PKG_ROOT = HERE.parents[1]                        # .../model_runtime_v0_3
CODE_DIR = PKG_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from modeling_real.contracts_real import (  # noqa: E402
    DEFAULT_SEED_V3,
    FEATURE_COLUMNS_V2,
    HORIZON_MAP_V3,
    TARGET_SOURCE_FEATURE_EXCLUSIONS,
    TASK_LABELS_ZH,
    TASK_SPECS_REAL,
)
from modeling_real.data_real import RealPreprocessor, StationMonthSource  # noqa: E402
from modeling_real.training_real import (  # noqa: E402
    _fit_ai,
    _fit_fusion,
    _fit_mechanism,
    _mech_values,
    _metric_direction,
    _predict_output,
    _primary_value,
    candidate_factories_real,
    evaluate_real,
)

# 与 gate.py 保持同一冻结口径（只读对齐，不在此重新发明）
FUSION_FAMILIES = ("mechanism_feature", "residual", "constrained_blend")
SINGLE_AI_FAMILIES = ("random_forest", "xgboost")
HIGHER_IS_BETTER = {"macro_f1", "accuracy", "roc_auc", "pr_auc"}
UPLIFT_THRESHOLD = 0.10
MIN_TEST_ROWS = 15

# 消融五臂（T3a 任务规定）+ 对照披露族
ABLATION_ARMS = ("mechanism", "random_forest", "xgboost", "mechanism_feature", "residual")
OPTIONAL_FUSION = ("constrained_blend",)
REFERENCE_BASELINES = ("simple_baseline", "climatology_global", "persistence")

FAMILY_ROLE = {
    "mechanism": "mechanism_only",
    "random_forest": "single_ai",
    "xgboost": "single_ai",
    "mechanism_feature": "fusion",
    "residual": "fusion",
    "constrained_blend": "fusion",
    "simple_baseline": "reference_baseline",
    "climatology_global": "reference_baseline",
    "persistence": "reference_baseline",
}

FROZEN_METRIC_SPEC = {
    "spec_doc": "experiments_r1/口径冻结提案_20260912.md（草案，待主控入台账后生效）",
    "primary_metrics": {
        "binary": "brier_score", "probability": "brier_score",
        "regression_density": "log1p_mae", "regression_default": "mae",
        "ordinal": "macro_f1",
    },
    "uplift_formula_min": "uplift = (baseline_metric - model_metric) / baseline_metric",
    "uplift_formula_max": "uplift = (model_metric - baseline_metric) / baseline_metric",
    "baseline_rule": "同 run、同切分、同 seed 下 validation 主指标最优的单一数据驱动族（RF/XGBoost 较优者）",
    "direction": "min 指标（brier/mae/log1p_mae）下降为正提升；max 指标（macro_f1）上升为正提升",
    "pass_rule": "uplift >= 0.10 且 n_test >= 15；基准为 0 / 指标不可算时不机械算百分比，如实记 INDETERMINATE",
    "no_mixing": "R²、准确率、误差下降百分比不得混写；每条提升声明必须绑定单一主指标名",
}

HONESTY_NOTE = (
    "本表为 T3a 消融脚手架草案：offline 模式只对既有产物做同帧复算（不重训练、不挑选子集）；"
    "selftest/retrain 模式的行必须按 evidence_source 标注，synthetic_selftest 一律不是证据；"
    "最终门禁状态以 T3b 冻结评估后 gate.py 生成的 gate_table.json 为准。"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(payload: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def uplift_of(model_value: float | None, baseline_value: float | None, direction: str) -> float | None:
    """冻结提升公式（与 gate.py 同式）；基准为 0 或不可算时返回 None，不机械算百分比。"""
    if model_value is None or baseline_value is None:
        return None
    if not (isinstance(baseline_value, (int, float)) and baseline_value == baseline_value):
        return None
    if baseline_value == 0:
        return None
    if direction == "max":
        return (model_value - baseline_value) / baseline_value
    return (baseline_value - model_value) / baseline_value


def status_of(uplift: float | None, n_test: int, value: float | None) -> str:
    """消融行候选状态（不是最终门禁状态；最终以 gate.py 冻结评估为准）。"""
    if n_test < MIN_TEST_ROWS:
        return f"NA_test_n_below_{MIN_TEST_ROWS}"
    if uplift is None:
        return "INDETERMINATE_baseline_zero_or_not_computable"
    if uplift >= UPLIFT_THRESHOLD:
        return "PASS_candidate"
    return "FAIL_below_10pct" if uplift >= 0 else "FAIL_worse_than_baseline"


def row_status(family: str, single_family: str | None, family_metrics: dict | None,
               uplift: float | None, n_test: int, value: float | None) -> str:
    """行状态：基线自身行 / 族失败行优先，其余按 uplift 规则。"""
    if family_metrics is not None and "error" in family_metrics:
        return "ERROR_family_failed"
    if single_family and family == single_family:
        return "BASELINE_row"
    return status_of(uplift, n_test, value)


def _family_value(metrics: dict | None, primary: str) -> float | None:
    if not isinstance(metrics, dict) or "error" in metrics:
        return None
    value = metrics.get(primary)
    if value is None and primary == "macro_f1":
        value = metrics.get("accuracy")
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _validation_pick(candidates: list[str], validation_by_family: dict, primary: str, direction: str) -> str | None:
    """复刻 gate.py 的 validation 选族规则（含 macro_f1→accuracy 回退与平 tie 取序首）。"""
    def vp(family: str) -> float | None:
        return _family_value(validation_by_family.get(family, {}), primary)

    usable = [f for f in candidates if vp(f) is not None]
    if not usable:
        return None
    pick = (max if direction == "max" else min)(usable, key=vp)
    return pick


# ---------------------------------------------------------------- offline 模式

def _test_frame_facts(run_dir: Path) -> dict:
    """从 test_predictions.csv 提取评估窗口与标签支持（只读，不挑子集）。"""
    csv_path = run_dir / "test_predictions.csv"
    facts: dict[str, Any] = {"test_month_min": None, "test_month_max": None,
                             "test_positives": None, "test_label_counts": None,
                             "actual_source": None}
    if not csv_path.is_file():
        return facts
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return facts
    if "month" in df.columns and len(df):
        facts["test_month_min"] = str(df["month"].min())
        facts["test_month_max"] = str(df["month"].max())
    if "actual" in df.columns:
        actual = df["actual"]
        facts["actual_source"] = "test_predictions.csv"
        numeric = pd.to_numeric(actual, errors="coerce")
        if numeric.notna().any() and numeric.dropna().isin([0, 1]).all():
            facts["test_positives"] = int((numeric == 1).sum())
        counts = actual.astype("object").value_counts(dropna=False)
        # 序数任务 CSV 的 actual 被 pd.to_numeric 强转过（gate 评估路径现状），NaN 说明如实带出
        facts["test_label_counts"] = {str(k): int(v) for k, v in counts.items()[:8]} \
            if isinstance(counts, dict) else {str(k): int(v) for k, v in counts.iloc[:8].items()}
    return facts


def offline_row(run_dir: Path, gate_row_by_run: dict[str, dict]) -> dict | None:
    config = _read_json(run_dir / "run_config.json")
    selection = _read_json(run_dir / "selection_manifest.json")
    test_metrics = _read_json(run_dir / "test_metrics_by_family.json")
    primary = str(config["primary_metric"])
    direction = "max" if primary in HIGHER_IS_BETTER else "min"
    validation_by_family = selection.get("validation_metrics_by_family", {})
    selected = str(selection.get("selected_family"))

    fusion_family = selected if selected in FUSION_FAMILIES else _validation_pick(
        [f for f in FUSION_FAMILIES if f in test_metrics], validation_by_family, primary, direction)
    single_family = _validation_pick(
        [f for f in SINGLE_AI_FAMILIES if f in test_metrics], validation_by_family, primary, direction)

    base_facts = {
        "task_id": config["task_id"],
        "task_label": TASK_LABELS_ZH.get(config["task_id"], config["task_id"]),
        "variant": config["variant"],
        "horizon_days": int(config["horizon_days"]),
        "month_offset": int(config["month_offset"]),
        "granularity_tier": config.get("granularity_tier"),
        "target": config.get("problem_type"),
        "primary_metric": primary,
        "metric_direction": direction,
        "run_id": config.get("run_id"),
        "data_version": config.get("data_version"),
        "training_protocol": config.get("protocol")
        or (config.get("split_protocol") or {}).get("protocol_id")
        or "frozen_split",
        "evidence_source": "runs_artifact_offline",
        "seed": config.get("seed"),
    }
    facts = _test_frame_facts(run_dir)

    # gate 交叉核对：用同一规则复算 gate 行的 fusion/single/uplift
    cross_check: dict[str, Any] = {"gate_table_reproduced": None}
    gate_row = gate_row_by_run.get(str(config.get("run_id")))
    if fusion_family and single_family:
        fusion_value = _family_value(test_metrics.get(fusion_family), primary)
        single_value = _family_value(test_metrics.get(single_family), primary)
        n_test = int((test_metrics.get(selected) or {}).get("n") or 0)
        repro_uplift = uplift_of(fusion_value, single_value, direction)
        if gate_row and gate_row.get("uplift") is not None and repro_uplift is not None:
            cross_check = {
                "gate_fusion_value": gate_row.get("fusion_value"),
                "gate_best_single_value": gate_row.get("best_single_value"),
                "gate_uplift": gate_row.get("uplift"),
                "reproduced_fusion_value": fusion_value,
                "reproduced_best_single_value": single_value,
                "reproduced_uplift": repro_uplift,
                "gate_table_reproduced": bool(
                    math.isclose(float(gate_row["fusion_value"]), fusion_value, rel_tol=1e-12)
                    and math.isclose(float(gate_row["best_single_value"]), single_value, rel_tol=1e-12)
                ),
            }
        elif gate_row:
            # gate NA 行（n_test<15 等）：uplift 本身不参与判定，按数值是否复现核对
            ok = True
            if gate_row.get("fusion_value") is not None and fusion_value is not None:
                ok = ok and math.isclose(float(gate_row["fusion_value"]), fusion_value, rel_tol=1e-12)
            if gate_row.get("best_single_value") is not None and single_value is not None:
                ok = ok and math.isclose(float(gate_row["best_single_value"]), single_value, rel_tol=1e-12)
            cross_check = {
                "gate_fusion_value": gate_row.get("fusion_value"),
                "gate_best_single_value": gate_row.get("best_single_value"),
                "gate_uplift": gate_row.get("uplift"),
                "gate_na_reason": gate_row.get("na_reason"),
                "reproduced_fusion_value": fusion_value,
                "reproduced_best_single_value": single_value,
                "gate_table_reproduced": bool(ok),
            }

    # 机理退化甄别：机理族在同一评估帧上是否与常数基线完全同值 / 输出是否常数
    mech_metrics = test_metrics.get("mechanism")
    simple_metrics = test_metrics.get("simple_baseline")
    mech_value = _family_value(mech_metrics, primary)
    simple_value = _family_value(simple_metrics, primary)
    mechanism_degenerate = bool(
        mech_value is not None and simple_value is not None and mech_value == simple_value
    )

    rows = []
    families = [f for f in (*ABLATION_ARMS, *OPTIONAL_FUSION, *REFERENCE_BASELINES) if f in test_metrics]
    for family in families:
        value = _family_value(test_metrics.get(family), primary)
        role = FAMILY_ROLE.get(family, "other")
        baseline_value = single_value if single_family else None
        upl = None if family == single_family else uplift_of(value, baseline_value, direction)
        rows.append({
            **base_facts,
            "run_dir": run_dir.name,
            "n_test": int((test_metrics.get(family) or {}).get("n") or 0),
            **facts,
            "ablation_family": family,
            "family_role": role,
            "test_value": value,
            "baseline_family": single_family,
            "baseline_value": baseline_value,
            "uplift_vs_best_single": upl,
            "status_vs_threshold": row_status(family, single_family, test_metrics.get(family),
                                              upl, int((test_metrics.get(family) or {}).get("n") or 0), value),
            "mechanism_degenerate_run": mechanism_degenerate,
            "gate_selected_family": selected,
            "gate_cross_check": cross_check if family in (fusion_family, single_family) else None,
        })
    return {
        "base": base_facts,
        "rows": rows,
        "fusion_family": fusion_family,
        "single_family": single_family,
        "selected_family": selected,
        "mechanism_degenerate": mechanism_degenerate,
    }


def detect_duplicate_experiments(run_summaries: list[dict]) -> list[dict]:
    """同源复用甄别：同 (task, variant, month_offset, protocol) 组内各时效的各族指标完全
    相同 → 判为同一实验的多行引用（gate_table 结构性问题的自动证据）。"""
    groups: dict[tuple, list[dict]] = {}
    for summary in run_summaries:
        base = summary["base"]
        key = (base["task_id"], base["variant"], base["month_offset"], base["training_protocol"])
        groups.setdefault(key, []).append(summary)
    out = []
    def _norm(v):
        # 浮点归一：同一实验重复评估允许 1e-12 相对量级的累加抖动
        return None if v is None else float("%.12g" % float(v))
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        signatures = set()
        for member in members:
            sig = tuple(sorted(
                (r["ablation_family"], _norm(r["test_value"]))
                for r in member["rows"] if r["test_value"] is not None
            ))
            signatures.add(sig)
        same_experiment = len(signatures) == 1
        out.append({
            "group_key": {"task_id": key[0], "variant": key[1],
                          "month_offset": key[2], "training_protocol": key[3]},
            "horizon_days": sorted(m["base"]["horizon_days"] for m in members),
            "run_dirs": sorted(m["base"].get("run_dir", "") for m in members if "run_dir" in m)
            or sorted(m["base"]["run_id"] for m in members),
            "metrics_identical_across_horizons": same_experiment,
            "independent_experiments": 1 if same_experiment else len(members),
            "verdict": ("同一实验的多时效复用（月度粒度映射 month_offset=0 所致），"
                        "10% 声明不得按 4 条独立证据计" if same_experiment
                        else "各时效指标不同，视为独立实验"),
        })
    return out


def cmd_offline(runs_dir: Path, out: Path, only: str | None) -> dict:
    runs_dir = Path(runs_dir)
    gate_path = PKG_ROOT / "evaluation" / "gate_table.json"
    gate_rows_by_run: dict[str, dict] = {}
    if gate_path.is_file():
        for row in _read_json(gate_path).get("rows", []):
            gate_rows_by_run[str(row.get("run_id"))] = row

    summaries, skipped = [], []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if only and only not in run_dir.name:
            continue
        needed = ("run_config.json", "selection_manifest.json", "test_metrics_by_family.json")
        if not all((run_dir / f).is_file() for f in needed):
            skipped.append(run_dir.name)
            continue
        try:
            summaries.append(offline_row(run_dir, gate_rows_by_run))
        except Exception as exc:  # noqa: BLE001 — 单 run 失败不阻断整体复算
            skipped.append(f"{run_dir.name}: {exc}")

    rows = [r for s in summaries for r in s["rows"]]
    gate_reproduced = [
        r["gate_cross_check"]["gate_table_reproduced"]
        for r in rows if r.get("gate_cross_check") and r["gate_cross_check"].get("gate_table_reproduced") is not None
    ]
    payload = {
        "runner": "ablation_runner.py",
        "mode": "offline",
        "generated_at": _utc_now(),
        "runs_dir": str(runs_dir),
        "frozen_metric_spec": FROZEN_METRIC_SPEC,
        "summary": {
            "runs_scanned": len(summaries),
            "rows": len(rows),
            "runs_skipped": skipped,
            "mechanism_degenerate_runs": sum(1 for s in summaries if s["mechanism_degenerate"]),
            "gate_cross_check_rows": len(gate_reproduced),
            "gate_cross_check_reproduced": sum(1 for v in gate_reproduced if v),
            "status_counts": {
                k: sum(1 for r in rows if r["status_vs_threshold"] == k)
                for k in sorted({r["status_vs_threshold"] for r in rows})
            },
        },
        "duplicate_experiment_groups": detect_duplicate_experiments(summaries),
        "rows": rows,
        "honesty_note": HONESTY_NOTE,
    }
    _write_json(payload, out)
    s = payload["summary"]
    print(f"[offline] runs={s['runs_scanned']} rows={s['rows']} "
          f"mechanism_degenerate={s['mechanism_degenerate_runs']}/{s['runs_scanned']} "
          f"gate_reproduced={s['gate_cross_check_reproduced']}/{s['gate_cross_check_rows']} → {out}")
    return payload


# ------------------------------------------------ retrain 路径（selftest 与 T3b 共用）

def _actual_values(frame: pd.DataFrame, problem_type: str) -> np.ndarray:
    """评估用真值：序数标签保持字符串（修复 gate 现路径 pd.to_numeric 把序数标签强转成
    NaN、产生幻影类 'nan' 的问题——见口径冻结提案 4.3）；其余转数值。"""
    if problem_type == "ordinal":
        return frame["actual"].astype(str).to_numpy(dtype=object)
    return pd.to_numeric(frame["actual"], errors="coerce").to_numpy(dtype=float)


def run_ablation_on_table(
    spec,
    table: pd.DataFrame,
    feature_columns: tuple[str, ...],
    seed: int,
    families: tuple[str, ...],
    horizon_days: int,
    evidence_source: str,
    climatology_history: pd.DataFrame | None = None,
) -> dict:
    """同一切分、同 seed 下训练并评估消融族；输出 gate 对齐行。

    复用 training_real 的工厂与指标实现；评估真值不做 pd.to_numeric 强转（序数修复）。
    """
    source = StationMonthSource(table, feature_columns)
    train = source.collect_split("train")
    validation = source.collect_split("validation")
    test = source.collect_split("test")
    meta = {
        "task_id": spec.task_id,
        "task_label": TASK_LABELS_ZH.get(spec.task_id, spec.task_id),
        "variant": spec.variant,
        "horizon_days": int(horizon_days),
        "month_offset": int(HORIZON_MAP_V3.month_offset(horizon_days)),
        "granularity_tier": HORIZON_MAP_V3.tier(horizon_days),
        "target": spec.problem_type,
        "primary_metric": spec.primary_metric,
        "metric_direction": _metric_direction(spec.primary_metric),
        "run_id": f"{spec.task_id}-{spec.variant}-ablation-r1",
        "seed": int(seed),
        "evidence_source": evidence_source,
        "split_counts": {"train": int(len(train)), "validation": int(len(validation)),
                         "test": int(len(test))},
        "test_window": {
            "month_min": str(test["month"].min()) if len(test) else None,
            "month_max": str(test["month"].max()) if len(test) else None,
        },
    }
    if not len(train) or not len(validation):
        return {"meta": meta, "rows": [], "error": "train/validation 为空，不可训练"}
    if len(test) < 3 and evidence_source != "synthetic_selftest":
        meta["test_warning"] = f"test 仅 {len(test)} 行，低于门禁最小行数 {MIN_TEST_ROWS}，行状态将为 NA"

    preprocessor = RealPreprocessor.fit(train, feature_columns)
    train_f = preprocessor.transform(train).assign(actual=train["actual"].to_numpy())
    train_f["month"] = train["month"].to_numpy()
    val_f = preprocessor.transform(validation).assign(actual=validation["actual"].to_numpy())
    test_f = preprocessor.transform(test)

    factories: dict[str, Callable] = candidate_factories_real(
        spec, seed, month_offset=meta["month_offset"], climatology_history=climatology_history,
    )

    val_actual = _actual_values(validation, spec.problem_type)
    test_actual = _actual_values(test, spec.problem_type)
    validation_metrics: dict[str, dict] = {}
    test_metrics: dict[str, dict] = {}
    prediction_unique: dict[str, int] = {}
    for name in families:
        factory = factories.get(name)
        if factory is None:
            validation_metrics[name] = {"error": f"factory 不存在（序数任务 residual 被注册表剔除等）"}
            continue
        try:
            candidate = factory(train_f, val_f)
            val_pred = _predict_output(candidate, val_f.loc[:, list(preprocessor.output_columns)], spec)
            prob_v = (val_pred["probability"].to_numpy(dtype=float)
                      if spec.problem_type in {"binary", "probability"} else None)
            vm = evaluate_real(spec, val_actual, val_pred["prediction"].to_numpy(), prob_v)
            validation_metrics[name] = vm
            test_pred = _predict_output(candidate, test_f.loc[:, list(preprocessor.output_columns)], spec)
            prob_t = (test_pred["probability"].to_numpy(dtype=float)
                      if spec.problem_type in {"binary", "probability"} else None)
            test_metrics[name] = evaluate_real(spec, test_actual, test_pred["prediction"].to_numpy(), prob_t)
            # 退化诊断取列：概率任务看 probability；其余（含 ordinal 字符串标签）看
            # prediction——ordinal 的 prediction 列经 _predict_output 也会补出全 NaN
            # 的 probability 列，取它会得到 nunique=0 的假诊断。
            uniq_col = ("probability"
                        if spec.problem_type in {"binary", "probability"} and "probability" in test_pred.columns
                        else "prediction")
            prediction_unique[name] = int(test_pred[uniq_col].nunique())
        except Exception as exc:  # noqa: BLE001 — 单族失败不阻断其它族
            validation_metrics[name] = {"error": str(exc)}
            test_metrics[name] = {"error": str(exc)}

    primary = spec.primary_metric
    direction = _metric_direction(primary)
    single_family = _validation_pick(
        [f for f in SINGLE_AI_FAMILIES if f in families], validation_metrics, primary, direction)
    single_value = _family_value(test_metrics.get(single_family), primary) if single_family else None
    simple_value = _family_value(test_metrics.get("simple_baseline"), primary)
    mech_value = _family_value(test_metrics.get("mechanism"), primary)
    mechanism_degenerate = bool(
        mech_value is not None and simple_value is not None and mech_value == simple_value
    ) or prediction_unique.get("mechanism", 2) <= 1

    positives = None
    if spec.problem_type in {"binary", "probability"} and len(test_actual):
        positives = int(np.nansum(np.asarray(test_actual, dtype=float) == 1))

    rows = []
    for name in families:
        value = _family_value(test_metrics.get(name), primary)
        n_test = int((test_metrics.get(name) or {}).get("n") or 0)
        upl = None if name == single_family else uplift_of(value, single_value, direction)
        rows.append({
            **meta,
            "n_test": n_test,
            "test_positives": positives,
            "ablation_family": name,
            "family_role": FAMILY_ROLE.get(name, "other"),
            "test_value": value,
            "validation_value": _family_value(validation_metrics.get(name), primary),
            "baseline_family": single_family,
            "baseline_value": single_value,
            "uplift_vs_best_single": upl,
            "status_vs_threshold": row_status(name, single_family, test_metrics.get(name),
                                              upl, n_test, value),
            "mechanism_degenerate_run": mechanism_degenerate,
            "prediction_unique_test": prediction_unique.get(name),
        })
    return {
        "meta": {k: v for k, v in meta.items() if k != "run_id"} | {"run_id": meta["run_id"]},
        "rows": rows,
        "selected_family_gate_rule": single_family,
        "mechanism_degenerate": mechanism_degenerate,
        "validation_metrics_by_family": {
            k: {kk: vv for kk, vv in v.items() if kk != "calibration_bins"}
            for k, v in validation_metrics.items() if isinstance(v, dict)
        },
    }


def _task_feature_columns(table: pd.DataFrame, spec) -> tuple[str, ...]:
    excluded = set(TARGET_SOURCE_FEATURE_EXCLUSIONS.get(spec.label_family, ()))
    return tuple(c for c in FEATURE_COLUMNS_V2 if c in table.columns and c not in excluded)


def _synthetic_panel(seed: int) -> tuple[dict[str, pd.DataFrame], dict[str, tuple[str, ...]]]:
    """合成小样例面板（明确标注 synthetic_selftest，绝非证据）：12 站 × 48 月，
    机理因子含真实信号，目标由机理量 + AI 可学的非线性项构成；时间 60/20/20 三块切分。"""
    rng = np.random.default_rng(seed)
    stations = [f"ST{i:02d}" for i in range(12)]
    months = [f"{y}-{m:02d}" for y in (2015, 2016, 2017, 2018) for m in range(1, 13)]
    rows = []
    row_id = 0
    for month in months:
        m_num = int(month[-2:])
        season = np.sin(2 * np.pi * m_num / 12)
        for st in stations:
            row_id += 1
            tp = float(rng.gamma(2.0, 0.05) + 0.05)
            tn = float(rng.gamma(2.0, 0.5) + 0.2)
            temp = float(17 + 8 * season + rng.normal(0, 1.2))
            light = float(np.clip(0.5 + 0.4 * season + rng.normal(0, 0.05), 0, 1.2))
            tf = float(np.clip((temp - 12) / 10, 0, 1.5))
            lf = float(np.clip(light / 0.8, 0, 1.5))
            pf = float(np.clip(tp / 0.2, 0, 2))
            nf = float(np.clip(tn / 1.2, 0, 2))
            growth = 0.6 * tf * lf * min(pf, nf) - 0.1
            latent = 8 + 30 * max(growth, 0) + 6 * tp + rng.normal(0, 2.0)
            rows.append({
                "station_id": st, "month": month, "row_id": row_id,
                "wq_tp": tp, "wq_tn": tn, "wq_do": float(rng.normal(8, 0.8)),
                "wq_nh4_n": float(abs(rng.normal(0.3, 0.1))),
                "wq_ph": float(rng.normal(7.8, 0.25)),
                "met_air_temperature_c": temp,
                "met_shortwave_radiation_wm2": float(150 + 100 * season + rng.normal(0, 15)),
                "hydro_water_level_m": float(rng.normal(3.2, 0.2)),
                "wq_phyto_biomass": float(max(latent, 0.0) / 40 + rng.normal(0, 0.02)),
                "mech_temperature_factor": tf, "mech_light_factor": lf,
                "mech_phosphorus_factor": pf, "mech_nitrogen_factor": nf,
                "mech_nutrient_factor": float(min(pf, nf)),
                "mech_net_growth_rate_d": float(growth),
                "calendar_month_sin": float(np.sin(2 * np.pi * m_num / 12)),
                "calendar_month_cos": float(np.cos(2 * np.pi * m_num / 12)),
            })
    frame = pd.DataFrame(rows)
    months_sorted = sorted(frame["month"].unique())
    tr_end = months_sorted[int(len(months_sorted) * 0.6) - 1]
    va_end = months_sorted[int(len(months_sorted) * 0.8) - 1]

    def split_of(m: str) -> str:
        return "train" if m <= tr_end else ("validation" if m <= va_end else "test")

    frame["dataset_split_frozen"] = frame["month"].map(split_of)

    # 回归目标（叶绿素样例）与序数目标（风险带样例）
    latent = frame.apply(lambda r: 8 + 30 * max(r["mech_net_growth_rate_d"], 0)
                         + 6 * r["wq_tp"] + float(np.sin(int(r["row_id"])) * 1.5), axis=1)
    rng2 = np.random.default_rng(seed + 1)
    frame["actual"] = np.maximum(latent.to_numpy() + rng2.normal(0, 1.5, len(frame)), 0.0)
    # RF/XGB 可学的额外非线性项（保证 AI 单族不至于与机理完全同信息）
    frame["actual"] = frame["actual"] + 2.5 * np.sin(0.8 * frame["wq_tp"].to_numpy() * 10) ** 2

    risk_frame = frame.copy()
    def band(v: float) -> str:
        return "none" if v < 20 else ("low" if v < 30 else ("medium" if v < 50 else "high"))
    risk_frame["actual"] = risk_frame["actual"].map(band)

    feat = ("wq_tp", "wq_tn", "wq_do", "wq_nh4_n", "wq_ph", "wq_phyto_biomass",
            "met_air_temperature_c", "met_shortwave_radiation_wm2", "hydro_water_level_m",
            "mech_temperature_factor", "mech_light_factor", "mech_phosphorus_factor",
            "mech_nitrogen_factor", "mech_nutrient_factor", "mech_net_growth_rate_d",
            "calendar_month_sin", "calendar_month_cos")
    return {"T5-chla-0m": frame, "T6-risk_level-0m": risk_frame}, {"T5-chla-0m": feat, "T6-risk_level-0m": feat}


def cmd_selftest(out: Path, seed: int) -> dict:
    """dry-run：合成小样例走 retrain 同一代码路径（回归 + 序数两种目标），证明链路可用。"""
    panels, feats = _synthetic_panel(seed)
    all_rows, groups = [], []
    for key, table in panels.items():
        task_id, variant = key.rsplit("-", 1)[0].split("-", 1)
        spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
        # 序数任务无 residual（注册表剔除），按注册表现状取族
        probe = candidate_factories_real(spec, seed)
        families = tuple(f for f in (*ABLATION_ARMS, *OPTIONAL_FUSION, *REFERENCE_BASELINES) if f in probe)
        result = run_ablation_on_table(
            spec, table.copy(), feats[key], seed, families, horizon_days=1,
            evidence_source="synthetic_selftest",
        )
        result["meta"]["panel"] = key
        groups.append(result)
        all_rows.extend(result["rows"])
    payload = {
        "runner": "ablation_runner.py",
        "mode": "selftest",
        "generated_at": _utc_now(),
        "seed": int(seed),
        "frozen_metric_spec": FROZEN_METRIC_SPEC,
        "summary": {
            "panels": [g["meta"].get("panel") for g in groups],
            "rows": len(all_rows),
            "errors": [g.get("error") for g in groups if g.get("error")],
            "ordinal_macro_f1_nonzero": any(
                (r["ablation_family"] != "simple_baseline" and (r["test_value"] or 0) > 0)
                for r in all_rows if r["primary_metric"] == "macro_f1"
            ),
            "status_counts": {
                k: sum(1 for r in all_rows if r["status_vs_threshold"] == k)
                for k in sorted({r["status_vs_threshold"] for r in all_rows})
            },
        },
        "groups": [
            {k: v for k, v in g.items() if k != "rows"} | {"rows": g["rows"]}
            for g in groups
        ],
        "rows": all_rows,
        "honesty_note": HONESTY_NOTE + " 本文件全部行来自合成数据（synthetic_selftest），仅证明链路可用，不是任何任务的证据。",
    }
    _write_json(payload, out)
    s = payload["summary"]
    print(f"[selftest] panels={len(s['panels'])} rows={s['rows']} "
          f"ordinal_f1_nonzero={s['ordinal_macro_f1_nonzero']} → {out}")
    return payload


def _apply_internal_time_block(table: pd.DataFrame, split_key: str = "month") -> tuple[pd.DataFrame, dict]:
    """训练期内时间分块 60/20/20（与 cli_real_cv.train_internal_time_block_cv_v1 同口径）。

    冻结表 validation/test 无行（标签全在冻结 train 期）时的唯一合法回退：
    按月份时序切块、无前视，同一 (task, horizon) 的全部消融族共用同一切分。
    """
    table = table.copy()
    months = sorted(table[split_key].unique())
    if len(months) < 5:
        return table, {"split_mode": "internal_time_block", "split_error": f"months<{len(months)}，无法分块"}
    train_end = months[max(int(len(months) * 0.6) - 1, 0)]
    validation_end = months[max(int(len(months) * 0.8) - 1, 0)]

    def split_of(month: str) -> str:
        if month <= train_end:
            return "train"
        if month <= validation_end:
            return "validation"
        return "test"

    table["dataset_split_frozen"] = [split_of(m) for m in table[split_key]]
    info = {
        "split_mode": "internal_time_block_cv_v1",
        "split_key": split_key,
        "block_bounds": {"train_max_month": train_end, "validation_max_month": validation_end,
                         "test_min_month": months[months.index(validation_end) + 1]},
    }
    return table, info


def cmd_retrain(task: str, variant: str, horizons: list[int], split_source: Path | None,
                seed: int, families: tuple[str, ...] | None, out: Path) -> dict:
    """T3b 模式：真实监督表 + （可选）T1 审计切分 → 同切分同 seed 消融重训。"""
    from modeling_real.target_builder import build_availability_matrix, build_supervised_base

    spec = next((s for s in TASK_SPECS_REAL if s.task_id == task and s.variant == variant), None)
    if spec is None:
        raise SystemExit(f"unknown task/variant: {task}/{variant}")

    split_map: dict[Any, str] | None = None
    if split_source is not None:
        payload = json.loads(Path(split_source).read_text(encoding="utf-8"))
        split_map = {k: v for k, v in payload.get("row_id_to_split", {}).items()}

    base, labels = build_supervised_base()
    _entries, tables = build_availability_matrix(base, labels)
    all_rows, groups = [], []
    for horizon in horizons:
        offset = HORIZON_MAP_V3.month_offset(horizon)
        table = tables.get(f"{task}-{variant}-{offset}m")
        if table is None or not len(table):
            groups.append({"horizon_days": horizon, "error": "监督表为空"})
            continue
        table = table.copy()
        split_info: dict = {"split_mode": "asis_frozen_table"}
        if split_map is not None:
            table["dataset_split_frozen"] = table["row_id"].map(
                lambda rid: split_map.get(str(rid), split_map.get(rid)))
            unmapped = int(table["dataset_split_frozen"].isna().sum())
            if unmapped:
                groups.append({"horizon_days": horizon,
                               "warning": f"split_source 未覆盖 {unmapped} 行，未覆盖行不进入任何 split"})
                table = table.dropna(subset=["dataset_split_frozen"])
            split_info = {"split_mode": "t1_audit_split_source", "split_source": str(split_source)}
        elif int((table["dataset_split_frozen"] == "validation").sum()) < 5:
            # 冻结表 validation 不足（T3/T4/T5/T6 现状）：训练期内时间分块回退（无前视）
            table, split_info = _apply_internal_time_block(
                table, "target_month" if offset >= 1 else "month")
        feats = _task_feature_columns(table, spec)
        probe = candidate_factories_real(spec, seed)
        fams = families or tuple(f for f in (*ABLATION_ARMS, *OPTIONAL_FUSION, *REFERENCE_BASELINES) if f in probe)
        history = None
        if offset >= 1:
            # climatology_history 与 cli_real_cv._climatology_history 同口径：用同一任务
            # mo=0 监督表的真实标签序列估月气候态，截断到本 run 测试段最早目标月之前
            # （无前视）。缺省 None 会让 mo>=1 的气候态退化为拟合段"几乎全 0 查表"。
            mo0_table = tables.get(f"{task}-{variant}-0m")
            test_months = table.loc[table["dataset_split_frozen"] == "test", "target_month"] \
                if "target_month" in table.columns else pd.Series(dtype=object)
            if mo0_table is not None and len(mo0_table) and len(test_months):
                cutoff = str(test_months.min())
                hist_frame = mo0_table.loc[mo0_table["target_month"] < cutoff]
                keep = [c for c in ("actual", *feats) if c in hist_frame.columns]
                if "actual" in keep and len(hist_frame):
                    history = hist_frame.loc[:, keep].reset_index(drop=True)
        result = run_ablation_on_table(spec, table, feats, seed, fams, horizon,
                                       evidence_source="retrain_draft", climatology_history=history)
        result["meta"].update(split_info)
        groups.append(result)
        all_rows.extend(result["rows"])
    payload = {
        "runner": "ablation_runner.py",
        "mode": "retrain_draft",
        "generated_at": _utc_now(),
        "task": task, "variant": variant, "horizons": horizons,
        "split_source": str(split_source) if split_source else None,
        "seed": int(seed),
        "frozen_metric_spec": FROZEN_METRIC_SPEC,
        "summary": {
            "rows": len(all_rows),
            "status_counts": {
                k: sum(1 for r in all_rows if r["status_vs_threshold"] == k)
                for k in sorted({r["status_vs_threshold"] for r in all_rows})
            },
        },
        "groups": groups,
        "rows": all_rows,
        "honesty_note": HONESTY_NOTE + " retrain_draft 行在 T1 审计切分落地并通过主控确认前不是门禁证据。",
    }
    _write_json(payload, out)
    print(f"[retrain] rows={len(all_rows)} → {out}")
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="T3a 同切分消融脚手架")
    parser.add_argument("mode", choices=("offline", "selftest", "retrain"))
    parser.add_argument("--runs-dir", default=str(PKG_ROOT / "runs"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--only", default=None, help="offline：只扫描目录名含该子串的 run")
    parser.add_argument("--task", default=None)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--horizons", default="1,3,7,15")
    parser.add_argument("--split-source", default=None, help="T1 审计切分 JSON：{\"row_id_to_split\": {...}}")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED_V3)
    parser.add_argument("--families", default=None)
    args = parser.parse_args(argv)

    stamp = "20260912"
    if args.mode == "offline":
        out = Path(args.out or HERE / "dryrun" / f"ablation_offline_{stamp}.json")
        cmd_offline(Path(args.runs_dir), out, args.only)
        return 0
    if args.mode == "selftest":
        out = Path(args.out or HERE / "dryrun" / f"ablation_selftest_{stamp}.json")
        cmd_selftest(out, args.seed)
        return 0
    if args.mode == "retrain":
        if not args.task or not args.variant:
            raise SystemExit("retrain 需要 --task 与 --variant")
        out = Path(args.out or HERE / f"ablation_retrain_{args.task}_{args.variant}_draft.json")
        families = tuple(args.families.split(",")) if args.families else None
        cmd_retrain(args.task, args.variant, [int(h) for h in args.horizons.split(",")],
                    Path(args.split_source) if args.split_source else None,
                    args.seed, families, out)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
