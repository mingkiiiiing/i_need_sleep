from __future__ import annotations

from typing import Literal

from datetime import date, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .core import api_response, capability_unavailable, not_found, response_meta
from .demo_provider import CLAIM_BOUNDARY, FORECAST_VERSION, OBSERVATION_VERSION
from .services import service

router = APIRouter(prefix="/api/v1")


class SimulatedWarningHandleRequest(BaseModel):
    event_id: str


def simulated_meta(dataset_version: str = FORECAST_VERSION) -> dict:
    return response_meta(data_mode="simulated", dataset_version=dataset_version, claim_boundary=CLAIM_BOUNDARY)


@router.get("/system/capabilities")
def get_capabilities(): return api_response(service.capabilities(), meta=simulated_meta())

@router.get("/datasets/summary")
def get_datasets_summary(): return api_response(service.datasets_summary(), meta=simulated_meta())

@router.get("/pipeline/runs/latest")
def get_latest_pipeline_run(): return api_response({"run_id": "DEMO-PIPELINE-V1", "status": "simulated", "dataset_versions": [OBSERVATION_VERSION, FORECAST_VERSION]}, meta=simulated_meta())

@router.get("/dashboard/overview")
def get_dashboard_overview(mode: Literal["historical", "simulated"] = "simulated"): return api_response(service.overview(), meta=simulated_meta())

@router.get("/spatial-entities")
def list_spatial_entities(entity_type: str | None = None, mode: Literal["observed", "simulated"] = "simulated"): return api_response(service.spatial_entities(entity_type), meta=simulated_meta())

@router.get("/spatial-entities/{entity_id}")
def get_spatial_entity(entity_id: str):
    entity = next((item for item in service.spatial_entities() if item["id"] == entity_id), None)
    if not entity: raise not_found("SPATIAL_ENTITY_NOT_FOUND", "空间对象不存在")
    return api_response(entity, meta=simulated_meta())

@router.get("/spatial-entities/{entity_id}/observations")
def get_observations(entity_id: str, variable_code: str | None = None):
    if not service.provider.zone(entity_id): raise not_found("SPATIAL_ENTITY_NOT_FOUND", "空间对象不存在")
    return api_response(service.provider.observations(entity_id, variable_code), meta=simulated_meta(OBSERVATION_VERSION))

@router.get("/spatial-entities/{entity_id}/quality")
def get_quality(entity_id: str):
    if not service.provider.zone(entity_id): raise not_found("SPATIAL_ENTITY_NOT_FOUND", "空间对象不存在")
    return api_response(service.quality(entity_id), meta=simulated_meta(OBSERVATION_VERSION))

@router.get("/forecast-capabilities")
def get_forecast_capabilities(): return api_response(service.capabilities()["capabilities"], meta=simulated_meta())

@router.get("/forecasts")
def list_forecasts(spatial_entity_id: str, horizon_days: int = Query(3)):
    if horizon_days > 15: raise capability_unavailable("30—90 天预测尚未就绪，不能返回演示算法结果作为正式预测")
    forecast = service.provider.forecast(spatial_entity_id, horizon_days)
    if not forecast: raise not_found("SPATIAL_ENTITY_NOT_FOUND", "空间对象不存在")
    return api_response([forecast], meta=simulated_meta())

@router.get("/forecasts/{forecast_id}")
def get_forecast(forecast_id: str):
    explanation = service.provider.explanation(forecast_id)
    if not explanation: raise not_found("FORECAST_NOT_FOUND", "预测记录不存在")
    entity_id = forecast_id.removeprefix("demo-forecast-").rsplit("-", 1)[0]
    horizon = int(forecast_id.rsplit("-", 1)[1].removesuffix("d"))
    return api_response(service.provider.forecast(entity_id, horizon), meta=simulated_meta())

@router.get("/forecasts/{forecast_id}/explanations")
def get_explanation(forecast_id: str):
    explanation = service.provider.explanation(forecast_id)
    if not explanation: raise not_found("FORECAST_NOT_FOUND", "预测记录不存在")
    return api_response(explanation, meta=simulated_meta())

@router.get("/map/layers")
def get_map_layers(): return api_response([{"id": "demo-risk-grid", "layer_type": "simulated_scenario", "data_mode": "simulated", "operational_use": False, "description": "演示风险格网，非监管决策用途"}], meta=simulated_meta())

@router.get("/map/risk-grid")
def get_risk_grid(horizon_days: int = Query(3)): return api_response(service.risk_grid(horizon_days), meta=simulated_meta())

@router.get("/map/risk-polygons")
def get_risk_polygons(horizon_days: int = Query(3)):
    grid = service.risk_grid(horizon_days)
    return api_response({"type": "FeatureCollection", "features": [], "source": "simulated_grid", "horizon_days": grid["horizon_days"]}, meta=simulated_meta())

