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
from .providers import ObservationProvider, PredictionProvider, create_observation_provider, create_prediction_provider

_GRID_CELL_RE = re.compile(r"^R(0[1-9]|1[01])-C(0[1-9]|1[0-9])$")
_STAGE_DAYS = (1, 3, 7, 15, 30)
_RISK_DEMO_TEXT = {"high": "红色演示", "mid": "橙色演示", "low": "绿色演示"}


class BackendService:
    def __init__(self, observation: ObservationProvider, prediction: PredictionProvider) -> None:
        self.observation = observation
        self.prediction = prediction

    # ---- Provider 身份（启动日志与能力披露共用） ----
    def provider_status(self) -> dict[str, str]:
        return {
            "observation_provider": self.observation.name(),
            "prediction_provider": self.prediction.name(),
        }

    # ---- 首页 ----
    def capabilities(self) -> dict[str, Any]:
        return {
            "data_as_of": AS_OF,
            "capabilities": {
                # 历史观测数据集存在但业务 Provider 未接入：不得表述为“真实监测已上线”
                "historical_observation": "dataset_available_backend_pending",
                "short_term_forecast_1_3d": "dataset_ready_model_pending",
                "medium_term_forecast_7_15d": "dataset_ready_model_pending",
                "long_term_forecast_30_90d": "blocked_auth",
                "satellite_chlorophyll": "experimental_not_operational",
                "real_time_warning_dispatch": "not_enabled",
                "demo_warning_dispatch": "available",
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
service = BackendService(_observation_provider, create_prediction_provider(_observation_provider))
