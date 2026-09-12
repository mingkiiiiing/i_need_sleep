# -*- coding: utf-8 -*-
"""交付物3：全部 42 run 的区间宽度体检（退化/过宽/无区分度/证据不足/欠覆盖）。

产出：width_degeneracy_report.md + width_degeneracy.csv（写入本目录）。

口径：
- 宽度 = bundle.intervals.residual_p95 − residual_p05（joblib 只读抽取），
  量纲 = 目标标签量纲（bloom/probability=概率 0-1；density/biomass/chla=原值单位）。
- actual 分布取 runs/<dir>/test_predictions.csv 的 actual 列（数值解析，NaN 剔除）。
- 判定规则（spec 定义 + 如实扩展）：
  degenerate        宽度 = 0
  wide              宽度 > 3 × IQR(actual)   （二分类 IQR=0 时规则按触发计，但标注量纲退化）
  no_discrimination 同 (task,variant,protocol) 组内各 horizon 宽度完全相同且为非常数正值（组≥2）
  weak_evidence     coverage = 1.0 且 test_n < 10
  undercover        coverage < 0.88（验收线 = 0.90 − 0.02）
  no_interval       区间不存在（risk_level 序数任务 intervals=None，或 run 目录 UNMAPPED 无模型）
                    —— spec 五类结论之外的如实扩展：无宽度可检时不得硬套 healthy。
- 主结论优先级：degenerate > wide > no_discrimination > undercover > weak_evidence >
  no_interval > healthy；全部触发项同时列于 flags 列，不做遮蔽。
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

import numpy as np

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
    read_run_predictions,
)

CSV_PATH = OUT_DIR / "width_degeneracy.csv"
MD_PATH = OUT_DIR / "width_degeneracy_report.md"

UNIT = {"bloom": "概率(0-1)", "probability": "概率(0-1)", "density": "原值(密度)", "biomass": "原值(生物量)", "chla": "原值(μg/L)", "risk_level": "序数标签(无区间)"}


def actual_stats(rows: list[dict]) -> dict:
    vals = []
    for r in rows:
        try:
            v = float(r.get("actual", ""))
        except (TypeError, ValueError):
            continue
        if np.isfinite(v):
            vals.append(v)
    if not vals:
        return {"n": 0, "q1": None, "median": None, "q3": None, "iqr": None, "min": None, "max": None}
    a = np.asarray(vals, dtype=float)
    q1, med, q3 = (float(x) for x in np.percentile(a, [25, 50, 75]))
    return {
        "n": int(a.size), "q1": q1, "median": med, "q3": q3,
        "iqr": q3 - q1, "min": float(a.min()), "max": float(a.max()),
    }


def main() -> dict:
    manifest = load_manifest()
    art_by_id = {a["artifact_id"]: a for a in manifest["models"]}
    # run_dir -> artifact_id（权威键 = run_config.artifact_id）
    dir2aid: dict[str, str | None] = {}
    for rd in list_run_dirs():
        rc = read_run_json(rd, "run_config.json") or {}
        dir2aid[rd] = rc.get("artifact_id") if rc.get("artifact_id") in art_by_id else None

    # 第一遍：收集宽度与 actual 统计
    recs: list[dict] = []
    for rd in list_run_dirs():
        aid = dir2aid.get(rd)
        rc = read_run_json(rd, "run_config.json") or {}
        unc = read_run_json(rd, "uncertainty.json") or {}
        cols, rows = read_run_predictions(rd)
        st = actual_stats(rows)
        width = None
        width_note = ""
        if aid:
            bundle, err = load_bundle(art_by_id[aid]["file"])
            if err:
                width_note = f"bundle 加载失败:{err}"
            else:
                biv = bundle_interval_facts(bundle)
                if biv["available"]:
                    width = biv["width_p95_minus_p05"]
                    width_note = f"p05={fmt(biv['residual_p05'],4)}, p95={fmt(biv['residual_p95'],4)}"
                else:
                    width_note = "bundle.intervals=None（序数任务，无 conformal 区间）"
        else:
            width_note = "run UNMAPPED（artifact_id 不在 manifest，无模型文件）"
        recs.append(
            {
                "run_dir": rd, "artifact_id": aid, "unc": unc, "st": st,
                "width": width, "width_note": width_note,
                "variant": rc.get("variant", ""),
                "task_id": rc.get("task_id", ""),
                "protocol": rc.get("protocol", ""),
                "horizon_days": rc.get("horizon_days", ""),
                "month_offset": rc.get("month_offset", ""),
            }
        )

    # 第二遍：no_discrimination 组判定（task,variant,protocol,month_offset 组内宽度全同且>0，组≥2）。
    # off0 的 T+1/3/7/15 与 off3 的 T+90 分属不同组，避免把「四个时效同宽」误并成「组内有差异」。
    groups: dict[tuple, list[float]] = {}
    for r in recs:
        if r["width"] is not None:
            groups.setdefault(
                (r["task_id"], r["variant"], r["protocol"], r.get("month_offset", "")), []
            ).append(r["width"])
    nodisc_groups = {
        g for g, ws in groups.items()
        if len(ws) >= 2 and all(abs(w - ws[0]) < 1e-12 for w in ws) and ws[0] > 0
    }

    # 第三遍：逐 run 判定
    for r in recs:
        unc, st, w = r["unc"], r["st"], r["width"]
        cov = unc.get("empirical_coverage_test")
        test_n = unc.get("test_n")
        flags: list[str] = []
        binary = r["variant"] in {"bloom", "probability"}
        if w is not None:
            if w == 0:
                flags.append("degenerate")
            if st["iqr"] is not None and w > 3 * st["iqr"]:
                flags.append("wide" + ("(binary_iqr0)" if binary and st["iqr"] == 0 else ""))
        if (r["task_id"], r["variant"], r["protocol"], r["month_offset"]) in nodisc_groups:
            flags.append("no_discrimination")
        if cov is not None and cov < ACCEPT_LINE and unc.get("calibration_n", 0) and unc.get("calibration_n") > 0:
            flags.append("undercover")
        if cov is not None and abs(cov - 1.0) < 1e-12 and test_n is not None and test_n < 10:
            flags.append("weak_evidence")
        order = ["degenerate", "wide", "wide(binary_iqr0)", "no_discrimination", "undercover", "weak_evidence"]
        primary = next((f for f in order if f in flags), None)
        if primary is None:
            primary = "no_interval" if w is None else "healthy"
        r.update({"cov": cov, "test_n": test_n, "flags": flags, "primary": primary, "binary": binary})

    # ---- CSV ----
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        wtr = csv.writer(f)
        wtr.writerow(
            ["run_dir", "artifact_id", "task_id", "variant", "protocol", "month_offset", "horizon_days",
             "test_n", "empirical_coverage_test", "width_p95_minus_p05", "unit",
             "actual_n", "actual_q1", "actual_median", "actual_q3", "actual_iqr",
             "actual_min", "actual_max", "3xIQR", "flags", "conclusion", "width_note"]
        )
        for r in recs:
            st = r["st"]
            iqr3 = None if st["iqr"] is None else 3 * st["iqr"]
            wtr.writerow([
                r["run_dir"], r["artifact_id"] or "UNMAPPED", r["task_id"], r["variant"],
                r["protocol"], r["month_offset"], r["horizon_days"], r["test_n"],
                "NA" if r["cov"] is None else f"{r['cov']:.6f}",
                "NA" if r["width"] is None else f"{r['width']:.6f}",
                UNIT.get(r["variant"], ""), st["n"],
                fmt(st["q1"]), fmt(st["median"]), fmt(st["q3"]), fmt(st["iqr"]),
                fmt(st["min"]), fmt(st["max"]), fmt(iqr3),
                "|".join(r["flags"]) if r["flags"] else "-",
                r["primary"], r["width_note"],
            ])

    # ---- MD ----
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    counts: dict[str, int] = {}
    for r in recs:
        counts[r["primary"]] = counts.get(r["primary"], 0) + 1
    anomalies = [r for r in recs if r["primary"] not in {"healthy"}]

    L = [
        "# 区间宽度体检报告（42 run 全量）",
        "",
        f"- 生成时间：{now}",
        f"- 生成脚本：`code/interval_audit/build_width_degeneracy.py`（只读审计）",
        f"- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_width_degeneracy.py`",
        "",
        "## 1. 口径与判定规则",
        "",
        "- **宽度** = bundle.intervals 的 `residual_p95 − residual_p05`（joblib 只读抽取；",
        "  uncertainty.json 未持久化分位数值）。区间 = 点预测 + [p05, p95]。",
        "- **量纲**（相对量纲，逐 variant 披露）：" + "；".join(f"{k}={v}" for k, v in UNIT.items()) + "。",
        "- **actual 分布**：runs/<dir>/test_predictions.csv 的 actual 列（数值解析，NaN 剔除），",
        "  报 Q1/中位/Q3/IQR（numpy 线性插值分位）。",
        "- **判定规则**：",
        "  - `degenerate`：宽度 = 0；",
        "  - `wide`：宽度 > 3 × IQR(actual)（二分类 actual∈{0,1} 时 IQR 常为 0，规则按字面触发，",
        "    标注 `wide(binary_iqr0)` 并注明量纲退化，不粉饰也不误读）；",
        "  - `no_discrimination`：同 (task,variant,protocol) 组内各 horizon 宽度完全相同",
        "    （逐位相等，非零正值，组内 ≥2 个）——区间宽度不随时效分化；",
        "  - `weak_evidence`：coverage = 100% 且 test_n < 10（证据不足）；",
        "  - `undercover`：coverage < 0.88（验收线 = coverage_target 0.90 − 容差 0.02）；",
        "  - `no_interval`（如实扩展类）：区间不存在——risk_level 序数任务 bundle.intervals=None，",
        "    或 run 目录 UNMAPPED 无模型文件。无宽度可检时不得硬套 healthy。",
        "- **主结论优先级**：degenerate > wide > no_discrimination > undercover > weak_evidence >",
        "  no_interval > healthy；所有触发项同时写入 flags 列（CSV）与本报告 flags 栏，不做遮蔽。",
        "",
        "## 2. 汇总",
        "",
        "| 主结论 | 数量 | 说明 |",
        "|---|---|---|",
    ]
    desc = {
        "healthy": "区间存在、宽度非零、覆盖达标、无同值组",
        "wide": "宽度 > 3×IQR(actual)",
        "wide(binary_iqr0)": "同上，且因二分类 IQR=0 触发（量纲退化，见 4.2）",
        "degenerate": "宽度 = 0",
        "no_discrimination": "组内各 horizon 宽度完全相同",
        "undercover": "coverage < 0.88",
        "weak_evidence": "coverage=100% 但 test_n<10",
        "no_interval": "risk_level 无区间 / run UNMAPPED 无模型",
    }
    for k in ["healthy", "wide", "wide(binary_iqr0)", "degenerate", "no_discrimination", "undercover", "weak_evidence", "no_interval"]:
        if counts.get(k):
            L.append(f"| {k} | {counts[k]} | {desc[k]} |")
    L += [
        "",
        f"异常/需关注 run 合计：**{len(anomalies)}/{len(recs)}**（healthy 除外）。明细：",
        "",
    ]
    for r in anomalies:
        covs = "NA" if r["cov"] is None else f"{r['cov']:.4f}"
        L.append(
            f"- `{r['run_dir']}` → **{r['primary']}**（flags: {'|'.join(r['flags']) if r['flags'] else '-'}；"
            f"cov={covs}, test_n={r['test_n']}, width={'NA' if r['width'] is None else format(r['width'], '.4f')}"
            f"{', IQR=' + format(r['st']['iqr'], '.4f') if r['st']['iqr'] is not None else ''}）"
        )
    L += [
        "",
        "## 3. 逐 run 明细（42 行）",
        "",
        "机读版：`width_degeneracy.csv`。列含义见第 1 节。",
        "",
        "| run 目录 | task/var/T+ | 协议 | test_n | cov | 宽度(量纲) | actual Q1/中位/Q3 | IQR | flags | 结论 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        st = r["st"]
        if st["n"] and st["q1"] is not None:
            if r["binary"]:
                q = f"{st['q1']:.2f}/{st['median']:.2f}/{st['q3']:.2f}"
                iqr_s = f"{st['iqr']:.2f}"
            else:
                q = f"{st['q1']:.3f}/{st['median']:.3f}/{st['q3']:.3f}"
                iqr_s = f"{st['iqr']:.3f}"
        else:
            q, iqr_s = "NA", "NA"
        L.append(
            f"| {r['run_dir']} | {r['task_id']}/{r['variant']}/T+{r['horizon_days']} | "
            f"{'frozen' if r['protocol'] == 'frozen_split' else 'cv'} | {r['test_n']} | "
            f"{'NA' if r['cov'] is None else format(r['cov'], '.4f')} | "
            f"{'NA' if r['width'] is None else format(r['width'], '.4f')} ({UNIT.get(r['variant'], '')}) | {q} | {iqr_s} | "
            f"{'|'.join(r['flags']) if r['flags'] else '-'} | **{r['primary']}** |"
        )
    L += [
        "",
        "## 4. 交叉发现",
        "",
        "### 4.1 校准池共享痕迹（无区分度的根因指向）",
        "",
    ]
    shared = [r for r in recs if "no_discrimination" in r["flags"]]
    if shared:
        gs = sorted({(r["task_id"], r["variant"], r["protocol"], r["month_offset"]) for r in shared})
        # 每组的共享宽度值（从数据取，不硬编码）
        w_by_group: dict[tuple, float] = {}
        for r in shared:
            w_by_group.setdefault((r["task_id"], r["variant"], r["protocol"], r["month_offset"]), r["width"])
        examples = "；".join(
            f"{t}/{v}/{'frozen' if p == 'frozen_split' else 'cv'}/off{m} 四行同为 {fmt(w_by_group[(t, v, p, m)], 4)}"
            for t, v, p, m in gs
        )
        L += [
            f"- {len(shared)} 个 run 命中 `no_discrimination`，涉及 {len(gs)} 个 (task,variant,protocol,offset) 组：",
            f"  {examples}。同组各 horizon（T+1/3/7/15）宽度逐位相同——",
            "  与复用条件报告第 3 节「8 个 bloom/probability bundle residual_p05/p95 完全相同",
            "  （p05=-0.3510, p95=0.0000）」互为印证：**残差池疑似按任务族共享，而非逐时效独立校准**。",
            "  在逐行校准残差未持久化的现状下（见重校准规范），这一点无法自证清白。",
            "",
        ]
    L += [
        "### 4.2 二分类 wide 判定的量纲说明",
        "",
        "- bloom/probability 的 actual∈{0,1}，test 段阳性极少（如 T1-bloom 40 行仅 1 例阳性），",
        "  IQR=0 → 3×IQR=0 → 任何正宽度都按字面触发 wide。这类行的 `wide(binary_iqr0)` 标注",
        "  **不构成「区间过宽」的实质指控**，但揭示了另一个实质问题：残差池以 0 附近的负残差为主",
        "  （p95=0.0 意味着 95% 分位残差 ≤0），区间几乎只向单侧张开，这与其 0.975 的高覆盖互为因果。",
        "- 回归任务（density/biomass/chla）的 wide 判定在原值量纲上有效，请看逐行 IQR 数值。",
        "",
        "### 4.3 no_interval 的两类来源",
        "",
        "- **T6-risk_level（序数）5 个 cv run**：预测为风险带字符串标签，无数值残差可池化",
        "  （training_real.py 对 ordinal 显式跳过 conformal），bundle.intervals=None、cal_n=0、coverage=None。",
        "  这是设计使然，但门禁表相应行为 NA；**该任务族没有任何区间/覆盖率证据**。",
        "- **8 个 UNMAPPED frozen run**（T5-chla 与 T6-risk_level 的 T+1/3/7/15）：无模型文件，",
        "  无从抽取区间；其中 T5-chla 4 个 run 的 cov=0.0（test_n=1）。",
        "",
    ]
    MD_PATH.write_text("\n".join(L), encoding="utf-8")
    return {"n_runs": len(recs), "counts": counts}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1))
