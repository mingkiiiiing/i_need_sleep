"""全部 /api/v1 路由：统一信封 + Pydantic 响应模型 + 稳定错误码。

兼容承诺：五个保留页面（首页/P01/P03/P07/历史复盘）当前消费的字段与键名
不得变动，详见 reports/audit7/frontend-api-consumers.md。
"""
from __future__ import annotations

import json
import os
import re
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
    ApiError,
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
from .station_forecast import StationForecastNotAvailable
from .alert_center import CenterInvalidOperation, CenterNotFound, alert_center
from .history_review import history_review
from .services import alert_engine, service
from .algorithm_models import (
    AlgorithmModelUnavailable,
    CLAIM_BOUNDARY as ALGORITHM_CLAIM_BOUNDARY,
    DATA_VERSION as ALGORITHM_DATA_VERSION,
    CLAIM_BOUNDARY_V3 as ALGORITHM_CLAIM_BOUNDARY_V3,
    DATA_VERSION_V3 as ALGORITHM_DATA_VERSION_V3,
    SUPPORTED_HORIZONS as ALGORITHM_HORIZONS,
)

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
    except StationForecastNotAvailable as exc:
        raise forecast_not_available(
            "站点级预测不可用（该站在数据窗口内无叶绿素a 序列或模型门槛未通过）",
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
    return _observed_call(request, alert_center.evaluate_and_sync)


# ---------- 预警与应急预案中心（事件处置层；触发判定仍在 alerts.py 引擎） ----------


def _center_call(request: Request, fn) -> dict[str, Any]:
    """预警中心统一包装：先翻译业务异常（404/422），再走 observed 信封。"""
    try:
        data = fn()
    except CenterNotFound as exc:
        raise entity_not_found(
            "预警事件或引用对象不存在",
            dataset_version=REALTIME_VERSION,
            detail=str(exc.args[0]) if exc.args else None,
        ) from exc
    except CenterInvalidOperation as exc:
        raise invalid_event_id(
            str(exc),
            dataset_version=REALTIME_VERSION,
        ) from exc
    return _observed_call(request, lambda: data)


class CenterActionRequest(BaseModel):
    action: str
    actor: str | None = None
    assignee: str | None = None
    reason: str | None = None
    comment: str | None = None


class CenterPushRequest(BaseModel):
    channels: list[str]
    groups: list[str]
    subject: str | None = None
    body: str | None = None
    actor: str | None = None


class CenterPlanRequest(BaseModel):
    plan_id: str
    actor: str | None = None


class CenterTaskRequest(BaseModel):
    status: Literal["todo", "doing", "done"]
    note: str | None = None
    actor: str | None = None


class CenterRulesRequest(BaseModel):
    notify: dict[str, bool] | None = None
    auto_simulate_push: dict[str, Any] | None = None
    predicted: dict[str, Any] | None = None


class CenterReadRequest(BaseModel):
    ids: list[str] | None = None
    all: bool = False


class ReviewNotesRequest(BaseModel):
    fields: dict[str, Any]
    editor: str | None = None


@router.get("/realtime/alerts/center", response_model=schemas.Envelope[dict])
def get_alert_center(
    request: Request,
    type: Literal["all", "realtime", "predicted"] = "all",
    status: Literal["all", "pending", "acknowledged", "processing", "review", "closed", "revoked"] = "all",
    search: str = "",
):
    """预警中心总览：统计卡、事件列表（实时/预测同列分标签）、预案库、规则、站内通知。"""
    return _observed_call(
        request,
        alert_center.overview,
        event_filter=type,
        status_filter=status,
        search=search,
    )


@router.get("/realtime/alerts/center/events/{event_id}", response_model=schemas.Envelope[dict])
def get_alert_center_event(request: Request, event_id: str):
    """预警事件详情：证据、处理记录、措施任务、模拟推送回执。"""
    return _center_call(request, lambda: alert_center.event_detail_or_404(event_id))


@router.post("/realtime/alerts/center/events/{event_id}/actions", response_model=schemas.Envelope[dict])
def post_alert_center_action(request: Request, event_id: str, body: CenterActionRequest):
    """事件工作流动作：确认/指派/开始处置/提交复核/关闭/重开/撤销（状态机见 alert_center）。"""
    return _center_call(request, lambda: alert_center.action_or_404(event_id, body.action, body.model_dump()))


@router.post("/realtime/alerts/center/events/{event_id}/push", response_model=schemas.Envelope[dict])
def post_alert_center_push(request: Request, event_id: str, body: CenterPushRequest):
    """短信/邮件模拟推送：生成模拟回执并留痕，绝不实际发送。"""
    return _center_call(request, lambda: alert_center.push_or_404(event_id, body.model_dump()))


@router.post("/realtime/alerts/center/events/{event_id}/plan", response_model=schemas.Envelope[dict])
def post_alert_center_plan(request: Request, event_id: str, body: CenterPlanRequest):
    """采用应急预案：复制该版本措施为事件任务，后续预案库更新不影响已生成任务。"""
    return _center_call(request, lambda: alert_center.adopt_plan_or_404(event_id, body.plan_id, body.model_dump()))


@router.post(
    "/realtime/alerts/center/events/{event_id}/tasks/{task_id}",
    response_model=schemas.Envelope[dict],
)
def post_alert_center_task(request: Request, event_id: str, task_id: str, body: CenterTaskRequest):
    """更新措施任务进展。"""
    return _center_call(request, lambda: alert_center.task_or_404(event_id, task_id, body.model_dump()))


@router.get("/realtime/alerts/center/records", response_model=schemas.Envelope[dict])
def get_alert_center_records(request: Request):
    """处理记录 / 模拟推送记录 / 操作审计（最近优先）。"""
    return _observed_call(request, alert_center.records_view)


@router.get("/realtime/alerts/center/notifications", response_model=schemas.Envelope[dict])
def get_alert_center_notifications(request: Request, unread_only: bool = False):
    """站内通知（铃铛通知中心数据源）：已读状态按用户独立保存。"""
    return _observed_call(request, lambda: alert_center.notifications_view(unread_only=unread_only))


@router.post("/realtime/alerts/center/notifications/read", response_model=schemas.Envelope[dict])
def post_alert_center_notifications_read(request: Request, body: CenterReadRequest):
    """标记通知已读：单批 ids 或全部（只影响当前用户）。"""
    return _observed_call(request, lambda: alert_center.mark_notifications_read(body.ids, all=body.all))


@router.post("/realtime/alerts/center/rules", response_model=schemas.Envelope[dict])
def post_alert_center_rules(request: Request, body: CenterRulesRequest):
    """更新预警中心可配置项：通知策略、自动模拟推送、预测预留参数（实测阈值口径只读）。"""
    return _observed_call(request, lambda: alert_center.update_rules(body.model_dump(exclude_none=True)))


# ---------- 历史复盘（事件复盘聚合；以 event_id 为主关联键，只读组合已有事实） ----------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_history_dates(start: str, end: str) -> None:
    for name, value in (("start", start), ("end", end)):
        if value and not _DATE_RE.match(value):
            raise invalid_date_range(
                f"{name} 须为 YYYY-MM-DD 日期",
                field=name,
                detail=f"{name}={value!r} 不是合法日期格式",
                dataset_version=REALTIME_VERSION,
            )
    if start and end and start > end:
        raise invalid_date_range(
            "开始日期晚于结束日期",
            field="start",
            detail=f"start={start} 晚于 end={end}",
            dataset_version=REALTIME_VERSION,
        )


@router.get("/history/reviews", response_model=schemas.Envelope[dict])
def get_history_reviews(
    request: Request,
    start: str = "",
    end: str = "",
    type: Literal["all", "realtime", "predicted"] = "all",
    level: Literal["all", "light", "moderate"] = "all",
    status: Literal["all", "pending", "acknowledged", "processing", "review", "closed", "revoked"] = "all",
    station: str = "",
    plan_adopted: Literal["all", "yes", "no"] = "all",
    tasks_done: Literal["all", "yes", "no"] = "all",
    push_failed: Literal["all", "yes", "no"] = "all",
):
    """历史事件复盘列表：全局统计 + 按条件筛选的事件简况（响应/处置耗时、预案/任务/推送计数）。"""
    _validate_history_dates(start, end)
    return _observed_call(
        request,
        history_review.list_reviews,
        start=start, end=end, type=type, level=level, status=status, station=station,
        plan_adopted=plan_adopted, tasks_done=tasks_done, push_failed=push_failed,
    )


@router.get("/history/metrics", response_model=schemas.Envelope[dict])
def get_history_metrics(request: Request):
    """历史复盘全局指标：关闭率（分子/分母）、平均响应/处置时长（含样本数）与统计口径。"""
    return _observed_call(request, history_review.history_metrics)


@router.get("/history/prediction-evaluations", response_model=schemas.Envelope[dict])
def get_history_prediction_evaluations(request: Request):
    """预测评估：正式预测接入前的诚实空态（可验证样本、指标定义与接入条件）。"""
    return _observed_call(request, history_review.prediction_evaluations)


@router.get("/history/reviews/{event_id}", response_model=schemas.Envelope[dict])
def get_history_review_detail(request: Request, event_id: str):
    """事件复盘聚合详情：里程碑时间线、观测证据、预案执行、通知推送、响应指标与复盘意见。"""
    return _center_call(request, lambda: history_review.review_detail(event_id))


@router.get("/history/reviews/{event_id}/timeline", response_model=schemas.Envelope[dict])
def get_history_review_timeline(request: Request, event_id: str):
    """事件全过程时间线：按当时内容组织的里程碑节点（颜色语义见 tone 字段）。"""
    return _center_call(request, lambda: history_review.review_timeline(event_id))


@router.get("/history/reviews/{event_id}/evidence", response_model=schemas.Envelope[dict])
def get_history_review_evidence(request: Request, event_id: str):
    """事件观测证据：触发前后指标序列（缺测断开不插值）、阈值线与证据节点。"""
    return _center_call(request, lambda: history_review.review_evidence(event_id))


@router.put("/history/reviews/{event_id}/review-notes", response_model=schemas.Envelope[dict])
def put_history_review_notes(request: Request, event_id: str, body: ReviewNotesRequest):
    """保存人工复盘意见（与系统证据分离存储）：记录编辑人、保存时间并递增版本。"""
    return _center_call(
        request,
        lambda: history_review.save_review_notes(event_id, body.fields, body.editor),
    )


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


# ---------- 站点级机理+AI 融合预测（observed 轨，v0.1 试点） ----------


@router.get("/realtime/stations/{entity_id}/forecast", response_model=schemas.Envelope[dict])
def get_realtime_station_forecast(request: Request, entity_id: str):
    """站点级短期预测（成员C 机理+AI 融合框架 v0.1）。

    仅覆盖数据窗口内有叶绿素a 观测序列的站点；无序列 → 409 FORECAST_NOT_AVAILABLE。
    模型卡（训练窗口/样本量/交叉验证指标/被阻塞提前期）随响应返回，页面必须披露。
    """
    return _observed_call(request, service.realtime_station_forecast, entity_id)


@router.get("/realtime/forecast/status", response_model=schemas.Envelope[dict])
def get_realtime_station_forecast_status(request: Request):
    """站点级预测引擎状态：覆盖站点数、服务/阻塞提前期与原因（能力披露）。"""
    return _observed_call(request, service.realtime_station_forecast_status)


# ---------- 预测（P03 / P07；T+30 能力阻塞） ----------


@router.get("/model/status", response_model=schemas.Envelope[dict])
def get_algorithm_model_status(request: Request):
    """63 模型交付包运行状态与声明边界。"""
    data = service.algorithm_model_status()
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY,
    )


