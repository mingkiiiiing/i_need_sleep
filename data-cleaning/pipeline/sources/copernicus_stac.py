from __future__ import annotations

from urllib.parse import urlencode

from .common import IngestResult, request_json, utc_now, write_raw_json


STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac/search"


def ingest_sentinel2_stac(
    start: str,
    end: str,
    bbox: str = "119.9,30.9,120.7,31.5",
    limit: int = 100,
) -> IngestResult:
    params = {
        "collections": "sentinel-2-l2a",
        "bbox": bbox,
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": str(limit),
    }
    url = STAC_URL + "?" + urlencode(params)
    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(url)
        features = payload.get("features", [])
        raw_path = write_raw_json("copernicus_sentinel2_stac", url, status, content_type, payload)
        return IngestResult(
            source_id="copernicus_sentinel2_stac",
            status="ingested" if status == 200 else "failed",
            request_url=url,
            raw_path=str(raw_path),
            records=len(features),
            retrieved_at=retrieved_at,
            metadata={
                "scene_ids": [feature.get("id") for feature in features],
                "bbox": bbox,
                "start": start,
                "end": end,
            },
        )
    except Exception as exc:
        return IngestResult("copernicus_sentinel2_stac", "failed", url, None, 0, retrieved_at, str(exc))
