"""Deterministic P0 provider. It never represents simulated values as observations or model outputs."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample-data"
FORECAST_VERSION = "DEMO-PRED-V1"
OBSERVATION_VERSION = "DEMO-OBS-V1"
CLAIM_BOUNDARY = "simulation_only"


class SimulatedProvider:
    def __init__(self) -> None:
        self._fixture = json.loads((SAMPLE_DIR / "simulated_api_fixture_v1.json").read_text(encoding="utf-8"))
        with (SAMPLE_DIR / "simulated_observations_v1.csv").open(encoding="utf-8", newline="") as file:
            self._observations = list(csv.DictReader(file))

    @property
    def zones(self) -> list[dict[str, Any]]:
        return self._fixture["zones"]

    def zone(self, entity_id: str) -> dict[str, Any] | None:
        return next((item for item in self.zones if item["id"] == entity_id), None)

    def observations(self, entity_id: str, variable_code: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._observations if row["spatial_entity_id"] == entity_id]
        if variable_code:
            rows = [row for row in rows if row["variable_code"] == variable_code]
        for row in rows:
            row["clean_value"] = float(row["clean_value"])
            row["is_imputed"] = row["is_imputed"].lower() == "true"
            row["data_mode"] = "simulated"
            row["dataset_version"] = OBSERVATION_VERSION
        return rows

    def forecast(self, entity_id: str, horizon_days: int) -> dict[str, Any] | None:
        zone = self.zone(entity_id)
        if not zone:
            return None
        base = {"high": 84, "mid": 61, "low": 28}[zone["risk"]]
        score = max(10, base - {1: 0, 3: 3, 7: 7, 15: 13, 30: 20}[horizon_days])
        return {
            "id": f"demo-forecast-{entity_id}-{horizon_days}d",
            "spatial_entity_id": entity_id,
            "prediction_run_id": "DEMO-RUN-V1",
            "horizon_days": horizon_days,
            "target_metric": "bloom_risk",
            "risk_score": score,
            "risk_level": "high" if score >= 75 else "mid" if score >= 45 else "low",
            "provider_type": "simulation",
            "model_version": "DEMO-RULE-V1",
            "claim_boundary": CLAIM_BOUNDARY,
            "uncertainty": {"lower": max(0, score - 10), "upper": min(100, score + 10), "method": "demo_rule_band"},
            "quality_gate": {"status": "warning", "decision": "candidate_assessment_only", "reason": "simulated data cannot trigger a real warning"},
        }

    def explanation(self, forecast_id: str) -> dict[str, Any] | None:
        parts = forecast_id.removeprefix("demo-forecast-").rsplit("-", 1)
        if len(parts) != 2 or not self.zone(parts[0]):
            return None
        return {
            "forecast_id": forecast_id,
            "method": "demo_rule_contribution",
            "claim_boundary": CLAIM_BOUNDARY,
            "features": [
                {"name": "air_temperature", "contribution": 0.34, "direction": "positive", "label": "气温（演示驱动）"},
                {"name": "wind_speed", "contribution": 0.24, "direction": "negative", "label": "风速（演示驱动）"},
                {"name": "total_phosphorus", "contribution": 0.20, "direction": "positive", "label": "总磷（演示驱动）"},
            ],
        }
