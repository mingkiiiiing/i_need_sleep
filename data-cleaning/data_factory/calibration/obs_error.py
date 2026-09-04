"""观测层误差参数 (设计 §6.11/§6.12/§6.7)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def satellite_valid_rates(pattern: pd.DataFrame, cloud_threshold: float = 0.7) -> pd.DataFrame:
    """月度有效（无云可用）率：cloud_ratio 越小越可用。"""

    if pattern.empty:
        return pd.DataFrame(columns=["month", "valid_rate", "n"])
    frame = pattern.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["month"] = frame["date"].dt.month
    frame["cloud_ratio"] = pd.to_numeric(frame["cloud_ratio"], errors="coerce").fillna(0.0)
    grouped = frame.groupby("month")["cloud_ratio"]
    return pd.DataFrame({"valid_rate": (grouped.apply(lambda s: float((s < cloud_threshold).mean()))), "n": grouped.size()})


def sampling_counts(pattern: pd.DataFrame) -> pd.DataFrame:
    """站点×月采样频次（真实采样日历直接作为仿真采样日期来源）。"""

    if pattern.empty:
        return pd.DataFrame(columns=["station_id", "month", "n_sample_days"])
    frame = pattern.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["month"] = frame["date"].dt.month
    return frame.groupby(["station_id", "month"]).size().reset_index(name="n_sample_days")


def publish_delay_hours(water_quality: pd.DataFrame) -> dict[str, float]:
    frame = water_quality
    if frame.empty or "acquired_at" not in frame.columns or "observed_at" not in frame.columns:
        return {"p50": 6.0, "p90": 24.0, "n": 0}
    observed = pd.to_datetime(frame["observed_at"], errors="coerce", utc=True)
    acquired = pd.to_datetime(frame["acquired_at"], errors="coerce", utc=True)
    delta = (acquired - observed).dt.total_seconds().dropna() / 3600.0
    delta = delta[(delta >= 0) & (delta < 24 * 30)]
    if delta.empty:
        return {"p50": 6.0, "p90": 24.0, "n": 0}
    return {"p50": float(np.percentile(delta, 50)), "p90": float(np.percentile(delta, 90)), "n": int(len(delta))}


def detection_limits(mechanism: dict[str, Any]) -> dict[str, float]:
    return dict((mechanism.get("obs") or {}).get("detection_limits") or {})


def measurement_error_pct(mechanism: dict[str, Any]) -> dict[str, float]:
    return dict((mechanism.get("obs") or {}).get("measurement_error_pct") or {"default": 10.0})
