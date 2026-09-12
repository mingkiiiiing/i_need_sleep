# -*- coding: utf-8 -*-
"""T3b 修复后 T5-chla / T6-risk_level 训练期内时间分块补充面板（20260912）。

为什么需要本面板：bug3（chla 双单位）修复后，T5/T6 冻结表的 test 段仍只有
2026-08 S1 一行（n_test=1 < 15 → NA），冻结口径下没有可判定的测试段。
口径冻结 F4.3 规定：标签全在训练期的任务（T5/T6-risk_level 现状）以补训协议
train_internal_time_block_cv_v1（60/20/20 月份时序块，无前视）的留出块为权威
窗口。runner 的 cmd_retrain 仅在 validation<5 时才自动回退该协议，而 T5/T6
冻结表 validation 恰有 31 行（2022-12/2023-10 野外航次月）→ 不触发回退。
本脚本直接复用 ablation_runner 的 _apply_internal_time_block 与
run_ablation_on_table，对同一修复后监督表强制时间分块，行结构与 runner 一致，
evidence_source=retrain_draft（draft，不是门禁证据）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]
CODE_DIR = PKG_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from ablation_runner import (  # noqa: E402
    ABLATION_ARMS,
    OPTIONAL_FUSION,
    REFERENCE_BASELINES,
    _apply_internal_time_block,
    _task_feature_columns,
    _utc_now,
    run_ablation_on_table,
)
from modeling_real.contracts_real import (  # noqa: E402
    DEFAULT_SEED_V3,
    HORIZON_MAP_V3,
    TASK_SPECS_REAL,
    task_spec_real,
)
from modeling_real.target_builder import build_supervised_base  # noqa: E402


def main() -> int:
    seed = DEFAULT_SEED_V3
    base, labels = build_supervised_base()
    groups, all_rows = [], []
    for task_id, variant in (("T5", "chla"), ("T6", "risk_level")):
        spec = next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)
        from modeling_real.target_builder import LABEL_FAMILY_COLUMNS

        column = LABEL_FAMILY_COLUMNS[spec.label_family]
        table = base.dropna(subset=[column]).copy()
        # 与 build_supervised_table mo=0 同口径：actual = 同行标签
        import pandas as pd

        table["actual"] = pd.to_numeric(table[column], errors="coerce")
        if spec.problem_type == "ordinal":
            from modeling_real.target_builder import risk_band

            table["actual"] = risk_band(table["actual"]).astype("object")
        table = table.dropna(subset=["actual"])
        table, split_info = _apply_internal_time_block(table, "month")
        feats = _task_feature_columns(table, spec)
        from ablation_runner import candidate_factories_real

        probe = candidate_factories_real(spec, seed)
        fams = tuple(f for f in (*ABLATION_ARMS, *OPTIONAL_FUSION, *REFERENCE_BASELINES) if f in probe)
        result = run_ablation_on_table(
            spec, table, feats, seed, fams, horizon_days=1,
            evidence_source="retrain_draft", climatology_history=None,
        )
        result["meta"]["split_info"] = split_info
        result["meta"]["panel_note"] = (
            "bug3 修复后标签；时间分块留出段为权威窗口（F4.3），非 2024+ 冻结测试段"
        )
        groups.append(result)
        all_rows.extend(result["rows"])

    payload = {
        "runner": "T3b_retrain_post_fix_panels_20260912.py (reuses ablation_runner internals)",
        "mode": "retrain_draft_time_block",
        "generated_at": _utc_now(),
        "seed": int(seed),
        "task_variants": [["T5", "chla"], ["T6", "risk_level"]],
        "summary": {
            "rows": len(all_rows),
            "status_counts": {
                k: sum(1 for r in all_rows if r["status_vs_threshold"] == k)
                for k in sorted({r["status_vs_threshold"] for r in all_rows})
            },
        },
        "groups": groups,
        "rows": all_rows,
        "honesty_note": (
            "draft：修复后标签 + 训练期内时间分块（无前视），不是 2024+ 冻结测试段证据；"
            "T5/T6 标签仍以 chla_station_proxy_v1 代理为主（provenance 见 run_config），"
            "不得表述为真实未来目标。"
        ),
    }
    out = HERE / "ablation_retrain_T5_T6_timeblock_postfix_draft_20260912.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[postfix timeblock] rows={len(all_rows)} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
