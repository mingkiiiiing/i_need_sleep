from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import SimulationConfig


REGION_AREA_KM2 = {
    "TAIHU_CT": 257.2,
    "TAIHU_ET": 350.7,
    "TAIHU_GH": 140.5,
    "TAIHU_ML": 280.7,
    "TAIHU_ST": 233.9,
    "TAIHU_WT": 514.5,
    "TAIHU_XK": 233.9,
    "TAIHU_ZS": 327.4,
}

REGION_RISK = {
    "TAIHU_CT": 0.05,
    "TAIHU_ET": -0.30,
    "TAIHU_GH": 0.20,
    "TAIHU_ML": 0.35,
    "TAIHU_ST": 0.10,
    "TAIHU_WT": 0.55,
    "TAIHU_XK": -0.25,
    "TAIHU_ZS": 0.45,
}

CONTINUOUS_COLUMNS = (
    "air_temperature_C",
    "precipitation_mm_day",
    "wind_speed_m_s",
    "wind_direction_deg",
    "solar_radiation_MJ_m2_day",
    "relative_humidity_pct",
    "surface_pressure_kPa",
    "water_temperature_C",
    "water_level_m",
    "flow_speed_m_s",
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "phytoplankton_biomass_mg_L",
    "chlorophyll_a_ug_L",
    "cyanobacteria_density_cells_L",
    "fai_proxy",
    "ndci_proxy",
    "bloom_probability",
)


def _ar1(rng: np.random.Generator, size: int, phi: float, sigma: float) -> np.ndarray:
    innovations = rng.normal(0.0, sigma, size)
    values = np.empty(size, dtype=float)
    values[0] = innovations[0]
    scale = math.sqrt(max(1.0 - phi * phi, 1e-9))
    for index in range(1, size):
        values[index] = phi * values[index - 1] + scale * innovations[index]
    return values


