"""藻类生长与表层聚集 (设计 §6.8).

dB/dt = μmax·fT·fN·fP·fI·B·(1−B/K) − (resp+mort+grazing)·B + ε；
静风时表层聚集增强；chla=色素比×表层生物量，藻密度=生物量/细胞质量换算。
输运（transport）在生物量步之后、光学推导之前施加。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def growth_factors(tw: np.ndarray, tn: np.ndarray, tp: np.ndarray, rad: np.ndarray, algae_cfg: dict[str, Any]) -> dict[str, np.ndarray]:
    topt = float(algae_cfg.get("Topt_c", 28.0))
    sigma_t = float(algae_cfg.get("sigma_t_c", 7.0))
    kn = float(algae_cfg.get("KN_mg_l", 0.20))
    kp = float(algae_cfg.get("KP_mg_l", 0.02))
    iopt = float(algae_cfg.get("Iopt_mj_m2_day", 14.0))
    ft = np.exp(-(((tw - topt) / sigma_t) ** 2))
    fn = tn / (kn + tn)
    fp = tp / (kp + tp)
    light = np.maximum(rad, 0.0) / iopt
    fi = light * np.exp(1.0 - np.clip(light, 0.0, None))
    fi = np.clip(fi, 0.0, 1.0)
    return {"fT": ft, "fN": fn, "fP": fp, "fI": fi}


def resolve_pigment_ratio(lookup, mechanism: dict[str, Any]) -> float:
    cfg = mechanism.get("algae", {})
    prior_ratio = float(cfg.get("pigment_ratio_base", 0.005))
    value, _ = lookup("algae", "pigment_ratio_ug_per_mg")
    if value is not None and 0.05 <= float(value) <= 60.0:
        return float(value)
    return prior_ratio


def simulate_biomass(
    dates: pd.DatetimeIndex,
    tw: np.ndarray,
    ws: np.ndarray,
    rad: np.ndarray,
    nutrients: dict[str, np.ndarray],
    lookup,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    scenario: dict[str, Any],
    zone_code: str = "",
) -> dict[str, np.ndarray]:
    T, N = tw.shape
    cfg = mechanism.get("algae", {})
    rng = rngs["algae"]

    mu_max = float(cfg.get("mu_max_per_day", 0.35))
    resp = float(cfg.get("resp_per_day", 0.08))
    mort = float(cfg.get("mort_per_day", 0.03))
    grazing = float(cfg.get("grazing_per_day", 0.02))
    k_base = float(cfg.get("K_base_mg_l", 60.0))
    zone_scale = float((cfg.get("K_zone_scale") or {}).get(zone_code, 1.0))
    carry_cap = k_base * zone_scale
    eps = float(cfg.get("eps_sigma_rel", 0.06))
    calm_wind = float(cfg.get("calm_wind_ms", 3.0))
    aggregation_gain = float(cfg.get("aggregation_gain", 1.5))
    biomass_cap = float(mechanism.get("physical_bounds", {}).get("phytoplankton_biomass", [0, 200])[1])

    tn = nutrients["total_nitrogen"]
    tp = nutrients["total_phosphorus"]
    factors = growth_factors(tw, tn, tp, rad, cfg)
    net_max = mu_max * factors["fT"] * factors["fN"] * factors["fP"] * factors["fI"]
    loss = resp * np.clip(tw / 25.0, 0.3, 1.6) + mort + grazing

    biomass = np.empty((T, N))
    biomass[0] = carry_cap * 0.08 * np.exp(rng.normal(0.0, 0.25, N))
    growth_rate = np.zeros((T, N))
    growth_rate[0] = net_max[0]
    bound_hits = {"phytoplankton_biomass": 0, "surface_biomass": 0}
    for t in range(1, T):
        mu_eff = net_max[t]
        growth_rate[t] = mu_eff
        db = mu_eff * biomass[t - 1] * np.maximum(1.0 - biomass[t - 1] / carry_cap, 0.0) - loss[t] * biomass[t - 1]
        new = biomass[t - 1] + db + biomass[t - 1] * rng.normal(0.0, eps, N)
        bound_hits["phytoplankton_biomass"] += int(((new <= 0.0) | (new > carry_cap)).sum())
        biomass[t] = np.clip(new, 0.01, carry_cap)

    # 表层聚集：静风增强 (设计 §6.8 低风速聚集风险)
    aggregation = 1.0 + aggregation_gain * np.clip(1.0 - ws / calm_wind, 0.0, 1.0)
    aggregated = biomass * aggregation
    bound_hits["surface_biomass"] = int((aggregated > biomass_cap).sum())
    surface_biomass = np.clip(aggregated, 0.0, biomass_cap)

    return {
        "phytoplankton_biomass": biomass,
        "surface_biomass": surface_biomass,
        "growth_rate": growth_rate,
        "_diagnostics": {"clamp_count": bound_hits["phytoplankton_biomass"], "carry_cap_mg_l": carry_cap},
        "_bound_hits": bound_hits,
    }


def derive_chla_density(
    surface_biomass: np.ndarray,
    pigment_ratio: float,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
) -> dict[str, np.ndarray]:
    cfg = mechanism.get("algae", {})
    rng = rngs["algae"]
    composition = float(cfg.get("composition_factor", 0.8))
    non_cyano = float(cfg.get("non_cyano_chla_ug_l", 4.0))
    cell_mass = float(cfg.get("cell_mass_ug_per_cell", 0.05))
    chla_cap = float(mechanism.get("physical_bounds", {}).get("chlorophyll_a", [0, 2000])[1])

    chla_raw = (non_cyano + pigment_ratio * composition * surface_biomass) * np.exp(rng.normal(0.0, 0.08, surface_biomass.shape))
    bound_hits = {"chlorophyll_a": int(((chla_raw < 0.1) | (chla_raw > chla_cap)).sum())}
    chla = np.clip(chla_raw, 0.1, chla_cap)
    # 万cells/L：mg/L → µg/L（×1000）→ 细胞数（/cell_mass µg）→ 万cells/L（/1e4）；
    # 乘性噪声（DG-005）：加性噪声在冬季低生物量期大量取负→钳 0，掩盖真实低密度信号
    density_raw = surface_biomass * 1000.0 * composition / cell_mass / 1.0e4 * np.exp(rng.normal(0.0, 0.10, surface_biomass.shape))
    bound_hits["cyanobacteria_density"] = int((density_raw < 0.0).sum())
    density = np.clip(density_raw, 0.0, None)
    return {"chlorophyll_a": chla, "cyanobacteria_density": density, "_bound_hits": bound_hits}
