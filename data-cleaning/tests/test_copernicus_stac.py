from __future__ import annotations

from pipeline.sources import copernicus_stac


def _feature():
    return {
        "type": "Feature",
        "id": "S2A_MSIL2A_20250628T024141_N0511_R089_T51RTQ_20250628T074719",
        "collection": "sentinel-2-l2a",
        "bbox": [119.9, 30.9, 120.7, 31.5],
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {
            "datetime": "2025-06-28T02:41:41.024Z",
            "eo:cloud_cover": 15.366124,
            "platform": "sentinel-2a",
            "processing:level": "L2",
        },
        "assets": {
            "B04_10m": {"href": "s3://eodata/B04.jp2", "type": "image/jp2", "roles": ["data"]},
            "SCL_20m": {"href": "s3://eodata/SCL.jp2", "type": "image/jp2", "roles": ["data"]},
        },
    }


def test_build_stac_url_uses_current_v1_search_endpoint():
    url = copernicus_stac.build_stac_search_url("2025-06-01", "2025-06-30", limit=1)
    assert url.startswith("https://stac.dataspace.copernicus.eu/v1/search?")
    assert "collections=sentinel-2-l2a" in url
    assert "bbox=119.9%2C30.9%2C120.7%2C31.5" in url
    assert "datetime=2025-06-01T00%3A00%3A00Z%2F2025-06-30T23%3A59%3A59Z" in url
    assert "limit=1" in url


def test_summarize_feature_preserves_scene_and_assets():
    summary = copernicus_stac.summarize_stac_feature(_feature())
    assert summary["scene_id"].startswith("S2A_MSIL2A_")
    assert summary["collection"] == "sentinel-2-l2a"
    assert summary["acquisition_at"].startswith("2025-06-28T02:41:41")
    assert summary["cloud_percent"] == 15.366124
    assert summary["asset_count"] == 2
    assert summary["assets"]["B04_10m"]["href"].startswith("s3://")


def test_ingest_returns_scene_metadata_and_assets(monkeypatch, tmp_path):
    payload = {"type": "FeatureCollection", "features": [_feature()], "links": [{"rel": "self", "href": "x"}]}
    monkeypatch.setattr(copernicus_stac, "request_json", lambda url: (200, "application/geo+json", payload))
    monkeypatch.setattr(copernicus_stac, "write_raw_json", lambda *args: tmp_path / "stac.json")
    result = copernicus_stac.ingest_sentinel2_stac("2025-06-01", "2025-06-30", limit=1)
    assert result.status == "ingested"
    assert result.records == 1
    assert result.metadata["collection"] == "sentinel-2-l2a"
    assert result.metadata["asset_count"] == 2
    assert result.metadata["scenes"][0]["scene_id"].startswith("S2A_MSIL2A_")
