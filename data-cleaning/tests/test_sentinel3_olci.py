from __future__ import annotations

import json

import pipeline.sources.sentinel3_olci as olci


class _Response:
    def __init__(self, payload: bytes, content_type: str = "application/json", status: int = 200):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_process_request_uses_official_olci_type_and_water_quality_bands():
    request = olci.build_sentinel3_process_request(
        start="2025-06-01T00:00:00Z",
        end="2025-06-03T23:59:59Z",
        max_cloud_coverage=35,
        mosaicking_order="leastCC",
        upsampling="NEAREST",
    )
    data = request["input"]["data"][0]
    assert data["type"] == "sentinel-3-olci-l2"
    assert data["dataFilter"]["timeRange"]["from"] == "2025-06-01T00:00:00Z"
    assert data["dataFilter"]["maxCloudCoverage"] == 35.0
    assert data["dataFilter"]["mosaickingOrder"] == "leastCC"
    assert data["processing"]["upsampling"] == "NEAREST"
    for band in ["CHL_OC4ME", "CHL_NN", "TSM_NN", "KD490_M07", "dataMask"]:
        assert band in request["evalscript"]
    for unavailable in ["B13", "B14", "B15", "B19", "B20"]:
        assert unavailable not in olci.TARGET_BANDS
    assert request["output"]["responses"][0]["format"]["type"] == "image/tiff"


def test_no_credentials_stops_before_process_post(tmp_path, monkeypatch):
    for name in ["TAIHU_CDSE_ACCESS_TOKEN", "TAIHU_CDSE_TOKEN", "TAIHU_CDSE_CLIENT_ID", "TAIHU_CDSE_CLIENT_SECRET"]:
        monkeypatch.delenv(name, raising=False)
    result = olci.run_sentinel3_olci(
        start="2025-06-01T00:00:00Z",
        end="2025-06-03T23:59:59Z",
        output_path=tmp_path / "taihu.tif",
        manifest_path=tmp_path / "manifest.json",
    )
    assert result["status"] == "BLOCKED_AUTH"
    assert result["token_received"] is False
    assert result["raster_written"] is False
    assert not (tmp_path / "taihu.tif").exists()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["status"] == "BLOCKED_AUTH"


def test_authorized_process_response_is_saved_with_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("TAIHU_CDSE_ACCESS_TOKEN", "test-token-not-persisted")
    calls = []

    def fake_opener(request, timeout=180):
        calls.append((request.full_url, request.method, request.headers.get("Authorization")))
        if request.full_url == olci.PROCESS_API_URL:
            return _Response(b"II*\x00fake-tiff", "image/tiff")
        raise AssertionError("direct access token should avoid token endpoint")

    output = tmp_path / "taihu.tif"
    manifest_path = tmp_path / "manifest.json"
    result = olci.run_sentinel3_olci(
        start="2025-06-01T00:00:00Z",
        end="2025-06-03T23:59:59Z",
        output_path=output,
        manifest_path=manifest_path,
        opener=fake_opener,
    )
    assert result["status"] == "completed"
    assert result["data_truth"] == "real_sentinel3_olci_taihu_raster"
    assert output.read_bytes().startswith(b"II*")
    assert result["checksum_sha256"]
    assert calls == [(olci.PROCESS_API_URL, "POST", "Bearer test-token-not-persisted")]
    assert "test-token-not-persisted" not in manifest_path.read_text(encoding="utf-8")