@router.get("/model/predictions", response_model=schemas.Envelope[dict])
def get_algorithm_predictions(
    request: Request,
    horizon_days: int = Query(3),
    entity_id: str = "lake",
    focus_metric: Literal["risk", "chla", "area", "biomass", "density"] = "risk",
):
    """交付包 V0.2 全任务预测；支持全湖 MEE 汇总或单个 MEE 站点输入。"""
    if horizon_days not in ALGORITHM_HORIZONS:
        raise invalid_horizon(
            "算法模型仅支持 1、3、7、15、30、60、90 天",
            detail=f"horizon_days={horizon_days} 不在 {list(ALGORITHM_HORIZONS)} 中",
            dataset_version=ALGORITHM_DATA_VERSION,
        )
    try:
        data = service.algorithm_predictions(horizon_days, entity_id, focus_metric)
    except KeyError as exc:
        raise entity_not_found(
            "实时站点不存在",
            dataset_version=ALGORITHM_DATA_VERSION,
            detail=f"entity_id={exc.args[0]!r} 不在 MEE 实时站点目录中",
        ) from exc
    except AlgorithmModelUnavailable as exc:
        raise capability_unavailable(
            "算法模型运行包当前不可用",
            detail=str(exc),
            dataset_version=ALGORITHM_DATA_VERSION,
        ) from exc
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=data["prediction_run_id"],
        data_mode="hybrid",
        as_of=data.get("issued_at") or _observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY,
    )


