"""Sparse, conservative 2-D neighbor transport for synthetic V0.3 states.

This is an experimental wind-aligned neighbor approximation, not a calibrated
three-dimensional hydrodynamic solver.  It deliberately operates on sparse
edge arrays and retains mass locally on isolated nodes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse


TRANSPORT_MODEL_VERSION = "TAIHU_SPARSE_NEIGHBOR_TRANSPORT_V0.3"
_CONSERVATION_TOLERANCE = 1e-8


@dataclass(frozen=True)
class TransportConfig:
    """Conservative transport settings.

    ``wind_response_scale`` is the wind speed (m/s) at which the bounded
    response ``speed / (speed + scale)`` reaches one half.  Attribute-based
    configurations may omit only this optional field, in which case 1.0 m/s
    is used; the two redistribution fractions must be explicit.
    """

    max_advective_fraction: float = 0.20
    diffusion_fraction: float = 0.02
    wind_response_scale: float = 1.0


def _as_finite_vector(value, name: str, size: int | None = None) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite one-dimensional vector") from exc
    if array.ndim != 1 or (size is not None and array.shape != (size,)):
        raise ValueError(f"{name} must be a finite one-dimensional vector of length {size}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array


def _transport_parameters(config) -> tuple[float, float, float]:
    try:
        advective = float(config.max_advective_fraction)
        diffusion = float(config.diffusion_fraction)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("config must provide finite max_advective_fraction and diffusion_fraction") from exc
    scale_value = getattr(config, "wind_response_scale", 1.0)
    try:
        wind_scale = float(scale_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("wind_response_scale must be finite and positive") from exc
    if not np.isfinite([advective, diffusion, wind_scale]).all():
        raise ValueError("transport configuration values must be finite")
    if not 0.0 <= advective <= 1.0 or not 0.0 <= diffusion <= 1.0:
        raise ValueError("transport fractions must lie in [0, 1]")
    if wind_scale <= 0.0:
        raise ValueError("wind_response_scale must be positive")
    return advective, diffusion, wind_scale


def _validated_edges(adjacency, node_count: int) -> tuple[np.ndarray, np.ndarray]:
    if not sparse.issparse(adjacency):
        raise ValueError("adjacency must be a scipy sparse matrix")
    if adjacency.shape != (node_count, node_count):
        raise ValueError("adjacency must have shape N x N")
    try:
        matrix = adjacency.tocsr(copy=True).astype(float, copy=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("adjacency must contain finite non-negative values") from exc
    if not np.isfinite(matrix.data).all() or (matrix.data < 0.0).any():
        raise ValueError("adjacency must contain finite non-negative values")
    if np.any(matrix.diagonal() != 0.0):
        raise ValueError("adjacency must have a zero diagonal")
    difference = (matrix - matrix.T).tocsr()
    difference.eliminate_zeros()
    if difference.nnz:
        raise ValueError("adjacency must be symmetric for the undirected grid contract")
    matrix.eliminate_zeros()
    rows = np.repeat(np.arange(node_count, dtype=np.intp), np.diff(matrix.indptr))
    return rows, matrix.indices.copy()


def _cleanup_and_check(result: np.ndarray, initial_mass: float) -> np.ndarray:
    if not np.isfinite(result).all():
        raise RuntimeError("transport produced a non-finite value")
    epsilon = 64.0 * np.finfo(float).eps * max(1.0, initial_mass)
    if np.any(result < -epsilon):
        raise RuntimeError("transport produced materially negative biomass")
    if np.any(result < 0.0):
        result = result.copy()
        result[result < 0.0] = 0.0
    final_mass = float(result.sum())
    if initial_mass == 0.0:
        if final_mass != 0.0:
            raise RuntimeError("zero biomass must remain exactly zero")
    elif abs(final_mass - initial_mass) / initial_mass >= _CONSERVATION_TOLERANCE:
        raise RuntimeError("transport violated the mass-conservation invariant")
    return result


def transport_step(biomass, coordinates, adjacency, wind_u, wind_v, config) -> np.ndarray:
    """Advance biomass by conservative wind-aligned transfer and diffusion.

    The input adjacency is a symmetric, zero-diagonal sparse grid-neighbor
    graph.  Edge values express membership rather than conductance; positive
    outbound wind alignments are normalized at each source.  Background
    diffusion is then applied as a separate uniform redistribution across a
    source's neighbors.  Inputs are read-only.
    """
    biomass_values = _as_finite_vector(biomass, "biomass")
    if (biomass_values < 0.0).any():
        raise ValueError("biomass must be non-negative")
    node_count = biomass_values.size
    try:
        point_coordinates = np.asarray(coordinates, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("coordinates must be finite N x 2 projected coordinates") from exc
    if point_coordinates.shape != (node_count, 2) or not np.isfinite(point_coordinates).all():
        raise ValueError("coordinates must be finite N x 2 projected coordinates")
    wind_u_values = _as_finite_vector(wind_u, "wind_u", node_count)
    wind_v_values = _as_finite_vector(wind_v, "wind_v", node_count)
    max_advective_fraction, diffusion_fraction, wind_scale = _transport_parameters(config)
    rows, columns = _validated_edges(adjacency, node_count)
    initial_mass = float(biomass_values.sum())
    if not rows.size:
        return biomass_values.astype(float, copy=True)

    delta = point_coordinates[columns] - point_coordinates[rows]
    distance = np.hypot(delta[:, 0], delta[:, 1])
    if np.any(distance == 0.0):
        raise ValueError("adjacent centroids must not have zero distance")
    if initial_mass == 0.0:
        return biomass_values.astype(float, copy=True)
    edge_unit = delta / distance[:, None]
    wind_speed = np.hypot(wind_u_values, wind_v_values)
    wind_unit = np.zeros((node_count, 2), dtype=float)
    nonzero_wind = wind_speed > 0.0
    wind_unit[nonzero_wind, 0] = wind_u_values[nonzero_wind] / wind_speed[nonzero_wind]
    wind_unit[nonzero_wind, 1] = wind_v_values[nonzero_wind] / wind_speed[nonzero_wind]
    alignment = np.maximum(0.0, np.einsum("ij,ij->i", edge_unit, wind_unit[rows]))
    alignment_sum = np.bincount(rows, weights=alignment, minlength=node_count)
    actual_advective_fraction = np.zeros(node_count, dtype=float)
    aligned = alignment_sum > 0.0
    actual_advective_fraction[aligned] = (
        max_advective_fraction * wind_speed[aligned] / (wind_speed[aligned] + wind_scale)
    )
    edge_weight = np.zeros_like(alignment)
    edge_weight[alignment > 0.0] = alignment[alignment > 0.0] / alignment_sum[rows[alignment > 0.0]]
    advective_transfer = biomass_values[rows] * actual_advective_fraction[rows] * edge_weight
    after_advection = biomass_values * (1.0 - actual_advective_fraction)
    after_advection += np.bincount(columns, weights=advective_transfer, minlength=node_count)

    degree = np.bincount(rows, minlength=node_count)
    actual_diffusion_fraction = np.where(degree > 0, diffusion_fraction, 0.0)
    diffusive_transfer = after_advection[rows] * actual_diffusion_fraction[rows] / degree[rows]
    result = after_advection * (1.0 - actual_diffusion_fraction)
    result += np.bincount(columns, weights=diffusive_transfer, minlength=node_count)
    return _cleanup_and_check(result, initial_mass)
