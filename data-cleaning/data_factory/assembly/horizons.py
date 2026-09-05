"""时效展开与特征装配 `assemble` (设计 §6.14/§9 T+1/3/7/15/30).

task_labels（目标日真值）→ 训练样本：issue_date = target_date − h；
气象特征来自 run 驱动表（df-0.3.0 统一气象驱动，与标签同源）：zone/lake 用
latent/weather_daily（驱动湖区均值），grid 样本用 latent/weather_driver 逐格值；
station/卫星为观测层且只取 available_time ≤ issue_date 的记录；latent 层
（水位/营养盐/生物量等）一律不进入特征。
issue_date 早于驱动窗 + max(lag) 的样本无法构成同源滞后窗口，整行拒绝（设计装配要求）。
sample_id = sha256(spatial_id|issue_time|target_date|task_id|horizon|dataset_version|scenario_id|random_seed|driver_hash)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory import GENERATOR_VERSION
from data_factory.contracts.constants import utc_now_iso
from data_factory.contracts.enums import HORIZONS, TASK_UNITS, Track
from data_factory.lineage.hashing import compute_sample_id, content_hash, row_hash
from data_factory.simulation.driver import AVAILABILITY_LAG_DAYS

FEATURE_LAGS = (1, 3, 7, 14, 30)
FEATURE_ROLLS = (3, 7, 14, 30)
WEATHER_FEATURES = ("air_temperature", "wind_speed", "precipitation", "shortwave_radiation")
STATION_FEATURES = ("water_temperature", "total_phosphorus", "total_nitrogen")
CORE_FEATURES = WEATHER_FEATURES + STATION_FEATURES + ("chlorophyll_a", "bloom_fraction")
AUX_FEATURES = tuple(c for c in CORE_FEATURES if c not in WEATHER_FEATURES)
SATELLITE_CHLA_BLOOM_UG_L = 30.0  # 与 label_thresholds.chla.warning 一致
WEATHER_AVAILABILITY_LAG_DAYS = AVAILABILITY_LAG_DAYS  # 日值气象次日出账（与驱动表一致）


def _run_weather_frame(sim_dir: Path, zone_code: str) -> pd.DataFrame:
    """run 驱动的 zone 均值气象帧（索引=可阅日=气象日+1，与标签同源）。"""
    path = sim_dir / "latent" / f"weather_daily_{zone_code}.parquet"
    if not path.exists():
        raise SystemExit(f"run weather table missing: {path} (先 python -m data_factory simulate)")
    weather = pd.read_parquet(path)
    weather["date"] = pd.to_datetime(weather["date"]) + pd.Timedelta(days=WEATHER_AVAILABILITY_LAG_DAYS)
    frame = weather.set_index("date")[list(WEATHER_FEATURES)].sort_index()
    return frame[~frame.index.duplicated(keep="last")]


def _observation_series(base_dir: Path) -> dict[str, pd.Series]:
    """观测层特征序列（available_time 聚合）：station 水温/TP/TN + 卫星 chla/bloom。"""
    obs_dir = base_dir / "observations"
    series: dict[str, pd.Series] = {}
    station_path = obs_dir / "station_observations.parquet"
    if station_path.exists():
        station = pd.read_parquet(station_path, columns=["variable_code", "value", "available_time"])
        station = station[station["variable_code"].isin(STATION_FEATURES) & station["value"].notna()]
        for variable in STATION_FEATURES:
            rows = station[station["variable_code"] == variable]
            if not rows.empty:
                avail = pd.to_datetime(rows["available_time"]).dt.normalize()
                series[variable] = rows.groupby(avail)["value"].mean()

    sat_path = obs_dir / "satellite_observations.parquet"
    if sat_path.exists():
        sat = pd.read_parquet(sat_path, columns=["variable_code", "value", "available_time"])
        sat = sat[(sat["variable_code"] == "chla_retrieval") & sat["value"].notna()]
        if not sat.empty:
            avail = pd.to_datetime(sat["available_time"]).dt.normalize()
            series["chlorophyll_a"] = sat.groupby(avail)["value"].mean()
            series["bloom_fraction"] = sat.assign(_pos=(sat["value"] >= SATELLITE_CHLA_BLOOM_UG_L)).groupby(avail)["_pos"].mean()
    return series


def _feature_source_frames(
    sim_dir: Path, base_dir: Path, zone_codes: list[str], dates: pd.DatetimeIndex
) -> tuple[dict[str, pd.DataFrame], pd.Timestamp]:
    """zone/lake 特征源帧（气象=run 驱动同源 + 观测层 station/sat），共享同一 union 索引。

    lake 帧气象取各 zone 驱动均值的再平均；观测层序列无 zone 分辨率，按日对齐。
    第二返回值为驱动气象可阅起点（min_issue_date 判定用）。
    """
    weather_frames = {zone: _run_weather_frame(sim_dir, zone) for zone in zone_codes}
    weather_start = min(frame.index.min() for frame in weather_frames.values())
    obs = _observation_series(base_dir)
    union = set(pd.DatetimeIndex(dates))
    for frame in weather_frames.values():
        union |= set(frame.index)
    for series in obs.values():
        union |= set(series.index)
    index = pd.DatetimeIndex(sorted(union))
    frames: dict[str, pd.DataFrame] = {}
    for zone, weather in weather_frames.items():
        frame = weather.reindex(index).astype(float)
        for name, series in obs.items():
            frame[name] = series.reindex(index)
        frames[zone] = frame
    weather_cols = list(WEATHER_FEATURES)
    stacked = pd.concat([frames[zone][weather_cols] for zone in weather_frames], keys=list(weather_frames))
    lake = stacked.groupby(level=1).mean().reindex(index)
    for name, series in obs.items():
        lake[name] = series.reindex(index)
    frames["TAIHU_WHOLE"] = lake
    return frames, weather_start


def _grid_weather_long(sim_dir: Path, zone_codes: list[str]) -> pd.DataFrame:
    """逐格气象长表 (grid_id × 可阅日)，来自 run 驱动表（与标签同源）。"""
    frames = []
    for zone in zone_codes:
        path = sim_dir / "latent" / f"weather_driver_{zone}.parquet"
        if not path.exists():
            raise SystemExit(f"run driver table missing: {path} (先 python -m data_factory simulate)")
        frames.append(pd.read_parquet(path, columns=["date", "grid_id", *WEATHER_FEATURES]))
    long_frame = pd.concat(frames, ignore_index=True)
    long_frame["date"] = pd.to_datetime(long_frame["date"]) + pd.Timedelta(days=WEATHER_AVAILABILITY_LAG_DAYS)
    return long_frame.sort_values(["grid_id", "date"]).reset_index(drop=True)


def _augment_grid_weather(long_frame: pd.DataFrame) -> pd.DataFrame:
    """逐格气象 lag/roll 特征（组内按日序滚动，跨格不泄漏），列名与 zone 特征一致。"""
    out = long_frame.copy()
    for variable in WEATHER_FEATURES:
        if variable not in out.columns:
            continue
        grouped = out.groupby("grid_id", sort=False)[variable]
        for lag in FEATURE_LAGS:
            out[f"{variable}_lag{lag}"] = grouped.shift(lag)
        for window in FEATURE_ROLLS:
            out[f"{variable}_roll{window}"] = grouped.rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)
    return out.set_index(["grid_id", "date"])


def _satellite_grid_pivots(satellite: pd.DataFrame) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """available_date 索引的 (date × grid) 卫星 chla 与 bloom(0/1) 透视，供 grid 样本特征。"""

    chla = satellite[(satellite["variable_code"] == "chla_retrieval") & satellite["value"].notna()]
    if chla.empty:
        return None, None
    chla = chla.assign(_d=pd.to_datetime(chla["available_time"]).dt.normalize())
    chla_pivot = chla.pivot_table(index="_d", columns="grid_id", values="value", aggfunc="mean")
    frac_pivot = chla_pivot.where(chla_pivot.isna(), (chla_pivot >= SATELLITE_CHLA_BLOOM_UG_L).astype(float))
    return chla_pivot, frac_pivot


def _augment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """预计算 lag/roll 列，把特征查询从 O(window) 切片降为 O(1)。

    lag 按日历回看（值取 index−lag 天，缺口为 NaN）；roll 用
    rolling(window, min_periods=1).mean()，在连续日频索引下与
    loc[:date].tail(window).mean() 逐值等价。
    """

    out = frame.copy()
    for column in CORE_FEATURES:
        if column not in out.columns:
            continue
        series = out[column]
        for lag in FEATURE_LAGS:
            out[f"{column}__lag{lag}"] = series.reindex(series.index - pd.Timedelta(days=lag)).to_numpy()
        for window in FEATURE_ROLLS:
            out[f"{column}__roll{window}"] = series.rolling(window, min_periods=1).mean().to_numpy()
    return out


def _zone_features_at(augmented: pd.DataFrame, date: pd.Timestamp, columns: tuple[str, ...] = CORE_FEATURES) -> dict[str, float]:
    """augmented 需已经过 _augment_frame，且 date 在索引内。columns 限定变量集合
    （grid 样本传 AUX_FEATURES：气象由逐格驱动表单独提供）。"""

    features: dict[str, float] = {}
    for column in columns:
        if column not in augmented.columns:
            continue
        value = augmented[column].get(date)
        if value is not None and np.isfinite(value):
            features[column] = round(float(value), 6)
        for lag in FEATURE_LAGS:
            lag_value = augmented[f"{column}__lag{lag}"].get(date)
            if lag_value is not None and np.isfinite(lag_value):
                features[f"{column}_lag{lag}"] = round(float(lag_value), 6)
        for window in FEATURE_ROLLS:
            roll_value = augmented[f"{column}__roll{window}"].get(date)
            if roll_value is not None and np.isfinite(roll_value):
                features[f"{column}_roll{window}"] = round(float(roll_value), 6)
    return features


def _grid_weather_features(grid_augmented: pd.DataFrame | None, grid_id: str, date: pd.Timestamp) -> dict[str, float]:
    """grid 样本逐格驱动气象特征（当期 + lag/roll，格内日序预计算）。缺格/缺日如实缺测。"""

    features: dict[str, float] = {}
    if grid_augmented is None or grid_augmented.empty:
        return features
    try:
        row = grid_augmented.loc[(grid_id, date)]
    except KeyError:
        return features
    if isinstance(row, pd.DataFrame):  # 同键重复行取首行
        row = row.iloc[0]
    for column in WEATHER_FEATURES:
        if column not in grid_augmented.columns:
            continue
        value = row[column]
        if value is not None and np.isfinite(value):
            features[column] = round(float(value), 6)
        for lag in FEATURE_LAGS:
            lag_value = row[f"{column}_lag{lag}"]
            if lag_value is not None and np.isfinite(lag_value):
                features[f"{column}_lag{lag}"] = round(float(lag_value), 6)
        for window in FEATURE_ROLLS:
            roll_value = row[f"{column}_roll{window}"]
            if roll_value is not None and np.isfinite(roll_value):
                features[f"{column}_roll{window}"] = round(float(roll_value), 6)
    return features


def _grid_bloom_features(frac_pivot: pd.DataFrame | None, spatial_id: str, date: pd.Timestamp) -> dict[str, float]:
    """grid 样本附加特征：卫星反演 bloom(0/1)（available_date 索引），缺过境为 NaN。"""

    features: dict[str, float] = {}
    if frac_pivot is None or spatial_id not in frac_pivot.columns:
        return features
    series = frac_pivot[spatial_id]
    value = series.get(date)
    if value is not None and np.isfinite(value):
        features["grid_bloom_fraction"] = round(float(value), 6)
    for lag in (1, 3, 7):
        lag_value = series.get(date - pd.Timedelta(days=lag))
        if lag_value is not None and np.isfinite(lag_value):
            features[f"grid_bloom_fraction_lag{lag}"] = round(float(lag_value), 6)
    return features


def _features_at(frame: pd.DataFrame, date: pd.Timestamp, spatial_id: str, spatial_type: str, frac_pivot: pd.DataFrame | None) -> dict[str, float]:
    """date 当日及其滞后/滚动特征；全部 ≤ issue_date。frame 需先经 _augment_frame。"""

    features = _zone_features_at(frame, date)
    if spatial_type == "grid":
        features.update(_grid_bloom_features(frac_pivot, spatial_id, date))
    return features


def expand_samples(
    config: dict[str, Any],
    *,
    labels: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    grid_weather: pd.DataFrame | None,
    frac_pivot: pd.DataFrame | None,
    split_of_date: dict[Any, str],
    dataset: str,
    identity: dict[str, Any],
    grid_zone_of: dict[str, str] | None = None,
    horizons: tuple[int, ...] = HORIZONS,
    issue_stride: int = 1,
    grid_issue_stride: int = 7,
    min_issue_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """labels → 训练样本（df-0.3.0 气象与标签同源）。

    frames：zone/lake 特征源帧（键=spatial_id，含 TAIHU_WHOLE），需先经 _augment_frame；
    grid 样本气象取逐格驱动表（grid_weather），其余观测层特征仍取其 zone 帧按日广播值。
    identity：scenario_id/random_seed/driver_hash/driver_type 随行携带并进入 sample_id，
    多情景/多种子合并时主键不冲突（A03 前置）。issue_date < min_issue_date（驱动可阅
    起点 + max(lag)）的样本无法构成同源滞后窗口，整行拒绝。
    """
    samples = []
    default_key = next(iter(frames)) if frames else ""
    zone_cache: dict[tuple[str, pd.Timestamp], tuple[dict[str, float], str]] = {}
    weather_cache: dict[tuple[str, pd.Timestamp], dict[str, float]] = {}
    n_zone_slots = len(CORE_FEATURES) * (1 + len(FEATURE_LAGS) + len(FEATURE_ROLLS))
    n_grid_slots = len(AUX_FEATURES) * (1 + len(FEATURE_LAGS) + len(FEATURE_ROLLS)) + len(WEATHER_FEATURES) * (1 + len(FEATURE_LAGS) + len(FEATURE_ROLLS)) + 4
    scenario_id = str(identity.get("scenario_id", ""))
    random_seed = int(identity.get("random_seed", 0))
    driver_hash = str(identity.get("driver_hash", ""))
    driver_type = str(identity.get("driver_type", ""))
    if min_issue_date is not None:
        anchor = pd.Timestamp(min_issue_date)
    elif frames:
        anchor = min(frame.index[0] for frame in frames.values())
    else:
        anchor = None

    def frame_key_of(spatial_id: str, spatial_type: str) -> str:
        if spatial_type == "grid":
            zone_key = (grid_zone_of or {}).get(spatial_id)
            if zone_key in frames:
                return zone_key
        if spatial_id in frames:
            return spatial_id
        return default_key

    for (task_id, spatial_id, spatial_type), group in labels.groupby(["task_id", "spatial_id", "spatial_type"]):
        stride = grid_issue_stride if spatial_type == "grid" else issue_stride
        group = group.copy()
        group["target_date"] = pd.to_datetime(group["target_date"])
        truth_by_date = group.set_index("target_date")
        for target_date in sorted(truth_by_date.index.unique()):
            truth = truth_by_date.loc[target_date]
            if isinstance(truth, pd.DataFrame):
                # 同一目标日可并存仿真真值与观测两源；SIM 轨显式优先仿真真值（设计 §6.1/§8）
                preference = {"simulation_truth": 0, "satellite_observation": 1, "station_observation": 2, "threshold_rule": 3}
                truth = (
                    truth.assign(_pref=truth["label_source_type"].map(preference).fillna(9))
                    .sort_values(["_pref"])
                    .iloc[0]
                )
            split = split_of_date.get(pd.Timestamp(target_date).normalize())
            if split in (None, "isolation"):
                continue
            spatial_id_str = str(spatial_id)
            fkey = frame_key_of(spatial_id_str, spatial_type)
            frame = frames[fkey]
            for horizon in horizons:
                issue_date = pd.Timestamp(target_date) - pd.Timedelta(days=int(horizon))
                if anchor is not None:
                    offset = (issue_date - anchor).days
                    if offset < 0:
                        continue
                    if spatial_type == "grid" and offset % max(stride, 1) != 0:
                        continue
                issue_time = issue_date.strftime("%Y-%m-%dT12:00:00+08:00")
                if spatial_type == "grid":
                    aux_key = ("aux", fkey, issue_date)  # 命名空间区分：grid 缓存 AUX 特征，zone 缓存全量特征
                    cached = zone_cache.get(aux_key)
                    if cached is None:
                        aux_feats = _zone_features_at(frame, issue_date, columns=AUX_FEATURES)
                        cached = (aux_feats, json.dumps(aux_feats, ensure_ascii=False, sort_keys=True))
                        zone_cache[aux_key] = cached
                    wkey = (spatial_id_str, issue_date)
                    weather_feats = weather_cache.get(wkey)
                    if weather_feats is None:
                        weather_feats = _grid_weather_features(grid_weather, spatial_id_str, issue_date)
                        weather_cache[wkey] = weather_feats
                    features = dict(cached[0])
                    features.update(weather_feats)
                    features.update(_grid_bloom_features(frac_pivot, spatial_id_str, issue_date))
                    features_json = json.dumps(features, ensure_ascii=False, sort_keys=True)
                else:
                    zkey = ("zone", fkey, issue_date)
                    cached = zone_cache.get(zkey)
                    if cached is None:
                        zone_feats = _zone_features_at(frame, issue_date)
                        cached = (zone_feats, json.dumps(zone_feats, ensure_ascii=False, sort_keys=True))
                        zone_cache[zkey] = cached
                    features, features_json = cached
                sample_id = compute_sample_id(
                    spatial_id=spatial_id_str,
                    issue_time=issue_time,
                    target_date=pd.Timestamp(target_date).strftime("%Y-%m-%d"),
                    task_id=task_id,
                    horizon=int(horizon),
                    dataset_version=dataset,
                    scenario_id=scenario_id,
                    random_seed=random_seed,
                    driver_hash=driver_hash,
                )
                samples.append(
                    {
                        "sample_id": sample_id,
                        "spatial_id": spatial_id_str,
                        "spatial_type": spatial_type,
                        "issue_date": issue_date,
                        "target_date": pd.Timestamp(target_date),
                        "target_metric": task_id,
                        "horizon_days": int(horizon),
                        "label_value": truth["label_value"],
                        "label_unit": truth["label_unit"] or TASK_UNITS.get(task_id, ""),
                        "label_status": truth["label_status"],
                        "label_source_type": truth["label_source_type"],
                        "quality_flag": truth["label_quality"],
                        "split": split,
                        "scenario_id": scenario_id,
                        "random_seed": random_seed,
                        "driver_type": driver_type,
                        "driver_hash": driver_hash,
                        "feature_window_note": (
                            f"driver-sourced features (weather=run driver "
                            f"{'per-grid' if spatial_type == 'grid' else 'zone-mean'}, d+1 出账/station/satellite); "
                            f"lags{list(FEATURE_LAGS)}+rolls{list(FEATURE_ROLLS)} ending at issue_date; "
                            "only available_time<=issue_date visible"
                        ),
                        "dataset_version": dataset,
                        "source_type": truth["label_source_type"],
                        "is_ground_truth": bool(truth["is_ground_truth"]),
                        "is_synthetic": bool(truth["is_synthetic"]),
                        "domain_coverage_fraction": round(float(truth.get("domain_coverage_fraction", 1.0) or 1.0), 6),
                        "is_partial_domain": bool(truth.get("is_partial_domain", False)),
                        "feature_observed_ratio": round(len(features) / max(n_grid_slots if spatial_type == "grid" else n_zone_slots, 1), 4),
                        "features_json": json.dumps(features, ensure_ascii=False, sort_keys=True),
                        "_row_hash": row_hash({"sample_id": sample_id, "features": features, "label_value": truth["label_value"]}),
                        "_evidence": str(truth.get("evidence_record_ids", "") or ""),
                    }
                )
    return pd.DataFrame(samples)


def load_split_lookup(base_dir: Path) -> dict[Any, str]:
    manifest = pd.read_csv(base_dir / "splits" / "split_manifest.csv", parse_dates=["date"])
    return {row.date: row.split for row in manifest.itertuples(index=False)}


def _dynamic_features_grid(
    station_frame: pd.DataFrame,
    grid_augmented: pd.DataFrame,
    chla_pivot: pd.DataFrame | None,
    frac_pivot: pd.DataFrame | None,
    grid_ids: list[str],
    dataset: str,
) -> pd.DataFrame:
    """DG-004 发布表：每 (grid × 可阅日) 的观测层特征。

    气象为该格 run 驱动逐日值（与标签同源）；水温/营养盐为观测层按可用日广播；
    chla/bloom_fraction 取该格卫星反演（缺过境 NaN）。
    """
    dates = grid_augmented.index.get_level_values("date").unique().sort_values()
    index = pd.MultiIndex.from_product([grid_ids, dates], names=["grid_id", "date"])
    weather_long = grid_augmented[list(WEATHER_FEATURES)].reindex(index)
    out = weather_long.reset_index()
    station_cols = [c for c in STATION_FEATURES if c in station_frame.columns]
    if station_cols:
        station = station_frame.reindex(columns=station_cols).reindex(dates)
        tiled = pd.DataFrame(np.tile(station.to_numpy(dtype=float), (len(grid_ids), 1)), columns=station_cols, index=index)
        for col in station_cols:
            out[col] = tiled[col].to_numpy()
    if chla_pivot is not None and not chla_pivot.empty:
        chla_long = chla_pivot.stack()
        chla_long.index = chla_long.index.swaplevel()
        chla_long.index.names = ["grid_id", "date"]
        out["chlorophyll_a"] = chla_long.reindex(index).to_numpy()
        frac_long = frac_pivot.stack()
        frac_long.index = frac_long.index.swaplevel()
        frac_long.index.names = ["grid_id", "date"]
        out["bloom_fraction"] = frac_long.reindex(index).to_numpy()
    else:
        out["chlorophyll_a"] = np.nan
        out["bloom_fraction"] = np.nan
    out["dataset_version"] = dataset
    return out


def _target_observation_daily(base_dir: Path, satellite: pd.DataFrame, zone_code: str, dataset: str) -> pd.DataFrame:
    """DG-004 发布表：标签消费的观测层真值行（卫星湖区/全湖聚合 + 站点点位）。"""

    rows: list[dict[str, Any]] = []
    sat = satellite[(satellite["variable_code"] == "chla_retrieval") & satellite["value"].notna()] if not satellite.empty else satellite
    if not sat.empty:
        sat = sat.assign(_d=pd.to_datetime(sat["available_time"]).dt.normalize())
        for date, group in sat.groupby("_d"):
            for spatial_id, spatial_type in ((zone_code, "zone"), ("TAIHU_WHOLE", "lake")):
                common = {
                    "date": date,
                    "spatial_id": spatial_id,
                    "spatial_type": spatial_type,
                    "observed_time": pd.to_datetime(group["observed_time"]).max(),
                    "available_time": pd.to_datetime(group["available_time"]).max(),
                    "source_type": "remote_sensing",
                    "is_synthetic": bool(group["is_synthetic"].fillna(False).astype(bool).all()),
                    "is_ground_truth": False,
                    "dataset_version": dataset,
                }
                rows.append({**common, "variable_code": "chlorophyll_a", "value": round(float(group["value"].mean()), 6), "unit": "ug/L"})
                rows.append({**common, "variable_code": "bloom_fraction", "value": round(float((group["value"] >= SATELLITE_CHLA_BLOOM_UG_L).mean()), 6), "unit": "1"})

    station_path = base_dir / "observations" / "station_observations.parquet"
    if station_path.exists():
        station = pd.read_parquet(station_path)
        station = station[station["value"].notna()]
        for row_obs in station.itertuples(index=False):
            rows.append(
                {
                    "date": pd.Timestamp(row_obs.observed_time).normalize(),
                    "spatial_id": row_obs.station_id,
                    "spatial_type": "station",
                    "variable_code": row_obs.variable_code,
                    "value": round(float(row_obs.value), 6),
                    "unit": row_obs.unit or "",
                    "observed_time": pd.Timestamp(row_obs.observed_time),
                    "available_time": pd.Timestamp(row_obs.available_time),
                    "source_type": row_obs.source_type,
                    "is_synthetic": bool(row_obs.is_synthetic),
                    "is_ground_truth": bool(row_obs.is_ground_truth),
                    "dataset_version": dataset,
                }
            )
    return pd.DataFrame(rows)


def run_assembly(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    labels_dir: Path,
    dataset: str | None = None,
    track: str = Track.SIM_V1.value,
) -> dict[str, Any]:
    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    labels = pd.read_parquet(labels_dir / "task_labels.parquet")
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    zone_codes = list(sim_manifest["zones"])

    cells = pd.read_csv(base_dir / "grid" / "grid_metadata.csv")
    cells = cells[cells["zone_code"].isin(zone_codes)].sort_values("grid_id").reset_index(drop=True)
    grid_ids = cells["grid_id"].tolist()
    dates = pd.to_datetime(sorted(labels["target_date"].unique()))

    source_frames, weather_start = _feature_source_frames(sim_dir, base_dir, zone_codes, dates)
    frames = {key: _augment_frame(frame) for key, frame in source_frames.items()}
    grid_weather = _augment_grid_weather(_grid_weather_long(sim_dir, zone_codes))
    min_issue_date = weather_start + pd.Timedelta(days=max(FEATURE_LAGS))
    grid_zone_of = dict(zip(cells["grid_id"], cells["zone_code"]))
    identity = {
        "scenario_id": str(sim_manifest.get("scenario_id", "") or ""),
        "random_seed": int(sim_manifest.get("random_seed", 0) or 0),
        "driver_hash": str(sim_manifest.get("driver_hash", "") or ""),
        "driver_type": str(sim_manifest.get("driver_type", "") or ""),
    }
    satellite_path = base_dir / "observations" / "satellite_observations.parquet"
    satellite = pd.read_parquet(satellite_path) if satellite_path.exists() else pd.DataFrame()
    chla_pivot, sat_frac_pivot = _satellite_grid_pivots(satellite) if not satellite.empty else (None, None)

    split_of_date = load_split_lookup(base_dir)
    assembly_cfg = config.get("assembly", {})
    samples = expand_samples(
        config,
        labels=labels,
        frames=frames,
        grid_weather=grid_weather,
        frac_pivot=sat_frac_pivot,
        split_of_date=split_of_date,
        dataset=dataset,
        identity=identity,
        grid_zone_of=grid_zone_of,
        horizons=tuple(assembly_cfg.get("horizons_days", HORIZONS)),
        issue_stride=int(assembly_cfg.get("issue_stride_days", 1)),
        grid_issue_stride=int(assembly_cfg.get("grid_issue_stride_days", 7)),
        min_issue_date=min_issue_date,
    )

    out_dir = base_dir / "assembly" / track.replace("-", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence = samples["_evidence"] if "_evidence" in samples.columns else pd.Series([""] * len(samples), index=samples.index)
    samples = samples.drop(columns=["_row_hash", "_evidence"])
    samples.to_parquet(out_dir / "model_training_samples.parquet", index=False)

    # DG-010：sample_id 键控逐行血缘（行数=样本数）
    lineage_dir = base_dir / "lineage"
    lineage_dir.mkdir(parents=True, exist_ok=True)
    created = utc_now_iso()
    lineage_rows = []
    for row, parent_ids in zip(samples.itertuples(index=False), evidence):
        lineage_rows.append(
            {
                "sample_id": row.sample_id,
                "label_table_record_hash": row_hash(
                    {
                        "task_id": row.target_metric,
                        "spatial_id": row.spatial_id,
                        "target_date": pd.Timestamp(row.target_date).strftime("%Y-%m-%d"),
                        "label_value": row.label_value,
                        "label_status": row.label_status,
                        "label_source_type": row.label_source_type,
                    }
                ),
                "parent_record_ids": parent_ids,
                "feature_bundle_sha": content_hash(row.features_json),
                "feature_observed_ratio": row.feature_observed_ratio,
                "transformation_versions": f"generator:{GENERATOR_VERSION}|dataset:{dataset}",
                "created_at_utc": created,
            }
        )
    pd.DataFrame(lineage_rows).to_parquet(lineage_dir / "row_lineage.parquet", index=False)

    # DG-004 发布表：观测层特征 + 标签用观测真值行
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dynamic = _dynamic_features_grid(source_frames[zone_codes[0]], grid_weather, chla_pivot, sat_frac_pivot, grid_ids, dataset)
    dynamic.to_parquet(data_dir / "dynamic_features_grid_daily.parquet", index=False)
    target_obs = _target_observation_daily(base_dir, satellite, zone_codes[0], dataset)
    target_obs.to_parquet(data_dir / "target_observation_daily.parquet", index=False)

    by_split = {k: int(v) for k, v in samples.groupby("split").size().items()} if not samples.empty else {}
    ratio = samples["feature_observed_ratio"].astype(float)
    manifest = {
        "status": "completed",
        "command": "assemble",
        "track": track,
        "dataset_version": dataset,
        "generation_batch_id": sim_manifest["generation_batch_id"],
        "rows_written": int(len(samples)),
        "samples_by_split": by_split,
        "samples_by_metric": {k: int(v) for k, v in samples.groupby("target_metric").size().items()} if not samples.empty else {},
        "horizons": list(assembly_cfg.get("horizons_days", HORIZONS)),
        "grid_issue_stride_days": int(assembly_cfg.get("grid_issue_stride_days", 7)),
        "feature_sources": {
            "weather": f"run 驱动表 latent/weather_driver_{{zone}}.parquet（grid 逐格）与 latent/weather_daily_{{zone}}.parquet（zone 均值），d+1 出账，与标签同源（driver_type={identity['driver_type']}）",
            "station": "observations/station_observations.parquet (water_temperature/total_phosphorus/total_nitrogen，TP/TN 为仿真观测层)",
            "chlorophyll_a/bloom_fraction": "observations/satellite_observations.parquet",
            "min_issue_date": pd.Timestamp(min_issue_date).strftime("%Y-%m-%d"),
            "latent_excluded": "water_level/biomass/density 等未观测变量不进特征",
        },
        "driver": {
            "scenario_id": identity["scenario_id"],
            "random_seed": identity["random_seed"],
            "driver_type": identity["driver_type"],
            "driver_hash": identity["driver_hash"],
        },
        "feature_observed_ratio": {"mean": round(float(ratio.mean()), 4), "min": round(float(ratio.min()), 4), "max": round(float(ratio.max()), 4)} if not samples.empty else {},
        "gating": "SIM-V1 全样本 is_synthetic=true 并逐行携带 track；HYBRID/REAL 轨验证/测试仅收 ground_truth (STAGED)",
        "assembled_at_utc": utc_now_iso(),
        "outputs": {
            "model_training_samples": str(out_dir / "model_training_samples.parquet"),
            "row_lineage": str(lineage_dir / "row_lineage.parquet"),
            "dynamic_features_grid_daily": str(data_dir / "dynamic_features_grid_daily.parquet"),
            "target_observation_daily": str(data_dir / "target_observation_daily.parquet"),
        },
        "next_action": "python -m data_factory validate",
    }
    (out_dir / "assembly_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
