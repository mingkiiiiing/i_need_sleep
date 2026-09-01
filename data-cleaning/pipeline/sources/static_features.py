from __future__ import annotations

"""Public DEM/land-cover ingestion and Taihu static-feature derivation.

The adapter uses the anonymous AWS Open Data objects published for Copernicus
DEM GLO-30 and ESA WorldCover 2021 v200.  It downloads only the tiles needed
for the Taihu study-area buffer, preserves raw assets and manifests, clips the
rasters, derives slope, and computes per-subbasin elevation/land-cover
statistics for the P07-04 boundary package.
"""

import json
from pathlib import Path
from typing import Any, Iterable

import fiona
import numpy as np
import pandas as pd
from rasterio.io import DatasetReader
from rasterio.mask import mask as raster_mask
from rasterio.merge import merge as raster_merge
from rasterio.transform import Affine
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from .common import PACKAGE_ROOT, download_asset, utc_now
from .hydro_boundaries import HYDROBASINS_LAYER


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
DEM_BUCKET_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
WORLDCOVER_BUCKET_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DEM_TILES = (
    "Copernicus_DSM_COG_10_N30_00_E119_00_DEM",
    "Copernicus_DSM_COG_10_N30_00_E120_00_DEM",
    "Copernicus_DSM_COG_10_N31_00_E119_00_DEM",
    "Copernicus_DSM_COG_10_N31_00_E120_00_DEM",
)
WORLDCOVER_TILES = (
    "ESA_WorldCover_10m_2021_v200_N30E117_Map.tif",
    "ESA_WorldCover_10m_2021_v200_N30E120_Map.tif",
)
DEM_LICENSE = "COPERNICUS_DEM_FREE_PUBLIC_LICENSE_WITH_ATTRIBUTION"
WORLDCOVER_LICENSE = "CC-BY-4.0"
DEFAULT_BOUNDARY_PACKAGE = STORAGE / "silver" / "geo" / "hydrolakes_hydrobasins.gpkg"
DEFAULT_RAW_ROOT = STORAGE / "raw" / "static_geo"
DEFAULT_OUTPUT_PARQUET = STORAGE / "silver" / "geo" / "static_features.parquet"
DEFAULT_OUTPUT_DEM = STORAGE / "silver" / "geo" / "copernicus_dem_glo30_taihu.tif"
DEFAULT_OUTPUT_SLOPE = STORAGE / "silver" / "geo" / "copernicus_dem_glo30_taihu_slope.tif"
DEFAULT_OUTPUT_WORLDCOVER = STORAGE / "silver" / "geo" / "worldcover_2021_taihu.tif"
DEFAULT_MANIFEST = STORAGE / "manifests" / "static_features_p07_05.json"
CLASS_NAMES = {
    10: "tree",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    70: "snow_ice",
    80: "permanent_water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}


def _dem_url(tile: str) -> str:
    return f"{DEM_BUCKET_BASE}/{tile}/{tile}.tif"


def _worldcover_url(tile: str) -> str:
    return f"{WORLDCOVER_BUCKET_BASE}/{tile}"


def download_static_assets(raw_root: Path | str = DEFAULT_RAW_ROOT) -> dict[str, Any]:
    """Download the official public tiles with resumable/idempotent manifests."""

    root = Path(raw_root)
    dem_root = root / "copernicus_dem_glo30"
    wc_root = root / "esa_worldcover_2021_v200"
    dem_results: list[dict[str, Any]] = []
    wc_results: list[dict[str, Any]] = []
    for tile in DEM_TILES:
        output = dem_root / f"{tile}.tif"
        dem_results.append(
            download_asset(
                source_id="copernicus_dem_glo30",
                asset_id=tile,
                url=_dem_url(tile),
                output_path=output,
                license_tag=DEM_LICENSE,
                redistribution_allowed="conditional",
                commercial_use="conditional",
                timeout=300,
                retries=2,
            )
        )
    for tile in WORLDCOVER_TILES:
        output = wc_root / tile
        wc_results.append(
            download_asset(
                source_id="esa_worldcover_2021_v200",
                asset_id=tile.removesuffix(".tif"),
                url=_worldcover_url(tile),
                output_path=output,
                license_tag=WORLDCOVER_LICENSE,
                redistribution_allowed="yes",
                commercial_use="yes",
                timeout=600,
                retries=2,
            )
        )
    return {"dem": dem_results, "worldcover": wc_results}


def _load_study_geometry(boundary_package: Path, buffer_deg: float) -> tuple[Any, Any, list[dict[str, Any]]]:
    if not boundary_package.exists():
        raise FileNotFoundError(f"boundary package not found: {boundary_package}")
    with fiona.open(boundary_package, layer="taihu_boundary_wgs84") as lake_source:
        lake_geometries = [shape(item["geometry"]) for item in lake_source if item.get("geometry")]
    if not lake_geometries:
        raise ValueError("Taihu boundary has no geometry")
    lake_geometry = unary_union(lake_geometries)
    study_geometry = lake_geometry.buffer(float(buffer_deg))
    selected: list[dict[str, Any]] = []
    with fiona.open(boundary_package, layer=HYDROBASINS_LAYER) as basin_source:
        for feature in basin_source:
            if not feature.get("geometry"):
                continue
            geometry = shape(feature["geometry"])
            if geometry.intersects(study_geometry):
                selected.append({"geometry": geometry, "properties": dict(feature["properties"])})
    if not selected:
        raise ValueError("no HydroBASINS polygons intersect the Taihu study buffer")
    return lake_geometry, study_geometry, selected


def _mosaic(paths: Iterable[Path], bounds: tuple[float, float, float, float]) -> tuple[np.ndarray, Affine, dict[str, Any]]:
    datasets: list[DatasetReader] = []
    try:
        for path in paths:
            dataset = fiona_env_raster_open(path)
            datasets.append(dataset)
        first = datasets[0]
        nodata = first.nodata if first.nodata is not None else 0
        array, transform = raster_merge(datasets, bounds=bounds, nodata=nodata)
        profile = first.profile.copy()
        profile.update({"height": array.shape[1], "width": array.shape[2], "transform": transform, "count": 1, "nodata": nodata})
        return array[0], transform, profile
    finally:
        for dataset in datasets:
            dataset.close()


def fiona_env_raster_open(path: Path) -> DatasetReader:
    # Kept as a tiny indirection to make raster opening easy to replace in
    # tests without coupling the adapter to an application-wide environment.
    import rasterio

    return rasterio.open(path)


def _write_raster(path: Path, array: np.ndarray, transform: Affine, profile: dict[str, Any], *, nodata: float | int) -> None:
    import rasterio

    path.parent.mkdir(parents=True, exist_ok=True)
    output_profile = dict(profile)
    output_profile.update(
        driver="GTiff",
        count=1,
        height=int(array.shape[0]),
        width=int(array.shape[1]),
        transform=transform,
        crs="EPSG:4326",
        nodata=nodata,
        compress="deflate",
    )
    with rasterio.open(path, "w", **output_profile) as sink:
        sink.write(array, 1)


def _derive_slope(dem: np.ndarray, transform: Affine, nodata: float | int) -> np.ndarray:
    values = dem.astype("float64", copy=True)
    invalid = ~np.isfinite(values) | (values == nodata)
    values[invalid] = np.nan
    mean_lat = float(transform.f + transform.e * values.shape[0] / 2.0)
    dy_m = abs(float(transform.e)) * 111_320.0
    dx_m = abs(float(transform.a)) * 111_320.0 * max(np.cos(np.deg2rad(mean_lat)), 0.1)
    gradient_y, gradient_x = np.gradient(values, dy_m, dx_m)
    slope = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y))).astype("float32")
    slope[invalid] = np.nan
    return slope


