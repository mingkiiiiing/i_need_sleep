from __future__ import annotations

import json
from pathlib import Path

import pipeline.sources.clms_lwq_byoc as byoc


PRODUCT = {
    "name": "c_gls_LWQ300_202608010000_GLOBE_OLCI_V2.1.1_cog",
    "content_date_start": "2026-08-01T00:00:00+00:00",
    "content_date_end": "2026-08-10T23:59:59.999000+00:00",
    "nominal_date": "2026-08-01T00:00:00+00:00",
    "target_variables": ["CHLAMEAN", "CHLAUNC", "FCBPROB"],
}


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


def test_process_request_uses_documented_byoc_collection_and_lwq_bands():
    request = byoc.build_clms_process_request(start="2026-08-01T00:00:00Z", end="2026-08-10T23:59:59Z")
    assert request["input"]["data"][0]["type"] == "byoc-5c2c9b2c-2893-41d9-b2bc-fbd6e5b8b31d"
    assert request["input"]["data"][0]["dataFilter"]["timeRange"]["from"] == "2026-08-01T00:00:00Z"
    assert all(band in request["evalscript"] for band in ["CHLAMEAN", "CHLAUNC", "FCBPROB", "QFLAG"])
    assert request["output"]["responses"][0]["format"]["type"] == "image/tiff"


def test_no_credentials_stops_before_process_post(tmp_path, monkeypatch):
    for name in ["TAIHU_CDSE_ACCESS_TOKEN", "TAIHU_CDSE_TOKEN", "TAIHU_CDSE_CLIENT_ID", "TAIHU_CDSE_CLIENT_SECRET"]:
        monkeypatch.delenv(name, raising=False)
    result = byoc.run_clms_lwq_byoc(selected_product=PRODUCT, output_path=tmp_path / "taihu.tif", manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["token_received"] is False
    assert not (tmp_path / "taihu.tif").exists()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["status"] == "BLOCKED_AUTH"


def test_authorized_process_response_is_saved_with_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("TAIHU_CDSE_ACCESS_TOKEN", "test-token-not-persisted")
    calls = []

    def fake_opener(request, timeout=180):
        calls.append((request.full_url, request.method))
        if request.full_url == byoc.PROCESS_API_URL:
            return _Response(b"II*\x00fake-tiff", "image/tiff")
        raise AssertionError("direct access token should avoid token endpoint")

    output = tmp_path / "taihu.tif"
    result = byoc.run_clms_lwq_byoc(selected_product=PRODUCT, output_path=output, manifest_path=tmp_path / "manifest.json", opener=fake_opener)
    assert result["status"] == "completed"
    assert result["data_truth"] == "real_clms_taihu_raster"
    assert output.read_bytes().startswith(b"II*")
    assert result["checksum_sha256"]
    assert calls == [(byoc.PROCESS_API_URL, "POST")]
