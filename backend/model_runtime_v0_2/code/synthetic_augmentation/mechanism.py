"""Compact, auditable daily cyanobacteria growth/loss mechanism for V0.3.

The model is a synthetic-development state model, not calibrated evidence of
Taihu field biomass.  All ``*_rate_d`` output fields are finite daily rates in
``day^-1``; limitation and capacity factors are dimensionless in ``[0, 1]``.
"""

from dataclasses import dataclass
import hashlib
import json
from numbers import Integral
from types import MappingProxyType
from typing import Mapping

import numpy as np
import pandas as pd


MECHANISM_MODEL_VERSION = "TAIHU_COMPACT_CYANOBACTERIA_MECHANISM_V0.3"
_CLAIM_BOUNDARY = "synthetic_development_only"
_REQUIRED_VISIBLE = (
    "water_temperature_C", "total_nitrogen_mg_L", "total_phosphorus_mg_L",
    "solar_radiation_MJ_m2_day", "mixing_index",
)
_KEY_COLUMNS = ("date", "grid_id", "grid_numeric_id", "experimental_zone_id")
_FACTOR_COLUMNS = (
    "temperature_factor", "nitrogen_factor", "phosphorus_factor", "nutrient_factor",
    "light_factor", "capacity_factor",
)
_RATE_COLUMNS = (
    "gross_growth_rate_d", "respiration_rate_d", "mortality_rate_d",
    "mixing_loss_rate_d", "net_growth_rate_d",
)


def _parameter(name, unit, source_class, lower, default, upper, scope):
    return MappingProxyType({
        "name": name, "unit": unit, "source_class": source_class,
        "lower_bound": lower, "default": default, "upper_bound": upper,
        "sampling_scope": scope,
    })


# Literature-informed parameters are deliberately ranges, not calibrated Taihu truths.
MECHANISM_PARAMETER_TABLE = (
    _parameter("mu_max_d", "day^-1", "literature_informed_range", 0.20, 0.55, 0.80, "realization"),
    _parameter("temperature_optimum_C", "degC", "literature_informed_range", 25.0, 27.0, 29.0, "realization"),
    _parameter("temperature_cold_width_C", "degC", "literature_informed_range", 6.0, 11.0, 18.0, "realization"),
    _parameter("temperature_hot_width_C", "degC", "literature_informed_range", 4.0, 8.0, 15.0, "realization"),
    _parameter("K_N_mg_L", "mg/L", "literature_informed_range", 0.10, 0.50, 2.00, "zone"),
    _parameter("K_P_mg_L", "mg/L", "literature_informed_range", 0.005, 0.030, 0.150, "zone"),
    _parameter("light_half_saturation_MJ_m2_day", "MJ/m2/day", "literature_informed_range", 2.0, 8.0, 20.0, "realization"),
    _parameter("self_shading_per_mg_L", "L/mg", "mechanism_assumption", 0.005, 0.025, 0.080, "grid"),
    _parameter("self_shading_fallback_biomass_mg_L", "mg/L", "conservative_fallback", 0.5, 3.0, 8.0, "grid"),
    _parameter("carrying_capacity_mg_L", "mg/L", "mechanism_assumption", 20.0, 32.0, 45.0, "grid"),
    _parameter("base_respiration_d", "day^-1", "literature_informed_range", 0.02, 0.06, 0.12, "realization"),
    _parameter("mortality_d", "day^-1", "literature_informed_range", 0.01, 0.04, 0.10, "realization"),
    _parameter("mixing_loss_per_index_d", "day^-1", "mechanism_assumption", 0.02, 0.09, 0.20, "zone"),
    _parameter("flow_loss_per_m_s_d", "day^-1/(m/s)", "mechanism_assumption", 0.0, 0.03, 0.10, "zone"),
    _parameter("sigma_b", "log(mg/L)", "mechanism_assumption", 0.0, 0.08, 0.20, "realization"),
    _parameter("biomass_scale_mg_L", "mg/L", "smooth_bound_assumption", 30.0, 36.0, 40.0, "grid"),
    _parameter("min_biomass_mg_L", "mg/L", "numerical_safeguard", 1e-6, 1e-3, 0.05, "realization"),
    _parameter("initial_blue_algae_fraction", "1", "conservative_initialization", 0.01, 0.15, 0.40, "grid"),
)


