from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "sources.yml"
EXPECTED_ENDPOINT = "https://stac.dataspace.copernicus.eu/v1/search"


def _copernicus_source() -> dict:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources", [])
    matches = [source for source in sources if source.get("source_id") == "copernicus_sentinel2_stac"]
    assert len(matches) == 1
    return matches[0]


def test_copernicus_stac_config_uses_verified_v1_search_endpoint() -> None:
    source = _copernicus_source()
    sample_request = source["sample_request"]

    assert source["endpoint"] == EXPECTED_ENDPOINT
    assert source["method"] == "GET"
    assert source["api_version"] == "STAC API 1.0.0"
    assert "catalogue.dataspace.copernicus.eu" not in source["endpoint"]
    assert "collections=sentinel-2-l2a" in sample_request
    assert "bbox=119.9,30.9,120.7,31.5" in sample_request
    assert "datetime=2025-06-01T00:00:00Z/2025-06-30T23:59:59Z" in sample_request
    assert "limit=1" in sample_request
    assert source["verified_status"] == 200
    assert source["verified_content_type"] == "application/geo+json"