@router.get("/model/acceptance", response_model=schemas.Envelope[dict])
def get_algorithm_acceptance(request: Request):
    """冻结测试口径下的 10% 提升门禁；失败状态必须原样返回。"""
    data = service.algorithm_acceptance()
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=None,
        data_mode="simulated",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY,
    )


@router.get("/model/spatial-field", response_model=schemas.Envelope[dict])
def get_algorithm_spatial_field(
    request: Request,
    horizon_days: int = Query(3),
    metric: Literal["risk", "chla", "area", "biomass"] = "risk",
    layer: Literal["model", "raster"] = "model",
    run_id: str | None = Query(None),
):
    """太湖范围内空间场：layer=model（legacy 站点样点）或 layer=raster（V0.3 连续栅格）。

    run_id 用于把空间场挂到同一次 predict_suite 运行（共享 prediction_run_id 前缀）。
    """
    if horizon_days not in ALGORITHM_HORIZONS:
        raise invalid_horizon(
            "算法空间推演仅支持 1、3、7、15、30、60、90 天",
            detail=f"horizon_days={horizon_days} 不在 {list(ALGORITHM_HORIZONS)} 中",
            dataset_version=ALGORITHM_DATA_VERSION,
        )
    if layer == "raster":
        data = _v3_algorithm_call(
            lambda: service.algorithm_spatial_field_v3(horizon_days, metric, "raster", run_id)
        )
    else:
        data = service.algorithm_spatial_field(horizon_days, metric)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=data["prediction_run_id"],
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY,
    )


