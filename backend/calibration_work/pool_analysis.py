# -*- coding: utf-8 -*-
"""残差池构成分析 + T+90 协议核验 + 覆盖率分口径复算。

读取 K1 已产出的残差池与模型内嵌分位数，输出：
  - OOF / validation 两池各自的 5%/95% 分位数与覆盖测试段覆盖率（用于说明"混合残差池"影响）
  - 测试段逐行覆盖率与审查 evidence.json 80.30%/85.47% 对账
  - T+90 协议窗口核对（CV 三块 vs 冻结段）
只写 backend/calibration_work/pool_analysis.json。
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
AUDIT = BACKEND.parent.parent / "不确定性专项审查_20260912"
sys.path.insert(0, str(PKG / "code"))
import joblib  # noqa: E402

warnings.filterwarnings("ignore")

CASES = [
    ("T+1", 0, 1, "T5-chla-1d-0m-cv", "T5-chla-0m-s20260907-1d.joblib"),
    ("T+90", 3, 90, "T5-chla-90d-3m-cv", "T5-chla-3m-s20260907-90d.joblib"),
]


def main() -> None:
    evidence = json.loads((AUDIT / "evidence.json").read_text(encoding="utf-8"))
    audit = {(r["variant"], r["horizon"]): r for r in evidence["recomputed"]}
    out = {}
    for tag, offset, horizon, run_dir, model_file in CASES:
        df = pd.read_csv(HERE / f"residual_pool_T5-chla_{tag}_mo{offset}.csv")
        bundle = joblib.load(PKG / "models" / model_file)
        test = pd.read_csv(PKG / "runs" / run_dir / "test_predictions.csv")
        pred = test["prediction"].to_numpy(dtype=float)
        actual = test["actual"].to_numpy(dtype=float)

        def cov(lo, hi):
            m = (actual >= pred + lo) & (actual <= pred + hi)
            return int(m.sum()), float(m.mean())

        oof = df[df["source"] == "oof"]["residual"].to_numpy(dtype=float)
        val = df[df["source"] == "validation"]["residual"].to_numpy(dtype=float)
        pooled = np.concatenate([oof, val])
        rec = audit[("chla", horizon)]
        row = {
            "counts": {"oof": int(len(oof)), "validation": int(len(val)), "pool": int(len(pooled)),
                       "bundle_calibration_n": int(bundle.intervals.calibration_n)},
            "quantiles": {
                "pool": [float(np.quantile(pooled, .05)), float(np.quantile(pooled, .95))],
                "oof_only": [float(np.quantile(oof, .05)), float(np.quantile(oof, .95))],
                "validation_only": [float(np.quantile(val, .05)), float(np.quantile(val, .95))],
                "bundle": [float(bundle.intervals.residual_p05), float(bundle.intervals.residual_p95)],
            },
            "residual_stats": {
                "oof": {"mean": float(oof.mean()), "std": float(oof.std(ddof=1)),
                        "min": float(oof.min()), "max": float(oof.max()), "median": float(np.median(oof))},
                "validation": {"mean": float(val.mean()), "std": float(val.std(ddof=1)),
                               "min": float(val.min()), "max": float(val.max()), "median": float(np.median(val))},
            },
            "coverage_test": {
                "pool_quantiles": cov(*np.quantile(pooled, [.05, .95])),
                "oof_only_quantiles": cov(*np.quantile(oof, [.05, .95])),
                "validation_only_quantiles": cov(*np.quantile(val, [.05, .95])),
                "bundle_quantiles": cov(float(bundle.intervals.residual_p05), float(bundle.intervals.residual_p95)),
            },
            "audit_evidence": {"covered": rec["covered"], "n": rec["n"], "coverage": rec["coverage"],
                               "sha256": rec["sha256"]},
            "audit_coverage_match": abs(rec["coverage"] - cov(float(bundle.intervals.residual_p05),
                                                               float(bundle.intervals.residual_p95))[1]) < 1e-12,
            "provenance_counts": df["actual_provenance"].value_counts().to_dict(),
            "month_span": {"oof": [str(df[df.source == "oof"]["month"].min()), str(df[df.source == "oof"]["month"].max())],
                           "validation": [str(df[df.source == "validation"]["month"].min()),
                                          str(df[df.source == "validation"]["month"].max())]},
        }
        # T+90 协议核验：CV 三块 vs 冻结段
        rc = json.loads((PKG / "runs" / run_dir / "run_config.json").read_text(encoding="utf-8"))
        row["protocol"] = {
            "protocol_id": rc.get("protocol"),
            "split_key": rc.get("split_key"),
            "split_block_bounds": rc.get("split_block_bounds"),
            "split_counts_internal": rc.get("split_counts_internal"),
            "cv_test_covered_by_frozen_test": (
                "冻结 test>=2024-01；本 CV 留出测试段为训练期内更早月份（见 split_block_bounds），"
                "故 CV 测试段并非冻结 2024+ 段，二者是不同口径"
            ),
        }
        out[tag] = row
    (HERE / "pool_analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                                             encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
