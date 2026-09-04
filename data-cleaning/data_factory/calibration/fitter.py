"""校准拟合编排 `fit --split train` (设计 §6.7 分层估计 + §10 先切分再拟合).

只用日期 ≤ train 末期（隔离窗前）的真实/可解释约束记录：
- 天气：NASA POWER 真实观测逐日气象（derived of real obs）
- 水温：ERA5 湖温（derived 约束）+ 先验收缩
- 营养盐/藻类：TAIHU_CLEAN water_quality ground_truth
- 水文：水位 ground_truth
C3S/NOAA 等预报输入一律不当拟合真值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory import GENERATOR_VERSION
from data_factory.contracts.constants import utc_now_iso
from data_factory.lineage.hashing import content_hash
from pipeline.provenance import sha256_file
from . import statistics as st
from .obs_error import detection_limits, measurement_error_pct, publish_delay_hours, satellite_valid_rates, sampling_counts

WEATHER_VARS = ["air_temperature", "wind_speed", "shortwave_radiation"]


def _local_naive(series: pd.Series) -> pd.Series:
    """UTC/aware 混杂的 observed_at → 本地（Asia/Shanghai）naive 时间，避免 tz 混拼。"""
    ts = pd.to_datetime(series, utc=True, errors="coerce")
    return ts.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)


def _filter_until(frame: pd.DataFrame, time_col: str, cutoff: pd.Timestamp) -> pd.DataFrame:
    """DG-002：拟合输入统一按本地时间 ≤ cutoff 过滤；不可解析（NaT）一律剔除。"""
    if frame.empty or time_col not in frame.columns:
        return frame
    local = _local_naive(frame[time_col])
    return frame[local.notna() & (local <= cutoff)].copy()


def _filter_date(frame: pd.DataFrame, date_col: str, cutoff: pd.Timestamp) -> pd.DataFrame:
    if frame.empty or date_col not in frame.columns:
        return frame
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    return frame[dates.notna() & (dates <= cutoff)].copy()


def _train_end_date(splits_dir: Path) -> pd.Timestamp:
    manifest = pd.read_csv(Path(splits_dir) / "split_manifest.csv", parse_dates=["date"])
    train_dates = manifest.loc[manifest["split"] == "train", "date"]
    return pd.Timestamp(train_dates.max())


def _harmonic_rows(rows: list[dict], family: str, variable: str, clim: dict, phi: float, sigma: float, year_sigma: float) -> None:
    keys = ["clim_a0", "clim_s1", "clim_c1", "clim_s2", "clim_c2"]
    values = [clim["a0"]] + list(clim["coef"]) + [0.0] * (5 - 1 - len(clim["coef"]))
    for key, value in zip(keys, values):
        rows.append(_row(family, "global", variable, key, value, clim["n"], "harmonic_climatology"))
    rows.append(_row(family, "global", variable, "ar_phi", phi, clim["n"], "ar1"))
    rows.append(_row(family, "global", variable, "ar_sigma", sigma, clim["n"], "ar1"))
    rows.append(_row(family, "global", variable, "year_sigma", year_sigma, clim["n"], "interannual_std"))


def _row(family: str, scope_type: str, scope_id: str, key: str, value: float, n: int, method: str, variable: str | None = None, unit: str = "") -> dict:
    return {
        "family": family,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "variable_code": variable or "",
        "parameter_key": key,
        "value": float(value) if value is not None and np.isfinite(value) else 0.0,
        "unit": unit,
        "n_samples": int(n),
        "method": method,
        "fitted_at_utc": utc_now_iso(),
    }


def _fit_weather(weather: pd.DataFrame, cutoff: pd.Timestamp, rows: list[dict]) -> None:
    frame = weather.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame[frame["date"] <= cutoff].sort_values("date")
    doy = frame["date"].dt.dayofyear.to_numpy()
    yearly_means = frame.groupby(frame["date"].dt.year)["air_temperature"].mean()
    year_sigma = float(yearly_means.std(ddof=0)) if len(yearly_means) > 1 else 0.0
    for variable in WEATHER_VARS:
        series = frame[variable].astype(float)
        clim = st.harmonic_climatology(doy, series.to_numpy(), n_harmonics=2)
        residual = series.to_numpy() - st.eval_climatology(clim, doy)
        phi, sigma, _ = st.ar1(residual)
        _harmonic_rows(rows, "weather", variable, clim, phi, sigma, float(year_sigma))
    precip = frame["precipitation"].astype(float)
    markov = st.monthly_markov(pd.DatetimeIndex(frame["date"]), precip.to_numpy())
    wet = frame.assign(wet=precip > 0.1)
    for month, group in wet.groupby(wet["date"].dt.month):
        intensities = group.loc[group["wet"], "precipitation"].to_numpy()
        shape, scale = st.gamma_moments(intensities)
        p01 = float(markov.loc[month, "p01"]) if month in markov.index else 0.3
        p11 = float(markov.loc[month, "p11"]) if month in markov.index else 0.5
        for key, value in (("p01", p01), ("p11", p11), ("gamma_shape", shape), ("gamma_scale", scale)):
            rows.append(_row("weather", "zone", f"m{int(month):02d}", key, value, int(len(group)), "markov_gamma", variable="precipitation", unit="mm" if key.startswith("gamma") else ""))
    residual_frame = frame.set_index("date")[WEATHER_VARS]
    corr = st.residual_corr(residual_frame, WEATHER_VARS)
    for i, a in enumerate(WEATHER_VARS):
        for b in WEATHER_VARS[i + 1:]:
            rows.append(_row("weather", "global", f"{a}|{b}", "residual_corr", float(corr.loc[a, b]), int(len(frame)), "residual_correlation"))
    rows.append(_row("weather", "global", "air_temperature", "extreme_p99", float(np.nanpercentile(frame["air_temperature"], 99)), len(frame), "quantile"))
    rows.append(_row("weather", "global", "precipitation", "extreme_p99", float(np.nanpercentile(frame["precipitation"], 99)), len(frame), "quantile", unit="mm"))
    rows.append(_row("weather", "global", "wind_speed", "calm_p10", float(np.nanpercentile(frame["wind_speed"], 10)), len(frame), "quantile", unit="m/s"))


def _fit_water_temp(met_hyd: pd.DataFrame, weather: pd.DataFrame, mechanism: dict, rows: list[dict], cutoff: pd.Timestamp) -> None:
    lake = _filter_until(met_hyd, "observed_at", cutoff)
    lake = lake[lake["variable_code"] == "lake_surface_temperature"][["observed_at", "value"]].copy()
    lake["date"] = _local_naive(lake["observed_at"]).dt.normalize()
    daily = lake.groupby("date")["value"].mean()
    wx = _filter_date(weather, "date", cutoff).copy()
    wx["date"] = pd.to_datetime(wx["date"])
    wx = wx.set_index("date")[["air_temperature", "wind_speed", "shortwave_radiation"]]
    joined = pd.concat([daily.rename("tlake"), wx], axis=1).dropna().sort_index()
    prior = mechanism.get("water_temp", {})
    n_min = int(prior.get("n_min", 12))
    strength = float(prior.get("prior_strength", 5.0))
    if len(joined) >= n_min + 2:
        tl = joined["tlake"]
        d_t = (tl - tl.shift(1)).dropna()
        common = joined.loc[d_t.index]
        x = pd.DataFrame(
            {
                "k1": common["air_temperature"] - tl.shift(1).loc[d_t.index],
                "k2": common["shortwave_radiation"] / 10.0,
                "k3": -common["wind_speed"],
            }
        )
        coef, *_ = np.linalg.lstsq(x.to_numpy(), d_t.to_numpy(), rcond=None)
        fitted = dict(zip(("k1", "k2", "k3"), coef))
    else:
        fitted = {}
    for key in ("k1", "k2", "k3", "k4"):
        prior_value = float(prior.get(key, 0.0))
        group_value = float(fitted.get(key, prior_value))
        value = st.shrink(len(joined), group_value, prior_value, n_min=n_min, prior_strength=strength)
        rows.append(_row("water_temp", "global", "", key, value, int(len(joined)), "constrained_lsq_shrunk", unit="per_day" if key == "k1" else ""))


def _fit_nutrients_algae(wq: pd.DataFrame, mechanism: dict, rows: list[dict], cutoff: pd.Timestamp) -> None:
    frame = wq[wq["is_ground_truth"] == True].copy()  # noqa: E712 — 明确布尔判断
    frame = _filter_until(frame, "observed_at", cutoff)
    frame["date"] = _local_naive(frame["observed_at"])
    frame["month"] = frame["date"].dt.month
    zone_stations = {code for code in frame["station_id"].astype(str) if str(code).startswith("TAIHU_") and code not in ("TAIHU_WHOLE",)}
    for variable in ("total_phosphorus", "total_nitrogen", "ammonia_nitrogen", "dissolved_oxygen", "pH", "phytoplankton_biomass", "chlorophyll_a"):
        sub = frame[frame["variable_code"] == variable].dropna(subset=["value"])
        sub = sub[sub["value"] > 0]
        global_mu, global_sigma = st.lognorm_params(sub["value"].to_numpy()) if variable != "pH" else (float(sub["value"].mean()), float(sub["value"].std()))
        for station in sorted(zone_stations):
            station_sub = sub[sub["station_id"] == station]
            monthly = st.monthly_lognorm(pd.DatetimeIndex(station_sub["date"]), station_sub["value"].to_numpy())
            for month, stats_row in monthly.iterrows():
                mu = st.shrink(int(stats_row["n"]), float(stats_row["mu"]), global_mu)
                sigma = st.shrink(int(stats_row["n"]), float(stats_row["sigma"]), global_sigma)
                rows.append(_row("nutrients" if variable != "phytoplankton_biomass" and variable != "chlorophyll_a" else "algae", "zone", f"{station}-m{int(month):02d}", "lognorm_mu", mu, int(stats_row["n"]), "monthly_lognorm_shrunk", variable=variable))
                rows.append(_row("nutrients" if variable != "phytoplankton_biomass" and variable != "chlorophyll_a" else "algae", "zone", f"{station}-m{int(month):02d}", "lognorm_sigma", sigma, int(stats_row["n"]), "monthly_lognorm_shrunk", variable=variable))
    # 色素比：同站同日 chla(ug/L) / 生物量(mg/L)。DG-006：先验量纲修正为 µg/mg（真实 ~1–3），
    # 无配对样本时显式落 prior_fallback 行留痕，不得静默回退旧量纲错误值 0.005
    frame["date_only"] = frame["date"].dt.date
    paired = frame.pivot_table(index=["station_id", "date_only"], columns="variable_code", values="value", aggfunc="mean")
    prior_ratio = float(mechanism.get("algae", {}).get("pigment_ratio_base", 1.5))
    fitted_ratio: float | None = None
    if {"chlorophyll_a", "phytoplankton_biomass"}.issubset(paired.columns):
        ratio = (paired["chlorophyll_a"] / paired["phytoplankton_biomass"]).replace([np.inf, -np.inf], np.nan).dropna()
        ratio = ratio[(ratio > 0.5) & (ratio < 50)]
        if len(ratio):
            value = st.shrink(len(ratio), float(ratio.median()), prior_ratio)
            rows.append(_row("algae", "global", "", "pigment_ratio_ug_per_mg", value, int(len(ratio)), "paired_median_shrunk"))
            fitted_ratio = float(value)
    if fitted_ratio is None:
        rows.append(_row("algae", "global", "", "pigment_ratio_ug_per_mg", prior_ratio, 0, "prior_fallback"))


def _fit_hydrology(met_hyd: pd.DataFrame, rows: list[dict], cutoff: pd.Timestamp) -> None:
    level = _filter_until(met_hyd, "observed_at", cutoff)
    level = level[level["variable_code"] == "water_level"][["observed_at", "value"]].dropna().copy()
    if level.empty:
        return
    level["date"] = _local_naive(level["observed_at"]).dt.normalize()
    daily = level.groupby("date")["value"].mean().sort_index()
    monthly = st.monthly_stats(pd.DatetimeIndex(daily.index), daily.to_numpy())
    for month, row in monthly.iterrows():
        rows.append(_row("hydrology", "zone", f"m{int(month):02d}", "level_mean_m", float(row["mean"]), int(row["n"]), "monthly_mean", unit="m"))
        rows.append(_row("hydrology", "zone", f"m{int(month):02d}", "level_std_m", float(row["std"]), int(row["n"]), "monthly_std", unit="m"))
    phi, sigma, _ = st.ar1(daily.diff().dropna().to_numpy() if len(daily) > 8 else daily.to_numpy())
    rows.append(_row("hydrology", "global", "", "level_ar_phi", phi, int(len(daily)), "ar1"))
    rows.append(_row("hydrology", "global", "", "level_ar_sigma", sigma, int(len(daily)), "ar1"))
    # DG-005：全局 level_mean_m 必须是绝对水位均值（真实 ~2.6–4.8 m）；
    # 旧实现把对差分做 AR1 得到的均值（≈日变化量）写入该键，导致仿真水位整体塌缩钳在 2.0 m 下界
    rows.append(_row("hydrology", "global", "", "level_mean_m", float(daily.mean()), int(len(daily)), "level_absolute_mean", unit="m"))


def _fit_obs(pattern_satellite: pd.DataFrame, pattern_station: pd.DataFrame, wq: pd.DataFrame, mechanism: dict, rows: list[dict], cutoff: pd.Timestamp) -> None:
    pattern_satellite = _filter_date(pattern_satellite, "date", cutoff)
    pattern_station = _filter_date(pattern_station, "date", cutoff)
    wq = _filter_until(wq, "observed_at", cutoff)
    rates = satellite_valid_rates(pattern_satellite)
    for month, row in rates.iterrows():
        rows.append(_row("obs", "zone", f"m{int(month):02d}", "satellite_valid_rate", float(row["valid_rate"]), int(row["n"]), "monthly_cloud_rate"))
    counts = sampling_counts(pattern_station)
    for _, row in counts.iterrows():
        rows.append(_row("obs", "station", f"{row['station_id']}-m{int(row['month']):02d}", "sample_days", int(row["n_sample_days"]), int(row["n_sample_days"]), "real_calendar"))
    delay = publish_delay_hours(wq)
    rows.append(_row("obs", "global", "", "publish_delay_p50_h", delay["p50"], delay["n"], "quantile", unit="h"))
    rows.append(_row("obs", "global", "", "publish_delay_p90_h", delay["p90"], delay["n"], "quantile", unit="h"))
    for variable, limit in detection_limits(mechanism).items():
        rows.append(_row("obs", "global", "", f"detection_limit::{variable}", float(limit), 0, "config", variable=variable))
    for variable, pct in measurement_error_pct(mechanism).items():
        rows.append(_row("obs", "global", "", f"measurement_error_pct::{variable}", float(pct), 0, "config", variable=variable))


def run_fit(config: dict[str, Any], *, history_dir: Path, splits_dir: Path, mechanism: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    cutoff = _train_end_date(splits_dir)
    weather_raw = pd.read_parquet(Path(history_dir) / "weather_observed_daily.parquet")
    wq_raw = pd.read_parquet(Path(history_dir) / "water_quality.parquet")
    met_hyd_raw = pd.read_parquet(Path(history_dir) / "meteorology_hydrology.parquet")
    pattern_satellite_raw = pd.read_csv(Path(history_dir) / "obs_pattern_satellite.csv")
    pattern_station_raw = pd.read_csv(Path(history_dir) / "obs_pattern_station.csv")

    # DG-002：所有拟合输入统一先按 train 末期 cutoff 过滤（NaT/不可解析一律剔除），
    # 分支内部再各自防御性过滤一次
    weather = _filter_date(weather_raw, "date", cutoff)
    wq = _filter_until(wq_raw, "observed_at", cutoff)
    met_hyd = _filter_until(met_hyd_raw, "observed_at", cutoff)
    pattern_satellite = _filter_date(pattern_satellite_raw, "date", cutoff)
    pattern_station = _filter_date(pattern_station_raw, "date", cutoff)

    def _max_date(frame: pd.DataFrame, col: str) -> str | None:
        if frame.empty or col not in frame.columns:
            return None
        ts = pd.to_datetime(frame[col], errors="coerce").dropna()
        return str(ts.max().date()) if len(ts) else None

    level_rows = met_hyd[met_hyd["variable_code"] == "water_level"] if not met_hyd.empty else met_hyd
    lake_temp_rows = met_hyd[met_hyd["variable_code"] == "lake_surface_temperature"] if not met_hyd.empty else met_hyd
    wq_dates = _local_naive(wq["observed_at"]) if not wq.empty else pd.Series(dtype="datetime64[ns]")
    wq_max = str(wq_dates.max().date()) if len(wq_dates.dropna()) else None
    per_family_max_input_date = {
        "weather": _max_date(weather, "date"),
        "water_temp": _max_date(lake_temp_rows, "observed_at") or _max_date(weather, "date"),
        "nutrients": wq_max,
        "algae": wq_max,
        "hydrology": _max_date(level_rows, "observed_at"),
        "obs": max(d for d in (_max_date(pattern_satellite, "date"), _max_date(pattern_station, "date"), wq_max) if d) if (len(pattern_satellite) or len(pattern_station) or wq_max) else None,
    }

    rows: list[dict] = []
    _fit_weather(weather, cutoff, rows)
    _fit_water_temp(met_hyd, weather, mechanism, rows, cutoff)
    _fit_nutrients_algae(wq, mechanism, rows, cutoff)
    _fit_hydrology(met_hyd, rows, cutoff)
    _fit_obs(pattern_satellite, pattern_station, wq, mechanism, rows, cutoff)

    parameter_sets = pd.DataFrame(rows)
    inputs = sorted({str(p) for p in [Path(history_dir) / "weather_observed_daily.parquet", Path(history_dir) / "water_quality.parquet", Path(history_dir) / "meteorology_hydrology.parquet", Path(history_dir) / "obs_pattern_satellite.csv", Path(history_dir) / "obs_pattern_station.csv"]})
    input_hashes = {p: sha256_file(Path(p)) for p in inputs}
    config_hash = content_hash(json.dumps(config, ensure_ascii=False, sort_keys=True, default=str))
    parameter_set_id = "ps-" + content_hash(json.dumps({"inputs": input_hashes, "generator": GENERATOR_VERSION, "config_hash": config_hash}, sort_keys=True))[:16]
    parameter_sets.insert(0, "parameter_set_id", parameter_set_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    parameter_sets.to_parquet(out_dir / "parameter_sets.parquet", index=False)
    manifest = {
        "status": "completed",
        "command": "fit",
        "split": "train",
        "train_cutoff_date": str(cutoff.date()),
        "cutoff_enforced_all_families": True,
        "per_family_max_input_date": per_family_max_input_date,
        "rule": "拟合仅使用日期<=train末期（隔离窗前）的真实/可解释约束记录；C3S/NOAA 预报不当真值；全部分支 cutoff 过滤（DG-002）",
        "input_filtering": {
            "weather_rows": int(len(weather)),
            "water_quality_rows": int(len(wq)),
            "meteorology_hydrology_rows": int(len(met_hyd)),
            "lake_surface_temperature_rows_with_valid_time": int(len(lake_temp_rows)),
        },
        "inputs_sha256": input_hashes,
        "config_hash": config_hash,
        "parameter_set_id": parameter_set_id,
        "n_parameters": int(len(parameter_sets)),
        "rows_written": int(len(parameter_sets)),
        "output": str(out_dir / "parameter_sets.parquet"),
    }
    (out_dir / "fit_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_param_lookup(parameter_sets: pd.DataFrame) -> Any:
    def lookup(family: str, key: str, scope_id: str | None = None) -> tuple[float | None, int]:
        frame = parameter_sets[(parameter_sets["family"] == family) & (parameter_sets["parameter_key"] == key)]
        if scope_id is not None:
            frame = frame[frame["scope_id"] == scope_id]
        if frame.empty:
            return None, 0
        best = frame.sort_values("n_samples", ascending=False).iloc[0]
        return float(best["value"]), int(best["n_samples"])

    return lookup
