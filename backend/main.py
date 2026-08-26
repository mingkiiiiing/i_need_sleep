"""A23 backend entry point."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:  # Supports `python -m uvicorn backend.main:app` from the repository root.
    from .app.api import router
    from .app.core import api_error, api_response
except ImportError:  # pragma: no cover - supports `python -m uvicorn main:app` in backend/.
    from app.api import router
    from app.core import api_error, api_response

app = FastAPI(
    title="蓝藻水华监测预警系统 API",
    description="P0 模拟数据联调服务。所有模拟值均带有数据版本和非决策声明。",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=api_error(
            status_code=exc.status_code,
            code=detail.get("code", "REQUEST_FAILED"),
            message=detail.get("message", "请求未能完成"),
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=api_error(
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
            message="请求参数或请求体不符合接口契约",
        ),
    )


@app.get("/")
def root():
    return api_response({"name": "蓝藻水华监测预警系统 API", "version": app.version, "docs": "/docs", "stage": "P0 simulated integration"})


@app.get("/api/health")
def health():
    return api_response({"status": "ok", "data_mode": "simulated", "service": "a23-backend"})