@router.get("/events")
def get_events():
    events = [{"id": f"demo-event-{index}", "event_type": "model", "occurred_at": f"2026-08-{16 + index:02d}T09:00:00+08:00", "spatial_entity_id": zone["id"], "title": "演示预测运行", "data_mode": "simulated", "prediction_run_id": "DEMO-RUN-V1"} for index, zone in enumerate(service.provider.zones)]
    return api_response(events, meta=simulated_meta())

# Existing cockpit pages consume these P0 compatibility views. They expose the same simulated provenance.
@router.get("/cockpit/time-stages")
def cockpit_time_stages(): return api_response([{"key": f"t{day}", "label": f"T+{day} 天", "short": f"T+{day}d", "days": day, "index": index} for index, day in enumerate([1, 3, 7, 15, 30])], meta=simulated_meta())

@router.get("/cockpit/points")
def cockpit_points():
    data = {}
    positions = {}
    for zone in service.provider.zones:
        forecast = service.provider.forecast(zone["id"], 3)
        risk_class = forecast["risk_level"]
        data[zone["id"]] = {"id": zone["id"], "name": zone["name"], "short": zone["short"], "risk": "SIMULATED / " + {"high": "红色演示", "mid": "橙色演示", "low": "绿色演示"}[risk_class], "riskClass": risk_class, "summary": "演示业务分区，非真实站点、非决策用途。", "metrics": {"density": "SIMULATED", "chla": "experimental / unavailable", "phosphorus": "SIMULATED", "temp": "air temperature proxy"}, "forecast": {"window": ["未来 1 天", "未来 3 天", "未来 7 天", "未来 15 天", "未来 30 天"], "title": ["演示研判"] * 5, "text": ["SIMULATED / 非决策用途"] * 5}, "factors": [{"name": item["label"], "value": round(item["contribution"] * 100)} for item in service.provider.explanation(forecast["id"])["features"]], "trend": [forecast["risk_score"]] * 24, "timeline": [["2026-08-21", "演示数据", "固定种子模拟，不代表真实事件。"]], "explainability": service.provider.explanation(forecast["id"])["features"], "dataMode": "simulated", "datasetVersion": FORECAST_VERSION}
        positions[zone["id"]] = zone["position"]
    return api_response({"pointData": data, "pointPositions": positions}, meta=simulated_meta())

@router.get("/cockpit/points/{entity_id}")
def cockpit_point(entity_id: str):
    response = cockpit_points()["data"]["pointData"].get(entity_id)
    if not response: raise not_found("SPATIAL_ENTITY_NOT_FOUND", "空间对象不存在")
    return api_response(response, meta=simulated_meta())

@router.get("/cockpit/risk-heatmap")
def cockpit_heatmap(): return api_response({f"t{day}": service.risk_grid(day)["grid"] for day in [1, 3, 7, 15, 30]}, meta=simulated_meta())

@router.get("/cockpit/events")
def cockpit_events():
    return api_response([{"id": f"demo-event-{index}", "time": f"08-{16 + index:02d} 09:00", "stageKey": f"t{[1, 3, 7, 15, 30][index % 5]}", "point": zone["id"], "title": "演示预测运行", "summary": "SIMULATED / 非决策用途", "severity": zone["risk"]} for index, zone in enumerate(service.provider.zones)], meta=simulated_meta())

@router.get("/cockpit/region-summary")
def cockpit_region_summary():
    points = service.provider.zones
    return api_response({"totalStations": len(points), "riskCounts": {"high": 1, "mid": 3, "low": 2}, "intensity": {zone["id"]: {f"t{day}": service.provider.forecast(zone["id"], day)["risk_score"] for day in [1, 3, 7, 15, 30]} for zone in points}, "data_mode": "simulated"}, meta=simulated_meta())


@router.post("/cockpit/handle-warning")
def cockpit_handle_warning(payload: SimulatedWarningHandleRequest):
    return api_response({"event_id": payload.event_id, "status": "simulated_dispatched", "channels": ["platform_simulation"], "data_mode": "simulated", "claim_boundary": CLAIM_BOUNDARY}, meta=simulated_meta())


@router.get("/cockpit/timeline")
def cockpit_timeline(start: date, end: date):
    if end < start or (end - start).days > 90:
        return api_response({"start_date": start.isoformat(), "end_date": end.isoformat(), "total_days": 0, "data": []}, meta=simulated_meta())
    days = (end - start).days + 1
    values = []
    for index in range(days):
        current = start + timedelta(days=index)
        score = 34 + (index * 7) % 38
        values.append({"date": current.isoformat(), "avg_chlorophyll": score, "risk_level": "high" if score >= 65 else "mid" if score >= 45 else "low", "data_mode": "simulated"})
    return api_response({"start_date": start.isoformat(), "end_date": end.isoformat(), "total_days": days, "data": values}, meta=simulated_meta())
