"""湖泊物理状态：水温 + 水量平衡 (设计 §6.5/§6.6).

水温 AR 方程 Tw(t)=Tw(t-1)+k1(Ta-Tw)+k2·Rad-k3·WindMix-k4·Depth+ε，速率限制与范围钳位；
水位 AR(1) + 降雨响应核（滞后 1–3 日）+ 蒸发；输出均已记录钳位计数。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def simulate_water_temperature(
    dates: pd.DatetimeIndex,
    ta_grid: np.ndarray,
    rad_grid: np.ndarray,
    ws_grid: np.ndarray,
    depth_m: np.ndarray,
    lookup,
    mechanism: dict[str, Any],
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, int]]:
    T, N = ta_grid.shape
    k1, _ = lookup("water_temp", "k1", None)
    k2, _ = lookup("water_temp", "k2", None)
    k3, _ = lookup("water_temp", "k3", None)
    k4, _ = lookup("water_temp", "k4", None)
    cfg = mechanism.get("water_temp", {})
    k1 = float(cfg.get("k1", 0.35)) if k1 is None else k1
    k2 = float(cfg.get("k2", 0.02)) if k2 is None else k2
    k3 = float(cfg.get("k3", 0.15)) if k3 is None else k3
    k4 = float(cfg.get("k4", 0.10)) if k4 is None else k4
    t_min = float(cfg.get("t_min_c", 0.0))
    t_max = float(cfg.get("t_max_c", 40.0))
    max_change = float(cfg.get("max_daily_change_c", 3.0))

    tw = np.empty((T, N))
    tw[0] = np.clip(ta_grid[0] * 0.8 + 2.0, t_min + 0.5, t_max)
    clamped_range = 0
    clamped_rate = 0
    depth_effect = k4 * (depth_m - float(np.mean(depth_m))) / max(float(np.mean(depth_m)), 0.5)
    for t in range(1, T):
        tendency = (
            k1 * (ta_grid[t] - tw[t - 1])
            + k2 * rad_grid[t]
            - k3 * ws_grid[t]
            - depth_effect
            + rng.normal(0.0, 0.15, N)
        )
        clamped_rate += int((np.abs(tendency) > max_change).sum())
        tw[t] = tw[t - 1] + np.clip(tendency, -max_change, max_change)
        over = (tw[t] < t_min) | (tw[t] > t_max)
        clamped_range += int(over.sum())
        tw[t] = np.clip(tw[t], t_min, t_max)
    return tw, {"range_clamps": clamped_range, "rate_clamps": clamped_rate}


def simulate_water_balance(
    dates: pd.DatetimeIndex,
    precip_lake: np.ndarray,
    lookup,
    mechanism: dict[str, Any],
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    T = len(dates)
    cfg = mechanism.get("hydrology", {})
    months = dates.month.to_numpy()
    level_mean_cfg = float(cfg.get("level_mean_m", 3.1))
    mean_row, _ = lookup("hydrology", "level_mean_m", None)
    level_mean = float(mean_row) if mean_row is not None else level_mean_cfg
    phi_cfg = float(cfg.get("level_ar_phi", 0.85))
    phi_row, _ = lookup("hydrology", "level_ar_phi", None)
    phi = float(phi_row) if phi_row is not None else phi_cfg
    sigma_row, _ = lookup("hydrology", "level_ar_sigma", None)
    sigma = float(sigma_row) if sigma_row is not None else 0.01
    resp_per_mm = float(cfg.get("rainfall_response_m_per_mm", 0.0004))
    lags = cfg.get("rainfall_response_lag_days", [1, 2, 3])
    weights = cfg.get("rainfall_response_weights", [0.5, 0.3, 0.2])
    amplitude = float(cfg.get("level_annual_amplitude_m", 0.35))

    seasonal = np.array([level_mean + amplitude * np.sin(2 * np.pi * (d - 105) / 365.25) for d in dates.dayofyear])
    level = np.empty(T)
    level[0] = seasonal[0]
    response = np.zeros(T)
    for lag, weight in zip(lags, weights):
        shifted = np.zeros(T)
        if lag < T:
            shifted[lag:] = precip_lake[:-lag] if lag else precip_lake
        response += weight * shifted
    response *= resp_per_mm
    for t in range(1, T):
        target = seasonal[t] + response[t]
        level[t] = phi * level[t - 1] + (1 - phi) * target + rng.normal(0.0, sigma)
    level = np.clip(level, 2.0, 5.0)
    depth_anomaly = level - level_mean
    return level, {"depth_anomaly": depth_anomaly, "level_mean": level_mean, "clamps": int(((level <= 2.0) | (level >= 5.0)).sum())}
