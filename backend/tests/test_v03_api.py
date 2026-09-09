"""V0.3 API 端点契约：v3 状态/预测/门禁/校准/栅格/达标看板 + legacy 不回退。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.app import services as services_module

client = TestClient(app)


class FakeRealtimeV3:
    """V0.3 预测链最小实时输入：全湖均值含氨氮（P0-1 口径）。"""

    def summary(self):
        return {
            "latest_snapshot_id": "mee-v03-test",
            "latest_observed_at": "2026-09-09T15:00:00+08:00",
            "means": {
                "total_phosphorus": {"value": 0.096},
                "total_nitrogen": {"value": 1.717},
                "dissolved_oxygen": {"value": 6.105},
                "pH": {"value": 7.9},
                "ammonia_nitrogen": {"value": 0.21},
                "chlorophyll_a": {"value": 12.5},
            },
        }

    def station(self, entity_id: str):
        return None


@pytest.fixture()
def fake_v3_realtime(monkeypatch):
    v3 = services_module.service.algorithm_v3
    assert v3 is not None, "V0.3 服务未实例化"
    monkeypatch.setattr(v3, "realtime", FakeRealtimeV3())
    return v3


def test_v03_status_discloses_package_generation_and_legacy(fake_v3_realtime):
    response = client.get("/api/v1/model/v3/status")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["package_generation"] == "v0_3"
    assert body["data"]["feature_contract"]["n_features"] == 78
    assert body["data"]["granularity_tier"]
    assert body["data"]["legacy_package"]["legacy"] is True
    assert body["meta"]["claim_boundary"] == "real_data_monthly_station_v0_3"


def test_v03_predictions_month_granularity_and_uncertainty(fake_v3_realtime):
    response = client.get("/api/v1/model/v3/predictions?horizon_days=3")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["month_offset"] == 0
    assert data["granularity_tier"] == "month_granularity"
    assert data["model"]["claim_boundary"] == "real_data_monthly_station_v0_3"
    results = data["results"]
    assert {"bloom", "chla", "probability"} <= set(results)
    uncertainty = results["probability"].get("uncertainty")
    if uncertainty is not None:
        assert uncertainty["method"] == "split_conformal_residual_quantiles"
        assert uncertainty["is_calibrated_confidence_interval"] is True


def test_v03_predictions_scenario_lock_on_30_60_90(fake_v3_realtime):
    response = client.get("/api/v1/model/v3/predictions?horizon_days=30")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["month_offset"] == 1
    for result in data["results"].values():
        assert result["compliance"] == {
            "label": "情景推演", "locked": True, "granularity_tier": "multi_month",
        }


def test_v03_predictions_rejects_unsupported_horizon(fake_v3_realtime):
    response = client.get("/api/v1/model/v3/predictions?horizon_days=45")
    assert response.status_code == 422


def test_gate_detail_endpoint_lists_rows_and_na_reasons():
    response = client.get("/api/v1/model/acceptance/detail")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows"]
    assert data["summary"]["status"] in {"PASS", "FAIL", "NOT_APPLICABLE"}
    assert data["min_test_rows"] == 15


def test_calibration_coverage_endpoint():
    response = client.get("/api/v1/model/calibration/coverage")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"]
    for item in data["items"]:
        assert item["coverage_target"] == 0.90


def test_retrieval_validation_endpoint_discloses_holdout_metrics():
    response = client.get("/api/v1/rs/retrieval/validation")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["split"] == "holdout"
    assert data["metrics"], "留出指标缺失"
    for sensor, metrics in data["metrics"].items():
        assert "r2" in metrics and "rmse" in metrics


def test_spatial_field_raster_layer_with_boundary():
    response = client.get("/api/v1/model/spatial-field?horizon_days=3&metric=chla&layer=raster")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["layer"] == "raster"
    assert data["unit"] == "μg/L"
    assert data["boundary"]["threshold_ug_l"] == 20.0
    assert data["png_url"].startswith("/rs/monthly_v3/")


def test_spatial_field_model_layer_keeps_legacy_behavior():
    response = client.get("/api/v1/model/spatial-field?horizon_days=3&metric=risk")
    assert response.status_code == 200
    assert "prediction_run_id" in response.json()["data"]


def test_acceptance_overview_lists_p0_items():
    response = client.get("/api/v1/acceptance/overview")
    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data["items"]]
    assert ids == [f"P0-{index}" for index in range(1, 7)]
    for item in data["items"]:
        assert item["status"] in {"达标", "未达标", "部分达标"}
        assert item["evidence"]


def test_legacy_model_status_unchanged_with_generation_disclosure():
    response = client.get("/api/v1/model/status")
    assert response.status_code == 200
    body = response.json()
    # 保留页面契约不回退：V0.2 口径字段原样保留
    assert body["data"]["model_count"] == 63
    assert body["data"]["package_generation"] == "v0_2_legacy"
    assert body["data"]["successor_package"]["package_generation"] == "v0_3"
