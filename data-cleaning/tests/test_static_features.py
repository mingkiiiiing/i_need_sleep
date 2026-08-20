from __future__ import annotations

import json
from pathlib import Path

import fiona
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, box, mapping

from pipeline.sources.hydro_boundaries import BOUNDARY_LAYER, HYDROBASINS_LAYER
from pipeline.sources.static_features import build_static_features, run_static_features


def _write_fixture_inputs(root: Path) -> tuple[Path, list[Path], list[Path]]:
    boundary = root / "boundaries.gpkg"
    lake_schema = {"geometry": "Polygon", "properties": {"hylak_id": "int"}}
    with fiona.open(boundary, "w", driver="GPKG", layer=BOUNDARY_LAYER, crs="EPSG:4326", schema=lake_schema) as sink:
        sink.write({"geometry": mapping(box(0.5, 0.5, 1.0, 1.0)), "properties": {"hylak_id": 148}})
    basin_schema = {"geometry": "MultiPolygon", "properties": {"HYBAS_ID": "int", "NEXT_DOWN": "int", "SUB_AREA": "float", "UP_AREA": "float", "PFAF_ID": "int"}}
    with fiona.open(boundary, "w", driver="GPKG", layer=HYDROBASINS_LAYER, crs="EPSG:4326", schema=basin_schema) as sink:
        sink.write({"geometry": mapping(MultiPolygon([box(0.4, 0.4, 1.4, 1.4)])), "properties": {"HYBAS_ID": 100, "NEXT_DOWN": 0, "SUB_AREA": 10.0, "UP_AREA": 10.0, "PFAF_ID": 1}})
    transform = from_origin(0.0, 2.0, 0.1, 0.1)
    dem = root / "dem.tif"
    dem_values = (100.0 + np.arange(400, dtype="float32").reshape(20, 20) * 0.1)
    with rasterio.open(dem, "w", driver="GTiff", height=20, width=20, count=1, dtype="float32", crs="EPSG:4326", transform=transform, nodata=-9999.0) as sink:
        sink.write(dem_values, 1)
    landcover = root / "worldcover.tif"
    landcover_values = np.where(np.indices((20, 20))[1] % 2 == 0, 10, 80).astype("uint8")
    with rasterio.open(landcover, "w", driver="GTiff", height=20, width=20, count=1, dtype="uint8", crs="EPSG:4326", transform=transform, nodata=0) as sink:
        sink.write(landcover_values, 1)
    return boundary, [dem], [landcover]


def test_missing_public_tiles_returns_download_plan(tmp_path):
    result = run_static_features(raw_root=tmp_path / "raw", manifest_path=tmp_path / "manifest.json", download=False)
    assert result["status"] == "BLOCKED_DATA"
    assert "dem_source_urls" in result
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["status"] == "BLOCKED_DATA"


def test_build_static_features_derives_dem_slope_and_landcover(tmp_path):
    boundary, dem, landcover = _write_fixture_inputs(tmp_path)
    result = build_static_features(
        boundary_package=boundary,
        dem_paths=dem,
        worldcover_paths=landcover,
        output_parquet=tmp_path / "static_features.parquet",
        output_dem=tmp_path / "dem_clip.tif",
        output_slope=tmp_path / "slope.tif",
        output_worldcover=tmp_path / "worldcover_clip.tif",
        manifest_path=tmp_path / "manifest.json",
        buffer_deg=0.2,
    )
    assert result["status"] == "completed"
    frame = pd.read_parquet(tmp_path / "static_features.parquet")
    assert len(frame) == 1
    assert frame.loc[0, "elevation_mean_m"] is not None
    assert frame.loc[0, "slope_mean_deg"] is not None
    assert frame.loc[0, "landcover_tree_pct"] > 0
    assert frame.loc[0, "landcover_permanent_water_pct"] > 0
    assert frame.loc[0, "data_truth"] if "data_truth" in frame.columns else True


def test_existing_static_feature_file_is_not_overwritten(tmp_path):
    boundary, dem, landcover = _write_fixture_inputs(tmp_path)
    output = tmp_path / "static_features.parquet"
    output.write_bytes(b"existing")
    try:
        build_static_features(boundary_package=boundary, dem_paths=dem, worldcover_paths=landcover, output_parquet=output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing static feature file must not be overwritten")
