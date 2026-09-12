# -*- coding: utf-8 -*-
"""R2（任务包 R2 / 台账 L-cal-18）：把 K1 的 OOF+validation 残差池重建方法扩展到
T3-density 与 T4-biomass 的 T+1（mo0 cv run）与 T+90（mo3 cv run）四组。

方法与 K1（rebuild_oof_pool.py）一致：直接 import backend/model_runtime_v0_3/code/modeling_real
的真实实现（target_builder / data_real / training_real / cli_real_cv），按
cli_real_cv._train_cv_run 的三块时间切分（60/20/20，month 或 target_month）重现
train/validation/test，再以 train_run_real 完全相同的调用序列重放：
    train_features = preprocessor.transform(train).assign(actual=...)   [training_real:861-865]
    selected 族 = bundle.selected_family（并用 selection_manifest 主指标复核）
    OOF 残差   = training_real._fit_oof_residuals(...)                  [training_real:925-927]
    validation 残差 = val_actual - 装配模型对校准块的预测               [training_real:913-924]
    pooled = concat([oof, validation])；P05/P95 = np.quantile(pooled,[.05,.95])

与 K1 的三点差异（为何不再需要 _replay_pkg）：
1. 现码 = 训练码：2026-09-13 凌晨 R1 全量冻结重跑（双管线强制重训，commit e698d0a）后，
   runs/ 与 models/ 下的目标产物全部由当前工作区代码重新产生。K1 面对的"部署模型
   (09-11) 与工作区代码 (09-12+) 版本漂移"对新产物不再成立。本脚本 sys.path 只挂
   modeling_real 当前实现，绝不挂 _replay_pkg；并以下列机器锚点自证"现码=训练码"：
     a) 重放 train_features 指纹 == 新 run selection_manifest.feature_sha256；
     b) 重放测试段逐行预测 == 新 run test_predictions.csv（逐行）；
     c) 重放校准块主指标 == selection_manifest.validation_value；
     d) 重建池 P05/P95 == 新模型内嵌 residual_p05/p95（calibration_n 同）。
   任一锚点失败即 all_checks_pass=false，不出可信产物。
2. 特征契约：本轮重跑日志（evaluation/rerun_r3/cv_stdout.log 首行）确认 train-cv 以
   frozen-78col 契约运行（无 TAIHU_FEATURE_CONTRACT=serving）。因此 feature_columns
   不取 SERVING_FEATURE_COLUMNS_V2（K1 面对的是 09-11 serving-8col 旧模型），而是直接
   采用 bundle.feature_columns（= 训练时 StationMonthSource 的特征列；T3/T4 均为
   77 列 = 78 契约列 − 目标同源 wq_phyto_biomass），并与 frozen-78col 交集逐项核对。
3. climatology_history（offset≥1 的 climatology_global 族需要）：照抄
   cli_real_cv.cmd_train_cv 的构造——用同一任务 month_offset=0 监督表，截断到留出
   测试段起点之前（目标月严格小于 test_start），保证折内/校准/测试全程无前视。

输出（只写 backend/calibration_work/，全部 r2_ 前缀，不触碰 K1 既有产物）：
  r2_residual_pool_<task>-<variant>_T+<h>_mo<offset>.csv / .json   ×4
  r2_reconcile_<task>-<variant>_T+<h>_mo<offset>.json              ×4
  r2_rebuild_summary.json
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
# 注意：本脚本只用现码。绝不把 calibration_work/_replay_pkg 加进 sys.path——
# 那是 K1 为重演 2026-09-11 旧模型锁定的代码快照，与本轮新产物无关。
sys.path.insert(0, str(PKG / "code"))

import joblib  # noqa: E402

warnings.filterwarnings("ignore")

from modeling_real.contracts_real import (  # noqa: E402
    DEFAULT_SEED_V3,
    FEATURE_COLUMNS_V2,
    TASK_SPECS_REAL,
)
from modeling_real.data_real import (  # noqa: E402
    RealPreprocessor,
    StationMonthSource,
    frame_digest,
)
from modeling_real.target_builder import build_supervised_base, build_supervised_table  # noqa: E402
from modeling_real.training_real import candidate_factories_real as _factories  # noqa: E402
from modeling_real.training_real import _fit_oof_residuals, _predict_output, regression_metrics  # noqa: E402
from modeling_real.cli_real_cv import (  # noqa: E402
    CV_BLOCK_TRAIN_FRACTION,
    CV_BLOCK_VALIDATION_FRACTION,
    _climatology_history,
)

SEED = DEFAULT_SEED_V3
PROTOCOL = "train_internal_time_block_cv_v1"
GIT_HEAD = "e698d0a"  # R1 冻结重跑产物所在提交；本轮自证"现码=训练码"的参照

SCHEMA = {
    "columns": {
        "row_id": "监督底表行号（model_dataset 行索引，任务内唯一）",
        "station_id": "空间单元（站点/全湖实体）",
        "month": "输入月 YYYY-MM",
        "target_month": "被预测月 YYYY-MM（offset=0 时等于输入月）",
        "dataset_split_frozen": "本次 CV 块内的角色 train/validation/test",
        "fold_id": "折标识（OOF=early->late 两折的 late 折；validation=CV 校准块）",
        "fold_role": "该行在折中的角色",
        "source": "oof | validation（残差池来源，严格分开）",
        "prediction": "预测值（OOF=early-only 折模型对 late 的预测；validation=装配模型对校准块的预测）",
        "actual": "实际标签值",
        "residual": "actual - prediction",
        "actual_provenance": "逐行标签来源",
        "model_sha256": "对应交付模型文件 sha256（身份锚点）",
        "run_id": "run 标识",
        "protocol": "评估协议",
        "in_fit_months": "OOF 行是否落在折模型拟合月范围内（必须为 False 才是真 OOF）",
        "fit_month_max": "折模型拟合块的最大月",
        "predict_month_min": "被预测块的最小月",
        "predictor_row_id_span": "折模型拟合行 row_id 数量（用于核对未见样本）",
    },
    "note": "沿用 K1 residual_pool_schema.json 同一 schema；r2_ 前缀文件为 R2 新增，覆盖 T3-density/T4-biomass 四组。"
            "pooled 分位数按 OOF 在前、validation 在后拼接，与 training_real:928-936 一致。",
}

CASES = [
    # (task_id, variant, horizon, offset, split_key, run_dir, model_file)
    ("T3", "density", 1, 0, "month", "T3-density-1d-0m-cv", "T3-density-0m-s20260907-1d.joblib"),
    ("T3", "density", 90, 3, "target_month", "T3-density-90d-3m-cv", "T3-density-3m-s20260907-90d.joblib"),
    ("T4", "biomass", 1, 0, "month", "T4-biomass-1d-0m-cv", "T4-biomass-0m-s20260907-1d.joblib"),
    ("T4", "biomass", 90, 3, "target_month", "T4-biomass-90d-3m-cv", "T4-biomass-3m-s20260907-90d.joblib"),
]


def _write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def cv_split(table: pd.DataFrame, split_key: str) -> tuple[pd.DataFrame, str, str, str | None]:
    """复刻 cli_real_cv._train_cv_run 的时间三块切分（60/20/20，按 split_key 月序）。"""
    months = sorted(table[split_key].unique())
    train_end = months[max(int(len(months) * CV_BLOCK_TRAIN_FRACTION) - 1, 0)]
    validation_end = months[
        max(int(len(months) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)) - 1, 0)
    ]

    def _split_of(month: str) -> str:
        if month <= train_end:
            return "train"
        if month <= validation_end:
            return "validation"
        return "test"

    out = table.copy()
    out["dataset_split_frozen"] = [_split_of(m) for m in out[split_key]]
    test_start = months[months.index(validation_end) + 1] if validation_end in months else None
    return out, train_end, validation_end, test_start


def reconstruct(task_id: str, variant: str, horizon: int, offset: int, split_key: str,
                run_dir: str, model_file: str,
                base: pd.DataFrame, labels: pd.DataFrame) -> dict:
    spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
    bundle = joblib.load(PKG / "models" / model_file)
    model_sha256 = hashlib.sha256((PKG / "models" / model_file).read_bytes()).hexdigest()

    table = build_supervised_table(base, labels, spec, offset)
    table, train_end, validation_end, test_start = cv_split(table, split_key)
    counts = table["dataset_split_frozen"].value_counts().to_dict()

    # 特征契约：本轮重跑为 frozen-78col；直接采用训练时真实使用的列（bundle 内预处理器
    # 的 feature_columns），并核对它等于 78col 契约与监督表的交集（frozen-78col 语义）。
    feature_columns = tuple(bundle.feature_columns)
    frozen_intersection = tuple(c for c in FEATURE_COLUMNS_V2 if c in table.columns)
    feature_contract_matches_frozen78 = feature_columns == frozen_intersection

    # offset≥1：月气候态基线的拟合样本照抄 cli_real_cv.cmd_train_cv（0m 表截断到测试段前）
    history = None
    if offset >= 1:
        history_table = build_supervised_table(base, labels, spec, 0)
        months_sorted = sorted(table[split_key].unique())
        clim_test_start = months_sorted[max(int(len(months_sorted) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)), 0)]
        history = _climatology_history(history_table, clim_test_start, feature_columns)

    source = StationMonthSource(table, feature_columns)
    meta = table.set_index("row_id")[["station_id", "target_month", "actual_provenance", "month"]]

    def _enrich(frame: pd.DataFrame) -> pd.DataFrame:
        # collect_split 只回传 特征列/actual/month/month_order/row_id（data_real.collect_split:104）；
        # 身份列按 row_id 从监督表补回，不改变特征/actual/排序口径。
        out = frame.copy()
        joined = meta.reindex(out["row_id"])
        out["station_id"] = joined["station_id"].to_numpy()
        out["target_month"] = joined["target_month"].to_numpy()
        out["actual_provenance"] = joined["actual_provenance"].to_numpy()
        return out

    train = _enrich(source.collect_split("train"))
    validation = _enrich(source.collect_split("validation"))
    test = _enrich(source.collect_split("test"))

    pre = RealPreprocessor.fit(train, source.feature_columns)
    tf = pre.transform(train).assign(actual=train["actual"].to_numpy())
    tf["month_order"] = train["month_order"].to_numpy()
    tf["month"] = train["month"].to_numpy()
    vf = pre.transform(validation).assign(actual=validation["actual"].to_numpy())
    vf["month_order"] = validation["month_order"].to_numpy()

    factories = _factories(spec, SEED, month_offset=offset, climatology_history=history)
    selected = bundle.selected_family

    # 装配模型（与训练一致：factory(train_features, validation_features)），复核族选择主指标
    cand_full = factories[selected](tf, vf)
    pred_vf = _predict_output(cand_full, vf.loc[:, list(pre.output_columns)], spec)
    val_actual_num = pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
    replay_primary = regression_metrics(
        val_actual_num, pred_vf["prediction"].to_numpy(dtype=float)
    )[spec.primary_metric]

    # ---- 保真锚 A：重放 train_features 指纹 == 新 run selection_manifest.feature_sha256 ----
    sel_manifest = json.loads((PKG / "runs" / run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    replay_digest = frame_digest(tf.drop(columns=["month_order"]))
    digest_match = replay_digest == sel_manifest["feature_sha256"]

    # ---- 保真锚 B：重放测试段逐行预测 == 新 run test_predictions.csv ----
    test_features = pre.transform(test)
    pred_test = _predict_output(cand_full, test_features, spec)
    run_test = pd.read_csv(PKG / "runs" / run_dir / "test_predictions.csv")
    aligned = run_test.set_index("row_id").loc[test["row_id"].to_numpy()]
    test_replay_max_abs_diff = float(np.max(np.abs(
        pred_test["prediction"].to_numpy(dtype=float) - aligned["prediction"].to_numpy(dtype=float)
    )))

    # ---- OOF 残差：调用原函数 + 逐行重建（两者必须一致，容差 1e-9）----
    oof_vec = _fit_oof_residuals(tf, source, spec, selected, factories, pre, SEED)
    months_t = np.sort(tf["month"].unique())
    cut = months_t[max(2, int(len(months_t) * 0.7))]
    early_mask = tf["month"] < cut
    early, late = tf[early_mask], tf[~early_mask]
    fit_months = sorted(early["month"].unique())
    cand_oof = factories[selected](early, None)  # early-only 折模型（validation=None）
    pred_late = _predict_output(cand_oof, late.loc[:, list(pre.output_columns)], spec)
    pv_late = pred_late["prediction"].to_numpy(dtype=float)
    av_late = pd.to_numeric(late["actual"], errors="coerce").to_numpy()
    res_late = av_late - pv_late
    finite_late = np.isfinite(res_late)

    def _tf_meta(frame: pd.DataFrame) -> pd.DataFrame:
        # tf = pre.transform(train) 已 reset_index，行位置 == train 行位置（train_run_real:861），
        # 但 transform 只保留 output_columns，故身份列按行位置从 train 帧取回。
        pos = np.asarray(frame.index, dtype=int)
        return pd.DataFrame({
            "row_id": train["row_id"].to_numpy()[pos],
            "station_id": train["station_id"].to_numpy()[pos],
            "month": train["month"].to_numpy()[pos],
            "target_month": train["target_month"].to_numpy()[pos],
            "actual_provenance": train["actual_provenance"].to_numpy()[pos],
        })

    late_ids = _tf_meta(late)
    oof_df = pd.DataFrame({
        "row_id": late_ids["row_id"].to_numpy()[finite_late],
        "station_id": late_ids["station_id"].to_numpy()[finite_late],
        "month": late_ids["month"].to_numpy()[finite_late],
        "target_month": late_ids["target_month"].to_numpy()[finite_late],
        "actual_provenance": late_ids["actual_provenance"].to_numpy()[finite_late],
        "prediction": pv_late[finite_late],
        "actual": av_late[finite_late],
        "residual": res_late[finite_late],
    })
    oof_df["dataset_split_frozen"] = "train"
    oof_df["fold_id"] = "train_expanding_2fold_late"
    oof_df["fold_role"] = "late_holdout_of_early_fit"
    oof_df["source"] = "oof"
    oof_df["in_fit_months"] = False
    oof_df["fit_month_max"] = max(fit_months)
    oof_df["predict_month_min"] = str(min(late["month"].unique()))
    oof_df["predictor_row_id_span"] = int(len(early))
    oof_df["model_sha256"] = model_sha256
    oof_df["run_id"] = bundle.run_id
    oof_df["protocol"] = PROTOCOL

    # ---- validation 残差 ----
    pv_val = pred_vf["prediction"].to_numpy(dtype=float)
    res_val = val_actual_num - pv_val
    finite_val = np.isfinite(res_val)
    val_df = pd.DataFrame({
        "row_id": validation["row_id"].to_numpy()[finite_val],
        "station_id": validation["station_id"].to_numpy()[finite_val],
        "month": validation["month"].to_numpy()[finite_val],
        "target_month": validation["target_month"].to_numpy()[finite_val],
        "actual_provenance": validation["actual_provenance"].to_numpy()[finite_val],
        "prediction": pv_val[finite_val],
        "actual": val_actual_num[finite_val],
        "residual": res_val[finite_val],
    })
    val_df["dataset_split_frozen"] = "validation"
    val_df["fold_id"] = "cv_validation_block"
    val_df["fold_role"] = "calibration_block"
    val_df["source"] = "validation"
    val_df["in_fit_months"] = False
    val_df["fit_month_max"] = max(tf["month"].unique())
    val_df["predict_month_min"] = str(min(validation["month"].unique()))
    val_df["predictor_row_id_span"] = int(len(tf))
    val_df["model_sha256"] = model_sha256
    val_df["run_id"] = bundle.run_id
    val_df["protocol"] = PROTOCOL

    pool_cols = list(oof_df.columns)
    pooled_df = pd.concat([oof_df[pool_cols], val_df[pool_cols]], ignore_index=True)
    pooled_values = np.concatenate([oof_df["residual"].to_numpy(), val_df["residual"].to_numpy()])
    p05 = float(np.quantile(pooled_values, 0.05))
    p95 = float(np.quantile(pooled_values, 0.95))

    # ---- 自证（五重对账 + 现码=训练码锚点）----
    oof_max_abs_diff = (
        float(np.max(np.abs(oof_vec - res_late[finite_late])))
        if len(oof_vec) == int(finite_late.sum()) and len(oof_vec) else float("inf")
    )
    oof_ids = set(oof_df["row_id"].tolist())
    val_ids = set(val_df["row_id"].tolist())
    train_ids = set(train["row_id"].tolist())
    val_split_ids = set(validation["row_id"].tolist())
    test_ids = set(test["row_id"].tolist())
    run_config = json.loads((PKG / "runs" / run_dir / "run_config.json").read_text(encoding="utf-8"))
    rebuilt_bounds = {"train_max_month": train_end, "validation_max_month": validation_end,
                      "test_min_month": test_start}

    # 测试段经验覆盖率按模型内嵌分位数复算（不参与拟合，仅对账 uncertainty.json）
    point_test = pred_test["prediction"].to_numpy(dtype=float)
    actual_test = pd.to_numeric(test["actual"], errors="coerce").to_numpy()
    covered = (actual_test >= point_test + float(bundle.intervals.residual_p05)) & (
        actual_test <= point_test + float(bundle.intervals.residual_p95))
    uncertainty_run = json.loads((PKG / "runs" / run_dir / "uncertainty.json").read_text(encoding="utf-8"))

    checks = {
        # 现码=训练码三锚（本脚本未用 _replay_pkg，通过即证明现码重放出训练产物）
        "replay_feature_digest_matches_run_selection_manifest": bool(digest_match),
        "prediction_frame_replay_matches_run_test_predictions": bool(test_replay_max_abs_diff < 1e-9),
        "selection_primary_metric_replay_matches_manifest": bool(
            replay_primary is not None
            and abs(float(replay_primary) - float(sel_manifest["validation_value"])) < 1e-9
        ),
        "feature_columns_equal_frozen78_intersection": bool(feature_contract_matches_frozen78),
        "preprocessor_medians_match_bundle": bool(
            all(abs(pre.medians[k] - bundle.preprocessor.medians[k]) < 1e-12 for k in pre.medians)
        ),
        # ① 行数
        "pool_n_equals_bundle_calibration_n": int(len(pooled_values)) == int(bundle.intervals.calibration_n),
        # ② 样本身份
        "oof_ids_subset_of_cv_train": oof_ids <= train_ids,
        "oof_ids_disjoint_from_validation_ids": len(oof_ids & val_ids) == 0,
        "validation_ids_equals_cv_validation": val_ids == val_split_ids,
        "pool_ids_disjoint_from_cv_test": len((oof_ids | val_ids) & test_ids) == 0,
        # ③ 折切分（early-only 折模型，无冒充）
        "oof_rows_all_in_late_block": bool((late_ids["month"].to_numpy()[finite_late] >= cut).all()),
        "early_months_all_before_cut": bool((early["month"] < cut).all()),
        "early_and_late_no_row_overlap": len(set(_tf_meta(early)["row_id"]) & set(late_ids["row_id"])) == 0,
        "fold_boundary_strictly_increasing_time": bool(max(fit_months) < min(late["month"].unique())),
        # ④ 残差值
        "oof_residual_vector_matches_within_tol": bool(oof_max_abs_diff < 1e-9),
        # ⑤ 分位数
        "p05_equals_bundle": bool(abs(p05 - float(bundle.intervals.residual_p05)) < 1e-12),
        "p95_equals_bundle": bool(abs(p95 - float(bundle.intervals.residual_p95)) < 1e-12),
        # 附：切分边界与 run_config 对账
        "split_block_bounds_match_run_config": rebuilt_bounds == {
            k: run_config["split_block_bounds"][k] for k in rebuilt_bounds
        },
    }
    reconcile = {
        "task_id": task_id,
        "variant": variant,
        "model_file": model_file,
        "model_sha256": model_sha256,
        "run_dir": run_dir,
        "run_id": bundle.run_id,
        "horizon_days": horizon,
        "month_offset": offset,
        "split_key": split_key,
        "protocol": PROTOCOL,
        "replay_code": {
            "source": f"workspace modeling_real @ git HEAD {GIT_HEAD}（R1 冻结重跑所用代码，工作区干净）",
            "replay_pkg_used": False,
            "reason": "R1 于 2026-09-13 以修复后代码强制重训全部 42 runs；新产物由现码产生，"
                      "L-cal-16 的版本漂移不再适用。本脚本三锚（特征指纹/测试逐行预测/分位数）通过即自证现码=训练码。",
            "replay_feature_digest": replay_digest,
            "run_feature_sha256": sel_manifest["feature_sha256"],
            "digest_match": bool(digest_match),
        },
        "feature_contract": {
            "expected": "frozen-78col（rerun_r3/cv_stdout.log 首行）",
            "n_features": len(feature_columns),
            "equals_frozen78_intersection": bool(feature_contract_matches_frozen78),
        },
        "selected_family": selected,
        "split_block_bounds_recomputed": rebuilt_bounds,
        "split_block_bounds_run_config": run_config.get("split_block_bounds"),
        "split_counts_recomputed": {
            "train": int(counts.get("train", 0)),
            "cv_validation": int(counts.get("validation", 0)),
            "cv_test": int(counts.get("test", 0)),
        },
        "oof_fold": {"cut_month": str(cut), "fit_months_max": max(fit_months),
                     "n_fit_rows": int(len(early)), "n_late_rows": int(len(late))},
        "counts": {
            "oof_rows_total": int(len(late)),
            "oof_rows_finite": int(finite_late.sum()),
            "validation_rows_total": int(len(validation)),
            "validation_rows_finite": int(finite_val.sum()),
            "pool_n": int(len(pooled_values)),
            "bundle_calibration_n": int(bundle.intervals.calibration_n),
        },
        "quantiles": {
            "recomputed_p05": p05,
            "recomputed_p95": p95,
            "bundle_p05": float(bundle.intervals.residual_p05),
            "bundle_p95": float(bundle.intervals.residual_p95),
            "delta_p05": p05 - float(bundle.intervals.residual_p05),
            "delta_p95": p95 - float(bundle.intervals.residual_p95),
        },
        "selection_replay": {
            "selected_family": selected,
            "primary_metric": spec.primary_metric,
            "replay_primary": float(replay_primary) if replay_primary is not None else None,
            "selection_manifest_value": float(sel_manifest["validation_value"]),
            "match": bool(replay_primary is not None
                          and abs(float(replay_primary) - float(sel_manifest["validation_value"])) < 1e-9),
        },
        "test_replay_max_abs_diff": test_replay_max_abs_diff,
        "oof_residual_max_abs_diff_vs_original_function": oof_max_abs_diff,
        "coverage_recheck": {
            "covered": int(covered.sum()),
            "test_n": int(len(actual_test)),
            "rate": float(np.mean(covered)),
            "run_uncertainty_empirical_coverage_test": uncertainty_run.get("empirical_coverage_test"),
            "match": bool(abs(float(np.mean(covered)) - float(uncertainty_run["empirical_coverage_test"])) < 1e-12),
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }

    tag = f"T+{horizon}" if horizon not in (30,) else f"T+{horizon}"
    stem = f"r2_residual_pool_{task_id}-{variant}_{tag}_mo{offset}"
    pooled_df.to_csv(HERE / f"{stem}.csv", index=False, encoding="utf-8-sig")
    _write_json({
        "schema": SCHEMA,
        "target": {"task_id": task_id, "variant": variant, "horizon_days": horizon,
                   "month_offset": offset, "run_id": bundle.run_id, "model_file": model_file,
                   "model_sha256": model_sha256},
        "reconcile": reconcile,
        "rows": pooled_df.to_dict(orient="records"),
    }, HERE / f"{stem}.json")
    _write_json(reconcile, HERE / f"r2_reconcile_{task_id}-{variant}_{tag}_mo{offset}.json")

    print(json.dumps({"case": f"{task_id}-{variant}-{tag}", "counts": reconcile["counts"],
                      "quantiles": reconcile["quantiles"],
                      "all_checks_pass": reconcile["all_checks_pass"]},
                     ensure_ascii=False, indent=2))
    return reconcile


def main() -> None:
    base, labels = build_supervised_base()
    print(f"[base] rows={len(base)}")
    out = {}
    for task_id, variant, horizon, offset, split_key, run_dir, model_file in CASES:
        key = f"{task_id}-{variant}-T+{horizon}_mo{offset}"
        out[key] = reconstruct(task_id, variant, horizon, offset, split_key, run_dir, model_file, base, labels)
    _write_json(out, HERE / "r2_rebuild_summary.json")
    print("[done] all_checks_pass:", {k: v["all_checks_pass"] for k, v in out.items()})


if __name__ == "__main__":
    main()
