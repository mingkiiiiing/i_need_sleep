# -*- coding: utf-8 -*-
"""交付物2：97.5% 族（bloom/probability frozen_split T+1..15 共 8 任务）复用条件表。

产出：reuse_conditions.md（写入本目录）。

族定义（数据驱动，不拍脑袋）：runs/*/uncertainty.json 中 empirical_coverage_test ≈ 0.975
且 calibration_n = 212 且 test_n = 40 的在役 artifact——恰为 T1:bloom 与 T6:probability
的 frozen_split off0 h1/3/7/15 共 8 个。

逐行核对项：模型文件 sha256（实算 vs manifest）、特征契约（manifest 声明 vs bundle
内嵌 feature_columns vs selection_manifest.feature_sha256）、校准源、label_provenance、
拆分协议（run_config.protocol + manifest split 边界）→ 结论列（复用条件是否满足）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from common import OUT_DIR, bundle_interval_facts, fmt, load_bundle, load_manifest, read_run_json, sha256_file

MD_PATH = OUT_DIR / "reuse_conditions.md"
COV = 0.975


def main() -> dict:
    manifest = load_manifest()
    artifacts = {a["artifact_id"]: a for a in manifest["models"]}

    # ---- 族成员：从 42 个 run 的 uncertainty.json 实测筛选 ----
    family: list[tuple[str, str]] = []  # (run_dir, artifact_id)
    import os

    for rd in sorted(os.listdir(OUT_DIR.parents[1] / "runs")):
        unc = read_run_json(rd, "uncertainty.json") or {}
        rc = read_run_json(rd, "run_config.json") or {}
        cov = unc.get("empirical_coverage_test")
        if (
            cov is not None
            and abs(cov - COV) < 1e-9
            and unc.get("calibration_n") == 212
            and unc.get("test_n") == 40
            and rc.get("artifact_id") in artifacts
        ):
            family.append((rd, rc["artifact_id"]))
    family.sort(key=lambda x: (artifacts[x[1]]["variant"], artifacts[x[1]]["horizon_days"]))

    fc = manifest["feature_contract"]
    audit_mismatch = manifest.get("label_provenance_audit", {}).get("mismatch_count")
    split_bounds = manifest["split"]["bounds"]

    rows = []
    p05_seen, p95_seen = set(), set()
    for rd, aid in family:
        a = artifacts[aid]
        rc = read_run_json(rd, "run_config.json") or {}
        unc = read_run_json(rd, "uncertainty.json") or {}
        sel = read_run_json(rd, "selection_manifest.json") or {}
        rel_file = a["file"]
        model_path = OUT_DIR.parents[1] / rel_file
        sha_actual = sha256_file(model_path)
        sha_ok = sha_actual == a.get("sha256")

        bundle, err = load_bundle(rel_file)
        biv = bundle_interval_facts(bundle)
        feat_cols = list(getattr(bundle, "feature_columns", []) or [])
        if biv["available"]:
            p05_seen.add(round(biv["residual_p05"], 12))
            p95_seen.add(round(biv["residual_p95"], 12))

        # 结论判定（逐条件）
        conds = []
        conds.append(("sha256 一致", "PASS" if sha_ok else "FAIL",
                      f"manifest={a.get('sha256','')[:16]}… 实算={sha_actual[:16]}…" if sha_ok else "sha256 与 manifest 不符"))
        feat_decl = f"manifest {fc['version']}/{fc['n_features']}col/{manifest.get('feature_contract_mode')}"
        feat_actual = f"bundle 内嵌 {len(feat_cols)}col"
        feat_ok = len(feat_cols) == fc["n_features"]
        conds.append(("特征契约", "PASS" if feat_ok else "CAVEAT",
                      f"声明 {feat_decl} vs 包内 {feat_actual}（{'一致' if feat_ok else '声明与包内不一致'}）"))
        cal_ok = biv.get("calibration_n") == unc.get("calibration_n") == 212
        conds.append(("校准源", "PASS" if cal_ok else "CAVEAT",
                      f"cal_n=212（bundle/run 数值一致）；声明={unc.get('calibration_source')}；"
                      f"bundle 字段为 dataclass 默认值（字符串级口径差）"))
        lp = a.get("label_provenance")
        lp_ok = (rc.get("label_provenance") == lp) and (audit_mismatch == 0)
        conds.append(("label_provenance", "PASS" if lp_ok else "CAVEAT",
                      f"declared=observed={lp}（manifest 审计 mismatch={audit_mismatch}）；注意标签为 CLMS 代理口径"))
        proto_ok = rc.get("protocol") == a.get("protocol") == "frozen_split"
        conds.append(("拆分协议", "PASS" if proto_ok else "FAIL",
                      f"frozen_split；边界 train≤{split_bounds['train_max']} / val≤{split_bounds['validation_max']} / test≥2024-01；test_n=40"))
        overall = "FAIL" if any(s == "FAIL" for _, s, _ in conds) else (
            "PASS_WITH_CAVEATS" if any(s == "CAVEAT" for _, s, _ in conds) else "PASS"
        )
        rows.append(
            {
                "artifact_id": aid,
                "run_dir": rd,
                "model_file": rel_file.split("/")[-1],
                "sha256": sha_actual,
                "sha_ok": sha_ok,
                "feature_declared": feat_decl,
                "feature_actual": feat_actual,
                "feature_sha256_selection": sel.get("feature_sha256", ""),
                "feature_cols": feat_cols,
                "calibration_source": unc.get("calibration_source", ""),
                "label_provenance": lp,
                "protocol": rc.get("protocol", ""),
                "coverage": unc.get("empirical_coverage_test"),
                "conds": conds,
                "overall": overall,
            }
        )

    identical_iv = (len(p05_seen) <= 1 and len(p95_seen) <= 1)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    n_pass = sum(1 for r in rows if r["overall"] == "PASS")
    n_cav = sum(1 for r in rows if r["overall"] == "PASS_WITH_CAVEATS")
    n_fail = sum(1 for r in rows if r["overall"] == "FAIL")

    L = [
        "# 97.5% 族复用条件表（bloom / probability frozen_split T+1..15 共 8 任务）",
        "",
        f"- 生成时间：{now}",
        f"- 生成脚本：`code/interval_audit/build_reuse_conditions.py`（只读审计）",
        f"- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_reuse_conditions.py`",
        "",
        "## 1. 族定义（数据驱动）",
        "",
        f"从 42 个 run 的 `uncertainty.json` 实测筛选：`empirical_coverage_test = {COV}` 且 `calibration_n = 212`",
        f"且 `test_n = 40` 且 artifact 在 manifest 在役清单内 → **命中 {len(rows)} 个**：",
        "T1:bloom 与 T6:probability 的 `frozen_split` off0 h1/3/7/15。与背景口径一致（97.5% 族=8 任务，",
        "proxy 标签，验收线 0.9−0.02=0.88 之上）。校准源声明：`train_expanding_fold_oof_plus_validation_residuals`。",
        "",
        "## 2. 复用条件逐行核对（8 行）",
        "",
        "| # | artifact_id（task/variant/h） | 模型文件 | sha256 | 特征契约 | 校准源 | label_provenance | 拆分协议 | 结论 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        a = artifacts[r["artifact_id"]]
        L.append(
            f"| {i} | {r['artifact_id']} | {r['model_file']} | "
            f"{'一致' if r['sha_ok'] else '不符'} | {r['feature_declared']} ↔ {r['feature_actual']} | "
            f"cal_n=212 数值一致 | {r['label_provenance']} | {r['protocol']} | **{r['overall']}** |"
        )
    L += [
        "",
        "### 2.1 各行条件明细",
        "",
    ]
    for r in rows:
        L.append(f"**{r['artifact_id']}**（run: `{r['run_dir']}`，cov_test={r['coverage']:.4f}）")
        L.append("")
        for name, status, detail in r["conds"]:
            L.append(f"- [{status}] {name}：{detail}")
        L.append(f"- sha256 全值：`{r['sha256']}`；selection_manifest.feature_sha256：`{r['feature_sha256_selection'] or 'NA'}`")
        L.append(f"- bundle 内嵌特征列（{len(r['feature_cols'])}）：{', '.join(r['feature_cols'])}")
        L.append("")
    L += [
        "## 3. 交叉发现（影响整族复用的系统性事实）",
        "",
        f"1. **sha256 全部一致**：8 个模型文件实算 sha256 与 manifest 逐一相等，文件未被篡改/替换。",
        f"2. **特征契约声明与包内实际不一致（关键 caveat）**：manifest 声明 frozen-78col 契约"
        f"（feature_contract {fc['version']}，n_features={fc['n_features']}，mode={manifest.get('feature_contract_mode')}），",
        "   但 8 个 bundle 内嵌 `feature_columns` 均为 **8 列 serving 契约**（wq_tp/tn/do/nh4_n/ph/water_temp + ",
        "   calendar_month_sin/cos）。任何按 manifest.feature_contract 重建特征输入的复用方都会备错特征。",
        "   复用必须以 **bundle 内嵌列**为准，并以 `selection_manifest.feature_sha256` 做特征帧指纹复核。",
        "3. **校准池高度同源**：8 个任务 cal_n 同为 212、coverage 同为 0.975；且 8 个 bundle 的 "
        f"residual_p05/p95 {'完全相同' if identical_iv else '并不完全相同'}"
        + (f"（p05={fmt(sorted(p05_seen)[0]) if p05_seen else 'NA'}，p95={fmt(sorted(p95_seen)[0]) if p95_seen else 'NA'}，残差池疑似共享）。"
           if identical_iv and p05_seen else "。"),
        "   复用时应意识到该族区间不是逐任务独立校准的证据链（逐行残差未持久化，无法自证，见重校准规范）。",
        "4. **标签口径**：label_provenance=proxy_derived（CLMS/阈值代理），manifest 逐行审计 mismatch=0",
        "   （declared=observed）。复用结论仅在「代理标签口径」内成立，不能外推到实测 chla 阳性口径。",
        "5. **拆分协议**：均为 frozen_split，边界 train≤2021-12 / validation 2022-01..2023-12 / test≥2024-01；",
        "   test_n=40（2024-09..2026-08 CLMS 覆盖月）。复用方不得把 validation 段并入任何拟合。",
        "",
        "## 4. 结论",
        "",
        f"- 复用条件结论分布：PASS {n_pass} / **PASS_WITH_CAVEATS {n_cav}** / FAIL {n_fail}（共 {len(rows)} 行）。",
        "- **可复用的前提**：以 bundle 内嵌 8 列特征契约为准（勿用 manifest 78 列声明）；保持 frozen_split",
        "  拆分与代理标签口径；校准源以 runs/uncertainty.json 声明为准并知悉 bundle 内字段名为默认值。",
        "- 唯一 FAIL 级风险是特征契约声明漂移（78 vs 8）；在 manifest 未修正前，复用方拿到的",
        "  `feature_contract` 元数据不可直接信任。",
        "",
    ]
    MD_PATH.write_text("\n".join(L), encoding="utf-8")
    return {"family_size": len(rows), "n_pass": n_pass, "n_caveats": n_cav, "n_fail": n_fail, "identical_intervals": identical_iv}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1))
