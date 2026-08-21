from __future__ import annotations

"""Auditable time/space alignment of resampled Taihu series.

The output is a relation table rather than a wide table.  Each row records one
target observation and one candidate driver, including the time gap, spatial
distance (when both records have coordinates), and an explicit match status.
This avoids silently pretending that a temporal-only match is spatially exact.
"""

import csv
import json
import math
import sqlite3
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resample import _float_or_none, _json_or_empty, _parse_time


WATER_QUALITY_VARIABLES = {
    "pH", "cod_mn", "dissolved_oxygen", "total_phosphorus", "phosphate_phosphorus",
    "total_nitrogen", "ammonia_nitrogen", "nitrate_nitrogen", "nitrite_nitrogen",
    "phytoplankton_biomass", "chlorophyll_a", "algae_density", "cyanobacteria_biomass",
}
METEOROLOGY_VARIABLES = {
    "air_temperature", "wind_speed", "wind_direction", "precipitation",
    "shortwave_radiation", "cloud_cover", "pressure", "par", "relative_humidity",
}
HYDROLOGY_VARIABLES = {"water_level", "discharge", "velocity", "water_flow", "water_temperature"}
DEFAULT_MAX_TIME_DIFF_HOURS = 24.0
DEFAULT_IDEAL_GROUND_REMOTE_HOURS = 3.0
MATCHING_STRATEGIES = {"nearest"}
DEFAULT_GRID_SIZE_M = 300.0
DEFAULT_STATION_BUFFER_PIXELS = (1, 2, 3)
# The catalogue bbox in study_area.yml is deliberately used as the default
# grid origin.  It is a stable origin, not a claim about the operational
# shoreline; all lake-area statistics still use the authoritative polygon.
DEFAULT_GRID_ORIGIN = (119.90, 30.90)
SUPPORTED_SOURCE_PIXEL_SIZES_M = {10.0, 20.0, 30.0}


def _is_ground_remote_pair(left_category: str, right_category: str) -> bool:
    return {left_category, right_category} in (
        {"remote_sensing", "water_quality"},
        {"remote_sensing", "hydrology"},
    )


def _category(row: dict[str, Any]) -> str:
    source_id = str(row.get("source_id") or "")
    variable = str(row.get("variable_code") or "")
    if source_id.startswith(("copernicus_", "sentinel", "clms_", "remote_")) or (row.get("scene_id") and not row.get("station_id")) or variable.startswith("remote_"):
        return "remote_sensing"
    if variable in WATER_QUALITY_VARIABLES:
        return "water_quality"
    if variable in METEOROLOGY_VARIABLES:
        return "meteorology"
    if variable in HYDROLOGY_VARIABLES:
        return "hydrology"
    return "other"


def read_resampled_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for key in (
                "clean_value", "observed_value", "longitude", "latitude", "aggregation_coverage",
                "pixel_size_m", "source_pixel_resolution_m", "spatial_resolution_m", "resolution_m",
            ):
                row[key] = _float_or_none(row.get(key))
            try:
                row["n_obs"] = int(float(row.get("n_obs") or 0))
            except (TypeError, ValueError):
                row["n_obs"] = 0
            row["quality_flags"] = _json_or_empty(row.get("quality_flags"))
            row["_time"] = _parse_time(row.get("time_bucket") or row.get("observed_at"))
            row["_category"] = _category(row)
            rows.append(row)
    return rows


def _local_xy_m(lon: float, lat: float, origin: tuple[float, float]) -> tuple[float, float]:
    """Project WGS84 coordinates to a deterministic local metric grid.

    The Taihu study area is small enough that the equirectangular approximation
    has sub-metre error at a 300 m grid.  Using a local projection here avoids
    introducing a hidden CRS dependency in the relation table; the boundary
    area calculation below still uses the authoritative UTM layer/projection.
    """

    lon0, lat0 = origin
    mean_lat = math.radians((lat + lat0) / 2.0)
    return (
        math.radians(lon - lon0) * 6_371_000.0 * math.cos(mean_lat),
        math.radians(lat - lat0) * 6_371_000.0,
    )


def _local_lonlat(x: float, y: float, origin: tuple[float, float]) -> tuple[float, float]:
    lon0, lat0 = origin
    lat = lat0 + math.degrees(y / 6_371_000.0)
    lon = lon0 + math.degrees(x / (6_371_000.0 * math.cos(math.radians((lat + lat0) / 2.0))))
    return lon, lat


