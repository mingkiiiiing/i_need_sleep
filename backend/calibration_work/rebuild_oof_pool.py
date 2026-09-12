# -*- coding: utf-8 -*-
"""K1 主线：按原训练折重建 T5-chla 的 OOF + validation 残差池，并与模型内嵌分位数五重对账。

方法（只读复用训练代码，不修改任何训练/模型文件）：
  直接 import backend/model_runtime_v0_3/code/modeling_real 下的真实实现：
    - target_builder.build_supervised_base / build_supervised_table（监督表）
    - data_real.StationMonthSource / RealPreprocessor（切分与预处理器）
    - training_real.candidate_factories_real / _predict_output / _fit_oof_residuals（候选族与 OOF 折）
    - cli_real_cv.CV_BLOCK_* / _climatology_history（训练期内时间分块协议）
  按 cli_real_cv._train_cv_run 的三块切分（60/20/20，按 month 或 target_month 时间序）
  重现 train/validation/test，然后用 train_run_real 完全相同的调用序列重放：
    train_features = preprocessor.transform(train).assign(actual=...)  [train_run_real:856-865]
    selected 族 = bundle.selected_family（并用 selection_manifest 的 validation MAE 复核）
    OOF 残差 = training_real._fit_oof_residuals(train_features, ...)   [training_real:925-927]
    validation 残差 = val_actual - selected_validation_pred            [training_real:913-924]
    pooled = concat([oof, validation])；P05/P95 = np.quantile(pooled,[.05,.95])  [training_real:928-936]

自证「没有让最终模型预测它训练过的样本冒充 OOF」：
  逐行标记 fold_id / source，且：
    - OOF 行的 month 全部 >= cut，early（拟合块）行的 month 全部 < cut；两集合 row_id 无交；
    - OOF 行的预测来自 early-only 折模型（factories[selected](early, None)），
      断言该模型训练用 row_id 集合与 OOF 行 row_id 集合交集为空；
    - 逐行残差向量必须与 training_real._fit_oof_residuals 的原函数返回值逐位一致；
    - OOF 行全部落在 cv_train 内，validation 行恰好等于 cv_validation，二者均不含 cv_test 行。

输出（只写 backend/calibration_work/）：
  residual_pool_T5-chla_T+1_mo0.csv / .json
  residual_pool_T5-chla_T+90_mo3.csv / .json
  residual_pool_schema.json
  reconcile_T5-chla_T+1_mo0.json
  reconcile_T5-chla_T+90_mo3.json
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
# 关键：部署模型训练于 2026-09-11，当时 target_builder 尚未包含 2026-09-12 才加入的
# chla 双单位归一（_normalize_chla_units，commit d92c421）。用工作区当前代码重放会得到
# 与模型记录不同的标签/预测（实测 test actual 全部 132 行不一致）。因此重放必须使用
# 训练当时的代码快照：git 73be6e7（2026-09-11 23:37，模型建立于 09-11 13:31-13:32）。
# 该快照由 scripts/export_replay_package.py 导出至 _replay_pkg/，只读使用不修改。
REPLAY_PKG = HERE / "_replay_pkg"
sys.path.insert(0, str(PKG / "code"))
sys.path.insert(0, str(REPLAY_PKG))

import joblib  # noqa: E402

warnings.filterwarnings("ignore")

from modeling_real import training_real as TR  # noqa: E402
from modeling_real.contracts_real import (  # noqa: E402
    DEFAULT_SEED_V3,
    SERVING_FEATURE_COLUMNS_V2,
    SERVING_LAGGED_TARGET_FEATURES,
    TASK_SPECS_REAL,
)
from modeling_real.data_real import RealPreprocessor, StationMonthSource, frame_digest  # noqa: E402
from modeling_real.target_builder import (  # noqa: E402
    build_supervised_base,
    build_supervised_table,
)
from modeling_real.cli_real_cv import (  # noqa: E402
    CV_BLOCK_TRAIN_FRACTION,
    CV_BLOCK_VALIDATION_FRACTION,
    _climatology_history,
)

SEED = DEFAULT_SEED_V3
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
        "prediction": "预测值（OOF=early-only 折模型对 late 的预测；validation=装配模型对校准确块的预测）",
        "actual": "实际标签值",
        "residual": "actual - prediction",
        "actual_provenance": "逐行标签来源（ground_truth | chla_station_proxy_v1）",
        "model_sha256": "对应交付模型文件 sha256（身份锚点）",
        "run_id": "run 标识",
        "protocol": "评估协议",
        "in_fit_months": "OOF 行是否落在折模型拟合月范围内（必须为 False 才是真 OOF）",
        "fit_month_max": "折模型拟合块的最大月",
        "predict_month_min": "被预测块的最小月",
        "predictor_row_id_span": "折模型拟合行 row_id 数量（用于核对未见样本）",
    },
    "note": "OOF 与 validation 逐行分文件保存，source 列区分；pooled 分位数按 OOF 在前、validation 在后拼接。",
}


def _write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def cv_split(table: pd.DataFrame, split_key: str) -> pd.DataFrame:
    """复刻 cli_real_cv._train_cv_run 的时间三块切分（60/20/20）。"""
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


def reconstruct(horizon: int, offset: int, split_key: str, run_dir: str, model_file: str,
                base: pd.DataFrame, labels: pd.DataFrame, bundle) -> dict:
    spec = next(s for s in TASK_SPECS_REAL if s.task_id == "T5" and s.variant == "chla")
    table = build_supervised_table(base, labels, spec, offset)
    table, train_end, validation_end, test_start = cv_split(table, split_key)
    counts = table["dataset_split_frozen"].value_counts().to_dict()

    feature_columns = tuple(c for c in SERVING_FEATURE_COLUMNS_V2 if c in table.columns)
    if offset >= 1:
        extra = SERVING_LAGGED_TARGET_FEATURES.get(spec.label_family, ())
        feature_columns = tuple(dict.fromkeys((*feature_columns, *(c for c in extra if c in table.columns))))

    history = None
    if offset >= 1:
        history_table = build_supervised_table(base, labels, spec, 0)
        history = _climatology_history(history_table, test_start, feature_columns)

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

    factories = TR.candidate_factories_real(
        spec, SEED, month_offset=offset, climatology_history=history,
    )
    selected = bundle.selected_family

    # 复核族选择：用同一 factory 在 validation 上的 MAE 对齐 selection_manifest
    cand_full = factories[selected](tf, vf)
    pred_vf = TR._predict_output(cand_full, vf.loc[:, list(pre.output_columns)], spec)
    mae_replay = float(np.mean(np.abs(
        pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
        - pred_vf["prediction"].to_numpy(dtype=float)
    )))

    # 重放保真锚：重放的 train_features 指纹必须等于原 run 的 selection_manifest.feature_sha256。
    # 这是"重放管线 == 原始训练管线"的机器可验证证据；不等则拒绝出产物。
    sel_manifest = json.loads((PKG / "runs" / run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    replay_digest = frame_digest(tf.drop(columns=["month_order"]))
    digest_match = replay_digest == sel_manifest["feature_sha256"]

    # ---- 测试段复放（验证重放管线与原始 run 等价）----
    test_features = pre.transform(test)
    pred_test = TR._predict_output(cand_full, test_features, spec)
    run_test = pd.read_csv(PKG / "runs" / run_dir / "test_predictions.csv")
    test_replay_max_abs_diff = float(np.max(np.abs(
        pred_test["prediction"].to_numpy(dtype=float) - run_test["prediction"].to_numpy(dtype=float)
    )))

    # ---- OOF 残差：调用原函数 + 逐行重建（两者必须逐位一致）----
    oof_vec = TR._fit_oof_residuals(tf, source, spec, selected, factories, pre, SEED)
    months_t = np.sort(tf["month"].unique())
    cut = months_t[max(2, int(len(months_t) * 0.7))]
    early_mask = tf["month"] < cut
    early, late = tf[early_mask], tf[~early_mask]
    fit_months = sorted(early["month"].unique())
    cand_oof = factories[selected](early, None)
    pred_late = TR._predict_output(cand_oof, late.loc[:, list(pre.output_columns)], spec)
    pv_late = pred_late["prediction"].to_numpy(dtype=float)
    av_late = pd.to_numeric(late["actual"], errors="coerce").to_numpy()
    res_late = av_late - pv_late
    finite_late = np.isfinite(res_late)

    def _pos_to_ids(frame: pd.DataFrame) -> pd.DataFrame:
        rows = frame.loc[:, ["row_id"]].copy()
        rows["station_id"] = frame["station_id"].to_numpy()
        rows["month"] = frame["month"].to_numpy()
        rows["target_month"] = frame["target_month"].to_numpy()
        rows["actual_provenance"] = frame["actual_provenance"].to_numpy()
        return rows

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
    oof_df["model_sha256"] = hashlib.sha256((PKG / "models" / model_file).read_bytes()).hexdigest()
    oof_df["run_id"] = bundle.run_id
    oof_df["protocol"] = "train_internal_time_block_cv_v1"

    # ---- validation 残差 ----
    val_pos = _pos_to_ids(validation)
    pv_val = pred_vf["prediction"].to_numpy(dtype=float)
    av_val = pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
    res_val = av_val - pv_val
    finite_val = np.isfinite(res_val)
    val_df = pd.DataFrame({
        "row_id": val_pos["row_id"].to_numpy()[finite_val],
        "station_id": val_pos["station_id"].to_numpy()[finite_val],
        "month": val_pos["month"].to_numpy()[finite_val],
        "target_month": val_pos["target_month"].to_numpy()[finite_val],
        "actual_provenance": val_pos["actual_provenance"].to_numpy()[finite_val],
        "prediction": pv_val[finite_val],
        "actual": av_val[finite_val],
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
    val_df["model_sha256"] = oof_df["model_sha256"].iloc[0]
    val_df["run_id"] = bundle.run_id
    val_df["protocol"] = "train_internal_time_block_cv_v1"

    pool_cols = list(oof_df.columns)
    pooled_df = pd.concat([oof_df[pool_cols], val_df[pool_cols]], ignore_index=True)
    pooled_values = np.concatenate([oof_df["residual"].to_numpy(), val_df["residual"].to_numpy()])
    p05 = float(np.quantile(pooled_values, 0.05))
    p95 = float(np.quantile(pooled_values, 0.95))

    # 自证 ----
    oof_max_abs_diff = (
        float(np.max(np.abs(oof_vec - res_late[finite_late])))
        if len(oof_vec) == int(finite_late.sum()) and len(oof_vec) else float("inf")
    )
    oof_ids = set(oof_df["row_id"].tolist())
    val_ids = set(val_df["row_id"].tolist())
    train_ids = set(train["row_id"].tolist())
    val_split_ids = set(validation["row_id"].tolist())
    test_ids = set(test["row_id"].tolist())
    checks = {
        "replay_package_feature_digest_matches_run": bool(digest_match),
        # 注意：RF/HistGB 在 n_jobs=4 下重复拟合存在 ~1e-14 级浮点差异（非结合求和），
        # 逐位相等不可达；以 1e-9 容差判定，另记录实测最大差。两次调用原函数的实测差
        # 同为 ~7e-15，证明该差异来自拟合本身而非本重建脚本。
        "oof_residual_vector_matches_within_tol": bool(oof_max_abs_diff < 1e-9),
        "oof_ids_disjoint_from_validation_ids": len(oof_ids & val_ids) == 0,
        "oof_ids_subset_of_cv_train": oof_ids <= train_ids,
        "validation_ids_equals_cv_validation": val_ids == val_split_ids,
        "pool_ids_disjoint_from_cv_test": len((oof_ids | val_ids) & test_ids) == 0,
        "oof_rows_all_in_late_block": bool((late_ids["month"].to_numpy()[finite_late] >= cut).all()),
        "early_months_all_before_cut": bool((early["month"] < cut).all()),
        "early_and_late_no_row_overlap": len(set(_tf_meta(early)["row_id"]) & set(late_ids["row_id"])) == 0,
        "fold_boundary_strictly_increasing_time": bool(max(fit_months) < min(late["month"].unique())),
        "preprocessor_medians_match_bundle": bool(
            all(abs(pre.medians[k] - bundle.preprocessor.medians[k]) < 1e-12 for k in pre.medians)
        ),
        "prediction_frame_replay_matches_run_test_predictions": bool(test_replay_max_abs_diff < 1e-9),
        "pool_n_equals_bundle_calibration_n": int(len(pooled_values)) == int(bundle.intervals.calibration_n),
        "p05_equals_bundle": bool(abs(p05 - float(bundle.intervals.residual_p05)) < 1e-12),
        "p95_equals_bundle": bool(abs(p95 - float(bundle.intervals.residual_p95)) < 1e-12),
    }
    reconcile = {
        "model_file": model_file,
        "run_dir": run_dir,
        "horizon_days": horizon,
        "month_offset": offset,
        "split_key": split_key,
        "protocol": "train_internal_time_block_cv_v1",
        "replay_package": {
            "path": str(REPLAY_PKG),
            "source_commit": "73be6e7 (2026-09-11 23:37:57 +0800)",
            "reason": "部署模型训练于 2026-09-11 13:31-13:32；工作区 HEAD 的 target_builder 含 09-12 新增 chla 单位归一，与训练时不同",
            "replay_feature_digest": replay_digest,
            "run_feature_sha256": sel_manifest["feature_sha256"],
            "digest_match": bool(digest_match),
        },
        "split_block_bounds_recomputed": {
            "train_max_month": train_end,
            "validation_max_month": validation_end,
            "test_min_month": test_start,
        },
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
            "replay_validation_mae": mae_replay,
            "selection_manifest_validation_mae": bundle.validation_value,
            "mae_match": bool(abs(mae_replay - float(bundle.validation_value)) < 1e-9),
        },
        "test_replay_max_abs_diff": test_replay_max_abs_diff,
        "oof_residual_max_abs_diff_vs_original_function": oof_max_abs_diff,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }

    tag = f"T+{horizon}" if horizon != 90 else "T+90"
    stem = f"residual_pool_T5-chla_{tag}_mo{offset}"
    pooled_df.to_csv(HERE / f"{stem}.csv", index=False, encoding="utf-8-sig")
    _write_json({
        "schema": SCHEMA,
        "target": {"task_id": "T5", "variant": "chla", "horizon_days": horizon,
                   "month_offset": offset, "run_id": bundle.run_id, "model_file": model_file},
        "reconcile": reconcile,
        "rows": pooled_df.to_dict(orient="records"),
    }, HERE / f"{stem}.json")
    _write_json(reconcile, HERE / f"reconcile_T5-chla_{tag}_mo{offset}.json")

    print(json.dumps({"tag": tag, "counts": reconcile["counts"],
                      "quantiles": reconcile["quantiles"],
                      "checks": checks, "all_checks_pass": reconcile["all_checks_pass"]},
                     ensure_ascii=False, indent=2))
    return reconcile


def main() -> None:
    _write_json(SCHEMA, HERE / "residual_pool_schema.json")
    base, labels = build_supervised_base()
    print(f"[base] rows={len(base)}")
    out = {}
    bundle1 = joblib.load(PKG / "models" / "T5-chla-0m-s20260907-1d.joblib")
    out["t1"] = reconstruct(1, 0, "month", "T5-chla-1d-0m-cv",
                            "T5-chla-0m-s20260907-1d.joblib", base, labels, bundle1)
    bundle90 = joblib.load(PKG / "models" / "T5-chla-3m-s20260907-90d.joblib")
    out["t90"] = reconstruct(90, 3, "target_month", "T5-chla-90d-3m-cv",
                             "T5-chla-3m-s20260907-90d.joblib", base, labels, bundle90)
    _write_json({k: v for k, v in out.items()}, HERE / "rebuild_summary.json")
    print("[done] all_checks_pass:", {k: v["all_checks_pass"] for k, v in out.items()})


if __name__ == "__main__":
    main()
