"""业务组装层：把 Provider 数据组织为各接口的 data 部分。

本层不构造信封（见 contracts.py）、不做 HTTP 语义判断（见 api.py）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .contracts import (
    AS_OF,
    CLAIM_BOUNDARY,
    DATA_MODE,
    OBSERVATION_VERSION,
    PREDICTION_RUN_ID,
    PREDICTION_VERSION,
    risk_level,
)
from .providers import (
    MeeRealtimeObservationProvider,
    ObservationProvider,
    PredictionProvider,
    RealtimeDataUnavailable,
    create_observation_provider,
    create_prediction_provider,
    create_realtime_observation_provider,
)
from .alerts import AlertEngine
from .station_forecast import MODEL_VERSION as _STATION_FC_VERSION
from .station_forecast import StationForecastEngine
from .algorithm_models import AlgorithmModelService, AlgorithmModelServiceV3, AlgorithmModelUnavailable
from .prediction_snapshot import FOCUS_RESULT_KEY, SNAPSHOT_HORIZONS, PredictionSnapshotService

_GRID_CELL_RE = re.compile(r"^R(0[1-9]|1[01])-C(0[1-9]|1[0-9])$")
_STAGE_DAYS = (1, 3, 7, 15, 30)
_RISK_DEMO_TEXT = {"high": "红色演示", "mid": "橙色演示", "low": "绿色演示"}

# 站点级预测引擎单例：目录签名变化由引擎内部对齐重建（与实时 Provider 同一热加载语义）
_station_forecast_engine_instance: StationForecastEngine | None = None


def station_forecast_engine(provider: MeeRealtimeObservationProvider) -> StationForecastEngine:
    global _station_forecast_engine_instance
    if _station_forecast_engine_instance is None:
        _station_forecast_engine_instance = StationForecastEngine(provider)
    return _station_forecast_engine_instance


class BackendService:
    def __init__(
        self,
        observation: ObservationProvider,
        prediction: PredictionProvider,
        realtime: MeeRealtimeObservationProvider | None = None,
    ) -> None:
        self.observation = observation
        self.prediction = prediction
        # 双轨：simulated 演示轨 + observed 实时轨；两轨数据永不混合
        self.realtime = realtime
        # V0.2 交付包保留为 legacy（保留页面端点继续消费，行为不回退）；
        # V0.3 真实数据包为默认算法服务，走 v3 端点，legacy 空间场作其回退链。
        self.algorithm = AlgorithmModelService(realtime) if realtime is not None else None
        self.algorithm_v3 = (
            AlgorithmModelServiceV3(realtime, legacy_service=self.algorithm)
            if realtime is not None
            else None
        )
        # 实测快照驱动的预测快照：后台预生成 + 磁盘持久化 + 原子发布。
        # 页面打开时读现成结果，只有实测数据/模型版本变化才重新推理。
        self.prediction_snapshot = (
            PredictionSnapshotService(self.algorithm_v3, realtime)
            if self.algorithm_v3 is not None
            else None
        )

    # ---- 实时观测轨（observed） ----

    def realtime_status(self) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        return self.realtime.status()

    def realtime_summary(self, snapshot_id: str | None = None) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        return self.realtime.summary(snapshot_id)

    def realtime_timeline(self) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        return self.realtime.snapshot_timeline()

    def realtime_stations(
        self,
        *,
        active: str | None = None,
        province: str | None = None,
        location_status: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        return self.realtime.stations(active=active, province=province, location_status=location_status)

    def realtime_station(self, entity_id: str) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        station = self.realtime.station(entity_id)
        if station is None:
            raise KeyError(entity_id)
        return station

    def realtime_observations(
        self,
        entity_id: str,
        *,
        window: str = "latest",
        start: str | None = None,
        end: str | None = None,
        variables: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        rows = self.realtime.observations(entity_id, window=window, start=start, end=end, variables=variables)
        if rows is None:
            raise KeyError(entity_id)
        return rows

    def realtime_quality(self, entity_id: str) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        quality = self.realtime.quality(entity_id)
        if quality is None:
            raise KeyError(entity_id)
        return quality

    # ---- 站点级机理+AI 融合预测（observed 轨唯一算法产出，v0.1 试点） ----

    def realtime_station_forecast(self, entity_id: str) -> dict[str, Any]:
        if self.realtime is None:
            raise RealtimeDataUnavailable("实时观测轨未配置")
        if self.realtime.station(entity_id) is None:
            raise KeyError(entity_id)
        return station_forecast_engine(self.realtime).forecast(entity_id)

    def realtime_station_forecast_status(self) -> dict[str, Any]:
        if self.realtime is None:
            return {"status": "not_configured", "model_version": _STATION_FC_VERSION}
        try:
            return station_forecast_engine(self.realtime).status()
        except Exception:  # noqa: BLE001 — 能力披露不得因数据层异常而失败
            return {"status": "unavailable", "model_version": _STATION_FC_VERSION, "reason": "实时观测数据不可用"}

    def algorithm_model_status(self) -> dict[str, Any]:
        if self.algorithm is None:
            return {"status": "not_configured", "model_count": 0}
        return self.algorithm.status()

    def algorithm_predictions(self, horizon_days: int, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any]:
        if self.algorithm is None:
            raise RealtimeDataUnavailable("算法模型运行服务未配置")
        return self.algorithm.predict_suite(horizon_days, entity_id, focus_metric)

    def algorithm_acceptance(self) -> dict[str, Any]:
        if self.algorithm is None:
            raise RealtimeDataUnavailable("算法模型运行服务未配置")
        return self.algorithm.acceptance()

    def remote_retrieval_status(self) -> dict[str, Any]:
        if self.algorithm is None:
            raise RealtimeDataUnavailable("算法模型运行服务未配置")
        return self.algorithm.retrieval_status()

    def calibrate_remote_retrieval(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.algorithm is None:
            raise RealtimeDataUnavailable("算法模型运行服务未配置")
        return self.algorithm.calibrate_retrieval(payload)

    def algorithm_spatial_field(self, horizon_days: int, metric: str = "risk") -> dict[str, Any]:
        if self.algorithm is None:
            raise RealtimeDataUnavailable("算法模型运行服务未配置")
        return self.algorithm.spatial_field(horizon_days, metric)

    # ---- V0.3 真实数据包（月度标签粒度 + conformal + 动态门禁） ----

    def _require_algorithm_v3(self) -> AlgorithmModelServiceV3:
        if self.algorithm_v3 is None:
            raise RealtimeDataUnavailable("V0.3 算法模型运行服务未配置")
        return self.algorithm_v3

    def algorithm_model_status_v3(self) -> dict[str, Any]:
        return self._require_algorithm_v3().status()

    def algorithm_predictions_v3(self, horizon_days: int, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any]:
        """优先命中预测快照。

        同一实测快照内不再重复运行模型；结果直接来自快照，只有"当前指标的局部
        敏感性解释"因与指标绑定而无法随快照落盘，需要时按需补齐一次并进入缓存。
        """
        snapshot = self.prediction_snapshot
        if snapshot is not None:
            data = snapshot.assemble(entity_id, horizon_days, focus_metric)
            if data is not None:
                result_key = FOCUS_RESULT_KEY.get(focus_metric)
                results = data.get("results") or {}
                item = results.get(result_key) if result_key else None
                if isinstance(item, dict) and item.get("explainability") is None:
                    explainability = snapshot.ensure_explainability(entity_id, horizon_days, focus_metric)
                    if explainability is not None:
                        item["explainability"] = explainability
                return data
        return self._require_algorithm_v3().predict_suite(horizon_days, entity_id, focus_metric)

    # ---- 预测快照（实测快照驱动的后台预生成结果） ----

    def prediction_snapshot_status(self) -> dict[str, Any]:
        snapshot = self.prediction_snapshot
        if snapshot is None:
            raise RealtimeDataUnavailable("预测快照服务未配置")
        return snapshot.status()

    def prediction_snapshot_rebuild(self) -> dict[str, Any]:
        """管理员主动重算：交给快照服务的后台线程强制重新推理。"""
        snapshot = self.prediction_snapshot
        if snapshot is None:
            raise RealtimeDataUnavailable("预测快照服务未配置")
        return snapshot.request_rebuild()

    def prediction_snapshot_view(self, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any]:
        """一次返回全部时效结果与版本状态。

        快照未覆盖该实体时（站点补齐尚未完成），回落到即时推理组装同一结构，
        并在 snapshot_source 中如实标注来源，页面无需区分两条路径。
        """
        snapshot = self.prediction_snapshot
        if snapshot is not None:
            payload = snapshot.snapshot_payload(entity_id, focus_metric)
            if payload is not None:
                return payload
        if snapshot is not None:
            # 可观测性：本次读取触发了即时推理（审计口径要求页面切换零推理）。
            snapshot.count_live_inference_fallback()
        horizons: dict[str, Any] = {}
        for horizon in SNAPSHOT_HORIZONS:
            horizons[str(horizon)] = self.algorithm_predictions_v3(horizon, entity_id, focus_metric)
        return {
            "entity_id": entity_id,
            "focus_metric": focus_metric,
            "horizons": horizons,
            "horizon_list": list(SNAPSHOT_HORIZONS),
            "trend": {
                "points": [
                    {
                        "horizon_days": int(horizon_key),
                        "risk_score": data.get("risk_score"),
                        "focus_value": (
                            (data.get("results") or {}).get(
                                FOCUS_RESULT_KEY.get(focus_metric) or "", {}
                            ) or {}
                        ).get("value"),
                        "focus_unit": (
                            (data.get("results") or {}).get(
                                FOCUS_RESULT_KEY.get(focus_metric) or "", {}
                            ) or {}
                        ).get("unit"),
                        "focus_status": (
                            (data.get("results") or {}).get(
                                FOCUS_RESULT_KEY.get(focus_metric) or "", {}
                            ) or {}
                        ).get("status"),
                        "issued_at": data.get("issued_at"),
                    }
                    for horizon_key, data in horizons.items()
                ]
            },
            "prediction_snapshot_id": None,
            "source_snapshot_id": None,
            "generated_at": None,
            "model_version": None,
            "status": {
                "state": "unavailable",
                "using_previous_success": False,
                "last_error": None,
                "stations": {"ready": False, "done": 0, "total": 0},
            },
            "snapshot_source": {"served_from_snapshot": False},
        }

    def algorithm_acceptance_v3(self) -> dict[str, Any]:
        return self._require_algorithm_v3().acceptance()

    def prediction_station_field(self, horizon_days: int, metric: str = "risk") -> dict[str, Any]:
        """快照驱动的站点空间场：与结果面板同一 prediction_snapshot_id，覆盖分母=快照站点层。"""
        snapshot = self.prediction_snapshot
        if snapshot is None:
            raise RealtimeDataUnavailable("预测快照服务未配置")
        data = snapshot.station_field(horizon_days, metric)
        if data is None:
            raise AlgorithmModelUnavailable(
                "预测快照站点场不可用：快照未就绪、站点层未补齐或版本已过期"
            )
        return data

    def prediction_driver_distribution(self, horizon_days: int = 1) -> dict[str, Any]:
        """全湖驱动因素分布：79 站机理分解的站间分布（环境状态口径，非模型贡献）。"""
        snapshot = self.prediction_snapshot
        if snapshot is None:
            raise RealtimeDataUnavailable("预测快照服务未配置")
        data = snapshot.driver_distribution(horizon_days)
        if data is None:
            raise AlgorithmModelUnavailable(
                "全湖驱动因素分布不可用：快照未就绪或站点层未补齐"
            )
        return data

    def algorithm_acceptance_detail(self) -> dict[str, Any]:
        return self._require_algorithm_v3().acceptance_detail()

    def algorithm_calibration_coverage(self) -> dict[str, Any]:
        return self._require_algorithm_v3().calibration_coverage()

    def algorithm_spatial_field_v3(
        self, horizon_days: int, metric: str = "chla", layer: str = "raster",
        prediction_run_id: str | None = None,
    ) -> dict[str, Any]:
        return self._require_algorithm_v3().spatial_field(horizon_days, metric, layer, prediction_run_id)

    def retrieval_validation(self) -> dict[str, Any]:
        return self._require_algorithm_v3().retrieval_validation()

    def acceptance_overview(self) -> dict[str, Any]:
        return self._require_algorithm_v3().acceptance_overview()

    # ---- Provider 身份（启动日志与能力披露共用） ----
    def provider_status(self) -> dict[str, str]:
        return {
            "observation_provider": self.observation.name(),
            "prediction_provider": self.prediction.name(),
        }

    def _realtime_capability(self) -> str:
        if self.realtime is None:
            return "not_configured"
        try:
            available = bool(self.realtime.status().get("available"))
        except Exception:  # noqa: BLE001 — 能力披露不得因数据层异常而失败
            return "not_configured"
        return "observed_track_available" if available else "observed_track_no_data"

    # ---- 首页 ----
    def capabilities(self) -> dict[str, Any]:
        return {
            "data_as_of": AS_OF,
            "capabilities": {
                # 历史观测数据集存在但业务 Provider 未接入：不得表述为“真实监测已上线”
                "historical_observation": "dataset_available_backend_pending",
                "short_term_forecast_1_3d": "dataset_ready_model_pending",
                # 站点级机理+AI 融合预测（observed 轨，v0.1 试点；仅覆盖有叶绿素a 序列的站点）
                "station_level_forecast_1_3d": self.realtime_station_forecast_status()["status"],
                "medium_term_forecast_7_15d": "dataset_ready_model_pending",
                "long_term_forecast_30_90d": "blocked_auth",
                # 交付包 V0.2 已接入独立 /model/predictions 运行链；其合成训练边界
                # 不改变原“正式预测”能力状态。
                "algorithm_bundle_1_90d": "model_connected_scenario_only",
                "satellite_chlorophyll": "experimental_not_operational",
                "real_time_warning_dispatch": "not_enabled",
                "demo_warning_dispatch": "available",
                # 实时观测轨（observed）：与 simulated 演示轨双轨隔离，状态如实披露
                "realtime_observation": self._realtime_capability(),
            },
            "blockers": [
                {
                    "code": "MISSING_C3S_SEASONAL_HINDCAST",
                    "scope": "30_90d",
                    "action": "配置 CDS API 并完成季节预测回报数据接入",
                }
            ],
            "provider_status": self.provider_status(),
        }

    def datasets_summary(self) -> dict[str, Any]:
        observation_rows = sum(
            len(self.observation.observations(zone["id"])) for zone in self.observation.zones()
        )
        return {
            "datasets": [
                {
                    "id": OBSERVATION_VERSION,
                    "data_mode": DATA_MODE,
                    "record_count": observation_rows,
                    "description": "P0 演示观测样本（脚本生成，非真实监测数据）",
                },
                {
                    "id": PREDICTION_VERSION,
                    "data_mode": DATA_MODE,
                    "record_count": 30,
                    "description": "P0 演示预测与风险分区样本（规则推演，非算法模型输出）",
                },
            ],
            "claim_boundary": CLAIM_BOUNDARY,
        }

    def pipeline_latest(self) -> dict[str, Any]:
        return {
            "run_id": "DEMO-PIPELINE-V1",
            "status": "simulated",
            "dataset_versions": [OBSERVATION_VERSION, PREDICTION_VERSION],
        }

    # ---- 空间对象 ----
    def spatial_entities(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        if entity_type and entity_type != "demo_zone":
            return []
        return [
            {
                "id": zone["id"],
                "entity_type": "demo_zone",
                "display_name": zone["name"],
                "short": zone["short"],
                "geometry_status": "simulated",
                "data_mode": DATA_MODE,
                "position": zone["position"],
                "risk_hint": zone["risk"],
            }
            for zone in self.observation.zones()
        ]

    def overview(self) -> dict[str, Any]:
        cards = []
        for zone in self.observation.zones():
            forecast = self.prediction.forecast(zone["id"], 3)
            if not forecast:
                continue
            cards.append(
                {
                    "code": f"risk_{zone['id']}",
                    "value": forecast["risk_score"],
                    "unit": "risk_score",
                    "spatial_scope": zone["id"],
                    "data_mode": DATA_MODE,
                    "quality": "warning",
                    "prediction_run_id": PREDICTION_RUN_ID,
                }
            )
        return {"cards": cards, "prediction_run_id": PREDICTION_RUN_ID, "claim_boundary": CLAIM_BOUNDARY}

    # ---- 驾驶舱兼容视图 ----
    def cockpit_time_stages(self) -> list[dict[str, Any]]:
        return [
            {
                "key": f"t{day}",
                "label": "30 天模拟预演" if day == 30 else f"T+{day} 天演示预测",
                "short": "T+30d 模拟" if day == 30 else f"T+{day}d",
                "days": day,
                "index": index,
                "data_mode": DATA_MODE,
                "capability_status": "simulation_only" if day == 30 else "sample_interface_only",
            }
            for index, day in enumerate(_STAGE_DAYS)
        ]

    def cockpit_points(self) -> dict[str, Any]:
        point_data: dict[str, Any] = {}
        positions: dict[str, Any] = {}
        for zone in self.observation.zones():
            forecast = self.prediction.forecast(zone["id"], 3)
            if not forecast:
                continue
            explanation = self.prediction.explanation(forecast["id"])
            features = explanation["features"] if explanation else []
            point_data[zone["id"]] = {
                "id": zone["id"],
                "name": zone["name"],
                "short": zone["short"],
                "risk": "SIMULATED / " + _RISK_DEMO_TEXT[forecast["risk_level"]],
                "risk_class": forecast["risk_level"],
                "summary": "演示业务分区，非真实站点、非决策用途。",
                "metrics": {
                    "density": "SIMULATED",
                    "chla": "experimental / unavailable",
                    "phosphorus": "SIMULATED",
                    "temp": "air temperature proxy",
                },
                "forecast": {
                    "window": [f"未来 {day} 天" for day in _STAGE_DAYS],
                    "title": ["演示研判"] * len(_STAGE_DAYS),
                    "text": ["SIMULATED / 非决策用途"] * len(_STAGE_DAYS),
                },
                "factors": [
                    {"name": item["label"], "value": round(item["contribution"] * 100)} for item in features
                ],
                "data_mode": DATA_MODE,
                "dataset_version": PREDICTION_VERSION,
            }
            positions[zone["id"]] = zone["position"]
        return {"point_data": point_data, "point_positions": positions}

    def cockpit_heat_field(self) -> dict[str, Any]:
        grids = {f"t{day}": self.prediction.risk_grid(day)["grid"] for day in _STAGE_DAYS}
        grids["scenario"] = {
            "layer_type": "simulated_scenario",
            "operational_use": False,
            "long_term_notice": "T+30 仅为模拟预演，不代表 30—90 天预测能力",
        }
        return grids

    def canonical_events(self) -> list[dict[str, Any]]:
        return [
            {
                "id": f"demo-event-{index}",
                "event_type": "model",
                "occurred_at": f"2026-08-{16 + index:02d}T09:00:00+08:00",
                "spatial_entity_id": zone["id"],
                "title": "演示预测运行",
                "summary": "SIMULATED / 非决策用途",
                "severity": zone["risk"],
                "data_mode": DATA_MODE,
                "dataset_version": PREDICTION_VERSION,
                "prediction_run_id": PREDICTION_RUN_ID,
            }
            for index, zone in enumerate(self.observation.zones())
        ]

    def cockpit_events(self) -> list[dict[str, Any]]:
        stage_cycle = _STAGE_DAYS
        return [
            {
                "id": f"demo-event-{index}",
                "time": f"08-{16 + index:02d} 09:00",
                "stage_key": f"t{stage_cycle[index % len(stage_cycle)]}",
                "point": zone["id"],
                "title": "演示预测运行",
                "summary": "SIMULATED / 非决策用途",
                "severity": zone["risk"],
                "data_mode": DATA_MODE,
                "dataset_version": PREDICTION_VERSION,
                "prediction_run_id": PREDICTION_RUN_ID,
            }
            for index, zone in enumerate(self.observation.zones())
        ]

    def region_summary(self) -> dict[str, Any]:
        zones = self.observation.zones()
        risk_counts = {"high": 0, "mid": 0, "low": 0}
        intensity: dict[str, dict[str, int]] = {}
        for zone in zones:
            risk_counts[zone["risk"]] += 1
            intensity[zone["id"]] = {}
            for day in _STAGE_DAYS:
                forecast = self.prediction.forecast(zone["id"], day)
                intensity[zone["id"]][f"t{day}"] = forecast["risk_score"] if forecast else 0
        return {
            "total_stations": len(zones),
            "risk_counts": risk_counts,
            "intensity": intensity,
        }

    # ---- 模拟预警处理 ----
    def handle_warning(self, event_id: str) -> dict[str, Any] | None:
        """演示对象引用校验：仅接受稳定事件 ID、演示分区 ID 或演示格网编号。"""
        known_zones = {zone["id"] for zone in self.observation.zones()}
        known_events = {item["id"] for item in self.canonical_events()}
        if event_id in known_events or event_id in known_zones or _GRID_CELL_RE.match(event_id):
            return {
                "event_id": event_id,
                "status": "simulated_dispatched",
                "channels": ["platform_simulation"],
                "persisted": False,
                "data_mode": DATA_MODE,
                "dataset_version": PREDICTION_VERSION,
                "claim_boundary": CLAIM_BOUNDARY,
            }
        return None

    # ---- 时间轴（演示风险序列，非叶绿素观测） ----
    def timeline(self, start: date, end: date) -> dict[str, Any]:
        days = (end - start).days + 1
        values = []
        for index in range(days):
            current = start + timedelta(days=index)
            score = 34 + (index * 7) % 38
            values.append(
                {
                    "date": current.isoformat(),
                    "risk_score": score,
                    "risk_level": risk_level(score),
                    "data_mode": DATA_MODE,
                    "dataset_version": PREDICTION_VERSION,
                }
            )
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_days": days,
            "data": values,
        }


_observation_provider = create_observation_provider()
service = BackendService(
    _observation_provider,
    create_prediction_provider(_observation_provider),
    create_realtime_observation_provider(),
)


def _alert_snapshot_fetch() -> dict[str, Any]:
    return service.realtime_summary(None)


def _alert_stations_fetch() -> list[dict[str, Any]]:
    return service.realtime.stations(active="latest")


alert_engine = AlertEngine(_alert_snapshot_fetch, _alert_stations_fetch)
