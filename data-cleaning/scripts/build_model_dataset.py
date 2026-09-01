# -*- coding: utf-8 -*-
"""机器学习月度数据集: 每一行 = 月份 × 站点(或采样点/格点)。

- 特征: 水质(wq_)、气象(met_)、水文(hydro_)、遥感月度(rs_)、静态(static_)
- 标签: target_chla / target_bloom / target_tp / target_tn / target_do
  仅地面观测可得; 无观测值保持为空, 不人工生成; target_*_source 列注明来源
- dataset_split: <=2024 train(历史数据一并纳入) / 2025 validation / >=2026 test

输出: merged_data/2026_sheng-fuwai-main-merge/cleaned/model_dataset_monthly.csv (+ .parquet)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, write_dataset

WQ_MONTHLY_VARS = ["ph", "do", "codmn", "tp", "po4_p", "tn", "nh4_n", "no3_n", "no2_n", "phyto_biomass"]
METEOR_VARS = {
    "air_temperature": "met_air_temperature_c", "precipitation": "met_precipitation_mm",
    "wind_speed_10m": "met_wind_speed_ms", "wind_direction": "met_wind_direction_deg",
    "shortwave_radiation": "met_shortwave_radiation_wm2",
}
SPLIT_RULE = {2022: "train", 2023: "train", 2024: "train", 2025: "validation", 2026: "test"}


def split_of(month: str) -> str:
    if not month:
        return ""
    y = int(month[:4])
    return SPLIT_RULE.get(y, "train")


def _read(name) -> pd.DataFrame:
    p = CLEANED / f"{name}.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, encoding="utf-8-sig")


def _station_type(s: str) -> str:
    if str(s).startswith("TAIHU_"):
        return "lake_subregion"
    if str(s).startswith("NASA_POWER"):
        return "grid_point"
    if s == "TH-01":
        return "realtime_station"
    if s == "S1":
        return "water_station"
    if str(s).startswith("IN_SITU"):
        return "field_sample_point"
    return "other"


def main() -> pd.DataFrame:
    print("== 月度宽表构建 ==")
    wq = _read("water_quality_cleaned")
    met = _read("meteorology_cleaned")
    hydro = _read("hydrology_cleaned")
    rs = _read("remote_sensing_monthly_cleaned")
    field = _read("field_samples_cleaned")
    stat = _read("static_features_cleaned")

    # ---- 水质(月度 THQBCA 各湖区变量) ----
    wq = wq[~wq["quality_flag"].astype(str).str.contains("Q13")].copy()
    wq["value"] = pd.to_numeric(wq["value"], errors="coerce")
    wqm = wq[wq["variable_code"].isin(WQ_MONTHLY_VARS)]
    wq_piv = wqm.pivot_table(index=["station_id", "month"], columns="variable_code",
                             values="value", aggfunc="mean").reset_index()
    wq_piv.columns = ["station_id", "month"] + [f"wq_{c}" for c in wq_piv.columns[2:]]
    wq_n = wqm.groupby(["station_id", "month"]).size().rename("n_wq_obs").reset_index()

    # ---- 标签来源: 地面 Chl-a (水站 S1 与现场样本) ----
    chla_rows: list[dict] = []
    s1 = wq[(wq["station_id"] == "S1") & (wq["variable_code"] == "chla")]
    for _, r in s1.iterrows():
        chla_rows.append(dict(station_id="S1", month=r["month"], target_chla=r["value"],
                              target_chla_source="taihu_water_station_batch"))
    for _, r in field.iterrows():
        if pd.notna(r.get("chla_mg_l")):
            chla_rows.append(dict(station_id=r["station_id"], month=r["month"],
                                  target_chla=r["chla_mg_l"], target_chla_source="zenodo_taihu_insitu"))
    chla_df = pd.DataFrame(chla_rows)

    # ---- MEE 月报评价(全湖) ----
    mee = _read("water_quality_cleaned")
    mee = mee[(mee["station_id"] == "TAIHU_WHOLE") &
              mee["variable_code"].str.startswith("category_")]
    mee_piv = mee.pivot_table(index="month", columns="variable_code",
                              values="value_text", aggfunc="first").reset_index()
    mee_piv.columns = ["month"] + ["mee_" + c.replace("category_", "") for c in mee_piv.columns[1:]]
    mee_cnt = mee[mee["variable_code"] == "category_monitoring_point_count"]\
        .groupby("month")["value"].first().rename("mee_monitoring_point_count").reset_index()
    mee_piv = mee_piv.merge(mee_cnt, on="month", how="left")

    # ---- 气象按月聚合(NASA POWER 格点) ----
    met["value"] = pd.to_numeric(met["value"], errors="coerce")
    agg: dict[str, str] = {}
    blocks = []
    for var in METEOR_VARS:
        sub = met[met["variable_code"] == var]
        if sub.empty:
            continue
        g = (sub.groupby(["station_id", "month"])["value"]
             .agg("mean" if var != "precipitation" else "sum")
             .rename(METEOR_VARS[var]).reset_index())
        blocks.append(g)
    met_g = blocks[0]
    for b in blocks[1:]:
        met_g = met_g.merge(b, on=["station_id", "month"], how="outer")

    # ---- 水文(全湖水位月聚合) ----
    hydro["value"] = pd.to_numeric(hydro["value"], errors="coerce")
    wl = hydro[hydro["variable_code"] == "water_level"]
    wl_lake = wl[wl["station_id"] == "TAIHU_WATER_LEVEL"].groupby("month").agg(
        hydro_water_level_m=("value", "mean"), hydro_water_level_std=("value", "std"),
        hydro_water_level_n_days=("value", "size")).reset_index()
    wl_th01 = wl[wl["station_id"] == "TH-01"][["station_id", "month"]]

    # ---- 遥感(月度全湖 + 年度 THQBCA) ----
    rs["mean"] = pd.to_numeric(rs["mean"], errors="coerce")
    rs_m = rs[rs["granularity"] != "annual"]
    rs_piv = rs_m.copy()
    rs_piv["key"] = "rs_" + rs_m["product"] + "_" + rs_m["variable"]
    rs_piv = rs_piv.pivot_table(index="month", columns="key", values="mean", aggfunc="first").reset_index()
    rs_low = (rs_m.groupby("month")["quality_flag"].apply(lambda s: ((s.astype(str) != "Q00").any()))
              .rename("rs_month_low_quality").reset_index())
    rs_a = rs[rs["granularity"] == "annual"].dropna(subset=["month"])
    rs_a["year"] = rs_a["month"].astype(str).str[:4]
    rs_apiv = rs_a.pivot_table(index="year", columns="variable", values="mean", aggfunc="first").reset_index()
    rs_apiv.columns = ["year"] + [f"rs_annual_{c}" for c in rs_apiv.columns[1:]]

    # ---- 静态特征 ----
    st_lake = stat[stat["entity_type"] == "lake"]
    lake_val = {k: _feat(st_lake, v) for k, v in {
        "static_lake_area_km2": "area_km2_calc",
        "static_lake_elevation_mean_m": "elevation_mean_m",
        "static_dem_valid_frac": "dem_valid_frac",
    }.items()}
    st_stat = stat[stat["entity_type"] == "station"].copy()
    st_stat["value"] = pd.to_numeric(st_stat["value"], errors="coerce")
    st_piv = st_stat.pivot_table(index="entity_id", columns="feature_name",
                                 values="value", aggfunc="first").reset_index()
    st_piv.columns = ["station_id"] + [f"static_station_{c}" for c in st_piv.columns[1:]]

    # ---- 站点注册(名称/坐标) ----
    reg: dict[str, dict] = {}
    for _, r in met.drop_duplicates("station_id").iterrows():
        reg[str(r["station_id"])] = dict(station_name=r.get("station_name"),
                                         longitude=r.get("longitude"), latitude=r.get("latitude"))
    for _, r in field.drop_duplicates("station_id").iterrows():
        reg[str(r["station_id"])] = dict(station_name=r.get("station_name"),
                                         longitude=r.get("longitude"), latitude=r.get("latitude"))
    reg.setdefault("TAIHU_WHOLE", dict(station_name="太湖全湖(18/17点位均值)", longitude=np.nan, latitude=np.nan))
    reg.setdefault("TH-01", dict(station_name="太湖梅梁湾站(水利部)", longitude=np.nan, latitude=np.nan))
    reg.setdefault("S1", dict(station_name="国家地表水自动监测站? (代码S1)", longitude=np.nan, latitude=np.nan))
    for z in ("ML", "GH", "ZS", "CT", "WT", "ST", "XK", "ET"):
        reg.setdefault(f"TAIHU_{z}", dict(station_name=f"TAIHU_{z}(湖区均值,无坐标)", longitude=np.nan, latitude=np.nan))

    # ---- 行网格: 站点 × 月份 ----
    parts = []
    parts.append(wq_piv[["station_id", "month"]])
    if len(met_g):
        parts.append(met_g[["station_id", "month"]])
    parts.append(mee_piv[["month"]].assign(station_id="TAIHU_WHOLE"))
    if len(chla_df):
        parts.append(chla_df[["station_id", "month"]])
    if len(wl_th01):
        parts.append(wl_th01)
    df = pd.concat(parts, ignore_index=True).drop_duplicates(["station_id", "month"]).reset_index(drop=True)
    df["station_type"] = df["station_id"].map(_station_type)
    print(f"  行网格: {df.shape[0]} 行 (站点 x 月), 站点数 {df['station_id'].nunique()}")

    # ---- 合并特征 ----
    df = df.merge(wq_piv, on=["station_id", "month"], how="left")
    df = df.merge(wq_n, on=["station_id", "month"], how="left")
    if len(met_g):
        df = df.merge(met_g, on=["station_id", "month"], how="left")
    df = df.merge(mee_piv, on="month", how="left")
    dup_cols = [c for c in df.columns if c.endswith("_x") and c[:-2] + "_y" in df.columns]
    for c in dup_cols:
        base = c[:-2]
        twin = base + "_y"
        df[base] = df[c].fillna(df[twin])
        df = df.drop(columns=[c, twin])
    df = df.merge(wl_lake, on="month", how="left")
    df = df.merge(rs_piv, on="month", how="left")
    df = df.merge(rs_low, on="month", how="left")
    if len(rs_apiv):
        df["year"] = df["month"].str[:4]
        df = df.merge(rs_apiv, on="year", how="left").drop(columns="year", errors="ignore")
    df = df.merge(st_piv, on="station_id", how="left")
    for k, v in lake_val.items():
        df[k] = v
    reg_df = pd.DataFrame([{"station_id": k, **v} for k, v in reg.items()])
    df = df.merge(reg_df, on="station_id", how="left")

    # ---- 标签 ----
    df = df.merge(chla_df, on=["station_id", "month"], how="left")
    for src, tgt in (("tp", "target_tp"), ("tn", "target_tn"), ("do", "target_do")):
        col = f"wq_{src}"
        if col in df.columns:
            df[tgt] = df[col]
            df[f"{tgt}_source"] = np.where(df[tgt].notna(), "taihu_thqbca_v2", None)
        else:
            df[tgt] = np.nan
            df[f"{tgt}_source"] = None
    df["target_bloom"] = np.nan
    df["target_bloom_source"] = None
    if "target_chla_source" not in df.columns:
        df["target_chla_source"] = None
    if "wq_chla" not in df.columns:
        df["wq_chla"] = df["target_chla"]
    df["target_chla_in_lake"] = df["target_chla"]

    # ---- 排序 + 拆分 ----
    df = df.sort_values(["month", "station_id"]).reset_index(drop=True)
    df["dataset_split"] = df["month"].map(split_of)
    df["rs_month_low_quality"] = df["rs_month_low_quality"].fillna(False)
    path = write_dataset(df, "model_dataset_monthly")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列")
    print("  split:", df.groupby("dataset_split").size().to_dict())
    print("  站点类型:", df.groupby("station_type").size().to_dict())
    print("  标签覆盖: chla=%d tp=%d tn=%d do=%d bloom=0" % (
        df["target_chla"].notna().sum(), df["target_tp"].notna().sum(),
        df["target_tn"].notna().sum(), df["target_do"].notna().sum()))
    return df


def _feat(df: pd.DataFrame, name) -> float:
    v = df[df["feature_name"] == name]["value"]
    return float(v.iloc[0]) if len(v) else np.nan


if __name__ == "__main__":
    main()
