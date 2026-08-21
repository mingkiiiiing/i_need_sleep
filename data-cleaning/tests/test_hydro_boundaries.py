from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import mapping, box

from pipeline.sources.hydro_boundaries import (
    BOUNDARY_LAYER,
    CENTROID_LAYER,
    HYDROBASINS_LAYER,
    build_hydrolakes_hydrobasins,
    run_hydrolakes_hydrobasins,
)


def _write_fixture_layers(root: Path) -> tuple[Path, Path]:
    lake = root / "lake.gpkg"
    lake_schema = {"geometry": "Polygon", "properties": {"hylak_id": "int", "lake_name": "str:20", "source_dataset": "str:30", "license": "str:20"}}
    with fiona.open(lake, "w", driver="GPKG", layer=BOUNDARY_LAYER, crs="EPSG:4326", schema=lake_schema) as sink:
        sink.write({"geometry": mapping(box(0, 0, 1, 1)), "properties": {"hylak_id": 148, "lake_name": "Tai", "source_dataset": "HydroLAKES", "license": "CC-BY-4.0"}})
    basin = root / "basins.shp"
    basin_schema = {"geometry": "Polygon", "properties": {"HYBAS_ID": "int", "NEXT_DOWN": "int", "SUB_AREA": "float", "UP_AREA": "float", "PFAF_ID": "int", "ORDER": "int"}}
    with fiona.open(basin, "w", driver="ESRI Shapefile", crs="EPSG:4326", schema=basin_schema) as sink:
        sink.write({"geometry": mapping(box(-0.2, -0.2, 1.2, 1.2)), "properties": {"HYBAS_ID": 100, "NEXT_DOWN": 0, "SUB_AREA": 100.0, "UP_AREA": 100.0, "PFAF_ID": 1, "ORDER": 1}})
        sink.write({"geometry": mapping(box(2, 2, 3, 3)), "properties": {"HYBAS_ID": 101, "NEXT_DOWN": 100, "SUB_AREA": 50.0, "UP_AREA": 50.0, "PFAF_ID": 2, "ORDER": 1}})
    return lake, basin


def test_missing_hydrobasins_returns_official_download_plan(tmp_path):
    result = run_hydrolakes_hydrobasins(manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_DATA"
    assert "hydrobasins_source_url" in result
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["status"] == "BLOCKED_DATA"


def test_build_selects_lake_intersection_and_upstream_chain_with_spatial_indexes(tmp_path):
    lake, basin = _write_fixture_layers(tmp_path)
    output = tmp_path / "hydrolakes_hydrobasins.gpkg"
    topology = tmp_path / "topology.csv"
    result = build_hydrolakes_hydrobasins(
        lake_boundary_path=lake,
        hydrobasins_path=basin,
        output_gpkg=output,
        topology_csv=topology,
        buffer_deg=0.1,
    )
    assert result["status"] == "completed"
    assert result["base_basin_count"] == 1
    assert result["selected_basin_count"] == 2
    assert result["topology_count"] == 2
    assert result["spatial_index_verified"] is True
    assert {BOUNDARY_LAYER, HYDROBASINS_LAYER, CENTROID_LAYER}.issubset(set(fiona.listlayers(output)))
    text = topology.read_text(encoding="utf-8-sig")
    assert "upstream_next_down_chain" in text
    with fiona.open(output, layer=HYDROBASINS_LAYER) as layer:
        reasons = {feature["properties"]["selection_reason"] for feature in layer}
    assert reasons == {"intersects_taihu_buffer", "upstream_next_down_chain"}


def test_existing_output_is_not_overwritten(tmp_path):
    lake, basin = _write_fixture_layers(tmp_path)
    output = tmp_path / "existing.gpkg"
    output.write_bytes(b"existing")
    try:
        build_hydrolakes_hydrobasins(lake_boundary_path=lake, hydrobasins_path=basin, output_gpkg=output, topology_csv=tmp_path / "topology.csv")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing boundary package must not be overwritten")
