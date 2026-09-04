"""确定性哈希与样本 ID (设计 §9 血缘)."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np


def _canonical(value: Any) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def row_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_canonical(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_sample_id(
    *,
    spatial_id: str,
    issue_time: str,
    target_date: str,
    task_id: str,
    horizon: int,
    dataset_version: str,
) -> str:
    key = "|".join([spatial_id, issue_time, target_date, task_id, str(horizon), dataset_version])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
