"""A23 backend entry point.

Provider 配置在导入期校验：OBSERVATION_PROVIDER / PREDICTION_PROVIDER
指向未实现实现时应用直接启动失败，绝不静默回退 simulated。
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

try:  # Supports `python -m uvicorn backend.main:app` from the repository root.
    from .app import errors as err
    from .app.alert_center import alert_center
    from .app.alerts import ALERT_CONFIG_PATH
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
    from .app.services import alert_engine, service
except ImportError:  # pragma: no cover - supports `python -m uvicorn main:app` in backend/.
    from app import errors as err
    from app.alert_center import alert_center
    from app.alerts import ALERT_CONFIG_PATH
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
    from app.services import alert_engine, service

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

# 卫星遥感年度 PNG（build_rs_overlays.py 生成产物）；目录缺失时跳过挂载，/rs/manifest 会给出明确错误
_RS_OVERLAYS_DIR = Path(__file__).resolve().parent / "rs_overlays"
if _RS_OVERLAYS_DIR.is_dir():
    app.mount("/rs", StaticFiles(directory=str(_RS_OVERLAYS_DIR)), name="rs")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Provider 配置: %s=%s %s=%s（未配置时默认 simulated）",
        OBSERVATION_PROVIDER_ENV,
        service.observation.name(),
        PREDICTION_PROVIDER_ENV,
        service.prediction.name(),
    )
    # 预警后台巡检：随服务常驻，按 alerts-config.json 的 evaluate_interval_s 周期评估
    # 最新快照并自动推送（通道未配置时只评估记录、投递记 skipped）。首轮评估在启动后
    # 先同步一次预警中心（历史告警导入事件），随后延迟一个周期，避免与应用启动抢实时目录；
    # 手动巡检走 POST /realtime/alerts/evaluate。
    try:
        alert_center.bootstrap()
        alert_center.sync_from_engine()
    except Exception as exc:  # noqa: BLE001 — 中心同步失败不阻断应用启动
        logger.warning("预警中心启动同步失败（下轮巡检重试）: %s", exc)
    alert_stop = threading.Event()
    alert_thread = threading.Thread(
        target=alert_center.run_forever,
        args=(alert_stop,),
        name="alert-evaluator",
        daemon=True,
    )
    alert_thread.start()
    logger.info(
        "预警巡检线程已启动: interval=%ss enabled=%s config=%s",
        alert_engine.interval_s,
        alert_engine.enabled,
        ALERT_CONFIG_PATH if ALERT_CONFIG_PATH.exists() else "未创建（未启用推送）",
    )
    # 站点级预测引擎预热：首次构建需数秒（全量样本训练+交叉验证），后台完成后
    # 首个请求直接命中缓存；失败不阻断启动，首次请求时按懒构建语义重试。
    def _warm_station_forecast() -> None:
        try:
            status = service.realtime_station_forecast_status()
            logger.info("站点级预测引擎预热完成: status=%s", status.get("status"))
        except Exception as exc:  # noqa: BLE001 — 预热失败留痕，不阻断应用启动
            logger.warning("站点级预测引擎预热失败（首次请求时重试）: %s", exc)
    threading.Thread(target=_warm_station_forecast, name="station-fc-warmup", daemon=True).start()
    try:
        yield
    finally:
        alert_stop.set()
        alert_thread.join(timeout=5)


app.router.lifespan_context = lifespan


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = f"req_{uuid4().hex}"
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


def _error_payload(request: Request, *, status_code: int, code: str, message: str, field: str | None, detail: str, dataset_version: str, track: dict[str, str] | None = None) -> dict[str, Any]:
    track = track or {}
    return {
        "code": status_code,
        "message": message,
        "data": None,
        "meta": {
            "data_mode": track.get("data_mode") or DATA_MODE,
            "dataset_version": dataset_version or dataset_version_for_path(request.url.path),
            "prediction_run_id": None,
            "as_of": track.get("as_of") or AS_OF,
            "claim_boundary": track.get("claim_boundary") or CLAIM_BOUNDARY,
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
            track=detail.get("track"),
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