def mechanism_parameter_table() -> pd.DataFrame:
    """Return a fresh, stable-order tabular view of the versioned parameters."""
    return pd.DataFrame([dict(row) for row in MECHANISM_PARAMETER_TABLE])


def parameter_table_sha256() -> str:
    """SHA-256 of canonical parameter content, independent of mapping identity."""
    content = [dict(row) for row in MECHANISM_PARAMETER_TABLE]
    canonical = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_mechanism_parameters() -> dict[str, float]:
    """Return a mutable copy of the documented V0.3 numeric defaults."""
    return {row["name"]: float(row["default"]) for row in MECHANISM_PARAMETER_TABLE}


@dataclass(frozen=True)
class MechanismState:
    """Immutable date/grid-aligned end-of-day biomass state.

    Tuple storage makes equality exact and safe for checkpoint comparisons.
    ``biomass_mg_L`` is strictly positive and finite for every ordered grid.
    """

    last_date: pd.Timestamp
    grid_ids: tuple[str, ...]
    biomass_mg_L: tuple[float, ...]

    def __post_init__(self):
        date = pd.Timestamp(self.last_date)
        grid_ids = tuple(str(value) for value in self.grid_ids)
        biomass = tuple(float(value) for value in self.biomass_mg_L)
        if pd.isna(date):
            raise ValueError("mechanism state last_date is invalid")
        if not grid_ids or any(not value or value == "nan" for value in grid_ids) or len(set(grid_ids)) != len(grid_ids):
            raise ValueError("mechanism state grid_ids must be non-empty and unique")
        if len(biomass) != len(grid_ids) or not np.isfinite(biomass).all() or not np.all(np.asarray(biomass) > 0):
            raise ValueError("mechanism state biomass must be finite and strictly positive")
        object.__setattr__(self, "last_date", date)
        object.__setattr__(self, "grid_ids", grid_ids)
        object.__setattr__(self, "biomass_mg_L", biomass)


def _parameters(parameters: Mapping | None) -> dict[str, float]:
    if parameters is not None and not isinstance(parameters, Mapping):
        raise ValueError("parameters must be a mapping or None")
    values = default_mechanism_parameters()
    if parameters is not None:
        unexpected = sorted(set(parameters) - set(values))
        if unexpected:
            raise ValueError(f"unknown mechanism parameters: {unexpected}")
        for name, value in parameters.items():
            try:
                values[name] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"mechanism parameter {name} is not numeric") from exc
    for row in MECHANISM_PARAMETER_TABLE:
        name = row["name"]
        value = values[name]
        if not np.isfinite(value) or not row["lower_bound"] <= value <= row["upper_bound"]:
            raise ValueError(f"mechanism parameter {name} is outside its documented bounds")
    if values["min_biomass_mg_L"] >= values["biomass_scale_mg_L"]:
        raise ValueError("min_biomass_mg_L must be below biomass_scale_mg_L")
    return values


