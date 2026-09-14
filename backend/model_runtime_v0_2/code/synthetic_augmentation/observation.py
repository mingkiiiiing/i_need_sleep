"""Visible remote-sensing observation process for V0.3 synthetic targets.

Cloud and coverage depend only on same-day visible meteorology and an internal
within-block weather persistence process.  They never read latent event,
probability, future labels, or target magnitude when deciding observability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .targets import (
    CLAIM_BOUNDARY,
    KEY_COLUMNS,
    MIN_VALID_PIXEL_RATIO,
    _explicit_rng,
    _ordered_grid_frame,
    _same_ordered_keys,
)


_REMOTE_COLUMNS = (
    "remote_chlorophyll_a_ug_L", "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L", "remote_fai_proxy", "remote_ndci_proxy",
)


def _soft_positive(raw: np.ndarray, scale: float) -> np.ndarray:
    raw = np.asarray(raw, dtype=float)
    if not np.isfinite(raw).all() or (raw <= 0).any():
        raise ValueError("observation formula generated invalid raw values")
    values = scale * (-np.expm1(-raw / scale))
    return np.clip(values, np.nextafter(0.0, 1.0), np.nextafter(scale, 0.0))


def _visible_drivers(drivers) -> pd.DataFrame:
    required = ("relative_humidity_pct", "precipitation_mm_day", "solar_radiation_MJ_m2_day")
    frame = _ordered_grid_frame(drivers, required=required, context="drivers")
    for name in required:
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    values = frame.loc[:, list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (frame.precipitation_mm_day < 0).any() or (frame.solar_radiation_MJ_m2_day < 0).any() or ((frame.relative_humidity_pct < 0) | (frame.relative_humidity_pct > 100)).any():
        raise ValueError("drivers have invalid visible meteorology")
    return frame


def apply_observation_process(latent, drivers, rng, config, force_cloud=False) -> pd.DataFrame:
    """Apply independent measurement and weather-only coverage processes.

    The input truth is copied, never modified.  ``force_cloud`` exists only for
    deterministic QA and masks every remote measurement without altering truth.
    """
    rng = _explicit_rng(rng)
    if not isinstance(force_cloud, (bool, np.bool_)):
        raise ValueError("force_cloud must be a boolean")
    latent_required = (
        "chlorophyll_a_ug_L", "phycocyanin_ug_L", "cyanobacteria_density_cells_L",
        "blue_algae_biomass_mg_L", "latent_bloom_probability", "latent_bloom_event",
    )
    truth = _ordered_grid_frame(latent, required=latent_required, context="latent")
    for name in latent_required:
        truth[name] = pd.to_numeric(truth[name], errors="coerce")
    continuous = ("chlorophyll_a_ug_L", "phycocyanin_ug_L", "cyanobacteria_density_cells_L", "blue_algae_biomass_mg_L", "latent_bloom_probability")
    if not np.isfinite(truth.loc[:, list(continuous)].to_numpy(dtype=float)).all() or (truth.loc[:, list(continuous)].to_numpy(dtype=float) <= 0).any() or (truth.latent_bloom_probability >= 1).any() or not np.isin(truth.latent_bloom_event.to_numpy(dtype=float), (0.0, 1.0)).all():
        raise ValueError("latent has invalid target values")
    visible = _visible_drivers(drivers)
    _same_ordered_keys(truth, visible, left_name="latent", right_name="drivers")
    n = len(truth)
    width = int((truth.date == truth.date.iloc[0]).sum())
    humidity = visible.relative_humidity_pct.to_numpy(dtype=float)
    rain = visible.precipitation_mm_day.to_numpy(dtype=float)
    solar = visible.solar_radiation_MJ_m2_day.to_numpy(dtype=float)
    persistent = np.zeros(width, dtype=float)
    cloud_probability = np.empty(n, dtype=float)
    cloud_draw = rng.random(n)
    for start in range(0, n, width):
        stop = start + width
        logit = -1.85 + 0.035 * (humidity[start:stop] - 60.0) + 0.025 * rain[start:stop] - 0.040 * solar[start:stop] + 0.75 * persistent
        cloud_probability[start:stop] = 1.0 / (1.0 + np.exp(-np.clip(logit, -35.0, 35.0)))
        # The latent layer is deliberately absent from this persistent state.
        persistent = 0.70 * persistent + 0.30 * (cloud_draw[start:stop] < cloud_probability[start:stop]).astype(float)
    cloud_fraction = np.clip(cloud_probability + rng.normal(0.0, 0.10, size=n), 0.0, 1.0)
    cloudy = cloud_draw < cloud_probability
    valid_pixel_ratio = np.clip(0.96 - 0.70 * cloud_fraction + rng.normal(0.0, 0.035, size=n), 0.0, 1.0)
    covered = (~cloudy) & (valid_pixel_ratio > MIN_VALID_PIXEL_RATIO)
    if force_cloud:
        covered[:] = False
        cloud_fraction[:] = 1.0
        valid_pixel_ratio[:] = 0.0
    chlorophyll = truth.chlorophyll_a_ug_L.to_numpy(dtype=float)
    phycocyanin = truth.phycocyanin_ug_L.to_numpy(dtype=float)
    density = truth.cyanobacteria_density_cells_L.to_numpy(dtype=float)
    detection_limits = {
        "remote_chlorophyll_a_detection_limit_ug_L": 0.10,
        "remote_phycocyanin_detection_limit_ug_L": 0.05,
        "remote_cyanobacteria_density_detection_limit_cells_L": 10_000.0,
        "remote_fai_detection_limit": 0.0005,
        "remote_ndci_detection_limit": 0.0010,
    }
    raw_chlorophyll = _soft_positive(chlorophyll * np.exp(rng.normal(0.0, 0.18, n)), 300.0)
    raw_phycocyanin = _soft_positive(phycocyanin * np.exp(rng.normal(0.0, 0.20, n)), 210.0)
    raw_density = _soft_positive(density * np.exp(rng.normal(0.0, 0.22, n)), 40_000_000.0)
    raw_fai = _soft_positive(0.004 + 0.0011 * np.log1p(chlorophyll) + np.exp(rng.normal(-6.1, 0.24, n)), 0.12)
    raw_ndci = _soft_positive(0.008 + 0.0015 * np.log1p(phycocyanin) + np.exp(rng.normal(-5.8, 0.22, n)), 0.16)
    raw_values = (raw_chlorophyll, raw_phycocyanin, raw_density, raw_fai, raw_ndci)
    limit_columns = tuple(detection_limits)
    below_limit = tuple(raw <= detection_limits[limit] for raw, limit in zip(raw_values, limit_columns))
    # A reported value at a detection limit is explicitly flagged as censored;
    # it is never silently represented as an exact analytical concentration.
    remote_values = tuple(np.where(flag, detection_limits[limit], raw) for raw, limit, flag in zip(raw_values, limit_columns, below_limit))
    output = truth.loc[:, list(KEY_COLUMNS)].copy()
    for name, values in zip(_REMOTE_COLUMNS, remote_values):
        output[name] = np.where(covered, values, np.nan)
    for name, value in detection_limits.items():
        output[name] = value
    flag_columns = (
        "remote_chlorophyll_a_below_detection_limit",
        "remote_phycocyanin_below_detection_limit",
        "remote_cyanobacteria_density_below_detection_limit",
        "remote_fai_below_detection_limit",
        "remote_ndci_below_detection_limit",
    )
    for name, flag in zip(flag_columns, below_limit):
        output[name] = pd.array(np.where(covered, flag, pd.NA), dtype="boolean")
    any_censored = np.logical_or.reduce(below_limit)
    output["censoring_status"] = np.where(~covered, "not_observed", np.where(any_censored, "left_censored", "none"))
    output["cloud_fraction"] = cloud_fraction
    output["valid_pixel_ratio"] = valid_pixel_ratio
    output["coverage_status"] = np.where(covered, "observed", "not_observed")
    output["missing_reason"] = np.where(covered, pd.NA, "forced_cloud_test" if force_cloud else "weather_cloud_or_low_valid_pixels")
    output["quality_status"] = np.where(~covered, "not_observed", np.where(any_censored, "usable_left_censored", "usable"))
    observation_time = truth.date + pd.Timedelta(hours=10, minutes=30)
    output["observed_time"] = observation_time.where(covered, pd.NaT)
    output["available_time"] = (observation_time + pd.Timedelta(hours=2)).where(covered, pd.NaT)
    output["observed_at"] = output["observed_time"]
    output["available_at"] = output["available_time"]
    output["issue_time"] = (observation_time + pd.Timedelta(hours=3)).where(covered, pd.NaT)
    output["data_role"] = "observable_measurement"
    output["value_type"] = "simulated_observation"
    output["label_evidence"] = "simulation_observation_process"
    output["data_mode"] = "simulation"
    output["is_ground_truth"] = 0
    output["is_model_feature"] = 1
    output["claim_boundary"] = getattr(config, "claim_boundary", CLAIM_BOUNDARY)
    output["observation_persistence_scope"] = "within_supplied_contiguous_block_only"
    return output
