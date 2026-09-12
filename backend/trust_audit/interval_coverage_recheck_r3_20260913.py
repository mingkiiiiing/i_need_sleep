# -*- coding: utf-8 -*-
"""K4 区间覆盖率独立复算工具（R5 冻结后审计刷新 r3 版，2026-09-13）。

背景：全量冻结重跑（e698d0a）后 34 个 joblib 全部重训、manifest 刷新，
六组覆盖率必然与 2026-09-12 审查 evidence.json 的旧数字不同（模型重训）。
本 r3 版由 interval_coverage_recheck.py 复制改造（原脚本保留不动）：
  1. 复算口径与原版完全一致（只读 bundle 内嵌 residual_p05/p95 + runs/*/test_predictions.csv，
     serving 物理裁剪；不重训、不重放）；
  2. 与旧审查 evidence.json 的对账字段**原样保留**——差异如实列出（预期漂移，非失败）；
  3. 新增新包**内部自洽**判据（r3 的真正 pass/fail 依据）：
       a) bundle 内嵌 uncertainty_meta.empirical_coverage_test == 复算值；
       b) manifest 条目 uncertainty.empirical_coverage_test == 复算值；
       c) manifest 条目 sha256 == 模型文件 sha256；
       d) 残差分位数有限且 p05<=p95。

用法（backend 目录下）：
    .venv/Scripts/python.exe trust_audit/interval_coverage_recheck_r3_20260913.py
产出：同目录 interval_coverage_recheck_r3_20260913.json。
退出码：0 = 六组新包自洽全部通过；2 = 存在缺口或自洽失败（旧 evidence 漂移不算失败）。
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
MANIFEST = PKG / "manifest.json"
DEFAULT_OUT = HERE / "interval_coverage_recheck_r3_20260913.json"

sys.path.insert(0, str(PKG / "code"))

EPS = 1e-12

# 六组目标：run_dir / model_file 与旧版一致（文件名未变、内容已重训）。
# expected_* 为 2026-09-12 审查 evidence.json 的旧数字，仅作新旧对照，不再作 pass/fail 依据。
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


def load_manifest_entries() -> dict:
    """新 manifest 按 artifact_id 建索引。"""
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": repr(exc)}
    return {e.get("artifact_id"): e for e in m.get("models", [])}


def load_evidence() -> dict:
    """旧审查 evidence.json reconputed 段（只读对照用）。"""
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
    if not RUN_MAP.is_file():
        return {}
    with RUN_MAP.open(encoding="utf-8-sig", newline="") as f:
        return {row["artifact_id"]: row for row in csv.DictReader(f)}


def load_bundle_intervals(model_path: Path) -> tuple[float, float, int, dict, str]:
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


def recompute_case(case: dict, evidence: dict, run_map: dict, manifest_entries: dict) -> dict:
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
        "old_evidence_coverage_20260912": case["expected_coverage"],
        "old_evidence_covered": case["expected_covered"],
        "old_evidence_n": case["expected_n"],
        "gaps": [],
    }

    if not model_path.is_file():
        rec["gaps"].append(f"模型文件缺失: {model_path}")
    if not csv_path.is_file():
        rec["gaps"].append(f"测试预测缺失: {csv_path}")
    if rec["gaps"]:
        rec["status"] = "gap"
        return rec

    # 映射表交叉核对（artifact_run_map.csv 为 2026-09-12 生成，model_file/run_dir 路径未变）
    mrow = run_map.get(case["artifact_id"])
    map_note = None
    if mrow is None:
        map_note = "artifact_run_map.csv 无此 artifact_id"
    elif mrow.get("model_file") != case["model_file"] or mrow.get("run_dir") != case["run_dir"]:
        map_note = (
            f"映射表不一致: model_file {mrow.get('model_file')} vs {case['model_file']}; "
            f"run_dir {mrow.get('run_dir')} vs {case['run_dir']}")
    rec["artifact_run_map_note"] = map_note

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

    # ---- r3 新增：新包内部自洽判据（真正的 pass/fail 依据） ----
    ment = manifest_entries.get(case["artifact_id"])
    self_checks = {"manifest_entry_found": ment is not None}
    if ment:
        m_unc = ment.get("uncertainty", {}) or {}
        m_cov = m_unc.get("empirical_coverage_test")
        self_checks.update({
            "manifest_sha256_match": ment.get("sha256") == model_sha,
            "manifest_coverage_match": (
                isinstance(m_cov, (int, float)) and abs(float(m_cov) - cov_raw) < 1e-9),
            "manifest_test_n_match": m_unc.get("test_n") == n,
        })
    self_checks.update({
        "bundle_meta_coverage_match": (
            meta.get("empirical_coverage_test") is not None
            and abs(float(meta["empirical_coverage_test"]) - cov_raw) < 1e-9),
        "bundle_meta_test_n_match": meta.get("test_n") == n,
        "quantiles_finite_and_ordered": (
            lo == lo and hi == hi and lo <= hi),
    })
    rec["self_consistency"] = self_checks
    rec["self_consistency_pass"] = all(
        v for k, v in self_checks.items() if isinstance(v, bool))

    # ---- 与旧审查 evidence.json 的对账（如实记录，预期漂移） ----
    ev = evidence.get((metric, horizon))
    recon = {"evidence_found": ev is not None}
    if ev:
        recon.update({
            "audit_covered_20260912": ev.get("covered"),
            "audit_n": ev.get("n"),
            "audit_coverage_20260912": ev.get("coverage"),
            "audit_sha256_20260912": ev.get("sha256"),
            "covered_match": ev.get("covered") == covered_raw,
            "n_match": ev.get("n") == n,
            "coverage_match": abs(float(ev.get("coverage")) - cov_raw) < 1e-12,
            "p05_match": abs(float(ev.get("residual_p05")) - lo) < 1e-12,
            "p95_match": abs(float(ev.get("residual_p95")) - hi) < 1e-12,
            "sha256_match": ev.get("sha256") == model_sha,
        })
        recon["all_match"] = all(recon[k] for k in (
            "covered_match", "n_match", "coverage_match", "p05_match", "p95_match", "sha256_match"))
        recon["drift_explanation"] = (
            "模型已全量重训（e698d0a），旧审查数字属 2026-09-12 旧包；"
            "本行为预期漂移对照，不作为 r3 失败依据。" if not recon["all_match"] else "与旧审查一致")
    rec["reconciliation_vs_old_evidence"] = recon
    return rec


def main() -> int:
    import numpy
    import pandas
    import sklearn

    ap = argparse.ArgumentParser(description="K4 r3 六组区间覆盖率独立复算（冻结新包，只读不重训）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出 JSON 路径")
    args = ap.parse_args()

    evidence = load_evidence()
    run_map = load_run_map()
    manifest_entries = load_manifest_entries()

    cases = [recompute_case(c, evidence, run_map, manifest_entries) for c in CASES]

    checked = [c for c in cases if c.get("status") == "checked"]
    gaps = []
    for c in cases:
        for g in c.get("gaps", []):
            gaps.append({"case": f"{c['metric']}T+{c['horizon_days']}", "gap": g})
        if c.get("status") == "gap":
            gaps.append({"case": f"{c['metric']}T+{c['horizon_days']}",
                         "gap": "无法复算（见上）"})

    self_fail = [
        f"{c['metric']}T+{c['horizon_days']}"
        for c in checked if not c.get("self_consistency_pass")
    ]
    drift = [
        {
            "case": f"{c['metric']}T+{c['horizon_days']}",
            "old_coverage_20260912": c.get("reconciliation_vs_old_evidence", {}).get("audit_coverage_20260912"),
            "new_coverage": c.get("coverage_raw"),
            "old_covered": c.get("reconciliation_vs_old_evidence", {}).get("audit_covered_20260912"),
            "new_covered": c.get("covered_raw"),
            "n": c.get("n_test"),
            "sha256_changed": not c.get("reconciliation_vs_old_evidence", {}).get("sha256_match"),
        }
        for c in checked
        if not c.get("reconciliation_vs_old_evidence", {}).get("all_match")
    ]

    payload = {
        "audit": "K4 区间覆盖率独立复算（R5 冻结后审计刷新 r3）",
        "date": "2026-09-13",
        "tool": "backend/trust_audit/interval_coverage_recheck_r3_20260913.py",
        "base_tool": "backend/trust_audit/interval_coverage_recheck.py（2026-09-12，保留不动）",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": (
            "只读 joblib bundle 的内嵌 residual_p05/p95 + runs/*/test_predictions.csv 逐行预测，"
            "按 serving 物理裁剪（下界 max(.,0)，density 上界 min(.,1)）独立复算经验覆盖率；"
            "不 import 训练代码、不重放、不重训。与 2026-09-12 审查 evidence.json 的差异为"
            "全量重训（e698d0a）后的预期漂移，r3 的 pass/fail 依据为新包内部自洽判据。"),
        "serving_clip_rule": "lower=max(x+resid_p05,0); upper=min(x+resid_p95,1) 仅对 density",
        "source_evidence": str(EVIDENCE),
        "sources_json": str(SOURCES) if SOURCES.is_file() else None,
        "artifact_run_map": str(RUN_MAP) if RUN_MAP.is_file() else None,
        "artifact_run_map_note": (
            "映射表为 2026-09-12 生成（文件名未变、模型内容已重训），仅作路径交叉核对；"
            "其 sha256/coverage 列属旧包数字，不作 r3 判据"),
        "environment": {
            "python": sys.version.split()[0],
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "summary": {
            "cases_total": len(cases),
            "cases_checked": len(checked),
            "self_consistency_pass_all": not self_fail and not gaps,
            "self_consistency_failures": self_fail,
            "gaps_count": len(gaps),
            "drift_vs_20260912_count": len(drift),
            "drift_cases": drift,
        },
        "cases": cases,
        "gaps": gaps,
        "notes": [
            "覆盖率测试段为训练期内留出块，非 2024+ 冻结段独立样本。",
            "chla T+1 校准段标签混合、T+90 全代理；density/biomass 为代理契约口径（新 manifest 中 biomass 标 ground_truth，L-cal-17 口径冲突仍在）。",
            "coverage_probability_col 仅在测试表含 probability 列时给出，用于探测 prediction/probability 口径差异。",
        ],
    }

    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 92)
    print("K4 r3 六组区间覆盖率独立复算（冻结新包 e698d0a；旧数字为 2026-09-12 对照）")
    print("=" * 92)
    print(f"{'组':<14}{'覆盖/测试(新)':>14}{'新覆盖率':>10}{'旧覆盖率':>10}{'自洽':>6}{'sha变':>6}")
    print("-" * 92)
    for c in cases:
        if c.get("status") != "checked":
            print(f"{c['label']+' T+'+str(c['horizon_days']):<14}{'--':>14}{'--':>10}{'--':>10}{'GAP':>6}")
            continue
        name = f"{c['label']} T+{c['horizon_days']}"
        frac = f"{c['covered_raw']}/{c['n_test']}"
        new_cov = f"{c['coverage_raw_pct']:.2f}%"
        old_cov = f"{c['old_evidence_coverage_20260912']*100:.2f}%"
        ok = "OK" if c.get("self_consistency_pass") else "FAIL"
        sha_changed = "是" if not c["reconciliation_vs_old_evidence"].get("sha256_match") else "否"
        print(f"{name:<14}{frac:>14}{new_cov:>10}{old_cov:>10}{ok:>6}{sha_changed:>6}")
    print("-" * 92)
    if self_fail:
        print("新包自洽失败：")
        for m in self_fail:
            print("  - " + m)
    if gaps:
        print("缺口：")
        for g in gaps:
            print("  - " + g["case"] + ": " + g["gap"])
    if not self_fail and not gaps:
        print(f"六组新包自洽全部通过（bundle meta / manifest / 复算三方一致）；"
              f"与 2026-09-12 旧审查数字漂移 {len(drift)} 组（模型重训所致，已如实记录）。")
    print(f"\n输出: {out}")

    return 0 if not self_fail and not gaps else 2


if __name__ == "__main__":
    raise SystemExit(main())