def _input_frame(frame: pd.DataFrame, *, require_keys: bool) -> tuple[pd.DataFrame, pd.DatetimeIndex, tuple[str, ...]]:
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a DataFrame")
    required = set(_REQUIRED_VISIBLE) | (set(_KEY_COLUMNS) if require_keys else set())
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"frame missing required visible fields: {missing}")
    result = frame.copy()
    for column in _REQUIRED_VISIBLE:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result[list(_REQUIRED_VISIBLE)].isna().any().any() or not np.isfinite(result[list(_REQUIRED_VISIBLE)].to_numpy(dtype=float)).all():
        raise ValueError("frame has non-finite visible environmental fields")
    if (result["total_nitrogen_mg_L"] < 0).any() or (result["total_phosphorus_mg_L"] < 0).any() or (result["solar_radiation_MJ_m2_day"] < 0).any():
        raise ValueError("nutrients and solar radiation must be non-negative")
    if (result["mixing_index"] < 0).any() or (result["mixing_index"] > 1).any():
        raise ValueError("mixing_index must be in [0, 1]")
    if not require_keys:
        return result, pd.DatetimeIndex([]), tuple()
    if result.empty:
        raise ValueError("frame must contain at least one date/grid row")
    if result[list(_KEY_COLUMNS)].isna().any().any():
        raise ValueError("frame has invalid keys")
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    if result["date"].isna().any():
        raise ValueError("frame has invalid dates")
    result["grid_id"] = result["grid_id"].astype(str)
    result["experimental_zone_id"] = result["experimental_zone_id"].astype(str)
    if result["grid_id"].str.len().eq(0).any() or result["grid_id"].eq("nan").any():
        raise ValueError("frame has invalid grid IDs")
    result["grid_numeric_id"] = pd.to_numeric(result["grid_numeric_id"], errors="coerce")
    numeric = result["grid_numeric_id"].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or not np.equal(numeric, np.floor(numeric)).all() or (numeric < 0).any():
        raise ValueError("frame has invalid grid_numeric_id")
    result["grid_numeric_id"] = result["grid_numeric_id"].astype(int)
    if "flow_speed_m_s" in result:
        result["flow_speed_m_s"] = pd.to_numeric(result["flow_speed_m_s"], errors="coerce")
        if result["flow_speed_m_s"].isna().any() or not np.isfinite(result["flow_speed_m_s"].to_numpy(dtype=float)).all() or (result["flow_speed_m_s"] < 0).any():
            raise ValueError("frame has invalid flow_speed_m_s")
    dates = pd.DatetimeIndex(pd.unique(result["date"]))
    if not dates.is_monotonic_increasing or (len(dates) > 1 and not np.all((dates[1:] - dates[:-1]) == pd.Timedelta(days=1))):
        raise ValueError("frame dates must be sorted and contiguous daily")
    first = result.loc[result["date"].eq(dates[0]), ["grid_id", "grid_numeric_id", "experimental_zone_id"]]
    grid_ids = tuple(first["grid_id"])
    if not grid_ids or len(set(grid_ids)) != len(grid_ids):
        raise ValueError("frame has duplicate grid IDs")
    expected = [(date, grid_id) for date in dates for grid_id in grid_ids]
    actual = list(zip(result["date"], result["grid_id"]))
    if actual != expected:
        raise ValueError("frame date/grid ordering must be sorted and complete")
    mapping = list(zip(first["grid_id"], first["grid_numeric_id"], first["experimental_zone_id"]))
    if list(zip(result["grid_id"], result["grid_numeric_id"], result["experimental_zone_id"])) != mapping * len(dates):
        raise ValueError("frame grid mapping differs across dates")
    return result, dates, grid_ids


