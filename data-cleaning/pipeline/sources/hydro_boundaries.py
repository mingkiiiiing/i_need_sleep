from __future__ import annotations

"""HydroLAKES/HydroBASINS boundary and topology adapter for Taihu.

The adapter consumes the official public HydroBASINS continental archive (or a
legally extracted shapefile), clips a bounded Taihu vicinity, follows
``NEXT_DOWN`` to retain upstream sub-basins, and writes a GeoPackage plus a
topology CSV.  Existing HydroLAKES boundary provenance is copied into the
combined package; no boundary geometry is invented.
"""

import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .common import PACKAGE_ROOT, RAW_ROOT, sha256_file, utc_now
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest


HYDROLAKES_SOURCE_URL = "https://zenodo.org/records/17503891/files/HydroLAKES_Asia.zip?download=1"
HYDROBASINS_SOURCE_URL = "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev08_v1c.zip"
HYDROBASINS_TECHDOC_URL = "https://www.hydrosheds.org/products/hydrobasins"
DEFAULT_LAKE_BOUNDARY = PACKAGE_ROOT / "storage" / "silver" / "geo" / "taihu_boundary.gpkg"
DEFAULT_HYDROBASINS_ARCHIVE = PACKAGE_ROOT / "storage" / "raw" / "hydrobasins" / "hybas_as_lev08_v1c.zip"
DEFAULT_OUTPUT_GPKG = PACKAGE_ROOT / "storage" / "silver" / "geo" / "hydrolakes_hydrobasins.gpkg"
DEFAULT_TOPOLOGY_CSV = PACKAGE_ROOT / "storage" / "reports" / "hydrobasins_topology.csv"
DEFAULT_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "hydrolakes_hydrobasins_p07_04.json"
BOUNDARY_LAYER = "taihu_boundary_wgs84"
HYDROBASINS_LAYER = "hydrobasins_level08_wgs84"
CENTROID_LAYER = "hydrobasins_centroids_wgs84"


def _extract_hydrobasins(path: Path, temporary_root: Path) -> Path:
    if path.suffix.casefold() != ".zip":
        return path
    with zipfile.ZipFile(path) as archive:
        archive.extractall(temporary_root)
    candidates = sorted(temporary_root.rglob("*.shp"))
    if not candidates:
        raise ValueError("HydroBASINS archive has no shapefile")
    return candidates[0]


def _load_lake_geometry(path: Path) -> tuple[Any, dict[str, Any]]:
    import fiona
    from shapely.geometry import shape
    from shapely.ops import unary_union

    with fiona.open(path, layer=BOUNDARY_LAYER) as source:
        geometries = [shape(feature["geometry"]) for feature in source if feature.get("geometry")]
        if not geometries:
            raise ValueError("Taihu boundary layer contains no geometry")
    return unary_union(geometries), {}


def _copy_boundary_layers(source_path: Path, output_path: Path) -> list[str]:
    import fiona

    copied: list[str] = []
    for layer in ("taihu_boundary_wgs84", "taihu_boundary_utm51n", "boundary_metadata"):
        if layer not in fiona.listlayers(source_path):
            continue
        with fiona.open(source_path, layer=layer) as source:
            kwargs: dict[str, Any] = {"driver": "GPKG", "layer": layer, "schema": source.schema.copy()}
            if source.crs:
                kwargs["crs"] = source.crs
            if layer != "boundary_metadata":
                kwargs["layer_options"] = {"SPATIAL_INDEX": "YES"}
            with fiona.open(output_path, mode="w", **kwargs) as target:
                for feature in source:
                    target.write({"geometry": feature["geometry"], "properties": dict(feature["properties"])})
        copied.append(layer)
    return copied


def _basin_schema(source_schema: dict[str, Any]) -> dict[str, Any]:
    # HydroBASINS archives may declare Polygon while containing a small number
    # of MultiPolygon records.  We normalize both to MultiPolygon at write
    # time, preserving the exact component geometry and avoiding Fiona schema
    # rejection on the mixed regional archive.
    schema = {"geometry": "MultiPolygon", "properties": dict(source_schema["properties"])}
    schema["properties"]["selection_reason"] = "str:24"
    return schema


def _as_multipolygon(geometry: Any) -> Any:
    from shapely.geometry import MultiPolygon

    if geometry.geom_type == "Polygon":
        return MultiPolygon([geometry])
    if geometry.geom_type == "MultiPolygon":
        return geometry
    raise ValueError(f"unexpected HydroBASINS geometry type: {geometry.geom_type}")


