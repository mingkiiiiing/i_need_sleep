"""统一气象驱动层：真实历史气象重放 (observed_replay, 设计 §7 大任务1).

历史逐日气象（ingest-history 发布表）广播到网格 + 统计拟合的微小空间偏差，
风向由观测 u/v 推导；热浪/静风/暴雨情景扰动与合成天气共用 weather.py helper，
作用在湖区均值序列上后空间化。驱动表随仿真运行落盘（latent/weather_driver_{zone}.parquet），
算法特征与标签由此同源；run 级 driver_hash 传播至 bloom/labels/samples 供 A24 门禁。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .rng import sample_field
from .weather import apply_calm_cap, apply_heatwave, apply_storm_pulse

BASE_SOURCE = "open_meteo_history"
DRIVER_VARIABLES = ("air_temperature", "wind_direction", "wind_speed", "shortwave_radiation", "precipitation", "relative_humidity", "cloud_cover")
REPLAY_REQUIRED_COLUMNS = ("air_temperature", "wind_speed", "wind_u", "wind_v", "precipitation", "shortwave_radiation")
AVAILABILITY_LAG_DAYS = 1  # 日值气象次日出账（与装配特征可见性一致）
SYNTHETIC_META = {"driver_type": "synthetic", "base_source": "synthetic_climatology_ar1"}


def load_observed_window(base_dir: Path, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """读取并校验重放窗口内的历史逐日观测气象（缺日/缺变量 fail fast）。"""
    path = base_dir / "history" / "weather_observed_daily.parquet"
    if not path.exists():
        raise SystemExit(f"observed replay driver missing: {path} (run: python -m data_factory ingest-history)")
    obs = pd.read_parquet(path)
    obs["date"] = pd.to_datetime(obs["date"])
    window = obs.set_index("date").reindex(pd.DatetimeIndex(dates))
    absent = [col for col in REPLAY_REQUIRED_COLUMNS if col not in window.columns or window[col].isna().any()]
    if absent:
        raise SystemExit(f"observed weather incomplete for replay {dates[0].date()}..{dates[-1].date()}: {absent}")
    return window


def build_replay_driver(
    base_dir: Path,
    dates: pd.DatetimeIndex,
    modes: np.ndarray,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    scenario: dict[str, Any],
) -> tuple[dict[str, np.ndarray], pd.DataFrame, dict[str, str]]:
    """真实气象重放 → (逐格数组, 湖区均值驱动, 驱动身份元数据)。

    湖区均值序列先叠加热浪/静风/暴雨扰动与 climate_shift，再广播到网格并加
    AR(1) 空间相关微偏差（幅度取 mechanism.weather.spatial_deviation.observed_replay，
    phi 复用合成模式对应变量取值）。湿度/云量为内部合成次级变量（观测源无此两列，
    禁止进入算法特征，A14）。
    """
    T, N = len(dates), modes.shape[0]
    months = dates.month.to_numpy()
    cfg = mechanism.get("weather", {})
    spatial_cfg = cfg.get("spatial_deviation", {})
    replay_cfg = spatial_cfg.get("observed_replay", {})
    rng = rngs["weather"]
    extremes = scenario.get("extremes") or {}

    window = load_observed_window(base_dir, dates)

    ta = window["air_temperature"].to_numpy(dtype=float) + float(scenario.get("climate_shift_deg", 0.0))
    ws = window["wind_speed"].to_numpy(dtype=float)
    rad = window["shortwave_radiation"].to_numpy(dtype=float)
    precip = np.clip(window["precipitation"].to_numpy(dtype=float), 0.0, None)
    wind_dir = np.degrees(np.arctan2(window["wind_v"].to_numpy(dtype=float), window["wind_u"].to_numpy(dtype=float))) % 360.0

    ta = np.clip(apply_heatwave(ta, months, extremes, rng), -10.0, 45.0)
    ws = np.clip(apply_calm_cap(ws, months, extremes), 0.0, 25.0)
    precip = np.clip(apply_storm_pulse(precip, months, extremes, rng), 0.0, 400.0)

    def spatialize(anomaly: np.ndarray, variable: str, additive: bool) -> np.ndarray:
        spec = replay_cfg.get(variable, {})
        amp = float(spec.get("amp_c", spec.get("amp_rel", 0.0)))
        phi = float(spatial_cfg.get(variable, {}).get("phi", 0.7))
        field = np.empty((T, N))
        prev = None
        for t in range(T):
            prev = np.clip(sample_field(rng, modes, phi, prev), -3.0, 3.0)
            field[t] = anomaly[t] + amp * prev if additive else anomaly[t] * (1.0 + amp * prev)
        return field

    ta_grid = spatialize(ta, "air_temperature", additive=True)
    ws_grid = spatialize(ws, "wind_speed", additive=False)
    rad_grid = spatialize(rad, "shortwave_radiation", additive=False)

    amp_p = float(replay_cfg.get("precipitation", {}).get("amp_rel", 0.0))
    phi_p = float(spatial_cfg.get("precipitation", {}).get("phi", 0.6))
    precip_grid = np.empty((T, N))
    prev_p = None
    for t in range(T):
        prev_p = sample_field(rng, modes, phi_p, prev_p)
        precip_grid[t] = precip[t] * np.exp(amp_p * prev_p - amp_p**2 / 2)
    precip_grid = np.clip(precip_grid, 0.0, None)

    # 次级变量：湿度与温度距平自洽，云量与降水状态耦合（写明简化）
    hum_cfg = cfg.get("humidity", {})
    humidity = np.clip(
        float(hum_cfg.get("base_pct", 78)) - float(hum_cfg.get("temp_sensitivity_pct_per_c", 1.2)) * (ta - np.array([np.mean(ta[months == m]) if (months == m).any() else 17.0 for m in months])) + rng.normal(0.0, 5.0, T),
        20.0,
        100.0,
    )
    cloud_cfg = cfg.get("cloud", {})
    cloud_phi = float(cloud_cfg.get("phi", 0.6))
    cloud_mean = np.where(precip > 0.0, float(cloud_cfg.get("wet_day_mean", 0.8)), float(cloud_cfg.get("dry_day_mean", 0.35)))
    cloud = np.empty(T)
    cloud[0] = cloud_mean[0]
    for t in range(1, T):
        cloud[t] = cloud_phi * cloud[t - 1] + (1 - cloud_phi) * cloud_mean[t] + rng.normal(0.0, 0.08)
    cloud = np.clip(cloud, 0.0, 1.0)

    arrays = {
        "air_temperature": ta_grid,
        "wind_speed": ws_grid,
        "wind_direction": np.repeat(wind_dir[:, None], N, axis=1),
        "shortwave_radiation": rad_grid,
        "precipitation": precip_grid,
        "relative_humidity": np.clip(humidity[:, None] + rng.normal(0.0, 3.0, (T, N)), 15.0, 100.0),
        "cloud_cover": np.clip(cloud[:, None] + rng.normal(0.0, 0.1, (T, N)), 0.0, 1.0),
    }
    lake_mean = pd.DataFrame(
        {
            "date": dates,
            "air_temperature": ta,
            "wind_speed": ws,
            "wind_direction": wind_dir,
            "shortwave_radiation": rad,
            "precipitation": precip,
            "relative_humidity": humidity,
            "cloud_cover": cloud,
            "wet_day": precip > 0.0,
        }
    )
    return arrays, lake_mean, {"driver_type": "observed_replay", "base_source": BASE_SOURCE}


def build_driver_frame(
    dates: pd.DatetimeIndex,
    grid_ids: list[str],
    arrays: dict[str, np.ndarray],
    meta: dict[str, str],
    scenario_id: str,
    seed: int,
) -> pd.DataFrame:
    """单 zone 网格级驱动表（engine 落盘 + 参与哈希；身份列随行携带）。"""
    frame = pd.DataFrame(
        {
            "date": np.repeat(pd.DatetimeIndex(dates), len(grid_ids)),
            "grid_id": np.tile(np.array(grid_ids), len(dates)),
        }
    )
    for variable in DRIVER_VARIABLES:
        frame[variable] = arrays[variable].round(6).ravel()
    frame["available_time"] = frame["date"] + pd.Timedelta(days=AVAILABILITY_LAG_DAYS)
    frame["driver_type"] = meta["driver_type"]
    frame["scenario_id"] = scenario_id
    frame["random_seed"] = int(seed)
    frame["base_source"] = meta["base_source"]
    return frame


def frame_driver_hash(frame: pd.DataFrame) -> str:
    """驱动表内容指纹：逐行 64 位哈希字节流 → sha256（顺序与值敏感、确定可复现）。"""
    columns = [c for c in frame.columns if c != "driver_hash"]
    digest = pd.util.hash_pandas_object(frame[columns], index=True).to_numpy(dtype="uint64")
    return hashlib.sha256(digest.tobytes()).hexdigest()


def run_driver_hash(frames: list[pd.DataFrame], meta: dict[str, str], scenario_id: str, seed: int, dates: pd.DatetimeIndex) -> str:
    """run 级 driver_hash：驱动身份元数据 + 各 zone 驱动表指纹（排序后拼接）。"""
    zone_hashes = sorted(frame_driver_hash(frame) for frame in frames)
    payload = json.dumps(
        {
            "base_source": meta["base_source"],
            "driver_type": meta["driver_type"],
            "scenario_id": scenario_id,
            "random_seed": int(seed),
            "start": str(dates[0].date()),
            "end": str(dates[-1].date()),
            "zone_driver_hashes": zone_hashes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
