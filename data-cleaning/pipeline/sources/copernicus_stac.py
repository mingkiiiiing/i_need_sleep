from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlencode

from .common import IngestResult, request_json, utc_now, write_raw_json


STAC_ROOT = "https://stac.dataspace.copernicus.eu/v1"
STAC_URL = f"{STAC_ROOT}/search"
DEFAULT_COLLECTION = "sentinel-2-l2a"


def _parse_bbox(bbox: str | tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if isinstance(bbox, str):
        values = tuple(float(item.strip()) for item in bbox.split(","))
    else:
        values = tuple(float(item) for item in bbox)
    if len(values) != 4:
        raise ValueError("bbox must be west,south,east,north")
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be valid WGS84 west,south,east,north")
    return west, south, east, north


def build_stac_search_url(
    start: str,
    end: str,
    bbox: str | tuple[float, float, float, float] = "119.9,30.9,120.7,31.5",
    limit: int = 100,
    collection: str = DEFAULT_COLLECTION,
) -> str:
    """Build a current CDSE STAC API v1 item-search URL."""

    west, south, east, north = _parse_bbox(bbox)
    if int(limit) < 1 or int(limit) > 1000:
        raise ValueError("limit must be between 1 and 1000")
    params = {
        "collections": collection,
        "bbox": ",".join(f"{value:g}" for value in (west, south, east, north)),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": str(int(limit)),
    }
    return STAC_URL + "?" + urlencode(params)


def summarize_stac_feature(feature: Mapping[str, Any]) -> dict[str, Any]:
    """Retain scene metadata and lightweight asset descriptors for later download."""

    properties = dict(feature.get("properties") or {})
    assets: dict[str, dict[str, Any]] = {}
    for key, asset in (feature.get("assets") or {}).items():
        if not isinstance(asset, Mapping):
            continue
        assets[str(key)] = {
            field: asset[field]
            for field in ("href", "type", "title", "roles", "file:size")
            if field in asset
        }
    cloud = properties.get("eo:cloud_cover")
    if cloud is None:
        cloud = properties.get("cloud_cover", properties.get("cloudCover"))
    collection = feature.get("collection")
    if collection is None:
        collections = feature.get("collections") or []
        collection = collections[0] if collections else None
    return {
        "scene_id": feature.get("id"),
        "collection": collection,
        "acquisition_at": properties.get("datetime") or properties.get("start_datetime"),
        "end_datetime": properties.get("end_datetime"),
        "cloud_percent": float(cloud) if cloud is not None else None,
        "platform": properties.get("platform"),
        "instruments": properties.get("instruments"),
        "processing_level": properties.get("processing:level"),
        "geometry": feature.get("geometry"),
        "bbox": feature.get("bbox"),
        "asset_count": len(assets),
        "assets": assets,
    }


def ingest_sentinel2_stac(
    start: str,
    end: str,
    bbox: str = "119.9,30.9,120.7,31.5",
    limit: int = 100,
) -> IngestResult:
    url = build_stac_search_url(start, end, bbox=bbox, limit=limit)
    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(url)
        features = payload.get("features", [])
        scenes = [summarize_stac_feature(feature) for feature in features]
        raw_path = write_raw_json("copernicus_sentinel2_stac", url, status, content_type, payload)
        return IngestResult(
            source_id="copernicus_sentinel2_stac",
            status="ingested" if status == 200 else "failed",
            request_url=url,
            raw_path=str(raw_path),
            records=len(features),
            retrieved_at=retrieved_at,
            metadata={
                "collection": DEFAULT_COLLECTION,
                "scene_ids": [scene.get("scene_id") for scene in scenes],
                "scenes": scenes,
                "asset_count": sum(int(scene.get("asset_count", 0)) for scene in scenes),
                "bbox": bbox,
                "start": start,
                "end": end,
                "next": payload.get("links", []),
            },
        )
    except Exception as exc:
        return IngestResult("copernicus_sentinel2_stac", "failed", url, None, 0, retrieved_at, str(exc))
