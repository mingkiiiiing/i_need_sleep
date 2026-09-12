# -*- coding: utf-8 -*-
"""T3b bug3（chla 双单位混用，L-data-05）修复前后对照（20260912）。

同一进程内以 monkeypatch 复现旧口径（chla 原值直通聚合），与修复口径
（mg/L×1000 → μg/L 统一）各构建一次监督底表，对比：
  1) 野外月标签值（IN_SITU_GROUP / S1）；
  2) chla 代理锚点（2020-12 航次均值）与代理参数；
  3) T1-bloom mo0 监督表阳性数（按 train/validation/test）；
  4) T5-chla mo0 actual 分布与 validation 值域；
  5) T6-risk_level mo0 风险带分布（训练段类别支持）。
输出 JSON 到 experiments_r1/dryrun/t3b_chla_unit_fix_check_20260912.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]
CODE_DIR = PKG_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import modeling_real.target_builder as tb  # noqa: E402
from modeling_real.contracts_real import task_spec_real  # noqa: E402
from modeling_real.target_builder import LABEL_FAMILY_COLUMNS  # noqa: E402


def supervised_table(base, labels, task_id, variant, offset=0):
    spec = task_spec_real(task_id, variant)
    return tb.build_supervised_table(base, labels, spec, offset)


def split_positives(table: pd.DataFrame) -> dict:
    out = {}
    for split in ("train", "validation", "test"):
        sub = table.loc[table["dataset_split_frozen"] == split, "actual"]
        out[split] = {
            "rows": int(len(sub)),
            "positives": int((pd.to_numeric(sub, errors="coerce") == 1).sum()),
        }
    return out


def panel_stats(base, labels) -> dict:
    t1 = supervised_table(base, labels, "T1", "bloom")
    t5 = supervised_table(base, labels, "T5", "chla")
    t6 = supervised_table(base, labels, "T6", "risk_level")
    chla = pd.to_numeric(t5["actual"], errors="coerce")
    return {
        "t1_bloom_mo0_positives_by_split": split_positives(t1),
        "t5_chla_mo0_actual": {
            "rows": int(len(chla)),
            "min": float(chla.min()), "mean": float(chla.mean()), "max": float(chla.max()),
            "nunique": int(chla.nunique()),
            "validation_values": sorted(set(
                pd.to_numeric(
                    t5.loc[t5["dataset_split_frozen"] == "validation", "actual"],
                    errors="coerce",
                ).dropna().tolist()
            )),
        },
        "t6_risk_band_counts": {str(k): int(v) for k, v in t6["actual"].value_counts().items()},
        "t6_train_band_counts": {
            str(k): int(v)
            for k, v in t6.loc[t6["dataset_split_frozen"] == "train", "actual"]
            .value_counts().items()
        },
    }


def field_label_rows(labels: pd.DataFrame) -> dict:
    sub = labels[labels["station_id"].isin(tb.FIELD_STATIONS)][
        ["station_id", "month", "label_chla_ug_l"]
    ].dropna()
    return {f"{r.station_id}|{r.month}": round(float(r.label_chla_ug_l), 6) for r in sub.itertuples()}


def main() -> int:
    # 旧口径：chla 原值直通（复现 L-data-05 污染路径）
    original_normalizer = tb._normalize_chla_units
    tb._normalize_chla_units = lambda wq: (wq, {"disabled": "legacy_passthrough_for_comparison"})
    try:
        base_old, labels_old = tb.build_supervised_base()
    finally:
        tb._normalize_chla_units = original_normalizer
    # 修复口径：mg/L×1000 统一到 μg/L
    base_new, labels_new = tb.build_supervised_base()

    proxy_old = base_old.attrs.get("chla_proxy_params", {})
    proxy_new = base_new.attrs.get("chla_proxy_params", {})
    payload = {
        "check": "T3b bug3 chla unit normalization before/after (L-data-05)",
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "old_labels_field_rows": field_label_rows(labels_old),
        "new_labels_field_rows": field_label_rows(labels_new),
        "chla_proxy_anchor": {
            "old": proxy_old.get("anchor"),
            "new": proxy_new.get("anchor"),
            "old_a": proxy_old.get("a"),
            "new_a": proxy_new.get("a"),
            "old_sigma_ln": proxy_old.get("sigma_ln"),
            "new_sigma_ln": proxy_new.get("sigma_ln"),
        },
        "panel_old": panel_stats(base_old, labels_old),
        "panel_new": panel_stats(base_new, labels_new),
    }
    out = HERE / "dryrun" / "t3b_chla_unit_fix_check_20260912.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps({
        "field_rows_old": payload["old_labels_field_rows"],
        "field_rows_new": payload["new_labels_field_rows"],
        "anchor_old_mean_ug_l": (proxy_old.get("anchor") or {}).get("chla_mean_ug_l"),
        "anchor_new_mean_ug_l": (proxy_new.get("anchor") or {}).get("chla_mean_ug_l"),
        "t1_positives_old": payload["panel_old"]["t1_bloom_mo0_positives_by_split"],
        "t1_positives_new": payload["panel_new"]["t1_bloom_mo0_positives_by_split"],
        "t5_mean_old": payload["panel_old"]["t5_chla_mo0_actual"]["mean"],
        "t5_mean_new": payload["panel_new"]["t5_chla_mo0_actual"]["mean"],
        "t6_train_bands_old": payload["panel_old"]["t6_train_band_counts"],
        "t6_train_bands_new": payload["panel_new"]["t6_train_band_counts"],
        "out": str(out),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
