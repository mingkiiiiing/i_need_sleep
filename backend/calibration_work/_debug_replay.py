# -*- coding: utf-8 -*-
"""诊断：重放得到的 train_features 是否与原始 run 的 selection_manifest.feature_sha256 一致。"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PKG = BACKEND / "model_runtime_v0_3"
sys.path.insert(0, str(PKG / "code"))
import joblib
warnings.filterwarnings("ignore")
from modeling_real import training_real as TR
from modeling_real.contracts_real import DEFAULT_SEED_V3, SERVING_FEATURE_COLUMNS_V2, TASK_SPECS_REAL
from modeling_real.data_real import RealPreprocessor, StationMonthSource, frame_digest
from modeling_real.target_builder import build_supervised_base, build_supervised_table
from modeling_real.cli_real_cv import CV_BLOCK_TRAIN_FRACTION, CV_BLOCK_VALIDATION_FRACTION

base, labels = build_supervised_base()
spec = next(s for s in TASK_SPECS_REAL if s.task_id == "T5" and s.variant == "chla")
for offset, split_key, run_dir, model_file in [
    (0, "month", "T5-chla-1d-0m-cv", "T5-chla-0m-s20260907-1d.joblib"),
    (3, "target_month", "T5-chla-90d-3m-cv", "T5-chla-3m-s20260907-90d.joblib"),
]:
    table = build_supervised_table(base, labels, spec, offset)
    months = sorted(table[split_key].unique())
    train_end = months[max(int(len(months) * CV_BLOCK_TRAIN_FRACTION) - 1, 0)]
    validation_end = months[max(int(len(months) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)) - 1, 0)]
    def _s(m):
        return "train" if m <= train_end else ("validation" if m <= validation_end else "test")
    table = table.copy()
    table["dataset_split_frozen"] = [_s(m) for m in table[split_key]]
    fc = tuple(c for c in SERVING_FEATURE_COLUMNS_V2 if c in table.columns)
    if offset >= 1:
        fc = tuple(dict.fromkeys((*fc, "wq_chla")))
    print("===", run_dir, "offset", offset, "featcols", fc)
    sm = json.loads((PKG / "runs" / run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    print("run feature_sha256    :", sm["feature_sha256"])
    # 原始实现：StationMonthSource 直接吃带 dataset_split_frozen 的 table
    src = StationMonthSource(table, fc)
    train = src.collect_split("train")
    val = src.collect_split("validation")
    print("train rows", len(train), "val rows", len(val))
    pre = RealPreprocessor.fit(train, src.feature_columns)
    tf = pre.transform(train).assign(actual=train["actual"].to_numpy())
    tf["month_order"] = train["month_order"].to_numpy()
    tf["month"] = train["month"].to_numpy()
    mine = frame_digest(tf.drop(columns=["month_order"]))
    print("replay feature_sha256 :", mine, "MATCH" if mine == sm["feature_sha256"] else "MISMATCH")
    # 也试：不含 month 列
    mine2 = frame_digest(tf.drop(columns=["month_order", "month"]))
    print("replay (drop month)   :", mine2, "MATCH" if mine2 == sm["feature_sha256"] else "MISMATCH")
    # 重放族选择
    fac = TR.candidate_factories_real(spec, DEFAULT_SEED_V3, month_offset=offset, climatology_history=None)
    sel = sm["selected_family"]
    c = fac[sel](tf, pre.transform(val).assign(actual=val["actual"].to_numpy()))
    vt = pre.transform(val).assign(actual=val["actual"].to_numpy())
    pv = TR._predict_output(c, vt.loc[:, list(pre.output_columns)], spec)["prediction"].to_numpy(float)
    mae = float(np.mean(np.abs(val["actual"].to_numpy(float) - pv)))
    print("replay val MAE", mae, "run", sm["validation_value"], "MATCH" if abs(mae - sm["validation_value"]) < 1e-9 else "MISMATCH")
    # 测试重放
    te = src.collect_split("test")
    pt = TR._predict_output(c, pre.transform(te), spec)["prediction"].to_numpy(float)
    run_te = pd.read_csv(PKG / "runs" / run_dir / "test_predictions.csv")
    print("test row_id equal:", (te["row_id"].to_numpy() == run_te["row_id"].to_numpy()).all())
    print("test max abs diff:", float(np.max(np.abs(pt - run_te["prediction"].to_numpy(float)))))
    print("run actual vs mine:", float(np.max(np.abs(te["actual"].to_numpy(float) - run_te["actual"].to_numpy(float)))))
