"""Provider 边界：观测与预测的唯一数据来源抽象。

当前仅实现 simulated。通过环境变量选择：
  OBSERVATION_PROVIDER / PREDICTION_PROVIDER（默认 simulated）

配置为 cleaned / member_c 等尚未实现的值时，工厂直接抛出 ProviderConfigError，
导致应用启动失败——禁止任何形式的静默回退 simulated。
"""
from __future__ import annotations

import csv
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .contracts import (
    CLAIM_BOUNDARY,
    DATA_MODE,
    GRID_COLUMNS,
    GRID_ROWS,
    OBSERVATION_VERSION,
    PREDICTION_RUN_ID,
    PREDICTION_VERSION,
    RISK_THRESHOLDS,
    risk_level,
)

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample-data"

OBSERVATION_PROVIDER_ENV = "OBSERVATION_PROVIDER"
PREDICTION_PROVIDER_ENV = "PREDICTION_PROVIDER"


class ProviderConfigError(RuntimeError):
    """Provider 配置指向未实现的实现时抛出，应用必须启动失败而非回退。"""


class ObservationProvider(ABC):
    """观测侧数据源：演示分区目录、模拟观测序列、质量摘要。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dataset_version(self) -> str: ...

    @abstractmethod
    def zones(self) -> list[dict[str, Any]]: ...

    def zone(self, entity_id: str) -> dict[str, Any] | None:
        return next((item for item in self.zones() if item["id"] == entity_id), None)

    @abstractmethod
    def observations(self, entity_id: str, variable_code: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def quality(self, entity_id: str) -> dict[str, Any]: ...


class PredictionProvider(ABC):
    """预测侧数据源：分区预测、预测解释、演示风险格网。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dataset_version(self) -> str: ...

    @abstractmethod
    def prediction_run_id(self) -> str: ...

    @abstractmethod
    def forecast(self, entity_id: str, horizon_days: int) -> dict[str, Any] | None: ...

    @abstractmethod
    def explanation(self, forecast_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def risk_grid(self, horizon_days: int) -> dict[str, Any]: ...


class SimulatedObservationProvider(ObservationProvider):
    """读取 backend/sample-data 固定样本，不访问任何外部数据现场。"""

    def __init__(self) -> None:
        self._fixture = json.loads((SAMPLE_DIR / "simulated_api_fixture_v1.json").read_text(encoding="utf-8"))
        with (SAMPLE_DIR / "simulated_observations_v1.csv").open(encoding="utf-8", newline="") as file:
            self._observations = list(csv.DictReader(file))

    def name(self) -> str:
        return "simulated"

    def dataset_version(self) -> str:
        return OBSERVATION_VERSION

    def zones(self) -> list[dict[str, Any]]:
        return self._fixture["zones"]

    def observations(self, entity_id: str, variable_code: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._observations if row["spatial_entity_id"] == entity_id]
        if variable_code:
            rows = [row for row in rows if row["variable_code"] == variable_code]
        result = []
        for row in rows:
            result.append(
                {
                    "spatial_entity_id": row["spatial_entity_id"],
                    "observed_at": row["observed_at"],
                    "variable_code": row["variable_code"],
                    "clean_value": float(row["clean_value"]),
                    "unit": row["unit"],
                    "value_origin": row["value_origin"],
                    "quality_status": row["quality_status"],
                    "is_imputed": row["is_imputed"].lower() == "true",
                    # 气温是驱动代理变量，非水温实测，必须逐行披露
                    "proxy_flag": row["variable_code"] == "air_temperature",
                    "data_mode": DATA_MODE,
                    "dataset_version": OBSERVATION_VERSION,
                }
            )
        return result

    def quality(self, entity_id: str) -> dict[str, Any]:
        return {
            "spatial_entity_id": entity_id,
            "status": "warning",
            "freshness": "simulated",
            "observed_count": len(self.observations(entity_id)),
            "source_count": 1,
            "is_imputed": False,
            "value_origin": "simulated",
            "proxy_flag": True,
            "limitations": ["P0 simulated data; not for operational decisions"],
        }


class SimulatedPredictionProvider(PredictionProvider):
    """确定性规则推演：固定种子语义、固定公式，不表示任何算法模型输出。"""

    HORIZON_SCORE_OFFSET = {1: 0, 3: 3, 7: 7, 15: 13, 30: 20}
    GRID_SHIFT = {1: 0, 3: 3, 7: 7, 15: 12, 30: 18}

    def __init__(self, zones: list[dict[str, Any]]) -> None:
        self._zones = zones

    def name(self) -> str:
        return "simulated"

    def dataset_version(self) -> str:
        return PREDICTION_VERSION

    def prediction_run_id(self) -> str:
        return PREDICTION_RUN_ID

    def zone(self, entity_id: str) -> dict[str, Any] | None:
        return next((item for item in self._zones if item["id"] == entity_id), None)

    def forecast(self, entity_id: str, horizon_days: int) -> dict[str, Any] | None:
        zone = self.zone(entity_id)
        if not zone:
            return None
        base = {"high": 84, "mid": 61, "low": 28}[zone["risk"]]
        score = max(10, base - self.HORIZON_SCORE_OFFSET[horizon_days])
        return {
            "id": f"demo-forecast-{entity_id}-{horizon_days}d",
            "spatial_entity_id": entity_id,
            "prediction_run_id": PREDICTION_RUN_ID,
            "horizon_days": horizon_days,
            "target_metric": "bloom_risk",
            "risk_score": score,
            "risk_level": risk_level(score),
            "provider_type": "simulation",
            "model_version": "DEMO-RULE-V1",
            "claim_boundary": CLAIM_BOUNDARY,
            "uncertainty": {
                "lower": max(0, score - 10),
                "upper": min(100, score + 10),
                "method": "demo_rule_band",
            },
            "quality_gate": {
                "status": "warning",
                "decision": "candidate_assessment_only",
                "reason": "simulated data cannot trigger a real warning",
            },
        }

    def explanation(self, forecast_id: str) -> dict[str, Any] | None:
        parts = forecast_id.removeprefix("demo-forecast-").rsplit("-", 1)
        if len(parts) != 2 or not self.zone(parts[0]):
            return None
        horizon_text = parts[1].removesuffix("d")
        if not horizon_text.isdigit() or int(horizon_text) not in self.HORIZON_SCORE_OFFSET:
            return None
        return {
            "forecast_id": forecast_id,
            "prediction_run_id": PREDICTION_RUN_ID,
            "dataset_version": PREDICTION_VERSION,
            "method": "demo_rule_contribution",
            "claim_boundary": CLAIM_BOUNDARY,
            "features": [
                {"name": "air_temperature", "contribution": 0.34, "direction": "positive", "label": "气温（演示驱动）"},
                {"name": "wind_speed", "contribution": 0.24, "direction": "negative", "label": "风速（演示驱动）"},
                {"name": "total_phosphorus", "contribution": 0.20, "direction": "positive", "label": "总磷（演示驱动）"},
            ],
        }

    def risk_grid(self, horizon_days: int) -> dict[str, Any]:
        shift = self.GRID_SHIFT[horizon_days]
        # 公式在数学上恒为整数，浮点仅产生 1e-14 量级尾差；显式取整保证契约值精确
        values = [
            [
                int(round(max(5, min(95, 90 - abs(column - 4 - shift / 3) * 9 - abs(row - 3) * 11))))
                for column in range(GRID_COLUMNS)
            ]
            for row in range(GRID_ROWS)
        ]
        return {
            "prediction_run_id": PREDICTION_RUN_ID,
            "horizon_days": horizon_days,
            "data_mode": DATA_MODE,
            "dataset_version": PREDICTION_VERSION,
            "grid": values,
            "rows": GRID_ROWS,
            "columns": GRID_COLUMNS,
            "resolution": {"rows": GRID_ROWS, "columns": GRID_COLUMNS, "unit": "risk_score"},
            "thresholds": RISK_THRESHOLDS,
            "claim_boundary": CLAIM_BOUNDARY,
        }


def _configured_provider(env_key: str) -> str:
    raw = os.environ.get(env_key, "").strip().lower()
    return raw or "simulated"


def create_observation_provider() -> ObservationProvider:
    name = _configured_provider(OBSERVATION_PROVIDER_ENV)
    if name == "simulated":
        return SimulatedObservationProvider()
    raise ProviderConfigError(
        f"{OBSERVATION_PROVIDER_ENV}={name!r} 的实现尚未提供，拒绝静默回退 simulated：请改回 'simulated' 或先实现对应 Provider"
    )


def create_prediction_provider(observation_provider: ObservationProvider) -> PredictionProvider:
    name = _configured_provider(PREDICTION_PROVIDER_ENV)
    if name == "simulated":
        return SimulatedPredictionProvider(observation_provider.zones())
    raise ProviderConfigError(
        f"{PREDICTION_PROVIDER_ENV}={name!r} 的实现尚未提供，拒绝静默回退 simulated：请改回 'simulated' 或先实现对应 Provider"
    )