def _normalise_pixel_size(row: dict[str, Any]) -> float | None:
    for key in ("pixel_size_m", "source_pixel_resolution_m", "spatial_resolution_m", "resolution_m"):
        value = _float_or_none(row.get(key))
        if value is not None and value > 0:
            return float(value)
    return None


def _spatial_time_key(row: dict[str, Any]) -> str | None:
    value = row.get("time_bucket") or row.get("observed_at") or row.get("observed_at_utc")
    return str(value) if value not in (None, "") else None


def _load_boundary_geometry(boundary_path: Path | None) -> tuple[Any | None, str | None, float | None]:
    """Load the frozen Taihu polygon and its planar area when available."""

    if boundary_path is None or not Path(boundary_path).exists():
        return None, None, None
    try:
        import fiona
        from shapely.geometry import shape
        from shapely.ops import transform, unary_union
        from pyproj import Transformer

        path = Path(boundary_path)
        layer = "taihu_boundary_wgs84"
        try:
            layers = fiona.listlayers(path)
            if layer not in layers:
                layer = layers[0]
        except Exception:
            pass
        with fiona.open(path, layer=layer) as source:
            geometries = [shape(item["geometry"]) for item in source if item.get("geometry")]
        if not geometries:
            return None, str(path), None
        geometry = unary_union(geometries)
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
        area_km2 = float(transform(transformer.transform, geometry).area / 1_000_000.0)
        return geometry, str(path), area_km2
    except Exception:
        # Spatial alignment remains usable without a boundary, but the manifest
        # must state that lake-area statistics are coverage estimates only.
        return None, str(boundary_path), None


def _remote_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("_category") == "remote_sensing"
        and row.get("clean_value") is not None
        and row.get("longitude") is not None
        and row.get("latitude") is not None
    ]


def _station_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("station_id") not in (None, "")
        and row.get("_category") != "remote_sensing"
        and row.get("longitude") is not None
        and row.get("latitude") is not None
    ]


def _station_buffer_matches(
    rows: list[dict[str, Any]],
    *,
    grid_size_m: float,
    buffer_pixels: tuple[int, ...],
) -> list[dict[str, Any]]:
    remote = _remote_rows(rows)
    stations = _station_rows(rows)
    radii = sorted({int(item) for item in buffer_pixels if int(item) > 0})
    if not radii:
        raise ValueError("buffer_pixels must contain at least one positive integer")
    max_radius = max(radii) * grid_size_m
    output: list[dict[str, Any]] = []
    for station in stations:
        station_time = _spatial_time_key(station)
        candidates = [item for item in remote if _spatial_time_key(item) == station_time]
        matched = False
        for candidate in candidates:
            distance = _haversine_m(
                float(station["longitude"]), float(station["latitude"]),
                float(candidate["longitude"]), float(candidate["latitude"]),
            )
            if distance > max_radius:
                continue
            hit = next((pixels for pixels in radii if distance <= pixels * grid_size_m), radii[-1])
            matched = True
            output.append({
                "station_source_id": station.get("source_id"),
                "station_id": station.get("station_id"),
                "station_variable_code": station.get("variable_code"),
                "station_time_bucket": station.get("time_bucket") or station.get("observed_at"),
                "station_clean_value": station.get("clean_value"),
                "station_longitude": station.get("longitude"),
                "station_latitude": station.get("latitude"),
                "remote_source_id": candidate.get("source_id"),
                "remote_scene_id": candidate.get("scene_id"),
                "remote_variable_code": candidate.get("variable_code"),
                "remote_time_bucket": candidate.get("time_bucket") or candidate.get("observed_at"),
                "remote_clean_value": candidate.get("clean_value"),
                "remote_longitude": candidate.get("longitude"),
                "remote_latitude": candidate.get("latitude"),
                "distance_m": round(distance, 3),
                "buffer_pixels": hit,
                "buffer_radius_m": round(hit * grid_size_m, 3),
                "within_1px": distance <= 1 * grid_size_m,
                "within_2px": distance <= 2 * grid_size_m,
                "within_3px": distance <= 3 * grid_size_m,
                "spatial_match_status": "matched",
                "alignment_reason": f"same_time_bucket_within_{hit}_pixels",
                "quality_flags": [],
            })
        if not matched:
            flags = []
            if station_time is None:
                flags.append("Q23")
            output.append({
                "station_source_id": station.get("source_id"),
                "station_id": station.get("station_id"),
                "station_variable_code": station.get("variable_code"),
                "station_time_bucket": station.get("time_bucket") or station.get("observed_at"),
                "station_clean_value": station.get("clean_value"),
                "station_longitude": station.get("longitude"),
                "station_latitude": station.get("latitude"),
                "remote_source_id": None, "remote_scene_id": None, "remote_variable_code": None,
                "remote_time_bucket": None, "remote_clean_value": None,
                "remote_longitude": None, "remote_latitude": None,
                "distance_m": None, "buffer_pixels": None, "buffer_radius_m": max_radius,
                "within_1px": False, "within_2px": False, "within_3px": False,
                "spatial_match_status": "no_remote_within_3px",
                "alignment_reason": "no_same_time_remote_pixel_within_buffer",
                "quality_flags": flags + ["Q23"],
            })
    return output


