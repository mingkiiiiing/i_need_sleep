"""Strictly causal V0.3 grid-day feature construction.

Only names in the explicit contracts below can become model features.  The
input frame may retain lineage and target fields for downstream target joining,
but unknown columns never gain lagged, rolling, or otherwise derived features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


LAGS = (1, 3, 7, 14, 30)
ROLLING_WINDOWS = (3, 7, 14, 30)
FORECAST_HORIZONS = (1, 3, 7, 15, 30)
_INVALID_GRID_ID_LITERALS = frozenset(("nan", "none", "null", "<na>"))

# These are the model-visible dynamic fields produced by the V0.3 driver,
# water-quality, and observation layers.  This list is deliberately closed.
OBSERVABLE_DYNAMIC_COLUMNS = (
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
    "mixing_index",
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "phytoplankton_biomass_mg_L",
    "remote_chlorophyll_a_ug_L",
    "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L",
    "remote_fai_proxy",
    "remote_ndci_proxy",
    "cloud_fraction",
    "valid_pixel_ratio",
)

MECHANISM_STATE_COLUMNS = (
    "temperature_factor",
    "nitrogen_factor",
    "phosphorus_factor",
    "nutrient_factor",
    "light_factor",
    "capacity_factor",
    "gross_growth_rate_d",
    "respiration_rate_d",
    "mortality_rate_d",
    "mixing_loss_rate_d",
    "net_growth_rate_d",
    "mechanism_state_biomass_mg_L",
    "mechanism_biomass_forecast_mg_L",
    "mechanism_blue_algae_biomass_forecast_mg_L",
)

MECHANISM_FORECAST_COLUMNS = tuple(
    name
    for horizon in FORECAST_HORIZONS
    for name in (
        f"mechanism_biomass_forecast_{horizon}d_mg_L",
        f"mechanism_blue_algae_biomass_forecast_{horizon}d_mg_L",
    )
)


def v03_feature_allowlist() -> tuple[str, ...]:
    """Return the stable, closed V0.3 model-feature schema.

    It intentionally contains no target, label, latent-truth, or provenance
    field.  Consumers must select this tuple rather than infer features from
    input column names.
    """
    calendar = ("calendar_day_of_year_sin", "calendar_day_of_year_cos", "calendar_day_of_week_sin", "calendar_day_of_week_cos")
    dynamic = tuple(
        name
        for column in OBSERVABLE_DYNAMIC_COLUMNS
        for name in (
            column,
            *(f"{column}_lag_{lag}d" for lag in LAGS),
            *(f"{column}_rolling_{stat}_{window}d" for window in ROLLING_WINDOWS for stat in ("mean", "max", "min", "std", "count")),
            f"{column}_change_1d",
            f"{column}_change_7d",
            f"{column}_missing",
        )
    )
    return (*calendar, *dynamic, *MECHANISM_STATE_COLUMNS, *MECHANISM_FORECAST_COLUMNS)


def _timestamps(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy(deep=True)
    for column in columns:
        result[column] = pd.to_datetime(result[column], errors="coerce")
    if "coverage_status" not in result.columns:
        if result.loc[:, list(columns)].isna().any().any():
            raise ValueError("causal features require valid issue_time and available_time")
        return result
    if "quality_status" not in result.columns or "observed_time" not in result.columns:
        raise ValueError("coverage_status requires Task 7 quality and observed timestamps")
    result["observed_time"] = pd.to_datetime(result["observed_time"], errors="coerce")
    coverage = result["coverage_status"].astype(str).str.strip()
    if not coverage.isin(("observed", "not_observed")).all():
        raise ValueError("coverage_status must be observed or not_observed")
    unobserved = coverage.eq("not_observed")
    if not result.loc[unobserved, "quality_status"].astype(str).eq("not_observed").all():
        raise ValueError("not_observed rows require not_observed quality_status")
    if result.loc[unobserved, ["observed_time", *columns]].notna().any().any():
        raise ValueError("not_observed rows require null Task 7 timestamps")
    observed = ~unobserved
    if result.loc[observed, ["observed_time", *columns]].isna().any().any():
        raise ValueError("observed rows require causal timestamps")
    if observed.any() and not (
        result.loc[observed, "observed_time"].le(result.loc[observed, "available_time"])
        & result.loc[observed, "available_time"].le(result.loc[observed, "issue_time"])
    ).all():
        raise ValueError("observed rows require causal timestamps")
    return result


def _mechanism_cutoff(frame: pd.DataFrame) -> pd.Series:
    """Return the only accepted mechanism driver-cutoff timestamp contract."""
    if "mechanism_driver_cutoff_time" not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    cutoff = pd.to_datetime(frame["mechanism_driver_cutoff_time"], errors="coerce")
    return cutoff


def _invalid_grid_id_literal_mask(values: pd.Series) -> pd.Series:
    """Identify null-string sentinels without treating valid substrings as null."""
    return values.astype(str).str.strip().str.casefold().isin(_INVALID_GRID_ID_LITERALS)


def _validate_v03_keys_and_dates(result: pd.DataFrame, config, context: str) -> pd.DataFrame:
    """Normalize and validate V0.3 grid/day identity at a public boundary."""
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    if result["date"].isna().any() or not result["date"].eq(result["date"].dt.normalize()).all():
        raise ValueError(f"{context} requires midnight dates")
    if result["grid_id"].isna().any():
        raise ValueError(f"{context} requires valid grid_id")
    result["grid_id"] = result["grid_id"].astype(str)
    if result["grid_id"].str.strip().eq("").any() or _invalid_grid_id_literal_mask(result["grid_id"]).any():
        raise ValueError(f"{context} requires non-blank grid_id")
    try:
        start = pd.Timestamp(config.start_date).normalize()
        end = pd.Timestamp(config.end_date).normalize()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{context} config requires valid date bounds") from exc
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError(f"{context} config requires valid date bounds")
    if result["date"].lt(start).any() or result["date"].gt(end).any():
        raise ValueError(f"{context} dates fall outside config range")
    if result.duplicated(["grid_id", "date"]).any():
        raise ValueError(f"{context} requires unique grid_id/date rows")
    return result


def _calendar_rolling(values: pd.Series, result: pd.DataFrame, window: int) -> pd.DataFrame:
    """Compute strictly-prior grid-local calendar-window statistics."""
    source = pd.DataFrame({"grid_id": result["grid_id"].to_numpy(), "date": result["date"].to_numpy(), "value": values.to_numpy()})
    rolling = source.groupby("grid_id", sort=False, observed=True).rolling(
        f"{window}D", on="date", closed="left", min_periods=1
    )["value"]
    keys = pd.MultiIndex.from_frame(result.loc[:, ["grid_id", "date"]])

    def align(series: pd.Series) -> pd.Series:
        return pd.Series(series.reindex(keys).to_numpy(), index=result.index)

    return pd.DataFrame(
        {
            "mean": align(rolling.mean()),
            "max": align(rolling.max()),
            "min": align(rolling.min()),
            "std": align(rolling.std(ddof=0)),
            "count": align(rolling.count()).fillna(0).astype("int64"),
        },
        index=result.index,
    )


def build_causal_features(frame: pd.DataFrame, config) -> pd.DataFrame:
    """Build causal feature columns without mutating ``frame``.

    A dynamic value is first made invisible unless it was available no later
    than that row's issue time.  Group-local shifts then ensure neither the
    current row nor a different grid contributes to lag or rolling features.
    Mechanism values require their explicit driver-cutoff timestamp too.
    """
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a DataFrame")
    required = {"grid_id", "date", "issue_time", "available_time"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"causal feature source columns missing: {missing}")
    result = _timestamps(frame, ("issue_time", "available_time"))
    result = _validate_v03_keys_and_dates(result, config, "causal features")
    result = result.sort_values(["grid_id", "date"], kind="mergesort").reset_index(drop=True)
    visible = result["available_time"].le(result["issue_time"])
    groups = result.groupby("grid_id", sort=False, observed=True)
    feature_columns: dict[str, pd.Series | np.ndarray] = {}

    day_of_year = result["date"].dt.dayofyear.astype(float)
    day_of_week = result["date"].dt.dayofweek.astype(float)
    feature_columns["calendar_day_of_year_sin"] = np.sin(2.0 * np.pi * day_of_year / 365.25)
    feature_columns["calendar_day_of_year_cos"] = np.cos(2.0 * np.pi * day_of_year / 365.25)
    feature_columns["calendar_day_of_week_sin"] = np.sin(2.0 * np.pi * day_of_week / 7.0)
    feature_columns["calendar_day_of_week_cos"] = np.cos(2.0 * np.pi * day_of_week / 7.0)

    for column in OBSERVABLE_DYNAMIC_COLUMNS:
        if column in result.columns:
            values = pd.to_numeric(result[column], errors="coerce").where(visible)
        else:
            values = pd.Series(np.nan, index=result.index, dtype=float)
        feature_columns[column] = values
        feature_columns[f"{column}_missing"] = values.isna().astype("int8")
        value_groups = values.groupby(result["grid_id"], sort=False, observed=True)
        for lag in LAGS:
            shifted = value_groups.shift(lag)
            shifted_dates = groups["date"].shift(lag)
            feature_columns[f"{column}_lag_{lag}d"] = shifted.where(shifted_dates.eq(result["date"] - pd.Timedelta(days=lag)))
        for window in ROLLING_WINDOWS:
            rolling = _calendar_rolling(values, result, window)
            feature_columns[f"{column}_rolling_mean_{window}d"] = rolling["mean"]
            feature_columns[f"{column}_rolling_max_{window}d"] = rolling["max"]
            feature_columns[f"{column}_rolling_min_{window}d"] = rolling["min"]
            feature_columns[f"{column}_rolling_std_{window}d"] = rolling["std"]
            feature_columns[f"{column}_rolling_count_{window}d"] = rolling["count"]
        feature_columns[f"{column}_change_1d"] = values - feature_columns[f"{column}_lag_1d"]
        feature_columns[f"{column}_change_7d"] = values - feature_columns[f"{column}_lag_7d"]

    cutoff = _mechanism_cutoff(result)
    mechanism_visible = cutoff.notna() & cutoff.le(result["issue_time"])
    for column in (*MECHANISM_STATE_COLUMNS, *MECHANISM_FORECAST_COLUMNS):
        if column in result.columns:
            feature_columns[column] = pd.to_numeric(result[column], errors="coerce").where(mechanism_visible)
        else:
            feature_columns[column] = np.nan
    retained = result.drop(columns=[name for name in feature_columns if name in result.columns])
    return pd.concat((retained, pd.DataFrame(feature_columns, index=result.index)), axis=1)