def _biomass_proxy(frame: pd.DataFrame, parameters: Mapping[str, float], prior_biomass=None) -> np.ndarray:
    if prior_biomass is not None:
        values = np.asarray(prior_biomass, dtype=float)
    elif "phytoplankton_biomass_mg_L" in frame:
        values = pd.to_numeric(frame["phytoplankton_biomass_mg_L"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("phytoplankton_biomass_mg_L must be finite and positive when supplied")
    else:
        values = np.full(len(frame), parameters["self_shading_fallback_biomass_mg_L"], dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("mechanism biomass proxy must be finite and positive")
    return values


def _factor_values(frame: pd.DataFrame, parameters: Mapping[str, float], prior_biomass=None) -> dict[str, np.ndarray]:
    biomass = _biomass_proxy(frame, parameters, prior_biomass)
    temperature = frame["water_temperature_C"].to_numpy(dtype=float)
    width = np.where(temperature <= parameters["temperature_optimum_C"], parameters["temperature_cold_width_C"], parameters["temperature_hot_width_C"])
    temperature_factor = np.exp(-np.square((temperature - parameters["temperature_optimum_C"]) / width))
    nitrogen_factor = frame["total_nitrogen_mg_L"].to_numpy(dtype=float) / (frame["total_nitrogen_mg_L"].to_numpy(dtype=float) + parameters["K_N_mg_L"])
    phosphorus_factor = frame["total_phosphorus_mg_L"].to_numpy(dtype=float) / (frame["total_phosphorus_mg_L"].to_numpy(dtype=float) + parameters["K_P_mg_L"])
    nutrient_factor = np.minimum(nitrogen_factor, phosphorus_factor)
    irradiance = frame["solar_radiation_MJ_m2_day"].to_numpy(dtype=float)
    light_factor = irradiance / (irradiance + parameters["light_half_saturation_MJ_m2_day"])
    light_factor *= np.exp(-parameters["self_shading_per_mg_L"] * biomass)
    capacity_factor = 1.0 / (1.0 + biomass / parameters["carrying_capacity_mg_L"])
    mixing = frame["mixing_index"].to_numpy(dtype=float)
    flow = frame["flow_speed_m_s"].to_numpy(dtype=float) if "flow_speed_m_s" in frame else np.zeros(len(frame), dtype=float)
    mixing_loss = parameters["mixing_loss_per_index_d"] * mixing + parameters["flow_loss_per_m_s_d"] * flow
    gross = parameters["mu_max_d"] * temperature_factor * nutrient_factor * light_factor * capacity_factor
    respiration = np.full(len(frame), parameters["base_respiration_d"], dtype=float)
    mortality = np.full(len(frame), parameters["mortality_d"], dtype=float)
    net = gross - respiration - mortality - mixing_loss
    values = {
        "temperature_factor": temperature_factor, "nitrogen_factor": nitrogen_factor,
        "phosphorus_factor": phosphorus_factor, "nutrient_factor": nutrient_factor,
        "light_factor": light_factor, "capacity_factor": capacity_factor,
        "gross_growth_rate_d": gross, "respiration_rate_d": respiration,
        "mortality_rate_d": mortality, "mixing_loss_rate_d": mixing_loss,
        "net_growth_rate_d": net,
    }
    if not all(np.isfinite(value).all() for value in values.values()):
        raise ValueError("mechanism factors or rates are not finite")
    return values


def limitation_factors(frame: pd.DataFrame, parameters: Mapping | None = None) -> pd.DataFrame:
    """Calculate visible-driver limitation factors and daily rate summaries.

    If ``phytoplankton_biomass_mg_L`` is absent, self-shading and capacity use
    the conservative documented fallback, never a target, label, or future
    blue-algae biomass value.
    """
    values = _parameters(parameters)
    checked, _, _ = _input_frame(frame, require_keys=False)
    output = checked.copy()
    for name, data in _factor_values(checked, values).items():
        output[name] = data
    output["mechanism_rate_unit"] = "day^-1"
    output["mechanism_factor_unit"] = "1"
    return output


def _smooth_positive_cap(raw_biomass: np.ndarray, parameters: Mapping[str, float]) -> np.ndarray:
    scale = parameters["biomass_scale_mg_L"]
    lower = parameters["min_biomass_mg_L"]
    raw = np.asarray(raw_biomass, dtype=float)
    if not np.isfinite(raw).all() or (raw <= 0).any():
        raise ValueError("raw mechanism biomass must be finite and strictly positive")
    # The analytic transform is inside the open interval, but floating-point
    # cancellation rounds extreme finite values onto a bound.  The nearest
    # representable interior values retain the smooth cap without a boundary pile.
    capped = lower + (scale - lower) * (-np.expm1(-raw / scale))
    return np.clip(capped, np.nextafter(lower, scale), np.nextafter(scale, lower))


def persistence_projection(
    frame: pd.DataFrame,
    horizon_days: int,
    parameters: Mapping | None = None,
) -> np.ndarray:
    """Advance biomass under persistence of the current visible drivers.

    This is a causality-safe dynamic projection: it repeats the issue-time
    environmental conditions for ``horizon_days`` and does not read target or
    future-driver columns.  The returned values are end-of-horizon biomass in
    ``mg/L`` using the documented compact cyanobacteria growth/loss model.
    """
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, Integral):
        raise ValueError("horizon_days must be a positive integer")
    if int(horizon_days) <= 0:
        raise ValueError("horizon_days must be a positive integer")
    values = _parameters(parameters)
    checked, _, _ = _input_frame(frame, require_keys=False)
    biomass = _biomass_proxy(checked, values)
    for _ in range(int(horizon_days)):
        factors = _factor_values(checked, values, prior_biomass=biomass)
        exponent = np.clip(
            factors["net_growth_rate_d"],
            -50.0,
            50.0,
        )
        biomass = _smooth_positive_cap(biomass * np.exp(exponent), values)
    return biomass


def _initial_biomass(frame: pd.DataFrame, parameters: Mapping[str, float]) -> np.ndarray:
    if "phytoplankton_biomass_mg_L" not in frame:
        raise ValueError("prior_state=None requires visible phytoplankton_biomass_mg_L for conservative initialization")
    visible = _biomass_proxy(frame, parameters)
    raw = visible * parameters["initial_blue_algae_fraction"]
    return _smooth_positive_cap(raw, parameters)


def _advance_rows(rows: pd.DataFrame, biomass: np.ndarray, parameters: Mapping[str, float], innovation: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    values = _factor_values(rows, parameters, prior_biomass=biomass)
    exponent = np.clip(values["net_growth_rate_d"] + parameters["sigma_b"] * innovation, -50.0, 50.0)
    raw_next = biomass * np.exp(exponent)
    next_biomass = _smooth_positive_cap(raw_next, parameters)
    return next_biomass, values


def _state_or_initial(prior_state, frame: pd.DataFrame, dates: pd.DatetimeIndex, grid_ids: tuple[str, ...], parameters: Mapping[str, float]) -> np.ndarray:
    width = len(grid_ids)
    if prior_state is None:
        return _initial_biomass(frame.iloc[:width], parameters)
    if not isinstance(prior_state, MechanismState):
        raise ValueError("invalid mechanism prior_state")
    if prior_state.grid_ids != grid_ids:
        raise ValueError("mechanism state grid ordering differs from frame")
    if prior_state.last_date != dates[0] - pd.Timedelta(days=1):
        raise ValueError("mechanism state last_date does not make the block contiguous")
    values = np.asarray(prior_state.biomass_mg_L, dtype=float)
    if values.shape != (width,) or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("mechanism state has invalid biomass")
    return values.copy()


def _provenance(output: pd.DataFrame) -> pd.DataFrame:
    output["mechanism_model_version"] = MECHANISM_MODEL_VERSION
    output["mechanism_parameter_hash"] = parameter_table_sha256()
    output["mechanism_rate_unit"] = "day^-1"
    output["mechanism_factor_unit"] = "1"
    output["data_mode"] = "simulation"
    output["is_ground_truth"] = 0
    output["claim_boundary"] = _CLAIM_BOUNDARY
    return output


def advance_biomass(frame: pd.DataFrame, prior_state: MechanismState | None, rng: np.random.Generator, parameters: Mapping | None = None) -> tuple[pd.DataFrame, MechanismState]:
    """Advance complete, date-grid ordered driver rows with explicit process noise."""
    if not isinstance(rng, np.random.Generator):
        raise ValueError("rng must be an explicit numpy.random.Generator")
    values = _parameters(parameters)
    checked, dates, grid_ids = _input_frame(frame, require_keys=True)
    biomass = _state_or_initial(prior_state, checked, dates, grid_ids, values)
    width = len(grid_ids)
    daily_outputs = []
    for day_index, _date in enumerate(dates):
        start = day_index * width
        rows = checked.iloc[start:start + width]
        biomass, factors = _advance_rows(rows, biomass, values, rng.normal(size=width))
        block = rows.copy()
        for name, data in factors.items():
            block[name] = data
        block["blue_algae_biomass_mg_L"] = biomass
        daily_outputs.append(block)
    output = _provenance(pd.concat(daily_outputs, ignore_index=True))
    state = MechanismState(last_date=dates[-1], grid_ids=grid_ids, biomass_mg_L=tuple(float(value) for value in biomass))
    return output, state


def _horizons(horizons) -> tuple[int, ...]:
    try:
        result = tuple(horizons)
    except TypeError as exc:
        raise ValueError("horizons must be unique positive integers") from exc
    if not result or any(isinstance(value, bool) or not isinstance(value, Integral) or value <= 0 for value in result) or len(set(result)) != len(result):
        raise ValueError("horizons must be unique positive integers")
    return tuple(int(value) for value in result)


def _reject_leaky_forecast_columns(frame: pd.DataFrame) -> None:
    lower_names = {str(name).lower() for name in frame.columns}
    allowed_provenance = {"is_ground_truth"}
    explicit_signals = (
        "blue_algae_biomass", "chlorophyll", "cyanobacteria", "phycocyanin",
    )
    forbidden = sorted(
        name for name in lower_names
        if name not in allowed_provenance and (
            name.startswith("bloom_") or name.startswith("mechanism_")
            or any(signal in name for signal in explicit_signals)
            or any(signal in name for signal in ("target", "label", "truth", "latent"))
        )
    )
    if forbidden:
        raise ValueError(f"future drivers contain leaky target, label, truth, or latent fields: {forbidden}")


def mechanism_forecast(current_state: MechanismState, future_drivers: pd.DataFrame, horizons, parameters: Mapping | None = None) -> pd.DataFrame:
    """Project zero-process-noise mechanism biomass for requested future horizons.

    Only visible environmental forecasts are accepted.  The input state is
    read-only and never updated or otherwise mutated by this projection.
    """
    if not isinstance(current_state, MechanismState):
        raise ValueError("current_state must be a MechanismState")
    requested = _horizons(horizons)
    _reject_leaky_forecast_columns(future_drivers)
    values = _parameters(parameters)
    checked, dates, grid_ids = _input_frame(future_drivers, require_keys=True)
    if grid_ids != current_state.grid_ids:
        raise ValueError("future driver grid ordering differs from current_state")
    if dates[0] != current_state.last_date + pd.Timedelta(days=1):
        raise ValueError("future drivers must start the day after current_state.last_date")
    if len(dates) < max(requested):
        raise ValueError("future drivers do not cover the maximum requested horizon")
    biomass = np.asarray(current_state.biomass_mg_L, dtype=float).copy()
    width = len(grid_ids)
    selected = []
    for day_index, date in enumerate(dates[:max(requested)]):
        rows = checked.iloc[day_index * width:(day_index + 1) * width]
        biomass, factors = _advance_rows(rows, biomass, values, np.zeros(width, dtype=float))
        horizon = day_index + 1
        if horizon in requested:
            block = rows.loc[:, list(_KEY_COLUMNS)].copy()
            block["issue_date"] = current_state.last_date
            block["target_date"] = date
            block["horizon_days"] = horizon
            for name, data in factors.items():
                block[name] = data
            block["mechanism_biomass_forecast_mg_L"] = biomass
            block["mechanism_blue_algae_biomass_forecast_mg_L"] = biomass
            selected.append(block)
    return _provenance(pd.concat(selected, ignore_index=True))
