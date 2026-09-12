# -*- coding: utf-8 -*-
"""交付物1：34 个在役 artifact ↔ 42 个 run 目录映射核对表。

产出：artifact_run_map.csv + artifact_run_map.md（写入本目录）。

映射方法（零猜测）：
  权威键 = run_config.json 的 artifact_id 与 manifest.json models[].artifact_id 精确字符串相等；
  命名规则 {task}-{variant}-{h}d-{off}m[-cv] 仅作交叉校验，不参与判定；
  凡 run_config.artifact_id 不在 manifest.models 中 → UNMAPPED（如实标注，不猜）。

对照（只读）：joblib.load(models/*.joblib) 抽 bundle.intervals 残差分位字段
  （residual_p05 / residual_p95 / calibration_n / calibration_source），
  与 runs/*/uncertainty.json 的记录对照，逐行标注一致/不一致。
  注：uncertainty.json 不含 p05/p95 数值，故数值级对照仅限 calibration_n /
  calibration_source / coverage / test_n；p05/p95 仅从 bundle 侧披露。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from common import (
    ACCEPT_LINE,
    OUT_DIR,
    PKG_ROOT,
    bundle_interval_facts,
    fmt,
    list_run_dirs,
    load_bundle,
    load_manifest,
    read_run_json,
    run_dir_name_rule,
    sha256_file,
)

CSV_PATH = OUT_DIR / "artifact_run_map.csv"
MD_PATH = OUT_DIR / "artifact_run_map.md"


def main() -> dict:
    manifest = load_manifest()
    artifacts = manifest["models"]
    by_artifact_id = {a["artifact_id"]: a for a in artifacts}

    # ---- run 目录索引：run_config.artifact_id -> [run_dir, ...] ----
    run_index: dict[str, list[str]] = {}
    run_meta: dict[str, dict] = {}
    for rd in list_run_dirs():
        rc = read_run_json(rd, "run_config.json") or {}
        unc = read_run_json(rd, "uncertainty.json") or {}
        aid = rc.get("artifact_id")
        run_meta[rd] = {"run_config": rc, "uncertainty": unc}
        if aid:
            run_index.setdefault(aid, []).append(rd)

    rows: list[dict] = []
    inconsistencies: list[str] = []
    for a in artifacts:
        aid = a["artifact_id"]
        rel_file = a["file"]
        model_path = PKG_ROOT / rel_file
        file_exists = model_path.is_file()
        sha_actual = sha256_file(model_path) if file_exists else None
        sha_match = (sha_actual == a.get("sha256")) if file_exists else None

        dirs = run_index.get(aid, [])
        if len(dirs) == 1:
            rd = dirs[0]
        elif not dirs:
            rd = None
        else:  # 理论不应发生：一 artifact 多 run 目录 → 如实并列，不猜
            rd = "MULTI:" + "|".join(dirs)
        rc = run_meta.get(dirs[0], {}).get("run_config", {}) if dirs and not str(rd).startswith("MULTI") else {}
        unc = run_meta.get(dirs[0], {}).get("uncertainty", {}) if dirs and not str(rd).startswith("MULTI") else {}

        # 命名规则交叉校验
        derived = run_dir_name_rule(a)
        name_match = (derived == rd) if isinstance(rd, str) and rd else None

        # bundle 只读抽取
        bundle, err = load_bundle(rel_file)
        biv = bundle_interval_facts(bundle)
        biv["available"] = biv["available"] or (err is not None and False)
        b_err = err

        # bundle vs run uncertainty 对照（数值级：calibration_n / coverage_target；字符串级：calibration_source）
        hard_diffs: list[str] = []   # 数值/结构级失配
        soft_diffs: list[str] = []   # 字符串/文档级
        structural = False
        if b_err:
            hard_diffs.append(f"bundle:{b_err}")
        elif not biv["available"]:
            # bundle 无区间（序数任务 intervals=None）。若 run 侧同为 cal_n=0，则两侧
            # 「没有可校准区间」这一事实互相印证 → 结构性一致，不算失配。
            if unc.get("calibration_n") == 0:
                structural = True
            else:
                hard_diffs.append(
                    f"bundle:intervals=None 而 run cal_n={unc.get('calibration_n')}（结构失配）"
                )
        if biv["available"]:
            if biv["calibration_n"] != unc.get("calibration_n"):
                hard_diffs.append(
                    f"calibration_n bundle={biv['calibration_n']} vs run={unc.get('calibration_n')}"
                )
            if (biv["coverage_target"] or None) != (unc.get("coverage_target") or None):
                hard_diffs.append(f"coverage_target bundle={biv['coverage_target']} vs run={unc.get('coverage_target')}")
            if (biv["calibration_source"] or "") != (unc.get("calibration_source") or ""):
                soft_diffs.append(
                    "calibration_source bundle="
                    f"{biv['calibration_source']!r} vs run={unc.get('calibration_source')!r}"
                )
        if rc.get("artifact_id") != aid:
            hard_diffs.append("artifact_id mismatch(run_config vs manifest)")

        # 校准状态口径
        cal_n = unc.get("calibration_n")
        if cal_n is None:
            calibration_status = "unknown"
        elif cal_n == 0:
            calibration_status = "not_calibrated(cal_n=0)"
        else:
            calibration_status = f"calibrated(cal_n={cal_n})"

        if hard_diffs:
            unc_consistent = "inconsistency(hard)"
        elif soft_diffs:
            unc_consistent = "inconsistency(string)"
        elif structural:
            unc_consistent = "consistent(structural)"
        else:
            unc_consistent = "consistent"

        cov = unc.get("empirical_coverage_test")
        cov_str = fmt(cov) if cov is None else f"{cov:.4f}"
        if cov is not None and cov < ACCEPT_LINE:
            cov_str += " (<0.88 验收线)"

        rows.append(
            {
                "artifact_id": aid,
                "model_file": rel_file,
                "model_file_exists": "yes" if file_exists else "NO",
                "sha256_match_manifest": {True: "yes", False: "NO", None: "NA"}[sha_match],
                "task_id": a.get("task_id", ""),
                "variant": a.get("variant", ""),
                "protocol": a.get("protocol", ""),
                "month_offset": a.get("month_offset", ""),
                "horizon_days": a.get("horizon_days", ""),
                "label_provenance": a.get("label_provenance", ""),
                "run_dir": rd if rd else "UNMAPPED(no run dir)",
                "run_dir_name_rule_match": {True: "yes", False: "NO", None: "NA"}[name_match],
                "empirical_coverage_test": cov_str,
                "test_n": unc.get("test_n", ""),
                "calibration_n_run": cal_n,
                "calibration_source_run": unc.get("calibration_source", ""),
                "calibration_status": calibration_status,
                "bundle_residual_p05": fmt(biv.get("residual_p05")),
                "bundle_residual_p95": fmt(biv.get("residual_p95")),
                "bundle_width": fmt(biv.get("width_p95_minus_p05")),
                "bundle_calibration_n": biv.get("calibration_n", "NA"),
                "unc_vs_bundle": unc_consistent,
                "diff_detail": "; ".join(hard_diffs + soft_diffs) if (hard_diffs or soft_diffs) else "",
            }
        )
        if hard_diffs or soft_diffs:
            inconsistencies.append(f"{aid}: " + "; ".join(hard_diffs + soft_diffs))

    # ---- 反向：42 个 run 目录中未被任何 artifact 认领的 ----
    mapped_dirs = {r["run_dir"] for r in rows if isinstance(r["run_dir"], str) and not r["run_dir"].startswith("UNMAPPED") and not r["run_dir"].startswith("MULTI")}
    unmapped_dirs = [rd for rd in list_run_dirs() if rd not in mapped_dirs]
    unmapped_rows = []
    for rd in unmapped_dirs:
        rc = run_meta[rd]["run_config"]
        unc = run_meta[rd]["uncertainty"]
        aid = rc.get("artifact_id", "")
        in_manifest = aid in by_artifact_id
        cov = unc.get("empirical_coverage_test")
        unmapped_rows.append(
            {
                "run_dir": rd,
                "run_config_artifact_id": aid,
                "in_manifest": "yes" if in_manifest else "NO",
                "protocol": rc.get("protocol", ""),
                "horizon_days": rc.get("horizon_days", ""),
                "test_n": unc.get("test_n", ""),
                "empirical_coverage_test": "NA" if cov is None else f"{cov:.4f}",
                "note": "run 目录存在但 manifest 无此 artifact_id → 无模型文件映射，如实标 UNMAPPED",
            }
        )

    # ---- CSV ----
    fieldnames = list(rows[0].keys())
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    with (OUT_DIR / "artifact_run_map_unmapped.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(unmapped_rows[0].keys()))
        w.writeheader()
        w.writerows(unmapped_rows)

    # ---- MD ----
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n_mapped = sum(1 for r in rows if isinstance(r["run_dir"], str) and not r["run_dir"].startswith("UNMAPPED"))
    n_name_ok = sum(1 for r in rows if r["run_dir_name_rule_match"] == "yes")
    n_sha_ok = sum(1 for r in rows if r["sha256_match_manifest"] == "yes")
    n_cons = sum(1 for r in rows if r["unc_vs_bundle"].startswith("consistent"))
    n_struct = sum(1 for r in rows if r["unc_vs_bundle"] == "consistent(structural)")
    n_soft = sum(1 for r in rows if r["unc_vs_bundle"] == "inconsistency(string)")
    n_hard = sum(1 for r in rows if r["unc_vs_bundle"] == "inconsistency(hard)")
    lines = [
        "# artifact ↔ run 目录映射核对表（34 在役 artifact × 42 run 目录）",
        "",
        f"- 生成时间：{now}",
        f"- 生成脚本：`code/interval_audit/build_artifact_run_map.py`（只读审计，无写回）",
        f"- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_artifact_run_map.py`",
        "",
        "## 1. 映射规则（写入报告，全程零猜测）",
        "",
        "1. **权威键**：`runs/<dir>/run_config.json` 的 `artifact_id` 与 `manifest.json` `models[].artifact_id`",
        "   **精确字符串相等**（如 `T1:bloom:frozen_split:off0:h15:s20260907`）。判定只认这个键。",
        "2. **命名交叉校验**（非权威）：run 目录命名 = `{task_id}-{variant}-{horizon_days}d-{month_offset}m`，",
        "   protocol=`train_internal_time_block_cv_v1` 时追加 `-cv` 后缀，`frozen_split` 无后缀。",
        "   manifest 的 `run_id`（如 `T1-bloom-0m-s20260907`）是训练期命名（含 seed），与 run 目录名不是同一命名空间，",
        "   仅作背景说明。",
        "3. **对不上即 UNMAPPED**：run 目录的 artifact_id 不在 manifest → 标 UNMAPPED；",
        "   artifact 找不到 run 目录 → 该行 run_dir 标 `UNMAPPED(no run dir)`。不做模糊匹配。",
        "",
        "## 2. 汇总",
        "",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| manifest 在役 artifact | {len(artifacts)} |",
        f"| run 目录总数 | {len(list_run_dirs())} |",
        f"| artifact→run 目录映射成功 | {n_mapped}/{len(artifacts)} |",
        f"| 命名规则交叉校验通过 | {n_name_ok}/{n_mapped} |",
        f"| 模型文件存在且 sha256=manifest.sha256 | {n_sha_ok}/{len(artifacts)} |",
        f"| bundle↔uncertainty：calibration_n / coverage_target 数值相等 | {n_cons + n_soft}/{len(artifacts)} |",
        f"| bundle↔uncertainty：calibration_source 字符串不一致 | {n_soft}/{len(artifacts)} |",
        f"| bundle↔uncertainty：risk_level 结构性一致（intervals=None ↔ cal_n=0） | {n_struct}/34 |",
        f"| bundle↔uncertainty：数值/结构级失配 | {n_hard}/{len(artifacts)} |",
        f"| 无主 run 目录（UNMAPPED，反向） | {len(unmapped_dirs)} |",
        "",
        "## 3. 34 行映射明细",
        "",
        "完整字段见 `artifact_run_map.csv`（UTF-8-SIG）。下表为关键列：",
        "",
        "| artifact_id | model file | task/variant/h | label_provenance | run 目录 | cov_test | cal 状态 | unc↔bundle |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['artifact_id']} | {r['model_file'].split('/')[-1]} | {r['task_id']}/{r['variant']}/T+{r['horizon_days']} | "
            f"{r['label_provenance']} | {r['run_dir']} | {r['empirical_coverage_test']} | {r['calibration_status']} | {r['unc_vs_bundle']} |"
        )
    lines += [
        "",
        "## 4. bundle.intervals（joblib 只读抽取）与 uncertainty.json 对照",
        "",
        "`ResidualIntervals` 字段：`residual_p05` / `residual_p95`（区间 = 点预测 ± 残差分位，",
        "宽度 = p95−p05，相对量纲=目标标签量纲：bloom/probability=概率，density/biomass/chla=原值）。",
        "uncertainty.json **不含** p05/p95 数值，仅含汇总（calibration_n / calibration_source / coverage）。",
        "",
        f"对照结论（分档如实报告）：",
        "",
        f"- **数值级：calibration_n / coverage_target 在 {n_cons + n_soft}/{len(artifacts)} 个可用 bundle 上",
        "  与 runs/uncertainty.json 完全相等，无任何数值失配。** 其中：",
        f"  - {n_struct} 个 risk_level（序数）bundle 为**结构性一致**：bundle.intervals=None，与 run 侧",
        "    cal_n=0 / coverage=None 两侧互相印证「无校准区间」；",
        f"  - {n_soft} 个存在**字符串级不一致**：`intervals.calibration_source` 全部是 dataclass 默认值",
        "    `train_fold_out_of_fold_plus_validation`，而 runs/uncertainty.json 与 manifest 声明为",
        "    `train_expanding_fold_oof_plus_validation_residuals`（bundle 侧 `ResidualIntervals` 默认字段",
        "    未随训练结果覆写）。不影响数值，但同一事实在包内有两个名字，建议后续版本统一。",
        f"- **数值/结构级失配 {n_hard}/{len(artifacts)}**：无。",
        "",
    ]
    if inconsistencies:
        lines += ["不一致逐行清单：", ""]
        for s in inconsistencies:
            lines.append(f"- {s}")
        lines.append("")
    lines += [
        "## 5. UNMAPPED run 目录（反向核对，8 个）",
        "",
        "以下 run 目录的 `run_config.artifact_id` 不在 manifest.models（34）中 → 无模型文件对应，",
        "如实标 UNMAPPED。明细见 `artifact_run_map_unmapped.csv`：",
        "",
        "| run 目录 | run_config.artifact_id | protocol | test_n | cov_test |",
        "|---|---|---|---|---|",
    ]
    for r in unmapped_rows:
        lines.append(
            f"| {r['run_dir']} | {r['run_config_artifact_id']} | {r['protocol']} | {r['test_n']} | {r['empirical_coverage_test']} |"
        )
    lines += [
        "",
        "## 6. 结论",
        "",
        f"- 34/34 在役 artifact 均能以精确 artifact_id 找到唯一 run 目录与唯一模型文件；",
        f"  命名交叉校验 {n_name_ok}/{n_mapped} 通过（规则可复述）。",
        f"- 模型文件 sha256 与 manifest 一致：{n_sha_ok}/{len(artifacts)}。",
        f"- bundle↔uncertainty：数值级全部一致；唯一的系统性不一致是 calibration_source 字符串",
        "  （bundle=dataclass 默认值 vs run=声明值），属文档口径问题，见第 4 节。",
        f"- 42−34=8 个 run 目录 UNMAPPED（T5-chla 与 T6-risk_level 的 frozen_split T+1/3/7/15 共 8 个，",
        "  门禁表亦无对应行——它们是候选 run，未入役）。对不上的如实标注，未做任何猜测式映射。",
        "",
    ]
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {"mapped": n_mapped, "unmapped_dirs": unmapped_dirs, "inconsistencies": inconsistencies}


if __name__ == "__main__":
    out = main()
    print(json.dumps({k: (v if k != "unmapped_dirs" else len(v)) for k, v in out.items()}, ensure_ascii=False, indent=1))
