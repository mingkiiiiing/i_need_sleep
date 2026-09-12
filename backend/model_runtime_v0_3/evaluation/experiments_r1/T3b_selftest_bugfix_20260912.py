# -*- coding: utf-8 -*-
"""T3b bug1+bug2 修复单元自证（20260912）。

用真实监督表验证两处修复（台账 L-diag-01/L-data-02 与 L-diag-02）：
  bug1  _mechanism_design 任务级剔除列收缩：T3-density / T4-biomass 的训练帧上，
        机理设计矩阵不再被 wq_phyto_biomass 连带置 NaN 打穿行有效性门，
        _fit_mechanism 不再常数回退（constant is None，HistGB 真实拟合）。
        旧口径（spec=None，缺席列置 NaN）作为对照复现 valid=0/全部行无效。
  bug2  序数评估 actual 直通：T6-risk_level 的 actual 是等级字符串，
        旧口径 pd.to_numeric 全 NaN → 幻影类；新口径 eval_actual_values 保持字符串，
        同一路径 RF 的 macro_f1 恢复非零。

输出 JSON 到 experiments_r1/dryrun/t3b_bugfix_selftest_20260912.json。
本脚本只读数据与代码，不写 runs/ 与 models/，产物为 draft 自证，不是门禁证据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

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
    TARGET_SOURCE_FEATURE_EXCLUSIONS,
    task_spec_real,
)
from modeling_real.data_real import RealPreprocessor, StationMonthSource  # noqa: E402
from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402
from modeling_real.training_real import (  # noqa: E402
    _fit_ai,
    _fit_mechanism,
    _mechanism_design,
    eval_actual_values,
    ordinal_metrics,
)


def task_feature_columns(table: pd.DataFrame, label_family: str) -> tuple[str, ...]:
    excluded = set(TARGET_SOURCE_FEATURE_EXCLUSIONS.get(label_family, ()))
    return tuple(c for c in FEATURE_COLUMNS_V2 if c in table.columns and c not in excluded)


def train_frame_of(table: pd.DataFrame, feats: tuple[str, ...]):
    source = StationMonthSource(table, feats)
    train = source.collect_split("train")
    preprocessor = RealPreprocessor.fit(train, feats)
    features = preprocessor.transform(train).assign(actual=train["actual"].to_numpy())
    return features


def check_mechanism(base, labels, task_id: str, variant: str) -> dict:
    """bug1 自证：修复口径设计矩阵行有效 + 不回退常数；旧口径复现 valid=0。"""
    spec = task_spec_real(task_id, variant)
    table = build_supervised_table(base, labels, spec, 0)
    feats = task_feature_columns(table, spec.label_family)
    features = train_frame_of(table, feats)
    assert "wq_phyto_biomass" not in features.columns, "任务监督表应已按契约剔除目标同源列"

    design_new = _mechanism_design(features, spec)
    x_new = design_new.to_numpy(dtype=float)
    valid_new = int(np.isfinite(x_new).all(axis=1).sum())

    design_old = _mechanism_design(features)  # spec=None：旧口径（缺席列置 NaN）
    x_old = design_old.to_numpy(dtype=float)
    valid_old = int(np.isfinite(x_old).all(axis=1).sum())

    candidate = _fit_mechanism(spec, features, DEFAULT_SEED_V3)
    prediction = candidate.predict_frame(features)
    return {
        "task_id": task_id,
        "variant": variant,
        "train_rows": int(len(features)),
        "design_columns_new": list(design_new.columns),
        "design_columns_new_n": int(x_new.shape[1]),
        "excluded_column_shrunk": "wq_phyto_biomass",
        "valid_rows_new": valid_new,
        "valid_rows_old_spec_none": valid_old,
        "old_path_valid_rows_all_lost": bool(valid_old == 0),
        "fit_mechanism_constant_is_none": candidate.constant is None,
        "fit_mechanism_model_loaded": candidate.model is not None,
        "prediction_unique_values": int(pd.Series(prediction["prediction"].to_numpy()).nunique()),
    }


def check_ordinal(base, labels) -> dict:
    """bug2 自证：T6-risk_level actual 字符串直通，同路径 RF macro_f1 恢复。"""
    spec = task_spec_real("T6", "risk_level")
    table = build_supervised_table(base, labels, spec, 0)
    feats = task_feature_columns(table, spec.label_family)

    # 冻结切分下 T6 的 validation/test 近空（标签全在训练期），用训练期内时间分块
    # 60/20/20（与 ablation_runner._apply_internal_time_block / cli_real_cv 同口径）
    months = sorted(table["month"].unique())
    train_end = months[max(int(len(months) * 0.6) - 1, 0)]
    validation_end = months[max(int(len(months) * 0.8) - 1, 0)]
    table = table.copy()
    table["dataset_split_frozen"] = [
        "train" if m <= train_end else ("validation" if m <= validation_end else "test")
        for m in table["month"]
    ]
    source = StationMonthSource(table, feats)
    train = source.collect_split("train")
    validation = source.collect_split("validation")
    test = source.collect_split("test")

    preprocessor = RealPreprocessor.fit(train, feats)
    train_f = preprocessor.transform(train).assign(actual=train["actual"].to_numpy())
    val_f = preprocessor.transform(validation).assign(actual=validation["actual"].to_numpy())
    test_f = preprocessor.transform(test)

    old_val = pd.to_numeric(validation["actual"], errors="coerce")
    actual_new_val = eval_actual_values(validation, spec)
    actual_new_test = eval_actual_values(test, spec)

    candidate = _fit_ai(spec, "random_forest", train_f, feats, DEFAULT_SEED_V3)
    val_pred = candidate.predict_frame(val_f)
    test_pred = candidate.predict_frame(test_f)
    metrics_val = ordinal_metrics(actual_new_val, val_pred["prediction"].to_numpy())
    metrics_test = ordinal_metrics(actual_new_test, test_pred["prediction"].to_numpy())
    # 完美预测 sanity：actual 对自身的 macro_f1 必须是 1.0（旧口径下不可能达到）
    sanity_self = ordinal_metrics(actual_new_test, actual_new_test)
    # 旧口径复现：to_numeric 后的 actual 传入 ordinal_metrics → 幻影类 'nan'
    old_actual_test = pd.to_numeric(test["actual"], errors="coerce").to_numpy()
    metrics_old_path = ordinal_metrics(old_actual_test, test_pred["prediction"].to_numpy())
    return {
        "task_id": "T6",
        "variant": "risk_level",
        "panel_rows": int(len(table)),
        "split_counts": {"train": int(len(train)), "validation": int(len(validation)),
                         "test": int(len(test))},
        "block_bounds": {"train_max_month": train_end, "validation_max_month": validation_end},
        "actual_value_counts": {str(k): int(v) for k, v in table["actual"].value_counts().items()},
        "old_path_numeric_nan_ratio_validation": float(old_val.isna().mean()),
        "new_path_actual_all_str": bool(all(isinstance(v, str) for v in actual_new_val)),
        "rf_macro_f1_validation_fixed": metrics_val["macro_f1"],
        "rf_macro_f1_test_fixed": metrics_test["macro_f1"],
        "rf_accuracy_test_fixed": metrics_test["accuracy"],
        "old_path_macro_f1_test": metrics_old_path["macro_f1"],
        "sanity_self_macro_f1": sanity_self["macro_f1"],
        "macro_f1_recovered": bool((metrics_test["macro_f1"] or 0) > 0.0),
    }


def main() -> int:
    base, labels = build_supervised_base()
    payload = {
        "selftest": "T3b bugfix unit selftest (bug1 mechanism shrink + bug2 ordinal actual passthrough)",
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "seed": DEFAULT_SEED_V3,
        "evidence_source": "retrain_draft_unit_selftest",
    }
    payload["bug1_mechanism"] = [
        check_mechanism(base, labels, "T3", "density"),
        check_mechanism(base, labels, "T4", "biomass"),
    ]
    payload["bug2_ordinal"] = check_ordinal(base, labels)
    out = HERE / "dryrun" / "t3b_bugfix_selftest_20260912.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ok1 = all(
        m["valid_rows_new"] > 0 and m["fit_mechanism_constant_is_none"]
        for m in payload["bug1_mechanism"]
    )
    ok2 = payload["bug2_ordinal"]["macro_f1_recovered"]
    print(json.dumps({
        "bug1_ok": ok1,
        "bug1_detail": [
            {k: m[k] for k in ("task_id", "train_rows", "valid_rows_new", "valid_rows_old_spec_none",
                               "fit_mechanism_constant_is_none", "prediction_unique_values")}
            for m in payload["bug1_mechanism"]
        ],
        "bug2_ok": ok2,
        "bug2_detail": {k: payload["bug2_ordinal"][k] for k in (
            "rf_macro_f1_test_fixed", "rf_accuracy_test_fixed", "old_path_macro_f1_test",
            "old_path_numeric_nan_ratio_validation", "sanity_self_macro_f1")},
        "out": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
