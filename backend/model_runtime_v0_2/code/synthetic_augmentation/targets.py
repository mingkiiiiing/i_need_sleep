"""Latent synthetic ecological targets and observation-aware bloom labels.

``simulation truth`` in this module is internal generator truth only.  It is
not an assertion about field observations or a regulatory water-bloom record.
Event persistence is intentionally limited to the supplied contiguous block;
the future partitioned pipeline must call this layer on a continuous block (or
provide an explicit carry state in a versioned interface revision).
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType

import numpy as np
import pandas as pd


KEY_COLUMNS = ("date", "grid_id", "grid_numeric_id", "experimental_zone_id")
CLAIM_BOUNDARY = "synthetic_development_only"
MIN_VALID_PIXEL_RATIO = 0.35
RISK_THRESHOLD_VERSION = "TAIHU_BLOOM_RISK_DEVELOPMENT_V0.3"
RISK_THRESHOLD_TABLE = (
    MappingProxyType({"version": RISK_THRESHOLD_VERSION, "level": "none", "minimum_coverage_ratio": 0.0}),
    MappingProxyType({"version": RISK_THRESHOLD_VERSION, "level": "low", "minimum_coverage_ratio": 0.02}),
    MappingProxyType({"version": RISK_THRESHOLD_VERSION, "level": "medium", "minimum_coverage_ratio": 0.10}),
    MappingProxyType({"version": RISK_THRESHOLD_VERSION, "level": "high", "minimum_coverage_ratio": 0.30}),
    MappingProxyType({"version": RISK_THRESHOLD_VERSION, "level": "severe", "minimum_coverage_ratio": 0.60}),
)


def risk_threshold_table_sha256() -> str:
    """Canonical SHA-256 for transparent non-regulatory development thresholds."""
    canonical = json.dumps(
        [dict(row) for row in RISK_THRESHOLD_TABLE], ensure_ascii=True,
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _explicit_rng(rng) -> np.random.Generator:
    if not isinstance(rng, np.random.Generator):
        raise ValueError("rng must be an explicit numpy.random.Generator")
    return rng


def _numeric(frame: pd.DataFrame, columns, *, positive=(), nonnegative=(), context: str) -> pd.DataFrame:
    result = frame.copy()
    for name in columns:
        result[name] = pd.to_numeric(result[name], errors="coerce")
    values = result[list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{context} has non-finite numeric values")
    for name in positive:
        if (result[name] <= 0).any():
            raise ValueError(f"{context} {name} must be strictly positive")
    for name in nonnegative:
        if (result[name] < 0).any():
            raise ValueError(f"{context} {name} must be non-negative")
    return result


def _ordered_grid_frame(frame, *, required=(), context="frame") -> pd.DataFrame:
    """Copy and strictly validate the shared date/grid ordering contract."""
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"{context} must be a DataFrame")
    missing = sorted(set(KEY_COLUMNS).union(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{context} missing required fields: {missing}")
    if frame.empty:
        raise ValueError(f"{context} must contain at least one date/grid row")
    result = frame.copy(deep=True)
    if result[list(KEY_COLUMNS)].isna().any().any():
        raise ValueError(f"{context} has invalid keys")
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    if result["date"].isna().any() or not result["date"].eq(result["date"].dt.normalize()).all():
        raise ValueError(f"{context} has invalid dates")
    result["grid_id"] = result["grid_id"].astype(str)
    result["experimental_zone_id"] = result["experimental_zone_id"].astype(str)
    if result.grid_id.str.len().eq(0).any() or result.grid_id.eq("nan").any() or result.experimental_zone_id.str.len().eq(0).any() or result.experimental_zone_id.eq("nan").any():
        raise ValueError(f"{context} has invalid grid mapping")
    result["grid_numeric_id"] = pd.to_numeric(result["grid_numeric_id"], errors="coerce")
    numeric_ids = result.grid_numeric_id.to_numpy(dtype=float)
    if not np.isfinite(numeric_ids).all() or not np.equal(numeric_ids, np.floor(numeric_ids)).all() or (numeric_ids < 0).any():
        raise ValueError(f"{context} has invalid grid_numeric_id")
    result["grid_numeric_id"] = result.grid_numeric_id.astype(int)
    dates = pd.DatetimeIndex(pd.unique(result.date))
    if not dates.is_monotonic_increasing or (len(dates) > 1 and not np.all((dates[1:] - dates[:-1]) == pd.Timedelta(days=1))):
        raise ValueError(f"{context} dates must be sorted and contiguous daily")
    first = result.loc[result.date.eq(dates[0]), list(KEY_COLUMNS[1:])]
    mapping = list(first.itertuples(index=False, name=None))
    if not mapping or len({row[0] for row in mapping}) != len(mapping):
        raise ValueError(f"{context} has duplicate grid IDs")
    expected_keys = [(date, grid_id) for date in dates for grid_id, _, _ in mapping]
    actual_keys = list(zip(result.date, result.grid_id))
    if actual_keys != expected_keys:
        raise ValueError(f"{context} date/grid ordering must be sorted and complete")
    if list(result.loc[:, list(KEY_COLUMNS[1:])].itertuples(index=False, name=None)) != mapping * len(dates):
        raise ValueError(f"{context} grid mapping differs across dates")
    return result


def _same_ordered_keys(left: pd.DataFrame, right: pd.DataFrame, *, left_name: str, right_name: str) -> None:
    if list(left.loc[:, KEY_COLUMNS].itertuples(index=False, name=None)) != list(right.loc[:, KEY_COLUMNS].itertuples(index=False, name=None)):
        raise ValueError(f"{left_name} and {right_name} must have exactly identical ordered keys")


def _soft_positive(raw: np.ndarray, scale: float) -> np.ndarray:
    raw = np.asarray(raw, dtype=float)
    if not np.isfinite(raw).all() or (raw <= 0).any():
        raise ValueError("target formula generated invalid raw values")
    capped = scale * (-np.expm1(-raw / scale))
    return np.clip(capped, np.nextafter(0.0, 1.0), np.nextafter(scale, 0.0))


def _expit(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=float), -35.0, 35.0)
    result = 1.0 / (1.0 + np.exp(-values))
    return np.clip(result, np.nextafter(0.0, 1.0), np.nextafter(1.0, 0.0))


def build_latent_targets(states, rng, config) -> pd.DataFrame:
    """Build internal ecological truth from visible contemporaneous mechanism state.

    The caller controls all random draws through ``rng``.  The supplied block
    must be complete, date-major, and contiguous so sampled events can retain
    their transparent within-block previous-event persistence.
    """
    rng = _explicit_rng(rng)
    required = (
        "blue_algae_biomass_mg_L", "phytoplankton_biomass_mg_L", "water_temperature_C",
        "total_nitrogen_mg_L", "total_phosphorus_mg_L", "solar_radiation_MJ_m2_day",
        "wind_speed_m_s", "mixing_index",
    )
    frame = _ordered_grid_frame(states, required=required, context="states")
    frame = _numeric(
        frame, required, positive=("blue_algae_biomass_mg_L", "phytoplankton_biomass_mg_L"),
        nonnegative=("total_nitrogen_mg_L", "total_phosphorus_mg_L", "solar_radiation_MJ_m2_day", "wind_speed_m_s"),
        context="states",
    )
    if ((frame.mixing_index < 0) | (frame.mixing_index > 1)).any():
        raise ValueError("states mixing_index must be in [0, 1]")
    mechanism_biomass = frame.blue_algae_biomass_mg_L.to_numpy(dtype=float)
    phyto = frame.phytoplankton_biomass_mg_L.to_numpy(dtype=float)
    temperature = frame.water_temperature_C.to_numpy(dtype=float)
    nitrogen = frame.total_nitrogen_mg_L.to_numpy(dtype=float)
    phosphorus = frame.total_phosphorus_mg_L.to_numpy(dtype=float)
    light = frame.solar_radiation_MJ_m2_day.to_numpy(dtype=float)
    wind = frame.wind_speed_m_s.to_numpy(dtype=float)
    mixing = frame.mixing_index.to_numpy(dtype=float)
    n = len(frame)
    # Independent innovations avoid deterministic copies from the shared state.
    biomass_noise = rng.normal(0.0, 0.14, size=n)
    chlorophyll_noise = rng.normal(0.0, 0.22, size=n)
    phycocyanin_noise = rng.normal(0.0, 0.25, size=n)
    density_noise = rng.normal(0.0, 0.20, size=n)
    target_biomass = _soft_positive(mechanism_biomass * np.exp(biomass_noise), 42.0)
    temperature_response = 0.70 + 0.38 * np.exp(-np.square((temperature - 27.0) / 12.0))
    nutrient_response = 0.40 + 0.60 * np.minimum(nitrogen / (nitrogen + 0.40), phosphorus / (phosphorus + 0.025))
    light_response = 0.55 + 0.45 * light / (light + 6.0)
    chlorophyll = _soft_positive(9.5 * mechanism_biomass * temperature_response * nutrient_response * np.exp(chlorophyll_noise), 380.0)
    phycocyanin = _soft_positive(5.7 * mechanism_biomass * (0.7 + 0.3 * nutrient_response) * np.exp(phycocyanin_noise), 240.0)
    density = _soft_positive(1_250_000.0 * mechanism_biomass * (0.65 + 0.35 * light_response) * np.exp(density_noise), 45_000_000.0)
    logit = (
        -3.0 + 0.63 * np.log1p(mechanism_biomass) + 0.32 * np.log1p(phyto)
        + 1.10 * (temperature_response - 0.70) + 0.75 * (nutrient_response - 0.40)
        + 0.45 * (light_response - 0.55) - 1.15 * mixing - 0.10 * wind
    )
    probability = _expit(logit)
    width = int((frame.date == frame.date.iloc[0]).sum())
    events = np.zeros(n, dtype=np.int8)
    prior = np.zeros(width, dtype=np.int8)
    uniforms = rng.random(n)
    for start in range(0, n, width):
        stop = start + width
        event_probability = np.clip(probability[start:stop] + 0.26 * prior, 0.0, 0.985)
        prior = (uniforms[start:stop] < event_probability).astype(np.int8)
        events[start:stop] = prior
    output = frame.loc[:, KEY_COLUMNS].copy()
    output["blue_algae_biomass_mg_L"] = target_biomass
    output["chlorophyll_a_ug_L"] = chlorophyll
    output["phycocyanin_ug_L"] = phycocyanin
    output["cyanobacteria_density_cells_L"] = density
    output["latent_bloom_probability"] = probability
    output["latent_bloom_event"] = events.astype(np.int8)
    output["data_role"] = "latent_simulation_truth"
    output["value_type"] = "simulated"
    output["label_evidence"] = "simulation_truth"
    output["data_mode"] = "simulation"
    output["is_ground_truth"] = 0
    output["is_model_feature"] = 0
    output["claim_boundary"] = getattr(config, "claim_boundary", CLAIM_BOUNDARY)
    output["target_persistence_scope"] = "within_supplied_contiguous_block_only"
    return output


def _metadata_frame(metadata, latent: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(metadata, pd.DataFrame):
        raise ValueError("metadata must be a DataFrame")
    required = set(KEY_COLUMNS[1:]) | {"water_area_m2"}
    missing = sorted(required - set(metadata.columns))
    if missing:
        raise ValueError(f"metadata missing required fields: {missing}")
    result = metadata.copy(deep=True)
    if result.empty or result[list(KEY_COLUMNS[1:])].isna().any().any() or result.grid_id.duplicated().any():
        raise ValueError("metadata must have one valid row per grid")
    result["grid_id"] = result.grid_id.astype(str)
    result["experimental_zone_id"] = result.experimental_zone_id.astype(str)
    result["grid_numeric_id"] = pd.to_numeric(result.grid_numeric_id, errors="coerce")
    ids = result.grid_numeric_id.to_numpy(dtype=float)
    if not np.isfinite(ids).all() or not np.equal(ids, np.floor(ids)).all() or (ids < 0).any():
        raise ValueError("metadata has invalid grid_numeric_id")
    result["grid_numeric_id"] = result.grid_numeric_id.astype(int)
    result = _numeric(result, ("water_area_m2",), positive=("water_area_m2",), context="metadata")
    expected = list(latent.loc[latent.date.eq(latent.date.iloc[0]), list(KEY_COLUMNS[1:])].itertuples(index=False, name=None))
    actual = list(result.loc[:, list(KEY_COLUMNS[1:])].itertuples(index=False, name=None))
    if actual != expected:
        raise ValueError("metadata mapping/order must exactly match the grid frame")
    return result


def _validate_observed_for_labels(observed: pd.DataFrame) -> None:
    required = (
        "coverage_status", "missing_reason", "quality_status", "valid_pixel_ratio",
        "observed_time", "available_time", "observed_at", "available_at", "issue_time", "remote_chlorophyll_a_ug_L",
        "remote_phycocyanin_ug_L", "remote_cyanobacteria_density_cells_L",
        "remote_fai_proxy", "remote_ndci_proxy",
        "remote_chlorophyll_a_detection_limit_ug_L", "remote_phycocyanin_detection_limit_ug_L",
        "remote_cyanobacteria_density_detection_limit_cells_L", "remote_fai_detection_limit",
        "remote_ndci_detection_limit", "remote_chlorophyll_a_below_detection_limit",
        "remote_phycocyanin_below_detection_limit", "remote_cyanobacteria_density_below_detection_limit",
        "remote_fai_below_detection_limit", "remote_ndci_below_detection_limit", "censoring_status",
    )
    missing = sorted(set(required) - set(observed.columns))
    if missing:
        raise ValueError(f"observed missing required fields: {missing}")
    status = observed.coverage_status.astype(str)
    if not status.isin(("observed", "not_observed")).all():
        raise ValueError("observed has malformed coverage_status")
    covered = status.eq("observed")
    measures = ["remote_chlorophyll_a_ug_L", "remote_phycocyanin_ug_L", "remote_cyanobacteria_density_cells_L", "remote_fai_proxy", "remote_ndci_proxy"]
    pixels = pd.to_numeric(observed.valid_pixel_ratio, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(pixels).all() or (pixels < 0).any() or (pixels > 1).any():
        raise ValueError("observed has invalid valid-pixel ratio")
    if np.any(pixels[covered.to_numpy()] <= MIN_VALID_PIXEL_RATIO):
        raise ValueError("covered observations have invalid valid-pixel ratio")
    limits_and_flags = (
        ("remote_chlorophyll_a_ug_L", "remote_chlorophyll_a_detection_limit_ug_L", "remote_chlorophyll_a_below_detection_limit"),
        ("remote_phycocyanin_ug_L", "remote_phycocyanin_detection_limit_ug_L", "remote_phycocyanin_below_detection_limit"),
        ("remote_cyanobacteria_density_cells_L", "remote_cyanobacteria_density_detection_limit_cells_L", "remote_cyanobacteria_density_below_detection_limit"),
        ("remote_fai_proxy", "remote_fai_detection_limit", "remote_fai_below_detection_limit"),
        ("remote_ndci_proxy", "remote_ndci_detection_limit", "remote_ndci_below_detection_limit"),
    )
    flag_values = []
    for measure, limit, flag in limits_and_flags:
        limits = pd.to_numeric(observed[limit], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(limits).all() or (limits <= 0).any():
            raise ValueError("observed has invalid detection limit")
        if not pd.api.types.is_bool_dtype(observed[flag]):
            raise ValueError("observed detection flags must use nullable Boolean dtype")
        if observed.loc[~covered, flag].notna().any():
            raise ValueError("unobserved detection flags must be null")
        if observed.loc[covered, flag].isna().any():
            raise ValueError("covered detection flags must be non-null")
        values = pd.to_numeric(observed.loc[covered, measure], errors="coerce").to_numpy(dtype=float)
        covered_limits = pd.to_numeric(observed.loc[covered, limit], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError("covered observations have invalid measurements")
        flags = observed.loc[covered, flag].to_numpy(dtype=bool)
        if np.any(flags & (values != covered_limits)) or np.any(~flags & (values <= covered_limits)):
            raise ValueError("observed detection-limit flags and values are inconsistent")
        flag_values.append(flags)
    covered_reason = observed.loc[covered, "missing_reason"]
    if covered_reason.notna().any() and covered_reason.dropna().astype(str).str.strip().ne("").any():
        raise ValueError("covered rows require an empty missing_reason")
    covered_status = observed.loc[covered, "quality_status"].astype(str)
    if not covered_status.isin(("usable", "usable_left_censored")).all():
        raise ValueError("covered rows have invalid quality_status")
    any_censored = np.logical_or.reduce(flag_values) if flag_values else np.zeros(int(covered.sum()), dtype=bool)
    censoring = observed.loc[covered, "censoring_status"].astype(str).to_numpy()
    if np.any(any_censored & ((censoring != "left_censored") | (covered_status.to_numpy() != "usable_left_censored"))) or np.any(~any_censored & ((censoring != "none") | (covered_status.to_numpy() != "usable"))):
        raise ValueError("covered censoring_status or quality_status is inconsistent")
    time_columns = ("observed_time", "available_time", "observed_at", "available_at", "issue_time")
    times = observed.loc[:, list(time_columns)].apply(pd.to_datetime, errors="coerce")
    if times.loc[covered].isna().any().any():
        raise ValueError("covered observation timestamps are required")
    if covered.any() and (not (times.loc[covered, "observed_time"] <= times.loc[covered, "available_time"]).all() or not (times.loc[covered, "available_time"] <= times.loc[covered, "issue_time"]).all() or not (times.loc[covered, "observed_at"] <= times.loc[covered, "available_at"]).all() or not (times.loc[covered, "available_at"] <= times.loc[covered, "issue_time"]).all()):
        raise ValueError("covered observation timestamps are not causal")
    if covered.any() and (not times.loc[covered, "observed_time"].eq(times.loc[covered, "observed_at"]).all() or not times.loc[covered, "available_time"].eq(times.loc[covered, "available_at"]).all()):
        raise ValueError("observation timestamp aliases are inconsistent")
    if observed.loc[~covered, "missing_reason"].isna().any() or observed.loc[~covered, "missing_reason"].astype(str).str.strip().eq("").any():
        raise ValueError("unobserved rows require a missing_reason")
    if observed.loc[~covered, measures].notna().any().any():
        raise ValueError("unobserved rows must have null remote measurements")
    if not observed.loc[~covered, "quality_status"].astype(str).eq("not_observed").all() or not observed.loc[~covered, "censoring_status"].astype(str).eq("not_observed").all():
        raise ValueError("unobserved rows have invalid quality_status or censoring_status")
    if times.loc[~covered].notna().any().any():
        raise ValueError("unobserved observation timestamps must be NaT")


def _risk_level(event: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    level = np.full(len(event), "none", dtype=object)
    for threshold in RISK_THRESHOLD_TABLE[1:]:
        mask = (event == 1) & (coverage >= threshold["minimum_coverage_ratio"])
        level[mask] = threshold["level"]
    return level


def build_bloom_labels(latent, observed, metadata, config) -> pd.DataFrame:
    """Return latent labels plus nullable model-visible labels after observation QA."""
    latent_required = ("latent_bloom_probability", "latent_bloom_event")
    latent_frame = _ordered_grid_frame(latent, required=latent_required, context="latent")
    latent_frame = _numeric(latent_frame, ("latent_bloom_probability",), context="latent")
    probability = latent_frame.latent_bloom_probability.to_numpy(dtype=float)
    event = pd.to_numeric(latent_frame.latent_bloom_event, errors="coerce").to_numpy(dtype=float)
    if ((probability <= 0) | (probability >= 1)).any() or not np.isin(event, (0.0, 1.0)).all():
        raise ValueError("latent has invalid bloom probability or event")
    observed_frame = _ordered_grid_frame(observed, context="observed")
    _same_ordered_keys(latent_frame, observed_frame, left_name="latent", right_name="observed")
    _validate_observed_for_labels(observed_frame)
    metadata_frame = _metadata_frame(metadata, latent_frame)
    water_area = np.tile(metadata_frame.water_area_m2.to_numpy(dtype=float), int(len(latent_frame) / len(metadata_frame)))
    event_int = event.astype(np.int8)
    biomass = pd.to_numeric(latent_frame.get("blue_algae_biomass_mg_L", pd.Series(np.ones(len(latent_frame)))), errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(biomass).all() or (biomass <= 0).any():
        raise ValueError("latent requires finite positive blue_algae_biomass_mg_L for area response")
    latent_coverage = np.where(event_int == 1, 0.025 + 0.75 * (-np.expm1(-biomass / 9.0)), 0.0)
    latent_coverage = np.clip(latent_coverage, 0.0, 1.0)
    latent_area = latent_coverage * water_area / 1e6
    covered = observed_frame.coverage_status.eq("observed").to_numpy()
    label_state = np.where(~covered, "simulation_unknown", np.where(event_int == 1, "simulation_positive", "simulation_negative"))
    visible_label = pd.array(np.where(covered, event_int, None), dtype="Int8")
    visible_area = np.where(covered, latent_area, np.nan)
    visible_coverage = np.where(covered, latent_coverage, np.nan)
    visible_risk = _risk_level(event_int, latent_coverage)
    visible_risk[~covered] = "unknown"
    output = latent_frame.loc[:, KEY_COLUMNS].copy()
    output["water_area_m2"] = water_area
    output["latent_bloom_label"] = event_int
    output["latent_bloom_probability"] = probability
    output["latent_bloom_area_km2"] = latent_area
    output["latent_bloom_coverage_ratio"] = latent_coverage
    output["bloom_label"] = visible_label
    output["label_state"] = label_state
    output["bloom_area_km2"] = visible_area
    output["bloom_coverage_ratio"] = visible_coverage
    output["bloom_risk_level"] = visible_risk
    for name in (
        "coverage_status", "missing_reason", "quality_status", "censoring_status", "valid_pixel_ratio",
        "observed_time", "available_time", "observed_at", "available_at", "issue_time",
        "remote_chlorophyll_a_below_detection_limit", "remote_phycocyanin_below_detection_limit",
        "remote_cyanobacteria_density_below_detection_limit", "remote_fai_below_detection_limit",
        "remote_ndci_below_detection_limit",
    ):
        output[name] = observed_frame[name].to_numpy(copy=True)
    output["risk_threshold_version"] = RISK_THRESHOLD_VERSION
    output["risk_threshold_sha256"] = risk_threshold_table_sha256()
    output["risk_threshold_basis"] = "transparent_development_assumption_not_regulatory_standard"
    output["data_role"] = "bloom_label"
    output["value_type"] = "simulated_label"
    output["label_evidence"] = "simulation_truth_masked_by_observation_process"
    output["data_mode"] = "simulation"
    output["is_ground_truth"] = 0
    output["is_model_feature"] = 0
    output["claim_boundary"] = getattr(config, "claim_boundary", CLAIM_BOUNDARY)
    return output
