# -*- coding: utf-8 -*-
"""现场采样/实验室数据清洗: Zenodo "Lake Taihu" 水槽试验数据集 (3 期 2020-12/2022-12/2023-10)。

- 每行 = 一个现场水样 (Date/Longitude/Latitude + Chl-a/TSM/SDD/Temp)
- Chl-a: 原单位 µg/L → 统一 mg/L (÷1000), 同时保留 chl_a_ug_l 原始列
- SDD: 原单位 cm → 同时保留 sdd_cm 与 sdd_m
- 光谱表 (350nm 起逐 nm) → 提取 rrs@490/560/665/705/842 (最邻近插值, 实测光谱数据)
- 坐标检查 WGS84 太湖范围

输出: merged_data/2026_sheng-fuwai-main-merge/cleaned/field_samples_cleaned.csv (+ .parquet)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (
    ROOT, STORAGE, TAIHU_BBOX, bnow, coerce_datetime, flag_join, to_number, write_dataset,
)

RAW_ROOT = STORAGE / "raw/zenodo_taihu_insitu"
SOURCE_NAME = "zenodo_taihu_insitu"
RRS_WAVELENGTHS = (490.0, 560.0, 665.0, 705.0, 842.0)


def _spectral_row_to_rrs(vals) -> dict:
    """谱表单元格(行): 波长列名 -> 反射率；按目标波长最近邻(±5nm)取插值。"""
    wave_cols: list[tuple[float, float]] = []   # (wavelength, value)
    for w_raw, v in vals:
        try:
            w = float(w_raw)
        except (TypeError, ValueError):
            continue
        vv = to_number(v)
        if np.isnan(vv):
            continue
        wave_cols.append((w, vv))
    if not wave_cols:
        return {}
    wave_cols.sort()
    ws = np.array([w for w, _ in wave_cols])
    vs = np.array([v for _, v in wave_cols])
    out = {}
    for target in RRS_WAVELENGTHS:
        if np.all(ws > target + 5) or np.all(ws < target - 5):
            continue
        v = float(np.interp(target, ws, vs))
        out[f"rrs_{int(target)}"] = v
    return out


def main() -> pd.DataFrame:
    print("== 现场样本清洗 ==")
    files = sorted(RAW_ROOT.glob("*.xlsx"))
    chunks, warnings = [], []
    for p in files:
        try:
            xl = pd.ExcelFile(p)
        except Exception as e:
            warnings.append(f"{p.name}: {e}")
            continue
        if "Water quality dataset" not in xl.sheet_names:
            warnings.append(f"{p.name}: 无 Water quality dataset 表")
            continue
        wq = xl.parse("Water quality dataset")
        # 规范化列名
        wq.columns = [str(c).strip() for c in wq.columns]
        colmap = {}
        for c in wq.columns:
            low = c.lower().replace(" ", "")
            if low.startswith("chl") or "叶绿素" in c:
                colmap[c] = "chla_ug_l"
            elif "tsm" in low or "悬浮" in c:
                colmap[c] = "tsm_mg_l"
            elif "sdd" in low or "secchi" in low or "透明" in c:
                colmap[c] = "sdd_cm"
            elif "temp" in low or "水温" in c:
                colmap[c] = "water_temp_c"
            elif "longitude" in low or "经度" in c:
                colmap[c] = "longitude"
            elif "latitude" in low or "纬度" in c:
                colmap[c] = "latitude"
            elif "date" in low or "时间" in c or "日期" in c:
                colmap[c] = "datetime_raw"
        wq = wq.rename(columns=colmap)
        # 光谱表
        spec = xl.parse("Water spectral dataset") if "Water spectral dataset" in xl.sheet_names else None
        spec_rows = {}
        if spec is not None:
            spec.columns = [str(c).strip() for c in spec.columns]
            for _, row in spec.iterrows():
                key = (str(row.get("Date", "")), str(row.get("Longitude", "")), str(row.get("Latitude", "")))
                spec_rows[key] = _spectral_row_to_rrs(zip(spec.columns[3:], row.values[3:]))
        for i, row in wq.iterrows():
            raw_date = row.get("datetime_raw")
            ts = coerce_datetime(raw_date)
            if pd.isna(ts):
                warnings.append(f"{p.name}: 时间无法解析 {raw_date!r}")
                continue
            lon = to_number(row.get("longitude"))
            lat = to_number(row.get("latitude"))
            chla_ug = to_number(row.get("chla_ug_l"))
            tsm = to_number(row.get("tsm_mg_l"))
            sdd_cm = to_number(row.get("sdd_cm"))
            temp = to_number(row.get("water_temp_c"))
            if all(np.isnan(v) for v in (lon, lat)):
                warnings.append(f"{p.name}: 缺坐标 {raw_date!r}")
                continue
            coord_ok = (TAIHU_BBOX["lon_min"] <= lon <= TAIHU_BBOX["lon_max"]
                        and TAIHU_BBOX["lat_min"] <= lat <= TAIHU_BBOX["lat_max"]) if not np.isnan(lon) else False
            flags = []
            notes = []
            if not coord_ok:
                flags.append("Q02"); notes.append("坐标超出太湖合理范围或缺失")
            if all(np.isnan(v) for v in (chla_ug, tsm, sdd_cm, temp)):
                flags.append("Q03"); notes.append("全部指标缺失")
            skey = (str(row.get("Date", "")), str(row.get("Longitude", "")), str(row.get("Latitude", "")))
            rrs = spec_rows.get(skey, {})
            chunks.append(dict(
                sample_id=f"{p.stem}_{i:03d}",
                station_id="IN_SITU_GROUP", station_name="野外采样点(独立坐标)",
                observed_at=ts.strftime("%Y-%m-%d %H:%M:%S"),
                date=ts.strftime("%Y-%m-%d"), month=ts.strftime("%Y-%m"),
                longitude=lon, latitude=lat,
                chla_ug_l=chla_ug, chla_mg_l=chla_ug / 1000.0 if not np.isnan(chla_ug) else np.nan,
                tsm_mg_l=tsm, sdd_cm=sdd_cm,
                sdd_m=sdd_cm / 100.0 if not np.isnan(sdd_cm) else np.nan,
                water_temp_c=temp,
                quality_flag=flag_join(flags), quality_note="; ".join(notes),
                source_name=SOURCE_NAME, source_file=str(p.relative_to(STORAGE)),
                source_row=str(int(i) + 2), acquisition_date=bnow().strftime("%Y-%m-%d %H:%M:%S"),
                **{f"rrs_{int(w)}": rrs.get(f"rrs_{int(w)}", np.nan) for w in RRS_WAVELENGTHS},
            ))
    df = pd.DataFrame(chunks)
    print(f"  [现场样本] {df.shape[0]} 个水样, 警告 {len(warnings)} 条")
    for w in warnings[:8]:
        print(f"    - {w}")
    # 去重: 同 时间+坐标+主要指标 完全一致
    before = len(df)
    df["_k"] = df.apply(lambda r: f"{r['observed_at']}|{round(r['longitude'], 6)}|{round(r['latitude'], 6)}|{r['chla_ug_l']}|{r['tsm_mg_l']}|{r['sdd_cm']}", axis=1)
    df = df.drop_duplicates(subset="_k").drop(columns="_k")
    path = write_dataset(df, "field_samples_cleaned")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列 (去重 {before - df.shape[0]})")
    return df


if __name__ == "__main__":
    main()
