from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


def api_response(data: Any, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": 200,
        "message": "success",
        "data": data,
        "meta": meta or {},
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
