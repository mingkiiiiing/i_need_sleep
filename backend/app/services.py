from __future__ import annotations

from typing import Any

from .demo_provider import CLAIM_BOUNDARY, FORECAST_VERSION, OBSERVATION_VERSION, SimulatedProvider


class BackendService:
    def __init__(self, provider: SimulatedProvider | None = None) -> None:
        self.provider = provider or SimulatedProvider()

    def capabilities(self) -> dict[str, Any]:
        return {
            "data_as_of": "2026-08-24T01:15:10+08:00",
            "capabilities": {
                "historical_observation": "available",
                "short_term_forecast_1_3d": "dataset_ready_model_pending",
                "medium_term_forecast_7_15d": "dataset_ready_model_pending",
                "long_term_forecast_30_90d": "blocked_auth",
                "satellite_chlorophyll": "experimental_not_operational",
                "real_time_warning_dispatch": "not_enabled",
                "demo_warning_dispatch": "available",
            },
            "blockers": [{"code": "MISSING_C3S_SEASONAL_HINDCAST", "scope": "30_90d", "action": "配置 CDS API 并完成季节预测回报数据接入"}],
        }

    def datasets_summary(self) -> dict[str, Any]:
        return {"datasets": [{"id": OBSERVATION_VERSION, "data_mode": "simulated", "record_count": 6, "description": "P0 前后端联调观测样本"}, {"id": FORECAST_VERSION, "data_mode": "simulated", "record_count": 30, "description": "P0 演示预测与风险分区样本"}], "claim_boundary": CLAIM_BOUNDARY}

    def spatial_entities(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        if entity_type and entity_type != "demo_zone":
            return []
        return [{"id": zone["id"], "entity_type": "demo_zone", "display_name": zone["name"], "short": zone["short"], "geometry_status": "simulated", "data_mode": "simulated", "position": zone["position"], "risk_hint": zone["risk"]} for zone in self.provider.zones]

    def quality(self, entity_id: str) -> dict[str, Any]:
        return {"spatial_entity_id": entity_id, "status": "warning", "freshness": "simulated", "observed_count": len(self.provider.observations(entity_id)), "source_count": 1, "is_imputed": False, "value_origin": "simulated", "proxy_flag": True, "limitations": ["P0 simulated data; not for operational decisions"]}

    def overview(self) -> dict[str, Any]:
        cards = []
        for zone in self.provider.zones:
            forecast = self.provider.forecast(zone["id"], 3)
            cards.append({"code": f"risk_{zone['id']}", "value": forecast["risk_score"], "unit": "risk_score", "spatial_scope": zone["id"], "data_mode": "simulated", "quality": "warning", "prediction_run_id": "DEMO-RUN-V1"})
        return {"cards": cards, "prediction_run_id": "DEMO-RUN-V1", "claim_boundary": CLAIM_BOUNDARY}

    def risk_grid(self, horizon_days: int) -> dict[str, Any]:
        if horizon_days not in {1, 3, 7, 15, 30}:
            raise ValueError("horizon_days must be one of 1, 3, 7, 15, 30")
        shift = {1: 0, 3: 3, 7: 7, 15: 12, 30: 18}[horizon_days]
        values = [[max(5, min(95, 90 - abs(column - 4 - shift / 3) * 9 - abs(row - 3) * 11)) for column in range(19)] for row in range(11)]
        return {"prediction_run_id": "DEMO-RUN-V1", "horizon_days": horizon_days, "data_mode": "simulated", "grid": values, "resolution": {"rows": 11, "columns": 19, "unit": "risk_score"}, "claim_boundary": CLAIM_BOUNDARY}


service = BackendService()