def _v3_algorithm_call(fn) -> dict[str, Any]:
    """V0.3 包统一异常翻译：包缺失 → 409，非法输入 → 422，站点不存在 → 404。"""
    try:
        return fn()
    except AlgorithmModelUnavailable as exc:
        raise capability_unavailable(
            "V0.3 算法运行包当前不可用",
            detail=str(exc),
            dataset_version=ALGORITHM_DATA_VERSION_V3,
        ) from exc
    except KeyError as exc:
        raise entity_not_found(
            "实时站点不存在",
            dataset_version=ALGORITHM_DATA_VERSION_V3,
            detail=f"entity_id={exc.args[0]!r} 不在 MEE 实时站点目录中",
        ) from exc
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
            message="请求参数不在 V0.3 支持范围内",
            detail=str(exc),
            dataset_version=ALGORITHM_DATA_VERSION_V3,
        ) from exc


@router.get("/model/v3/status", response_model=schemas.Envelope[dict])
def get_algorithm_model_status_v3(request: Request):
    """V0.3 真实数据包状态：78 字段契约、月度标签粒度披露与 legacy 对照。"""
    data = _v3_algorithm_call(service.algorithm_model_status_v3)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/predictions", response_model=schemas.Envelope[dict])
def get_algorithm_predictions_v3(
    request: Request,
    horizon_days: int = Query(3),
    entity_id: str = "lake",
    focus_metric: Literal["risk", "chla", "area", "biomass", "density"] = "risk",
):
    """V0.3 全任务预测：月度标签粒度 + conformal P05/P95 区间；30/60/90 天携带“情景推演”锁定标记。"""
    data = _v3_algorithm_call(
        lambda: service.algorithm_predictions_v3(horizon_days, entity_id, focus_metric)
    )
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data["prediction_run_id"],
        data_mode="hybrid",
        as_of=data.get("issued_at") or _observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/prediction-status", response_model=schemas.Envelope[dict])
def get_prediction_snapshot_status(request: Request):
    """预测快照状态（轻量）：前端轮询此接口比对 prediction_snapshot_id，不触发任何推理。"""
    data = _v3_algorithm_call(service.prediction_snapshot_status)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data.get("prediction_snapshot_id"),
        data_mode="hybrid",
        as_of=data.get("generated_at") or _observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.post("/model/v3/prediction-snapshot/rebuild", response_model=schemas.Envelope[dict])
def rebuild_prediction_snapshot(request: Request):
    """管理员主动重算：丢弃当前版本缓存产物，后台强制重新推理全部时效与站点。

    版本键不变也重算——用于代码口径修复后版本键看不见代码变更的场景。
    期间继续服务当前已发布快照，新结果通过完整性校验后才原子切换。
    """
    data = _v3_algorithm_call(service.prediction_snapshot_rebuild)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data.get("published_prediction_snapshot_id"),
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/prediction-snapshot", response_model=schemas.Envelope[dict])
def get_prediction_snapshot(
    request: Request,
    entity_id: str = "lake",
    focus_metric: Literal["risk", "chla", "area", "biomass", "density"] = "risk",
):
    """一次读取全部时效结果与版本状态：页面打开即有结果，切换时效不再运行模型。"""
    data = _v3_algorithm_call(lambda: service.prediction_snapshot_view(entity_id, focus_metric))
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data.get("prediction_snapshot_id"),
        data_mode="hybrid",
        as_of=data.get("generated_at") or _observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/prediction-spatial-field", response_model=schemas.Envelope[dict])
