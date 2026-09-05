"""第七任务收口：错误契约、诚实披露与 Provider 边界测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

OBS_VERSION = "DEMO-OBS-V1"
PRED_VERSION = "DEMO-PRED-V1"
RUN_ID = "DEMO-RUN-V1"
META_KEYS = {"data_mode", "dataset_version", "prediction_run_id", "as_of", "claim_boundary", "request_id"}


def assert_error_envelope(
    body: dict, *, status: int, code: str, dataset_version: str, field: str | None = None
) -> dict:
    assert body["code"] == status
    assert body["data"] is None
    assert isinstance(body["errors"], list) and body["errors"]
    first = body["errors"][0]
    assert first["code"] == code
    if field is not None:
        assert first["field"] == field
    assert first["detail"]
    meta = body["meta"]
    assert set(meta.keys()) == META_KEYS
    assert meta["data_mode"] == "simulated"
    assert meta["dataset_version"] == dataset_version
    assert meta["prediction_run_id"] is None
    assert meta["claim_boundary"] == "simulation_only"
    assert meta["as_of"] == "2026-08-24T08:00:00+08:00"
    assert meta["request_id"]
    return body


# ---- 1. 非法对象引用：404 ENTITY_NOT_FOUND ----
def test_unknown_entity_returns_404_entity_not_found() -> None:
    assert_error_envelope(
        client.get("/api/v1/spatial-entities/no_such_zone").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=OBS_VERSION,
    )
    assert_error_envelope(
        client.get("/api/v1/spatial-entities/no_such_zone/observations").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=OBS_VERSION,
    )


def test_unknown_forecast_id_returns_404_entity_not_found() -> None:
    assert_error_envelope(
        client.get("/api/v1/forecasts/demo-forecast-no_such_zone-3d").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=PRED_VERSION,
    )
    assert_error_envelope(
        client.get("/api/v1/forecasts/demo-forecast-no_such_zone-3d/explanations").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=PRED_VERSION,
    )


# ---- 2. 非法档位：422 INVALID_HORIZON ----
@pytest.mark.parametrize("horizon", [0, 2, 5, -1, 31])
def test_invalid_horizon_returns_422(horizon: int) -> None:
    assert_error_envelope(
        client.get(f"/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days={horizon}").json(),
        status=422,
        code="INVALID_HORIZON",
        field="horizon_days",
        dataset_version=PRED_VERSION,
    )
    assert_error_envelope(
        client.get(f"/api/v1/map/risk-grid?horizon_days={horizon}").json(),
        status=422,
        code="INVALID_HORIZON",
        field="horizon_days",
        dataset_version=PRED_VERSION,
    )


# ---- 3. T+30 分区预测：能力阻塞而非假数据 ----
def test_t30_zone_forecast_returns_409_capability_unavailable() -> None:
    body = assert_error_envelope(
        client.get("/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=30").json(),
        status=409,
        code="CAPABILITY_UNAVAILABLE",
        dataset_version=PRED_VERSION,
    )
    assert "30" in body["errors"][0]["detail"] or "T+30" in body["errors"][0]["detail"]


def test_t30_forecast_record_returns_409_capability_unavailable() -> None:
    assert_error_envelope(
        client.get("/api/v1/forecasts/demo-forecast-northwest_hotspot-30d").json(),
        status=409,
        code="CAPABILITY_UNAVAILABLE",
        dataset_version=PRED_VERSION,
    )


# ---- 4/5. timeline 日期倒置与跨度超限：4xx 而非空数组 ----
def test_timeline_reversed_dates_returns_422_invalid_date_range() -> None:
    body = assert_error_envelope(
        client.get("/api/v1/cockpit/timeline?start=2026-08-22&end=2026-08-20").json(),
        status=422,
        code="INVALID_DATE_RANGE",
        field="start",
        dataset_version=PRED_VERSION,
    )
    assert "start" in body["errors"][0]["detail"] or "end" in body["errors"][0]["detail"]


def test_timeline_over_90_days_returns_422_query_range_too_large() -> None:
    body = assert_error_envelope(
        client.get("/api/v1/cockpit/timeline?start=2026-06-01&end=2026-08-31").json(),
        status=422,
        code="QUERY_RANGE_TOO_LARGE",
        dataset_version=PRED_VERSION,
    )
    assert "90" in body["errors"][0]["detail"]


def test_timeline_exactly_90_day_span_is_accepted() -> None:
    # 前端 historyCore.js MAX_RANGE_DAYS=90：diff=90（91 个日历日）必须放行
    resp = client.get("/api/v1/cockpit/timeline?start=2026-06-02&end=2026-08-31")
    assert resp.status_code == 200
    assert resp.json()["code"] == 200


def test_timeline_malformed_dates_rejected_not_silently_emptied() -> None:
    assert client.get("/api/v1/cockpit/timeline?start=not-a-date&end=2026-08-20").status_code == 422


# ---- 6. timeline 不再声称真实叶绿素/水质观测 ----
def test_timeline_rows_claim_no_real_chlorophyll_or_quality() -> None:
    rows = client.get("/api/v1/cockpit/timeline?start=2026-08-20&end=2026-08-22").json()["data"]["data"]
    assert rows
    forbidden = {
        "chlorophyll_a",
        "chla",
        "total_phosphorus",
        "total_nitrogen",
        "observation",
        "observed_value",
        "quality_status",
        "value_origin",
    }
    for row in rows:
        assert not (set(row.keys()) & forbidden), f"timeline 行携带疑似观测字段: {row}"
        assert row["data_mode"] == "simulated"
        assert row["dataset_version"] == PRED_VERSION


def test_dashboard_overview_has_no_avg_chlorophyll_claim() -> None:
    payload = client.get("/api/v1/dashboard/overview").json()["data"]
    text = str(payload).lower()
    assert "叶绿素" not in str(payload)
    assert "chlorophyll" not in text


# ---- 7. forecast ↔ explanation 严格绑定 ----
def test_explanation_is_strictly_bound_to_its_forecast() -> None:
    forecast_id = "demo-forecast-central_lake-7d"
    forecast = client.get(f"/api/v1/forecasts/{forecast_id}").json()["data"]
    explanation = client.get(f"/api/v1/forecasts/{forecast_id}/explanations").json()["data"]
    assert explanation["forecast_id"] == forecast_id == forecast["id"]
    assert explanation["prediction_run_id"] == forecast["prediction_run_id"] == RUN_ID
    # 数据版本由信封 meta 携带，data 内不重复声称
    assert explanation["dataset_version"] == PRED_VERSION
    assert explanation["features"], "解释必须提供特征贡献列表"
    for feature in explanation["features"]:
        assert feature["name"] and feature["label"]
        assert 0 <= feature["contribution"] <= 1


def test_explanation_rejected_for_blocked_t30_record() -> None:
    # T+30 无可解释预测：解释接口不得为被能力阻塞的档位编造解释
    body = assert_error_envelope(
        client.get("/api/v1/forecasts/demo-forecast-central_lake-30d/explanations").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=PRED_VERSION,
    )
    assert "解释" in body["errors"][0]["detail"] or "forecast" in body["errors"][0]["detail"]


# ---- 8. 空 risk-polygons 诚实披露原因，不虚构几何 ----
@pytest.mark.parametrize("horizon", [1, 3, 7, 15])
def test_risk_polygons_are_empty_with_honest_reason(horizon: int) -> None:
    data = client.get(f"/api/v1/map/risk-polygons?horizon_days={horizon}").json()["data"]
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []
    assert data["empty_reason"]
    assert data["horizon_days"] == horizon
    # 不虚构面积/分辨率/置信度/迁移速度等数值字段：仅披露空结果与原因
    fabricated_keys = {"area_km2", "resolution", "resolution_m", "confidence", "migration_speed"}
    assert not (set(data.keys()) & fabricated_keys)


# ---- 9/10/11. 模拟发送预警：simulated_dispatched + persisted:false ----
def test_handle_warning_returns_simulated_dispatched_and_not_persisted() -> None:
    data = client.post("/api/v1/cockpit/handle-warning", json={"event_id": "demo-event-1"}).json()["data"]
    assert data["status"] == "simulated_dispatched"
    assert data["persisted"] is False
    assert data["data_mode"] == "simulated"
    assert data["claim_boundary"] == "simulation_only"


@pytest.mark.parametrize("ref", ["northwest_hotspot", "R01-C01", "R11-C19"])
def test_handle_warning_accepts_three_demo_reference_kinds(ref: str) -> None:
    data = client.post("/api/v1/cockpit/handle-warning", json={"event_id": ref}).json()["data"]
    assert data["status"] == "simulated_dispatched"
    assert data["persisted"] is False


@pytest.mark.parametrize(
    "ref", ["demo-event-999", "not-an-id", "R00-C01", "R12-C01", "R01-C20", "", "drop table"]
)
def test_invalid_event_reference_rejected_with_422(ref: str) -> None:
    body = assert_error_envelope(
        client.post("/api/v1/cockpit/handle-warning", json={"event_id": ref}).json(),
        status=422,
        code="INVALID_EVENT_ID",
        field="event_id",
        dataset_version=PRED_VERSION,
    )
    # 不存在的事件 ID 必须被拒绝，而非静默成功
    assert body["data"] is None


def test_handle_warning_requires_event_id_field() -> None:
    resp = client.post("/api/v1/cockpit/handle-warning", json={})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "REQUEST_VALIDATION_FAILED"


# ---- 12. 不存在真实短信/邮件/电话渠道 ----
def test_warning_channels_contain_no_real_delivery_channels() -> None:
    data = client.post("/api/v1/cockpit/handle-warning", json={"event_id": "demo-event-1"}).json()["data"]
    assert data["channels"] == ["platform_simulation"]
    text = str(data)
    for banned in ("sms", "email", "短信", "邮件", "电话", "phone", "dingtalk", "webhook"):
        assert banned not in text.lower()


# ---- 13. 错误响应保留 request_id 且可跨请求区分 ----
def test_error_responses_carry_unique_request_ids() -> None:
    ids = set()
    for _ in range(3):
        body = client.get("/api/v1/spatial-entities/no_such_zone").json()
        ids.add(body["meta"]["request_id"])
    assert len(ids) == 3


# ---- 14. 请求真实数据模式：409 SIMULATION_ONLY ----
def test_real_data_modes_return_409_simulation_only() -> None:
    assert_error_envelope(
        client.get("/api/v1/dashboard/overview?mode=historical").json(),
        status=409,
        code="SIMULATION_ONLY",
        dataset_version=PRED_VERSION,
    )
    assert_error_envelope(
        client.get("/api/v1/spatial-entities?mode=observed").json(),
        status=409,
        code="SIMULATION_ONLY",
        dataset_version=OBS_VERSION,
    )


# ---- 14b. 错误路径数据身份：观察类=OBS / 预测类=PRED（audit7 返工新增） ----
def test_observation_endpoint_success_envelope() -> None:
    body = client.get("/api/v1/spatial-entities").json()
    assert body["code"] == 200 and body["message"] == "ok" and body["errors"] == []
    meta = body["meta"]
    assert set(meta.keys()) == META_KEYS
    assert meta["dataset_version"] == OBS_VERSION
    assert meta["prediction_run_id"] is None
    assert meta["data_mode"] == "simulated"
    assert meta["claim_boundary"] == "simulation_only"
    assert meta["as_of"] == "2026-08-24T08:00:00+08:00"
    assert meta["request_id"].startswith("req_")


def test_observation_endpoint_business_error_carries_obs_version() -> None:
    # P1 根因回归：观察类接口业务错误的 meta.dataset_version 必须保持 DEMO-OBS-V1
    assert_error_envelope(
        client.get("/api/v1/spatial-entities/no_such_zone").json(),
        status=404,
        code="ENTITY_NOT_FOUND",
        dataset_version=OBS_VERSION,
    )
    assert_error_envelope(
        client.get("/api/v1/spatial-entities?mode=observed").json(),
        status=409,
        code="SIMULATION_ONLY",
        dataset_version=OBS_VERSION,
    )


def test_observation_endpoint_validation_error_carries_obs_version() -> None:
    # RequestValidationError 也不得回落到预测版本
    body = assert_error_envelope(
        client.get("/api/v1/spatial-entities?mode=bogus").json(),
        status=422,
        code="REQUEST_VALIDATION_FAILED",
        field="query.mode",
        dataset_version=OBS_VERSION,
    )
    assert "mode" in body["errors"][0]["detail"] or body["errors"][0]["field"] == "query.mode"


def test_prediction_endpoint_business_error_carries_pred_version() -> None:
    assert_error_envelope(
        client.get("/api/v1/dashboard/overview?mode=historical").json(),
        status=409,
        code="SIMULATION_ONLY",
        dataset_version=PRED_VERSION,
    )


def test_prediction_endpoint_validation_error_carries_pred_version() -> None:
    assert_error_envelope(
        client.get("/api/v1/cockpit/timeline?start=not-a-date&end=2026-08-20").json(),
        status=422,
        code="REQUEST_VALIDATION_FAILED",
        field="query.start",
        dataset_version=PRED_VERSION,
    )


@pytest.fixture()
def silent_client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _boom(*_args, **_kwargs):
    raise RuntimeError("simulated internal failure")


# ---- 14c. 兜底 500 同样按接口类别选择数据身份 ----
def test_unhandled_error_on_observation_path_returns_obs_version(
    monkeypatch: pytest.MonkeyPatch, silent_client: TestClient
) -> None:
    from backend.app.services import service

    monkeypatch.setattr(service, "spatial_entities", _boom)
    body = assert_error_envelope(
        silent_client.get("/api/v1/spatial-entities").json(),
        status=500,
        code="INTERNAL_ERROR",
        dataset_version=OBS_VERSION,
    )
    assert body["message"] == "服务内部错误"


def test_unhandled_error_on_prediction_path_returns_pred_version(
    monkeypatch: pytest.MonkeyPatch, silent_client: TestClient
) -> None:
    from backend.app.services import service

    monkeypatch.setattr(service, "overview", _boom)
    assert_error_envelope(
        silent_client.get("/api/v1/dashboard/overview").json(),
        status=500,
        code="INTERNAL_ERROR",
        dataset_version=PRED_VERSION,
    )


# ---- 15. Provider 边界：配置未实现实现时拒绝启动/静默回退 ----
def test_provider_defaults_to_simulated_explicitly() -> None:
    from backend.app.providers import create_observation_provider, create_prediction_provider

    obs = create_observation_provider()
    pred = create_prediction_provider(obs)
    assert obs.name() == "simulated"
    assert obs.dataset_version() == OBS_VERSION
    assert pred.name() == "simulated"
    assert pred.dataset_version() == "DEMO-PRED-V1"
    assert pred.prediction_run_id() == "DEMO-RUN-V1"


@pytest.mark.parametrize(
    ("env", "value"),
    [("OBSERVATION_PROVIDER", "cleaned"), ("OBSERVATION_PROVIDER", "member_c"), ("OBSERVATION_PROVIDER", "typo")],
)
def test_observation_provider_without_implementation_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str
) -> None:
    from backend.app import providers

    monkeypatch.setenv(env, value)
    with pytest.raises(providers.ProviderConfigError) as excinfo:
        providers.create_observation_provider()
    assert "静默回退" in str(excinfo.value) or "simulated" in str(excinfo.value)


@pytest.mark.parametrize("value", ["cleaned", "member_c", "typo"])
def test_prediction_provider_without_implementation_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    from backend.app import providers

    monkeypatch.setenv("PREDICTION_PROVIDER", value)
    with pytest.raises(providers.ProviderConfigError):
        providers.create_prediction_provider(providers.create_observation_provider())


def test_provider_config_error_never_falls_back_to_simulated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app import providers

    monkeypatch.setenv("OBSERVATION_PROVIDER", "cleaned")
    with pytest.raises(providers.ProviderConfigError):
        providers.create_observation_provider()
    # 显式恢复 simulated 后可用
    monkeypatch.setenv("OBSERVATION_PROVIDER", "simulated")
    assert providers.create_observation_provider().name() == "simulated"


def test_capabilities_report_provider_status_honestly() -> None:
    caps = client.get("/api/v1/system/capabilities").json()["data"]
    assert caps["provider_status"] == {
        "observation_provider": "simulated",
        "prediction_provider": "simulated",
    }
    caps_map = caps["capabilities"]
    assert caps_map["real_time_warning_dispatch"] == "not_enabled"
    assert caps_map["long_term_forecast_30_90d"] == "blocked_auth"
    assert caps_map["historical_observation"] == "dataset_available_backend_pending"
    assert caps_map["demo_warning_dispatch"] == "available"
