"""A23 backend entry point.

Provider 配置在导入期校验：OBSERVATION_PROVIDER / PREDICTION_PROVIDER
指向未实现实现时应用直接启动失败，绝不静默回退 simulated。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:  # Supports `python -m uvicorn backend.main:app` from the repository root.
    from .app import errors as err
    from .app.api import router
    from .app.contracts import (
        AS_OF,
        CLAIM_BOUNDARY,
        DATA_MODE,
        dataset_version_for_path,
        request_id_of,
    )
    from .app.providers import (
        OBSERVATION_PROVIDER_ENV,
        PREDICTION_PROVIDER_ENV,
        create_observation_provider,
        create_prediction_provider,
    )
    from .app.services import service
except ImportError:  # pragma: no cover - supports `python -m uvicorn main:app` in backend/.
    from app import errors as err
    from app.api import router
    from app.contracts import (
        AS_OF,
        CLAIM_BOUNDARY,
        DATA_MODE,
        dataset_version_for_path,
        request_id_of,
    )
    from app.providers import (
        OBSERVATION_PROVIDER_ENV,
        PREDICTION_PROVIDER_ENV,
        create_observation_provider,
        create_prediction_provider,
    )
    from app.services import service

logger = logging.getLogger("uvicorn.error")

app = FastAPI(
    title="蓝藻水华监测预警系统 API",
    description="统一信封的模拟数据联调服务。所有模拟值均带有数据版本和非决策声明。",
    version="2.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Provider 配置: %s=%s %s=%s（未配置时默认 simulated）",
        OBSERVATION_PROVIDER_ENV,
        service.observation.name(),
        PREDICTION_PROVIDER_ENV,
        service.prediction.name(),
    )
    yield


app.router.lifespan_context = lifespan


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = f"req_{uuid4().hex}"
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


def _error_payload(request: Request, *, status_code: int, code: str, message: str, field: str | None, detail: str, dataset_version: str) -> dict[str, Any]:
    return {
        "code": status_code,
        "message": message,
        "data": None,
        "meta": {
            "data_mode": DATA_MODE,
            "dataset_version": dataset_version or dataset_version_for_path(request.url.path),
            "prediction_run_id": None,
            "as_of": AS_OF,
            "claim_boundary": CLAIM_BOUNDARY,
            "request_id": request_id_of(request),
        },
        "errors": [{"code": code, "field": field, "detail": detail}],
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = err.error_detail(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(
            request,
            status_code=exc.status_code,
            code=detail["code"],
            message=detail["message"],
            field=detail["field"],
            detail=detail["detail"],
            dataset_version=detail["dataset_version"],
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", []) if part != "body") or None
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            request,
            status_code=422,
            code=err.REQUEST_VALIDATION_FAILED,
            message="请求参数或请求体不符合接口契约",
            field=field,
            detail=str(first.get("msg", "validation failed")),
            dataset_version=dataset_version_for_path(request.url.path),
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_payload(
            request,
            status_code=500,
            code=err.INTERNAL_ERROR,
            message="服务内部错误",
            field=None,
            detail="internal error",
            dataset_version=dataset_version_for_path(request.url.path),
        ),
    )


@app.get("/")
def root(request: Request):
    from .app.contracts import envelope
    from .app.contracts import OBSERVATION_VERSION

    return envelope(
        request,
        {"name": "蓝藻水华监测预警系统 API", "version": app.version, "docs": "/docs", "stage": "P0 simulated integration"},
        dataset_version=OBSERVATION_VERSION,
    )


@app.get("/api/health")
def health(request: Request):
    from .app.contracts import envelope, OBSERVATION_VERSION

    return envelope(
        request,
        {"status": "ok", "data_mode": DATA_MODE, "service": "a23-backend"},
        dataset_version=OBSERVATION_VERSION,
    )
