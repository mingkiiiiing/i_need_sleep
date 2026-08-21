import json
from pathlib import Path

import pipeline.sources.common as source_common
from pipeline.provenance import (
    build_asset_manifest,
    sanitize_headers,
    sanitize_url,
    write_asset_manifest,
)


def test_sanitize_url_and_headers_remove_credentials(tmp_path):
    url = sanitize_url(
        "https://example.test/data?token=abc123&client_secret=xyz&bbox=1%2C2"
    )
    assert "abc123" not in url
    assert "xyz" not in url
    assert "bbox=1%2C2" in url
    headers = sanitize_headers(
        {"Authorization": "Bearer abc123", "Content-Type": "application/json"}
    )
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["Content-Type"] == "application/json"


def test_asset_manifest_contains_http_checksum_license_and_retry_contract(tmp_path):
    asset = tmp_path / "sample.json"
    asset.write_text('{"value": 1}\n', encoding="utf-8")
    manifest = build_asset_manifest(
        source_id="test_source",
        asset_id="sample-001",
        request_url="https://example.test/data?api_key=secret",
        local_path=asset,
        requested_at_utc="2026-08-19T00:00:00Z",
        retrieved_at_utc="2026-08-19T00:00:01Z",
        http_status=200,
        response_headers={"Content-Type": "application/json"},
        license_tag="CC-BY-4.0",
        redistribution_allowed="yes",
        commercial_use="yes",
        retries=2,
    )
    assert manifest["manifest_type"] == "raw_asset"
    assert manifest["http_status"] == 200
    assert manifest["checksum_sha256"]
    assert manifest["size_bytes"] == asset.stat().st_size
    assert manifest["license"]["license_tag"] == "CC-BY-4.0"
    assert manifest["retries"] == 2
    assert "secret" not in manifest["request_url"]
    output = tmp_path / "manifest.json"
    write_asset_manifest(manifest, output)
    assert json.loads(output.read_text(encoding="utf-8"))["source_id"] == "test_source"


def test_common_raw_writer_emits_the_shared_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(source_common, "RAW_ROOT", tmp_path / "raw")
    monkeypatch.setenv("A23_MANIFEST_ROOT", str(tmp_path / "manifests"))
    raw = source_common.write_raw_json(
        "test_source", "https://example.test/data?token=secret", 200, "application/json", {"ok": True}
    )
    manifests = list((tmp_path / "manifests").glob("raw_test_source_*.json"))
    assert raw.exists()
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["manifest_type"] == "raw_asset"
    assert payload["http_status"] == 200
    assert "secret" not in payload["request_url"]
