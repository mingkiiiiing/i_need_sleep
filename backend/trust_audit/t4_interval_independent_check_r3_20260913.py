# -*- coding: utf-8 -*-
"""T4 不确定性/预测区间独立检验（2026-09-13 R5 冻结后审计刷新（r3），只读运行产物，独立复算）。

对应台账：L-vfy-05、看板 T4“区间独立验证：覆盖率、宽度、上下界有效、单类别处理”。

独立口径（不复用官方统计，直接从 runs/test_predictions.csv + bundle.intervals 复算）：
  ① 结构有效：p05/p95 有限值、p05<=p95、物理裁剪后仍不倒置、点值落在区间内；
  ② 覆盖率：按 serving 同款物理裁剪（lower=max(.,0)，bounded 输出 upper=min(.,1)）
     独立复算经验覆盖率，并与 manifest.uncertainty.empirical_coverage_test 对照；
  ③ 宽度分布：min/p25/median/mean/p75/max 与退化（p05==p95）比例；
  ④ 退化/共享标记：同任务族残差池共享（(p05,p95) 恒同值）是否如实（ec37ddf 披露）。

诚实性口径（必须随结果一起读）：
  - 测试段锚点 actual 全部为 manifest.label_provenance 标注的来源（本轮全部 proxy_derived，
    由 CLMS 代理派生——见 L-data-01/04/05）。本报告的“覆盖率”是“对代理标签的覆盖率”，
    不是对实测真值的覆盖率；实测日/旬尺度锚点不足（L-data-08 硬阻断）。

产出：同目录 t4_interval_check_r3_20260913.json。
"""
from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "model_runtime_v0_3"
CODE = PKG / "code"
OUT = Path(__file__).resolve().parent / "t4_interval_check_r3_20260913.json"

