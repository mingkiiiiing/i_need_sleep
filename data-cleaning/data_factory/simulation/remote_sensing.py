"""观测层·卫星：真实过境日驱动 (设计 §6.1 两层世界 / §6.11).

仅在真实卫星过境日生成模拟反演（S2 指数 + MODIS chla）；
云遮日不产生有效行，缺失在 labeling 阶段落 unknown。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

S2_VARIABLES = ("ndci", "fai", "mci")
MODIS_VARIABLES = ("chla_retrieval",)


def _satellite_days(obs_pattern: pd.DataFrame, dates: pd.DatetimeIndex) -> dict[pd.Timestamp, dict[str, Any]]:
    """返回 {date: {"s2": {coverage, cloud}, "modis": {...}}}；无 pattern 时不产出过境。"""

    in_range = set(dates.date)
    days: dict[pd.Timestamp, dict[str, Any]] = {}
    if obs_pattern is None or obs_pattern.empty:
        return days
    for row in obs_pattern.itertuples():
        date = pd.Timestamp(row.date)
        if date.date() not in in_range:
            continue
        variable = str(row.source_variable)
        entry = days.setdefault(date, {})
        sensor = "modis" if variable in ("chlorophyll_a", "chla_retrieval") else "s2"
        info = entry.setdefault(sensor, {"coverage": None, "cloud": None})
        if variable in ("ndci", "fai"):
            # 同景多变量共享覆盖/云信息，任一非空即采用
            info["coverage"] = info["coverage"] if info["coverage"] is not None else getattr(row, "coverage_frac", None)
            info["cloud"] = info["cloud"] if info["cloud"] is not None else getattr(row, "cloud_ratio", None)
    return days


def build_satellite_observations(
    dates: pd.DatetimeIndex,
    chla_grid: np.ndarray,
    bloom_fraction: np.ndarray,
    grid_ids: list[str],
    obs_pattern: pd.DataFrame,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    meta: dict[str, Any],
) -> pd.DataFrame:
    cfg = mechanism.get("remote_sensing", {})
    rng = rngs["obs_spatial"]
    cloud_threshold = float(cfg.get("cloud_invalid_threshold", 0.70))
    delay_p50 = float(mechanism.get("obs", {}).get("publish_delay_p50_h", 6.0))
    delay_p90 = float(mechanism.get("obs", {}).get("publish_delay_p90_h", 24.0))

    date_index = {d.date(): i for i, d in enumerate(dates)}
    rows: list[dict[str, Any]] = []
    for date, sensors in _satellite_days(obs_pattern, dates).items():
        t = date_index[date.date()]
        day_chla = chla_grid[t]
        for sensor, info in sensors.items():
            cloud = info["cloud"]
            if cloud is None or pd.isna(cloud):
                cloud = float(np.clip(rng.beta(2.0, 3.0), 0.0, 1.0))
            coverage = info["coverage"]
            if coverage is None or pd.isna(coverage):
                coverage = float(rng.uniform(0.85, 1.0))
            if float(cloud) >= cloud_threshold:
                continue  # 云遮日：不产生有效观测行
            available_time = date + pd.Timedelta(hours=float(rng.uniform(delay_p50, max(delay_p90, delay_p50))))
            variables = S2_VARIABLES if sensor == "s2" else MODIS_VARIABLES
            for grid_i, grid_id in enumerate(grid_ids):
                chla = float(day_chla[grid_i])
                for variable in variables:
                    spec = cfg.get(variable, {})
                    if variable == "chla_retrieval":
                        value = float(spec.get("bias", 0.85)) * chla * float(np.exp(rng.normal(0.0, float(spec.get("noise_sigma_rel", 0.35)))))
                        unit = "ug/L"
                    else:
                        value = float(spec.get("base", 0.0)) + float(spec.get("per_chla_ug", 0.0005)) * chla + float(rng.normal(0.0, float(spec.get("noise_sigma", 0.01))))
                        unit = "unitless"
                    rows.append(
                        {
                            "grid_id": grid_id,
                            "observed_time": date,
                            "available_time": available_time,
                            "variable_code": variable,
                            "value": round(float(max(value, 0.0)), 6),
                            "unit": unit,
                            "coverage_ratio": round(float(coverage), 4),
                            "quality_flag": "pass",
                            "missing_reason": None,
                            "value_type": "simulated",
                            "is_ground_truth": False,
                            "is_synthetic": True,
                            "source_type": "remote_sensing",
                            "parent_record_ids": f"{meta['dataset_version']}|latent|{grid_id}|{date.date()}|chlorophyll_a",
                            "generator_version": meta["generator_version"],
                            "generation_batch_id": meta["generation_batch_id"],
                        }
                    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["observed_time"] = pd.to_datetime(frame["observed_time"])
    frame["available_time"] = pd.to_datetime(frame["available_time"])
    return frame
