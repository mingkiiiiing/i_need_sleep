# -*- coding: utf-8 -*-
"""气象数据清洗：NASA POWER 逐小时历史产品（原始 JSON）。

- 站点: 太湖城区格点 (120.30E, 31.20N) 单点
- 变量: T2M(空气温度℃) WS10M(10m风速m/s) WD10M(风向°) PRECTOTCORR(降水mm/hr)
        ALLSKY_SFC_SW_DWN(向下短波辐射 W/m²)
- 时间统一为北京时间；数值质量标记；单位统一。

输出: merged_data/2026_sheng-fuwai-main-merge/cleaned/meteorology_cleaned.csv (+ .parquet)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (  # noqa: E402
    ROOT, STORAGE, PHYSICAL_RANGES, bnow, date_of, datetime_of, flag_join,
    map_variable, month_of, to_number, write_dataset,
)

RAW_ROOT = STORAGE / "raw/nasa_power_hourly"
SOURCE_NAME = "nasa_power_hourly"

# NASA POWER 参数 → (标准变量, 目标单位, 物理范围)
PARAM_MAP = {
    "T2M": ("air_temperature", "℃", (-60.0, 60.0)),
    "T2MDEW": ("dew_point_temperature", "℃", (-80.0, 50.0)),
    "WS2M": ("wind_speed_2m", "m/s", (0.0, 100.0)),
    "WS10M": ("wind_speed_10m", "m/s", (0.0, 100.0)),
    "WD2M": ("wind_direction", "°", (0.0, 360.0)),
    "WD10M": ("wind_direction", "°", (0.0, 360.0)),
    "PRECTOTCORR": ("precipitation", "mm/hour", (0.0, 200.0)),
    "ALLSKY_SFC_SW_DWN": ("shortwave_radiation", "W/m²", (0.0, 2000.0)),
    "RH2M": ("relative_humidity", "%", (0.0, 100.0)),
    "PS": ("surface_pressure", "hPa", (500.0, 1100.0)),
    "TCDC": ("total_cloud_cover", "%", (0.0, 100.0)),
}


def clean() -> pd.DataFrame:
    rows: list[dict] = []
    files = sorted(RAW_ROOT.glob("history_*.json"))
    years_ok, years_fail = [], []
    for p in files:
        m = re.search(r"history_(\d{4})\.json", p.name)
        year = m.group(1) if m else ""
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            payload = data.get("payload", data)
            geo = payload.get("geometry") or {}
            coords = geo.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            if lon is None or lat is None:
                props = payload.get("properties") or {}
                lon = (props.get("parameter", {}).get("_LON") or props.get("header", {}).get("lons") or [None])[0] \
                    if isinstance(props.get("parameter", {}).get("_LON") or props.get("header", {}).get("lons"), list) \
                    else None
                lat = lon  # 尽力, 后续校验
            params = (payload.get("properties") or {}).get("parameter") or {}
            prop_params = params
            station_id = f"NASA_POWER_{float(lon):.3f}_{float(lat):.3f}"
            for param, series in prop_params.items():
                vcode = param.split(".")[0].upper() if param.startswith("_") else param.upper()
                if vcode not in PARAM_MAP:
                    continue
                var, unit, (lo, hi) = PARAM_MAP[vcode]
                for hour_key, raw in series.items():
                    ts = pd.Timestamp(f"{hour_key[:4]}-{hour_key[4:6]}-{hour_key[6:8]} {hour_key[8:10]}:00:00",
                                      tz="UTC")
                    ts = ts.tz_convert("Asia/Shanghai").tz_localize(None)
                    val = to_number(raw)
                    flags, notes = [], []
                    if np.isnan(val):
                        flags.append("Q03"); notes.append("数值缺失")
                    else:
                        if not (lo <= val <= hi):
                            flags.append("Q05"); notes.append(f"超出物理合理范围({lo}-{hi})")
                    rows.append(dict(
                        station_id=station_id,
                        station_name=f"太湖区格点 {station_id}",
                        observed_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
                        date=ts.strftime("%Y-%m-%d"), month=ts.strftime("%Y-%m"),
                        variable_code=var, value=val,
                        value_text="" if not np.isnan(val) else str(raw),
                        unit=unit, quality_flag=flag_join(flags),
                        quality_note="; ".join(notes) + "; NASA POWER 卫星-再分析格点产品" if notes
                        else "NASA POWER 卫星-再分析格点产品",
                        source_name=SOURCE_NAME, source_file=str(p.relative_to(STORAGE)),
                        source_row=str(hour_key), source_unit=str(param),
                        conversion_rule="UTC→北京; 单位取 NASA POWER 定义",
                        value_origin="satellite_reanalysis_grid",
                        longitude=lon, latitude=lat, acquisition_date=bnow().strftime("%Y-%m-%d %H:%M:%S"),
                    ))
            years_ok.append(year)
        except Exception as e:
            years_fail.append((year, str(e)[:80]))
            print(f"  [NASA] {p.name} 解析失败: {e}")
    df = pd.DataFrame(rows)
    print(f"  [NASA POWER] 成功年份 {years_ok}, 失败 {years_fail}")
    print(f"  行数 {len(df)}, 站点 {df['station_id'].unique().tolist()}, "
          f"时间 {df['observed_at'].min()} -> {df['observed_at'].max()}" if len(df) else "无记录")
    return df


def main() -> pd.DataFrame:
    print("== 气象清洗 ==")
    df = clean()
    if len(df):
        df["_t"] = pd.to_datetime(df["observed_at"], errors="coerce")
        df = df.sort_values(["_t", "station_id", "variable_code"]).drop(columns="_t").reset_index(drop=True)
    path = write_dataset(df, "meteorology_cleaned")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列")
    return df


if __name__ == "__main__":
    main()
