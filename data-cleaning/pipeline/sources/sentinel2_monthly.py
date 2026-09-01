from __future__ import annotations

"""Build a reproducible monthly Sentinel-2 L2A Taihu data cube.

The module reads public cloud-optimized GeoTIFF windows from Earth Search and
writes one fixed 20 m, lake-masked GeoTIFF per band and month.  It deliberately
keeps catalogue metadata and per-output checksums so the derived cube can be
audited without treating a tile-level cloud percentage as lake-local quality.
"""

import csv
import hashlib
import json
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests

from .earth_search_sentinel2 import API, COLLECTION, COLLECTION_FALLBACKS, TAIHU_BBOX

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
DEFAULT_OUTPUT = STORAGE / "rasters" / "sentinel2_monthly_20m"
DEFAULT_MANIFEST = STORAGE / "manifests" / "sentinel2_monthly_2022_2026.json"
DEFAULT_BOUNDARY = STORAGE / "silver" / "geo" / "taihu_boundary.gpkg"
TARGET_CRS = "EPSG:32651"
TARGET_RESOLUTION = 20.0
TARGET_ASSETS = ("green", "red", "rededge1", "nir", "swir16", "scl")
ASSET_BAND_NAMES = {
    "green": "B03",
    "red": "B04",
    "rededge1": "B05",
    "nir": "B08",
    "swir16": "B11",
    "scl": "SCL",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _month_ranges(start: date, end: date) -> Iterable[tuple[str, date, date]]:
    cursor = start.replace(day=1)
    while cursor <= end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = min(end, next_month - timedelta(days=1))
        yield cursor.strftime("%Y-%m"), max(cursor, start), month_end
        cursor = next_month


def _tile(feature: dict[str, Any]) -> str:
    props = feature.get("properties") or {}
    code = props.get("grid:code") or props.get("s2:mgrs_tile") or props.get("mgrs:tile")
    if code:
        return str(code).replace("MGRS-", "")
    parts = str(feature.get("id") or "").split("_")
    return parts[1].removeprefix("T") if len(parts) > 1 else "unknown"


def _cloud(feature: dict[str, Any]) -> float:
    value = (feature.get("properties") or {}).get("eo:cloud_cover")
    return float(value) if value is not None else 100.0


def search_month(start: date, end: date, max_cloud: float, *, timeout: int = 90) -> list[dict[str, Any]]:
    for collection in COLLECTION_FALLBACKS:
        payload = {
            "collections": [collection],
            "bbox": list(TAIHU_BBOX),
            "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
            "limit": 1000,
            "query": {"eo:cloud_cover": {"lt": max_cloud}},
        }
        response = None
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = requests.post(API, json=payload, timeout=timeout)
                response.raise_for_status()
                last_error = None
                break
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_error = exc
                time.sleep(2**attempt)
        if last_error is not None or response is None:
            raise last_error or RuntimeError("Earth Search request failed")
        features = response.json().get("features") or []
        if features:
            for feature in features:
                feature["_source_collection"] = collection
            return features
    return []


def select_best_day(features: list[dict[str, Any]], assets: tuple[str, ...] = TARGET_ASSETS) -> list[dict[str, Any]]:
    """Prefer maximum same-day tile coverage, then lowest mean cloud."""

    by_day: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for feature in features:
        feature_assets = feature.get("assets") or {}
        if not all(feature_assets.get(name, {}).get("href") for name in assets):
            continue
        observed = str((feature.get("properties") or {}).get("datetime") or "")[:10]
        tile = _tile(feature)
        current = by_day[observed].get(tile)
        if current is None or _cloud(feature) < _cloud(current):
            by_day[observed][tile] = feature
    if not by_day:
        return []
    _, selected = min(
        by_day.items(),
        key=lambda item: (
            -len(item[1]),
            sum(_cloud(scene) for scene in item[1].values()) / len(item[1]),
            item[0],
        ),
    )
    return sorted(selected.values(), key=lambda feature: (_cloud(feature), _tile(feature)))


def build_monthly_plan(start: date, end: date) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for month, month_start, month_end in _month_ranges(start, end):
        selected: list[dict[str, Any]] = []
        threshold = 30.0
        candidates: list[dict[str, Any]] = []
        for threshold in (30.0, 60.0, 101.0):
            candidates = search_month(month_start, month_end, threshold)
            selected = select_best_day(candidates)
            if selected:
                break
        plan.append(
            {
                "month": month,
                "range": [month_start.isoformat(), month_end.isoformat()],
                "cloud_threshold": threshold,
                "candidate_scenes": len(candidates),
                "selected_date": str((selected[0].get("properties") or {}).get("datetime") or "")[:10] if selected else None,
                "selected": selected,
            }
        )
    return plan


def _target_grid(boundary_path: Path, resolution: float = TARGET_RESOLUTION):
    import fiona
    from pyproj import Transformer
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from shapely.geometry import shape
    from shapely.ops import transform as shapely_transform, unary_union

    with fiona.open(boundary_path, layer="taihu_boundary_wgs84") as layer:
        geometries = [shape(feature["geometry"]) for feature in layer]
    geometry = unary_union(geometries)
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    projected = shapely_transform(transformer.transform, geometry)
    left, bottom, right, top = projected.bounds
    left = math.floor(left / resolution) * resolution
    bottom = math.floor(bottom / resolution) * resolution
    right = math.ceil(right / resolution) * resolution
    top = math.ceil(top / resolution) * resolution
    width = int(round((right - left) / resolution))
    height = int(round((top - bottom) / resolution))
    affine = from_origin(left, top, resolution, resolution)
    mask = rasterize([(projected.__geo_interface__, 1)], out_shape=(height, width), transform=affine, fill=0, dtype="uint8").astype(bool)
    return affine, width, height, mask, (left, bottom, right, top)


def _valid_existing(path: Path, width: int, height: int) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        import rasterio

        with rasterio.open(path) as dataset:
            return dataset.width == width and dataset.height == height and dataset.count == 1
    except Exception:
        return False


def _render_asset(
    scenes: list[dict[str, Any]], asset: str, output: Path, affine: Any, width: int, height: int, lake_mask: np.ndarray
) -> dict[str, Any]:
    import rasterio
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, reproject, transform_bounds
    from rasterio.windows import Window, from_bounds

    dtype = "uint8" if asset == "scl" else "uint16"
    destination = np.zeros((height, width), dtype=dtype)
    errors: list[str] = []
    for scene in scenes:
        href = scene["assets"][asset]["href"]
        temporary = np.zeros_like(destination)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                    with rasterio.open(href) as source:
                        target_bounds = array_bounds(height, width, affine)
                        source_bounds = transform_bounds(TARGET_CRS, source.crs, *target_bounds, densify_pts=21)
                        window = from_bounds(*source_bounds, transform=source.transform).round_offsets().round_lengths()
                        window = window.intersection(Window(0, 0, source.width, source.height))
                        source_values = source.read(1, window=window)
                        reproject(
                            source=source_values,
                            destination=temporary,
                            src_transform=source.window_transform(window),
                            src_crs=source.crs,
                            src_nodata=source.nodata or 0,
                            dst_transform=affine,
                            dst_crs=TARGET_CRS,
                            dst_nodata=0,
                            resampling=Resampling.nearest if asset == "scl" else Resampling.bilinear,
                        )
                last_error = None
                break
            except Exception as exc:  # remote COG reads can fail transiently
                last_error = exc
                time.sleep(2**attempt)
        if last_error is not None:
            errors.append(f"{scene.get('id')}: {type(last_error).__name__}: {last_error}")
            continue
        fill = (destination == 0) & (temporary != 0)
        destination[fill] = temporary[fill]
    destination[~lake_mask] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": dtype,
        "crs": TARGET_CRS,
        "transform": affine,
        "nodata": 0,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
        "predictor": 2,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(output, "w", **profile) as target:
        target.write(destination, 1)
    valid = int(((destination != 0) & lake_mask).sum())
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "valid_lake_fraction": valid / int(lake_mask.sum()),
        "errors": errors,
    }


