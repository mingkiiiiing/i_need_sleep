from __future__ import annotations

import pandas as pd

from .features import _invalid_grid_id_literal_mask


TARGET_COLUMNS = {
    "bloom_label": "target_bloom",
    "bloom_probability": "target_bloom_probability",
    "bloom_area_km2": "target_bloom_area_km2",
    "blue_algae_biomass_mg_L": "target_blue_algae_biomass_mg_L",
    "chlorophyll_a_ug_L": "target_chlorophyll_a_ug_L",
    "bloom_risk_level": "target_bloom_risk_level",
}


V03_TARGET_COLUMNS = {
    "bloom_label": "target_bloom",
    "bloom_probability": "target_bloom_probability",
    "bloom_area_km2": "target_bloom_area_km2",
    "bloom_coverage_ratio": "target_bloom_coverage_ratio",
    "cyanobacteria_density_cells_L": "target_cyanobacteria_density_cells_L",
    "blue_algae_biomass_mg_L": "target_blue_algae_biomass_mg_L",
    "chlorophyll_a_ug_L": "target_chlorophyll_a_ug_L",
    "bloom_risk_level": "target_bloom_risk_level",
}


def _v03_horizons(config) -> tuple[int, ...]:
    try:
        horizons = tuple(int(value) for value in config.horizons)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("V0.3 config must provide forecast horizons") from exc
    if horizons != (1, 3, 7, 15, 30):
        raise ValueError("V0.3 forecast horizons must be exactly (1, 3, 7, 15, 30)")
    return horizons


def _v04_horizons(config) -> tuple[int, ...]:
    try:
        horizons = tuple(int(value) for value in config.horizons)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("V0.4 config must provide forecast horizons") from exc
    if horizons != (1, 3, 7, 15, 30, 60, 90):
        raise ValueError(
            "V0.4 forecast horizons must be exactly (1, 3, 7, 15, 30, 60, 90)"
        )
    return horizons


def _validate_v03_keys_and_dates(result: pd.DataFrame, config) -> pd.DataFrame:
    """Normalize and validate V0.3 grid/day identity at the forecast boundary."""
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    if result["date"].isna().any() or not result["date"].eq(result["date"].dt.normalize()).all():
        raise ValueError("V0.3 forecast source requires midnight dates")
    if result["grid_id"].isna().any():
        raise ValueError("V0.3 forecast source has invalid grid_id")
    result["grid_id"] = result["grid_id"].astype(str)
    if result["grid_id"].str.strip().eq("").any() or _invalid_grid_id_literal_mask(result["grid_id"]).any():
        raise ValueError("V0.3 forecast source requires non-blank grid_id")
    try:
        start = pd.Timestamp(config.start_date).normalize()
        end = pd.Timestamp(config.end_date).normalize()
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("V0.3 config requires valid date bounds") from exc
    if pd.isna(start) or pd.isna(end) or start > end:
        raise ValueError("V0.3 config requires valid date bounds")
    if result["date"].lt(start).any() or result["date"].gt(end).any():
        raise ValueError("V0.3 forecast source dates fall outside config range")
    if result.duplicated(["grid_id", "date"]).any():
        raise ValueError("V0.3 forecast source requires unique grid_id/date rows")
    return result


def assign_split(date: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(date)
    if timestamp.year <= 2017:
        return "train"
    if timestamp.year <= 2021:
        return "validation"
    return "test"


def build_forecast_samples(
    frame: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 3, 7, 15, 30, 90),
) -> pd.DataFrame:
    required = {"sample_id", "date", "spatial_id", *TARGET_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"forecast source columns missing: {missing}")
    if not horizons or any(int(horizon) <= 0 for horizon in horizons):
        raise ValueError("forecast horizons must be positive")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    result = result.sort_values(["spatial_id", "date"]).reset_index(drop=True)
    result["dataset_split"] = result["date"].map(assign_split)
    grouped = result.groupby("spatial_id", sort=False, observed=True)

    for horizon in tuple(int(value) for value in horizons):
        date_column = f"target_date_{horizon}d"
        result[date_column] = grouped["date"].shift(-horizon)
        target_split = result[date_column].map(
            lambda value: assign_split(value) if pd.notna(value) else pd.NA
        )
        same_split = target_split.eq(result["dataset_split"]).fillna(False)
        for source_column, target_prefix in TARGET_COLUMNS.items():
            output_column = f"{target_prefix}_{horizon}d"
            shifted = grouped[source_column].shift(-horizon)
            result[output_column] = shifted.where(same_split)
        result.loc[~same_split, date_column] = pd.NaT

    return result


def _build_grid_forecast_samples(
    frame: pd.DataFrame, config, horizons: tuple[int, ...], version: str
) -> pd.DataFrame:
    """Attach exact-date targets and explicit split/tail embargo flags.

    Targets are joined by ``grid_id`` and ``date + horizon`` rather than by
    positional shifting, so a missing source date can never silently turn into
    a wrong target date.  Nullable bloom labels retain their unknown state;
    embargo is about absent/cross-split target *rows*, not label class.
    """
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a DataFrame")
    required = {"grid_id", "date", *V03_TARGET_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{version} forecast source columns missing: {missing}")
    result = frame.copy(deep=True)
    result = _validate_v03_keys_and_dates(result, config)
    result = result.sort_values(["grid_id", "date"], kind="mergesort").reset_index(drop=True)
    result["dataset_split"] = result["date"].map(assign_split)

    future_values = result.loc[:, ["grid_id", "date", *V03_TARGET_COLUMNS]].copy()
    for horizon in horizons:
        join_values = future_values.copy()
        join_values["date"] = join_values["date"] - pd.Timedelta(days=horizon)
        renamed = {
            source: f"{prefix}_{horizon}d"
            for source, prefix in V03_TARGET_COLUMNS.items()
        }
        join_values = join_values.rename(columns=renamed)
        join_values[f"target_date_{horizon}d"] = join_values["date"] + pd.Timedelta(days=horizon)
        merged = result.loc[:, ["grid_id", "date"]].merge(join_values, on=["grid_id", "date"], how="left", sort=False)
        target_date = merged[f"target_date_{horizon}d"]
        target_split = target_date.map(lambda value: assign_split(value) if pd.notna(value) else pd.NA)
        valid = target_date.notna() & target_split.eq(result["dataset_split"])
        result[f"target_embargo_{horizon}d"] = (~valid).astype("int8")
        result[f"target_date_{horizon}d"] = target_date.where(valid)
        for prefix in V03_TARGET_COLUMNS.values():
            name = f"{prefix}_{horizon}d"
            result[name] = merged[name].where(valid)
    return result


def build_v03_forecast_samples(frame: pd.DataFrame, config) -> pd.DataFrame:
    """Attach exact-date V0.3 targets without changing its five-horizon contract."""
    return _build_grid_forecast_samples(
        frame, config, _v03_horizons(config), "V0.3"
    )


def build_v04_forecast_samples(frame: pd.DataFrame, config) -> pd.DataFrame:
    """Attach exact-date V0.4 targets for all seven frozen horizons."""
    return _build_grid_forecast_samples(
        frame, config, _v04_horizons(config), "V0.4"
    )
