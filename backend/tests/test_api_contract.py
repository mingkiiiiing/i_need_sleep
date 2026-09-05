"""第七任务收口：统一信封、数据身份与页面兼容契约测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

OBS_VERSION = "DEMO-OBS-V1"
PRED_VERSION = "DEMO-PRED-V1"
RUN_ID = "DEMO-RUN-V1"
META_KEYS = {"data_mode", "dataset_version", "prediction_run_id", "as_of", "claim_boundary", "request_id"}
ZONE_IDS = {
    "northwest_hotspot",
    "central_lake",
    "river_inlet",
    "southeast_station",
    "water_intake",
    "south_channel",
}
STAGES = ("t1", "t3", "t7", "t15", "t30")

# 全部保留接口（含五页面消费路径与遗留兼容路径）
GET_ENDPOINTS = [
    "/system/capabilities",
    "/datasets/summary",
    "/pipeline/runs/latest",
    "/dashboard/overview",
    "/spatial-entities",
    "/spatial-entities/northwest_hotspot",
    "/spatial-entities/northwest_hotspot/observations",
    "/spatial-entities/northwest_hotspot/quality",
    "/forecast-capabilities",
    "/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=3",
    "/forecasts/demo-forecast-northwest_hotspot-3d",
    "/forecasts/demo-forecast-northwest_hotspot-3d/explanations",
    "/map/layers",
    "/map/risk-grid?horizon_days=3",
    "/map/risk-polygons?horizon_days=3",
    "/events",
    "/cockpit/time-stages",
    "/cockpit/points",
    "/cockpit/points/northwest_hotspot",
    "/cockpit/risk-heatmap",
    "/cockpit/events",
    "/cockpit/region-summary",
    "/cockpit/timeline?start=2026-08-20&end=2026-08-22",
]


def assert_envelope(body: dict) -> None:
    assert body["code"] == 200
    assert body["message"] == "ok"
    assert body["errors"] == []
    assert set(body["meta"].keys()) == META_KEYS
    assert body["meta"]["data_mode"] == "simulated"
    assert body["meta"]["claim_boundary"] == "simulation_only"
    assert body["meta"]["as_of"] == "2026-08-24T08:00:00+08:00"
    assert body["meta"]["request_id"].startswith("req_")


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_all_endpoints_use_unified_envelope(path):
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_request_id_is_present_and_unique_across_requests():
    first = client.get("/api/v1/system/capabilities")
    second = client.get("/api/v1/system/capabilities")
    rid_a = first.json()["meta"]["request_id"]
    rid_b = second.json()["meta"]["request_id"]
    assert rid_a != rid_b
    assert first.headers["X-Request-Id"] == rid_a


def test_observation_and_prediction_dataset_versions_are_assigned_by_domain():
    observation_side = [
        "/system/capabilities",
        "/datasets/summary",
        "/pipeline/runs/latest",
        "/spatial-entities",
        "/spatial-entities/northwest_hotspot/observations",
        "/spatial-entities/northwest_hotspot/quality",
    ]
    prediction_side = [
        "/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=3",
        "/forecast-capabilities",
        "/map/risk-grid?horizon_days=3",
        "/events",
        "/cockpit/points",
        "/cockpit/region-summary",
        "/cockpit/timeline?start=2026-08-20&end=2026-08-22",
    ]
    for path in observation_side:
        body = client.get(f"/api/v1{path}").json()
        assert body["meta"]["dataset_version"] == OBS_VERSION, path
        assert body["meta"]["prediction_run_id"] is None, path
    for path in prediction_side:
        body = client.get(f"/api/v1{path}").json()
        assert body["meta"]["dataset_version"] == PRED_VERSION, path
        assert body["meta"]["prediction_run_id"] == RUN_ID, path


def test_risk_grids_have_fixed_shape_values_and_thresholds():
    for horizon in (1, 3, 7, 15, 30):
        body = client.get(f"/api/v1/map/risk-grid?horizon_days={horizon}").json()
        data = body["data"]
        grid = data["grid"]
        assert data["rows"] == 11
        assert data["columns"] == 19
        assert len(grid) == 11
        assert all(len(row) == 19 for row in grid)
        assert data["resolution"] == {"rows": 11, "columns": 19, "unit": "risk_score"}
        assert data["thresholds"] == {"low": [0, 44], "mid": [45, 74], "high": [75, 100]}
        flat = [value for row in grid for value in row]
        assert all(isinstance(value, int) and 0 <= value <= 100 for value in flat)
        assert data["prediction_run_id"] == RUN_ID
        assert data["data_mode"] == "simulated"
        if horizon == 30:
            assert data["capability_status"] == "long_term_forecast_blocked_simulation_only"
        else:
            assert data["capability_status"] is None


def test_risk_levels_are_consistent_across_endpoints():
    forecasts = {
        entity: client.get(
            f"/api/v1/forecasts?spatial_entity_id={entity}&horizon_days=3"
        ).json()["data"][0]
        for entity in ZONE_IDS
    }
    points = client.get("/api/v1/cockpit/points").json()["data"]["pointData"]
    events = client.get("/api/v1/cockpit/events").json()["data"]
    canonical_events = client.get("/api/v1/events").json()["data"]
    entities = {item["id"]: item for item in client.get("/api/v1/spatial-entities").json()["data"]}

    for entity in ZONE_IDS:
        level = forecasts[entity]["risk_level"]
        assert level in {"high", "mid", "low"}
        assert points[entity]["riskClass"] == level
        assert entities[entity]["risk_hint"] == level
        event_severities = [ev["severity"] for ev in events if ev["point"] == entity]
        assert event_severities == [level]
        assert [ev["severity"] for ev in canonical_events if ev["spatial_entity_id"] == entity] == [level]
        score = forecasts[entity]["risk_score"]
        expected = "high" if score >= 75 else "mid" if score >= 45 else "low"
        assert level == expected

    region = client.get("/api/v1/cockpit/region-summary").json()["data"]
    counts = {"high": 0, "mid": 0, "low": 0}
    for entity in ZONE_IDS:
        counts[forecasts[entity]["risk_level"]] += 1
        for stage in STAGES:
            day = int(stage[1:])
            if day <= 15:
                score = region["intensity"][entity][stage]
                level_of_score = "high" if score >= 75 else "mid" if score >= 45 else "low"
                forecast_by_day = client.get(
                    f"/api/v1/forecasts?spatial_entity_id={entity}&horizon_days={day}"
                ).json()["data"][0]
                assert level_of_score == forecast_by_day["risk_level"]
    assert region["riskCounts"] == counts
    assert region["totalStations"] == 6


def test_all_six_objects_are_demo_zones_everywhere():
    entities = client.get("/api/v1/spatial-entities").json()["data"]
    assert len(entities) == 6
    assert {item["entity_type"] for item in entities} == {"demo_zone"}
    assert {item["id"] for item in entities} == ZONE_IDS

    points = client.get("/api/v1/cockpit/points").json()["data"]
    assert set(points["pointData"].keys()) == ZONE_IDS
    assert set(points["pointPositions"].keys()) == ZONE_IDS

    region = client.get("/api/v1/cockpit/region-summary").json()["data"]
    assert set(region["intensity"].keys()) == ZONE_IDS

    for ev in client.get("/api/v1/events").json()["data"]:
        assert ev["spatial_entity_id"] in ZONE_IDS
    for ev in client.get("/api/v1/cockpit/events").json()["data"]:
        assert ev["point"] in ZONE_IDS


def test_home_capabilities_never_overstate_readiness():
    body = client.get("/api/v1/system/capabilities").json()["data"]
    caps = body["capabilities"]
    assert caps["historical_observation"] == "dataset_available_backend_pending"
    assert caps["short_term_forecast_1_3d"] == "dataset_ready_model_pending"
    assert caps["medium_term_forecast_7_15d"] == "dataset_ready_model_pending"
    assert caps["long_term_forecast_30_90d"] == "blocked_auth"
    assert caps["real_time_warning_dispatch"] == "not_enabled"
    assert caps["demo_warning_dispatch"] == "available"
    assert body["provider_status"] == {
        "observation_provider": "simulated",
        "prediction_provider": "simulated",
    }
    datasets = client.get("/api/v1/datasets/summary").json()["data"]["datasets"]
    assert [item["id"] for item in datasets] == [OBS_VERSION, PRED_VERSION]
    assert all(item["data_mode"] == "simulated" for item in datasets)
    pipeline = client.get("/api/v1/pipeline/runs/latest").json()["data"]
    assert pipeline["status"] == "simulated"


def test_openapi_schema_is_generated():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert len(schema["paths"]) >= 24
    for path in [
        "/api/v1/system/capabilities",
        "/api/v1/map/risk-grid",
        "/api/v1/forecasts",
        "/api/v1/events",
        "/api/v1/cockpit/handle-warning",
        "/api/v1/cockpit/timeline",
    ]:
        assert path in schema["paths"]


# ---------- 旧前端调用兼容（frontend-api-consumers.md 第 7 节） ----------


def test_cockpit_points_keeps_legacy_composite_shape_and_fields():
    body = client.get("/api/v1/cockpit/points").json()
    data = body["data"]
    assert set(data.keys()) == {"pointData", "pointPositions"}
    point = data["pointData"]["northwest_hotspot"]
    for key in ("id", "name", "short", "risk", "riskClass", "summary", "metrics", "forecast", "factors", "dataMode", "datasetVersion"):
        assert key in point, key
    assert point["dataMode"] == "simulated"
    assert point["datasetVersion"] == PRED_VERSION
    assert set(point["metrics"].keys()) == {"density", "chla", "phosphorus", "temp"}
    assert point["forecast"]["window"] == ["未来 1 天", "未来 3 天", "未来 7 天", "未来 15 天", "未来 30 天"]
    assert set(data["pointPositions"]["northwest_hotspot"].keys()) == {"top", "left"}


def test_cockpit_heatmap_keeps_stage_keys_for_lake_map():
    body = client.get("/api/v1/cockpit/risk-heatmap").json()["data"]
    for stage in STAGES:
        grid = body[stage]
        assert len(grid) == 11 and len(grid[0]) == 19
    assert body["_scenario"]["operational_use"] is False


def test_cockpit_events_kept_legacy_field_names_and_stable_ids():
    canonical = client.get("/api/v1/events").json()["data"]
    cockpit = client.get("/api/v1/cockpit/events").json()["data"]
    assert {ev["id"] for ev in canonical} == {ev["id"] for ev in cockpit}
    for ev in cockpit:
        for key in ("id", "time", "stageKey", "point", "title", "summary", "severity"):
            assert key in ev, key


def test_time_stages_expose_capability_status_for_ui_labels():
    stages = client.get("/api/v1/cockpit/time-stages").json()["data"]
    assert [s["key"] for s in stages] == list(STAGES)
    assert [s["days"] for s in stages] == [1, 3, 7, 15, 30]
    assert stages[4]["capability_status"] == "simulation_only"
    assert all(s["capability_status"] == "sample_interface_only" for s in stages[:4])


def test_legacy_forecast_endpoint_accepts_target_metric():
    body = client.get(
        "/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=3&target_metric=chlorophyll_a"
    ).json()
    assert body["data"][0]["target_metric"] == "bloom_risk"


def test_observation_rows_keep_consumed_columns():
    body = client.get("/api/v1/spatial-entities/northwest_hotspot/observations").json()
    row = body["data"][0]
    for key in (
        "spatial_entity_id",
        "observed_at",
        "variable_code",
        "clean_value",
        "unit",
        "value_origin",
        "quality_status",
        "is_imputed",
        "dataset_version",
    ):
        assert key in row, key
    assert all(item["value_origin"] == "simulated" for item in body["data"])


def test_air_temperature_proxy_is_flagged_row_by_row():
    rows = client.get("/api/v1/spatial-entities/northwest_hotspot/observations").json()["data"]
    air_rows = [row for row in rows if row["variable_code"] == "air_temperature"]
    other_rows = [row for row in rows if row["variable_code"] != "air_temperature"]
    assert air_rows and all(row["proxy_flag"] is True for row in air_rows)
    assert all(row["proxy_flag"] is False for row in other_rows)
    quality = client.get("/api/v1/spatial-entities/northwest_hotspot/quality").json()["data"]
    assert quality["proxy_flag"] is True
    assert quality["value_origin"] == "simulated"


def test_forecast_binds_dataset_identity_and_quality_gate():
    forecast = client.get(
        "/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=7"
    ).json()["data"][0]
    assert forecast["prediction_run_id"] == RUN_ID
    assert forecast["model_version"] == "DEMO-RULE-V1"
    assert forecast["provider_type"] == "simulation"
    assert forecast["claim_boundary"] == "simulation_only"
    assert forecast["quality_gate"]["status"] == "warning"
    assert forecast["quality_gate"]["decision"] == "candidate_assessment_only"
