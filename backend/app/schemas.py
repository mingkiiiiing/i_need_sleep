"""OpenAPI 契约模型：全部 /api/v1 响应的 Pydantic 定义。

序列化约定：接口内部以字段名（snake_case）构造数据，
FastAPI response_model 默认按 alias 输出（camelCase 为前端既有消费字段）。
"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---- 统一信封 ----
class ResponseMeta(BaseModel):
    data_mode: str
    dataset_version: str
    prediction_run_id: str | None
    as_of: str
    claim_boundary: str
    request_id: str


class ErrorItem(BaseModel):
    code: str
    field: str | None = None
    detail: str


class Envelope(BaseModel, Generic[T]):
    code: int
    message: str
    data: T
    meta: ResponseMeta
    errors: list[ErrorItem]


# ---- 系统能力 / 数据集 / 管道 ----
class CapabilityBlocker(BaseModel):
    code: str
    scope: str
    action: str


class CapabilitiesData(BaseModel):
    data_as_of: str
    capabilities: dict[str, str]
    blockers: list[CapabilityBlocker]
    provider_status: dict[str, str]


class DatasetInfo(BaseModel):
    id: str
    data_mode: str
    record_count: int
    description: str


class DatasetsSummaryData(BaseModel):
    datasets: list[DatasetInfo]
    claim_boundary: str


class PipelineRunData(BaseModel):
    run_id: str
    status: str
    dataset_versions: list[str]


class OverviewCard(BaseModel):
    code: str
    value: int
    unit: str
    spatial_scope: str
    data_mode: str
    quality: str
    prediction_run_id: str


class OverviewData(BaseModel):
    cards: list[OverviewCard]
    prediction_run_id: str
    claim_boundary: str


# ---- 空间对象 / 观测 ----
class ZonePosition(BaseModel):
    top: str
    left: str


class SpatialEntity(BaseModel):
    id: str
    entity_type: str
    display_name: str
    short: str
    geometry_status: str
    data_mode: str
    position: ZonePosition
    risk_hint: str


class ObservationRow(BaseModel):
    spatial_entity_id: str
    observed_at: str
    variable_code: str
    clean_value: float
    unit: str
    value_origin: str
    quality_status: str
    is_imputed: bool
    proxy_flag: bool
    data_mode: str
    dataset_version: str


class QualityReport(BaseModel):
    spatial_entity_id: str
    status: str
    freshness: str
    observed_count: int
    source_count: int
    is_imputed: bool
    value_origin: str
    proxy_flag: bool
    limitations: list[str]


# ---- 实时观测轨（observed；MEE 国控站点） ----
class StationLocation(BaseModel):
    lon: float | None
    lat: float | None
    location_status: Literal["verified", "metadata_only", "suspicious", "missing"]
    registry_source: str | None


class MonitoringStation(BaseModel):
    id: str
    entity_type: Literal["monitoring_station"]
    source_id: str
    source_station_name: str
    display_name: str
    aliases: list[str]
    province: str | None
    basin: str | None
    location: StationLocation
    active_in_latest_snapshot: bool
    first_seen_at: str | None
    last_seen_at: str | None
    latest_observed_at: str | None
    latest_snapshot_id: str | None
    latest_water_quality_level: int | None
    available_variable_count: int
    qc_rejected_variable_count: int
    missing_variable_count: int
    data_mode: str
    dataset_version: str


class StationObservationRow(BaseModel):
    station_entity_id: str
    snapshot_id: str
    observed_at: str | None
    retrieved_at: str | None
    variable_code: str
    value: float | None
    unit: str | None
    observation_status: Literal["ok", "missing", "qc_rejected", "parse_failed"]
    missing_reason: str | None
    source_quality_note: str | None
    qc_status: str
    evidence_level: str
    verification_state: str
    is_ground_truth: bool
    data_mode: str
    dataset_version: str


class StationQuality(BaseModel):
    station_entity_id: str
    status: str
    observed_lag_h: float | None
    retrieval_lag_h: float | None
    variable_coverage: dict[str, int]
    coverage_ratio: float
    missing_variables: list[str]
    qc_rejected_variables: list[str]
    snapshot_count: int
    location_status: str
    is_ground_truth: bool
    verification_state: str
    suitability: dict[str, bool]
    limitations: list[str]
    data_mode: str
    dataset_version: str


class RealtimeStationMarker(BaseModel):
    id: str
    name: str | None
    province: str | None = None
    basin: str | None = None
    lon: float
    lat: float
    location_status: str
    chla: float | None
    water_level: int | None
    metrics: dict[str, float] = {}
    observed_at: str | None


class RealtimeWarningItem(BaseModel):
    station_id: str
    station_name: str | None
    chla: float
    band: Literal["light", "moderate"]
    lon: float | None
    lat: float | None
    location_status: str


class RealtimeSummary(BaseModel):
    source: str
    dataset_version: str
    as_of: str | None
    freshness_status: str
    observed_lag_h: float | None
    latest_snapshot_id: str
    selected_snapshot_id: str
    is_latest: bool
    retrieved_at: str | None
    latest_observed_at: str | None
    station_total: int
    class_counts: dict[str, int]
    class_total: int
    dominant_class: str | None
    class_iii_rate: float | None
    class_compliance: dict[str, int]
    chla_report_stations: int
    warnings: list[RealtimeWarningItem]
    warning_thresholds: dict[str, float]
    means: dict[str, dict[str, Any]]
    trends: dict[str, dict[str, Any]]
    health: dict[str, Any]
    markers: list[RealtimeStationMarker]


class RealtimeTimeline(BaseModel):
    source: str
    dataset_version: str
    latest_snapshot_id: str | None
    warning_thresholds: dict[str, float]
    snapshots: list[dict[str, Any]]


class RealtimeStatus(BaseModel):
    source: str
    dataset_version: str
    available: bool
    collection_status: str
    freshness_status: str
    snapshot_count: int
    active_station_count: int
    latest_station_count: int | None
    latest_observed_at: str | None
    observed_lag_h: float | None
    as_of: str | None
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: str | None
    last_error_code: str | None
    declared_record_count: int | None = None
    parsed_station_count: int | None = None
    latest_snapshot_id: str | None = None
    note: str | None = None


# ---- 预警通知（蓝藻筛查同口径 10/25 μg/L；投递回执如实披露） ----

class AlertDelivery(BaseModel):
    channel: str
    status: Literal["sent", "failed", "skipped"]
    at: str
    detail: str
    recipients: list[str]
    receipt: str | None = None


class AlertEvent(BaseModel):
    id: str
    station_id: str
    station_name: str
    province: str | None
    level: Literal["light", "moderate"]
    chla: float | None
    snapshot_id: str | None
    observed_at: str | None
    kind: Literal["trigger", "escalation"]
    status: Literal["active", "resolved"]
    triggered_at: str
    resolved_at: str | None = None
    resolve_reason: str | None = None
    deliveries: list[AlertDelivery]


class AlertOverview(BaseModel):
    version: str
    enabled: bool
    channels: dict[str, dict[str, bool]]
    active_counts: dict[str, int]
    active_total: int
    active_alerts: list[AlertEvent]
    recent_alerts: list[AlertEvent]
    last_evaluated_at: str | None
    last_error: str | None
    thresholds: dict[str, float]
    threshold_note: str


class AlertEvaluation(BaseModel):
    evaluated_at: str
    enabled: bool
    snapshot_id: str | None
    stations_scanned: int
    warnings_seen: int
    triggered: list[str]
    escalated: list[str]
    resolved: list[dict[str, Any]]
    deliveries: list[AlertDelivery]


# ---- 预测 ----
class ForecastUncertainty(BaseModel):
    lower: int
    upper: int
    method: str


class ForecastQualityGate(BaseModel):
    status: str
    decision: str
    reason: str


class Forecast(BaseModel):
    id: str
    spatial_entity_id: str
    prediction_run_id: str
    horizon_days: int
    target_metric: str
    risk_score: int
    risk_level: str
    provider_type: str
    model_version: str
    claim_boundary: str
    uncertainty: ForecastUncertainty
    quality_gate: ForecastQualityGate


class ExplanationFeature(BaseModel):
    name: str
    contribution: float
    direction: Literal["positive", "negative"]
    label: str


class Explanation(BaseModel):
    forecast_id: str
    prediction_run_id: str
    dataset_version: str
    method: str
    claim_boundary: str
    features: list[ExplanationFeature]


# ---- 地图 ----
class MapLayer(BaseModel):
    id: str
    layer_type: str
    data_mode: str
    operational_use: bool
    description: str


class RiskPolygonsData(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[Any]
    horizon_days: int
    source: str
    empty_reason: str
    data_mode: str
    dataset_version: str
    prediction_run_id: str
    claim_boundary: str


# ---- 事件 ----
class CanonicalEvent(BaseModel):
    """规范事件源（/events）。"""

    id: str
    event_type: str
    occurred_at: str
    spatial_entity_id: str
    title: str
    summary: str
    severity: str
    data_mode: str
    dataset_version: str
    prediction_run_id: str


class CockpitEvent(BaseModel):
    """兼容视图（/cockpit/events），与规范事件源共享同一组稳定 ID。"""

    id: str
    time: str
    stage_key: str = Field(serialization_alias="stageKey")
    point: str
    title: str
    summary: str
    severity: str
    data_mode: str
    dataset_version: str
    prediction_run_id: str


# ---- 驾驶舱兼容视图 ----
class TimeStage(BaseModel):
    key: str
    label: str
    short: str
    days: int
    index: int
    data_mode: str
    capability_status: str


class PointMetrics(BaseModel):
    density: str
    chla: str
    phosphorus: str
    temp: str


class PointFactor(BaseModel):
    name: str
    value: int
    unit: str = "%"


class PointForecastBrief(BaseModel):
    window: list[str]
    title: list[str]
    text: list[str]


class CockpitPoint(BaseModel):
    id: str
    name: str
    short: str
    risk: str
    risk_class: str = Field(serialization_alias="riskClass")
    summary: str
    metrics: PointMetrics
    forecast: PointForecastBrief
    factors: list[PointFactor]
    data_mode: str = Field(serialization_alias="dataMode")
    dataset_version: str = Field(serialization_alias="datasetVersion")


class CockpitPointsData(BaseModel):
    point_data: dict[str, CockpitPoint] = Field(serialization_alias="pointData")
    point_positions: dict[str, ZonePosition] = Field(serialization_alias="pointPositions")


class HeatFieldData(BaseModel):
    t1: list[list[int]]
    t3: list[list[int]]
    t7: list[list[int]]
    t15: list[list[int]]
    t30: list[list[int]]
    scenario: dict[str, Any] = Field(serialization_alias="_scenario")


class RegionSummaryData(BaseModel):
    total_stations: int = Field(serialization_alias="totalStations")
    risk_counts: dict[str, int] = Field(serialization_alias="riskCounts")
    intensity: dict[str, dict[str, int]]


# ---- 模拟预警处理 ----
class HandleWarningData(BaseModel):
    event_id: str
    status: str
    channels: list[str]
    persisted: bool
    data_mode: str
    dataset_version: str
    claim_boundary: str


# ---- 时间轴 ----
class TimelineRow(BaseModel):
    date: str
    risk_score: int
    risk_level: str
    data_mode: str
    dataset_version: str


class TimelineData(BaseModel):
    start_date: str
    end_date: str
    total_days: int
    data: list[TimelineRow]