def _zonal_stats(dem_dataset: DatasetReader, slope_dataset: DatasetReader, landcover_dataset: DatasetReader, geometry: Any) -> dict[str, Any]:
    geom = [mapping(geometry)]
    dem, _ = raster_mask(dem_dataset, geom, crop=True, filled=False)
    slope, _ = raster_mask(slope_dataset, geom, crop=True, filled=False)
    landcover, _ = raster_mask(landcover_dataset, geom, crop=True, filled=False)
    dem_values = dem[0].compressed().astype("float64")
    dem_values = dem_values[np.isfinite(dem_values)]
    slope_values = slope[0].compressed().astype("float64")
    slope_values = slope_values[np.isfinite(slope_values)]
    lc_values = landcover[0].compressed().astype("int16")
    result: dict[str, Any] = {
        "dem_valid_fraction": float(dem_values.size / dem[0].size) if dem[0].size else 0.0,
        "landcover_valid_fraction": float(lc_values.size / landcover[0].size) if landcover[0].size else 0.0,
        "dem_quality_flag": "ok" if dem_values.size else "no_valid_pixels",
        "landcover_quality_flag": "ok" if lc_values.size else "no_valid_pixels",
        "elevation_mean_m": float(np.mean(dem_values)) if dem_values.size else None,
        "elevation_min_m": float(np.min(dem_values)) if dem_values.size else None,
        "elevation_max_m": float(np.max(dem_values)) if dem_values.size else None,
        "elevation_std_m": float(np.std(dem_values)) if dem_values.size else None,
        "slope_mean_deg": float(np.mean(slope_values)) if slope_values.size else None,
        "slope_max_deg": float(np.max(slope_values)) if slope_values.size else None,
    }
    for code, name in CLASS_NAMES.items():
        result[f"landcover_{name}_pct"] = float(np.count_nonzero(lc_values == code) / lc_values.size * 100.0) if lc_values.size else None
    return result


