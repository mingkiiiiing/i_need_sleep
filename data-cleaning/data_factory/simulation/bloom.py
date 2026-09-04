"""水华覆盖率与面积 (设计 §6.10).

sigmoid(f(B_surf, 静风, 水温, 持续性, 岸边)) → 网格覆盖率；面积=覆盖率×有效水面。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from data_factory.contracts.spatial import cell_indices

_EPS = 1e-6


def _shore_index(grid_metadata: pd.DataFrame) -> np.ndarray:
    ix, iy = cell_indices(grid_metadata["grid_id"])
    pos = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(ix, iy))}
    shore = np.zeros(len(grid_metadata))
    for i in range(len(grid_metadata)):
        n = sum((int(ix[i]) + dx, int(iy[i]) + dy) in pos for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        shore[i] = (4 - n) / 4.0
    return shore


def _persistence(surface_biomass: np.ndarray, window: int) -> np.ndarray:
    """过去 window 日内表层生物量高于自身滚动中位数的比例，前 window-1 日用可用窗口。"""
    T, N = surface_biomass.shape
    out = np.zeros((T, N))
    for t in range(T):
        lo = max(0, t - window + 1)
        seg = surface_biomass[lo : t + 1]
        median = np.median(seg, axis=0)
        out[t] = (seg > median).mean(axis=0)
    return out


def simulate_bloom_fraction(
    surface_biomass: np.ndarray,
    tw: np.ndarray,
    ws: np.ndarray,
    effective_area_m2: np.ndarray,
    grid_metadata: pd.DataFrame,
    mechanism: dict[str, Any],
) -> dict[str, np.ndarray]:
    cfg = mechanism.get("bloom", {})
    calm_wind = float(mechanism.get("algae", {}).get("calm_wind_ms", 3.0))

    a0 = float(cfg.get("a0", -3.0))
    a1 = float(cfg.get("a1", 0.9))
    a2 = float(cfg.get("a2", 0.5))
    a3 = float(cfg.get("a3", 0.06))
    a4 = float(cfg.get("a4", 0.5))
    a5 = float(cfg.get("a5", 0.3))
    window = int(cfg.get("persistence_days", 7))

    log_b = np.log(surface_biomass + _EPS)
    calm = np.clip(1.0 - ws / calm_wind, 0.0, 1.0)
    persist = _persistence(surface_biomass, window)
    shore = _shore_index(grid_metadata)[None, :]

    logit = a0 + a1 * log_b + a2 * calm + a3 * tw + a4 * persist + a5 * shore
    fraction = 1.0 / (1.0 + np.exp(-np.clip(logit, -30.0, 30.0)))
    fraction = np.clip(fraction, 0.0, 1.0)

    area_km2 = fraction * effective_area_m2[None, :] / 1.0e6
    return {"bloom_fraction": fraction, "bloom_area_grid_km2": area_km2, "logit": logit}


def aggregate_bloom(
    dates: pd.DatetimeIndex,
    bloom_fraction: np.ndarray,
    bloom_area_grid_km2: np.ndarray,
    effective_area_m2: np.ndarray,
    zone_of_cell: np.ndarray,
    frozen_lake_area_km2: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按网格→湖区聚合。返回 (bloom_lake_daily, zone_daily) 两张表。

    DG-001：本仿真只覆盖部分湖区时，lake 行必须显式携带 domain_coverage_*
    （仿真有效面积 / 冻结全湖面积），禁止把部分域冒充全湖。"""
    T, N = bloom_fraction.shape
    lake_total_area = float(effective_area_m2.sum()) / 1.0e6
    coverage = 1.0 if not frozen_lake_area_km2 else min(lake_total_area / float(frozen_lake_area_km2), 1.0)
    is_partial = coverage < 0.9999
    records = []
    zone_records = []
    zones = sorted(set(zone_of_cell.tolist()))
    for t, date in enumerate(dates):
        lake_area = float(bloom_area_grid_km2[t].sum())
        records.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "bloom_area_km2": round(lake_area, 6),
                "lake_area_km2": round(lake_total_area, 6),
                "bloom_fraction_lake": round(lake_area / max(lake_total_area, _EPS), 6),
                "domain_coverage_km2": round(lake_total_area, 6),
                "domain_coverage_fraction": round(coverage, 6),
                "is_partial_domain": is_partial,
            }
        )
        for zone in zones:
            mask = zone_of_cell == zone
            z_area_cells = float(effective_area_m2[mask].sum()) / 1.0e6
            z_bloom = float(bloom_area_grid_km2[t][mask].sum())
            zone_records.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "zone_code": zone,
                    "bloom_area_km2": round(z_bloom, 6),
                    "zone_area_km2": round(z_area_cells, 6),
                    "bloom_fraction_zone": round(z_bloom / max(z_area_cells, _EPS), 6),
                    "mean_fraction": round(float(bloom_fraction[t][mask].mean()), 6),
                    "domain_coverage_km2": round(z_area_cells, 6),
                    "domain_coverage_fraction": 1.0,
                    "is_partial_domain": False,
                }
            )
    return pd.DataFrame(records), pd.DataFrame(zone_records)
