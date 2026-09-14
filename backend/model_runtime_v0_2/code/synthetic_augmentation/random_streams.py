"""Stable, coordinate-derived random streams for V0.3 simulation components."""

from enum import IntEnum
from numbers import Integral

import numpy as np


class ComponentCode(IntEnum):
    WEATHER = 101
    HYDROLOGY = 102
    WATER_QUALITY = 103
    MECHANISM = 104
    TRANSPORT = 105
    OBSERVATION = 106
    TARGETS = 107


def _component_code(component) -> ComponentCode:
    try:
        return ComponentCode(component)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid component value: {component!r}") from exc


def _nonnegative_coordinate(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def derive_seed_sequence(
    config,
    component,
    year=0,
    zone_id=0,
    grid_numeric_id=0,
) -> np.random.SeedSequence:
    """Return a seed sequence whose entropy is fixed by simulation coordinates."""
    component_code = _component_code(component)
    year = _nonnegative_coordinate(year, "year")
    zone_id = _nonnegative_coordinate(zone_id, "zone_id")
    grid_numeric_id = _nonnegative_coordinate(grid_numeric_id, "grid_numeric_id")
    entropy = [config.base_seed, int(component_code), year, zone_id, grid_numeric_id]
    return np.random.SeedSequence(entropy)


def make_rng(config, component, year=0, zone_id=0, grid_numeric_id=0) -> np.random.Generator:
    """Create a stable NumPy generator for one component and coordinate tuple."""
    return np.random.default_rng(
        derive_seed_sequence(config, component, year, zone_id, grid_numeric_id)
    )
