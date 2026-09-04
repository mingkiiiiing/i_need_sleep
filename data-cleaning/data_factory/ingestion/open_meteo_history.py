"""Open-Meteo 历史气象批量下载 (taihugurad openmeteo_fetcher.py 重写式适配)。

流量闸门：估算 > warn_mb 且未给 assume_yes=True 时拒绝下载（BLOCKED_CONFIRM）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory.contracts.constants import RAW_ROOT
from .raw_store import write_raw_snapshot

SOURCE_ID = "open_meteo_history"

PARAM_MAPPING: dict[str, str] = {
    "temperature_2m": "air_temperature",
    "relative_humidity_2m": "relative_humidity",
    "dewpoint_2m": "dewpoint",
    "precipitation": "precipitation",
    "rain": "rain",
    "wind_speed_10m": "wind_speed",
    "wind_direction_10m": "wind_direction",
    "wind_gusts_10m": "wind_gusts",
    "shortwave_radiation": "shortwave_radiation",
    "direct_radiation": "direct_radiation",
    "diffuse_radiation": "diffuse_radiation",
    "surface_pressure": "surface_pressure",
    "cloud_cover": "cloud_cover",
    "et0_fao_evapotranspiration": "et0_evapotranspiration",
    "soil_temperature_0_to_7cm": "soil_temperature",
}


def estimate_download_mb(n_points: int, start: str, end: str, mb_per_point_year: float = 1.1) -> float:
    years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 0.0)
    return round(n_points * years * mb_per_point_year, 1)


def _segments(start: str, end: str, segment_years: int) -> list[tuple[str, str]]:
    bounds = pd.date_range(start, end, freq=f"{segment_years}YS")
    edges = [pd.Timestamp(start)] + list(bounds) + [pd.Timestamp(end) + pd.Timedelta(days=1)]
    segments = []
    for a, b in zip(edges[:-1], edges[1:]):
        b = min(b, pd.Timestamp(end))
        if a <= b:
            segments.append((a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")))
    return segments


def fetch_point(
    lat: float,
    lon: float,
    start: str,
    end: str,
    *,
    hourly_params: list[str],
    timezone: str = "Asia/Shanghai",
    base_url: str = "https://archive-api.open-meteo.com/v1/archive",
    throttle_s: float = 3.0,
    segment_years: int = 2,
) -> pd.DataFrame:
    import requests

    frames: list[pd.DataFrame] = []
    for seg_start, seg_end in _segments(start, end, segment_years):
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": seg_start,
            "end_date": seg_end,
            "hourly": ",".join(hourly_params),
            "timezone": timezone,
        }
        for attempt in range(1, 4):
            resp = requests.get(base_url, params=params, timeout=120)
            if resp.status_code == 429:
                time.sleep(30 * attempt)
                continue
            resp.raise_for_status()
            break
        body = resp.json()
        hourly = body.get("hourly", {})
        frame = pd.DataFrame(hourly)
        frame = frame.rename(columns=PARAM_MAPPING)
        frame["lat"] = lat
        frame["lon"] = lon
        frames.append(frame)
        time.sleep(throttle_s)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def pick_grid_points(cells: pd.DataFrame, *, max_points: int, spacing_km: float) -> pd.DataFrame:
    """从冻结网格等距抽样下载点（坐标与网格一致，血缘可追溯）。"""

    candidates = cells.sort_values("grid_id").reset_index(drop=True)
    if len(candidates) <= max_points:
        return candidates[["grid_id", "lon", "lat"]]
    step = max(len(candidates) // max_points, 1)
    picked = candidates.iloc[::step].head(max_points)
    return picked[["grid_id", "lon", "lat"]]


def run_open_meteo_history(
    config: dict[str, Any],
    *,
    start: str,
    end: str,
    cells: pd.DataFrame,
    out_dir: Path,
    raw_root: Path | None = None,
    assume_yes: bool = False,
) -> dict[str, Any]:
    cfg = (config.get("realtime_sources") or {}).get("open_meteo_history") or {}
    if not cfg.get("enabled", True):
        return {"status": "disabled", "command": "collect-realtime", "rows_written": 0}
    points = pick_grid_points(cells, max_points=int(cfg.get("max_points", 20)), spacing_km=float(cfg.get("point_spacing_km", 7)))
    est_mb = estimate_download_mb(len(points), start, end, float(config.get("download", {}).get("est_mb_per_point_year", 1.1)))
    warn_mb = float(config.get("download", {}).get("warn_mb", 50))
    if est_mb > warn_mb and not assume_yes:
        return {
            "status": "BLOCKED_CONFIRM",
            "command": "collect-realtime",
            "estimated_mb": est_mb,
            "warn_mb": warn_mb,
            "n_points": int(len(points)),
            "message": f"预计下载约 {est_mb} MB（> {warn_mb} MB 闸门）。确认带宽后加 --yes 重跑。",
        }

    raw_root = raw_root or RAW_ROOT
    frames: list[pd.DataFrame] = []
    for row in points.itertuples(index=False):
        frame = fetch_point(
            row.lat,
            row.lon,
            start,
            end,
            hourly_params=list(cfg.get("hourly_params", list(PARAM_MAPPING))),
            timezone=cfg.get("timezone", "Asia/Shanghai"),
            base_url=cfg.get("base_url", "https://archive-api.open-meteo.com/v1/archive"),
            throttle_s=float(cfg.get("throttle_s", 3.0)),
            segment_years=int(cfg.get("segment_years", 2)),
        )
        frame["grid_id"] = row.grid_id
        frames.append(frame)
        snapshot_payload = frame.to_csv(index=False).encode("utf-8")
        write_raw_snapshot(
            SOURCE_ID,
            snapshot_payload,
            raw_root=raw_root,
            request_url=cfg.get("base_url", ""),
            extra={"grid_id": row.grid_id, "start": start, "end": end, "format": "csv"},
        )
    result = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "open_meteo_history.csv"
    result.to_csv(output, index=False)
    return {
        "status": "completed",
        "command": "collect-realtime",
        "source_id": SOURCE_ID,
        "n_points": int(len(points)),
        "rows_written": int(len(result)),
        "estimated_mb": est_mb,
        "output": str(output),
    }
