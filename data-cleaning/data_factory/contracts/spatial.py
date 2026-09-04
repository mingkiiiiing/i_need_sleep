"""冻结 1km 网格、湖区划分与站点映射 (设计 §6.2 / contracts.spatial)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform
from shapely.prepared import prep

CRS_AREA = "EPSG:32651"
CRS_STORAGE = "EPSG:4326"


@dataclass
class GridSpec:
    cell_size_m: int = 1000
    min_water_fraction: float = 0.05


def load_boundary(gpkg: Path) -> tuple[Any, Any, dict[str, Any]]:
    """返回 (WGS84 几何, UTM51N 几何, 元数据)。"""

    layers = fiona.listlayers(gpkg)
    layer = "taihu_boundary_wgs84" if "taihu_boundary_wgs84" in layers else layers[0]
    with fiona.open(gpkg, layer=layer) as collection:
        features = list(collection)
    feature = features[0]
    geom_wgs84 = shape(feature["geometry"])
    transformer = Transformer.from_crs(CRS_STORAGE, CRS_AREA, always_xy=True)
    geom_utm = shp_transform(transformer.transform, geom_wgs84)
    meta = dict(feature["properties"])
    return geom_wgs84, geom_utm, meta


def build_grid(geom_wgs84: Any, geom_utm: Any, spec: GridSpec) -> pd.DataFrame:
    prepared = prep(geom_utm)
    min_x, min_y, max_x, max_y = geom_utm.bounds
    cell = spec.cell_size_m
    to_wgs84 = Transformer.from_crs(CRS_AREA, CRS_STORAGE, always_xy=True)
    ix0, iy0 = int(np.floor(min_x / cell)), int(np.floor(min_y / cell))
    ix1, iy1 = int(np.ceil(max_x / cell)), int(np.ceil(max_y / cell))
    rows: list[dict[str, Any]] = []
    for ix in range(ix0, ix1):
        for iy in range(iy0, iy1):
            x0, y0 = ix * cell, iy * cell
            square = shapely_box(x0, y0, x0 + cell, y0 + cell)
            if not prepared.intersects(square):
                continue
            inter = geom_utm.intersection(square)
            area = inter.area
            water_fraction = area / (cell * cell)
            if water_fraction < spec.min_water_fraction:
                continue
            centroid = inter.centroid
            lon, lat = to_wgs84.transform(centroid.x, centroid.y)
            rows.append(
                {
                    "ix": ix,
                    "iy": iy,
                    "utm_x": centroid.x,
                    "utm_y": centroid.y,
                    "lon": lon,
                    "lat": lat,
                    "water_fraction": water_fraction,
                    "effective_water_area_m2": area,
                }
            )
    df = pd.DataFrame(rows)
    df["grid_id"] = df.apply(lambda r: f"G{int(r['ix']):04d}{int(r['iy']):04d}", axis=1)
    return df


def shapely_box(x0: float, y0: float, x1: float, y1: float):  # 局部小工具，避免顶部多余导入
    from shapely.geometry import box

    return box(x0, y0, x1, y1)


def assign_zones(cells: pd.DataFrame, geom_utm: Any, zone_rules: dict[str, Any]) -> pd.DataFrame:
    """从湖体质心按方位角扇区划分湖区（derived 近似，可配置）。"""

    cx, cy = geom_utm.centroid.x, geom_utm.centroid.y
    dx = cells["utm_x"] - cx
    dy = cells["utm_y"] - cy
    azimuth = (np.degrees(np.arctan2(dx, dy))) % 360.0
    radius = np.hypot(dx, dy)
    center_radius_m = float(zone_rules.get("center_radius_km", 6.0)) * 1000.0
    max_radius = float(np.percentile(radius, 98))
    zone_code = np.full(len(cells), "", dtype=object)
    in_center = radius <= center_radius_m
    zone_code[in_center] = "TAIHU_CT"
    sectors: dict[str, tuple[float, float]] = {
        k: tuple(v) for k, v in (zone_rules.get("sectors") or {}).items()
    }
    for code, (start, end) in sectors.items():
        if end >= start:
            mask = (azimuth >= start) & (azimuth < end)
        else:
            mask = (azimuth >= start) | (azimuth < end)
        zone_code[mask & ~in_center] = code
    fallback = zone_rules.get("fallback", "TAIHU_CT")
    zone_code[(zone_code == "") & ~in_center] = fallback
    cells = cells.copy()
    cells["zone_code"] = zone_code
    cells["lake_zone"] = cells["zone_code"].map(ZONE_NAMES).fillna(cells["zone_code"])
    cells["radius_ratio"] = radius / max(max_radius, 1.0)
    return cells


ZONE_NAMES: dict[str, str] = {
    "TAIHU_ML": "梅梁湾",
    "TAIHU_ZS": "竺山湖",
    "TAIHU_GH": "贡湖",
    "TAIHU_XK": "胥湖",
    "TAIHU_ET": "东太湖",
    "TAIHU_CT": "湖心区",
    "TAIHU_WT": "西部沿岸",
    "TAIHU_ST": "南部沿岸",
}


def _grid_version(metadata_csv_text: str) -> str:
    return "gridv1-" + hashlib.sha256(metadata_csv_text.encode("utf-8")).hexdigest()[:16]


def _edge_flags(cells: pd.DataFrame) -> np.ndarray:
    seen = set(zip(cells["ix"], cells["iy"]))
    edges = []
    for ix, iy in zip(cells["ix"], cells["iy"]):
        complete = all((ix + dx, iy + dy) in seen for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        edges.append(not complete)
    return np.array(edges, dtype=bool)


TAIHU_DOMAIN_LON = (119.8, 120.6)
TAIHU_DOMAIN_LAT = (30.5, 31.5)


def _num_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _coords_sane(lon: Any, lat: Any) -> bool:
    """DG-013：太湖域坐标健全性——非空有限数值且落在太湖经纬范围内。"""
    lo, la = _num_or_none(lon), _num_or_none(lat)
    if lo is None or la is None:
        return False
    return TAIHU_DOMAIN_LON[0] <= lo <= TAIHU_DOMAIN_LON[1] and TAIHU_DOMAIN_LAT[0] <= la <= TAIHU_DOMAIN_LAT[1]


def map_stations(stations: pd.DataFrame, cells: pd.DataFrame, geom_wgs84: Any, *, max_dist_m: float = 2000.0) -> pd.DataFrame:
    """站点→网格映射。DG-013：坐标不健全（越出太湖域/非数值）→ bad_coordinates，
    界外 → outside_boundary；二者均不分配网格（grid_id=None）。仅界内且就近有格网的站
    mapping_status=mapped，才可进入观测层采样。"""

    to_utm = Transformer.from_crs(CRS_STORAGE, CRS_AREA, always_xy=True)
    cell_tree = cKDTree(cells[["utm_x", "utm_y"]].to_numpy(dtype=float))
    prepared = prep(geom_wgs84)
    from shapely.geometry import Point

    out = []
    for row in stations.to_dict("records"):
        lon_raw, lat_raw = row.get("lon"), row.get("lat")
        sane = _coords_sane(lon_raw, lat_raw)
        inside = False
        cell = None
        dist = None
        if sane:
            lon, lat = float(lon_raw), float(lat_raw)
            point = Point(lon, lat)
            inside = bool(prepared.contains(point))
            x, y = to_utm.transform(lon, lat)
            d, idx = cell_tree.query([x, y])
            if inside and d <= max_dist_m:
                dist, cell = float(d), cells.iloc[int(idx)]
        else:
            lon, lat = _num_or_none(lon_raw), _num_or_none(lat_raw)
        if not sane:
            status, reason = "bad_coordinates", "coords_outside_taihu_domain_or_nonnumeric"
        elif not inside:
            status, reason = "outside_boundary", "outside_lake_boundary"
        elif cell is None:
            status, reason = "unmapped_no_grid_cell", "no_grid_cell_within_max_distance"
        else:
            status, reason = "mapped", ""
        out.append(
            {
                "station_id": row["station_id"],
                "station_name": row.get("station_name", row["station_id"]),
                "station_type": row.get("station_type", "unknown"),
                "lon": lon,
                "lat": lat,
                "grid_id": cell["grid_id"] if cell is not None else None,
                "lake_zone": cell["lake_zone"] if cell is not None else None,
                "zone_code": cell["zone_code"] if cell is not None else None,
                "outside_boundary": not inside,
                "mapping_status": status,
                "unmapped_reason": reason,
                "map_distance_m": dist,
                "provenance_type": row.get("provenance_type", "metadata_only"),
                "registry_source": row.get("registry_source", "taihugurad_stations_json"),
            }
        )
    return pd.DataFrame(out)


def run_freeze_grid(config: dict[str, Any], *, boundary_gpkg: Path, out_dir: Path, stations_json: Path | None = None) -> dict[str, Any]:
    grid_cfg = config["grid"]
    spec = GridSpec(cell_size_m=int(grid_cfg.get("cell_size_m", 1000)), min_water_fraction=float(grid_cfg.get("min_water_fraction", 0.05)))
    geom_wgs84, geom_utm, boundary_meta = load_boundary(boundary_gpkg)
    cells = build_grid(geom_wgs84, geom_utm, spec)
    cells = assign_zones(cells, geom_utm, config.get("zones", {}))

    # 静态先验：湖区平均水深（derived，来自 mechanism_parameters 的湖区先验）
    zone_depth = (config.get("zone_priors") or {}).get("depth_mean_m", {})
    cells["depth_mean_m"] = cells["zone_code"].map(zone_depth).astype(float)
    cells["shoreline_dist_m"] = cells.apply(lambda r: geom_utm.exterior.distance(PointUtm(r["utm_x"], r["utm_y"])), axis=1)
    cells["is_edge"] = _edge_flags(cells)
    cells["grid_version"] = "pending"

    columns = [
        "grid_id", "lon", "lat", "utm_x", "utm_y", "water_fraction", "effective_water_area_m2",
        "lake_zone", "zone_code", "shoreline_dist_m", "depth_mean_m", "is_edge",
    ]
    meta_text = cells[columns].sort_values("grid_id").to_csv(index=False)
    version = _grid_version(meta_text)
    cells["grid_version"] = version

    out_dir.mkdir(parents=True, exist_ok=True)
    cells[["grid_version"] + columns].to_csv(out_dir / "grid_metadata.csv", index=False)

    def _features(frame: pd.DataFrame, props_fn) -> list[dict[str, Any]]:
        cell = spec.cell_size_m
        features = []
        for row in frame.itertuples(index=False):
            x0 = int(row.ix) * cell
            y0 = int(row.iy) * cell
            square_wgs = _square_wgs84(x0, y0, cell)
            features.append({"type": "Feature", "geometry": mapping(square_wgs), "properties": props_fn(row)})
        return features

    grid_fc = {"type": "FeatureCollection", "features": _features(cells, lambda r: {"grid_id": r.grid_id, "zone_code": r.zone_code, "grid_version": version})}
    (out_dir / "grid_boundaries.geojson").write_text(json.dumps(grid_fc, ensure_ascii=False), encoding="utf-8")

    zone_summary = cells.groupby("zone_code")["effective_water_area_m2"].sum().to_dict()
    region_fc = {"type": "FeatureCollection", "features": _features(cells, lambda r: {"zone_code": r.zone_code})}
    (out_dir / "region_boundaries.geojson").write_text(json.dumps(region_fc, ensure_ascii=False), encoding="utf-8")
    lake_fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(geom_wgs84), "properties": {"hylak_id": boundary_meta.get("Hylak_id", 148)}}]}
    (out_dir / "lake_boundary.geojson").write_text(json.dumps(lake_fc, ensure_ascii=False), encoding="utf-8")

    stations = pd.DataFrame()
    if stations_json is not None and Path(stations_json).exists():
        payload = json.loads(Path(stations_json).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            entries = payload
        else:
            entries = payload.get("stations", [])
        stations = pd.DataFrame(
            [
                {
                    "station_id": s.get("id") or s.get("name"),
                    "station_name": s.get("name"),
                    "station_type": s.get("type", "unknown"),
                    "lon": s.get("lon"),
                    "lat": s.get("lat"),
                    "provenance_type": "metadata_only",
                    "registry_source": "taihugurad_stations_json",
                }
                for s in entries
                if s.get("lon") is not None and s.get("lat") is not None
            ]
        )
    mapping_df = map_stations(stations, cells, geom_wgs84) if not stations.empty else pd.DataFrame(columns=["station_id", "station_name", "station_type", "lon", "lat", "grid_id", "lake_zone", "zone_code", "outside_boundary", "mapping_status", "unmapped_reason", "map_distance_m", "provenance_type", "registry_source"])
    status_col = "mapping_status" if "mapping_status" in mapping_df.columns else None
    stations_out = mapping_df[["station_id", "station_name", "station_type", "lon", "lat", "provenance_type", "registry_source"] + (["mapping_status", "unmapped_reason"] if status_col else [])].copy()
    stations_out.to_csv(out_dir / "stations.csv", index=False)
    mapping_df.to_csv(out_dir / "station_grid_mapping.csv", index=False)

    manifest = {
        "status": "completed",
        "grid_version": version,
        "cell_size_m": spec.cell_size_m,
        "n_cells": int(len(cells)),
        "total_water_area_km2": round(float(cells["effective_water_area_m2"].sum()) / 1e6, 3),
        # DG-001：冻结的全湖有效水面面积，作为 partial-domain 覆盖率的分母
        "lake_area_km2_frozen": round(float(cells["effective_water_area_m2"].sum()) / 1e6, 3),
        "n_zones": int(cells["zone_code"].nunique()),
        "zone_area_km2": {k: round(v / 1e6, 3) for k, v in zone_summary.items()},
        "n_stations": int(len(stations_out)),
        "outside_boundary_stations": int((mapping_df["mapping_status"] == "outside_boundary").sum()) if status_col else 0,
        "bad_coordinates_stations": int((mapping_df["mapping_status"] == "bad_coordinates").sum()) if status_col else 0,
        "mapped_stations": int((mapping_df["mapping_status"] == "mapped").sum()) if status_col else 0,
        "mapping_status_counts": mapping_df["mapping_status"].value_counts().to_dict() if status_col else {},
        "outputs": ["grid_metadata.csv", "grid_boundaries.geojson", "region_boundaries.geojson", "lake_boundary.geojson", "stations.csv", "station_grid_mapping.csv"],
    }
    (out_dir / "grid_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def PointUtm(x: float, y: float):
    from shapely.geometry import Point

    return Point(x, y)


def _square_wgs84(x0: float, y0: float, cell: int):
    from shapely.geometry import box
    from shapely.ops import transform as t
    from pyproj import Transformer

    to_wgs84 = Transformer.from_crs(CRS_AREA, CRS_STORAGE, always_xy=True)
    return t(to_wgs84.transform, box(x0, y0, x0 + cell, y0 + cell))


def load_grid(grid_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    cells = pd.read_csv(grid_dir / "grid_metadata.csv")
    manifest = json.loads((grid_dir / "grid_manifest.json").read_text(encoding="utf-8"))
    return cells, manifest


def cell_indices(grid_ids: pd.Series | list[str] | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """grid_id G{ix:04d}{iy:04d} → (ix, iy) 整型数组。"""

    ids = pd.Series(list(grid_ids), dtype="string")
    ix = ids.str.slice(1, 5).astype(int).to_numpy()
    iy = ids.str.slice(5, 9).astype(int).to_numpy()
    return ix, iy
