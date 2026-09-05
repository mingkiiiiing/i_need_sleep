"""外源气象驱动 (设计 §6.4)：气候态 + 年际距平 + 天气过程 + 空间场 + 极端事件.

禁止正弦+白噪声：气候态为 2 阶调和拟合（NASA POWER 真实观测），过程项为 AR(1)
残差（保持连续性），降水为 Markov 发生过程 × Gamma 强度，空间偏差为相关随机场。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .rng import sample_field


def apply_heatwave(ta: np.ndarray, months: np.ndarray, extremes: dict[str, Any], rng: np.random.Generator) -> np.ndarray:
    """热浪情景：在情景月内按 P60 以上高温日挑起点，连续 heatwave_days 天加温（合成/重放驱动共用）。"""
    if not extremes.get("heatwave_days"):
        return ta
    months_pool = list(set(extremes.get("months", []) or []))
    candidates = np.where(np.isin(months, months_pool) & (ta > np.percentile(ta, 60)))[0]
    if len(candidates):
        start = int(rng.choice(candidates))
        ta[start : start + int(extremes["heatwave_days"])] += float(extremes.get("heatwave_add_deg", 4.0))
    return ta


def apply_calm_cap(ws: np.ndarray, months: np.ndarray, extremes: dict[str, Any]) -> np.ndarray:
    """静风情景：情景月内风速不超过上限（表层聚集条件）。"""
    calm_cap = extremes.get("calm_wind_ms")
    months_pool = list(set(extremes.get("months", []) or []))
    if calm_cap and months_pool:
        mask = np.isin(months, months_pool)
        ws[mask] = np.minimum(ws[mask], float(calm_cap))
    return ws


def apply_storm_pulse(precip: np.ndarray, months: np.ndarray, extremes: dict[str, Any], rng: np.random.Generator) -> np.ndarray:
    """暴雨情景：在情景月内随机挑 storm_days 天，日降水抬升至 storm_mm。"""
    storm_days = extremes.get("storm_days")
    if not storm_days:
        return precip
    candidates = np.where(np.isin(months, list(set(extremes.get("months", []) or []))))[0]
    if len(candidates):
        starts = rng.choice(candidates, size=min(int(storm_days), len(candidates)), replace=False)
        storm_mm = float(extremes.get("storm_mm", 150))
        for s in np.atleast_1d(starts):
            precip[s : s + 1] = np.maximum(precip[s : s + 1], storm_mm)
    return precip


def simulate_weather(
    dates: pd.DatetimeIndex,
    modes: np.ndarray,
    lookup,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    scenario: dict[str, Any],
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """返回 (逐格数组 dict, 湖区均值驱动表)。lookup(family, key, scope) -> (value, n)。"""

    T, N = len(dates), modes.shape[0]
    doy = dates.dayofyear.to_numpy().astype(float)
    months = dates.month.to_numpy()
    cfg = mechanism.get("weather", {})
    spatial_cfg = cfg.get("spatial_deviation", {})

    def clim_coef(variable: str) -> tuple[np.ndarray, float, float, float]:
        a0, _ = lookup("weather", "clim_a0", variable)
        s1, _ = lookup("weather", "clim_s1", variable)
        c1, _ = lookup("weather", "clim_c1", variable)
        s2, _ = lookup("weather", "clim_s2", variable)
        c2, _ = lookup("weather", "clim_c2", variable)
        omega = 2.0 * np.pi / 365.25
        base = np.full(T, a0 if a0 is not None else fallbacks[variable], dtype=float)
        base += (s1 or 0.0) * np.sin(omega * doy) + (c1 or 0.0) * np.cos(omega * doy)
        base += (s2 or 0.0) * np.sin(2 * omega * doy) + (c2 or 0.0) * np.cos(2 * omega * doy)
        phi, _ = lookup("weather", "ar_phi", variable)
        sigma, _ = lookup("weather", "ar_sigma", variable)
        year_sigma, _ = lookup("weather", "year_sigma", variable)
        return base, float(phi if phi is not None else 0.5), float(sigma if sigma is not None else 1.0), float(year_sigma or 0.0)

    fallbacks = {"air_temperature": 17.0, "wind_speed": 3.5, "shortwave_radiation": 14.0}
    rng = rngs["weather"]

    def ar_process(base: np.ndarray, phi: float, sigma: float) -> np.ndarray:
        residual = np.empty(T)
        residual[0] = 0.0
        innovation = rng.standard_normal(T) * sigma
        for t in range(1, T):
            residual[t] = phi * residual[t - 1] + innovation[t]
        return base + residual

    extremes = scenario.get("extremes") or {}

    # 气温：气候态 + 年际距平（全期常数） + 天气过程 + 热浪情景
    base, phi, sigma, year_sigma = clim_coef("air_temperature")
    year_anomaly = rng.normal(0.0, year_sigma) if year_sigma else 0.0
    year_anomaly += float(scenario.get("climate_shift_deg", 0.0))
    ta = ar_process(base + year_anomaly, phi, max(sigma, 0.5))
    ta = apply_heatwave(ta, months, extremes, rng)
    ta = np.clip(ta, -10.0, 45.0)

    # 风速：气候态 + AR(1)；静风情景上限
    base_w, phi_w, sigma_w, _ = clim_coef("wind_speed")
    ws = ar_process(base_w, phi_w, max(sigma_w, 0.3))
    ws = apply_calm_cap(ws, months, extremes)
    ws = np.clip(ws, 0.0, 25.0)
    wind_dir = np.degrees(np.cumsum(rng.normal(0.0, 12.0, T))) % 360.0

    # 辐射：气候态 + AR(1)，与云量弱耦合
    base_r, phi_r, sigma_r, _ = clim_coef("shortwave_radiation")
    rad = ar_process(base_r, phi_r, max(sigma_r, 0.8))
    rad = np.clip(rad, 0.5, 40.0)

    # 降水：Markov 发生 × Gamma 强度（月度参数）
    wet = np.zeros(T, dtype=bool)
    for m in range(1, 13):
        mask = months == m
        if not mask.any():
            continue
        p01, _ = lookup("weather", "p01", f"m{m:02d}")
        p11, _ = lookup("weather", "p11", f"m{m:02d}")
        p01 = 0.3 if p01 is None else p01
        p11 = 0.5 if p11 is None else p11
        states = np.empty(mask.sum(), dtype=int)
        states[0] = 1 if rng.random() < p01 else 0
        for i in range(1, mask.sum()):
            states[i] = 1 if rng.random() < (p11 if states[i - 1] else p01) else 0
        wet[mask] = states.astype(bool)
    precip = np.zeros(T)
    for m in range(1, 13):
        mask = (months == m) & wet
        if not mask.any():
            continue
        shape_p, _ = lookup("weather", "gamma_shape", f"m{m:02d}")
        scale_p, _ = lookup("weather", "gamma_scale", f"m{m:02d}")
        shape_p = 0.8 if shape_p is None else shape_p
        scale_p = 6.0 if scale_p is None else scale_p
        precip[mask] = rng.gamma(max(shape_p, 0.1), max(scale_p, 0.1), int(mask.sum()))
    precip = apply_storm_pulse(precip, months, extremes, rng)
    precip = np.clip(precip, 0.0, 400.0)

    # 湿度/云量：次级变量（与温度/降水自洽），写明简化
    hum_cfg = cfg.get("humidity", {})
    humidity = np.clip(
        float(hum_cfg.get("base_pct", 78)) - float(hum_cfg.get("temp_sensitivity_pct_per_c", 1.2)) * (ta - np.array([np.mean(ta[months == m]) if (months == m).any() else 17.0 for m in months])) + rng.normal(0.0, 5.0, T),
        20.0,
        100.0,
    )
    cloud_cfg = cfg.get("cloud", {})
    cloud_phi = float(cloud_cfg.get("phi", 0.6))
    cloud_mean = np.where(wet, float(cloud_cfg.get("wet_day_mean", 0.8)), float(cloud_cfg.get("dry_day_mean", 0.35)))
    cloud = np.empty(T)
    cloud[0] = cloud_mean[0]
    for t in range(1, T):
        cloud[t] = cloud_phi * cloud[t - 1] + (1 - cloud_phi) * cloud_mean[t] + rng.normal(0.0, 0.08)
    cloud = np.clip(cloud, 0.0, 1.0)

    # 空间偏差场（相关随机场，日间持续；场值截断 ±3，防止乘法距平越界成负温度/零辐射）
    def spatial(anomaly: np.ndarray, key: str, amp: float, phi_s: float, additive: bool = False) -> np.ndarray:
        field = np.empty((T, N))
        prev = None
        for t in range(T):
            prev = np.clip(sample_field(rng, modes, phi_s, prev), -3.0, 3.0)
            field[t] = anomaly[t] + amp * prev if additive else anomaly[t] * (1.0 + amp * prev)
        return field

    ta_grid = spatial(ta, "air_temperature", float(spatial_cfg.get("air_temperature", {}).get("amp_c", 1.5)), float(spatial_cfg.get("air_temperature", {}).get("phi", 0.8)), additive=True)
    ws_grid = spatial(ws, "wind_speed", float(spatial_cfg.get("wind_speed", {}).get("amp_rel", 0.2)), float(spatial_cfg.get("wind_speed", {}).get("phi", 0.7)))
    rad_grid = spatial(rad, "shortwave_radiation", float(spatial_cfg.get("shortwave_radiation", {}).get("amp_rel", 0.15)), float(spatial_cfg.get("shortwave_radiation", {}).get("phi", 0.7)))
    precip_multiplier = np.empty((T, N))
    prev_p = None
    amp_p = float(spatial_cfg.get("precipitation", {}).get("amp_rel", 0.6))
    phi_p = float(spatial_cfg.get("precipitation", {}).get("phi", 0.6))
    for t in range(T):
        prev_p = sample_field(rng, modes, phi_p, prev_p)
        factor = np.exp(amp_p * prev_p - amp_p**2 / 2)
        precip_multiplier[t] = precip[t] * factor
    precip_grid = np.clip(precip_multiplier, 0.0, None)
    humidity_grid = np.clip(humidity[:, None] + rng.normal(0.0, 3.0, (T, N)), 15.0, 100.0)
    cloud_grid = np.clip(cloud[:, None] + rng.normal(0.0, 0.1, (T, N)), 0.0, 1.0)

    arrays = {
        "air_temperature": ta_grid,
        "wind_speed": ws_grid,
        "wind_direction": np.repeat(wind_dir[:, None], N, axis=1),
        "shortwave_radiation": rad_grid,
        "precipitation": precip_grid,
        "relative_humidity": humidity_grid,
        "cloud_cover": cloud_grid,
    }
    lake_mean = pd.DataFrame(
        {
            "date": dates,
            "air_temperature": ta,
            "wind_speed": ws,
            "wind_direction": wind_dir,
            "shortwave_radiation": rad,
            "precipitation": precip,
            "relative_humidity": humidity,
            "cloud_cover": cloud,
            "wet_day": wet,
        }
    )
    return arrays, lake_mean