def _grid_aggregate(
    rows: list[dict[str, Any]],
    *,
    grid_size_m: float,
    grid_origin: tuple[float, float],
    boundary_geometry: Any | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from shapely.geometry import Point
    except Exception:
        Point = None
    pixels = _remote_rows(rows)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in pixels:
        x, y = _local_xy_m(float(row["longitude"]), float(row["latitude"]), grid_origin)
        grid_x, grid_y = math.floor(x / grid_size_m), math.floor(y / grid_size_m)
        key = (_spatial_time_key(row), row.get("variable_code"), row.get("source_id"), grid_x, grid_y)
        copy = dict(row)
        copy["_grid_x"], copy["_grid_y"] = grid_x, grid_y
        groups[key].append(copy)
    output: list[dict[str, Any]] = []
    for (time_key, variable, source_id, grid_x, grid_y), members in sorted(groups.items(), key=lambda item: str(item[0])):
        center_lon, center_lat = _local_lonlat((grid_x + 0.5) * grid_size_m, (grid_y + 0.5) * grid_size_m, grid_origin)
        in_lake = None
        if boundary_geometry is not None and Point is not None:
            in_lake = bool(boundary_geometry.covers(Point(center_lon, center_lat)))
        values = [float(item["clean_value"]) for item in members if item.get("clean_value") is not None]
        source_sizes = [_normalise_pixel_size(item) for item in members]
        source_sizes = [item for item in source_sizes if item is not None]
        output.append({
            "time_bucket": time_key, "variable_code": variable, "source_id": source_id,
            "grid_id": f"g{grid_x}_{grid_y}", "grid_x": grid_x, "grid_y": grid_y,
            "grid_center_longitude": round(center_lon, 9), "grid_center_latitude": round(center_lat, 9),
            "grid_size_m": grid_size_m, "n_pixels": len(members), "valid_pixel_count": len(values),
            "valid_fraction": round(len(values) / len(members), 6) if members else 0.0,
            "value_mean": round(sum(values) / len(values), 9) if values else None,
            "source_pixel_resolution_m": min(source_sizes) if source_sizes else None,
            "source_pixel_resolutions_m": sorted(set(source_sizes)),
            "estimated_pixel_area_km2": round(sum((item / 1000.0) ** 2 for item in source_sizes), 9) if source_sizes else None,
            "in_lake": in_lake,
            "quality_flags": [] if values else ["Q01"],
        })
    stats_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in output:
        stats_groups[(row["time_bucket"], row["variable_code"], row["source_id"])].append(row)
    stats: list[dict[str, Any]] = []
    for (time_key, variable, source_id), members in sorted(stats_groups.items(), key=lambda item: str(item[0])):
        lake_members = [item for item in members if item.get("in_lake") is True]
        has_boundary = boundary_geometry is not None
        valid_cells = [item for item in lake_members if item.get("valid_pixel_count", 0) > 0]
        pixel_area = sum(float(item.get("estimated_pixel_area_km2") or 0.0) for item in valid_cells)
        stats.append({
            "time_bucket": time_key, "variable_code": variable, "source_id": source_id,
            "grid_size_m": grid_size_m, "grid_cells_total": len(members),
            "grid_cells_in_lake": len(lake_members) if has_boundary else None,
            "valid_grid_cells": len(valid_cells),
            "valid_fraction": round(len(valid_cells) / len(lake_members), 6) if lake_members else 0.0,
            "valid_pixel_area_km2": round(pixel_area, 9) if pixel_area else 0.0,
            "lake_area_km2": None,
            "area_status": "boundary_unavailable" if not has_boundary else "boundary_loaded",
            "boundary_source": None,
        })
    return output, stats


def spatial_align_records(
    rows: list[dict[str, Any]],
    *,
    boundary_path: Path | None = None,
    grid_size_m: float = DEFAULT_GRID_SIZE_M,
    station_buffer_pixels: tuple[int, ...] = DEFAULT_STATION_BUFFER_PIXELS,
    grid_origin: tuple[float, float] = DEFAULT_GRID_ORIGIN,
) -> dict[str, Any]:
    if grid_size_m <= 0:
        raise ValueError("grid_size_m must be positive")
    if len(grid_origin) != 2:
        raise ValueError("grid_origin must be (longitude, latitude)")
    boundary_geometry, boundary_source, boundary_area_km2 = _load_boundary_geometry(boundary_path)
    station_matches = _station_buffer_matches(rows, grid_size_m=grid_size_m, buffer_pixels=station_buffer_pixels)
    grid_rows, lake_stats = _grid_aggregate(
        rows, grid_size_m=grid_size_m, grid_origin=grid_origin, boundary_geometry=boundary_geometry,
    )
    for item in lake_stats:
        item["lake_area_km2"] = boundary_area_km2
        item["boundary_source"] = boundary_source
    return {
        "station_buffer_matches": station_matches,
        "grid_300m_observations": grid_rows,
        "lake_area_stats": lake_stats,
        "counts": {
            "input_rows": len(rows), "station_rows": len(_station_rows(rows)),
            "remote_pixel_rows": len(_remote_rows(rows)), "station_buffer_rows": len(station_matches),
            "matched_station_buffer_rows": sum(1 for item in station_matches if item.get("spatial_match_status") == "matched"),
            "grid_rows": len(grid_rows), "lake_stat_rows": len(lake_stats),
        },
        "spatial_policy": "stations match same-time remote pixels within the smallest configured 1/2/3-pixel buffer; remote pixels aggregate to a deterministic 300 m grid; lake statistics are boundary-clipped when the authoritative polygon is available",
        "grid": {"grid_size_m": grid_size_m, "origin": list(grid_origin), "station_buffer_pixels": list(station_buffer_pixels)},
        "boundary": {"source": boundary_source, "area_km2": boundary_area_km2, "status": "loaded" if boundary_geometry is not None else "unavailable"},
    }


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def _series_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("source_id"), row.get("station_id"), row.get("scene_id"), row.get("variable_code"))


