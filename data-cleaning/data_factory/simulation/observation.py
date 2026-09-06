"""观测层·站点：真实采样日历驱动 (设计 §6.1/§6.12) + MEE 实时快照桥接.

仅在真实站点采样日生成模拟观测（潜在真值 + 测量误差 + 检出限/缺测）；
below_detection_limit/缺测不造值。MEE 实时快照作为真实观测并入观测层。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

LATENT_VARIABLES = (
    "water_temperature",
    "pH",
    "dissolved_oxygen",
    "turbidity",
    "secchi_depth",
    "cod_mn",
    "total_phosphorus",
    "total_nitrogen",
    "ammonia_nitrogen",
    "chlorophyll_a",
    "phytoplankton_biomass",
    "cyanobacteria_density",
)


def _publish_delay(rng: np.random.Generator, p50: float, p90: float) -> float:
    # 对数正态近似：p50 处中位数、p90 处 90 分位
    sigma = float(np.log(max(p90, p50 + 0.1) / max(p50, 0.1)) / 1.2816)
    return float(p50 * np.exp(rng.normal(0.0, max(sigma, 0.05))))


def build_station_observations(
    dates: pd.DatetimeIndex,
    latent: dict[str, np.ndarray],
    grid_ids: list[str],
    station_mapping: pd.DataFrame,
    obs_pattern_station: pd.DataFrame,
    mechanism: dict[str, Any],
    rngs: dict[str, np.random.Generator],
    meta: dict[str, Any],
) -> pd.DataFrame:
    """DG-013：仅界内且已映射网格的站点参与采样；采样日期由真实站点采样日历
    （obs_pattern_station，全湖级 TAIHU_WHOLE 月度事件等）∩ 仿真期驱动。"""

    rng = rngs["obs_station"]
    obs_cfg = mechanism.get("obs", {})
    limits = obs_cfg.get("detection_limits", {})
    error_cfg = obs_cfg.get("measurement_error_pct", {})
    delay_p50 = float(obs_cfg.get("publish_delay_p50_h", 6.0))
    delay_p90 = float(obs_cfg.get("publish_delay_p90_h", 24.0))

    date_index = {d.date(): i for i, d in enumerate(dates)}
    grid_index = {g: i for i, g in enumerate(grid_ids)}
    stations = station_mapping.set_index("station_id")
    sample_dates = sorted({d for d in pd.to_datetime(obs_pattern_station["date"]).dt.date if d in date_index})
    rows: list[dict[str, Any]] = []
    for date in sample_dates:
        t = date_index[date]
        observed_time = pd.Timestamp(date) + pd.Timedelta(hours=9)  # 采样通常上午
        available_time = observed_time + pd.Timedelta(hours=_publish_delay(rng, delay_p50, delay_p90))
        for station_id, station in stations.iterrows():
            grid_id = station["grid_id"]
            gi = grid_index.get(grid_id)
            if gi is None:
                continue
            for variable in LATENT_VARIABLES:
                frame = latent.get(variable)
                if frame is None:
                    continue
                latent_value = float(frame[t][gi])
                limit = float(limits.get(variable, 0.0)) if variable in limits else None
                error_pct = float(error_cfg.get(variable, error_cfg.get("default", 10.0)))
                if rng.random() < 0.02:
                    rows.append(_row(station_id, grid_id, observed_time, available_time, variable, None, None, None, error_pct, "warning", "instrument_missing", meta))
                    continue
                if limit is not None and latent_value < limit:
                    rows.append(_row(station_id, grid_id, observed_time, available_time, variable, None, None, limit, error_pct, "pass", "below_detection_limit", meta))
                    continue
                value = latent_value * float(np.exp(rng.normal(0.0, error_pct / 100.0)))
                quality = "warning" if error_pct >= 20.0 else "pass"
                rows.append(_row(station_id, grid_id, observed_time, available_time, variable, round(value, 6), latent_value, limit, error_pct, quality, None, meta))
    frame = pd.DataFrame(rows)
    if frame.empty:
        # 保留 schema：空观测表也要带列，供下游 labeling/assembly 消费
        return pd.DataFrame(columns=list(_row("", "", pd.NaT, pd.NaT, "", None, None, None, 0.0, "pass", None, meta).keys()))
    frame["observed_time"] = pd.to_datetime(frame["observed_time"])
    frame["available_time"] = pd.to_datetime(frame["available_time"])
    return frame


def _row(
    station_id: str,
    grid_id: str,
    observed_time: pd.Timestamp,
    available_time: pd.Timestamp,
    variable: str,
    value: float | None,
    _latent: float | None,
    limit: float | None,
    error_pct: float,
    quality: str,
    missing_reason: str | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "station_id": station_id,
        "station_name": None,
        "grid_id": grid_id,
        "observed_time": observed_time,
        "available_time": available_time,
        "variable_code": variable,
        "value": value,
        "unit": "",
        "detection_limit": limit,
        "measurement_error_pct": error_pct,
        "quality_flag": quality,
        "missing_reason": missing_reason,
        "value_type": "simulated",
        "is_ground_truth": False,
        "is_synthetic": True,
        "source_type": "simulation_observation",
        "parent_record_ids": f"{meta['dataset_version']}|latent|{grid_id}|{observed_time.date()}|{variable}",
        "generator_version": meta["generator_version"],
        "generation_batch_id": meta["generation_batch_id"],
    }


_MEE_BRIDGE_COLUMNS = [
    "station_id",
    "station_name",
    "grid_id",
    "observed_time",
    "available_time",
    "variable_code",
    "value",
    "unit",
    "detection_limit",
    "measurement_error_pct",
    "quality_flag",
    "missing_reason",
    "value_type",
    "is_ground_truth",
    "is_synthetic",
    "source_type",
    "parent_record_ids",
    "generator_version",
    "generation_batch_id",
    "qc_note",
]


def filter_mee_fresh(mee_frame: pd.DataFrame, max_lag_h: float, *, now: pd.Timestamp | None = None) -> tuple[pd.DataFrame, int]:
    """MEE 实时观测新鲜度门禁（审计 2026-09-06）。

    观测时间滞后超过 max_lag_h 的行不得作为实时观测进入观测层（missing_reason=stale
    语义）；返回 (保留行, 剔除行数)。max_lag_h<=0 表示关闭门禁。
    """

    if mee_frame is None or mee_frame.empty or max_lag_h <= 0:
        return mee_frame, 0
    from data_factory.ingestion.mee_realtime import TZ_CN

    obs_times = pd.to_datetime(mee_frame["observed_time"], errors="coerce")
    obs_times = obs_times.dt.tz_localize(TZ_CN) if obs_times.dt.tz is None else obs_times.dt.tz_convert(TZ_CN)
    cutoff = (now or pd.Timestamp.now(tz=TZ_CN)) - pd.Timedelta(hours=float(max_lag_h))
    fresh_mask = obs_times.notna() & (obs_times >= cutoff)
    return mee_frame[fresh_mask], int((~fresh_mask).sum())


def bridge_realtime_mee(
    mee_observations: pd.DataFrame,
    meta: dict[str, Any],
    *,
    station_mapping: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """MEE 实时快照 → 观测层。身份字段透传 ingestion QC 判定，不得改写为 ground truth。

    审计 2026-09-06 整改：station_name 保留可读站名不再清空；传入 station_mapping
    （station_grid_mapping.csv）时按站名/站点ID 映射 grid_id，未映射站点 grid_id
    置空并在 qc_note 留痕 station_not_mapped_to_grid，不得猜测网格。
    """

    if mee_observations is None or mee_observations.empty:
        # 保留 schema：空桥接也带列，供下游 assembly 消费
        return pd.DataFrame(columns=list(_MEE_BRIDGE_COLUMNS))
    frame = mee_observations.copy()
    if "station_name" not in frame.columns:
        frame["station_name"] = None
    frame["station_name"] = frame["station_name"].where(frame["station_name"].notna(), frame["station_id"])
    if station_mapping is not None and not station_mapping.empty:
        candidates = station_mapping
        if "mapping_status" in candidates.columns:
            candidates = candidates[candidates["mapping_status"] == "mapped"]
        name_to_grid: dict[str, Any] = {}
        for _, row in candidates.iterrows():
            grid_id = row.get("grid_id")
            if pd.isna(grid_id) or grid_id in (None, ""):
                continue
            for key in {str(row.get("station_name") or "").strip(), str(row.get("station_id") or "").strip()}:
                if key:
                    name_to_grid.setdefault(key, grid_id)
        lookup = frame["station_name"].astype(str).str.strip()
        frame["grid_id"] = lookup.map(name_to_grid)
        unmapped = frame["grid_id"].isna()
        if unmapped.any() and "qc_note" in frame.columns:
            note = frame["qc_note"].fillna("").astype(str)
            frame.loc[unmapped, "qc_note"] = (note[unmapped] + ";station_not_mapped_to_grid").str.lstrip(";")
    else:
        frame["grid_id"] = None
    frame["observed_time"] = pd.to_datetime(frame["observed_time"])
    frame["available_time"] = pd.to_datetime(frame["available_time"]) if "available_time" in frame.columns else frame["observed_time"]
    frame["detection_limit"] = None
    frame["measurement_error_pct"] = None
    # DG-014：QC 未通过的行保持 pending_review / observation_candidate / is_ground_truth=false
    frame["quality_flag"] = frame["quality_flag"].fillna("pending_review") if "quality_flag" in frame.columns else "pending_review"
    frame["missing_reason"] = None
    frame["value_type"] = frame["value_type"].fillna("observation_candidate") if "value_type" in frame.columns else "observation_candidate"
    frame["is_ground_truth"] = frame["is_ground_truth"].fillna(False).astype(bool) if "is_ground_truth" in frame.columns else False
    frame["is_synthetic"] = False
    frame["source_type"] = "mee_surface_water_realtime"
    snapshot_col = "snapshot_file" if "snapshot_file" in frame.columns else ("source_snapshot" if "source_snapshot" in frame.columns else None)
    frame["parent_record_ids"] = frame[snapshot_col].astype(str) if snapshot_col else ""
    frame["generator_version"] = meta["generator_version"]
    frame["generation_batch_id"] = meta["generation_batch_id"]
    for col in _MEE_BRIDGE_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    return frame[_MEE_BRIDGE_COLUMNS]


def run_build_observations(
    config: dict[str, Any],
    *,
    base_dir: Path,
    sim_dir: Path,
    mechanism: dict[str, Any],
    dataset: str | None = None,
) -> dict[str, Any]:
    """编排观测层：真实站点采样日历 + 真实卫星过境日 + MEE 实时快照桥接。"""

    import json

    import numpy as np
    from data_factory.simulation import remote_sensing as rs

    dataset = dataset or config.get("dataset_id", "mvp_meiliangwan_2024")
    sim_manifest = json.loads((sim_dir / "sim_manifest.json").read_text(encoding="utf-8"))
    zone_codes = list(sim_manifest["zones"])
    meta = {
        "dataset_version": dataset,
        "generator_version": sim_manifest["generator_version"],
        "generation_batch_id": sim_manifest["generation_batch_id"],
    }

    mapping = pd.read_csv(base_dir / "grid" / "station_grid_mapping.csv")
    if "mapping_status" in mapping.columns:
        mapping = mapping[mapping["mapping_status"] == "mapped"]
    else:
        outside = mapping["outside_boundary"].astype(str).str.lower().isin(["true", "1", "yes"])
        mapping = mapping[~outside]
    mapping = mapping[mapping["zone_code"].isin(zone_codes) & mapping["grid_id"].notna()]
    pattern_station = pd.read_csv(base_dir / "history" / "obs_pattern_station.csv", parse_dates=["date"])
    pattern_satellite = pd.read_csv(base_dir / "history" / "obs_pattern_satellite.csv", parse_dates=["date"])

    cells = pd.read_csv(base_dir / "grid" / "grid_metadata.csv")
    cells = cells[cells["zone_code"].isin(zone_codes)].sort_values("grid_id").reset_index(drop=True)
    grid_ids = cells["grid_id"].tolist()
    dates = pd.to_datetime(sorted(pd.read_parquet(sim_dir / "bloom_grid_daily.parquet")["date"].unique()))

    wq = pd.read_parquet(sim_dir / "latent" / f"water_quality_grid_daily_{zone_codes[0]}.parquet")
    bio = pd.read_parquet(sim_dir / "latent" / f"biomass_grid_daily_{zone_codes[0]}.parquet")

    def _pivot(frame: pd.DataFrame, variable: str, column: str = "value") -> np.ndarray:
        sub = frame[frame["variable_code"] == variable] if "variable_code" in frame.columns else frame
        sub = sub.copy()
        sub["date"] = pd.to_datetime(sub["date"])
        matrix = sub.pivot(index="date", columns="grid_id", values=column).reindex(index=dates, columns=grid_ids)
        return matrix.to_numpy(dtype=float)

    latent = {variable: _pivot(wq, variable) for variable in LATENT_VARIABLES}
    latent["phytoplankton_biomass"] = _pivot(bio, "surface_biomass_mg_l", column="surface_biomass_mg_l")

    station_obs = build_station_observations(dates, latent, grid_ids, mapping, pattern_station, mechanism, {k: np.random.default_rng(np.random.SeedSequence([sim_manifest["random_seed"], 98, i])) for i, k in enumerate(("x", "obs_station"))}, meta)
    chla_grid = latent["chlorophyll_a"]
    fraction_grid = _pivot(pd.read_parquet(sim_dir / "bloom_grid_daily.parquet").assign(variable_code="bloom_fraction"), "bloom_fraction", column="bloom_fraction")
    satellite_obs = rs.build_satellite_observations(dates, chla_grid, fraction_grid, grid_ids, pattern_satellite, mechanism, {k: np.random.default_rng(np.random.SeedSequence([sim_manifest["random_seed"], 99, i])) for i, k in enumerate(("x", "obs_spatial"))}, meta)

    mee_path = base_dir / "realtime" / "mee_observations.parquet"
    mee_rows = pd.DataFrame()
    mee_stale_dropped = 0
    mee_gate_h: float | None = None
    if mee_path.exists():
        mee_frame = pd.read_parquet(mee_path)
        if not mee_frame.empty:
            # 新鲜度门禁（审计 2026-09-06）：超龄行剔除，剔除行数在 manifest 留痕
            mee_gate_h = float(((config.get("realtime_sources") or {}).get("mee") or {}).get("freshness_max_lag_h", 24.0))
            mee_frame, mee_stale_dropped = filter_mee_fresh(mee_frame, mee_gate_h)
        mee_rows = bridge_realtime_mee(mee_frame, meta, station_mapping=mapping)

    out_dir = base_dir / "observations"
    out_dir.mkdir(parents=True, exist_ok=True)
    station_obs.to_parquet(out_dir / "station_observations.parquet", index=False)
    satellite_obs.to_parquet(out_dir / "satellite_observations.parquet", index=False)
    if mee_path.exists():
        mee_rows.to_parquet(out_dir / "mee_realtime_observations.parquet", index=False)

    manifest = {
        "status": "completed",
        "command": "build-observations",
        "rows_written": int(len(station_obs) + len(satellite_obs) + len(mee_rows)),
        "station_obs_rows": int(len(station_obs)),
        "satellite_obs_rows": int(len(satellite_obs)),
        "mee_realtime_rows": int(len(mee_rows)),
        "mee_stale_rows_dropped": mee_stale_dropped,
        "mee_freshness_max_lag_h": mee_gate_h,
        "mee_unmapped_station_rows": int(mee_rows["grid_id"].isna().sum()) if not mee_rows.empty else 0,
        "stations_used": int(mapping["station_id"].nunique()),
        "rule": "仅真实采样日/过境日生成观测；below_detection_limit 与 instrument_missing 记 missing_reason 不造值；"
        "MEE 实时观测经 freshness_max_lag_h 门禁，超龄行剔除不进入观测层",
        "outputs": {
            "station_observations": str(out_dir / "station_observations.parquet"),
            "satellite_observations": str(out_dir / "satellite_observations.parquet"),
        },
        "next_action": "python -m data_factory build-labels",
    }
    (out_dir / "observations_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
