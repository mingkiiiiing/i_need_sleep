# -*- coding: utf-8 -*-
"""K4 区间覆盖率独立复算工具（2026-09-12，只读模型文件 + 测试预测产物）。

对应台账：区间校准专项台账_20260912.md A 组（L-cal-01..06，六组覆盖率）。
对应看板：K4「审查证据固化与覆盖率复算工具」。

口径（与审查 audit.py / serving `_build_uncertainty` 一致）：
  1. 从部署模型文件（joblib bundle）读取**内嵌残差分位数** residual_p05 / residual_p95，
     不重新训练、不重新拟合；
  2. 从同一次训练的测试预测产物 `runs/<run_dir>/test_predictions.csv` 读取逐行
     prediction / actual；
  3. 区间 = prediction + residual 分位数；按 serving 物理裁剪（下界 max(.,0)，
     density 等有界输出上界 min(.,1)）独立复算经验覆盖率；
  4. 与审查证据 `不确定性专项审查_20260912/evidence.json` 的 reconputed 六组逐项对账
     （覆盖率、覆盖数、样本数、模型 sha256、残差分位数）。

诚实性口径（必须随结果一起读）：
  - 覆盖率是在**训练期内留出测试块**上核算的，不是 2024+ 冻结段独立样本；
  - T+1/T+90 校准段标签主要为代理（chla_station_proxy_v1），叶绿素 T+1 混合、T+90 全代理，
    密度/生物量为代理契约口径——即"对代理标签的覆盖率"，非实测真值覆盖率。

K1 已确立训练代码版本漂移（工作区现码 != 部署模型同代）：本工具**只用只读模型文件 +
测试预测产物**，不 import 训练代码、不重放、不重训，因此不受版本漂移影响。

用法（backend 目录下，一条命令）：
    .venv/Scripts/python.exe trust_audit/interval_coverage_recheck.py
产出：同目录 interval_coverage_recheck_20260912.json（stdout 同时打印结果表）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent          # backend/trust_audit
BACKEND = HERE.parent                            # backend
DEV = BACKEND.parent                             # 01_我们的开发
SUMMARY_ROOT = DEV.parent                        # 项目完整汇总_2026-08-31
PKG = BACKEND / "model_runtime_v0_3"
AUDIT_DIR = SUMMARY_ROOT / "不确定性专项审查_20260912"
EVIDENCE = AUDIT_DIR / "evidence.json"
SOURCES = AUDIT_DIR / "sources.json"
RUN_MAP = PKG / "code" / "interval_audit" / "artifact_run_map.csv"
DEFAULT_OUT = HERE / "interval_coverage_recheck_20260912.json"

# 模型反序列化需要 modeling_real 包可见（与审查 audit.py 同款），只读引用、不执行训练逻辑。
sys.path.insert(0, str(PKG / "code"))

EPS = 1e-12

# 六组独立复算目标（与台账 A 组 / sources.json 一致）。artifact_id 供与映射表交叉核对。
CASES = [
    dict(metric="chla", label="叶绿素a", horizon=1,
         run_dir="T5-chla-1d-0m-cv", model_file="models/T5-chla-0m-s20260907-1d.joblib",
         artifact_id="T5:chla:train_internal_time_block_cv_v1:off0:h1:s20260907",
         expected_covered=106, expected_n=132, expected_coverage=0.803030303030303,
         serving_upper_clip=False),
    dict(metric="chla", label="叶绿素a", horizon=90,
         run_dir="T5-chla-90d-3m-cv", model_file="models/T5-chla-3m-s20260907-90d.joblib",
         artifact_id="T5:chla:train_internal_time_block_cv_v1:off3:h90:s20260907",
         expected_covered=100, expected_n=117, expected_coverage=0.8547008547008547,
         serving_upper_clip=False),
    dict(metric="density", label="密度代理", horizon=1,
         run_dir="T3-density-1d-0m-cv", model_file="models/T3-density-0m-s20260907-1d.joblib",
         artifact_id="T3:density:train_internal_time_block_cv_v1:off0:h1:s20260907",
         expected_covered=90, expected_n=117, expected_coverage=0.7692307692307693,
         serving_upper_clip=True),
    dict(metric="density", label="密度代理", horizon=90,
         run_dir="T3-density-90d-3m-cv", model_file="models/T3-density-3m-s20260907-90d.joblib",
         artifact_id="T3:density:train_internal_time_block_cv_v1:off3:h90:s20260907",
         expected_covered=93, expected_n=117, expected_coverage=0.7948717948717948,
         serving_upper_clip=True),
    dict(metric="biomass", label="生物量", horizon=1,
         run_dir="T4-biomass-1d-0m-cv", model_file="models/T4-biomass-0m-s20260907-1d.joblib",
         artifact_id="T4:biomass:train_internal_time_block_cv_v1:off0:h1:s20260907",
         expected_covered=87, expected_n=117, expected_coverage=0.7435897435897436,
         serving_upper_clip=False),
    dict(metric="biomass", label="生物量", horizon=90,
         run_dir="T4-biomass-90d-3m-cv", model_file="models/T4-biomass-3m-s20260907-90d.joblib",
         artifact_id="T4:biomass:train_internal_time_block_cv_v1:off3:h90:s20260907",
         expected_covered=95, expected_n=117, expected_coverage=0.811965811965812,
         serving_upper_clip=False),
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_evidence() -> dict:
    """读取审查 evidence.json reconputed 段，按 (variant, horizon) 建索引。"""
    if not EVIDENCE.is_file():
        return {}
    try:
        payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": repr(exc)}
    out = {}
    for item in payload.get("recomputed", []):
        out[(item.get("variant"), int(item.get("horizon")))] = item
    return out


def load_run_map() -> dict:
    """读取 artifact_run_map.csv，按 artifact_id 建索引（交叉核对 model_file / run_dir）。"""
    if not RUN_MAP.is_file():
        return {}
    with RUN_MAP.open(encoding="utf-8-sig", newline="") as f:
        return {row["artifact_id"]: row for row in csv.DictReader(f)}


def load_bundle_intervals(model_path: Path) -> tuple[float, float, int, dict, str]:
    """只读加载 joblib bundle，取出内嵌残差分位数与 uncertainty_meta。不重训。"""
    import joblib

    bundle = joblib.load(model_path)
    iv = getattr(bundle, "intervals", None)
    if iv is None:
        raise ValueError("bundle 无 intervals 属性")
    lo = float(iv.residual_p05)
    hi = float(iv.residual_p95)
    cal_n = int(getattr(iv, "calibration_n", 0) or 0)
    meta = dict(getattr(bundle, "uncertainty_meta", {}) or {})
    return lo, hi, cal_n, meta, type(bundle).__name__


def recompute_case(case: dict, evidence: dict, run_map: dict) -> dict:
    metric, horizon = case["metric"], case["horizon"]
    model_path = PKG / case["model_file"]
    csv_path = PKG / "runs" / case["run_dir"] / "test_predictions.csv"

    rec = {
        "metric": metric,
        "label": case["label"],
        "horizon_days": horizon,
        "artifact_id": case["artifact_id"],
        "run_dir": case["run_dir"],
        "model_file": case["model_file"],
        "expected_coverage": case["expected_coverage"],
        "expected_covered": case["expected_covered"],
        "expected_n": case["expected_n"],
        "gaps": [],
    }

    # 产物存在性（缺失如实记录，不静默跳过）
    if not model_path.is_file():
        rec["gaps"].append(f"模型文件缺失: {model_path}")
    if not csv_path.is_file():
        rec["gaps"].append(f"测试预测缺失: {csv_path}")
    if rec["gaps"]:
        rec["status"] = "gap"
        return rec

    # 映射表交叉核对
    mrow = run_map.get(case["artifact_id"])
    if mrow is None:
        rec["gaps"].append("artifact_run_map.csv 无此 artifact_id")
    else:
        if mrow.get("model_file") != case["model_file"]:
            rec["gaps"].append(
                f"映射表 model_file 不一致: {mrow.get('model_file')} != {case['model_file']}")
        if mrow.get("run_dir") != case["run_dir"]:
            rec["gaps"].append(
                f"映射表 run_dir 不一致: {mrow.get('run_dir')} != {case['run_dir']}")

    lo, hi, cal_n, meta, bundle_type = load_bundle_intervals(model_path)
    model_sha = sha256_file(model_path)
    csv_sha = sha256_file(csv_path)

    rec.update({
        "status": "checked",
        "residual_p05": lo,
        "residual_p95": hi,
        "residual_width": hi - lo,
        "calibration_n": cal_n,
        "bundle_type": bundle_type,
        "uncertainty_meta_empirical_coverage_test": meta.get("empirical_coverage_test"),
        "uncertainty_meta_test_n": meta.get("test_n"),
        "uncertainty_meta_calibration_source": meta.get("calibration_source"),
        "label_provenance": (
            meta.get("label_provenance")
            or (mrow.get("label_provenance") if mrow else None)),
        "label_provenance_source": (
            "uncertainty_meta" if meta.get("label_provenance")
            else ("artifact_run_map" if mrow else None)),
        "model_sha256": model_sha,
        "test_predictions_sha256": csv_sha,
    })

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    n = len(rows)

    covered_raw = covered_clip = 0
    per_row = []
    for r in rows:
        pred = float(r["prediction"])
        actual = float(r["actual"])
        raw_lo, raw_hi = pred + lo, pred + hi
        lo_c = max(raw_lo, 0.0)
        hi_c = min(raw_hi, 1.0) if case["serving_upper_clip"] else raw_hi
        in_raw = (actual >= raw_lo - EPS) and (actual <= raw_hi + EPS)
        in_clip = (actual >= lo_c - EPS) and (actual <= hi_c + EPS)
        covered_raw += int(in_raw)
        covered_clip += int(in_clip)
        per_row.append({
            "sample_id": r.get("row_id"),
            "month": r.get("month"),
            "prediction": pred,
            "actual": actual,
            "residual": actual - pred,
            "lower_raw": raw_lo,
            "upper_raw": raw_hi,
            "lower_serving": lo_c,
            "upper_serving": hi_c,
            "covered_raw": bool(in_raw),
            "covered_serving": bool(in_clip),
        })

    cov_raw = covered_raw / n if n else float("nan")
    cov_clip = covered_clip / n if n else float("nan")

    # 备选：若测试表含 probability 列，额外按 probability 复算（口径差异探测，非主口径）
    cov_prob = None
    if rows and "probability" in rows[0]:
        cp = 0
        for r in rows:
            p = float(r["probability"])
            lo_c = max(p + lo, 0.0)
            hi_c = min(p + hi, 1.0) if case["serving_upper_clip"] else p + hi
            cp += int((float(r["actual"]) >= lo_c - EPS) and (float(r["actual"]) <= hi_c + EPS))
        cov_prob = cp / n

    rec.update({
        "n_test": n,
        "covered_raw": covered_raw,
        "covered_serving_clipped": covered_clip,
        "coverage_raw": cov_raw,
        "coverage_serving_clipped": cov_clip,
        "coverage_probability_col": cov_prob,
        "coverage_raw_pct": round(cov_raw * 100, 2),
        "rows": per_row,
    })

    # 与审查 evidence.json 对账
    ev = evidence.get((metric, horizon))
    recon = {"evidence_found": ev is not None}
    if ev:
        recon.update({
            "audit_covered": ev.get("covered"),
            "audit_n": ev.get("n"),
            "audit_coverage": ev.get("coverage"),
            "audit_serving_clipped_coverage": ev.get("serving_clipped_coverage"),
            "audit_residual_p05": ev.get("residual_p05"),
            "audit_residual_p95": ev.get("residual_p95"),
            "audit_sha256": ev.get("sha256"),
            "covered_match": ev.get("covered") == covered_raw,
            "n_match": ev.get("n") == n,
            "coverage_match": abs(float(ev.get("coverage")) - cov_raw) < 1e-12,
            "serving_clipped_match": (
                abs(float(ev.get("serving_clipped_coverage")) - cov_clip) < 1e-12),
            "p05_match": abs(float(ev.get("residual_p05")) - lo) < 1e-12,
            "p95_match": abs(float(ev.get("residual_p95")) - hi) < 1e-12,
            "sha256_match": ev.get("sha256") == model_sha,
        })
        recon["all_match"] = all(recon[k] for k in (
            "covered_match", "n_match", "coverage_match",
            "serving_clipped_match", "p05_match", "p95_match", "sha256_match"))
    rec["reconciliation"] = recon

    # 自身记录（模型内嵌 uncertainty_meta 的 coverage）对账
    rec["bundle_meta_coverage_match"] = (
        meta.get("empirical_coverage_test") is not None
        and abs(float(meta["empirical_coverage_test"]) - cov_raw) < 1e-12)
    return rec


def main() -> int:
    import numpy
    import pandas
    import sklearn

    ap = argparse.ArgumentParser(description="K4 六组区间覆盖率独立复算（只读，不重训）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 JSON 路径")
    args = ap.parse_args()

    evidence = load_evidence()
    run_map = load_run_map()

    cases = [recompute_case(c, evidence, run_map) for c in CASES]

    checked = [c for c in cases if c.get("status") == "checked"]
    gaps = []
    for c in cases:
        for g in c.get("gaps", []):
            gaps.append({"case": f"{c['metric']}T+{c['horizon_days']}", "gap": g})
        if c.get("status") == "gap":
            gaps.append({"case": f"{c['metric']}T+{c['horizon_days']}",
                         "gap": "无法复算（见上）"})

    mismatches = [
        f"{c['metric']}T+{c['horizon_days']} (复算 {c.get('coverage_raw_pct')}% vs 审查 "
        f"{round(c['expected_coverage']*100,2)}%)"
        for c in cases
        if c.get("status") == "checked" and not c["reconciliation"].get("all_match")
    ]

    payload = {
        "audit": "K4 区间覆盖率独立复算",
        "date": "2026-09-12",
        "tool": "backend/trust_audit/interval_coverage_recheck.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": (
            "只读 joblib bundle 的内嵌 residual_p05/p95 + runs/*/test_predictions.csv 逐行预测，"
            "按 serving 物理裁剪（下界 max(.,0)，density 上界 min(.,1)）独立复算经验覆盖率；"
            "不 import 训练代码、不重放、不重训，规避 K1 记录的训练代码版本漂移。"),
        "serving_clip_rule": "lower=max(x+resid_p05,0); upper=min(x+resid_p95,1) 仅对 density",
        "source_evidence": str(EVIDENCE),
        "sources_json": str(SOURCES) if SOURCES.is_file() else None,
        "artifact_run_map": str(RUN_MAP) if RUN_MAP.is_file() else None,
        "environment": {
            "python": sys.version.split()[0],
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "summary": {
            "cases_total": len(cases),
            "cases_checked": len(checked),
            "all_reconcile_pass": not mismatches and not gaps,
            "mismatches": mismatches,
            "gaps_count": len(gaps),
        },
        "cases": cases,
        "gaps": gaps,
        "notes": [
            "覆盖率测试段为训练期内留出块，非 2024+ 冻结段独立样本。",
            "chla T+1 校准段标签混合、T+90 全代理；density/biomass 为代理契约口径。",
            "coverage_probability_col 仅在测试表含 probability 列时给出，用于探测 prediction/probability 口径差异。",
        ],
    }

    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- stdout 结果表 ----
    print("=" * 78)
    print("K4 六组区间覆盖率独立复算（只读模型文件 + 测试预测，不重训）")
    print("=" * 78)
    print(f"{'组':<14}{'覆盖/测试':>12}{'复算覆盖率':>12}{'审查覆盖率':>12}{'对账':>8}")
    print("-" * 78)
    for c in cases:
        if c.get("status") != "checked":
            print(f"{c['label']+' T+'+str(c['horizon_days']):<14}{'--':>12}{'--':>12}"
                  f"{round(c['expected_coverage']*100,2):>11}%{'GAP':>8}")
            continue
        name = f"{c['label']} T+{c['horizon_days']}"
        frac = f"{c['covered_raw']}/{c['n_test']}"
        cov = f"{c['coverage_raw_pct']:.2f}%"
        exp = f"{c['expected_coverage']*100:.2f}%"
        ok = "OK" if c["reconciliation"].get("all_match") else "DIFF"
        print(f"{name:<14}{frac:>12}{cov:>12}{exp:>12}{ok:>8}")
    print("-" * 78)
    if mismatches:
        print("不一致：")
        for m in mismatches:
            print("  - " + m)
    if gaps:
        print("缺口：")
        for g in gaps:
            print("  - " + g["case"] + ": " + g["gap"])
    if not mismatches and not gaps:
        print("六组复算与审查 evidence.json 完全一致（覆盖率/覆盖数/样本数/分位数/模型 sha256）。")
    print(f"\n输出: {out}")

    # 退出码：全一致 0；有不一致或缺口 2（便于自动化判读）
    return 0 if not mismatches and not gaps else 2


if __name__ == "__main__":
    raise SystemExit(main())
