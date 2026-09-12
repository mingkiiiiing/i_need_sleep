# -*- coding: utf-8 -*-
"""用历史代码版本（git 73be6e7）重放，验证能否复现部署模型的 train_features / actual / 预测。"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PKG = BACKEND / "model_runtime_v0_3"
REPLAY = HERE / "_replay_pkg"
sys.path.insert(0, str(PKG / "code"))
sys.path.insert(0, str(REPLAY))
import joblib
warnings.filterwarnings("ignore")
from modeling_real import training_real as TR
print("SELFTEST target_builder module file:", TR.__file__)
from modeling_real.contracts_real import DEFAULT_SEED_V3, SERVING_FEATURE_COLUMNS_V2, TASK_SPECS_REAL
from modeling_real.data_real import RealPreprocessor, StationMonthSource, frame_digest, load_bundle
from modeling_real.target_builder import build_supervised_base, build_supervised_table
from modeling_real.cli_real_cv import CV_BLOCK_TRAIN_FRACTION, CV_BLOCK_VALIDATION_FRACTION

print("replay pkg:", REPLAY)
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
    table = table.copy()
    table["dataset_split_frozen"] = [("train" if m <= train_end else ("validation" if m <= validation_end else "test")) for m in table[split_key]]
    fc = tuple(c for c in SERVING_FEATURE_COLUMNS_V2 if c in table.columns)
    if offset >= 1:
        fc = tuple(dict.fromkeys((*fc, "wq_chla")))
    print("===", run_dir)
    sm = json.loads((PKG / "runs" / run_dir / "selection_manifest.json").read_text(encoding="utf-8"))
    src = StationMonthSource(table, fc)
    train, val, te = src.collect_split("train"), src.collect_split("validation"), src.collect_split("test")
    print("rows", len(train), len(val), len(te))
    pre = RealPreprocessor.fit(train, src.feature_columns)
    tf = pre.transform(train).assign(actual=train["actual"].to_numpy())
    tf["month_order"] = train["month_order"].to_numpy(); tf["month"] = train["month"].to_numpy()
    mine = frame_digest(tf.drop(columns=["month_order"]))
    print("feature_sha256", mine, "MATCH" if mine == sm["feature_sha256"] else "MISMATCH")
    run_te = pd.read_csv(PKG / "runs" / run_dir / "test_predictions.csv")
    print("test actual max abs diff:", float(np.max(np.abs(te["actual"].to_numpy(float) - run_te["actual"].to_numpy(float)))))
    # 全量 actual 对齐（test 行）
    j = pd.DataFrame({"rid": te["row_id"].to_numpy(), "mine": te["actual"].to_numpy(float), "run": run_te["actual"].to_numpy(float)})
    print("n actual mismatch rows (test):", int((np.abs(j["mine"] - j["run"]) > 1e-9).sum()), "/", len(j))
    fac = TR.candidate_factories_real(spec, DEFAULT_SEED_V3, month_offset=offset, climatology_history=None)
    sel = sm["selected_family"]
    vt = pre.transform(val).assign(actual=val["actual"].to_numpy())
    c = fac[sel](tf, vt)
    pv = TR._predict_output(c, vt.loc[:, list(pre.output_columns)], spec)["prediction"].to_numpy(float)
    print("val MAE", float(np.mean(np.abs(val["actual"].to_numpy(float) - pv))), "run", sm["validation_value"])
    pt = TR._predict_output(c, pre.transform(te), spec)["prediction"].to_numpy(float)
    print("test pred max abs diff:", float(np.max(np.abs(pt - run_te["prediction"].to_numpy(float)))))
