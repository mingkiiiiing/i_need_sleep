"""Anchor-conditioned, mechanism-informed water-quality state generation."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .random_streams import ComponentCode, make_rng


_CORE = (
    "total_phosphorus_mg_L", "total_nitrogen_mg_L", "dissolved_oxygen_mg_L", "ph",
)
_OUTPUT = (*_CORE, "phytoplankton_biomass_mg_L")
_DRIVER_COLUMNS = (
    "date", "grid_id", "grid_numeric_id", "experimental_zone_id", "precipitation_mm_day",
    "water_temperature_C", "solar_radiation_MJ_m2_day", "flow_speed_m_s", "mixing_index",
)
_RANGES = ((1e-6, 1.0), (1e-6, 20.0), (0.0, 25.0), (5.5, 10.5), (1e-6, 100.0))


@dataclass(frozen=True)
class WaterQualityState:
    """Immutable transformed per-grid state; tuples make equality deterministic."""

    last_date: pd.Timestamp
    grid_ids: tuple[str, ...]
    transformed_values: tuple[tuple[float, float, float, float, float], ...]


# Fixed PSD template (factor construction), intentionally mechanism-informed rather than empirical.
_MECHANISM_FACTOR = np.array([
    [1.00, 0.10], [0.72, 0.14], [-0.40, 0.72], [0.12, 0.68], [0.56, -0.36],
], dtype=float)
_MECHANISM_COVARIANCE = _MECHANISM_FACTOR @ _MECHANISM_FACTOR.T + np.eye(5) * 0.12
_MECHANISM_CHOL = np.linalg.cholesky(_MECHANISM_COVARIANCE)


def _driver_frame(drivers: pd.DataFrame):
    if not isinstance(drivers, pd.DataFrame):
        raise ValueError("drivers must be a DataFrame")
    missing = sorted(set(_DRIVER_COLUMNS) - set(drivers.columns))
    if missing:
        raise ValueError(f"drivers fields missing: {missing}")
    frame = drivers.loc[:, _DRIVER_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any() or frame[["grid_id", "grid_numeric_id", "experimental_zone_id"]].isna().any().any():
        raise ValueError("drivers have invalid keys")
    frame["grid_id"] = frame["grid_id"].astype(str)
    frame["experimental_zone_id"] = frame["experimental_zone_id"].astype(str)
    frame["grid_numeric_id"] = pd.to_numeric(frame["grid_numeric_id"], errors="coerce")
    numeric_values = frame["grid_numeric_id"].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all() or not np.equal(numeric_values, np.floor(numeric_values)).all() or (numeric_values < 0).any():
        raise ValueError("drivers have invalid grid_numeric_id")
    frame["grid_numeric_id"] = frame["grid_numeric_id"].astype(int)
    for column in _DRIVER_COLUMNS[4:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(_DRIVER_COLUMNS[4:])].isna().any().any() or not np.isfinite(frame[list(_DRIVER_COLUMNS[4:])].to_numpy()).all():
        raise ValueError("drivers contain non-finite fields")
    dates = pd.DatetimeIndex(pd.unique(frame["date"]))
    if len(dates) == 0 or not dates.is_monotonic_increasing or not np.all((dates[1:] - dates[:-1]) == pd.Timedelta(days=1)):
        raise ValueError("drivers dates must be sorted and contiguous")
    first = frame.loc[frame["date"].eq(dates[0]), ["grid_id", "grid_numeric_id", "experimental_zone_id"]]
    grid_ids = tuple(first["grid_id"])
    if not grid_ids or len(set(grid_ids)) != len(grid_ids):
        raise ValueError("drivers have duplicate grid IDs")
    expected = [(date, grid_id) for date in dates for grid_id in grid_ids]
    actual = list(zip(frame["date"], frame["grid_id"]))
    if actual != expected:
        raise ValueError("drivers date/grid ordering must be sorted and complete")
    mapping = list(zip(first["grid_id"], first["grid_numeric_id"], first["experimental_zone_id"]))
    expected_mapping = mapping * len(dates)
    actual_mapping = list(zip(frame["grid_id"], frame["grid_numeric_id"], frame["experimental_zone_id"]))
    if actual_mapping != expected_mapping:
        raise ValueError("drivers grid mapping differs across dates")
    zone_labels = first["experimental_zone_id"].to_numpy()
    numeric_ids = first["grid_numeric_id"].to_numpy(dtype=int)
    return frame, dates, grid_ids, numeric_ids, zone_labels


def _profile(anchor_profile):
    if not isinstance(anchor_profile, dict):
        raise ValueError("anchor profile must be a mapping")
    missing = sorted(set(_CORE) - set(anchor_profile))
    if missing:
        raise ValueError(f"anchor profile required variables missing: {missing}")
    profile = dict(anchor_profile)
    if "phytoplankton_biomass_mg_L" not in profile:
        profile["phytoplankton_biomass_mg_L"] = {
            "median": 4.0, "q05": 1.0, "q25": 2.5, "q75": 6.5, "q95": 11.0,
            "fallback": "conservative_no_training_profile",
        }
    medians, scales = [], []
    for index, name in enumerate(_OUTPUT):
        item = profile.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"anchor profile invalid for {name}")
        try:
            values = [float(item[key]) for key in ("median", "q05", "q25", "q75", "q95")]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"anchor profile invalid for {name}") from exc
        if not np.isfinite(values).all() or not (values[1] <= values[2] <= values[0] <= values[3] <= values[4]):
            raise ValueError(f"anchor profile invalid quantiles for {name}")
        low, high = _RANGES[index]
        if not low < values[0] <= high:
            raise ValueError(f"anchor profile median outside hard range for {name}")
        median = values[0]
        if index in (0, 1, 4):
            scale = max((np.log(max(values[3], low)) - np.log(max(values[2], low))) / 1.349, 0.08)
            medians.append(np.log(median))
        else:
            scale = max((values[3] - values[2]) / 1.349, 0.08 if index == 3 else 0.35)
            medians.append(median)
        scales.append(scale)
    return np.asarray(medians), np.asarray(scales), profile


def _state_or_initial(state, dates, grid_ids, medians):
    if state is None:
        return np.tile(medians, (len(grid_ids), 1))
    if not isinstance(state, WaterQualityState):
        raise ValueError("invalid water-quality state")
    if tuple(state.grid_ids) != tuple(grid_ids):
        raise ValueError("water-quality state grid ordering differs from drivers")
    if pd.Timestamp(state.last_date) != dates[0] - pd.Timedelta(days=1):
        raise ValueError("water-quality state last_date does not make the block contiguous")
    values = np.asarray(state.transformed_values, dtype=float)
    if values.shape != (len(grid_ids), 5) or not np.isfinite(values).all():
        raise ValueError("invalid water-quality state values")
    return values.copy()


def _zone_numbers(labels):
    return {label: index + 1 for index, label in enumerate(sorted(set(labels)))}


def _year_innovations(config, dates, zone_labels, numeric_ids):
    """Create bounded, call-local grid-year innovation arrays for O(1) day lookup."""
    innovations = {}
    zones = _zone_numbers(zone_labels)
    for year in sorted(set(dates.year)):
        days_in_year = 366 if pd.Timestamp(year, 12, 31).dayofyear == 366 else 365
        for index, (zone_label, numeric_id) in enumerate(zip(zone_labels, numeric_ids)):
            rng = make_rng(config, ComponentCode.WATER_QUALITY, int(year), zones[str(zone_label)], int(numeric_id))
            innovations[(int(year), index)] = _MECHANISM_CHOL @ rng.normal(size=(days_in_year, 5)).T
    return innovations, zones


def generate_water_quality_block(drivers, anchor_profile, initial_state, config):
    """Generate bounded water-quality values from marginal training anchors and driver states."""
    frame, dates, grid_ids, numeric_ids, zone_labels = _driver_frame(drivers)
    medians, scales, profile = _profile(anchor_profile)
    state = _state_or_initial(initial_state, dates, grid_ids, medians)
    innovations, zones = _year_innovations(config, dates, zone_labels, numeric_ids)
    records = []
    width = len(grid_ids)
    phyto_reference = float(np.exp(medians[4]))
    for date_index, date in enumerate(dates):
        rows = frame.iloc[date_index * width:(date_index + 1) * width]
        for local_index, row in enumerate(rows.itertuples(index=False)):
            previous = state[local_index].copy()
            rain_loading = min(float(row.precipitation_mm_day), 260.0) / 100.0
            temperature = float(row.water_temperature_C)
            solar = float(row.solar_radiation_MJ_m2_day)
            biomass_previous = float(np.exp(previous[4]))
            equilibrium = medians.copy()
            equilibrium[0] += 0.060 * rain_loading + 0.006 * float(row.flow_speed_m_s)
            equilibrium[1] += 0.045 * rain_loading
            equilibrium[4] += 0.035 * (temperature - 20.0) + 0.020 * (solar - 15.0) + 0.012 * rain_loading
            equilibrium[2] += -0.18 * (temperature - 20.0) - 0.055 * (biomass_previous - phyto_reference)
            equilibrium[3] += 0.018 * (biomass_previous - phyto_reference)
            noise = innovations[(int(date.year), local_index)][:, int(date.dayofyear) - 1]
            state[local_index] = 0.90 * previous + 0.10 * equilibrium + 0.18 * scales * noise
            values = np.array([
                np.exp(state[local_index, 0]), np.exp(state[local_index, 1]), state[local_index, 2],
                state[local_index, 3], np.exp(state[local_index, 4]),
            ])
            values = np.array([np.clip(value, low, high) for value, (low, high) in zip(values, _RANGES)])
            state[local_index, 0] = np.log(values[0])
            state[local_index, 1] = np.log(values[1])
            state[local_index, 2] = values[2]
            state[local_index, 3] = values[3]
            state[local_index, 4] = np.log(values[4])
            records.append({
                "date": date, "grid_id": row.grid_id, "grid_numeric_id": int(row.grid_numeric_id),
                "experimental_zone_id": row.experimental_zone_id,
                **{name: float(value) for name, value in zip(_OUTPUT, values)},
                "water_quality_source_class": "synthetic_derived", "water_quality_covariance_method": "mechanism_informed_psd_template",
                "anchor_profile_basis": "training_only_marginal_profiles", "data_mode": "simulation", "is_ground_truth": 0,
                "claim_boundary": config.claim_boundary, "base_seed": int(config.base_seed),
                "generator_version": config.generator_version, "data_version": config.data_version,
            })
    output = pd.DataFrame.from_records(records)
    next_state = WaterQualityState(
        last_date=pd.Timestamp(dates[-1]), grid_ids=tuple(grid_ids),
        transformed_values=tuple(tuple(float(value) for value in row) for row in state),
    )
    return output, next_state
