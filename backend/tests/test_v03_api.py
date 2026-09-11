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


def _suite(horizon: int) -> dict:
    """模型层记录：读取接口已改为快照只读，端到端语义断言直接调 predict_suite。"""
    return services_module.service.algorithm_v3.predict_suite(horizon, "lake", "risk")


def test_v03_predictions_month_granularity_and_uncertainty(fake_v3_realtime):
    data = _suite(3)
    assert data["month_offset"] == 0
    assert data["granularity_tier"] == "month_granularity"
    assert data["model"]["claim_boundary"] == "real_data_monthly_station_v0_3"
    results = data["results"]
    assert {"bloom", "chla", "probability"} <= set(results)
    uncertainty = results["probability"].get("uncertainty")
    if uncertainty is not None:
        assert uncertainty["method"] == "split_conformal_residual_quantiles"
        # 区间语义：这是预测区间，不是参数置信区间；旧口径单一布尔量已停用
        assert "is_calibrated_confidence_interval" not in uncertainty
        assert uncertainty["is_prediction_interval"] is True
        assert uncertainty["interval_semantics"] == "prediction_interval_not_parameter_confidence_interval"
        # 三层结论必须独立给出：结构自洽 / 校准证据 / 决策可用
        assert isinstance(uncertainty["structural_valid"], bool)
        assert uncertainty["calibration_status"] in {
            "validated", "no_test_evidence", "insufficient_test_evidence", "unavailable",
        }
        evidence = uncertainty["calibration_evidence"]
        assert {"status", "calibration_n", "test_n", "empirical_coverage", "min_test_n"} <= set(evidence)
        # 决策可用 = 结构自洽 ∧ 校准证据充分；二者缺一即不可用于决策
        assert uncertainty["decision_usable"] == (
            uncertainty["structural_valid"] and uncertainty["calibration_status"] == "validated"
        )
        # test_n=0/1 时经验覆盖率非 0 即 1，绝不构成校准证据
        if uncertainty["test_n"] in (None, 0, 1):
            assert uncertainty["calibration_status"] != "validated"
            assert uncertainty["decision_usable"] is False
        # 双指纹：既证明站点实测不同，也证明模型最终输入矩阵不同
        assert data["observed_input_fingerprint"]
        assert data["fingerprint_schema"] == "dual_fingerprint_v1"
        assert data["transformed_model_input_fingerprints"]


def test_v03_predictions_longterm_lock_on_30_60_90(fake_v3_realtime):
    """30/60/90 天的合规边界语义不变（locked=true），表述已与事实对齐。

    2026-09-11：这三档此前统称"情景推演"，现在有真实来源与留出回测——90 天为逐站模型，
    30/60 天为季节气候态基线。沿用旧称会低报证据强度；但"不得当作逐站实测预测"的边界
    依旧成立，故 label 改为"中长期月度趋势"、locked 保持 True、granularity_tier 不变。
    """
    data = _suite(30)
    assert data["month_offset"] == 1
    for key, result in data["results"].items():
        expected = {
            "label": "中长期月度趋势", "locked": True, "granularity_tier": "multi_month",
        }
        if key == "area":
            # 2026-09-11 起水华面积来自月度反演基底边界面积，粒度口径如实标注
            expected["granularity_tier"] = "month_retrieval_base"
        assert result["compliance"] == expected


def test_v03_predictions_snapshot_not_ready_returns_409(fake_v3_realtime):
    """审计合同：业务读取接口快照未就绪一律 409，绝不回落即时推理。"""
    response = client.get("/api/v1/model/v3/predictions?horizon_days=3")
    assert response.status_code == 409
    body = response.json()
    codes = [body.get("detail", {}).get("code")] + [e.get("code") for e in body.get("errors", [])]
    assert "PREDICTION_SNAPSHOT_NOT_READY" in codes


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
    # P0-7/P0-8 为 2026-09-11 复审新增：标签来源逐行继承、模型身份一一对应
    assert ids == [f"P0-{index}" for index in range(1, 9)]
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
