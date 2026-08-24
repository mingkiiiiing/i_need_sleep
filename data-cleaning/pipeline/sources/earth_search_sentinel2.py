from __future__ import annotations

"""No-auth Sentinel-2 L2A access through Element 84 Earth Search/AWS COGs."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-c1-l2a"
COLLECTION_FALLBACKS = (COLLECTION, "sentinel-2-l2a", "sentinel-2-pre-c1-l2a")
TAIHU_BBOX = (119.8, 30.9, 120.8, 31.6)
DEFAULT_ASSETS = ("blue", "green", "red", "rededge1", "nir", "swir16", "scl")


def build_search_payload(start: str, end: str, *, max_cloud: float = 30.0, limit: int = 20, collection: str = COLLECTION) -> dict[str, Any]:
    return {"collections": [collection], "bbox": list(TAIHU_BBOX), "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": limit, "query": {"eo:cloud_cover": {"lt": max_cloud}}}


def search_scenes(start: str, end: str, *, max_cloud: float = 30.0, limit: int = 20, timeout: int = 60, collection: str = COLLECTION) -> list[dict[str, Any]]:
    response = requests.post(API, json=build_search_payload(start, end, max_cloud=max_cloud, limit=limit, collection=collection), timeout=timeout)
    response.raise_for_status()
    features = response.json().get("features") or []
    return sorted(features, key=lambda item: (float(item.get("properties", {}).get("eo:cloud_cover") or 100.0), str(item.get("properties", {}).get("datetime") or "")))


def select_scene(features: list[dict[str, Any]], assets: tuple[str, ...] = DEFAULT_ASSETS) -> dict[str, Any] | None:
    return next((feature for feature in features if all(name in (feature.get("assets") or {}) and feature["assets"][name].get("href") for name in assets)), None)


def _mgrs_tile(feature: dict[str, Any]) -> str:
    properties = feature.get("properties") or {}
    tile = properties.get("s2:mgrs_tile") or properties.get("mgrs:tile")
    if tile:
        return str(tile)
    parts = str(feature.get("id") or "").split("_")
    return parts[1] if len(parts) > 1 else "unknown"


def select_scene_set(features: list[dict[str, Any]], assets: tuple[str, ...] = DEFAULT_ASSETS) -> list[dict[str, Any]]:
    """Select the lowest-cloud same-day tile set intersecting the Taihu bbox."""

    complete = [feature for feature in features if all(name in (feature.get("assets") or {}) and feature["assets"][name].get("href") for name in assets)]
    by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for feature in complete:
        observed = str((feature.get("properties") or {}).get("datetime") or "")[:10]
        tile = _mgrs_tile(feature)
        current = by_day.setdefault(observed, {}).get(tile)
        cloud = float((feature.get("properties") or {}).get("eo:cloud_cover") or 100.0)
        current_cloud = float((current.get("properties") or {}).get("eo:cloud_cover") or 100.0) if current else float("inf")
        if current is None or cloud < current_cloud:
            by_day[observed][tile] = feature
    if not by_day:
        return []
    _, chosen = min(
        by_day.items(),
        key=lambda item: (
            -len(item[1]),
            sum(float((scene.get("properties") or {}).get("eo:cloud_cover") or 100.0) for scene in item[1].values()) / len(item[1]),
            item[0],
        ),
    )
    return [chosen[tile] for tile in sorted(chosen)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crop_cog(href: str, output: Path, bbox: tuple[float, float, float, float] = TAIHU_BBOX) -> dict[str, Any]:
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.Env(GDAL_HTTP_MULTIRANGE="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(href) as source:
            projected = transform_bounds("EPSG:4326", source.crs, *bbox, densify_pts=21)
            window = from_bounds(*projected, transform=source.transform).round_offsets().round_lengths()
            window = window.intersection(rasterio.windows.Window(0, 0, source.width, source.height))
            data = source.read(window=window)
            profile = source.profile.copy()
            profile.update(driver="GTiff", height=data.shape[1], width=data.shape[2], transform=source.window_transform(window), tiled=True, compress="deflate")
            with rasterio.open(output, "w", **profile) as target:
                target.write(data)
    return {"path": str(output), "bytes": output.stat().st_size, "sha256": _sha256(output)}


def run_earth_search_sentinel2(start: str, end: str, output_root: Path, *, max_cloud: float = 30.0, assets: tuple[str, ...] = DEFAULT_ASSETS, manifest_path: Path | None = None) -> dict[str, Any]:
    scenes: list[dict[str, Any]] = []
    selected_collection = COLLECTION
    search_attempts: list[dict[str, Any]] = []
    for collection in COLLECTION_FALLBACKS:
        scenes = search_scenes(start, end, max_cloud=max_cloud, collection=collection)
        search_attempts.append({"collection": collection, "scene_count": len(scenes)})
        if scenes:
            selected_collection = collection
            break
    selected = select_scene(scenes, assets)
    outputs: dict[str, Any] = {}
    status = "completed" if selected else "BLOCKED_DATA"
    warnings: list[str] = []
    if selected:
        scene_root = output_root / str(selected["id"])
        for asset in assets:
            try:
                outputs[asset] = crop_cog(selected["assets"][asset]["href"], scene_root / f"{asset}.tif")
            except Exception as exc:
                outputs[asset] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                warnings.append(f"{asset}_crop_failed")
        if not all(item.get("path") for item in outputs.values()):
            status = "completed_with_warnings"
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest = {
        "run_id": f"earth_search_s2_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}", "source_id": "earth_search_sentinel2_l2a",
        "status": status, "authorization": "none", "api": API, "collection": selected_collection,
        "query": build_search_payload(start, end, max_cloud=max_cloud, collection=selected_collection), "search_attempts": search_attempts, "scene_count": len(scenes),
        "selected_scene": {"id": selected.get("id"), "datetime": selected.get("properties", {}).get("datetime"), "cloud_cover": selected.get("properties", {}).get("eo:cloud_cover")} if selected else None,
        "outputs": outputs, "warnings": warnings, "license_note": "Copernicus Sentinel data free and open; preserve attribution and source metadata", "manifest": str(manifest_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def run_earth_search_sentinel2_mosaic(start: str, end: str, output_root: Path, *, max_cloud: float = 30.0, assets: tuple[str, ...] = DEFAULT_ASSETS, manifest_path: Path | None = None, limit: int = 100) -> dict[str, Any]:
    """Download a same-day, multi-tile Taihu scene set instead of one partial tile."""

    scenes: list[dict[str, Any]] = []
    selected_collection = COLLECTION
    search_attempts: list[dict[str, Any]] = []
    for collection in COLLECTION_FALLBACKS:
        scenes = search_scenes(start, end, max_cloud=max_cloud, limit=limit, collection=collection)
        search_attempts.append({"collection": collection, "scene_count": len(scenes)})
        if scenes:
            selected_collection = collection
            break
    selected = select_scene_set(scenes, assets)
    outputs: dict[str, Any] = {}
    warnings: list[str] = []
    for scene in selected:
        scene_id = str(scene["id"])
        scene_outputs: dict[str, Any] = {}
        for asset in assets:
            try:
                scene_outputs[asset] = crop_cog(scene["assets"][asset]["href"], output_root / scene_id / f"{asset}.tif")
            except Exception as exc:
                scene_outputs[asset] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                warnings.append(f"{scene_id}:{asset}_crop_failed")
        outputs[scene_id] = scene_outputs
    complete = bool(selected) and all(item.get("path") for scene_outputs in outputs.values() for item in scene_outputs.values())
    status = "completed" if complete else "completed_with_warnings" if selected else "BLOCKED_DATA"
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest = {
        "run_id": f"earth_search_s2_mosaic_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "source_id": "earth_search_sentinel2_l2a",
        "status": status,
        "authorization": "none",
        "api": API,
        "collection": selected_collection,
        "query": build_search_payload(start, end, max_cloud=max_cloud, limit=limit, collection=selected_collection),
        "search_attempts": search_attempts,
        "scene_count": len(scenes),
        "selected_scenes": [{"id": scene["id"], "tile": _mgrs_tile(scene), "datetime": (scene.get("properties") or {}).get("datetime"), "cloud_cover": (scene.get("properties") or {}).get("eo:cloud_cover")} for scene in selected],
        "outputs": outputs,
        "warnings": warnings,
        "license_note": "Copernicus Sentinel data free and open; preserve attribution and source metadata",
        "manifest": str(manifest_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