def _candidate_spatial(target: dict[str, Any], candidate: dict[str, Any], max_space_m: float) -> tuple[int, float | None, str]:
    target_station = target.get("station_id")
    candidate_station = candidate.get("station_id")
    if target_station and candidate_station and target_station == candidate_station:
        return 0, 0.0, "same_station"
    coords = (target.get("longitude"), target.get("latitude"), candidate.get("longitude"), candidate.get("latitude"))
    if all(value is not None for value in coords):
        distance = _haversine_m(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))
        if distance <= max_space_m:
            return 1, distance, "coordinate_distance"
        return 99, distance, "outside_radius"
    return 2, None, "not_available"


def _nearest_in_series(
    target: dict[str, Any],
    series_index: tuple[list[datetime], list[dict[str, Any]]],
    max_time_diff_hours: float,
    max_space_m: float,
) -> tuple[dict[str, Any] | None, float | None, float | None, float | None, str]:
    times, valid_rows = series_index
    if not times or target.get("_time") is None:
        return None, None, None, None, "no_candidate"
    position = bisect_left(times, target["_time"])
    best: tuple[tuple[float, float, float], dict[str, Any], float | None, str] | None = None
    for index in {max(0, position - 1), min(len(valid_rows) - 1, position)}:
        candidate = valid_rows[index]
        time_gap = abs((candidate["_time"] - target["_time"]).total_seconds()) / 3600.0
        if time_gap > max_time_diff_hours:
            continue
        spatial_rank, distance, spatial_status = _candidate_spatial(target, candidate, max_space_m)
        if spatial_rank >= 99:
            continue
        distance_score = distance if distance is not None else 0.0
        score = (float(spatial_rank), time_gap, distance_score)
        if best is None or score < best[0]:
            best = (score, candidate, distance, spatial_status)
    if best is None:
        return None, None, None, None, "no_match_within_threshold"
    signed_gap = (best[1]["_time"] - target["_time"]).total_seconds() / 3600.0
    return best[1], best[0][1], signed_gap, best[2], best[3]


