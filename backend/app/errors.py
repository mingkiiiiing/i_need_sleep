"""统一错误契约：稳定错误码 + ApiError 工厂。

错误响应由 main.py 的异常处理器渲染为：
{"code": <http>, "message": ..., "data": null, "meta": {...}, "errors": [{"code", "field", "detail"}]}
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# ---- 公共稳定错误码 ----
INVALID_DATE_RANGE = "INVALID_DATE_RANGE"          # 422 查询日期范围无效（如 start 晚于 end）
QUERY_RANGE_TOO_LARGE = "QUERY_RANGE_TOO_LARGE"    # 422 查询跨度超过上限
INVALID_HORIZON = "INVALID_HORIZON"                # 422 预测档位不受支持
ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"              # 404 演示对象/预测记录不存在
FORECAST_NOT_AVAILABLE = "FORECAST_NOT_AVAILABLE"  # 409 预测记录存在但当前 Provider 无法提供
CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"  # 409 能力阻塞（如 30—90 天预测未就绪）
INVALID_EVENT_ID = "INVALID_EVENT_ID"              # 422 事件/演示对象引用不存在
SIMULATION_ONLY = "SIMULATION_ONLY"                # 409 请求真实数据/正式能力，当前仅提供模拟演示
REQUEST_VALIDATION_FAILED = "REQUEST_VALIDATION_FAILED"  # 422 参数类型/格式不合法（兜底）
INTERNAL_ERROR = "INTERNAL_ERROR"                  # 500 兜底

_DATASET_VERSION_KEY = "_dataset_version"


class ApiError(HTTPException):
    """携带稳定错误码的 HTTPException；detail 由异常处理器渲染为统一信封。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        detail: str | None = None,
        dataset_version: str = "",
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                "field": field,
                "detail": detail or message,
                _DATASET_VERSION_KEY: dataset_version,
            },
        )


def error_detail(exc: HTTPException) -> dict[str, Any]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return {
        "code": detail.get("code", "REQUEST_FAILED"),
        "message": detail.get("message", "请求未能完成"),
        "field": detail.get("field"),
        "detail": detail.get("detail", detail.get("message", "请求未能完成")),
        "dataset_version": detail.get(_DATASET_VERSION_KEY, ""),
    }


def invalid_date_range(message: str, *, field: str | None = None, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=422, code=INVALID_DATE_RANGE, message=message, field=field, detail=detail, dataset_version=dataset_version)


def query_range_too_large(message: str, *, field: str | None = None, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=422, code=QUERY_RANGE_TOO_LARGE, message=message, field=field, detail=detail, dataset_version=dataset_version)


def invalid_horizon(message: str, *, field: str = "horizon_days", detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=422, code=INVALID_HORIZON, message=message, field=field, detail=detail, dataset_version=dataset_version)


def entity_not_found(message: str, *, dataset_version: str, detail: str | None = None) -> ApiError:
    return ApiError(status_code=404, code=ENTITY_NOT_FOUND, message=message, dataset_version=dataset_version, detail=detail)


def forecast_not_available(message: str, *, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=409, code=FORECAST_NOT_AVAILABLE, message=message, detail=detail, dataset_version=dataset_version)


def capability_unavailable(message: str, *, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=409, code=CAPABILITY_UNAVAILABLE, message=message, detail=detail, dataset_version=dataset_version)


def invalid_event_id(message: str, *, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=422, code=INVALID_EVENT_ID, message=message, field="event_id", detail=detail, dataset_version=dataset_version)


def simulation_only(message: str, *, detail: str | None = None, dataset_version: str = "") -> ApiError:
    return ApiError(status_code=409, code=SIMULATION_ONLY, message=message, detail=detail, dataset_version=dataset_version)
