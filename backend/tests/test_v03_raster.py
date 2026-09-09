"""V0.3 连续栅格空间场：月度 PNG、固定色标、20 μg/L 边界 GeoJSON。"""
from __future__ import annotations

import json

from backend.app.rs_raster import RasterFieldService

BLOOM_THRESHOLD_UG_L = 20.0


def _raster_service() -> RasterFieldService:
    service = RasterFieldService()
    assert service.manifest_path.is_file(), "raster_manifest.json 缺失：请先运行 build_raster_field.py"
    return service


def test_raster_manifest_has_monthly_layers_with_fixed_color_scale():
    service = _raster_service()
    layers = service.list_layers()
    assert len(layers) >= 27
    months = [layer["month"] for layer in layers]
    assert len(months) == len(set(months)), "月份图层不得重复"


def test_raster_layer_payload_complete_for_frontend():
    service = _raster_service()
    layer = service.get_raster_layer()
    assert layer["metric"] == "chla"
    assert layer["unit"] == "μg/L"
    assert layer["vmin"] == 0.0 and layer["vmax"] == 60.0
    assert layer["png_url"].startswith("/rs/monthly_v3/")
    assert layer["boundary_geojson_url"].startswith("/rs/monthly_v3/")
    assert layer["boundary"]["threshold_ug_l"] == BLOOM_THRESHOLD_UG_L
    assert layer["spatial_method"] == "calibrated_annual_product_plus_station_residual"
    # 太湖大致范围（纬度 30.8-31.6，经度 119.8-120.4）
    (lat_min, lon_min), (lat_max, lon_max) = layer["bounds"]
    assert 30.5 < lat_min < lat_max < 32.0
    assert 119.5 < lon_min < lon_max < 120.7


def test_boundary_geojson_files_exist_on_disk():
    service = _raster_service()
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    for layer in manifest.get("layers", []):
        png = service.overlays_dir / layer["png"]
        boundary = service.overlays_dir / layer["boundary_geojson"]
        assert png.is_file(), f"缺栅格 PNG: {png}"
        assert boundary.is_file(), f"缺边界 GeoJSON: {boundary}"


def test_boundary_geojson_is_valid_feature_collection():
    service = _raster_service()
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    latest = manifest["layers"][-1]
    geojson = service.get_boundary_geojson(latest["month"])
    assert geojson.get("type") == "FeatureCollection"
    assert isinstance(geojson.get("features"), list)
