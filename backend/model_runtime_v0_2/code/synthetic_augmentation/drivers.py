"""Deterministic gridded weather and compact hydrological state evolution."""

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .random_streams import ComponentCode, make_rng
from .sources import POWER_COLUMN_MAP


@dataclass(frozen=True)
class DriverState:
    """Carry state expressed as immutable scalar tuples for deterministic equality."""

    last_date: pd.Timestamp
    grid_ids: tuple[str, ...]
    rainfall_memory: tuple[float, ...]
    air_micro: tuple[float, ...]
    water_temperature: tuple[float, ...]
    water_level: tuple[float, ...]
    flow_speed: tuple[float, ...]
    mixing_index: tuple[float, ...]


_METADATA_COLUMNS = (
    "grid_id", "grid_numeric_id", "experimental_zone_id", "centroid_x_m",
    "centroid_y_m", "mean_water_depth_m",
)
_WEATHER_COLUMNS = tuple(POWER_COLUMN_MAP.values())


def _as_dates(dates: Iterable) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce"))
    if len(result) == 0 or result.isna().any() or result.has_duplicates:
        raise ValueError("dates must be a non-empty, unique calendar")
    if not result.is_monotonic_increasing or not np.all((result[1:] - result[:-1]) == pd.Timedelta(days=1)):
        raise ValueError("dates must be sorted and contiguous daily")
    return result


