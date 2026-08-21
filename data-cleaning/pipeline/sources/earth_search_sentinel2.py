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
TAIHU_BBOX = (119.8, 30.9, 120.8, 31.6)
DEFAULT_ASSETS = ("blue", "green", "red", "rededge1", "nir", "swir16", "scl")


def build_search_payload(start: str, end: str, *, max_cloud: float = 30.0, limit: int = 20) -> dict[str, Any]:
    return {"collections": [COLLECTION], "bbox": list(TAIHU_BBOX), "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": limit, "query": {"eo:cloud_cover": {"lt": max_cloud}}}


def search_scenes(start: str, end: str, *, max_cloud: float = 30.0, limit: int = 20, timeout: int = 60) -> list[dict[str, Any]]:
    response = requests.post(API, json=build_search_payload(start, end, max_cloud=max_cloud, limit=limit), timeout=timeout)
    response.raise_for_status()
    features = response.json().get("features") or []
    return sorted(features, key=lambda item: (float(item.get("properties", {}).get("eo:cloud_cover") or 100.0), str(item.get("properties", {}).get("datetime") or "")))


def select_scene(features: list[dict[str, Any]], assets: tuple[str, ...] = DEFAULT_ASSETS) -> dict[str, Any] | None:
    return next((feature for feature in features if all(name in (feature.get("assets") or {}) and feature["assets"][name].get("href") for name in assets)), None)


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
    scenes = search_scenes(start, end, max_cloud=max_cloud)
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
        "status": status, "authorization": "none", "api": API, "collection": COLLECTION,
        "query": build_search_payload(start, end, max_cloud=max_cloud), "scene_count": len(scenes),
        "selected_scene": {"id": selected.get("id"), "datetime": selected.get("properties", {}).get("datetime"), "cloud_cover": selected.get("properties", {}).get("eo:cloud_cover")} if selected else None,
        "outputs": outputs, "warnings": warnings, "license_note": "Copernicus Sentinel data free and open; preserve attribution and source metadata", "manifest": str(manifest_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
