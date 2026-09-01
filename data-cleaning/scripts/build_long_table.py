# -*- coding: utf-8 -*-
"""生成统一长表 all_data_long:
每一行 = 某个时间、位置、指标的一次观测(或派生汇总, quality_flag 标注)。

字段: datetime, date, month, station_id, station_name, longitude, latitude,
      category, variable, value, value_text, unit, quality_flag, quality_note,
      source_name, source_file, source_url, acquisition_date, dataset_split

排序: 时间升序 → station_id → variable。dataset_split: <2025 train / 2025 validation / >=2026 test。
输出: merged_data/2026_sheng-fuwai-main-merge/cleaned/all_data_long.csv (+ .parquet)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, bnow, write_dataset

LONG_COLS = [
    "datetime", "date", "month", "station_id", "station_name", "longitude", "latitude",
    "category", "variable", "value", "value_text", "unit", "quality_flag", "quality_note",
    "source_name", "source_file", "source_url", "acquisition_date", "dataset_split",
]


def split_of(month: str) -> str:
    if not month or pd.isna(month):
        return ""
    y = int(month[:4])
    if y <= 2024:
        return "train"
    if y == 2025:
        return "validation"
    return "test"


def _norm(df: pd.DataFrame, category: str) -> pd.DataFrame:
    df = df.copy()
    out = pd.DataFrame(columns=LONG_COLS)
    if df.empty:
        return out
    for col in LONG_COLS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[LONG_COLS]
    df["datetime"] = df["datetime"].fillna("")
    df["month"] = df["month"].astype(str)
    if (df["datetime"] == "").any() == False and len(df):
        pass
    df["dataset_split"] = df["month"].map(split_of)
    df["acquisition_date"] = df["acquisition_date"].fillna(bnow().strftime("%Y-%m-%d %H:%M:%S"))
    df["category"] = category
    return df


def from_water_quality() -> pd.DataFrame:
    p = CLEANED / "water_quality_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    if df.empty:
        return _norm(df, "water_quality")
    df = df.rename(columns={"observed_at": "datetime", "variable_code": "variable", "source_unit": "unit_orig"})
    df["datetime"] = df["datetime"].fillna("")
    df["source_url"] = ""
    df["value_text"] = df.get("value_text", "")
    return _norm(df, "water_quality")


def from_meteorology() -> pd.DataFrame:
    p = CLEANED / "meteorology_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    df = df.rename(columns={"observed_at": "datetime", "variable_code": "variable"})
    df["source_url"] = "https://power.larc.nasa.gov/"
    df["value_text"] = ""
    return _norm(df, "meteorology")


def from_hydrology() -> pd.DataFrame:
    p = CLEANED / "hydrology_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    df = df.rename(columns={"observed_at": "datetime", "variable_code": "variable"})
    if "scene_id" in df.columns:
        df = df.drop(columns=["scene_id"])
    df["source_url"] = ""
    df["value_text"] = ""
    return _norm(df, "hydrology")


def from_field_samples() -> pd.DataFrame:
    p = CLEANED / "field_samples_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    rows = []
    variable_map = [
        ("chla_mg_l", "chla", "mg/L"),
        ("tsm_mg_l", "tsm", "mg/L"),
        ("sdd_m", "sdd", "m"),
        ("water_temp_c", "water_temperature", "℃"),
    ]
    for _, r in df.iterrows():
        for col, var, unit in variable_map:
            v = r.get(col)
            if v is None or pd.isna(v):
                continue
            rows.append(dict(
                datetime=r["observed_at"], date=r.get("date"), month=r.get("month"),
                station_id=r["station_id"], station_name=r.get("station_name"),
                longitude=r.get("longitude"), latitude=r.get("latitude"),
                variable=var, value=v, value_text="", unit=unit,
                quality_flag=r.get("quality_flag", "Q00"), quality_note=r.get("quality_note", ""),
                source_name="zenodo_taihu_insitu", source_file=r.get("source_file", ""),
                source_url="", acquisition_date=r.get("acquisition_date", ""),
            ))
        for w in (490, 560, 665, 705, 842):
            v = r.get(f"rrs_{w}")
            if v is None or pd.isna(v):
                continue
            rows.append(dict(
                datetime=r["observed_at"], date=r.get("date"), month=r.get("month"),
                station_id=r["station_id"], station_name=r.get("station_name"),
                longitude=r.get("longitude"), latitude=r.get("latitude"),
                variable=f"rrs_{w}", value=v, value_text="", unit="sr^-1",
                quality_flag=r.get("quality_flag", "Q00"),
                quality_note="源自现场光谱实测(插值到标准波长)", source_name="zenodo_taihu_insitu",
                source_file=r.get("source_file", ""), source_url="",
                acquisition_date=r.get("acquisition_date", ""),
            ))
    out = pd.DataFrame(rows)
    return _norm(out, "field_samples")


def from_static() -> pd.DataFrame:
    p = CLEANED / "static_features_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    df = df.rename(columns={"entity_id": "station_id", "feature_name": "variable"})
    df["station_name"] = df["station_id"]
    df["datetime"] = ""
    df["month"] = ""
    df["longitude"] = np.nan
    df["latitude"] = np.nan
    df["source_url"] = ""
    df["value_text"] = ""
    return _norm(df, "static_features")


def from_remote() -> pd.DataFrame:
    p = CLEANED / "remote_sensing_monthly_cleaned.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    rows = []
    for _, r in df.iterrows():
        rows.append(dict(
            datetime=f"{r['month']}-01" if r.get("month") else "",
            date=f"{r['month']}-01" if r.get("month") else "", month=r.get("month"),
            station_id="TAIHU_REMOTE", station_name="太湖全湖(遥感)", longitude=120.23, latitude=31.22,
            variable=f"rs_{r['product']}_{r['variable']}", value=r.get("mean"),
            value_text="", unit="retrieval_unit",
            quality_flag=r.get("quality_flag", "Q00"),
            quality_note=f"全湖统计行; median={r.get('median', np.nan):.4g} "
                         f"std={r.get('std', np.nan):.4g} {r.get('quality_note', '')} "
                         f"coverage={r.get('coverage_frac', np.nan):.3f} n={r.get('n_files')}"
                         if pd.notna(r.get("median")) else f"{r.get('quality_note', '')}",
            source_name=r["product"],
            source_file="remote_sensing_monthly_cleaned.csv",
            source_url="", acquisition_date=bnow().strftime("%Y-%m-%d %H:%M:%S"),
        ))
    out = pd.DataFrame(rows)
    return _norm(out, "remote_sensing")


def main() -> pd.DataFrame:
    print("== 长表构建 ==")
    parts = [
        ("water_quality", from_water_quality()),
        ("meteorology", from_meteorology()),
        ("hydrology", from_hydrology()),
        ("field_samples", from_field_samples()),
        ("static_features", from_static()),
        ("remote_sensing", from_remote()),
    ]
    frames = []
    for name, df in parts:
        frames.append(df)
        print(f"  [{name}] {len(df)} 行")
    df = pd.concat(frames, ignore_index=True)
    df["_dt"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["_dt"] = df["_dt"].fillna(pd.Timestamp("1900-01-01"))
    df["_st"] = df["station_id"].fillna("")
    df["_var"] = df["variable"].fillna("")
    df = df.sort_values(["_dt", "_st", "_var"]).drop(columns=["_dt", "_st", "_var"]).reset_index(drop=True)
    path = write_dataset(df, "all_data_long")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列")
    print(df.groupby(["category", "dataset_split"]).size().to_string())
    return df


if __name__ == "__main__":
    main()