def _logistic(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _interpolate_anchor(
    region_anchors: pd.DataFrame,
    dates: pd.DatetimeIndex,
    column: str,
    fallback: float,
) -> np.ndarray:
    valid = region_anchors.loc[region_anchors[column].notna(), ["month", column]].copy()
    if valid.empty:
        return np.full(len(dates), fallback, dtype=float)
    anchor_dates = pd.DatetimeIndex(pd.to_datetime(valid["month"].astype(str) + "-15"))
    anchor_values = valid[column].astype(float).to_numpy()
    order = np.argsort(anchor_dates.view("int64"))
    anchor_ordinals = anchor_dates.view("int64")[order]
    daily_ordinals = dates.view("int64")
    return np.interp(daily_ordinals, anchor_ordinals, anchor_values[order])


def _assign_split(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    years = pd.DatetimeIndex(dates).year
    return np.select(
        [years <= 2017, years <= 2021],
        ["train", "validation"],
        default="test",
    )


def _simulate_region(
    region_id: str,
    region_index: int,
    weather: pd.DataFrame,
    anchors: pd.DataFrame,
    config: SimulationConfig,
) -> pd.DataFrame:
    seed = np.random.SeedSequence([config.random_seed, region_index])
    rng = np.random.default_rng(seed)
    dates = pd.DatetimeIndex(weather["date"])
    count = len(dates)
    region_anchors = anchors.loc[anchors["station_id"] == region_id].sort_values("month")
    if region_anchors.empty:
        raise ValueError(f"no quarterly anchors for region {region_id}")

    day_of_year = dates.dayofyear.to_numpy()
    seasonal = np.sin(2.0 * np.pi * (day_of_year - 172.0) / 365.25)
    region_center = region_index - 3.5
    slow_weather = _ar1(rng, count, phi=0.985, sigma=0.22)
    fast_weather = _ar1(rng, count, phi=0.72, sigma=0.32)

    air_temperature = (
        weather["air_temperature_C"].to_numpy(dtype=float)
        + 0.09 * region_center
        + slow_weather
    )
    precipitation = np.clip(
        weather["precipitation_mm_day"].to_numpy(dtype=float)
        * 0.90
        * np.exp(0.025 * region_center + rng.normal(0.0, 0.06, count)),
        0.0,
        260.0,
    )
    wind_speed = np.clip(
        weather["wind_speed_m_s"].to_numpy(dtype=float)
        * 0.52
        * (1.0 + 0.018 * region_center)
        + fast_weather * 0.20,
        0.05,
        18.0,
    )
    wind_direction = np.mod(
        weather["wind_direction_deg"].to_numpy(dtype=float)
        + 2.5 * region_center
        + _ar1(rng, count, phi=0.55, sigma=6.0),
        360.0,
    )
    solar_radiation = np.clip(
        weather["solar_radiation_MJ_m2_day"].to_numpy(dtype=float)
        * (1.0 - 0.006 * region_center)
        * np.exp(rng.normal(0.0, 0.025, count)),
        0.0,
        35.0,
    )
    humidity = np.clip(
        weather["relative_humidity_pct"].to_numpy(dtype=float)
        + 0.30 * region_center
        + _ar1(rng, count, phi=0.80, sigma=0.8),
        20.0,
        100.0,
    )
    pressure = np.clip(
        weather["surface_pressure_kPa"].to_numpy(dtype=float)
        - 0.012 * region_center
        + _ar1(rng, count, phi=0.90, sigma=0.05),
        95.0,
        104.0,
    )

    air_smoothed = pd.Series(air_temperature).ewm(span=9, adjust=False).mean().to_numpy()
    water_temperature = np.clip(
        0.78 * air_smoothed
        + 5.2
        + 0.055 * (solar_radiation - np.nanmean(solar_radiation))
        + 0.08 * region_center
        + _ar1(rng, count, phi=0.94, sigma=0.35),
        1.0,
        34.5,
    )
    rain_7d = pd.Series(precipitation).rolling(7, min_periods=1).sum().to_numpy()
    rain_30d = pd.Series(precipitation).rolling(30, min_periods=1).sum().to_numpy()
    water_level = np.clip(
        3.05
        + 0.00125 * (rain_30d - np.nanmedian(rain_30d))
        - 0.07 * seasonal
        + 0.008 * region_center
        + _ar1(rng, count, phi=0.985, sigma=0.025),
        2.55,
        4.25,
    )
    flow_speed = np.clip(
        0.025 + 0.0010 * rain_7d + 0.012 * wind_speed + np.abs(fast_weather) * 0.008,
        0.01,
        0.85,
    )

    base_tp = _interpolate_anchor(region_anchors, dates, "wq_tp", 0.11)
    base_tn = _interpolate_anchor(region_anchors, dates, "wq_tn", 2.2)
    base_do = _interpolate_anchor(region_anchors, dates, "wq_do", 8.2)
    base_ph = _interpolate_anchor(region_anchors, dates, "wq_ph", 8.1)
    base_biomass = _interpolate_anchor(region_anchors, dates, "wq_phyto_biomass", 3.0)
    rain_z = (rain_30d - np.nanmedian(rain_30d)) / (np.nanstd(rain_30d) + 1e-9)
    tp = np.clip(
        base_tp
        * np.exp(0.075 * seasonal + 0.035 * rain_z + _ar1(rng, count, 0.96, 0.055)),
        0.008,
        0.65,
    )
    tn_raw = np.maximum(
        base_tn
        * np.exp(-0.035 * seasonal + 0.025 * rain_z + _ar1(rng, count, 0.97, 0.045)),
        0.25,
    )
    tn = np.maximum(12.0 * np.tanh(tn_raw / 12.0), 0.25)
    dissolved_oxygen = np.clip(
        base_do
        - 0.095 * (water_temperature - 18.0)
        - 0.16 * np.maximum(base_biomass - np.nanmedian(base_biomass), 0.0)
        + _ar1(rng, count, 0.90, 0.32),
        2.0,
        16.5,
    )
    ph = np.clip(
        base_ph + 0.09 * seasonal + _ar1(rng, count, 0.91, 0.055),
        6.6,
        10.0,
    )

    temperature_suitability = np.exp(-0.5 * ((water_temperature - 27.0) / 6.2) ** 2)
    phosphorus_limitation = tp / (tp + 0.055)
    nitrogen_limitation = tn / (tn + 0.75)
    nutrient_suitability = np.sqrt(phosphorus_limitation * nitrogen_limitation)
    light_suitability = _logistic((solar_radiation - 11.0) / 3.2)
    calm_suitability = _logistic((3.4 - wind_speed) / 0.85)
    disturbance = np.exp(-np.minimum(rain_7d, 120.0) / 115.0)

    desired_log_chla = (
        np.log(np.clip(3.5 + 3.8 * base_biomass, 1.0, None))
        + 0.78 * temperature_suitability
        + 0.48 * nutrient_suitability
        + 0.32 * light_suitability
        + 0.28 * calm_suitability
        + 0.18 * disturbance
        + REGION_RISK[region_id] * 0.35
        - 1.05
    )
    log_chla = np.empty(count, dtype=float)
    log_chla[0] = desired_log_chla[0] + rng.normal(0.0, 0.14)
    innovations = rng.normal(0.0, 0.16, count)
    for index in range(1, count):
        log_chla[index] = (
            0.86 * log_chla[index - 1]
            + 0.14 * desired_log_chla[index]
            + innovations[index]
        )
    chlorophyll_raw = np.exp(log_chla)
    chlorophyll = np.maximum(300.0 * np.tanh(chlorophyll_raw / 300.0), 0.6)
    biomass = np.clip(
        0.42 * base_biomass
        + 0.105 * chlorophyll
        + _ar1(rng, count, 0.92, 0.28),
        0.05,
        35.0,
    )
    cyanobacteria_share = _logistic(
        -1.25
        + 2.0 * temperature_suitability
        + 0.70 * calm_suitability
        + 0.45 * nutrient_suitability
        + REGION_RISK[region_id]
        + _ar1(rng, count, 0.90, 0.18)
    )
    cyanobacteria_density_raw = np.maximum(
        chlorophyll * cyanobacteria_share * np.exp(rng.normal(12.4, 0.42, count)),
        1.0e3,
    )
    cyanobacteria_density = np.maximum(
        3.0e8 * np.tanh(cyanobacteria_density_raw / 3.0e8),
        1.0e3,
    )
    blue_algae_biomass = np.clip(
        biomass
        * cyanobacteria_share
        * np.exp(_ar1(rng, count, phi=0.88, sigma=0.10)),
        0.01,
        30.0,
    )

    bloom_logit = (
        -6.50
        + 0.70 * np.log1p(chlorophyll)
        + 2.10 * temperature_suitability
        - 0.90 * (1.0 - temperature_suitability)
        + 0.55 * calm_suitability
        + 0.40 * nutrient_suitability
        + 0.30 * light_suitability
        + REGION_RISK[region_id]
        + _ar1(rng, count, 0.965, 0.55)
    )
    bloom_probability = np.clip(_logistic(bloom_logit), 0.002, 0.985)
    bloom_event = np.zeros(count, dtype=np.int8)
    for index in range(count):
        persistence = 0.18 if index and bloom_event[index - 1] else 0.0
        event_probability = min(bloom_probability[index] + persistence, 0.995)
        bloom_event[index] = int(rng.random() < event_probability)

    cloud_probability = np.clip(
        0.10 + 0.006 * precipitation + 0.004 * np.maximum(humidity - 72.0, 0.0),
        0.06,
        0.82,
    )
    covered = rng.random(count) > cloud_probability
    label_state = np.where(covered, np.where(bloom_event == 1, "positive", "negative"), "unknown")
    bloom_label = pd.array(np.where(covered, bloom_event, np.nan), dtype="Int8")
    area_fraction = np.where(
        bloom_event == 1,
        np.clip(
            0.008
            + 0.22 * bloom_probability
            + rng.lognormal(mean=-3.5, sigma=0.62, size=count),
            0.002,
            0.72,
        ),
        0.0,
    )
    bloom_area = np.where(covered, REGION_AREA_KM2[region_id] * area_fraction, np.nan)
    risk_level = np.where(
        ~covered,
        "unknown",
        np.select(
            [bloom_probability >= 0.70, bloom_probability >= 0.42, bloom_probability >= 0.18],
            ["high", "medium", "low"],
            default="none",
        ),
    )
    fai_proxy = np.clip(
        0.0015 + 0.00042 * chlorophyll + rng.normal(0.0, 0.0035, count),
        -0.02,
        0.12,
    )
    ndci_proxy = np.clip(
        -0.06 + 0.030 * np.log1p(chlorophyll) + rng.normal(0.0, 0.025, count),
        -0.35,
        0.55,
    )
    fai_proxy[~covered] = np.nan
    ndci_proxy[~covered] = np.nan

    result = pd.DataFrame(
        {
            "sample_id": [f"{region_id}:{date:%Y-%m-%d}" for date in dates],
            "date": dates,
            "spatial_id": region_id,
            "spatial_type": "lake_region",
            "region_area_km2": REGION_AREA_KM2[region_id],
            "air_temperature_C": air_temperature,
            "precipitation_mm_day": precipitation,
            "wind_speed_m_s": wind_speed,
            "wind_direction_deg": wind_direction,
            "solar_radiation_MJ_m2_day": solar_radiation,
            "relative_humidity_pct": humidity,
            "surface_pressure_kPa": pressure,
            "water_temperature_C": water_temperature,
            "water_level_m": water_level,
            "flow_speed_m_s": flow_speed,
            "total_phosphorus_mg_L": tp,
            "total_nitrogen_mg_L": tn,
            "dissolved_oxygen_mg_L": dissolved_oxygen,
            "ph": ph,
            "phytoplankton_biomass_mg_L": biomass,
            "chlorophyll_a_ug_L": chlorophyll,
            "cyanobacteria_density_cells_L": cyanobacteria_density,
            "blue_algae_biomass_mg_L": blue_algae_biomass,
            "fai_proxy": fai_proxy,
            "ndci_proxy": ndci_proxy,
            "bloom_probability": bloom_probability,
            "bloom_area_km2": bloom_area,
            "bloom_label": bloom_label,
            "bloom_label_state": label_state,
            "bloom_risk_level": risk_level,
            "coverage_status": np.where(covered, "covered", "not_observed"),
            "quality_flag": np.where(covered, "pass", "warning"),
            "weather_source_class": "external_reanalysis_plus_derived_microclimate",
            "water_quality_source_class": "synthetic_conditioned_on_observed_anchor",
            "source_class": "synthetic_conditioned",
            "data_mode": "simulation",
            "is_ground_truth": 0,
            "label_evidence": "simulation_mechanism",
            "data_version": config.data_version,
            "generator_version": config.generator_version,
            "random_seed": config.random_seed,
            "claim_boundary": config.claim_boundary,
            "dataset_split": _assign_split(dates),
        }
    )
    return result


def generate_region_daily(
    weather: pd.DataFrame,
    anchors: pd.DataFrame,
    config: SimulationConfig | None = None,
) -> pd.DataFrame:
    config = config or SimulationConfig()
    frames = [
        _simulate_region(region_id, index, weather, anchors, config)
        for index, region_id in enumerate(config.region_ids)
    ]
    return pd.concat(frames, ignore_index=True).sort_values(["spatial_id", "date"]).reset_index(drop=True)


def aggregate_lake_daily(region_daily: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "spatial_id", "region_area_km2", "bloom_label", "coverage_status"}
    missing = sorted(required - set(region_daily.columns))
    if missing:
        raise ValueError(f"lake aggregation columns missing: {missing}")
    if (region_daily["spatial_id"] == "TAIHU_WHOLE").any():
        raise ValueError("TAIHU_WHOLE must not be present in regional input")

    def aggregate_day(group: pd.DataFrame) -> pd.Series:
        weights = group["region_area_km2"].to_numpy(dtype=float)
        result: dict[str, object] = {}
        for column in CONTINUOUS_COLUMNS:
            values = group[column].to_numpy(dtype=float)
            valid = np.isfinite(values)
            result[column] = float(np.average(values[valid], weights=weights[valid])) if valid.any() else np.nan
        result["region_area_km2"] = float(weights.sum())
        result["bloom_area_km2"] = float(group["bloom_area_km2"].sum(min_count=1))
        observed = group["coverage_status"].eq("covered")
        positives = group.loc[observed, "bloom_label"].fillna(0).astype(int)
        if observed.sum() < 4:
            result["bloom_label"] = pd.NA
            result["bloom_label_state"] = "unknown"
            result["coverage_status"] = "partial_not_observed"
        else:
            label = int(positives.max())
            result["bloom_label"] = label
            result["bloom_label_state"] = "positive" if label else "negative"
            result["coverage_status"] = "covered" if observed.all() else "partial_covered"
        probability = float(result["bloom_probability"])
        result["bloom_risk_level"] = (
            "unknown"
            if result["bloom_label_state"] == "unknown"
            else "high"
            if probability >= 0.70
            else "medium"
            if probability >= 0.42
            else "low"
            if probability >= 0.18
            else "none"
        )
        result["quality_flag"] = "pass" if result["bloom_label_state"] != "unknown" else "warning"
        return pd.Series(result)

    lake = region_daily.groupby("date", sort=True, observed=True).apply(
        aggregate_day, include_groups=False
    ).reset_index()
    lake.insert(0, "sample_id", lake["date"].map(lambda value: f"TAIHU_WHOLE:{value:%Y-%m-%d}"))
    lake.insert(2, "spatial_id", "TAIHU_WHOLE")
    lake.insert(3, "spatial_type", "lake_aggregate")
    lake["weather_source_class"] = "derived_area_weighted_aggregate"
    lake["water_quality_source_class"] = "derived_area_weighted_aggregate"
    lake["source_class"] = "derived_simulation"
    lake["data_mode"] = "simulation"
    lake["is_ground_truth"] = 0
    lake["label_evidence"] = "simulation_mechanism"
    lake["data_version"] = region_daily["data_version"].iloc[0]
    lake["generator_version"] = region_daily["generator_version"].iloc[0]
    lake["random_seed"] = int(region_daily["random_seed"].iloc[0])
    lake["claim_boundary"] = "synthetic_development_only"
    lake["dataset_split"] = _assign_split(lake["date"])
    lake["bloom_label"] = pd.array(lake["bloom_label"], dtype="Int8")
    return lake