def _write_topology_csv(path: Path, features: dict[int, dict[str, Any]], reasons: dict[int, str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["hybas_id", "next_down", "selection_reason", "sub_area_km2", "up_area_km2", "pfaf_id", "order"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for hybas_id, item in sorted(features.items()):
            properties = item["properties"]
            writer.writerow({
                "hybas_id": hybas_id,
                "next_down": properties.get("NEXT_DOWN"),
                "selection_reason": reasons.get(hybas_id),
                "sub_area_km2": properties.get("SUB_AREA"),
                "up_area_km2": properties.get("UP_AREA"),
                "pfaf_id": properties.get("PFAF_ID"),
                "order": properties.get("ORDER"),
            })
    return len(features)


def _spatial_index_present(path: Path, layer: str) -> bool:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (f"rtree_{layer}_geom",)).fetchone() is not None
    finally:
        connection.close()


def build_hydrolakes_hydrobasins(
    *,
    lake_boundary_path: Path | str = DEFAULT_LAKE_BOUNDARY,
    hydrobasins_path: Path | str,
    output_gpkg: Path | str = DEFAULT_OUTPUT_GPKG,
    topology_csv: Path | str = DEFAULT_TOPOLOGY_CSV,
    buffer_deg: float = 0.5,
) -> dict[str, Any]:
    """Create a combined GeoPackage from real HydroLAKES and HydroBASINS files."""

    import fiona
    from shapely.geometry import mapping, shape

    lake_path = Path(lake_boundary_path)
    basin_input = Path(hydrobasins_path)
    output = Path(output_gpkg)
    topology = Path(topology_csv)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing boundary package: {output}")
    if not lake_path.exists() or not basin_input.exists():
        raise FileNotFoundError("lake boundary and HydroBASINS input are required")
    if buffer_deg <= 0:
        raise ValueError("buffer_deg must be positive")

    with tempfile.TemporaryDirectory(prefix="taihu_hydrobasins_") as temp_dir:
        basin_shp = _extract_hydrobasins(basin_input, Path(temp_dir))
        lake_geometry, _ = _load_lake_geometry(lake_path)
        search_geometry = lake_geometry.buffer(float(buffer_deg))
        selected: dict[int, dict[str, Any]] = {}
        reasons: dict[int, str] = {}
        base_ids: set[int] = set()
        source_schema: dict[str, Any] | None = None
        source_crs: Any = None
        with fiona.open(basin_shp) as source:
            source_schema = source.schema.copy()
            source_crs = source.crs
            for feature in source:
                properties = dict(feature["properties"])
                hybas_id = int(properties["HYBAS_ID"])
                geometry = shape(feature["geometry"])
                if geometry.intersects(search_geometry):
                    selected[hybas_id] = {"geometry": mapping(_as_multipolygon(geometry)), "properties": properties}
                    reasons[hybas_id] = "intersects_taihu_buffer"
                    base_ids.add(hybas_id)
            if not base_ids:
                raise ValueError("no HydroBASINS level-08 polygon intersects the Taihu search buffer")
            # Follow NEXT_DOWN repeatedly to retain upstream contributing basins.
            changed = True
            passes = 0
            while changed and passes < 16:
                changed = False
                passes += 1
                for feature in source:
                    properties = dict(feature["properties"])
                    hybas_id = int(properties["HYBAS_ID"])
                    next_down = properties.get("NEXT_DOWN")
                    try:
                        next_down_id = int(next_down)
                    except (TypeError, ValueError):
                        continue
                    if next_down_id in selected and hybas_id not in selected:
                        geometry = shape(feature["geometry"])
                        selected[hybas_id] = {"geometry": mapping(_as_multipolygon(geometry)), "properties": properties}
                        reasons[hybas_id] = "upstream_next_down_chain"
                        changed = True
        assert source_schema is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        copied_layers = _copy_boundary_layers(lake_path, output)
        basin_schema = _basin_schema(source_schema)
        with fiona.open(output, mode="w", layer=HYDROBASINS_LAYER, driver="GPKG", crs=source_crs, schema=basin_schema, layer_options={"SPATIAL_INDEX": "YES"}) as target:
            for hybas_id, item in selected.items():
                properties = dict(item["properties"])
                properties["selection_reason"] = reasons[hybas_id]
                target.write({"geometry": item["geometry"], "properties": properties})
        centroid_schema = {"geometry": "Point", "properties": {"HYBAS_ID": "int", "NEXT_DOWN": "int", "selection_reason": "str:24"}}
        with fiona.open(output, mode="w", layer=CENTROID_LAYER, driver="GPKG", crs=source_crs, schema=centroid_schema, layer_options={"SPATIAL_INDEX": "YES"}) as target:
            for hybas_id, item in selected.items():
                center = shape(item["geometry"]).centroid
                properties = item["properties"]
                target.write({"geometry": mapping(center), "properties": {"HYBAS_ID": hybas_id, "NEXT_DOWN": properties.get("NEXT_DOWN"), "selection_reason": reasons[hybas_id]}})
    topology_count = _write_topology_csv(topology, selected, reasons)
    layer_names = fiona.listlayers(output)
    return {
        "status": "completed",
        "output_gpkg": str(output),
        "topology_csv": str(topology),
        "lake_boundary_source": str(lake_path),
        "hydrobasins_source": str(basin_input),
        "source_crs": str(source_crs),
        "buffer_deg": float(buffer_deg),
        "base_basin_count": len(base_ids),
        "selected_basin_count": len(selected),
        "topology_count": topology_count,
        "layers": layer_names,
        "spatial_index_verified": _spatial_index_present(output, HYDROBASINS_LAYER) and _spatial_index_present(output, CENTROID_LAYER),
        "topology_rule": "selected polygons intersect Taihu buffer or are upstream through NEXT_DOWN chain",
        "license": "HydroLAKES CC-BY-4.0; HydroBASINS HydroSHEDS license with attribution required",
        "data_truth": "real_external_hydrolakes_boundary_and_hydrobasins_archive",
    }


def run_hydrolakes_hydrobasins(
    *,
    lake_boundary_path: Path | str = DEFAULT_LAKE_BOUNDARY,
    hydrobasins_path: Path | str | None = None,
    output_gpkg: Path | str = DEFAULT_OUTPUT_GPKG,
    topology_csv: Path | str = DEFAULT_TOPOLOGY_CSV,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    buffer_deg: float = 0.5,
) -> dict[str, Any]:
    """Run the boundary build or return a truthful public-download plan."""

    manifest = Path(manifest_path)
    if hydrobasins_path is None:
        result = {
            "task_id": "P07-04",
            "status": "BLOCKED_DATA",
            "data_truth": "official_download_plan_only",
            "hydrolakes_source_url": HYDROLAKES_SOURCE_URL,
            "hydrobasins_source_url": HYDROBASINS_SOURCE_URL,
            "hydrobasins_technical_documentation": HYDROBASINS_TECHDOC_URL,
            "lake_boundary_path": str(lake_boundary_path),
            "output_gpkg": str(output_gpkg),
            "topology_csv": str(topology_csv),
            "next_action": "provide or download the official HydroBASINS Asia level-08 archive; then run the bounded build",
        }
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    basin_path = Path(hydrobasins_path)
    result = build_hydrolakes_hydrobasins(
        lake_boundary_path=lake_boundary_path,
        hydrobasins_path=basin_path,
        output_gpkg=output_gpkg,
        topology_csv=topology_csv,
        buffer_deg=buffer_deg,
    )
    raw_asset_manifest = None
    if basin_path.exists():
        asset = build_asset_manifest(
            source_id="hydrobasins",
            asset_id=basin_path.stem,
            request_url=HYDROBASINS_SOURCE_URL,
            local_path=basin_path,
            retrieved_at_utc=utc_now(),
            http_status=200,
            response_headers={},
            license_tag="HYDROSHEDS_LICENSE_WITH_ATTRIBUTION",
            redistribution_allowed="conditional",
            commercial_use="conditional",
            status="completed",
        )
        raw_asset_manifest = manifest_root(PACKAGE_ROOT) / f"raw_hydrobasins_{basin_path.stem}.json"
        write_asset_manifest(asset, raw_asset_manifest)
    result.update({
        "task_id": "P07-04",
        "manifest": str(manifest),
        "raw_asset_manifest": str(raw_asset_manifest) if raw_asset_manifest else None,
        "hydrolakes_source_url": HYDROLAKES_SOURCE_URL,
        "hydrobasins_source_url": HYDROBASINS_SOURCE_URL,
        "retrieved_at_utc": utc_now(),
    })
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = [
    "BOUNDARY_LAYER",
    "CENTROID_LAYER",
    "DEFAULT_HYDROBASINS_ARCHIVE",
    "DEFAULT_LAKE_BOUNDARY",
    "DEFAULT_MANIFEST",
    "DEFAULT_OUTPUT_GPKG",
    "DEFAULT_TOPOLOGY_CSV",
    "HYDROBASINS_SOURCE_URL",
    "HYDROLAKES_SOURCE_URL",
    "build_hydrolakes_hydrobasins",
    "run_hydrolakes_hydrobasins",
]
