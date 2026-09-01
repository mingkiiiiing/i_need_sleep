from __future__ import annotations

import sqlite3
from pathlib import Path

import fiona
import yaml


ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
CONFIG_PATH = ROOT / "config" / "study_area.yml"
BOUNDARY_PATH = STORAGE / "silver" / "geo" / "taihu_boundary.gpkg"


def _load_config() -> dict[str, object]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_taihu_catalog_bbox_and_boundary_provenance_are_frozen() -> None:
    config = _load_config()
    boundary = config["boundary"]
    assert config["catalog_bbox_wgs84"] == [119.90, 30.90, 120.75, 31.65]
    assert config["bbox_role"] == "catalog_search_only"
    assert boundary["source_dataset"] == "HydroLAKES v1.0"
    assert boundary["source_feature_id"] == 148
    assert boundary["license"] == "CC-BY-4.0"
    assert boundary["geometry_crs"] == "EPSG:4326"
    assert boundary["area_calculation_crs"] == "EPSG:32651"
    assert BOUNDARY_PATH.exists()


def test_taihu_boundary_geopackage_has_exchange_and_projected_layers() -> None:
    layer_names = set(fiona.listlayers(BOUNDARY_PATH))
    assert {"taihu_boundary_wgs84", "taihu_boundary_utm51n"}.issubset(layer_names)

    with fiona.open(BOUNDARY_PATH, layer="taihu_boundary_wgs84") as layer:
        assert layer.crs.to_epsg() == 4326
        assert len(layer) == 1
        feature = next(iter(layer))
        assert feature["properties"]["hylak_id"] == 148
        assert feature["properties"]["boundary_role"] == "authoritative_public_reference_polygon"

    with fiona.open(BOUNDARY_PATH, layer="taihu_boundary_utm51n") as layer:
        assert layer.crs.to_epsg() == 32651
        assert len(layer) == 1
        projected = next(iter(layer))
        assert projected["properties"]["area_km2_calc"] > 0

    with sqlite3.connect(BOUNDARY_PATH) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM boundary_metadata"))
    assert metadata["source_feature_id"] == "148"
    assert metadata["source_md5"] == "7601d5fad928195d6a91c616adb172ad"
    assert metadata["area_calc_crs"] == "EPSG:32651"