def run_monthly_cube(
    start: date,
    end: date,
    *,
    output_root: Path = DEFAULT_OUTPUT,
    boundary_path: Path = DEFAULT_BOUNDARY,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    import rasterio

    output_root = Path(output_root)
    manifest_path = Path(manifest_path)
    affine, width, height, lake_mask, bounds = _target_grid(Path(boundary_path))
    plan = build_monthly_plan(start, end)
    inventory: list[dict[str, Any]] = []
    for index, item in enumerate(plan, start=1):
        month = item["month"]
        scenes = item.pop("selected")
        month_root = output_root / month
        outputs: dict[str, Any] = {}
        print(f"[{index}/{len(plan)}] {month} {item['selected_date']} tiles={len(scenes)}", flush=True)
        if not scenes:
            item.update(status="missing_catalogue_scene", outputs=outputs, selected_scenes=[])
            inventory.append(item)
            continue
        for asset in TARGET_ASSETS:
            output = month_root / f"taihu_s2_l2a_{month}_{ASSET_BAND_NAMES[asset]}_20m.tif"
            if _valid_existing(output, width, height):
                with rasterio.open(output) as dataset:
                    values = dataset.read(1)
                outputs[asset] = {
                    "path": str(output),
                    "bytes": output.stat().st_size,
                    "sha256": _sha256(output),
                    "valid_lake_fraction": float(((values != 0) & lake_mask).sum() / lake_mask.sum()),
                    "errors": [],
                    "resumed": True,
                }
            else:
                outputs[asset] = _render_asset(scenes, asset, output, affine, width, height, lake_mask)
        scl_path = Path(outputs["scl"]["path"])
        with rasterio.open(scl_path) as dataset:
            scl = dataset.read(1)
        cloudy = np.isin(scl, [0, 1, 3, 7, 8, 9, 10, 11])
        clear_fraction = float((lake_mask & ~cloudy).sum() / lake_mask.sum())
        item.update(
            status="completed" if all(not value["errors"] for value in outputs.values()) else "completed_with_warnings",
            selected_scenes=[
                {
                    "id": scene.get("id"),
                    "tile": _tile(scene),
                    "datetime": (scene.get("properties") or {}).get("datetime"),
                    "cloud_cover": _cloud(scene),
                    "collection": scene.get("_source_collection", COLLECTION),
                    "assets": {asset: scene["assets"][asset]["href"] for asset in TARGET_ASSETS},
                }
                for scene in scenes
            ],
            outputs=outputs,
            clear_lake_fraction=clear_fraction,
        )
        inventory.append(item)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"status": "running", "months": inventory}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    csv_path = output_root / "sentinel2_monthly_inventory.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["month", "selected_date", "status", "cloud_threshold", "candidate_scenes", "tile_count", "mean_tile_cloud", "clear_lake_fraction"],
        )
        writer.writeheader()
        for item in inventory:
            scenes = item.get("selected_scenes") or []
            writer.writerow(
                {
                    "month": item["month"],
                    "selected_date": item.get("selected_date"),
                    "status": item["status"],
                    "cloud_threshold": item["cloud_threshold"],
                    "candidate_scenes": item["candidate_scenes"],
                    "tile_count": len(scenes),
                    "mean_tile_cloud": sum(scene["cloud_cover"] for scene in scenes) / len(scenes) if scenes else None,
                    "clear_lake_fraction": item.get("clear_lake_fraction"),
                }
            )
    manifest = {
        "run_id": f"sentinel2_monthly_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed" if all(item["status"] == "completed" for item in inventory) else "completed_with_warnings",
        "source_id": "copernicus_sentinel2_l2a_via_earth_search",
        "api": API,
        "collection": COLLECTION,
        "period": [start.isoformat(), end.isoformat()],
        "selection": "one maximum-tile-coverage, lowest-mean-cloud same-day set per calendar month; cloud threshold fallback 30/60/101 percent",
        "assets": list(TARGET_ASSETS),
        "grid": {"crs": TARGET_CRS, "resolution_m": TARGET_RESOLUTION, "width": width, "height": height, "bounds": bounds},
        "boundary": str(boundary_path),
        "month_count": len(inventory),
        "completed_months": sum(item["status"].startswith("completed") for item in inventory),
        "inventory_csv": str(csv_path),
        "months": inventory,
        "license_note": "Contains modified Copernicus Sentinel data; preserve scene IDs, acquisition metadata and attribution.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


__all__ = ["build_monthly_plan", "run_monthly_cube", "search_month", "select_best_day"]
