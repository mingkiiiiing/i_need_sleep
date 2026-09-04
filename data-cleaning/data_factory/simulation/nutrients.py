"""营养盐与 DO/pH/浊度 (设计 §6.7).

X(t+1)=X(t)+Load+Release−Uptake−Settling−Outflow+ε，向拟合月度气候态弱恢复（防随机游走漂移）；
Uptake 用前一日生物量（避免循环依赖）；DO 由饱和值/光合/呼吸/复氧平衡。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

SEASON_OF_MONTH = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}


def _clip_with_hits(values: np.ndarray, low: float, high: float, hits: dict[str, int], key: str) -> np.ndarray:
    """DG-005：钳位前统计越界命中（pre-clip bound hits），暴露物理失稳。"""
    hits[key] = int(((values < low) | (values > high)).sum())
    return np.clip(values, low, high)


def _monthly_target(dates: pd.DatetimeIndex, lookup, family: str, variable: str, zone_code: str, fallback: float) -> np.ndarray:
    values = np.empty(len(dates))
    for i, date in enumerate(dates):
        mu, _ = lookup(family, "lognorm_mu", f"{zone_code}-m{int(date.month):02d}")
        values[i] = float(mu) if mu is not None and mu > 0 else fallback
    return np.exp(values)


def simulate_nutrients(
    dates: pd.DatetimeIndex,
    tw: np.ndarray,
    ws: np.ndarray,
    rad: np.ndarray,
    precip: np.ndarray,
    biomass_prev: np.ndarray,
    growth_rate_prev: np.ndarray,
    depth_m: np.ndarray,
    zone_code: str,
    lookup,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    scenario: dict[str, Any],
) -> dict[str, np.ndarray]:
    T, N = tw.shape
    cfg = mechanism.get("nutrients", {})
    rng = rngs["nutrients"]
    depth = np.maximum(depth_m, 0.5)
    load_multiplier = float(scenario.get("load_multiplier", 1.0))
    storm_multiplier = float((scenario.get("extremes") or {}).get("load_pulse_multiplier", cfg.get("storm_load_multiplier", 3.0)))

    months = np.array([SEASON_OF_MONTH[m] for m in dates.month])

    def season_load(key: str) -> np.ndarray:
        base = np.array([float(cfg.get(key, {}).get(s, 0.1)) for s in months])
        precip_day = precip.mean(axis=1) if precip.ndim == 2 else precip
        wet_factor = np.where(precip_day > 10.0, float(cfg.get("wet_day_load_multiplier", 2.0)), 1.0)
        storm_factor = np.where(precip_day > 100.0, storm_multiplier, 1.0)
        return base * load_multiplier * wet_factor * storm_factor

    relax = float(cfg.get("relax_strength_per_day", 0.05))
    settle_tp = float(cfg.get("settling_tp_per_day", 0.02))
    settle_tn = float(cfg.get("settling_tn_per_day", 0.01))
    outflow = float(cfg.get("outflow_frac_per_day", 0.01))
    theta = float(cfg.get("release_theta", 1.07))
    release_tp = float(cfg.get("release_tp_per_day", 0.004))
    release_tn = float(cfg.get("release_tn_per_day", 0.03))
    uptake_tp = float(cfg.get("uptake_tp_ratio", 0.004))
    uptake_tn = float(cfg.get("uptake_tn_ratio", 0.04))
    # DG-005：摄取量按实际净同化计（Logistic 容量抑制），不得用潜在生长×生物量——
    # 旧口径在低生物量期产生过量净输入，把 TN 顶到物理上界
    algae_cfg = mechanism.get("algae", {})
    carry_cap = float(algae_cfg.get("K_base_mg_l", 60.0)) * float((algae_cfg.get("K_zone_scale") or {}).get(zone_code, 1.0))

    def _net_growth(gr: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.maximum(gr, 0.0) * b * np.maximum(1.0 - b / carry_cap, 0.0)

    target_tp = _monthly_target(dates, lookup, "nutrients", "total_phosphorus", zone_code, np.log(0.10))
    target_tn = _monthly_target(dates, lookup, "nutrients", "total_nitrogen", zone_code, np.log(1.8))
    tp = np.empty((T, N))
    tn = np.empty((T, N))
    tp[0] = target_tp[0] * np.exp(rng.normal(0.0, 0.10, N))
    tn[0] = target_tn[0] * np.exp(rng.normal(0.0, 0.08, N))
    for t in range(1, T):
        load_tp = season_load("load_tp_g_m2_day")[t] / depth[t]
        load_tn = season_load("load_tn_g_m2_day")[t] / depth[t]
        temp_factor = theta ** (tw[t] - 20.0)
        net_prev = _net_growth(growth_rate_prev[t - 1], biomass_prev[t - 1])
        uptake_p = uptake_tp * net_prev
        uptake_n = uptake_tn * net_prev
        tp[t] = (
            tp[t - 1] * (1 - settle_tp - outflow)
            + load_tp
            + release_tp * temp_factor / depth[t]
            - uptake_p
            + relax * (target_tp[t] - tp[t - 1])
            + tp[t - 1] * rng.normal(0.0, 0.03, N)
        )
        tn[t] = (
            tn[t - 1] * (1 - settle_tn - outflow)
            + load_tn
            + release_tn * temp_factor / depth[t]
            - uptake_n
            + relax * (target_tn[t] - tn[t - 1])
            + tn[t - 1] * rng.normal(0.0, 0.025, N)
        )
    bound_hits: dict[str, int] = {}
    tp = _clip_with_hits(tp, 0.005, 2.0, bound_hits, "total_phosphorus")
    tn = _clip_with_hits(tn, 0.1, 12.0, bound_hits, "total_nitrogen")

    nh4 = _clip_with_hits(tn * float(cfg.get("nh4_frac_of_tn", 0.25)) * np.exp(rng.normal(-0.1, 0.15, (T, N))), 0.005, 5.0, bound_hits, "ammonia_nitrogen")
    po4 = _clip_with_hits(tp * float(cfg.get("po4_frac_of_tp", 0.45)), 0.002, 1.0, bound_hits, "phosphate_phosphorus")
    no3 = _clip_with_hits(tn * float(cfg.get("no3_frac_of_tn", 0.45)), 0.01, 10.0, bound_hits, "nitrate_nitrogen")
    no2 = _clip_with_hits(tn * float(cfg.get("no2_frac_of_tn", 0.03)), 0.001, 1.0, bound_hits, "nitrite_nitrogen")

    # DO：饱和 + 复氧 + 光合产氧 − 呼吸/底泥
    do_cfg = cfg.get("do", {})
    sat = 14.62 - 0.32 * tw + 0.0037 * tw**2  # 淡水近似饱和溶解氧
    do = np.empty((T, N))
    do[0] = sat[0] * 0.9
    reaer = float(do_cfg.get("reaeration_per_day", 0.30))
    photo_max = float(do_cfg.get("photosynthetic_max_mg_l_day", 3.0))
    resp = float(do_cfg.get("respiration_per_day", 0.08))
    sediment = float(do_cfg.get("sediment_per_day", 0.05))
    for t in range(1, T):
        production = photo_max * np.clip(rad[t] / 20.0, 0.0, 1.5) * np.clip(biomass_prev[t - 1] / 10.0, 0.0, 1.5) / max(np.mean(depth), 1.0)
        consumption = (resp * np.clip(tw[t] / 30.0, 0.2, 1.5) * np.clip(biomass_prev[t - 1], 0.0, None) + sediment * np.clip(tw[t] / 25.0, 0.0, 2.0))
        do[t] = do[t - 1] + reaer * (sat[t] - do[t - 1]) + production - consumption + rng.normal(0.0, 0.15, N)
    do = _clip_with_hits(do, 0.0, 20.0, bound_hits, "dissolved_oxygen")

    ph_cfg = cfg.get("ph", {})
    ph = _clip_with_hits(
        float(ph_cfg.get("base", 7.9)) + float(ph_cfg.get("bloom_amplitude", 0.6)) * np.clip(biomass_prev / 40.0, 0.0, 1.2) + rng.normal(0.0, 0.05, (T, N)),
        6.0,
        9.5,
        bound_hits,
        "pH",
    )
    turb_cfg = cfg.get("turbidity", {})
    turbidity = _clip_with_hits(
        float(turb_cfg.get("wind_resuspension_ntu", 12.0)) * np.clip(ws / 6.0, 0.0, 2.5)
        + float(turb_cfg.get("bloom_contribution_ntu", 8.0)) * np.clip(biomass_prev / 40.0, 0.0, 2.0)
        + rng.normal(0.0, 3.0, (T, N)),
        1.0,
        200.0,
        bound_hits,
        "turbidity",
    )
    sdd = _clip_with_hits(float(cfg.get("sdd_m_base", 0.45)) / (1.0 + 0.03 * turbidity), 0.05, 2.5, bound_hits, "secchi_depth")
    cod = _clip_with_hits(float(cfg.get("cod_mn_per_biomass", 4.0)) * 0.5 + biomass_prev * 0.15 + rng.normal(0.0, 0.5, (T, N)), 0.5, 40.0, bound_hits, "cod_mn")

    return {
        "total_phosphorus": tp,
        "total_nitrogen": tn,
        "ammonia_nitrogen": nh4,
        "phosphate_phosphorus": po4,
        "nitrate_nitrogen": no3,
        "nitrite_nitrogen": no2,
        "dissolved_oxygen": do,
        "pH": ph,
        "turbidity": turbidity,
        "secchi_depth": sdd,
        "cod_mn": cod,
        "_bound_hits": bound_hits,
    }
