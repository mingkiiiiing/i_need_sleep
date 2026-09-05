"""全部 /api/v1 路由：统一信封 + Pydantic 响应模型 + 稳定错误码。

兼容承诺：五个保留页面（首页/P01/P03/P07/历史复盘）当前消费的字段与键名
不得变动，详见 reports/audit7/frontend-api-consumers.md。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from . import schemas
from .contracts import (
    OBSERVATION_VERSION,
    PREDICTION_RUN_ID,
    PREDICTION_VERSION,
    MAX_TIMELINE_SPAN_DAYS,
    CLAIM_BOUNDARY,
    DATA_MODE,
    envelope,
)
from .errors import (
    capability_unavailable,
    entity_not_found,
    forecast_not_available,
    invalid_date_range,
    invalid_event_id,
    invalid_horizon,
    query_range_too_large,
    simulation_only,
)
from .services import service

router = APIRouter(prefix="/api/v1")

_HORIZONS = (1, 3, 7, 15, 30)


class HandleWarningRequest(BaseModel):
    event_id: str


def _ok(request: Request, data: Any, dataset_version: str, *, run: bool = False) -> dict[str, Any]:
    return envelope(
        request,
        data,
        dataset_version=dataset_version,
        prediction_run_id=PREDICTION_RUN_ID if run else None,
    )


def _require_entity(entity_id: str, *, dataset_version: str) -> None:
    if not service.observation.zone(entity_id):
        raise entity_not_found(
            "演示分区不存在",
            dataset_version=dataset_version,
            detail=f"spatial_entity_id={entity_id!r} 不是已注册的 demo_zone",
        )


def _require_horizon(horizon_days: int) -> None:
    if horizon_days not in _HORIZONS:
        raise invalid_horizon(
            "horizon_days 仅支持 1、3、7、15 或 30",
            detail=f"horizon_days={horizon_days} 不在支持档位 {list(_HORIZONS)} 中",
            dataset_version=PREDICTION_VERSION,
        )


def _parse_forecast_id(forecast_id: str) -> tuple[str, int] | None:
    parts = forecast_id.removeprefix("demo-forecast-").rsplit("-", 1)
    if len(parts) != 2:
        return None
    horizon_text = parts[1].removesuffix("d")
    if not horizon_text.isdigit():
        return None
    return parts[0], int(horizon_text)


# ---------- 首页 ----------


@router.get("/system/capabilities", response_model=schemas.Envelope[schemas.CapabilitiesData])
def get_capabilities(request: Request):
    return _ok(request, service.capabilities(), OBSERVATION_VERSION)


@router.get("/datasets/summary", response_model=schemas.Envelope[schemas.DatasetsSummaryData])
def get_datasets_summary(request: Request):
    return _ok(request, service.datasets_summary(), OBSERVATION_VERSION)


@router.get("/pipeline/runs/latest", response_model=schemas.Envelope[schemas.PipelineRunData])
def get_latest_pipeline_run(request: Request):
    return _ok(request, service.pipeline_latest(), OBSERVATION_VERSION)


@router.get("/dashboard/overview", response_model=schemas.Envelope[schemas.OverviewData])
def get_dashboard_overview(request: Request, mode: Literal["historical", "simulated"] = "simulated"):
    if mode == "historical":
        raise simulation_only("历史真实观测尚未接入业务 API；当前仅提供模拟演示总览", dataset_version=PREDICTION_VERSION)
    return _ok(request, service.overview(), PREDICTION_VERSION, run=True)


# ---------- 空间对象与观测（P03 / P07 / 历史复盘共用） ----------


@router.get("/spatial-entities", response_model=schemas.Envelope[list[schemas.SpatialEntity]])
def list_spatial_entities(
    request: Request,
    entity_type: str | None = None,
    mode: Literal["observed", "simulated"] = "simulated",
):
    if mode == "observed":
        raise simulation_only(
            "真实站点与历史观测尚未接入业务 API；当前仅提供 demo_zone 演示分区",
            dataset_version=OBSERVATION_VERSION,
        )
    return _ok(request, service.spatial_entities(entity_type), OBSERVATION_VERSION)


@router.get("/spatial-entities/{entity_id}", response_model=schemas.Envelope[schemas.SpatialEntity])
def get_spatial_entity(request: Request, entity_id: str):
    _require_entity(entity_id, dataset_version=OBSERVATION_VERSION)
    entity = next((item for item in service.spatial_entities() if item["id"] == entity_id), None)
    return _ok(request, entity, OBSERVATION_VERSION)


@router.get(
    "/spatial-entities/{entity_id}/observations",
    response_model=schemas.Envelope[list[schemas.ObservationRow]],
)
def get_observations(request: Request, entity_id: str, variable_code: str | None = None):
    _require_entity(entity_id, dataset_version=OBSERVATION_VERSION)
    return _ok(request, service.observation.observations(entity_id, variable_code), OBSERVATION_VERSION)


@router.get("/spatial-entities/{entity_id}/quality", response_model=schemas.Envelope[schemas.QualityReport])
def get_quality(request: Request, entity_id: str):
    _require_entity(entity_id, dataset_version=OBSERVATION_VERSION)
    return _ok(request, service.observation.quality(entity_id), OBSERVATION_VERSION)


# ---------- 预测（P03 / P07；T+30 能力阻塞） ----------


@router.get("/forecast-capabilities", response_model=schemas.Envelope[dict[str, str]])
def get_forecast_capabilities(request: Request):
    return _ok(request, service.capabilities()["capabilities"], PREDICTION_VERSION, run=True)


@router.get("/forecasts", response_model=schemas.Envelope[list[schemas.Forecast]])
def list_forecasts(
    request: Request,
    spatial_entity_id: str,
    horizon_days: int = Query(3),
    target_metric: str = "bloom_risk",
):
    _require_horizon(horizon_days)
    if horizon_days > 15:
        raise capability_unavailable(
            "30—90 天预测尚未就绪，不能返回演示算法结果作为正式预测",
            detail="T+30 分区预测被能力阻塞；风险地图的 T+30 演示格网请使用 /map/risk-grid",
            dataset_version=PREDICTION_VERSION,
        )
    _require_entity(spatial_entity_id, dataset_version=PREDICTION_VERSION)
    forecast = service.prediction.forecast(spatial_entity_id, horizon_days)
    if not forecast:
        raise forecast_not_available(
            "当前预测 Provider 无法提供该分区的预测结果",
            detail=f"provider={service.prediction.name()} 无法生成 {spatial_entity_id} 的 T+{horizon_days} 预测",
            dataset_version=PREDICTION_VERSION,
        )
    return _ok(request, [forecast], PREDICTION_VERSION, run=True)


@router.get("/forecasts/{forecast_id}", response_model=schemas.Envelope[schemas.Forecast])
def get_forecast(request: Request, forecast_id: str):
    parsed = _parse_forecast_id(forecast_id)
    if not parsed or not service.prediction.zone(parsed[0]):
        raise entity_not_found(
            "预测记录不存在",
            dataset_version=PREDICTION_VERSION,
            detail=f"forecast_id={forecast_id!r} 无法解析为已注册分区的预测记录",
        )
    entity_id, horizon_days = parsed
    if horizon_days > 15:
        raise capability_unavailable(
            "30—90 天预测尚未就绪，不能返回演示算法结果作为正式预测",
            detail="T+30 预测仅作为模拟预演数据存在于驾驶舱视图，正式预测接口对其能力阻塞",
            dataset_version=PREDICTION_VERSION,
        )
    forecast = service.prediction.forecast(entity_id, horizon_days)
    if not forecast:
        raise forecast_not_available(
            "当前预测 Provider 无法提供该预测记录",
            detail=f"provider={service.prediction.name()} 无法生成 {forecast_id}",
            dataset_version=PREDICTION_VERSION,
        )
    return _ok(request, forecast, PREDICTION_VERSION, run=True)


@router.get("/forecasts/{forecast_id}/explanations", response_model=schemas.Envelope[schemas.Explanation])
def get_explanation(request: Request, forecast_id: str):
    parsed = _parse_forecast_id(forecast_id)
    if not parsed or not service.prediction.zone(parsed[0]) or parsed[1] > 15:
        raise entity_not_found(
            "预测记录不存在，解释结果必须绑定已存在的 forecast",
            dataset_version=PREDICTION_VERSION,
            detail=f"forecast_id={forecast_id!r} 不是可解释的预测记录",
        )
    explanation = service.prediction.explanation(forecast_id)
    if not explanation:
        raise forecast_not_available(
            "当前预测 Provider 无法提供该预测记录的解释",
            detail=f"provider={service.prediction.name()} 无法解释 {forecast_id}",
            dataset_version=PREDICTION_VERSION,
        )
    return _ok(request, explanation, PREDICTION_VERSION, run=True)


# ---------- 地图（P07） ----------


@router.get("/map/layers", response_model=schemas.Envelope[list[schemas.MapLayer]])
def get_map_layers(request: Request):
    return _ok(
        request,
        [
            {
                "id": "demo-risk-grid",
                "layer_type": "simulated_scenario",
                "data_mode": DATA_MODE,
                "operational_use": False,
                "description": "演示风险格网，非监管决策用途",
            }
        ],
        PREDICTION_VERSION,
        run=True,
    )


def _grid_data(horizon_days: int) -> dict[str, Any]:
    data = service.prediction.risk_grid(horizon_days)
    data["layer_type"] = "simulated_scenario"
    data["operational_use"] = False
    data["capability_status"] = "long_term_forecast_blocked_simulation_only" if horizon_days == 30 else None
    return data


@router.get("/map/risk-grid", response_model=schemas.Envelope[schemas.RiskGridData])
def get_risk_grid(request: Request, horizon_days: int = Query(3)):
    _require_horizon(horizon_days)
    return _ok(request, _grid_data(horizon_days), PREDICTION_VERSION, run=True)


@router.get("/map/risk-polygons", response_model=schemas.Envelope[schemas.RiskPolygonsData])
def get_risk_polygons(request: Request, horizon_days: int = Query(3)):
    _require_horizon(horizon_days)
    return _ok(
        request,
        {
            "type": "FeatureCollection",
            "features": [],
            "horizon_days": horizon_days,
            "source": "simulated_grid",
            "empty_reason": (
                "演示风险格网不提供矢量面生成能力；为避免虚构湖岸边界、面积或迁移路径，"
                "本接口诚实返回空 FeatureCollection"
            ),
            "data_mode": DATA_MODE,
            "dataset_version": PREDICTION_VERSION,
            "prediction_run_id": PREDICTION_RUN_ID,
            "claim_boundary": CLAIM_BOUNDARY,
        },
        PREDICTION_VERSION,
        run=True,
    )


# ---------- 事件（规范源 + 兼容视图，共享稳定 ID） ----------


@router.get("/events", response_model=schemas.Envelope[list[schemas.CanonicalEvent]])
def get_events(request: Request):
    return _ok(request, service.canonical_events(), PREDICTION_VERSION, run=True)


# ---------- 驾驶舱兼容视图（P01 / 历史复盘） ----------


@router.get("/cockpit/time-stages", response_model=schemas.Envelope[list[schemas.TimeStage]])
def cockpit_time_stages(request: Request):
    return _ok(request, service.cockpit_time_stages(), PREDICTION_VERSION, run=True)


@router.get("/cockpit/points", response_model=schemas.Envelope[schemas.CockpitPointsData])
def cockpit_points(request: Request):
    return _ok(request, service.cockpit_points(), PREDICTION_VERSION, run=True)


@router.get("/cockpit/points/{entity_id}", response_model=schemas.Envelope[schemas.CockpitPoint])
def cockpit_point(request: Request, entity_id: str):
    _require_entity(entity_id, dataset_version=PREDICTION_VERSION)
    points = service.cockpit_points()["point_data"]
    if entity_id not in points:
        raise entity_not_found(
            "演示分区不存在",
            dataset_version=PREDICTION_VERSION,
            detail=f"entity_id={entity_id!r} 不是已注册的 demo_zone",
        )
    return _ok(request, points[entity_id], PREDICTION_VERSION, run=True)


@router.get("/cockpit/risk-heatmap", response_model=schemas.Envelope[schemas.HeatFieldData])
def cockpit_heatmap(request: Request):
    return _ok(request, service.cockpit_heat_field(), PREDICTION_VERSION, run=True)


@router.get("/cockpit/events", response_model=schemas.Envelope[list[schemas.CockpitEvent]])
def cockpit_events(request: Request):
    return _ok(request, service.cockpit_events(), PREDICTION_VERSION, run=True)


@router.get("/cockpit/region-summary", response_model=schemas.Envelope[schemas.RegionSummaryData])
def cockpit_region_summary(request: Request):
    return _ok(request, service.region_summary(), PREDICTION_VERSION, run=True)


@router.post("/cockpit/handle-warning", response_model=schemas.Envelope[schemas.HandleWarningData])
def cockpit_handle_warning(request: Request, payload: HandleWarningRequest):
    result = service.handle_warning(payload.event_id)
    if not result:
        raise invalid_event_id(
            "事件引用不存在",
            detail=(
                f"event_id={payload.event_id!r} 不是稳定事件 ID（demo-event-N）、演示分区 ID "
                "或演示格网编号（R01-C01 至 R11-C19）"
            ),
            dataset_version=PREDICTION_VERSION,
        )
    return _ok(request, result, PREDICTION_VERSION, run=True)


@router.get("/cockpit/timeline", response_model=schemas.Envelope[schemas.TimelineData])
def cockpit_timeline(request: Request, start: date, end: date):
    if end < start:
        raise invalid_date_range(
            "查询日期范围无效",
            field="start",
            detail=f"start={start.isoformat()} 不得晚于 end={end.isoformat()}",
            dataset_version=PREDICTION_VERSION,
        )
    if (end - start).days > MAX_TIMELINE_SPAN_DAYS:
        raise query_range_too_large(
            "查询范围过大",
            detail=f"start 与 end 跨度不得超过 {MAX_TIMELINE_SPAN_DAYS} 天（当前 {(end - start).days} 天）",
            dataset_version=PREDICTION_VERSION,
        )
    return _ok(request, service.timeline(start, end), PREDICTION_VERSION, run=True)
