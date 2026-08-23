# -*- coding: utf-8 -*-
"""水质数据清洗：THQBCA-V2 (太湖各湖区月尺度 pH/COD/DO/TP/TN…)、
MEE 地表水月报(太湖湖体评价)、国家水站批次(HJ1404 自动监测)。

输出: storage/cleaned/water_quality_cleaned.csv (+ .parquet)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (  # noqa: E402
    CLEANED, ROOT, STORAGE, PHYSICAL_RANGES, Q_FLAGS, flag_join,
    coerce_datetime, date_of, datetime_of, is_missing, map_variable,
    month_of, to_number, write_dataset,
)

SOURCE_NAME = "taihu_thqbca_v2_water_quality"
SOURCE_NAME_MEE = "mee_surface_water_monthly_report"
SOURCE_NAME_STATION = "taihu_water_station_batch"

WQ_CSV = CLEANED / "water_quality_cleaned.csv"

LONG_COLS = [
    "station_id", "station_name", "observed_at", "date", "month",
    "variable_code", "value", "value_text", "unit", "quality_flag",
    "quality_note", "source_name", "source_file", "source_row",
    "source_unit", "conversion_rule", "value_origin",
]


# ----------------------------- THQBCA -----------------------------
def clean_thqbca(records: list[dict]) -> pd.DataFrame:
    xlsx = ROOT / "storage/raw/taihu_thqbca_zenodo/extracted/THQBCA-V2/1.WaterQuality/1WaterQuality.xlsx"
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    per_source = {"_filter": []}
    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        header = rows[0]
        # Date 列 + 湖区列；最后一个非空表头常为单位，如 "(mg/L)"、"(-)"
        # 注意: read_only 模式下末尾可能补 None 列, 需取最后一个非空表头
        unit_str = ""
        for h in reversed(header):
            if h is not None:
                unit_str = str(h).strip()
                break
        unit = _unit_from_header(unit_str)
        var_raw = sheet.title
        variable = map_variable(var_raw)
        zones = [str(h).strip() for h in header[1:] if _is_station_header(h) and h is not None]
        if "(-)" in zones:
            zones.remove("(-)")
        for data_row in rows[1:]:
            if data_row is None or len(data_row) < 2:
                continue
            raw_date = data_row[0]
            # 年份整数 → 年尺度记录
            annual = False
            if isinstance(raw_date, (int, float)) and 1900 <= float(raw_date) <= 2100:
                ts = pd.Timestamp(f"{int(raw_date)}-01-01")
                annual = True
            else:
                ts = coerce_datetime(raw_date)
            if pd.isna(ts):
                per_source["_filter"].append(str(raw_date))
                continue
            for j, zone_raw in enumerate(zones):
                zone = str(zone_raw).strip()
                if zone == "(-)" or zone == "":
                    continue
                raw = data_row[j + 1]
                if is_missing(raw):
                    continue  # 空单元格: 源缺失观测, 不产生行
                val = to_number(raw)
                station = "TAIHU_WHOLE" if zone.casefold() == "whole lake" else f"TAIHU_{zone}"
                flags, note = _wq_checks(variable, val, ts, station)
                if annual:
                    flags = flag_join([flags, "Q13"]) if flags != "Q00" else "Q13"
                    note = (note + "; 年尺度").strip().strip(";")
                records.append(dict(
                    station_id=station, station_name=station, observed_at=datetime_of(ts),
                    date=date_of(ts), month=month_of(ts), variable_code=variable,
                    value=val if not np.isnan(val) else np.nan,
                    value_text="" if not np.isnan(val) else str(raw),
                    unit=unit if not np.isnan(val) else "", quality_flag=flags,
                    quality_note=f"{note}; 数据源未提供湖区坐标" if station != "TAIHU_WHOLE" else note,
                    source_name=SOURCE_NAME, source_file=str(xlsx.relative_to(ROOT)),
                    source_row=f"{sheet.title}:{rows.index(data_row) + 2}:{zone}",
                    source_unit=unit_str, conversion_rule="", value_origin="observed",
                ))
    wb.close()
    if per_source["_filter"]:
        print(f"  [THQBCA] 无法解析日期 {len(per_source['_filter'])} 个(已跳过): {set(str(x) for x in per_source['_filter'][:5])}")
    return pd.DataFrame()


def _unit_from_header(raw: str) -> str:
    m = re.search(r"\(([^()]*)\)", str(raw))
    if not m:
        return ""
    u = m.group(1).strip()
    lower = u.lower()
    if lower in ("-", "—", "/", ""):
        return ""
    return {"mg/l": "mg/L", "mg/l:": "mg/L", "µg/l": "µg/L", "μg/l": "µg/L",
            "℃": "℃", "°c": "℃", "m3": "m³", "cells/l": "cells/L"}.get(lower, u)


def _is_station_header(h) -> bool:
    if h is None:
        return False
    s = str(h).strip()
    if not s or s in ("(-)", "(mg/L)", "(μm)", "(10 4 cells/L)", "(μg/l)", "(℃)"):
        return True if s in ("(-)", "") or not s.startswith("(") else False
    return not s.startswith("(")


def _wq_checks(variable: str, val: float, ts, station: str) -> tuple[str, str]:
    flags, notes = [], []
    if np.isnan(val):
        flags.append("Q03"); notes.append("数值缺失")
    elif variable in PHYSICAL_RANGES:
        lo, hi = PHYSICAL_RANGES[variable]
        if not (lo <= val <= hi):
            flags.append("Q05"); notes.append(f"超出物理合理范围({lo}-{hi})")
    if pd.isna(ts):
        flags.append("Q01"); notes.append("时间无法解析")
    if station != "TAIHU_WHOLE":
        flags.append("Q12"); notes.append("湖区无坐标元数据")
    return flag_join(flags), "; ".join(notes)


# ----------------------------- MEE 月报 -----------------------------
def parse_mee_text(text: str) -> dict:
    out: dict[str, dict] = {}
    seg = re.search(r"太湖湖体.{0,2600}?(?=1\.2\s|2\s|三、|河流)", text, re.S)
    body = seg.group(0) if seg else text

    def status_after(pattern: str) -> str:
        m = re.search(pattern, body, re.S)
        if not m:
            return ""
        v = m.group(1).strip()
        v = re.sub(r"^(整体|全湖|水质|水体|为|：|,|，|。)+", "", v).strip()
        return v

    def first_status(prefix: str) -> str:
        m = re.search(re.escape(prefix) + r"([^。；]{0,30})", body, re.S)
        if not m:
            return ""
        v = m.group(1).strip()
        v = re.sub(r"^(为|：|,|，)+", "", v)
        return v.strip()

    pc = re.search(r"监测(\d+)个点位", body)
    out["monitoring_point_count"] = dict(value=pc.group(1) if pc else "", unit="count",
                                         note="监测点数" if pc else "未解析")
    whole = first_status("全湖整体")
    out["water_quality_category"] = dict(value=whole, unit="classification", note="全湖整体水质类别评述")
    zones = {}
    for prefix in ("东部沿岸区", "西部沿岸区", "北部沿岸区", "湖心区"):
        v = first_status(prefix)
        if v:
            zones[prefix] = v
    if zones:
        out["zone_status"] = dict(value="; ".join(f"{k}为{v}" for k, v in zones.items()) if False else None,
                                  unit="", note="")
        out["zone_status"]["value"] = "; ".join(f"{k}: {v}" for k, v in zones.items())
    m = re.search(r"总氮单独评价时?[：:]?全湖整体为([^。；]+)", body)
    out["tn_class"] = dict(value=m.group(1).strip() if m else "", unit="classification", note="总氮单独评价类别")
    m = re.search(r"营养状态评价表明?[：:]?全湖整体为([^。；]+)", body)
    out["trophic_state"] = dict(value=m.group(1).strip() if m else "", unit="classification",
                                note="全湖营养状态评价")
    # 分区营养状态
    tr_zones = {}
    for prefix in ("东部沿岸区", "西部沿岸区", "北部沿岸区", "湖心区"):
        m2 = re.search(re.escape(prefix) + r"为([^。；]+)", body)
        if m2:
            tr_zones[prefix] = m2.group(1).strip()
    if tr_zones:
        if m and False:
            pass
        out["trophic_state_zones"] = dict(value="; ".join(f"{k}: {v}" for k, v in tr_zones.items()),
                                          unit="", note="分区营养状态")
    return out


def clean_mee(records: list[dict]) -> pd.DataFrame:
    root = ROOT / "storage/silver/mee_taihu_monthly"
    txts = sorted(root.glob("taihu_*.txt"))
    n_ok = n_fail = 0
    for p in txts:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="gb18030")
        m = re.search(r"(\d{4})[_-](\d{2})", p.name)
        month_full = f"{m.group(1)}-{m.group(2)}" if m else ""
        d = parse_mee_text(text)
        if not d:
            n_fail += 1
            continue
        for field, info in d.items():
            if field in ("monitoring_point_count",):
                v = info["value"]
                val = to_number(v)
                unit = info["unit"]
            elif "zones" in field:
                val = float("nan")
                unit = info["unit"]
            else:
                val = float("nan")
                unit = "classification"
            if field == "zone_status" or field == "trophic_state_zones":
                unit = ""
            if info.get("value") is None or info["value"] == "":
                continue
            ts = pd.Timestamp(f"{month_full}-01")
            records.append(dict(
                station_id="TAIHU_WHOLE", station_name="太湖全湖(17点位)",
                observed_at=datetime_of(ts), date=date_of(ts), month=month_full,
                variable_code=f"category_{field}", value=val,
                value_text=str(info["value"]), unit=unit,
                quality_flag="Q00", quality_note=f"MEE月报评价: {info['note']}",
                source_name=SOURCE_NAME_MEE,
                source_file=str(p.relative_to(ROOT)), source_row="",
                source_unit=unit, conversion_rule="", value_origin="report_evaluation",
            ))
        n_ok += 1
    print(f"  [MEE] 解析 {n_ok} 个月报, 失败 {n_fail} (检查 text 结构)")
    return pd.DataFrame()


# ----------------------------- 水站批次 -----------------------------
def clean_water_station(records: list[dict]) -> pd.DataFrame:
    files = sorted(STORAGE.glob("staging/*/taihu_water_station_batch/*.csv"))
    used = 0
    for p in files:
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(p, encoding="gb18030")
        if "variable_code" not in df.columns:
            continue
        for _, row in df.iterrows():
            ts = coerce_datetime(row.get("observed_at"))
            val = to_number(row.get("observed_value", row.get("clean_value")))
            var = map_variable(row.get("variable_code", row.get("source_parameter", "")))
            if var in ("chla", "chlorophyll_a"):
                var = "chla"
            station = str(row.get("station_id", row.get("scene_id") or "UNKNOWN_STATION"))
            if pd.isna(val) and is_missing(row.get("observed_value", "")):
                continue
            flags = ["Q00"]
            if row.get("is_imputed") in (True, "True", "true"):
                flags.append("Q06")
            records.append(dict(
                station_id=station, station_name=str(row.get("station_name") or station),
                observed_at=datetime_of(ts), date=date_of(ts), month=month_of(ts),
                variable_code=var, value=val, value_text="" if not np.isnan(val) else str(row.get("observed_value")),
                unit=str(row.get("unit") or ""), quality_flag=flag_join(flags),
                quality_note="" if "Q06" not in flags else "插补值",
                source_name=SOURCE_NAME_STATION,
                source_file=str(p.relative_to(ROOT)), source_row=str(row.get("source_row", "")),
                source_unit=str(row.get("source_unit") or ""),
                conversion_rule=str(row.get("conversion_rule") or ""),
                value_origin=str(row.get("value_origin", "observed")),
            ))
            used += 1
    print(f"  [水站批次] {len(files)} 个文件, {used} 行")
    return pd.DataFrame()


def main() -> pd.DataFrame:
    print("== 水质清洗 ==")
    records: list[dict] = []
    clean_thqbca(records)
    clean_mee(records)
    clean_water_station(records)
    df = pd.DataFrame(records).reindex(columns=LONG_COLS)
    if df.empty:
        df = pd.DataFrame(columns=LONG_COLS)
    # 排序: 时间 → 站点 → 变量
    df["_dt"] = pd.to_datetime(df["observed_at"], errors="coerce")
    df = df.sort_values(["_dt", "station_id", "variable_code"]).drop(columns="_dt").reset_index(drop=True)
    # 完全重复去除（同 站/时/变量/值 完全一致）
    dups = int(df.duplicated(subset=["station_id", "observed_at", "variable_code", "value"], keep="first").sum())
    # 注意: value 为 float, value_text 为 str —— 双列保留原始与类别文本
    before = len(df)
    df = df.drop_duplicates(subset=["station_id", "observed_at", "variable_code", "value"], keep="first")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # 单位规范化 + NO2-N 源单位为 µg/L, 统一换算为 mg/L
    unit_map = {"mg/l": "mg/L", "ug/l": "µg/L", "μg/l": "µg/L", "µg/l": "µg/L"}
    df["unit"] = df["unit"].astype(str).str.replace(" ", "").replace(unit_map)
    m_no2 = df["variable_code"] == "no2_n"
    if m_no2.any():
        df.loc[m_no2 & (df["unit"] == "µg/L"), "value"] = pd.to_numeric(df.loc[m_no2 & (df["unit"] == "µg/L"), "value"], errors="coerce") / 1000.0
        df.loc[m_no2, "conversion_rule"] = "NO2-N: µg/L -> mg/L (÷1000)"
        df.loc[m_no2 & (df["unit"] == "µg/L"), "unit"] = "mg/L"
        df.loc[m_no2 & (df["unit"] == "µg/L"), "source_unit"] = "µg/L"
    path = write_dataset(df, "water_quality_cleaned")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列, 去重 {dups}/{before}")
    return df


if __name__ == "__main__":
    main()