def get_prediction_station_field(
    request: Request,
    horizon_days: int = Query(3),
    metric: Literal["risk", "chla", "biomass", "density"] = "risk",
):
    """快照驱动的站点空间场：与结果面板同一 prediction_snapshot_id，覆盖分母=快照站点层总数。

    区别于 /model/spatial-field（legacy V0.2 合成站点场）：本接口逐站给出数值或缺失原因，
    仅缺可信坐标的站不绘制，且坐标缺失原因逐站披露。
    """
    data = _v3_algorithm_call(lambda: service.prediction_station_field(horizon_days, metric))
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data.get("prediction_snapshot_id"),
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/driver-distribution", response_model=schemas.Envelope[dict])
def get_prediction_driver_distribution(
    request: Request,
    horizon_days: int = Query(1),
):
    """全湖驱动因素分布：79 站机理净生长率分解的站间分布（环境状态口径，非模型贡献排序）。"""
    data = _v3_algorithm_call(lambda: service.prediction_driver_distribution(horizon_days))
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=data.get("prediction_snapshot_id"),
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/v3/acceptance", response_model=schemas.Envelope[dict])
def get_algorithm_acceptance_v3(request: Request):
    """V0.3 10% 门禁汇总（唯一来源 gate_table.json，实时生成；N.A. 如实披露）。"""
    data = _v3_algorithm_call(service.algorithm_acceptance_v3)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/acceptance/detail", response_model=schemas.Envelope[dict])
def get_algorithm_acceptance_detail(request: Request):
    """V0.3 10% 门禁逐行明细：任务 × 变体 × 时效，含 n_test、指标与 NA 原因。"""
    data = _v3_algorithm_call(service.algorithm_acceptance_detail)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/calibration/coverage", response_model=schemas.Envelope[dict])
def get_algorithm_calibration_coverage(request: Request):
    """V0.3 conformal 区间覆盖率元数据（目标 90%，冻结测试集经验覆盖率如实披露）。"""
    data = _v3_algorithm_call(service.algorithm_calibration_coverage)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/rs/retrieval/validation", response_model=schemas.Envelope[dict])
def get_rs_retrieval_validation(request: Request):
    """V0.3 遥感反演地面配对校准的留出验证证据（R²/RMSE 可为负，如实披露）。"""
    data = _v3_algorithm_call(service.retrieval_validation)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="derived",
        as_of=_observed_as_of(),
        claim_boundary="retrieval_calibration_development_evidence_only",
    )


@router.get("/acceptance/overview", response_model=schemas.Envelope[dict])
def get_acceptance_overview(request: Request):
    """V0.3 达标看板聚合：P0-1..P0-6 六项达标状态与证据链接。"""
    data = _v3_algorithm_call(service.acceptance_overview)
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION_V3,
        prediction_run_id=None,
        data_mode="hybrid",
        as_of=_observed_as_of(),
        claim_boundary=ALGORITHM_CLAIM_BOUNDARY_V3,
    )


@router.get("/model/retrieval/status", response_model=schemas.Envelope[dict])
def get_remote_retrieval_status(request: Request):
    """藻类参数反演与校准链的当前真实能力。"""
    data = service.remote_retrieval_status()
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=None,
        data_mode="derived",
        as_of=_observed_as_of(),
        claim_boundary="experimental_remote_retrieval_only",
    )


@router.post("/model/retrieval/calibrate", response_model=schemas.Envelope[dict])
def calibrate_remote_retrieval(request: Request, payload: dict[str, Any]):
    """用同期地面配对拟合仿射校准并应用到待校准反演值。"""
    try:
        data = service.calibrate_remote_retrieval(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
            message="遥感反演校准输入无效",
            detail=str(exc),
            dataset_version=ALGORITHM_DATA_VERSION,
        ) from exc
    return envelope(
        request,
        data,
        dataset_version=ALGORITHM_DATA_VERSION,
        prediction_run_id=None,
        data_mode="derived",
        as_of=_observed_as_of(),
        claim_boundary="pair_calibration_development_only",
    )


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
