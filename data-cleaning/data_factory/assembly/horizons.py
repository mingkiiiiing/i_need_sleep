"""时效展开与特征装配 `assemble` (设计 §6.14/§9 T+1/3/7/15/30).

task_labels（目标日真值）→ 训练样本：issue_date = target_date − h；
特征全部来自观测层（DG-004）：真实逐日气象 + 站点采样 + 卫星过境反演，
且只取 available_time ≤ issue_date 的记录；latent 层（水位/营养盐/生物量等）一律不进入特征。
样本 frame 按"可阅日"（available_time 日）索引，issue_date 当天查询即天然满足可见性约束。
sample_id = sha256(spatial_id|issue_time|target_date|task_id|horizon|dataset_version)。
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

FEATURE_LAGS = (1, 3, 7, 14, 30)
FEATURE_ROLLS = (3, 7, 14, 30)
WEATHER_FEATURES = ("air_temperature", "wind_speed", "precipitation", "shortwave_radiation")
CORE_FEATURES = WEATHER_FEATURES + ("water_temperature", "chlorophyll_a", "bloom_fraction")
SATELLITE_CHLA_BLOOM_UG_L = 30.0  # 与 label_thresholds.chla.warning 一致
WEATHER_AVAILABILITY_LAG_DAYS = 1  # 真实日值气象次日出账


def _operational_features(base_dir: Path, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """观测层特征源（DG-004）：按可阅日索引，latent 层不进入特征。

    - 气象 4 变量：history/weather_observed_daily.parquet（真实观测 2024 全年；日值次日出账）
    - water_temperature：observations/station_observations.parquet（站点采样日历，稀疏，无观测日 NaN）
    - chlorophyll_a / bloom_fraction：observations/satellite_observations.parquet（过境日 + publish delay，缺测 NaN）
    """
    weather = pd.read_parquet(base_dir / "history" / "weather_observed_daily.parquet")
    weather["date"] = pd.to_datetime(weather["date"]) + pd.Timedelta(days=WEATHER_AVAILABILITY_LAG_DAYS)
    frame = weather.set_index("date")[list(WEATHER_FEATURES)].sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]

    # 先收集全部可阅日并扩索引，再赋值列——直接 frame[col]=series 会静默丢弃
    # 不在当前索引上的日期（观测可阅日 ≠ 气象日历日）。
    obs_dir = base_dir / "observations"
    station_path = obs_dir / "station_observations.parquet"
    station_series: pd.Series | None = None
    if station_path.exists():
        station = pd.read_parquet(station_path, columns=["variable_code", "value", "available_time"])
        station = station[(station["variable_code"] == "water_temperature") & station["value"].notna()]
        if not station.empty:
            avail = pd.to_datetime(station["available_time"]).dt.normalize()
            station_series = station.groupby(avail)["value"].mean()

    sat_path = obs_dir / "satellite_observations.parquet"
    sat_chla: pd.Series | None = None
    sat_frac: pd.Series | None = None
    if sat_path.exists():
        sat = pd.read_parquet(sat_path, columns=["variable_code", "value", "available_time"])
        sat = sat[(sat["variable_code"] == "chla_retrieval") & sat["value"].notna()]
        if not sat.empty:
            avail = pd.to_datetime(sat["available_time"]).dt.normalize()
            sat_chla = sat.groupby(avail)["value"].mean()
            sat_frac = sat.assign(_pos=(sat["value"] >= SATELLITE_CHLA_BLOOM_UG_L)).groupby(avail)["_pos"].mean()

    union = set(frame.index) | set(pd.DatetimeIndex(dates))
    for series in (station_series, sat_chla, sat_frac):
        if series is not None:
            union |= set(series.index)
    frame = frame.reindex(sorted(union))
    if station_series is not None:
        frame["water_temperature"] = station_series
    if sat_chla is not None:
        frame["chlorophyll_a"] = sat_chla
        frame["bloom_fraction"] = sat_frac

    frame = frame.sort_index()
    frame.index.name = "date"
    return frame.astype(float)


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


def _zone_features_at(augmented: pd.DataFrame, date: pd.Timestamp) -> dict[str, float]:
    """augmented 需已经过 _augment_frame，且 date 在索引内。"""

    features: dict[str, float] = {}
    for column in CORE_FEATURES:
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
    frame: pd.DataFrame,
    frac_pivot: pd.DataFrame | None,
    split_of_date: dict[Any, str],
    dataset: str,
    horizons: tuple[int, ...] = HORIZONS,
    issue_stride: int = 1,
    grid_issue_stride: int = 7,
) -> pd.DataFrame:
    samples = []
    zone_cache: dict[pd.Timestamp, tuple[dict[str, float], str]] = {}
    n_zone_slots = len(CORE_FEATURES) * (1 + len(FEATURE_LAGS) + len(FEATURE_ROLLS))
    n_grid_slots = 4  # grid_bloom_fraction + lag1/3/7
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
            for horizon in horizons:
                issue_date = pd.Timestamp(target_date) - pd.Timedelta(days=int(horizon))
                if (issue_date - frame.index[0]).days < 0:
                    continue
                if spatial_type == "grid" and ((issue_date - frame.index[0]).days % max(stride, 1)) != 0:
                    continue
                cached = zone_cache.get(issue_date)
                if cached is None:
                    zone_feats = _zone_features_at(frame, issue_date)
                    cached = (zone_feats, json.dumps(zone_feats, ensure_ascii=False, sort_keys=True))
                    zone_cache[issue_date] = cached
                if spatial_type == "grid":
                    features = dict(cached[0])
                    features.update(_grid_bloom_features(frac_pivot, str(spatial_id), issue_date))
                    features_json = json.dumps(features, ensure_ascii=False, sort_keys=True)
                else:
                    features = cached[0]
                    features_json = cached[1]
                issue_time = issue_date.strftime("%Y-%m-%dT12:00:00+08:00")
                sample_id = compute_sample_id(
                    spatial_id=str(spatial_id),
                    issue_time=issue_time,
                    target_date=pd.Timestamp(target_date).strftime("%Y-%m-%d"),
                    task_id=task_id,
                    horizon=int(horizon),
                    dataset_version=dataset,
                )
                samples.append(
                    {
                        "sample_id": sample_id,
                        "spatial_id": str(spatial_id),
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
                        "feature_window_note": f"observation-layer features (weather d+1/station/satellite); lags{list(FEATURE_LAGS)}+rolls{list(FEATURE_ROLLS)} ending at issue_date; only available_time<=issue_date visible",
                        "dataset_version": dataset,
                        "source_type": truth["label_source_type"],
                        "is_ground_truth": bool(truth["is_ground_truth"]),
                        "is_synthetic": bool(truth["is_synthetic"]),
                        "domain_coverage_fraction": round(float(truth.get("domain_coverage_fraction", 1.0) or 1.0), 6),
                        "is_partial_domain": bool(truth.get("is_partial_domain", False)),
                        "feature_observed_ratio": round(len(features) / max(n_zone_slots + (n_grid_slots if spatial_type == "grid" else 0), 1), 4),
                        "features_json": json.dumps(features, ensure_ascii=False, sort_keys=True),
                        "_row_hash": row_hash({"sample_id": sample_id, "features": features, "label_value": truth["label_value"]}),
                        "_evidence": str(truth.get("evidence_record_ids", "") or ""),
                    }
                )
    return pd.DataFrame(samples)


def load_split_lookup(base_dir: Path) -> dict[Any, str]:
    manifest = pd.read_csv(base_dir / "splits" / "split_manifest.csv", parse_dates=["date"])
    return {row.date: row.split for row in manifest.itertuples(index=False)}


def _dynamic_features_grid(frame: pd.DataFrame, chla_pivot: pd.DataFrame | None, frac_pivot: pd.DataFrame | None, grid_ids: list[str], dataset: str) -> pd.DataFrame:
    """DG-004 发布表：每 (grid × 可阅日) 的观测层特征。

    气象/水温为区域观测按可用日广播；chla/bloom_fraction 取该格卫星反演（缺过境 NaN）。
    """
    feature_cols = [c for c in (*WEATHER_FEATURES, "water_temperature") if c in frame.columns]
    base = frame.reindex(columns=feature_cols)
    index = pd.MultiIndex.from_product([grid_ids, base.index], names=["grid_id", "date"])
    out = pd.DataFrame(np.tile(base.to_numpy(dtype=float), (len(grid_ids), 1)), columns=feature_cols, index=index)
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
    out = out.reset_index()
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

    frame = _augment_frame(_operational_features(base_dir, dates))
    satellite_path = base_dir / "observations" / "satellite_observations.parquet"
    satellite = pd.read_parquet(satellite_path) if satellite_path.exists() else pd.DataFrame()
    chla_pivot, sat_frac_pivot = _satellite_grid_pivots(satellite) if not satellite.empty else (None, None)

    split_of_date = load_split_lookup(base_dir)
    assembly_cfg = config.get("assembly", {})
    samples = expand_samples(
        config,
        labels=labels,
        frame=frame,
        frac_pivot=sat_frac_pivot,
        split_of_date=split_of_date,
        dataset=dataset,
        horizons=tuple(assembly_cfg.get("horizons_days", HORIZONS)),
        issue_stride=int(assembly_cfg.get("issue_stride_days", 1)),
        grid_issue_stride=int(assembly_cfg.get("grid_issue_stride_days", 7)),
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
    dynamic = _dynamic_features_grid(frame, chla_pivot, sat_frac_pivot, grid_ids, dataset)
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
            "weather": "history/weather_observed_daily.parquet (d+1 出账)",
            "water_temperature": "observations/station_observations.parquet",
            "chlorophyll_a/bloom_fraction": "observations/satellite_observations.parquet",
            "latent_excluded": True,
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
