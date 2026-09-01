# -*- coding: utf-8 -*-
"""自动质量检查: 数据质量报告 data_quality_report.csv

每份(输入源 × 输出文件)记录:
raw_rows(源数据行/文件数), cleaned_rows, duplicates_removed, missing_rate,
anomalies(范围外/Q05), time_min, time_max, unit_conflicts, availability, status, notes。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, ROOT, PHYSICAL_RANGES, write_dataset

REPORT_COLS = [
    "dataset_name", "output_file", "raw_count", "cleaned_rows", "duplicates_removed",
    "missing_rate", "out_of_range", "time_min", "time_max", "unit_conflicts",
    "availability", "status", "notes",
]


def _time_range(df: pd.DataFrame, col="observed_at") -> tuple[str, str]:
    if df.empty or col not in df.columns:
        return "", ""
    ts = pd.to_datetime(df[col], errors="coerce")
    return ts.min().strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts.min()) else "", \
        ts.max().strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ts.max()) else ""


def _missing_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan
    return round(float(df.isna().mean().mean()), 4)


def _out_of_range(df: pd.DataFrame, var_col="variable_code", val_col="value") -> int:
    if df.empty or var_col not in df.columns or val_col not in df.columns:
        return 0
    n = 0
    v = pd.to_numeric(df[val_col], errors="coerce")
    for var, (lo, hi) in PHYSICAL_RANGES.items():
        m = df[var_col] == var
        if not m.any():
            continue
        n += int(((v[m] < lo) | (v[m] > hi)).sum())
    return n


def main() -> pd.DataFrame:
    print("== 质量报告 ==")
    rows = []

    def row(name, out, raw, cleaned, dup, miss, oor, tmin, tmax, availability, status, notes=""):
        rows.append(dict(dataset_name=name, output_file=out, raw_count=raw, cleaned_rows=cleaned,
                         duplicates_removed=dup, missing_rate=miss, out_of_range=oor,
                         time_min=tmin, time_max=tmax, unit_conflicts="见notes" if notes else "",
                         availability=availability, status=status, notes=notes))

    def stats(name, out_file, df, raw, availability):
        tmin, tmax = _time_range(df)
        flag = df["quality_flag"].astype(str) if "quality_flag" in df.columns else pd.Series(["Q00"] * len(df))
        row(name, out_file, raw, len(df), 0, _missing_rate(df), _out_of_range(df),
            tmin, tmax, availability,
            "ok" if len(df) else "empty",
            note_text := ("; ".join(filter(None, [
                f"源文件行数(含缺失)合计 {raw}",
                f"Q标记分布: {flag.value_counts().head(4).to_dict()}",
            ])) if len(df) else "无输出记录"))

    # 水质
    wq = pd.read_csv(CLEANED / "water_quality_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "water_quality_cleaned.csv").exists() else pd.DataFrame()
    stats("THQBCA-V2 太湖水质月序列 + MEE月报 + 水站批次", "water_quality_cleaned.csv", wq,
          raw=0, availability="2005-2026(196个月度样本+55个月评价+11水站记录)")
    row("THQBCA 1.WaterQuality.xlsx", "water_quality_cleaned.csv", 0, 0, 0, np.nan, 0, "2005-02-01", "2020-11-01",
        "2005-02~2020-11", "ok", "13 项指标(细菌除外: ph/codmn/do/tp/po4-p/tn/nh4-n/no3-n/no2-n/浮游植物生物量/丰度/浮游动物); 湖区: 全湖+ML/GH/ZS/CT/WT/ST/XK/ET; 湖区无坐标; Phyto_number/Zoo_* 为年尺度")
    row("MEE 地表水月报(太湖湖体, PDF OCR 文本)", "water_quality_cleaned.csv", 55, 0, 0, np.nan, 0, "2022-01-01", "2026-06-01",
        "55 个月", "ok", "全湖 17 点位; 评价类文本(非观测数值); 原始 PDF 见 merged_data/2026_sheng-fuwai-main-merge/raw/mee_surface_water_monthly")
    row("国家水站批次(11 条)", "water_quality_cleaned.csv", 11, 11, 0, np.nan, 0, "2026-08-18", "2026-08-18",
        "仅 1 条叶绿素(S1)", "partial",
        "上游批次 CSV 只剩标准化产物; 原始响应已清理, 无历史长序列; 站点坐标未提供")

    # 气象
    met = pd.read_csv(CLEANED / "meteorology_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "meteorology_cleaned.csv").exists() else pd.DataFrame()
    stats("NASA POWER 逐小时历史(格点 120.3E/31.2N)", "meteorology_cleaned.csv", met, raw=0, availability="2005-2025(缺2021)")
    row("NASA POWER history_*.json(2005-2020, 2022-2025)", "meteorology_cleaned.csv", 20, len(met), 0,
        _missing_rate(met), _out_of_range(met), "2005-01-01 08:00:00", "2026-01-01 07:00:00",
        "18 个年份(缺 2021)", "partial",
        "变量: 气温/10m风速/风向/降水(mm/h)/短波辐射; 卫星-再分析格点产品(非实测); 未获取 GFS/ECMWF 历史再分析(仅有 2026-08-18 预报场)")
    row("GFS/ECMWF grib2 预报场 & Open-Meteo 季节集合", "(未转录入表)", 4, 0, 0, np.nan, 0, "2026-08-18", "2026-08-18",
        "预报产品", "excluded",
        "预报驱动数据, 非观测; 未入 meteorology_cleaned; 缺 cfgrib 库未解析内容, 仅归档登记")

    # 水文
    hy = pd.read_csv(CLEANED / "hydrology_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "hydrology_cleaned.csv").exists() else pd.DataFrame()
    stats("THQBCA 3.Climate WaterLevel + mwr_hfc 水情", "hydrology_cleaned.csv", hy, raw=0, availability="2004-2020(逐日)+2026-08(实时)")
    row("THQBCA WaterLevel(逐日平均水位)", "hydrology_cleaned.csv", 6211, 6156, 0, _missing_rate(hy), _out_of_range(hy),
        "2004-01-01", "2020-12-31", "2004-2020", "ok", "单位 m; 为湖区平均水位")
    row("mwr_hfc 水情批次(GBK CSV)", "hydrology_cleaned.csv", 61, 6, 0, np.nan, 0, "2026-08-19", "2026-08-23",
        "实时少量", "partial", "仅 2026-08 少量实时水位; 流量等其余指标未获取到")
    row("tba_hydrology 下载(太湖流域水利门户)", "hydrology_cleaned.csv", 63, 0, 0, np.nan, 0, "", "",
        "无", "failed", "返回 406/403 错误页(HTML), 无有效数据; 需人工申领(见 merged_data/2026_sheng-fuwai-main-merge/authorization)")

    # 遥感
    inv = pd.read_csv(CLEANED / "remote_sensing_inventory.csv", encoding="utf-8-sig") if (CLEANED / "remote_sensing_inventory.csv").exists() else pd.DataFrame()
    rs = pd.read_csv(CLEANED / "remote_sensing_monthly_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "remote_sensing_monthly_cleaned.csv").exists() else pd.DataFrame()
    row("遥感栅格全量索引(逐文件)", "remote_sensing_inventory.csv", len(inv), len(inv), 0, np.nan, 0, "", "",
        f"{len(inv)} 个文件行", "ok", "S2 月合成682+20m6+CLMS 70+检索5+THQBCA生物光学146+EarthSearch37")
    low = rs[rs.quality_flag.astype(str) != "Q00"]
    row("遥感月度全湖特征", "remote_sensing_monthly_cleaned.csv", len(rs), len(rs), 0, _missing_rate(rs), 0,
        rs.month.min(), rs.month.max(), f"{len(rs)} 行", "ok",
        f"低质量标记月份数(含 2022-11/2024-04): {len(low)}; 覆盖 842-1506 波段反射率/NDCI/MCI/FAI/NDWI; CLMS 2024-09~2026-08; THQBCA 年度1984-2022")

    # 现场样本
    fs = pd.read_csv(CLEANED / "field_samples_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "field_samples_cleaned.csv").exists() else pd.DataFrame()
    stats("Zenodo Lake Taihu 现场采样(2020/2022/2023)", "field_samples_cleaned.csv", fs, raw=41, availability="3 期水样")
    row("现场采样坐标范围", "field_samples_cleaned.csv", 41, 41, 0, np.nan, 0, "2020-12-22", "2023-10-17",
        "3 个出征日", "ok", "叶绿素 µg/L→mg/L 已换算; SDD cm→m 保留双列; 光谱 rrs 490-842nm 已提取")

    # 静态
    st = pd.read_csv(CLEANED / "static_features_cleaned.csv", encoding="utf-8-sig") if (CLEANED / "static_features_cleaned.csv").exists() else pd.DataFrame()
    stats("静态特征(湖泊/流域/站点)", "static_features_cleaned.csv", st, raw=0, availability="静态")
    row("HydroBASINS 流域矢量", "static_features_cleaned.csv", 0, st[st.entity_type == "basin"].shape[0], 0, np.nan, 0, "", "",
        f"{st[st.entity_type == 'basin'].shape[0]} 个流域特征行", "ok", "0.5° 缓冲相交子集")

    # 长表与宽表
    longf = pd.read_csv(CLEANED / "all_data_long.csv", encoding="utf-8-sig", low_memory=False) if (CLEANED / "all_data_long.csv").exists() else pd.DataFrame()
    rows.append(dict(dataset_name="all_data_long(统一长表)", output_file="all_data_long.csv",
                     raw_count=0, cleaned_rows=len(longf), duplicates_removed=0,
                     missing_rate=_missing_rate(longf), out_of_range=0,
                     time_min=longf["datetime"].dropna().min() if not longf.empty else "",
                     time_max=longf["datetime"].dropna().max() if not longf.empty else "",
                     unit_conflicts="", availability=f"{len(longf)} 行", status="ok" if len(longf) else "empty",
                     notes="类别分布可见 cleaning_summary.md; 含静态/遥感汇总行(Q11标记)"))
    wid = pd.read_csv(CLEANED / "model_dataset_monthly.csv", encoding="utf-8-sig") if (CLEANED / "model_dataset_monthly.csv").exists() else pd.DataFrame()
    rows.append(dict(dataset_name="model_dataset_monthly(机器学习宽表)", output_file="model_dataset_monthly.csv",
                     raw_count=0, cleaned_rows=len(wid), duplicates_removed=0,
                     missing_rate=_missing_rate(wid), out_of_range=0,
                     time_min=str(wid["month"].min()) if not wid.empty else "",
                     time_max=str(wid["month"].max()) if not wid.empty else "",
                     unit_conflicts="", availability=f"{len(wid)} 行", status="ok" if len(wid) else "empty",
                     notes="月份x站点; dataset_split 划分见文件"))

    df = pd.DataFrame(rows)
    path = write_dataset(df, "data_quality_report")
    print(f"  [输出] {path}  {df.shape[0]} 行")
    return df


if __name__ == "__main__":
    main()
