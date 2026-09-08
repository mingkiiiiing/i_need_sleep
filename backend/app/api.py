"""全部 /api/v1 路由：统一信封 + Pydantic 响应模型 + 稳定错误码。

兼容承诺：五个保留页面（首页/P01/P03/P07/历史复盘）当前消费的字段与键名
不得变动，详见 reports/audit7/frontend-api-consumers.md。
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
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
    OBSERVED_DATA_MODE,
    REALTIME_CLAIM_BOUNDARY,
    REALTIME_VERSION,
    RS_AS_OF,
    RS_CLAIM_BOUNDARY,
    RS_DATA_MODE,
    RS_VERSION,
    envelope,
    observed_envelope,
)
from .errors import (
    capability_unavailable,
    entity_not_found,
    forecast_not_available,
    invalid_date_range,
    invalid_event_id,
    invalid_horizon,
    query_range_too_large,
    realtime_data_unavailable,
    simulation_only,
)
from .providers import RealtimeDataUnavailable
from .services import alert_engine, service

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


# ---- 实时观测轨（observed）辅助 ----


def _is_realtime_entity(entity_id: str) -> bool:
    return entity_id.startswith("mee-")


def _observed_as_of() -> str:
    try:
        return service.realtime.as_of() or REALTIME_VERSION
    except Exception:  # noqa: BLE001 — meta 展示字段不得因数据层异常失败
        return REALTIME_VERSION


def _observed_call(request: Request, fn, *args, **kwargs) -> dict[str, Any]:
    """执行实时轨取数：无数据 → 409 REALTIME_DATA_UNAVAILABLE（禁止回退模拟）。

    错误信封同样分轨：data_mode=observed + 实时 claim_boundary + 数据 as_of。
    """
    track = {
        "data_mode": OBSERVED_DATA_MODE,
        "claim_boundary": REALTIME_CLAIM_BOUNDARY,
        "as_of": _observed_as_of(),
    }
    try:
        data = fn(*args, **kwargs)
    except RealtimeDataUnavailable as exc:
        raise realtime_data_unavailable(
            "实时观测数据不可用：从未成功抓取；页面必须显式提示不可用",
            detail=str(exc),
            dataset_version=REALTIME_VERSION,
            **track,
        ) from exc
    except KeyError as exc:
        raise entity_not_found(
            "实时站点不存在",
            dataset_version=REALTIME_VERSION,
            detail=f"spatial_entity_id={exc.args[0]!r} 不在 MEE 实时站点目录中",
            **track,
        ) from exc
    return observed_envelope(request, data, dataset_version=REALTIME_VERSION, as_of=_observed_as_of())


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


@router.get(
    "/spatial-entities",
    response_model=schemas.Envelope[list[schemas.SpatialEntity | schemas.MonitoringStation]],
)
def list_spatial_entities(
    request: Request,
    entity_type: str | None = None,
    mode: Literal["observed", "simulated"] = "simulated",
    active: Literal["latest", "all"] = "latest",
    province: str | None = None,
    location_status: Literal["verified", "metadata_only", "suspicious", "missing"] | None = None,
):
    if mode == "observed":
        if entity_type and entity_type != "monitoring_station":
            return _ok(request, [], OBSERVATION_VERSION)
        return _observed_call(
            request,
            service.realtime_stations,
            active=active,
            province=province,
            location_status=location_status,
        )
    return _ok(request, service.spatial_entities(entity_type), OBSERVATION_VERSION)


@router.get("/realtime/status", response_model=schemas.Envelope[schemas.RealtimeStatus])
def get_realtime_status(request: Request):
    return _observed_call(request, service.realtime_status)


@router.get("/realtime/summary", response_model=schemas.Envelope[schemas.RealtimeSummary])
def get_realtime_summary(request: Request, snapshot: str | None = None):
    """全湖实时汇总（驾驶舱）：类别分布、蓝藻筛查预警、均值/短期趋势、透明加权健康分、地图点位。

    snapshot 参数用于真实快照回放（默认最新）。
    """
    return _observed_call(request, service.realtime_summary, snapshot)


@router.get("/realtime/timeline", response_model=schemas.Envelope[schemas.RealtimeTimeline])
def get_realtime_timeline(request: Request):
    """快照时间轴：每个成功快照的聚合状态，驱动驾驶舱回放条。"""
    return _observed_call(request, service.realtime_timeline)


@router.get("/realtime/alerts/overview", response_model=schemas.Envelope[schemas.AlertOverview])
def get_realtime_alerts_overview(request: Request):
    """预警总览（右上角通知组件数据源）：当前生效告警、通道配置状态、最近事件与投递回执。"""
    return _observed_call(request, alert_engine.overview)


@router.get("/realtime/alerts", response_model=schemas.Envelope[list[schemas.AlertEvent]])
def get_realtime_alerts(
    request: Request,
    status: Literal["active", "resolved", "all"] = "all",
    level: Literal["light", "moderate"] | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    """告警事件历史（/alerts 预警通知页数据源），含每通道投递状态与网关回执。"""
    data = alert_engine.store.list_alerts()
    if status != "all":
        data = [a for a in data if a.get("status") == status]
    if level:
        data = [a for a in data if a.get("level") == level]
    return _observed_call(request, lambda: data[:limit])


@router.post("/realtime/alerts/evaluate", response_model=schemas.Envelope[schemas.AlertEvaluation])
def post_realtime_alerts_evaluate(request: Request):
    """手动触发一次预警巡检（后台线程按 evaluate_interval_s 自动巡检）。"""
    return _observed_call(request, alert_engine.evaluate)


@router.get(
    "/spatial-entities/{entity_id}",
    response_model=schemas.Envelope[schemas.SpatialEntity | schemas.MonitoringStation],
)
def get_spatial_entity(request: Request, entity_id: str):
    if _is_realtime_entity(entity_id):
        return _observed_call(request, service.realtime_station, entity_id)
    _require_entity(entity_id, dataset_version=OBSERVATION_VERSION)
    entity = next((item for item in service.spatial_entities() if item["id"] == entity_id), None)
    return _ok(request, entity, OBSERVATION_VERSION)


@router.get(
    "/spatial-entities/{entity_id}/observations",
    response_model=schemas.Envelope[list[schemas.ObservationRow | schemas.StationObservationRow]],
)
def get_observations(
    request: Request,
    entity_id: str,
    variable_code: str | None = None,
    window: Literal["latest", "range"] = "latest",
    start: str | None = None,
    end: str | None = None,
    variables: str | None = None,
):
    if _is_realtime_entity(entity_id):
        track = {
            "data_mode": OBSERVED_DATA_MODE,
            "claim_boundary": REALTIME_CLAIM_BOUNDARY,
            "as_of": _observed_as_of(),
        }
        if window == "range":
            if not start or not end:
                raise invalid_date_range(
                    "window=range 需要 start 与 end（ISO 日期）",
                    dataset_version=REALTIME_VERSION,
                    **track,
                )
            try:
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            except ValueError as exc:
                raise invalid_date_range(f"日期格式无法解析: {exc}", dataset_version=REALTIME_VERSION, **track) from exc
            if span < 0:
                raise invalid_date_range("start 晚于 end", dataset_version=REALTIME_VERSION, **track)
            if span > MAX_TIMELINE_SPAN_DAYS:
                raise query_range_too_large(
                    f"查询跨度超过上限 {MAX_TIMELINE_SPAN_DAYS} 天",
                    dataset_version=REALTIME_VERSION,
                    **track,
                )
        variable_list = [item.strip() for item in variables.split(",") if item.strip()] if variables else None
        return _observed_call(
            request,
            service.realtime_observations,
            entity_id,
            window=window,
            start=start,
            end=end,
            variables=variable_list,
        )
    _require_entity(entity_id, dataset_version=OBSERVATION_VERSION)
    return _ok(request, service.observation.observations(entity_id, variable_code), OBSERVATION_VERSION)


@router.get(
    "/spatial-entities/{entity_id}/quality",
    response_model=schemas.Envelope[schemas.QualityReport | schemas.StationQuality],
)
def get_quality(request: Request, entity_id: str):
    if _is_realtime_entity(entity_id):
        return _observed_call(request, service.realtime_quality, entity_id)
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
            detail="T+30 分区预测被能力阻塞；情景格网已下线，历史观测请使用 /rs/manifest 遥感图层",
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
                "id": "rs-annual-chla",
                "layer_type": "satellite_retrieval",
                "data_mode": RS_DATA_MODE,
                "operational_use": False,
                "description": "THQBCA-V2 年度叶绿素 a 遥感反演图层（1984–2019，真实历史观测）",
            },
            {
                "id": "rs-annual-fac",
                "layer_type": "satellite_retrieval",
                "data_mode": RS_DATA_MODE,
                "operational_use": False,
                "description": "THQBCA-V2 年度漂浮藻类覆盖率反演图层（2003–2022，真实历史观测）",
            },
            {
                "id": "realtime-station-points",
                "layer_type": "station_observation",
                "data_mode": OBSERVED_DATA_MODE,
                "operational_use": False,
                "description": "MEE 国控站实时观测点位（observed）",
            },
        ],
        PREDICTION_VERSION,
        run=True,
    )


# ---------- 卫星遥感图层（P07；THQBCA-V2 年度反演产品） ----------


def _rs_overlays_dir() -> Path:
    override = os.environ.get("RS_OVERLAYS_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "rs_overlays", here / "rs_overlays"):
        if candidate.is_dir():
            return candidate
    return here.parent / "rs_overlays"


@router.get("/rs/manifest", response_model=schemas.Envelope[dict[str, Any]])
def get_rs_manifest(request: Request):
    manifest_path = _rs_overlays_dir() / "manifest.json"
    if not manifest_path.is_file():
        raise capability_unavailable(
            "遥感图层产物尚未生成：请先运行 data-cleaning/scripts/build_rs_overlays.py",
            detail=f"manifest 不存在：{manifest_path}",
            dataset_version=RS_VERSION,
            data_mode=RS_DATA_MODE,
            claim_boundary=RS_CLAIM_BOUNDARY,
            as_of=RS_AS_OF,
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise capability_unavailable(
            "遥感图层清单不可读",
            detail=f"{manifest_path}: {exc}",
            dataset_version=RS_VERSION,
            data_mode=RS_DATA_MODE,
            claim_boundary=RS_CLAIM_BOUNDARY,
            as_of=RS_AS_OF,
        ) from exc
    return envelope(
        request,
        data,
        dataset_version=RS_VERSION,
        data_mode=RS_DATA_MODE,
        as_of=RS_AS_OF,
        claim_boundary=RS_CLAIM_BOUNDARY,
    )


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