warnings.filterwarnings("ignore", message="Setting the shape on a NumPy array has been deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(CODE))
from modeling_real.data_real import load_bundle  # noqa: E402

# serving _build_uncertainty 同款：有界输出集合（backend/app/algorithm_models.py:1441）
BOUNDED_UPPER = {"bloom", "coverage", "density", "probability", "spatial"}
# task/variant → serving output_key（与 v3 空间场/快照同一映射语义）
OUTPUT_KEY = {
    ("T1", "bloom"): "bloom",
    ("T3", "density"): "density",
    ("T4", "biomass"): "biomass",
    ("T5", "chla"): "chla",
    ("T6", "probability"): "probability",
    ("T6", "risk_level"): "risk_level",
}


# runs 目录命名规则（与 modeling_real 一致：目录名含时效与月偏移，manifest.run_id 不含时效）
def run_dir_of(entry: dict) -> Path:
    suffix = "-cv" if entry.get("protocol") == "train_internal_time_block_cv_v1" else ""
    name = f"{entry['task_id']}-{entry['variant']}-{entry['horizon_days']}d-{entry['month_offset']}m{suffix}"
    return PKG / "runs" / name


# 实测锚点来源列（features_base.parquet；其余任务目标无实测来源列=代理契约口径）
ANCHOR_SOURCE_COL = {
    "T5": "target_chla_source",
    "T6": "target_bloom_source",
    "T1": "target_bloom_source",
}


def qstats(values: np.ndarray) -> dict:
    if values.size == 0:
        return {"n": 0}
    return {
        "n": int(values.size),
        "min": float(np.min(values)),
        "p25": float(np.quantile(values, 0.25)),
        "median": float(np.median(values)),
        "mean": float(np.mean(values)),
        "p75": float(np.quantile(values, 0.75)),
        "max": float(np.max(values)),
    }


def main() -> int:
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    csv_sha = {}
    for entry in manifest.get("models", []):
        task, variant = entry.get("task_id"), entry.get("variant")
        output_key = OUTPUT_KEY.get((task, variant), variant)
        row = {
            "artifact_id": entry.get("artifact_id"),
            "task_variant": f"{task}/{variant}",
            "output_key": output_key,
            "protocol": entry.get("protocol"),
            "horizon_days": entry.get("horizon_days"),
            "run_id": entry.get("run_id"),
            "label_provenance": entry.get("label_provenance"),
        }
        # bundle 区间（serving 实际使用的对象）
        bundle = load_bundle(PKG / entry["file"])
        iv = getattr(bundle, "intervals", None)
        if iv is None:
            row["status"] = "no_intervals"
            rows.append(row)
            continue
        r05, r95 = float(iv.residual_p05), float(iv.residual_p95)
        row["residual_p05"] = r05
        row["residual_p95"] = r95
        row["residual_width"] = r95 - r05
        row["calibration_n"] = int(getattr(iv, "calibration_n", 0) or 0)

        # 测试段独立复算（runs 目录名按训练侧命名规则推导，manifest.run_id 无时效后缀）
        run_dir = run_dir_of(entry)
        row["run_dir"] = str(run_dir.relative_to(PKG))
        row["run_dir_exists"] = run_dir.is_dir()
        csv_path = run_dir / "test_predictions.csv"
        if not csv_path.is_file():
            row["status"] = "no_test_predictions"
            rows.append(row)
            continue
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()[:16]
        csv_sha.setdefault(digest, []).append(row["artifact_id"])
        df = pd.read_csv(csv_path)
        pred_col = "probability" if "probability" in df.columns and output_key in BOUNDED_UPPER else "prediction"
        # probability 列只在概率任务存在；chla/biomass 用 prediction
        if pred_col == "probability" and "probability" not in df.columns:
            pred_col = "prediction"
        pred = pd.to_numeric(df[pred_col], errors="coerce").to_numpy(dtype=float)
        actual = pd.to_numeric(df["actual"], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(pred) & np.isfinite(actual)
        row["test_rows"] = int(df.shape[0])
        row["test_rows_with_anchor"] = int(mask.sum())
        row["test_months"] = sorted(map(str, df["month"].dropna().unique().tolist()))
        row["test_window"] = [row["test_months"][0], row["test_months"][-1]] if row["test_months"] else []
        # 锚点来源逐行统计（join features_base.parquet 的实测来源列）
        src_col = ANCHOR_SOURCE_COL.get(task)
        row["anchor_source_semantics"] = "no_ground_truth_source_column(proxy_contract)" if not src_col else None
        if src_col:
            try:
                fb = pd.read_parquet(PKG / "supervised" / "features_base.parquet", columns=["row_id", src_col])
                merged = df[["row_id"]].merge(fb, on="row_id", how="left")
                counts = merged[src_col].value_counts(dropna=False)
                row["anchor_source_counts"] = {str(k): int(v) for k, v in counts.items()}
                row["anchor_source_semantics"] = (
                    "ground_truth_only" if set(counts.index) <= {"zenodo_taihu_insitu", "taihu_water_station_batch"}
                    else "mixed_or_proxy"
                )
            except Exception as exc:  # noqa: BLE001
                row["anchor_source_counts_error"] = repr(exc)
        if mask.sum() == 0:
            row["status"] = "no_valid_anchor"
            rows.append(row)
            continue
        p, a = pred[mask], actual[mask]

        raw_lo, raw_hi = p + r05, p + r95
        lo = np.maximum(raw_lo, 0.0)
        hi = np.minimum(raw_hi, 1.0) if output_key in BOUNDED_UPPER else raw_hi

        cov_raw = float(np.mean((a >= raw_lo - 1e-12) & (a <= raw_hi + 1e-12)))
        cov_serving = float(np.mean((a >= lo - 1e-12) & (a <= hi + 1e-12)))
        width = hi - lo
        degenerate = np.isclose(lo, hi)

        row["status"] = "checked"
        row["structural"] = {
            "raw_p05_le_p95": bool(r05 <= r95),
            "raw_finite": bool(np.isfinite(r05) and np.isfinite(r95)),
            "clipped_p05_le_p95_all_rows": bool(np.all(lo <= hi + 1e-12)),
            "point_in_interval_rate_raw": float(np.mean((a >= raw_lo - 1e-12) & (a <= raw_hi + 1e-12))),
            "point_in_interval_rate_serving": cov_serving,  # 点值与区间同基，serving 口径下=覆盖率
            "upper_clipped_to_1": bool(output_key in BOUNDED_UPPER and np.any(raw_hi > 1.0)),
        }
        row["coverage"] = {
            "empirical_raw_no_clip": round(cov_raw, 4),
            "empirical_serving_clip": round(cov_serving, 4),
            "manifest_declared": entry.get("uncertainty", {}).get("empirical_coverage_test"),
            "manifest_test_n": entry.get("uncertainty", {}).get("test_n"),
            "independent_vs_manifest_diff": (
                round(abs(cov_serving - float(entry["uncertainty"]["empirical_coverage_test"])), 4)
                if isinstance(entry.get("uncertainty", {}).get("empirical_coverage_test"), (int, float))
                else None
            ),
            "anchor_semantics": row.get("anchor_source_semantics") or "unknown",
        }
        row["width"] = {
            "distribution_serving_clip": qstats(width),
            "degenerate_rate": float(np.mean(degenerate)),
            "degenerate_n": int(np.sum(degenerate)),
            "clipped_at_bound_rate": float(
                np.mean(np.isclose(lo, 0.0) | (np.isclose(hi, 1.0) if output_key in BOUNDED_UPPER else False))
            ),
        }
        rows.append(row)

    # ---- 族共享残差池复核（ec37ddf 披露口径；浮点末位噪声按 1e-9 容差归并） ----
    def canon(v: float) -> float:
        return round(v, 9)

    groups: dict[tuple, set] = {}
    for r in rows:
        if "residual_p05" in r:
            key = (r["task_variant"], r["protocol"])
            groups.setdefault(key, set()).add((canon(r["residual_p05"]), canon(r["residual_p95"])))
    sharing = [
        {
            "group": f"{k[0]}:{k[1]}",
            "distinct_intervals": len(v),
            "family_shared": len(v) == 1,
            "intervals": sorted(v),
        }
        for k, v in sorted(groups.items())
    ]

    # ---- 测试段帧复用复核（同 run_id / 同 csv sha） ----
    reuse = [
        {"test_predictions_sha16": k, "artifacts": v, "artifact_count": len(v)}
        for k, v in sorted(csv_sha.items(), key=lambda kv: -len(kv[1]))
        if len(v) > 1
    ]

    summary = {
        "models_total": len(rows),
        "with_intervals": sum(1 for r in rows if r.get("status") == "checked"),
        "no_intervals": [r["artifact_id"] for r in rows if r.get("status") == "no_intervals"],
        "no_valid_anchor": [r["artifact_id"] for r in rows if r.get("status") in ("no_test_predictions", "no_valid_anchor")],
        "structural_violations": [
            r["artifact_id"]
            for r in rows
            if r.get("structural") and (
                not r["structural"]["raw_p05_le_p95"]
                or not r["structural"]["raw_finite"]
                or not r["structural"]["clipped_p05_le_p95_all_rows"]
            )
        ],
        "fully_degenerate_models": [
            r["artifact_id"] for r in rows if r.get("width", {}).get("degenerate_rate", 0) == 1.0
        ],
        "family_shared_groups": sum(1 for s in sharing if s["family_shared"]),
        "coverage_vs_manifest_max_diff": max(
            (r["coverage"]["independent_vs_manifest_diff"] for r in rows if r.get("coverage")),
            default=None,
        ),
        "anchor_note": (
            "锚点构成见各 model 行 anchor_source_counts：实测来源仅 target_chla 42/914 行"
            "（zenodo_taihu_insitu 41 + taihu_water_station_batch 1）；bloom/density/biomass 目标无实测来源列"
            "（代理契约），覆盖率对代理标签部分为参考性指标（L-data-01/04/05/08）"
        ),
    }

    payload = {
        "audit": "T4 区间独立检验",
        "date": "2026-09-13",
        "serving_clip_rule": "lower=max(x,0); upper=min(x,1) for bloom/coverage/density/probability/spatial（同 serving _build_uncertainty）",
        "summary": summary,
        "family_residual_pool_sharing": sharing,
        "test_frame_reuse": reuse,
        "models": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {OUT}")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