def align_records(
    rows: list[dict[str, Any]],
    *,
    max_time_diff_hours: float = DEFAULT_MAX_TIME_DIFF_HOURS,
    ideal_ground_remote_hours: float = DEFAULT_IDEAL_GROUND_REMOTE_HOURS,
    max_space_m: float = 50_000.0,
    matching_strategy: str = "nearest",
) -> dict[str, Any]:
    if max_time_diff_hours <= 0 or ideal_ground_remote_hours <= 0 or ideal_ground_remote_hours > max_time_diff_hours:
        raise ValueError("time windows must be positive and ideal_ground_remote_hours <= max_time_diff_hours")
    if max_space_m < 0:
        raise ValueError("max_space_m must be non-negative")
    if matching_strategy not in MATCHING_STRATEGIES:
        raise ValueError(f"unsupported matching_strategy: {matching_strategy}")
    targets = [row for row in rows if row.get("_category") in {"water_quality", "remote_sensing"} and row.get("clean_value") is not None]
    series_by_variable: dict[str, list[tuple[list[datetime], list[dict[str, Any]], str]]] = defaultdict(list)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("_category") in {"meteorology", "hydrology", "remote_sensing", "water_quality"} and row.get("clean_value") is not None:
            grouped[_series_key(row)].append(row)
    for series in grouped.values():
        ordered = sorted(series, key=lambda item: item.get("_time") or datetime.max.replace(tzinfo=timezone.utc))
        valid = [row for row in ordered if row.get("_time") is not None and row.get("clean_value") is not None]
        series_by_variable[str(series[0].get("variable_code") or "")].append(([row["_time"] for row in valid], valid, _category(valid[0]) if valid else "other"))

    alignments: list[dict[str, Any]] = []
    match_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    for target in targets:
        target_category = str(target.get("_category"))
        target_counts[target_category] += 1
        for variable, series_list in sorted(series_by_variable.items()):
            if variable == target.get("variable_code") and target_category == _category(target):
                continue
            # Only drivers that can be used by the first-release model are
            # emitted; unrelated archive variables stay in the resampled table.
            feature_category = next((item[2] for item in series_list if item[2] != "other"), "other")
            if feature_category not in {"meteorology", "hydrology", "remote_sensing", "water_quality"}:
                continue
            best: tuple[tuple[float, float, int, float], dict[str, Any], float | None, float | None, float | None, str, str, float] | None = None
            for series_index in series_list:
                candidate_category = series_index[2]
                candidate, time_gap, signed_gap, space_gap, spatial_status = _nearest_in_series(target, (series_index[0], series_index[1]), max_time_diff_hours, max_space_m)
                if candidate is None or time_gap is None:
                    continue
                rank = 0 if spatial_status == "same_station" else 1 if spatial_status == "coordinate_distance" else 2
                distance_score = space_gap if space_gap is not None else 0.0
                ground_remote_pair = _is_ground_remote_pair(target_category, candidate_category)
                time_window = ideal_ground_remote_hours if ground_remote_pair else max_time_diff_hours
                if time_gap > time_window:
                    # A ground—satellite pair may use the ordinary 24 h
                    # window, but it is explicitly marked as regular rather
                    # than being presented as an ideal ±3 h match.
                    if not ground_remote_pair or time_gap > max_time_diff_hours:
                        continue
                    time_class = "regular_24h"
                    window_rank = 1
                    time_window = max_time_diff_hours
                elif ground_remote_pair and time_gap <= ideal_ground_remote_hours:
                    time_class = "ideal_3h"
                    window_rank = 0
                else:
                    time_class = "regular_24h"
                    window_rank = 1
                score = (float(window_rank), time_gap, rank, distance_score)
                if best is None or score < best[0]:
                    best = (score, candidate, time_gap, signed_gap, space_gap, spatial_status, time_class, time_window)
            if best is None:
                alignments.append(
                    {
                        "target_source_id": target.get("source_id"), "target_station_id": target.get("station_id"),
                        "target_scene_id": target.get("scene_id"),
                        "target_variable_code": target.get("variable_code"), "target_time_bucket": target.get("time_bucket"),
                        "target_clean_value": target.get("clean_value"), "feature_source_id": None,
                        "feature_station_id": None, "feature_scene_id": None, "feature_variable_code": variable,
                        "feature_time_bucket": None, "feature_clean_value": None,
                        "time_gap_hours": None, "time_gap_signed_hours": None, "time_window_hours": ideal_ground_remote_hours if _is_ground_remote_pair(target_category, feature_category) else max_time_diff_hours,
                        "time_match_class": "unmatched", "matching_strategy": matching_strategy, "space_gap_m": None,
                        "target_category": target_category, "feature_category": feature_category,
                        "spatial_status": "not_available", "match_status": "unmatched",
                        "alignment_reason": "no_candidate_within_time_and_space_window",
                        "quality_flags": ["Q23"],
                    }
                )
                match_counts["unmatched"] += 1
                continue
            candidate = best[1]
            status = "matched_temporal_spatial" if best[5] in {"same_station", "coordinate_distance"} else "matched_temporal_only"
            alignment_reason = "matched_within_time_and_space_window" if status == "matched_temporal_spatial" else "spatial_metadata_unavailable"
            flags = []
            if status == "matched_temporal_only":
                flags.append("Q23")
            alignments.append(
                {
                    "target_source_id": target.get("source_id"), "target_station_id": target.get("station_id"),
                    "target_scene_id": target.get("scene_id"),
                    "target_variable_code": target.get("variable_code"), "target_time_bucket": target.get("time_bucket"),
                    "target_clean_value": target.get("clean_value"), "feature_source_id": candidate.get("source_id"),
                    "feature_station_id": candidate.get("station_id"), "feature_scene_id": candidate.get("scene_id"), "feature_variable_code": variable,
                    "feature_time_bucket": candidate.get("time_bucket"), "feature_clean_value": candidate.get("clean_value"),
                    "time_gap_hours": round(float(best[2]), 6), "time_gap_signed_hours": round(float(best[3]), 6) if best[3] is not None else None,
                    "time_window_hours": best[7], "time_match_class": best[6], "matching_strategy": matching_strategy,
                    "space_gap_m": None if best[4] is None else round(float(best[4]), 3),
                    "target_category": target_category, "feature_category": feature_category,
                    "spatial_status": best[5], "match_status": status, "alignment_reason": alignment_reason, "quality_flags": flags,
                }
            )
            match_counts[status] += 1
    return {
        "records": alignments,
        "target_counts": dict(target_counts),
        "match_counts": dict(match_counts),
        "series_count": sum(len(items) for items in series_by_variable.values()),
        "thresholds": {"max_time_diff_hours": max_time_diff_hours, "ideal_ground_remote_hours": ideal_ground_remote_hours, "max_space_m": max_space_m},
        "matching_strategy": matching_strategy,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    return len(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS temporal_alignments")
        connection.execute(
            """CREATE TABLE temporal_alignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_source_id TEXT, target_station_id TEXT, target_scene_id TEXT, target_variable_code TEXT,
                target_time_bucket TEXT, target_clean_value REAL,
                feature_source_id TEXT, feature_station_id TEXT, feature_scene_id TEXT, feature_variable_code TEXT,
                feature_time_bucket TEXT, feature_clean_value REAL,
                time_gap_hours REAL, time_gap_signed_hours REAL, time_window_hours REAL, time_match_class TEXT, matching_strategy TEXT, space_gap_m REAL,
                target_category TEXT, feature_category TEXT,
                spatial_status TEXT, match_status TEXT, alignment_reason TEXT, quality_flags TEXT
            )"""
        )
        columns = [
            "target_source_id", "target_station_id", "target_scene_id", "target_variable_code", "target_time_bucket", "target_clean_value",
            "feature_source_id", "feature_station_id", "feature_scene_id", "feature_variable_code", "feature_time_bucket", "feature_clean_value",
            "time_gap_hours", "time_gap_signed_hours", "time_window_hours", "time_match_class", "matching_strategy", "space_gap_m",
            "target_category", "feature_category", "spatial_status", "match_status", "alignment_reason", "quality_flags",
        ]
        sql = f"INSERT INTO temporal_alignments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        connection.executemany(sql, [tuple(json.dumps(row.get(column), ensure_ascii=False) if column == "quality_flags" else row.get(column) for column in columns) for row in rows])
        connection.commit()
    finally:
        connection.close()


def run_alignment(
    input_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    max_time_diff_hours: float = DEFAULT_MAX_TIME_DIFF_HOURS,
    ideal_ground_remote_hours: float = DEFAULT_IDEAL_GROUND_REMOTE_HOURS,
    max_space_m: float = 50_000.0,
    matching_strategy: str = "nearest",
    manifest_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    rows = read_resampled_csv(input_path)
    result = align_records(rows, max_time_diff_hours=max_time_diff_hours, ideal_ground_remote_hours=ideal_ground_remote_hours, max_space_m=max_space_m, matching_strategy=matching_strategy)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or Path(__file__).resolve().parents[1] / "storage" / "exports" / f"align_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "temporal_alignments.csv"
    _write_csv(output, result["records"])
    database = database or Path(__file__).resolve().parents[1] / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["records"])
    manifest = {
        "run_id": run_id or f"align_{stamp}",
        "status": "completed_with_temporal_only_or_unmatched" if any(row.get("match_status") != "matched_temporal_spatial" for row in result["records"]) else "completed",
        "input": str(input_path), "output": str(output), "database": str(database),
        "input_rows": len(rows), "alignment_rows": len(result["records"]),
        "target_counts": result["target_counts"], "match_counts": result["match_counts"], "series_count": result["series_count"],
        "thresholds": {"max_time_diff_hours": max_time_diff_hours, "ideal_ground_remote_hours": ideal_ground_remote_hours, "max_space_m": max_space_m},
        "matching_strategy": matching_strategy,
        "temporal_policy": "ground—satellite ideal ±3h, regular <=24h; ordinary drivers nearest <=24h; signed and absolute time gaps returned",
        "spatial_policy": "same station or both coordinates within radius; otherwise temporal-only with Q23; never fabricate distance",
    }
    manifest_path = manifest_path or Path(__file__).resolve().parents[1] / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest


def _write_spatial_sqlite(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        schemas = {
            "station_buffer_matches": result["station_buffer_matches"],
            "grid_300m_observations": result["grid_300m_observations"],
            "lake_area_stats": result["lake_area_stats"],
        }
        for table, rows in schemas.items():
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
            if not rows:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY AUTOINCREMENT)')
                continue
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            definitions = []
            for column in columns:
                sample = next((row.get(column) for row in rows if row.get(column) is not None), None)
                sql_type = "REAL" if isinstance(sample, (int, float)) and not isinstance(sample, bool) else "INTEGER" if isinstance(sample, bool) else "TEXT"
                definitions.append(f'"{column}" {sql_type}')
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')
            values = []
            for row in rows:
                values.append(tuple(
                    json.dumps(row.get(column), ensure_ascii=False)
                    if isinstance(row.get(column), (list, dict)) else row.get(column)
                    for column in columns
                ))
            placeholders = ",".join("?" for _ in columns)
            column_sql = ",".join(f'"{item}"' for item in columns)
            connection.executemany(f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})', values)
        connection.commit()
    finally:
        connection.close()


def run_spatial_alignment(
    input_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    boundary_path: Path | None = None,
    grid_size_m: float = DEFAULT_GRID_SIZE_M,
    station_buffer_pixels: tuple[int, ...] = DEFAULT_STATION_BUFFER_PIXELS,
    grid_origin: tuple[float, float] = DEFAULT_GRID_ORIGIN,
    manifest_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    rows = read_resampled_csv(input_path)
    result = spatial_align_records(
        rows,
        boundary_path=boundary_path,
        grid_size_m=grid_size_m,
        station_buffer_pixels=station_buffer_pixels,
        grid_origin=grid_origin,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root or Path(__file__).resolve().parents[1] / "storage" / "exports" / f"spatial_align_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "station_buffer_matches": output_root / "station_buffer_matches.csv",
        "grid_300m_observations": output_root / "grid_300m_observations.csv",
        "lake_area_stats": output_root / "lake_area_stats.csv",
    }
    for key, path in outputs.items():
        _write_csv(path, result[key])
    database = database or Path(__file__).resolve().parents[1] / "storage" / "data_cleaning.db"
    _write_spatial_sqlite(database, result)
    manifest = {
        "run_id": run_id or f"spatial_align_{stamp}",
        "status": "completed",
        "input": str(input_path),
        "outputs": {key: str(path) for key, path in outputs.items()},
        "database": str(database),
        "counts": result["counts"],
        "grid": result["grid"],
        "boundary": result["boundary"],
        "spatial_policy": result["spatial_policy"],
        "data_truth": "real_input_rows_only; no synthetic observations; unknown pixel resolution remains null; boundary-unavailable area is not presented as authoritative lake area",
    }
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
