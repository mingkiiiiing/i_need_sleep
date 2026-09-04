"""冻结阈值与标签三态规则 (设计 §6.13/§10).

frozen=true：正/负判定只依赖 threshold_set_id 对应 YAML；缺证据一律 unknown。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def load_thresholds(thresholds: dict[str, Any]) -> dict[str, Any]:
    if not thresholds.get("frozen", False):
        raise SystemExit("label_thresholds.yaml frozen must be true (设计 §10)")
    bloom = thresholds.get("bloom", {})
    chla = thresholds.get("chla_ug_l", {})
    return {
        "threshold_set_id": thresholds["threshold_set_id"],
        "grid_fraction_positive": float(bloom.get("grid_fraction_positive", 0.05)),
        "zone_area_km2_positive": float(bloom.get("zone_area_km2_positive", 1.0)),
        "lake_area_km2_positive": float(bloom.get("lake_area_km2_positive", 10.0)),
        "satellite_detection_min_fraction": float(bloom.get("satellite_detection_min_fraction", 0.02)),
        "chla_warning": float(chla.get("warning", 30.0)),
        "chla_alert": float(chla.get("alert", 60.0)),
    }


def bloom_binary(area_km2: float | np.ndarray, spatial_level: str, th: dict[str, Any]) -> np.ndarray:
    key = {"grid": "grid_fraction_positive", "zone": "zone_area_km2_positive", "lake": "lake_area_km2_positive"}[spatial_level]
    # grid 级输入是覆盖率（0-1），zone/lake 级输入是面积 km²
    if spatial_level == "grid":
        return (np.asarray(area_km2, dtype=float) >= th[key]).astype(int)
    return (np.asarray(area_km2, dtype=float) >= th[key]).astype(int)


def risk_level_series(chla: np.ndarray, bloom_fraction: np.ndarray) -> np.ndarray:
    """风险等级 0–3：持续窗口基于 zone 覆盖率（label_thresholds risk_levels 规则）。"""

    chla = np.asarray(chla, dtype=float)
    frac = np.asarray(bloom_fraction, dtype=float)
    above_warn = chla >= 30.0
    above_alert = chla >= 60.0

    def run_length(mask: np.ndarray, window: int) -> np.ndarray:
        out = np.zeros(len(mask), dtype=bool)
        run = 0
        for i, flag in enumerate(mask):
            run = run + 1 if flag else 0
            out[i] = run >= window
        return out

    persist3 = run_length(frac >= 0.05, 3)
    persist7 = run_length(frac >= 0.05, 7)
    level = np.zeros(len(chla), dtype=int)
    level[above_warn | (frac >= 0.05)] = 1
    level[above_alert & persist3] = 2
    level[above_alert & persist7] = 3
    return level


def satellite_bloom_label(
    chla_values: np.ndarray | pd.Series,
    th: dict[str, Any],
) -> int | None:
    """单日卫星反演 → 湖区水华二值标签；无有效值返回 None（unknown）。"""

    values = np.asarray(chla_values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return None
    positive_cells = values >= th["chla_warning"]
    if positive_cells.mean() >= th["grid_fraction_positive"]:
        return 1
    if positive_cells.mean() >= th["satellite_detection_min_fraction"]:
        return 1
    return 0
