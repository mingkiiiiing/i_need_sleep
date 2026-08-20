from __future__ import annotations

import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fiona
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ZIP = ROOT / "storage" / "raw" / "geo" / "hydrolakes" / "HydroLAKES_Asia.zip"
SOURCE_DIR = ROOT / "storage" / "raw" / "geo" / "hydrolakes" / "asia"
SOURCE_SHP = SOURCE_DIR / "HydroLAKES_Asia.shp"
OUTPUT_GPKG = ROOT / "storage" / "silver" / "geo" / "taihu_boundary.gpkg"
OUTPUT_MANIFEST = ROOT / "storage" / "silver" / "geo" / "taihu_boundary_manifest.json"
HYLAK_ID = 148
SOURCE_URL = "https://zenodo.org/records/17503891/files/HydroLAKES_Asia.zip?download=1"
SOURCE_RECORD = "https://zenodo.org/records/17503891"
SOURCE_DOI = "10.5281/zenodo.17503891"
SOURCE_VERSION = "HydroLAKES v1.0 Asia subset; Zenodo v1 (2025-11-01)"
LICENSE = "CC-BY-4.0"


def ensure_source() -> None:
    if SOURCE_SHP.exists():
        return
    if not SOURCE_ZIP.exists():
        raise FileNotFoundError(f"missing source archive: {SOURCE_ZIP}")
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE_ZIP) as archive:
        archive.extractall(SOURCE_DIR)


def load_taihu() -> tuple[dict[str, Any], Any]:
    with fiona.open(SOURCE_SHP) as collection:
        if collection.crs.get("init") not in ("epsg:4326", "EPSG:4326") and collection.crs_wkt:
            # The distributed .prj is WGS84; the explicit check below keeps the
            # generated exchange layer from silently changing source CRS.
            crs_text = collection.crs_wkt.upper()
            if "WGS 84" not in crs_text and "WGS_1984" not in crs_text:
                raise ValueError(f"unexpected source CRS: {collection.crs}")
        for feature in collection:
            if int(feature["properties"]["Hylak_id"]) == HYLAK_ID:
                return dict(feature["properties"]), shape(feature["geometry"])
    raise LookupError(f"HydroLAKES feature Hylak_id={HYLAK_ID} not found")


def write_layers(properties: dict[str, Any], geometry: Any) -> tuple[float, float]:
    OUTPUT_GPKG.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_GPKG.exists():
        OUTPUT_GPKG.unlink()
    projected_transformer = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
    projected = transform(projected_transformer.transform, geometry)
    area_km2 = float(projected.area / 1_000_000.0)
    source_area_km2 = float(properties["Lake_area"])
    base_properties = {
        "hylak_id": HYLAK_ID,
        "lake_name": str(properties.get("Lake_name") or "Tai"),
        "source_area_km2": source_area_km2,
        "area_km2_calc": round(area_km2, 6),
        "area_calc_crs": "EPSG:32651",
        "source_dataset": "HydroLAKES v1.0",
        "source_record": SOURCE_RECORD,
        "source_version": SOURCE_VERSION,
        "license": LICENSE,
        "boundary_role": "authoritative_public_reference_polygon",
    }
    schema = {
        "geometry": "Polygon",
        "properties": {
            "hylak_id": "int",
            "lake_name": "str:40",
            "source_area_km2": "float",
            "area_km2_calc": "float",
            "area_calc_crs": "str:16",
            "source_dataset": "str:40",
            "source_record": "str:120",
            "source_version": "str:100",
            "license": "str:20",
            "boundary_role": "str:50",
        },
    }
    with fiona.open(OUTPUT_GPKG, "w", driver="GPKG", layer="taihu_boundary_wgs84", crs="EPSG:4326", schema=schema) as sink:
        sink.write({"geometry": mapping(geometry), "properties": base_properties})
    with fiona.open(OUTPUT_GPKG, "w", driver="GPKG", layer="taihu_boundary_utm51n", crs="EPSG:32651", schema=schema) as sink:
        sink.write({"geometry": mapping(projected), "properties": base_properties})
    with sqlite3.connect(OUTPUT_GPKG) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS boundary_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        metadata = {
            "source_url": SOURCE_URL,
            "source_record": SOURCE_RECORD,
            "source_doi": SOURCE_DOI,
            "source_md5": "7601d5fad928195d6a91c616adb172ad",
            "source_feature_id": str(HYLAK_ID),
            "geometry_crs": "EPSG:4326",
            "area_calc_crs": "EPSG:32651",
            "source_area_km2": str(source_area_km2),
            "area_km2_calc": str(round(area_km2, 6)),
            "license": LICENSE,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        connection.executemany("INSERT OR REPLACE INTO boundary_metadata(key, value) VALUES (?, ?)", metadata.items())
        connection.commit()
    return source_area_km2, area_km2


def main() -> None:
    ensure_source()
    properties, geometry = load_taihu()
    source_area_km2, area_km2 = write_layers(properties, geometry)
    manifest = {
        "status": "completed",
        "source_feature_id": HYLAK_ID,
        "source_lake_name": properties.get("Lake_name") or "Tai",
        "source_area_km2": source_area_km2,
        "area_km2_calc": round(area_km2, 6),
        "geometry_crs": "EPSG:4326",
        "area_calc_crs": "EPSG:32651",
        "source_url": SOURCE_URL,
        "source_record": SOURCE_RECORD,
        "source_doi": SOURCE_DOI,
        "source_version": SOURCE_VERSION,
        "license": LICENSE,
        "output": str(OUTPUT_GPKG.relative_to(ROOT)).replace("\\", "/"),
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