def _metadata_frame(metadata: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(metadata, pd.DataFrame):
        raise ValueError("metadata must be a DataFrame")
    missing = sorted(set(_METADATA_COLUMNS) - set(metadata.columns))
    if missing:
        raise ValueError(f"metadata columns missing: {missing}")
    frame = metadata.loc[:, _METADATA_COLUMNS].copy()
    if frame["grid_id"].isna().any() or frame["grid_id"].astype(str).str.len().eq(0).any():
        raise ValueError("metadata has missing grid IDs")
    if frame["grid_id"].duplicated().any() or frame["grid_numeric_id"].duplicated().any():
        raise ValueError("metadata has duplicate grid IDs")
    for column in ("grid_numeric_id", "centroid_x_m", "centroid_y_m", "mean_water_depth_m"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any() or not np.isfinite(frame[column]).all():
            raise ValueError(f"metadata has non-finite {column}")
    numeric = frame["grid_numeric_id"].to_numpy(dtype=float)
    if not np.equal(numeric, np.floor(numeric)).all() or (numeric < 0).any():
        raise ValueError("metadata grid_numeric_id must be non-negative integers")
    if frame["experimental_zone_id"].isna().any():
        raise ValueError("metadata has missing experimental_zone_id")
    frame["grid_id"] = frame["grid_id"].astype(str)
    frame["grid_numeric_id"] = frame["grid_numeric_id"].astype(int)
    return frame.sort_values(["grid_numeric_id", "grid_id"], kind="mergesort").reset_index(drop=True)


def _weather_frame(dates: pd.DatetimeIndex, weather: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(weather, pd.DataFrame) or "date" not in weather.columns:
        raise ValueError("weather must include date")
    missing = sorted(set(_WEATHER_COLUMNS) - set(weather.columns))
    if missing:
        raise ValueError(f"weather columns missing: {missing}")
    frame = weather.loc[:, ["date", *_WEATHER_COLUMNS]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise ValueError("weather has invalid or duplicate dates")
    for column in _WEATHER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(_WEATHER_COLUMNS)].isna().any().any() or not np.isfinite(frame[list(_WEATHER_COLUMNS)].to_numpy(dtype=float)).all():
        raise ValueError("weather contains non-finite NASA values")
    frame = frame.set_index("date")
    missing_dates = dates.difference(frame.index)
    if len(missing_dates):
        raise ValueError("weather calendar is incomplete for requested dates")
    return frame.loc[dates]


def _zone_numbers(frame: pd.DataFrame) -> dict[str, int]:
    labels = sorted(frame["experimental_zone_id"].astype(str).unique())
    return {label: index + 1 for index, label in enumerate(labels)}


def _state_or_initial(state, dates: pd.DatetimeIndex, grid_ids: tuple[str, ...]):
    size = len(grid_ids)
    if state is None:
        return (np.zeros(size), np.zeros(size), np.full(size, 18.0), np.full(size, 3.2),
                np.full(size, 0.12), np.full(size, 0.35))
    if not isinstance(state, DriverState):
        raise ValueError("invalid driver state")
    if tuple(state.grid_ids) != grid_ids:
        raise ValueError("driver state grid ordering differs from metadata")
    if pd.Timestamp(state.last_date) != dates[0] - pd.Timedelta(days=1):
        raise ValueError("driver state last_date does not make the block contiguous")
    values = (state.rainfall_memory, state.air_micro, state.water_temperature,
              state.water_level, state.flow_speed, state.mixing_index)
    if any(len(value) != size for value in values):
        raise ValueError("invalid driver state size")
    arrays = tuple(np.asarray(value, dtype=float) for value in values)
    if not all(np.isfinite(value).all() for value in arrays):
        raise ValueError("invalid non-finite driver state")
    return arrays


def _year_innovations(config, component, dates, metadata, zones, count: int):
    """Bound each component's random work to one full grid-year array per block.

    Arrays are local to the call (never a global cache), so a later contiguous
    block reproduces the same coordinate/day innovation by indexing its own
    identical year array.
    """
    innovations = {}
    for year in sorted(set(dates.year)):
        days_in_year = 366 if pd.Timestamp(year, 12, 31).dayofyear == 366 else 365
        for index, row in enumerate(metadata.itertuples(index=False)):
            zone = zones[str(row.experimental_zone_id)]
            rng = make_rng(config, component, int(year), zone, int(row.grid_numeric_id))
            innovations[(int(year), index)] = rng.normal(size=(days_in_year, count))
    return innovations


def generate_driver_block(dates, metadata, weather, initial_state, config):
    """Generate one contiguous date-grid block and a carry state for its next block."""
    dates = _as_dates(dates)
    metadata = _metadata_frame(metadata)
    weather = _weather_frame(dates, weather)
    grid_ids = tuple(metadata["grid_id"])
    rain_memory, air_micro, water_temp, water_level, flow_speed, mixing = _state_or_initial(
        initial_state, dates, grid_ids
    )
    zones = _zone_numbers(metadata)
    static = []
    for row in metadata.itertuples(index=False):
        zone = zones[str(row.experimental_zone_id)]
        rng = make_rng(config, ComponentCode.WEATHER, 0, zone, int(row.grid_numeric_id))
        static.append(rng.normal(size=4))
    static = np.asarray(static)
    # Low-frequency coordinate terms keep neighboring grids meteorologically similar;
    # seeded residuals remain deliberately small and are not used as an external claim.
    x = metadata["centroid_x_m"].to_numpy(dtype=float)
    y = metadata["centroid_y_m"].to_numpy(dtype=float)
    x_scale = max(float(np.ptp(x)), 1_000.0)
    y_scale = max(float(np.ptp(y)), 1_000.0)
    x_phase = (x - float(x.mean())) / x_scale * np.pi
    y_phase = (y - float(y.mean())) / y_scale * np.pi
    smooth = np.column_stack((
        0.55 * np.sin(x_phase) + 0.30 * np.cos(y_phase),
        0.24 * np.cos(x_phase) + 0.12 * np.sin(y_phase),
        0.18 * np.sin(x_phase + y_phase),
        0.20 * np.cos(x_phase - y_phase),
    ))
    static = 0.18 * static + smooth
    weather_innovations = _year_innovations(
        config, ComponentCode.WEATHER, dates, metadata, zones, count=3
    )
    hydrology_innovations = _year_innovations(
        config, ComponentCode.HYDROLOGY, dates, metadata, zones, count=2
    )
    records = []
    for date in dates:
        lake = weather.loc[date]
        lake_values = {f"lake_{column}": float(lake[column]) for column in _WEATHER_COLUMNS}
        for index, row in enumerate(metadata.itertuples(index=False)):
            weather_noise = weather_innovations[(int(date.year), index)][int(date.dayofyear) - 1]
            hydro_noise = hydrology_innovations[(int(date.year), index)][int(date.dayofyear) - 1]
            air_micro[index] = 0.76 * air_micro[index] + 0.24 * weather_noise[0]
            air = float(np.clip(lake.air_temperature_C + 0.42 * static[index, 0] + 0.95 * air_micro[index], -20, 45))
            precipitation = float(np.clip(lake.precipitation_mm_day * (1 + 0.045 * static[index, 1]) + 0.18 * weather_noise[1], 0, 260))
            wind = float(np.clip(lake.wind_speed_m_s + 0.20 * static[index, 2] + 0.12 * weather_noise[2], 0, 25))
            direction = float((lake.wind_direction_deg + 5.0 * static[index, 3]) % 360)
            solar = float(np.clip(lake.solar_radiation_MJ_m2_day + 0.35 * static[index, 1], 0, 40))
            humidity = float(np.clip(lake.relative_humidity_pct - 0.6 * static[index, 0], 0, 100))
            pressure = float(np.clip(lake.surface_pressure_kPa + 0.05 * static[index, 2], 90, 110))
            rain_memory[index] = 0.82 * rain_memory[index] + precipitation
            depth_adjustment = 0.10 * (float(row.mean_water_depth_m) - 2.5)
            water_temp[index] = float(np.clip(
                water_temp[index] + 0.13 * (air - water_temp[index]) + 0.012 * solar + 0.05 * hydro_noise[0], 0, 38
            ))
            seasonal = 0.035 * np.sin(2 * np.pi * date.dayofyear / 365.25)
            water_level[index] = float(np.clip(
                0.82 * water_level[index] + 0.18 * (3.18 + depth_adjustment + 0.0065 * rain_memory[index] + seasonal)
                + 0.004 * hydro_noise[0], 2, 5
            ))
            flow_speed[index] = float(np.clip(
                0.73 * flow_speed[index] + 0.27 * (0.025 + 0.007 * precipitation + 0.018 * wind + 0.0012 * rain_memory[index])
                + 0.006 * hydro_noise[1], 0, 1.5
            ))
            mixing[index] = float(np.clip(
                0.70 * mixing[index] + 0.30 * (1 / (1 + np.exp(-(0.30 * wind + 0.9 * flow_speed[index] - 1.25))))
                + 0.006 * hydro_noise[1], 0, 1
            ))
            records.append({
                "date": date, "grid_id": row.grid_id, "grid_numeric_id": int(row.grid_numeric_id),
                "experimental_zone_id": row.experimental_zone_id, **lake_values,
                "air_temperature_C": air, "precipitation_mm_day": precipitation,
                "wind_speed_m_s": wind, "wind_direction_deg": direction,
                "solar_radiation_MJ_m2_day": solar, "relative_humidity_pct": humidity,
                "surface_pressure_kPa": pressure, "water_temperature_C": water_temp[index],
                "water_level_m": water_level[index], "flow_speed_m_s": flow_speed[index],
                "mixing_index": mixing[index], "weather_source_class": "external_reanalysis",
                "driver_source_class": "synthetic_derived", "data_mode": "simulation", "is_ground_truth": 0,
                "claim_boundary": config.claim_boundary, "base_seed": int(config.base_seed),
                "generator_version": config.generator_version, "data_version": config.data_version,
            })
    output = pd.DataFrame.from_records(records)
    state = DriverState(
        last_date=pd.Timestamp(dates[-1]), grid_ids=grid_ids,
        rainfall_memory=tuple(float(value) for value in rain_memory), air_micro=tuple(float(value) for value in air_micro),
        water_temperature=tuple(float(value) for value in water_temp), water_level=tuple(float(value) for value in water_level),
        flow_speed=tuple(float(value) for value in flow_speed), mixing_index=tuple(float(value) for value in mixing),
    )
    return output, state
