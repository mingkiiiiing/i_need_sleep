"""Authoritative experimental-grid loading, metadata, and sparse adjacency."""
from __future__ import annotations

import hashlib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import sparse

GRID_CRS = "EPSG:32651"
ZONE_VERSION = "centroid_quantile_4x2_v1"


def load_experimental_grid(path, config) -> gpd.GeoDataFrame:
    grid = path.copy() if isinstance(path, gpd.GeoDataFrame) else gpd.read_file(Path(path))
    if config.expected_grid_count != 1520:
        raise ValueError("expected_grid_count must equal 1520")
    _validate_grid(grid, expected_count=1520)
    grid = grid.sort_values("grid_id", kind="mergesort").reset_index(drop=True)
    grid["grid_numeric_id"] = np.arange(len(grid), dtype=np.int64)
    return grid


def _validate_grid(grid: gpd.GeoDataFrame, *, expected_count: int) -> None:
    """Validate an input frame; internal helper permits small contract fixtures."""
    if grid.crs is None or grid.crs.to_epsg() != 4326:
        raise ValueError("input CRS must be EPSG:4326")
    if len(grid) != expected_count:
        raise ValueError(f"feature count must equal {expected_count}")
    for col in ("grid_id", "grid_size_m", "grid_version", "boundary_status", "geometry"):
        if col not in grid.columns:
            raise ValueError(f"missing required column: {col}")
    if grid["grid_id"].isna().any() or (~grid["grid_id"].astype(str).str.strip().astype(bool)).any() or not grid["grid_id"].is_unique:
        raise ValueError("grid_id must be unique and non-null")
    if not np.all(grid["grid_size_m"] == 1000):
        raise ValueError("grid_size_m must equal 1000")
    if not np.all(grid["grid_version"] == "provisional_1km_V0.1"):
        raise ValueError("grid_version must equal provisional_1km_V0.1")
    if not np.all(grid["boundary_status"] == "provisional"):
        raise ValueError("boundary_status must equal provisional")
    if grid.geometry.isna().any() or grid.geometry.is_empty.any() or (~grid.geometry.is_valid).any():
        raise ValueError("geometry must be valid and non-empty")


def _zones(projected: gpd.GeoDataFrame) -> np.ndarray:
    c = projected.geometry.centroid
    # Fixed spatial partition: x quartiles, then y halves within each x band.
    xrank = pd.Series(c.x).rank(method="first", pct=True).to_numpy()
    xbin = np.minimum((xrank * 4).astype(int), 3)
    y = c.y.to_numpy()
    ybin = np.zeros(len(y), dtype=int)
    for band in range(4):
        ix = np.flatnonzero(xbin == band)
        ybin[ix] = (y[ix] >= np.median(y[ix])).astype(int)
    return np.array([f"EXP_ZONE_{b * 2 + yy + 1:02d}" for b, yy in zip(xbin, ybin)])


def build_grid_metadata(grid: gpd.GeoDataFrame, config) -> pd.DataFrame:
    projected = grid.to_crs(GRID_CRS)
    cent = projected.geometry.centroid
    area = projected.geometry.area.to_numpy()
    lonlat = gpd.GeoSeries(cent, crs=projected.crs).to_crs("EPSG:4326")
    x, y = cent.x.to_numpy(), cent.y.to_numpy()
    spanx, spany = max(np.ptp(x), 1.0), max(np.ptp(y), 1.0)
    metadata = pd.DataFrame({
        "grid_id": grid.grid_id.to_numpy(), "grid_numeric_id": grid.grid_numeric_id.to_numpy(),
        "grid_version": grid.grid_version.to_numpy(), "grid_status": "experimental_provisional",
        "centroid_longitude": lonlat.x.to_numpy(), "centroid_latitude": lonlat.y.to_numpy(),
        "centroid_x_m": x, "centroid_y_m": y, "geometry_area_m2": area,
        "water_area_m2": area, "water_fraction": np.minimum(area / 1_000_000.0, 1.0),
        "experimental_zone_id": _zones(projected),
        "mean_water_depth_m": 2.0 + 0.8 * (x - x.min()) / spanx + 0.4 * (y - y.min()) / spany,
        "distance_to_shore_m": 100.0 + 0.15 * np.hypot(x - x.mean(), y - y.mean()),
        "distance_to_inflow_m": 500.0 + 0.2 * np.hypot(x - x.min(), y - y.min()),
        "elevation_m": 2.0 + 0.001 * (y - y.mean()),
        "valid_from": pd.Timestamp(config.start_date), "valid_to": pd.Timestamp(config.end_date),
    })
    derived = ("geometry_source_class", "water_area_source_class", "water_fraction_source_class", "centroid_source_class")
    synthetic = ("experimental_zone_source_class", "mean_water_depth_source_class", "distance_to_shore_source_class", "distance_to_inflow_source_class", "elevation_source_class")
    for col in derived: metadata[col] = "derived_geometry"
    for col in synthetic: metadata[col] = "synthetic_static"
    return metadata


def build_adjacency(grid: gpd.GeoDataFrame) -> sparse.csr_matrix:
    projected = grid.to_crs(GRID_CRS)
    geoms = projected.geometry.to_numpy()
    rows, cols = set(), set()
    sidx = projected.sindex
    for i, geom in enumerate(geoms):
        for j in sidx.query(geom.buffer(1.0), predicate="intersects"):
            j = int(j)
            if i != j: rows.add((i, j))
    before = [i for i in range(len(geoms)) if not any(a == i for a, _ in rows)]
    centers = np.array([[g.centroid.x, g.centroid.y] for g in geoms])
    for i in before:
        d = np.sum((centers - centers[i]) ** 2, axis=1); d[i] = np.inf
        j = int(np.argmin(d)); rows.update(((i, j), (j, i)))
    if rows:
        rr, cc = zip(*rows); matrix = sparse.csr_matrix((np.ones(len(rr), dtype=np.int8), (rr, cc)), shape=(len(geoms), len(geoms)))
    else: matrix = sparse.csr_matrix((len(geoms), len(geoms)), dtype=np.int8)
    matrix._isolated_before_repair = [str(grid.iloc[i].grid_id) for i in before]
    return matrix


def adjacency_summary(grid, matrix) -> dict:
    deg = np.asarray(matrix.sum(axis=1)).ravel()
    ids = grid.sort_values("grid_numeric_id").grid_id.astype(str).tolist()
    return {"node_count": matrix.shape[0], "undirected_edge_count": int(matrix.nnz // 2),
            "isolated_before_repair_ids": list(getattr(matrix, "_isolated_before_repair", [])),
            "degree_min": int(deg.min()) if len(deg) else 0, "degree_median": float(np.median(deg)) if len(deg) else 0.0,
            "degree_max": int(deg.max()) if len(deg) else 0, "crs": GRID_CRS,
            "ordering_hash": hashlib.sha256("|".join(ids).encode()).hexdigest()}
