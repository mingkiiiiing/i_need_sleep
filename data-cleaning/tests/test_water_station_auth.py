from __future__ import annotations

from pathlib import Path

import pipeline.sources.water_station as water_station


def test_fetch_blocks_before_network_without_station_token(monkeypatch):
    monkeypatch.delenv("TAIHU_WATER_STATION_TOKEN", raising=False)
    monkeypatch.setattr(water_station, "request_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not be called")))
    result = water_station.ingest_water_station_endpoint("https://example.test/hj1404", source_id="taihu_water_station")
    assert result.status == "BLOCKED_AUTH"
    assert result.raw_path is None
    assert result.metadata == {"token_env": "TAIHU_WATER_STATION_TOKEN", "token_present": False, "request_attempted": False}


def test_fetch_uses_bearer_token_but_persists_only_sanitized_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TAIHU_WATER_STATION_TOKEN", "secret-token")
    captured: dict[str, object] = {}

    def fake_request(url, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        return 200, "application/json", {"records": [{"station_id": "S1", "value": 1}]}

    raw_path = tmp_path / "response.json"
    monkeypatch.setattr(water_station, "request_json", fake_request)
    monkeypatch.setattr(water_station, "write_raw_json", lambda *args: raw_path)
    result = water_station.ingest_water_station_endpoint("https://example.test/hj1404?token=secret-token", source_id="taihu_water_station")
    assert result.status == "ingested"
    assert result.request_url == "https://example.test/hj1404?token=%5BREDACTED%5D"
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert result.metadata["request_attempted"] is True
    assert "secret-token" not in result.request_url


def test_auth_probe_does_not_attempt_network(monkeypatch):
    monkeypatch.delenv("TAIHU_WATER_STATION_TOKEN", raising=False)
    result = water_station.probe_water_station_auth("https://example.test/hj1404")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["request_attempted"] is False
    assert result["token_present"] is False
