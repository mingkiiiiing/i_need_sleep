"""卫星遥感图层 /rs/manifest 契约：observed 轨信封 + 产物缺失时 409 能力阻塞。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

RS_VERSION = "THQBCA-V2-BIOOPTICS-V1"
RS_CLAIM_BOUNDARY = "satellite_annual_retrieval_not_in_situ"


def _write_manifest(tmp_path):
    manifest = {
        "generated_at": "2026-09-07T12:00:00+08:00",
        "source_dataset": "test",
        "note": "test",
        "layers": [
            {
                "id": "chla",
                "name": "叶绿素 a 浓度",
                "unit": "μg/L",
                "vmin": 0,
                "vmax": 60,
                "legend_stops": [[0.0, "#16a34a"], [1.0, "#dc2626"]],
                "years": [
                    {
                        "year": 2019,
                        "png": "chla/TH_Chla_2019.png",
                        "bounds": [[30.9, 119.9], [31.5, 120.4]],
                        "stats": {"valid_pct": 52.7, "min": 0.17, "mean": 23.09, "p95": 33.55, "max": 79.94},
                    }
                ],
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_rs_manifest_uses_observed_track_envelope(tmp_path, monkeypatch):
    _write_manifest(tmp_path)
    monkeypatch.setenv("RS_OVERLAYS_DIR", str(tmp_path))
    body = client.get("/api/v1/rs/manifest").json()
    assert body["code"] == 200
    assert body["meta"]["data_mode"] == "observed"
    assert body["meta"]["dataset_version"] == RS_VERSION
    assert body["meta"]["claim_boundary"] == RS_CLAIM_BOUNDARY
    assert body["meta"]["prediction_run_id"] is None
    layer = body["data"]["layers"][0]
    assert layer["id"] == "chla"
    assert layer["years"][0]["png"] == "chla/TH_Chla_2019.png"
    assert len(layer["years"][0]["bounds"]) == 2


def test_rs_manifest_missing_artifacts_returns_409(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("RS_OVERLAYS_DIR", str(empty))
    body = client.get("/api/v1/rs/manifest").json()
    assert body["code"] == 409
    assert body["errors"][0]["code"] == "CAPABILITY_UNAVAILABLE"
    assert body["meta"]["dataset_version"] == RS_VERSION
    assert body["meta"]["data_mode"] == "observed"


@pytest.mark.skipif(
    not (__import__("pathlib").Path(__file__).resolve().parents[1] / "rs_overlays" / "manifest.json").is_file(),
    reason="rs_overlays 产物未生成（build_rs_overlays.py）",
)
def test_rs_manifest_static_png_mounted():
    manifest = client.get("/api/v1/rs/manifest").json()["data"]
    first = manifest["layers"][0]["years"][0]
    response = client.get(f"/rs/{first['png']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
