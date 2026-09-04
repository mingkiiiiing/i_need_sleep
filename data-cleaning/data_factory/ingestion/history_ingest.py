"""历史数据接入 (设计 §7 十九类来源进入方式 + §8 原始留存).

- 发布表 TAIHU_CLEAN_FINAL_V1 → 规范码/规范单位 history parquet
- NASA POWER 本地原始逐时 JSON → 逐日真实观测气象（derived，带 source_file 血缘）
- 真实卫星过境模式 / 真实站点采样日历 → 观测层驱动
- 来源登记 source_registry.csv（含 taihugurad 采集来源与 LICENSE 事实）
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_factory.contracts.constants import DEFAULT_RELEASE_TABLES, NASA_POWER_RAW, SOURCE_REGISTRY_CSV
from data_factory.contracts.constants import utc_now_iso

TABLES = ["water_quality", "meteorology_hydrology", "remote_sensing", "static_features", "labels"]


def parse_aux(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def canonical_code(code: str, code_map: dict[str, str]) -> str:
    return code_map.get(code, code)


def convert_value(variable_code: str, value: float, unit: str, conversions: dict[str, dict[str, float]]) -> float:
    table = conversions.get(variable_code)
    if table and unit in table:
        return float(value) * float(table[unit])
    return float(value)


def ingest_release_tables(release_dir: Path, config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    code_map = config.get("variable_code_map", {})
    conversions = config.get("unit_conversions", {})
    out: dict[str, pd.DataFrame] = {}
    for name in TABLES:
        path = Path(release_dir) / "tables" / f"{name}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        frame["variable_code"] = frame["variable_code"].astype(str).map(lambda c: canonical_code(c, code_map))
        if "unit" in frame.columns:
            frame["value"] = frame.apply(
                lambda r: convert_value(r["variable_code"], r["value"], str(r["unit"]), conversions) if pd.notna(r.get("value")) else r.get("value"),
                axis=1,
            )
        aux = frame.get("aux")
        if aux is not None:
            frame["aux_dict"] = aux.map(parse_aux)
            frame["station_id"] = frame.apply(
                lambda r: (r["aux_dict"].get("station_id") or r.get("spatial_id") or "") if isinstance(r["aux_dict"], dict) else (r.get("spatial_id") or ""),
                axis=1,
            )
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce", utc=True)
        out[name] = frame
    return out


def _power_parameter_frames(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    return payload.get("properties", {}).get("parameter", {})


def ingest_nasa_power(raw_dir: Path) -> pd.DataFrame:
    """本地 NASA POWER 逐时 JSON → 逐日真实观测气象（UTC→Asia/Shanghai 当地日）。"""

    files = sorted(Path(raw_dir).glob("history_*.json"))
    rows: list[dict[str, Any]] = []
    source_files: list[str] = []
    for path in files:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        payload = body.get("payload") or body
        params = _power_parameter_frames(payload)
        if not params:
            continue
        source_files.append(path.name)
        series: dict[str, pd.Series] = {}
        for key, values in params.items():
            index = pd.to_datetime(pd.Series(list(values.keys())), format="%Y%m%d%H", errors="coerce")
            data = pd.to_numeric(pd.Series(list(values.values()), dtype=float), errors="coerce")
            data[data <= -999.0] = np.nan
            index_utc = index.dt.tz_localize("UTC")
            series[key] = pd.Series(data.to_numpy(), index=index_utc)
        frame = pd.DataFrame(series).dropna(how="all")
        if frame.empty:
            continue
        local = frame.tz_convert("Asia/Shanghai")
        local["date"] = local.index.date
        grouped = local.groupby("date")
        daily = pd.DataFrame(
            {
                "air_temperature": grouped["T2M"].mean() if "T2M" in local else np.nan,
                "wind_speed": grouped["WS10M"].mean() if "WS10M" in local else np.nan,
                "wind_u": grouped.apply(lambda g: float(np.nanmean(-g["WS10M"] * np.sin(np.radians(g["WD10M"])))) if {"WS10M", "WD10M"}.issubset(g.columns) else np.nan),
                "wind_v": grouped.apply(lambda g: float(np.nanmean(-g["WS10M"] * np.cos(np.radians(g["WD10M"])))) if {"WS10M", "WD10M"}.issubset(g.columns) else np.nan),
                "precipitation": grouped["PRECTOTCORR"].sum(min_count=12) if "PRECTOTCORR" in local else np.nan,
                "shortwave_radiation": grouped["ALLSKY_SFC_SW_DWN"].sum(min_count=12) if "ALLSKY_SFC_SW_DWN" in local else np.nan,
            }
        ).reset_index()
        daily.columns = ["date", "air_temperature", "wind_speed", "wind_u", "wind_v", "precipitation", "shortwave_radiation"]
        rows.append(daily)
    if not rows:
        return pd.DataFrame(columns=["date", "air_temperature", "wind_speed", "wind_u", "wind_v", "precipitation", "shortwave_radiation", "source_file"])
    result = pd.concat(rows, ignore_index=True)
    result = result.groupby("date", as_index=False).mean(numeric_only=True)
    result = result.dropna(subset=["air_temperature"], how="all")
    # 辐射单位自检：按量级判别——逐时 W/m² 的 24h 求和（年均 ~3600）×0.0036→MJ/m2/day；
    # kWh/m2/day 求和（年均 ~3.7）×3.6→MJ/m2/day；年均 8~25 视为已是 MJ/m2/day
    rad_mean = float(np.nanmean(result["shortwave_radiation"].to_numpy(dtype=float))) if result["shortwave_radiation"].notna().any() else 0.0
    if rad_mean > 100:
        result["shortwave_radiation"] = result["shortwave_radiation"] * 0.0036
    elif 0 < rad_mean <= 6.0:
        result["shortwave_radiation"] = result["shortwave_radiation"] * 3.6
    result["unit"] = "degC|m/s|m/s|m/s|mm|MJ_m2_day"
    result["provenance_type"] = "derived"
    result["is_ground_truth"] = False
    result["source_file"] = ";".join(source_files)
    result["date"] = pd.to_datetime(result["date"])
    return result


def build_obs_pattern_satellite(remote_sensing: pd.DataFrame) -> pd.DataFrame:
    if remote_sensing.empty:
        return pd.DataFrame(columns=["date", "source_variable", "coverage_frac", "cloud_ratio"])
    rows = []
    frame = remote_sensing.copy()
    if "aux_dict" not in frame.columns:
        frame["aux_dict"] = frame.get("aux", pd.Series(dtype=object)).map(parse_aux)
    for (date, variable), group in frame.groupby([frame["observed_at"].dt.date, "variable_code"]):
        aux = group["aux_dict"].iloc[0] if isinstance(group["aux_dict"].iloc[0], dict) else {}
        rows.append(
            {
                "date": date,
                "source_variable": variable,
                "coverage_frac": aux.get("coverage_frac"),
                "cloud_ratio": aux.get("cloud_ratio"),
            }
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["date", "source_variable"])


def build_obs_pattern_station(water_quality: pd.DataFrame) -> pd.DataFrame:
    frame = water_quality.copy()
    frame["date"] = frame["observed_at"].dt.date
    pattern = (
        frame.groupby(["station_id", "date"]).size().reset_index(name="n_records")
    )
    dates = pd.to_datetime(pattern["date"])
    pattern["month"] = dates.dt.month
    pattern["weekday"] = dates.dt.weekday
    return pattern


_REGISTRY_ROWS: list[dict[str, str]] = [
    {"source_id": "c3s_seasonal", "category_role": "外源气象情景与集合不确定性", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "forecast_input；不得当真值"},
    {"source_id": "era5_lake_temp", "category_role": "水温派生约束", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "derived"},
    {"source_id": "taihu_water_quality", "category_role": "水质/生物校准与部分观测", "handles_real_labels": "conditional", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "ground_truth；月度为主"},
    {"source_id": "taihu_hydrology", "category_role": "水位/雨量约束", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "ground_truth 水位"},
    {"source_id": "taihu_static_features", "category_role": "静态空间特征", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "metadata/derived"},
    {"source_id": "sentinel2_cdse_monthly_30m", "category_role": "遥感派生指数", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "derived/proxy"},
    {"source_id": "modis_aqua_chla", "category_role": "遥感派生叶绿素", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "derived/proxy"},
    {"source_id": "taihu_field_samples", "category_role": "现场样本", "handles_real_labels": "conditional", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "ground_truth 稀疏"},
    {"source_id": "noaa_gfs", "category_role": "短期预报", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "forecast_input"},
    {"source_id": "clms_lwq_300m_10daily_v2", "category_role": "十日水质代理", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "proxy"},
    {"source_id": "clms_lwq_300m_v2", "category_role": "单资产叶绿素代理", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "proxy"},
    {"source_id": "legacy_intermediate", "category_role": "旧中间产物", "handles_real_labels": "no", "provenance_state": "metadata_only", "automation_status": "registered", "notes": ""},
    {"source_id": "mee_surface_water_monthly", "category_role": "月报元数据", "handles_real_labels": "no", "provenance_state": "metadata_only", "automation_status": "implemented", "notes": "禁 OCR 猜测"},
    {"source_id": "legacy_unclassified", "category_role": "旧未分类", "handles_real_labels": "no", "provenance_state": "metadata_only", "automation_status": "registered", "notes": ""},
    {"source_id": "data_portal_catalog", "category_role": "公开门户目录", "handles_real_labels": "no", "provenance_state": "metadata_only", "automation_status": "registered", "notes": ""},
    {"source_id": "modis_aqua_chla_l2", "category_role": "L2 叶绿素", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "derived"},
    {"source_id": "sentinel3_olci", "category_role": "OLCI 资产状态", "handles_real_labels": "no", "provenance_state": "blocked_auth", "automation_status": "registered", "notes": "blocked_auth"},
    {"source_id": "bloom_archive", "category_role": "蓝藻样例元数据", "handles_real_labels": "conditional", "provenance_state": "metadata_only", "automation_status": "registered", "notes": ""},
    {"source_id": "thqbca_archive", "category_role": "THQBCA-V2 档案", "handles_real_labels": "conditional", "provenance_state": "cleaned", "automation_status": "implemented", "notes": "ground_truth 主来源"},
    {"source_id": "nasa_power_hourly", "category_role": "真实观测气象（逐时→逐日）", "handles_real_labels": "no", "provenance_state": "derived", "automation_status": "implemented_local_ingest", "notes": "本地原始 JSON 零流量接入；校准用"},
    {"source_id": "mee_surface_water_realtime", "category_role": "国控水质实时观测候选", "handles_real_labels": "no", "provenance_state": "cleaned", "automation_status": "implemented_realtime_snapshot", "notes": "taihugurad 重写式适配；上游 README 声称 MIT 但无 LICENSE 文件；tls_verify 配置化留痕"},
    {"source_id": "taihugurad_stations_json", "category_role": "站点注册引导", "handles_real_labels": "no", "provenance_state": "metadata_only", "automation_status": "implemented", "notes": "61 站；含坏地理编码需边界校验"},
    {"source_id": "open_meteo_history", "category_role": "补充历史气象", "handles_real_labels": "no", "provenance_state": "blocked_confirm", "automation_status": "implemented_not_downloaded", "notes": ">50MB 需 --yes 闸门"},
    {"source_id": "qweather_realtime", "category_role": "实时/预报气象补充", "handles_real_labels": "no", "provenance_state": "blocked_auth", "automation_status": "implemented_key_gated", "notes": "需 QWEATHER_API_KEY"},
    {"source_id": "gee_remote_features", "category_role": "GEE 遥感特征", "handles_real_labels": "no", "provenance_state": "blocked_auth", "automation_status": "planner_only", "notes": "需 earthengine authenticate"},
]


def build_source_registry() -> pd.DataFrame:
    frame = pd.DataFrame(_REGISTRY_ROWS)
    frame["registered_at_utc"] = utc_now_iso()
    return frame


def run_ingest_history(config: dict[str, Any], *, release_dir: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = ingest_release_tables(release_dir, config)
    outputs: dict[str, str] = {}
    for name, frame in tables.items():
        path = out_dir / f"{name}.parquet"
        frame.drop(columns=["aux_dict"], errors="ignore").to_parquet(path, index=False)
        outputs[name] = str(path)

    weather = ingest_nasa_power(NASA_POWER_RAW)
    weather_path = out_dir / "weather_observed_daily.parquet"
    weather.to_parquet(weather_path, index=False)
    outputs["weather_observed_daily"] = str(weather_path)

    satellite_pattern = build_obs_pattern_satellite(tables.get("remote_sensing", pd.DataFrame()))
    satellite_path = out_dir / "obs_pattern_satellite.csv"
    satellite_pattern.to_csv(satellite_path, index=False)
    outputs["obs_pattern_satellite"] = str(satellite_path)

    station_pattern = build_obs_pattern_station(tables.get("water_quality", pd.DataFrame()))
    station_path = out_dir / "obs_pattern_station.csv"
    station_pattern.to_csv(station_path, index=False)
    outputs["obs_pattern_station"] = str(station_path)

    registry = build_source_registry()
    registry_path = out_dir / "source_registry.csv"
    registry.to_csv(registry_path, index=False)
    outputs["source_registry"] = str(registry_path)

    return {
        "status": "completed",
        "command": "ingest-history",
        "rows_read": int(sum(len(f) for f in tables.values())) + int(len(weather)),
        "rows_written": int(sum(len(f) for f in tables.values())) + int(len(weather)) + int(len(satellite_pattern)) + int(len(station_pattern)),
        "weather_observed_days": int(weather["date"].nunique()) if not weather.empty else 0,
        "weather_source_files": int(weather["source_file"].iloc[0].count(";") + 1) if not weather.empty else 0,
        "satellite_pass_dates": int(satellite_pattern["date"].nunique()) if not satellite_pattern.empty else 0,
        "station_sample_dates": int(station_pattern["date"].nunique()) if not station_pattern.empty else 0,
        "outputs": outputs,
    }