def build_static_features(
    *,
    boundary_package: Path | str = DEFAULT_BOUNDARY_PACKAGE,
    dem_paths: Iterable[Path | str],
    worldcover_paths: Iterable[Path | str],
    output_parquet: Path | str = DEFAULT_OUTPUT_PARQUET,
    output_dem: Path | str = DEFAULT_OUTPUT_DEM,
    output_slope: Path | str = DEFAULT_OUTPUT_SLOPE,
    output_worldcover: Path | str = DEFAULT_OUTPUT_WORLDCOVER,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    buffer_deg: float = 0.5,
) -> dict[str, Any]:
    """Clip public rasters and write per-basin static features."""

    boundary = Path(boundary_package)
    dem_inputs = [Path(item) for item in dem_paths]
    worldcover_inputs = [Path(item) for item in worldcover_paths]
    parquet_path = Path(output_parquet)
    dem_output = Path(output_dem)
    slope_output = Path(output_slope)
    landcover_output = Path(output_worldcover)
    manifest = Path(manifest_path)
    if parquet_path.exists():
        raise FileExistsError(f"refusing to overwrite existing static feature file: {parquet_path}")
    if not dem_inputs or not worldcover_inputs or any(not path.exists() for path in [*dem_inputs, *worldcover_inputs]):
        raise FileNotFoundError("DEM and WorldCover input tiles are required")
    lake_geometry, study_geometry, basins = _load_study_geometry(boundary, buffer_deg)
    bounds = tuple(float(value) for value in study_geometry.bounds)
    dem_array, dem_transform, dem_profile = _mosaic(dem_inputs, bounds)
    wc_array, wc_transform, wc_profile = _mosaic(worldcover_inputs, bounds)
    dem_nodata = dem_profile.get("nodata", -9999)
    wc_nodata = wc_profile.get("nodata", 0)
    slope_array = _derive_slope(dem_array, dem_transform, dem_nodata)
    _write_raster(dem_output, dem_array, dem_transform, dem_profile, nodata=dem_nodata)
    _write_raster(slope_output, slope_array, dem_transform, {**dem_profile, "dtype": "float32"}, nodata=np.nan)
    _write_raster(landcover_output, wc_array, wc_transform, wc_profile, nodata=wc_nodata)

    import rasterio

    rows: list[dict[str, Any]] = []
    with rasterio.open(dem_output) as dem_dataset, rasterio.open(slope_output) as slope_dataset, rasterio.open(landcover_output) as landcover_dataset:
        for item in basins:
            properties = item["properties"]
            geometry = item["geometry"]
            row: dict[str, Any] = {
                "hybas_id": int(properties["HYBAS_ID"]),
                "next_down": int(properties["NEXT_DOWN"]) if properties.get("NEXT_DOWN") is not None else None,
                "sub_area_km2": float(properties["SUB_AREA"]) if properties.get("SUB_AREA") is not None else None,
                "up_area_km2": float(properties["UP_AREA"]) if properties.get("UP_AREA") is not None else None,
                "pfaf_id": int(properties["PFAF_ID"]) if properties.get("PFAF_ID") is not None else None,
                "study_scope": "taihu_0.5deg_buffer_intersecting_basins",
                "distance_to_taihu_boundary_km": float(geometry.centroid.distance(lake_geometry) * 111.32),
                "source_dem": "Copernicus DEM GLO-30 Public 2021",
                "source_landcover": "ESA WorldCover 2021 v200",
                "license_dem": DEM_LICENSE,
                "license_landcover": WORLDCOVER_LICENSE,
            }
            row.update(_zonal_stats(dem_dataset, slope_dataset, landcover_dataset, geometry))
            rows.append(row)
    frame = pd.DataFrame(rows).sort_values("hybas_id").reset_index(drop=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    result = {
        "status": "completed",
        "output_parquet": str(parquet_path),
        "output_dem": str(dem_output),
        "output_slope": str(slope_output),
        "output_worldcover": str(landcover_output),
        "boundary_package": str(boundary),
        "feature_count": int(len(frame)),
        "dem_shape": [int(dem_array.shape[0]), int(dem_array.shape[1])],
        "worldcover_shape": [int(wc_array.shape[0]), int(wc_array.shape[1])],
        "crop_bounds_wgs84": list(bounds),
        "buffer_deg": float(buffer_deg),
        "class_map": CLASS_NAMES,
        "sources": {
            "dem": {"dataset": "Copernicus DEM GLO-30 Public", "urls": [_dem_url(tile) for tile in DEM_TILES], "license": DEM_LICENSE},
            "landcover": {"dataset": "ESA WorldCover 2021 v200", "urls": [_worldcover_url(tile) for tile in WORLDCOVER_TILES], "license": WORLDCOVER_LICENSE},
        },
        "data_truth": "real_external_copernicus_dem_and_esa_worldcover",
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def run_static_features(
    *,
    boundary_package: Path | str = DEFAULT_BOUNDARY_PACKAGE,
    raw_root: Path | str = DEFAULT_RAW_ROOT,
    output_parquet: Path | str = DEFAULT_OUTPUT_PARQUET,
    output_dem: Path | str = DEFAULT_OUTPUT_DEM,
    output_slope: Path | str = DEFAULT_OUTPUT_SLOPE,
    output_worldcover: Path | str = DEFAULT_OUTPUT_WORLDCOVER,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    buffer_deg: float = 0.5,
    download: bool = True,
) -> dict[str, Any]:
    """Download or report the official plan, then build static features."""

    root = Path(raw_root)
    if download:
        assets = download_static_assets(root)
    else:
        assets = None
    dem_paths = [root / "copernicus_dem_glo30" / f"{tile}.tif" for tile in DEM_TILES]
    worldcover_paths = [root / "esa_worldcover_2021_v200" / tile for tile in WORLDCOVER_TILES]
    if any(not path.exists() for path in [*dem_paths, *worldcover_paths]):
        result = {
            "task_id": "P07-05",
            "status": "BLOCKED_DATA",
            "data_truth": "official_download_plan_only",
            "boundary_package": str(boundary_package),
            "dem_source_urls": [_dem_url(tile) for tile in DEM_TILES],
            "worldcover_source_urls": [_worldcover_url(tile) for tile in WORLDCOVER_TILES],
            "next_action": "download the official public DEM and WorldCover tiles, then rerun static feature build",
        }
        path = Path(manifest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    result = build_static_features(
        boundary_package=boundary_package,
        dem_paths=dem_paths,
        worldcover_paths=worldcover_paths,
        output_parquet=output_parquet,
        output_dem=output_dem,
        output_slope=output_slope,
        output_worldcover=output_worldcover,
        manifest_path=manifest_path,
        buffer_deg=buffer_deg,
    )
    result.update({"task_id": "P07-05", "download_assets": assets, "retrieved_at_utc": utc_now()})
    Path(manifest_path).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


__all__ = [
    "CLASS_NAMES",
    "DEFAULT_BOUNDARY_PACKAGE",
    "DEFAULT_MANIFEST",
    "DEFAULT_OUTPUT_DEM",
    "DEFAULT_OUTPUT_PARQUET",
    "DEFAULT_OUTPUT_SLOPE",
    "DEFAULT_OUTPUT_WORLDCOVER",
    "DEFAULT_RAW_ROOT",
    "DEM_TILES",
    "WORLDCOVER_TILES",
    "build_static_features",
    "download_static_assets",
    "run_static_features",
]
