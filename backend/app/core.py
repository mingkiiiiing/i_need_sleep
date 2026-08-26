from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException


def api_response(data: Any, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": 200,
        "message": "success",
        "data": data,
        "meta": {"request_id": f"req_{uuid4().hex}", **(meta or {})},
        "errors": [],
    }


def api_error(*, status_code: int, code: str, message: str) -> dict[str, Any]:
    """Return a public, stable error contract without implementation details."""
    return {
        "code": status_code,
        "message": message,
        "data": None,
        "meta": {"request_id": f"req_{uuid4().hex}", "generated_at": datetime.now(timezone.utc).isoformat()},
        "errors": [{"code": code, "message": message}],
    }


def response_meta(*, data_mode: str, dataset_version: str, claim_boundary: str) -> dict[str, Any]:
    return {
        "data_mode": data_mode,
        "dataset_version": dataset_version,
        "claim_boundary": claim_boundary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def not_found(code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": detail})


def capability_unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "CAPABILITY_UNAVAILABLE", "message": detail})


def data_mode_unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "DATA_MODE_UNAVAILABLE", "message": detail})


def invalid_query_range(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "INVALID_QUERY_RANGE", "message": detail})
