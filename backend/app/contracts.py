"""统一响应契约：数据身份常量、风险阈值、响应信封构造。

所有 /api/v1 接口的成功与错误响应都必须经由本模块构造，
保证 code/message/data/meta/errors 结构与数据身份字段全局一致。
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

# ---- 数据身份（全站唯一口径，与前端 dataIdentity.js 对齐） ----
DATA_MODE = "simulated"
OBSERVATION_VERSION = "DEMO-OBS-V1"
PREDICTION_VERSION = "DEMO-PRED-V1"
PREDICTION_RUN_ID = "DEMO-RUN-V1"
CLAIM_BOUNDARY = "simulation_only"
# 演示数据统一的生成基准时间（与前端 asOfFull 一致），非服务器墙钟时间
AS_OF = "2026-08-24T08:00:00+08:00"

# ---- 风险阈值（0—44 低 / 45—74 中 / 75—100 高，与前端 gridCore.js 一致） ----
RISK_THRESHOLDS = {"low": [0, 44], "mid": [45, 74], "high": [75, 100]}
GRID_ROWS = 11
GRID_COLUMNS = 19
HORIZONS = (1, 3, 7, 15, 30)
FORECAST_HORIZONS = (1, 3, 7, 15)
MAX_TIMELINE_SPAN_DAYS = 90


# 观察类路由前缀：成功与错误响应均使用 OBSERVATION_VERSION；
# 其余 /api/v1 路由（预测/驾驶舱/地图/事件）使用 PREDICTION_VERSION。
_OBSERVATION_PATHS = (
    "/api/health",
    "/api/v1/system",
    "/api/v1/datasets",
    "/api/v1/pipeline",
    "/api/v1/spatial-entities",
)


def dataset_version_for_path(path: str) -> str:
    """集中式"请求路径 → OBS/PRED 数据身份"解析。

    RequestValidationError、兜底 500 等脱离路由上下文的错误出口
    必须经此选择 dataset_version，不得固定为预测版本。
    """
    if any(path == p or path.startswith(f"{p}/") for p in _OBSERVATION_PATHS):
        return OBSERVATION_VERSION
    return PREDICTION_VERSION


def risk_level(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "mid"
    return "low"


def request_id_of(request: Any) -> str:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = f"req_{uuid4().hex}"
        request.state.request_id = request_id
    return request_id


def response_meta(request: Any, *, dataset_version: str, prediction_run_id: str | None = None) -> dict[str, Any]:
    return {
        "data_mode": DATA_MODE,
        "dataset_version": dataset_version,
        "prediction_run_id": prediction_run_id,
        "as_of": AS_OF,
        "claim_boundary": CLAIM_BOUNDARY,
        "request_id": request_id_of(request),
    }


def envelope(
    request: Any,
    data: Any,
    *,
    dataset_version: str,
    prediction_run_id: str | None = None,
) -> dict[str, Any]:
    """统一成功信封。meta 固定六键，任何字段不得在 data/meta 间漂移。"""
    return {
        "code": 200,
        "message": "ok",
        "data": data,
        "meta": response_meta(request, dataset_version=dataset_version, prediction_run_id=prediction_run_id),
        "errors": [],
    }
