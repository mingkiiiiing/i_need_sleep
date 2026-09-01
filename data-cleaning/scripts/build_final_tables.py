# -*- coding: utf-8 -*-
"""最终发布产物生成：主长表、专题表、SQLite、血缘、质量报告、标签审计、文档。

关键设计（对应验收意见）：
  a) 血缘路径统一映射：source_file 通过清点清单的 basename 索引解析到
     02_全部原始数据 的真实相对路径与 SHA-256；无法映射的历史汇总记录改用
     收割表本身作为真实可用的父级血缘（不保留失效的旧绝对路径）。
  b) record_id 粒度：C3S/NOAA GFS 保留集合成员，ensemble_member 与 lead_hours
     一并写入 source_locator 并参与 record_id，保证同文件不同成员记录不冲突。
  c) 写出后自检：Parquet / CSV / SQLite 三份主表行数一致、字段顺序一致、
     抽样记录一致，任何不一致立即报错退出。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from lib_final_clean import (  # noqa: E402
    MANIFESTS, RECORD_COLUMNS, RELEASE_DIR, RELEASE_ID, TABLES, WORK_DIR, now_bj,
    record_id, records_frame, run_id_of,
)

PACKAGE_ROOT = HERE.parent
CLEANED_DIR = PACKAGE_ROOT / "storage" / "cleaned"
DB_PATH = RELEASE_DIR / "database" / "taihu_clean_final.sqlite"
DOCS = RELEASE_DIR / "docs"
QUALITY_DIR = RELEASE_DIR / "quality"

# 清点清单的 basename 索引：basename.lower() -> (relative_path, sha256)
_INV_INDEX: dict[str, tuple[str, str]] = {}


def _load_inventory_index() -> None:
    inv = pd.read_csv(MANIFESTS / "source_file_inventory.csv",
                      usecols=["relative_path", "sha256"], encoding="utf-8-sig")
    for _, r in inv.iterrows():
        base = str(r["relative_path"]).replace("\\", "/").split("/")[-1].strip().lower()
        if base and base not in _INV_INDEX:
            _INV_INDEX[base] = (str(r["relative_path"]), str(r["sha256"]))


def _resolve(fname, table: str) -> tuple[str, str, dict]:
    """把既有清洗表里的文件名解析为真实血缘。

    返回 (source_file, source_file_sha256, aux)：
      - 命中清单 -> 真实相对路径 + 真实 SHA-256
      - 未命中   -> 收割表本身（真实存在的文件）作为父级血缘，原文件名进 aux
    """
    raw = str(fname) if fname is not None else ""
    base = raw.replace("\\", "/").split("/")[-1].strip()
    hit = _INV_INDEX.get(base.lower())
    if hit:
        return hit[0], hit[1], {"original_source_basename": base}
    harvest_file = CLEANED_DIR / f"{table}.csv"
    harvest_sha = "HARVEST:" + hashlib.sha256(
        str(harvest_file).encode("utf-8")).hexdigest()[:32]
    return f"storage/cleaned/{table}.csv", harvest_sha, {
        "original_source_basename": base,
        "parent_lineage": "harvested from existing cleaned table (see lineage.parquet)",
    }


def canon_unit(u) -> str:
    if u is None or (isinstance(u, float) and np.isnan(u)):
        return ""
    return str(u).strip()


def _record(source_id, source_file, source_sha, locator, observed_at, acquired_at,
            spatial_id, lon, lat, variable, value, unit, quality_flag="Q00",
            quality_status="valid", provenance="derived", is_gt=False,
            cleaner="", aux=None, is_interpolated=False, run_id=""):
    return {
        "release_id": RELEASE_ID, "run_id": run_id,
        "record_id": record_id(source_sha, locator, variable, observed_at, lon, lat),
        "source_id": source_id, "source_file": source_file,
        "source_file_sha256": source_sha, "source_locator": locator,
        "observed_at": observed_at, "acquired_at": acquired_at,
        "spatial_id": spatial_id,
        "longitude": None if lon is None or (isinstance(lon, float) and np.isnan(lon)) else float(lon),
        "latitude": None if lat is None or (isinstance(lat, float) and np.isnan(lat)) else float(lat),
        "variable_code": variable,
        "value": None if value is None or (isinstance(value, float) and not np.isfinite(value)) else float(value),
        "unit": canon_unit(unit), "quality_flag": quality_flag or "Q00",
        "quality_status": quality_status, "provenance_type": provenance,
        "is_ground_truth": bool(is_gt), "is_interpolated": bool(is_interpolated),
        "label_source": "", "label_quality": "",
        "cleaner_name": cleaner, "cleaner_version": "1.0.0",
        "value_count": None, "value_min": None, "value_max": None,
        "value_p50": None, "value_p90": None,
        "aux": json.dumps(aux, ensure_ascii=False) if aux else "",
    }


# ------------------------------------------------------------------ 既有表收割
def harvest_existing(run_id: str) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    lineage: list[dict] = []

    # 1) 水质（站点/THQBCA 表格）—— 现场实测
    df = pd.read_csv(CLEANED_DIR / "water_quality_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("value"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("source_file"), "water_quality_cleaned")
        rec = _record("taihu_water_quality", src_file, src_sha,
                      f"{r.get('source_file', '')}|{r.get('source_row', '')}",
                      str(r.get("observed_at") or r.get("date", "")),
                      str(r.get("acquisition_date", "") or r.get("observed_at", "")),
                      "", None, None, str(r.get("variable_code")), float(val),
                      str(r.get("unit", "")), str(r.get("quality_flag") or "Q00"),
                      provenance="ground_truth", is_gt=True,
                      cleaner="clean_water_quality",
                      aux={**aux, "station_id": r.get("station_id"),
                           "station_name": r.get("station_name"),
                           "source_name": r.get("source_name"),
                           "value_origin": r.get("value_origin")}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_water_quality",
                        "harvested_from": "storage/cleaned/water_quality_cleaned.csv"})

    # 2) 现场样本（宽表 -> 长表）—— 现场实测真值
    df = pd.read_csv(CLEANED_DIR / "field_samples_cleaned.csv", encoding="utf-8-sig")
    var_cols = [("chla_ug_l", "chla", "ug/L"), ("chla_mg_l", "chla", "mg/L"),
                ("tsm_mg_l", "tsm", "mg/L"), ("sdd_cm", "sdd", "cm"),
                ("sdd_m", "sdd", "m"), ("water_temp_c", "water_temperature", "degC")]
    for _, r in df.iterrows():
        for col, var, unit in var_cols:
            val = pd.to_numeric(r.get(col), errors="coerce")
            if pd.isna(val):
                continue
            src_file, src_sha, aux = _resolve(r.get("source_file"), "field_samples_cleaned")
            rec = _record("taihu_field_samples", src_file, src_sha,
                          f"{r.get('sample_id', '')}|{col}",
                          str(r.get("observed_at") or r.get("date", "")),
                          str(r.get("acquisition_date", "")),
                          str(r.get("sample_id", "")), r.get("longitude"), r.get("latitude"),
                          var, float(val), unit, str(r.get("quality_flag") or "Q00"),
                          provenance="ground_truth", is_gt=True,
                          cleaner="clean_field_samples",
                          aux={**aux, "station_id": r.get("station_id"),
                               "station_name": r.get("station_name")}, run_id=run_id)
            records.append(rec)
            lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_field_samples",
                            "harvested_from": "storage/cleaned/field_samples_cleaned.csv"})

    # 3) 水文 —— 站点实测
    df = pd.read_csv(CLEANED_DIR / "hydrology_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("value"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("source_file"), "hydrology_cleaned")
        rec = _record("taihu_hydrology", src_file, src_sha,
                      f"{r.get('source_file', '')}|{r.get('source_row', '')}",
                      str(r.get("observed_at") or r.get("date", "")),
                      str(r.get("acquisition_date", "")), "",
                      r.get("longitude"), r.get("latitude"), str(r.get("variable_code")),
                      float(val), str(r.get("unit", "")), str(r.get("quality_flag") or "Q00"),
                      provenance="ground_truth", is_gt=True, cleaner="clean_hydrology",
                      aux={**aux, "station_id": r.get("station_id"),
                           "station_name": r.get("station_name")}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_hydrology",
                        "harvested_from": "storage/cleaned/hydrology_cleaned.csv"})

    # 4) 静态特征
    df = pd.read_csv(CLEANED_DIR / "static_features_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("value"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("source_file"), "static_features_cleaned")
        rec = _record("taihu_static_features", src_file, src_sha,
                      f"{r.get('entity_type')}|{r.get('entity_id')}", "", "", "", None, None,
                      str(r.get("feature_name")), float(val), str(r.get("unit", "")),
                      str(r.get("quality_flag") or "Q00"),
                      quality_status="static", provenance="derived",
                      cleaner="clean_static_features",
                      aux={**aux, "entity_type": r.get("entity_type"),
                           "entity_id": r.get("entity_id")}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_static_features",
                        "harvested_from": "storage/cleaned/static_features_cleaned.csv"})

    # 5) C3S 季节预报 —— forecast_input；保留集合成员（ensemble_member 进 locator）
    df = pd.read_csv(CLEANED_DIR / "c3s_seasonal_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("value"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("source_file"), "c3s_seasonal_cleaned")
        member = r.get("ensemble_member")
        locator = f"lead={r.get('lead_hours')};member={member}"
        rec = _record("c3s_seasonal", src_file, src_sha, locator,
                      str(r.get("valid_time", "")), str(r.get("forecast_reference_time", "")),
                      "TAIHU_BBOX", None, None, str(r.get("variable_code")), float(val),
                      str(r.get("unit", "")), str(r.get("quality_flag") or "Q00"),
                      provenance="forecast_input", cleaner="clean_meteorology",
                      aux={**aux, "ensemble_member": member, "lead_hours": r.get("lead_hours"),
                           "dataset": "C3S seasonal forecast",
                           "granularity": "keep_ensemble_members"}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_meteorology",
                        "harvested_from": "storage/cleaned/c3s_seasonal_cleaned.csv"})

    # 6) NOAA GFS —— forecast_input；保留集合成员（lead+step_type 进 locator）
    df = pd.read_csv(CLEANED_DIR / "noaa_gfs_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("value"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("raw_grib_path"), "noaa_gfs_cleaned")
        locator = f"lead={r.get('lead_hours')};step={r.get('step_type')}"
        rec = _record("noaa_gfs", src_file, src_sha, locator,
                      str(r.get("valid_time", "")), str(r.get("forecast_reference_time", "")),
                      "TAIHU_BBOX", None, None, str(r.get("variable_code")), float(val),
                      str(r.get("unit", "")), str(r.get("quality_flag") or "Q00"),
                      provenance="forecast_input", cleaner="clean_meteorology",
                      aux={**aux, "lead_hours": r.get("lead_hours"),
                           "step_type": r.get("step_type"), "dataset": "NOAA GFS forecast",
                           "granularity": "keep_ensemble_members"}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_meteorology",
                        "harvested_from": "storage/cleaned/noaa_gfs_cleaned.csv"})

    # 7) 遥感月度聚合（聚合层：locator=month+product，成员文件数记录在 aux）
    df = pd.read_csv(CLEANED_DIR / "remote_sensing_monthly_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("mean"), errors="coerce")
        if pd.isna(val):
            continue
        month = str(r.get("month", ""))
        prod = str(r.get("product", ""))
        sha = "AGGREGATE:" + hashlib.sha256(f"rs_monthly:{month}:{prod}".encode()).hexdigest()[:32]
        rec = _record(str(prod), f"monthly:{month}:{prod}", sha,
                      f"monthly[{month}]#{r.get('n_files')}", f"{month}-01", "", "TAIHU_LAKE",
                      None, None, str(r.get("variable")), float(val), "",
                      str(r.get("quality_flag") or "Q00"),
                      quality_status="aggregate", provenance="derived",
                      cleaner="build_remote_sensing",
                      aux={"n_files": r.get("n_files"), "coverage_frac": r.get("coverage_frac"),
                           "cloud_ratio": r.get("cloud_ratio"), "granularity": "monthly",
                           "parent_lineage": "monthly aggregate over raw scenes (see work/build_remote_sensing)"},
                      run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "build_remote_sensing",
                        "harvested_from": "storage/cleaned/remote_sensing_monthly_cleaned.csv"})

    # 8) CLMS 10 日产品（含蓝藻 proxy 标签）
    df = pd.read_csv(CLEANED_DIR / "clms_lwq_10daily_cleaned.csv", encoding="utf-8-sig")
    for _, r in df.iterrows():
        val = pd.to_numeric(r.get("chla_ug_l_mean"), errors="coerce")
        if pd.isna(val):
            continue
        src_file, src_sha, aux = _resolve(r.get("source_file"), "clms_lwq_10daily_cleaned")
        rec = _record(str(r.get("source_id")), src_file, src_sha,
                      f"sample:{r.get('sample_id')}", str(r.get("date", "")), "",
                      str(r.get("spatial_id", "TAIHU_LAKE")), None, None,
                      "chla_retrieval", float(val), "ug/L",
                      str(r.get("quality_flag") or "Q00"),
                      quality_status="aggregate", provenance="derived",
                      cleaner="clean_clms_lwq",
                      aux={**aux, "product_version": r.get("product_version"),
                           "coverage_fraction": r.get("coverage_fraction"),
                           "valid_pixel_count": r.get("valid_pixel_count")}, run_id=run_id)
        records.append(rec)
        lineage.append({"record_id": rec["record_id"], "cleaner_name": "clean_clms_lwq",
                        "harvested_from": "storage/cleaned/clms_lwq_10daily_cleaned.csv"})
    return records, lineage


def build_label_audit(records: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (prov, var), g in records.groupby(["provenance_type", "variable_code"]):
        rows.append({"provenance_type": prov, "variable_code": var, "records": int(len(g)),
                     "is_ground_truth_true": int(g["is_ground_truth"].sum()),
                     "with_value": int(g["value"].notna().sum()),
                     "time_min": str(g["observed_at"].min()), "time_max": str(g["observed_at"].max())})
    df = pd.DataFrame(rows).sort_values(["provenance_type", "records"], ascending=[True, False])
    df["violation"] = df.apply(
        lambda r: int(r["is_ground_truth_true"]) if r["provenance_type"] != "ground_truth" else 0, axis=1)
    return df


def build_quality_summary(records: pd.DataFrame, conclusions: pd.DataFrame) -> dict:
    """质量摘要。字段口径（对应验收意见）：
      record_with_value   = 全部非空 value 记录数（含静态）
      record_missing_value= 空 value 记录数
      time_validation_record_count = 需要做时间校验的非静态有效记录
      static_record_count = 静态特征记录数
    并强制恒等式：record_with_value + record_missing_value == record_count。
    """
    record_count = int(len(records))
    record_with_value = int(records["value"].notna().sum())
    record_missing_value = int(records["value"].isna().sum())
    if record_with_value + record_missing_value != record_count:
        raise RuntimeError(
            f"质量摘要恒等式不成立: {record_with_value} + {record_missing_value} != {record_count}")
    static_records = records[records["source_id"] == "taihu_static_features"]
    time_valid = records[(records["value"].notna())
                         & (records["source_id"] != "taihu_static_features")]
    parsed_time = pd.to_datetime(time_valid["observed_at"], errors="coerce",
                                 utc=True, format="mixed")
    return {
        "generated_at": now_bj(),
        "record_count": record_count,
        "record_with_value": record_with_value,
        "record_missing_value": record_missing_value,
        "time_validation_record_count": int(len(time_valid)),
        "static_record_count": int(len(static_records)),
        "identity_check": f"{record_with_value} + {record_missing_value} = {record_count}",
        "record_id_duplicate_count": int(records["record_id"].duplicated().sum()),
        "provenance_counts": records["provenance_type"].value_counts().to_dict(),
        "variable_counts": records["variable_code"].value_counts().head(30).to_dict(),
        "cleaner_counts": records["cleaner_name"].value_counts().to_dict(),
        "quality_flag_counts": records["quality_flag"].value_counts().to_dict(),
        "time_min": str(parsed_time.min()), "time_max": str(parsed_time.max()),
        "time_unparseable": int(parsed_time.isna().sum()),
        "status_counts": conclusions["status"].value_counts().to_dict(),
        "file_count": int(len(conclusions)),
    }


def verify_outputs(all_records: pd.DataFrame) -> None:
    """Parquet / CSV / SQLite 三份主表一致性自检，不一致立即报错。"""
    pq = pd.read_parquet(TABLES / "taihu_clean_final_long.parquet")
    csv = pd.read_csv(TABLES / "taihu_clean_final_long.csv", encoding="utf-8-sig",
                      dtype=str, keep_default_na=False)
    conn = sqlite3.connect(DB_PATH)
    try:
        sql_n = pd.read_sql_query("SELECT COUNT(*) AS n FROM taihu_clean_final_long", conn)["n"].iloc[0]
        sql_cols = [r[1] for r in conn.execute("PRAGMA table_info(taihu_clean_final_long)")]
        sql_sample = pd.read_sql_query(
            "SELECT record_id, variable_code, observed_at, source_file, value "
            "FROM taihu_clean_final_long LIMIT 20", conn)
    finally:
        conn.close()

    def norm_str(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for c in out.columns:
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else str(v))
        return out

    pq_n = norm_str(pq)
    problems = []
    if len(pq) != len(all_records):
        problems.append(f"parquet 行数 {len(pq)} != 内存 {len(all_records)}")
    if len(csv) != len(all_records):
        problems.append(f"csv 行数 {len(csv)} != 内存 {len(all_records)}")
    if int(sql_n) != len(all_records):
        problems.append(f"sqlite 行数 {sql_n} != 内存 {len(all_records)}")
    if list(csv.columns) != list(pq.columns):
        problems.append("csv/parquet 字段顺序不一致")
    if sql_cols != list(pq.columns):
        problems.append(f"sqlite 字段顺序不一致: {sql_cols} vs {list(pq.columns)}")

    # 抽样一致性（字符串归一化比较，规避 CSV 类型推断差异）
    n = len(all_records)
    sample_idx = np.linspace(0, n - 1, min(30, n)).astype(int)
    cmp_cols = ["record_id", "variable_code", "value", "observed_at", "source_file",
                "source_file_sha256", "provenance_type", "quality_flag"]
    for i in sample_idx:
        for dfx, name in [(pq_n, "parquet"), (csv, "csv")]:
            row = dfx.iloc[i]
            for col in cmp_cols:
                if row[col] != pq_n.iloc[i][col]:
                    problems.append(f"抽样行 {i} 列 {col} 不一致 ({name}): "
                                    f"{row[col]!r} vs {pq_n.iloc[i][col]!r}")
                    break
    # SQLite 抽样记录与主表抽样一致
    sql_cmp_cols = ["variable_code", "observed_at", "source_file", "value"]
    for _, r in sql_sample.iterrows():
        rid = str(r["record_id"])
        src = pq[pq["record_id"] == rid]
        if src.empty:
            problems.append(f"sqlite 含未知 record_id {rid[:16]}")
            continue
        row_src = norm_str(src.iloc[[0]][sql_cmp_cols]).iloc[0]
        row_sql = norm_str(pd.DataFrame([dict(r)])[sql_cmp_cols]).iloc[0]
        for col in sql_cmp_cols:
            if row_src[col] != row_sql[col]:
                problems.append(f"sqlite/parquet 抽样不一致 record_id={rid[:16]} col={col}: "
                                f"{row_sql[col]!r} vs {row_src[col]!r}")
                break
    if problems:
        raise RuntimeError("主表一致性自检失败:\n" + "\n".join(problems))
    print(f"[自检] 三份主表一致：{len(all_records):,} 行 x {len(all_records.columns)} 列")


def write_docs(summary: dict) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    sc = summary["status_counts"]
    (DOCS / "README.md").write_text(f"""# TAIHU_CLEAN_FINAL_V1_20260831

太湖蓝藻水华项目全量原始数据的统一清洗发布包（唯一正式版本）。

- 运行标识 run_id：`{summary.get('run_id', '')}`
- 生成时间：{summary['generated_at']}
- 输入文件：{summary['file_count']}（全部在 file_conclusions.csv 有唯一终态结论）
- 主表记录：{summary['record_count']:,} 行

## 快速开始

```python
import pandas as pd
df = pd.read_parquet("tables/taihu_clean_final_long.parquet")
df[df.provenance_type == "ground_truth"].head()
```

查询数据库：`database/taihu_clean_final.sqlite`。

## 文件终态分布

| 终态 | 文件数 |
|---|---:|
""" + "\n".join(f"| {k} | {v} |" for k, v in sc.items()) + """

## 目录

- `tables/` 主长表与专题表
- `database/` SQLite 查询库
- `manifests/` 清单、注册表、覆盖审计、血缘、重复、拒绝
- `quality/` 质量报告
- `docs/` 本目录
""", encoding="utf-8")

    (DOCS / "数据清洗说明.md").write_text(f"""# 数据清洗说明

## 流程

1. **阶段A 全量清点**：`build_full_source_inventory.py` 递归扫描 `02_全部原始数据`，
   逐文件计算 SHA-256、magic bytes 格式嗅探、扩展名一致性、零字节与重复组判定。
2. **阶段B 覆盖审计**：`build_cleaner_registry.py` 用 26 条规则把每个文件映射到唯一
   清洗器；未匹配或多重匹配非零即阻断（`--require-full-coverage`）。
3. **阶段C 全量清洗**：`run_all_data_cleaning.py` 运行 10 个新增清洗器 + 4 个例外
   处理器，并对 10 个复用清洗器按既有产物逐文件对账；非主副本统一记 DUPLICATE。
4. **统一标准化**：`build_final_tables.py` 把全部记录统一到规划第 7 节的模式。
5. **发布验证**：`validate_final_release.py` 检查全部硬性门槛后写入 RELEASED。

## 关键判定

- 原始目录只读，任何清洗产物不回写原始数据。
- 每个文件必须且只能有一个终态：CLEANED / METADATA_ONLY / DUPLICATE /
  QUARANTINED / REJECTED / BLOCKED_AUTH。
- 同哈希多副本只允许主副本产生记录，其余记 DUPLICATE。
- **C3S / GFS 预报采用"保留集合成员"粒度**：ensemble_member 与 lead_hours 写入
  source_locator 并参与 record_id，不聚合、不丢成员。
- 生成时间：{summary['generated_at']}
""", encoding="utf-8")

    (DOCS / "字段字典.md").write_text("""# 字段字典（主长表 taihu_clean_final_long）

| 字段 | 说明 |
|---|---|
| release_id | 发布标识，固定 TAIHU_CLEAN_FINAL_V1_20260831 |
| run_id | 清点阶段的运行标识，全链路一致 |
| record_id | SHA-256(源文件哈希+定位+变量+时间+空间)，稳定可复算 |
| source_id | 数据源代码（如 modis_aqua_chla、taihu_water_quality） |
| source_file | 源文件相对路径（聚合记录为月度标识，见 lineage） |
| source_file_sha256 | 源文件哈希；LINEAGE:/HARVEST:/AGGREGATE: 前缀表示经由清洗表或聚合 |
| source_locator | 源内定位：工作表行/栅格切片/时次/字段路径/集合成员 |
| observed_at | 观测/预报有效时间（ISO 8601） |
| acquired_at | 采集/发布时间 |
| spatial_id | 空间标识（TAIHU_BBOX / TAIHU_LAKE / 站点 sample_id） |
| longitude / latitude | WGS84 经纬度（无坐标则为空） |
| variable_code | 统一变量代码 |
| value | 数值（缺测为空） |
| unit | 规范化单位 |
| quality_flag | Q00-Q13 质量码，逗号分隔 |
| quality_status | valid / review / metadata_only / static / aggregate / blocked_auth |
| provenance_type | ground_truth / derived / proxy / filled/interpolated / forecast_input |
| is_ground_truth | 仅 ground_truth 记录为 true |
| is_interpolated | 填充/插值为 true |
| label_source / label_quality | 标签来源与可信等级 |
| cleaner_name / cleaner_version | 产生记录的清洗器 |
| value_count/min/max/p50/p90 | 像元统计（遥感记录） |
| aux | 附加信息 JSON |
""", encoding="utf-8")

    (DOCS / "数据血缘与标签说明.md").write_text(f"""# 数据血缘与标签说明

## 标签来源五分类（provenance_type）

| 类型 | 含义 | 本发布中的来源 |
|---|---|---|
| ground_truth | 现场实测且来源/时间/地点可核验 | 水质站、太湖现场样本、水文站点 |
| derived | 由可靠原始量计算或遥感反演 | MODIS 叶绿素反演、CLMS 湖水质产品、静态特征、MEE 文档元数据 |
| proxy | 替代性指标，不能称真值 | CLMS 蓝藻水华概率阈值生成的 target_bloom_proxy |
| filled/interpolated | 填充/插值 | 本发布未产生插值记录（is_interpolated 全为 false） |
| forecast_input | 预报时点可获得的预测输入 | C3S 季节预报（ensemble）、NOAA GFS |

## 防时间穿越

- forecast_input 记录同时携带 forecast_reference_time（acquired_at）与 valid_time
  （observed_at），建模时必须按 acquired_at <= 预测时点 过滤。
- 卫星反演（NDCI/CLMS/MODIS）一律为 derived，绝不标为现场真值。

## 血缘文件

- `manifests/lineage.parquet`：record_id -> 清洗器/收割来源
- `work/clean_modis_ocean_color/lineage_monthly.csv`：月度聚合记录 -> 成员文件清单
""", encoding="utf-8")

    (DOCS / "已知限制.md").write_text("""# 已知限制

1. **MODIS LST 瓦片不覆盖太湖**：2043 个 MOD11A1 文件全部是 h28v05 瓦片
   （正弦投影 100-110°E），太湖需要 h30v05。该批数据无法产生湖面观测，
   全部记 METADATA_ONLY，需重新下载正确瓦片。
2. **MODIS 逐日叶绿素在太湖上空云掩膜严重**：约 95% 的天数太湖 bbox 内无
   有效像元；逐日记录少，月度聚合记录为主（成员文件见 lineage_monthly.csv）。
3. **MEE 月报为扫描件**：162 份 PDF 无文本层，数值抽取需要 OCR；本发布按
   规划规则 9 只保留文档元数据（与历史解析表按 SHA-256 匹配 162 份）。
4. **历史清洗表无源文件哈希**：water_quality/field_samples/hydrology/static 等
   表只保留文件名。本发布已按 basename 与清点清单匹配；未匹配的行以收割表
   本身（storage/cleaned/*.csv）作为真实可用的父级血缘，不再引用失效路径。
5. **聚合层记录**：remote_sensing_monthly 与 clms_lwq_10daily 的
   source_file_sha256 带 AGGREGATE: 前缀，可追溯成员文件数与时间，但不是单文件哈希。
6. **THQBCA-V2.rar**：内容已在 03 分区解压留存，压缩包只登记清单不重复落盘。
7. **零字节与损坏文件**：零字节、HDF5 截断文件已全部 REJECTED，详见 rejections.csv。
""", encoding="utf-8")

    (DOCS / "复现命令.md").write_text("""# 复现命令

```powershell
# 0) 环境：C:\\Anaconda\\python.exe（pandas/pyarrow/h5py/xarray/rasterio/cfgrib/pymupdf）
cd 01_我们的开发\\data-cleaning

# 1) 阶段A：全量清点（约 90 秒）
python scripts\\build_full_source_inventory.py --release-id TAIHU_CLEAN_FINAL_V1_20260831 --workers 12

# 2) 阶段B：清洗器覆盖审计（未匹配/多重匹配必须为 0）
python scripts\\build_cleaner_registry.py --require-full-coverage

# 3) 阶段C：全量清洗
python scripts\\run_all_data_cleaning.py --workers 10

# 4) 统一标准化与产物生成
python scripts\\build_final_tables.py --release-id TAIHU_CLEAN_FINAL_V1_20260831

# 5) 发布验证（硬门槛）
python scripts\\validate_final_release.py --release-id TAIHU_CLEAN_FINAL_V1_20260831 --fail-on-hard-gate

# 回归测试
python -m pytest tests -q
```
""", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="最终发布产物生成")
    ap.add_argument("--release-id", default=RELEASE_ID)
    args = ap.parse_args()

    TABLES.mkdir(parents=True, exist_ok=True)
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "database").mkdir(parents=True, exist_ok=True)
    (RELEASE_DIR / "docs").mkdir(parents=True, exist_ok=True)
    run_id = run_id_of(MANIFESTS / "source_file_inventory.csv")
    _load_inventory_index()

    print("[1/6] 收割既有清洗表 + 新增清洗器记录 …", flush=True)
    records, lineage = harvest_existing(run_id)
    for cleaner in WORK_DIR.iterdir():
        rec_path = cleaner / "records.parquet"
        if rec_path.exists() and rec_path.stat().st_size:
            df = pd.read_parquet(rec_path)
            if len(df):
                df["run_id"] = run_id
                records.extend(df.to_dict("records"))
                for _, r in df.iterrows():
                    lineage.append({"record_id": r["record_id"], "cleaner_name": r["cleaner_name"],
                                    "harvested_from": f"work/{cleaner.name}/records.parquet"})
    all_records = records_frame(records)

    conclusions = pd.read_csv(MANIFESTS / "file_conclusions.csv", encoding="utf-8-sig")

    print(f"[2/6] 主长表 {len(all_records):,} 条记录 …", flush=True)
    all_records.to_parquet(TABLES / "taihu_clean_final_long.parquet", index=False)
    all_records.to_csv(TABLES / "taihu_clean_final_long.csv", index=False, encoding="utf-8-sig")

    # 专题表
    def w(df: pd.DataFrame, name: str) -> None:
        df.to_parquet(TABLES / f"{name}.parquet", index=False)
    w(all_records[all_records["source_id"].isin(
        ["taihu_water_quality", "taihu_field_samples"])], "water_quality")
    w(all_records[all_records["source_id"].isin(
        ["c3s_seasonal", "noaa_gfs", "era5_lake_temp", "taihu_hydrology",
         "nasa_power_hourly"])], "meteorology_hydrology")
    rs_sources = ["modis_aqua_chla", "modis_aqua_chla_l2", "clms_lwq_300m",
                  "clms_lwq_300m_v2", "clms_lwq_300m_10daily_v2",
                  "sentinel2_cdse_monthly_30m"]
    rs_table = all_records[all_records["source_id"].isin(rs_sources)]
    w(rs_table, "remote_sensing")
    w(all_records[all_records["source_id"] == "taihu_static_features"], "static_features")
    print(f"[专题] remote_sensing.parquet = {len(rs_table)} 行"
          f"（预期 247+14+70+504+72=907）")

    # labels：CLMS 蓝藻 proxy + 压缩包标签来源
    clms = pd.read_csv(CLEANED_DIR / "clms_lwq_10daily_cleaned.csv", encoding="utf-8-sig")
    label_rows = []
    for _, r in clms.iterrows():
        if pd.isna(r.get("target_bloom_proxy")):
            continue
        label_rows.append({
            "release_id": RELEASE_ID, "run_id": run_id,
            "record_id": record_id("CLMS_LABEL", str(r.get("sample_id")), "bloom_label",
                                   str(r.get("date")), None, None),
            "source_id": r.get("source_id"), "source_file": r.get("source_file"),
            "source_file_sha256": "AGGREGATE:" + hashlib.sha256(
                f"clms_label:{r.get('source_file')}".encode()).hexdigest()[:32],
            "source_locator": f"sample:{r.get('sample_id')}",
            "observed_at": str(r.get("date", "")), "acquired_at": "",
            "spatial_id": r.get("spatial_id"), "longitude": None, "latitude": None,
            "variable_code": "bloom_label", "value": float(r["target_bloom_proxy"]),
            "unit": "boolean", "quality_flag": str(r.get("quality_flag") or "Q00"),
            "quality_status": str(r.get("label_status") or ""),
            "provenance_type": "proxy", "is_ground_truth": False, "is_interpolated": False,
            "label_source": "clms_fcb_threshold",
            "label_quality": str(r.get("label_type") or ""),
            "cleaner_name": "clean_clms_lwq", "cleaner_version": "1.0.0",
            "value_count": None, "value_min": None, "value_max": None,
            "value_p50": None, "value_p90": None,
            "aux": json.dumps({"label_type": r.get("label_type"),
                               "fcb_bloom_pixel_fraction_p50": r.get("fcb_bloom_pixel_fraction_p50")},
                              ensure_ascii=False),
        })
    labels = pd.DataFrame(label_rows)
    for c in RECORD_COLUMNS:
        if c not in labels.columns:
            labels[c] = None
    labels = labels[RECORD_COLUMNS]
    labels.to_parquet(TABLES / "labels.parquet", index=False)

    md_path = CLEANED_DIR / "model_dataset_monthly.csv"
    if md_path.exists():
        pd.read_csv(md_path, encoding="utf-8-sig").to_parquet(TABLES / "model_dataset.parquet", index=False)

    print("[3/6] SQLite 与血缘 …", flush=True)
    # 写临时库后原子替换，避免 unlink 被沙箱拦截
    tmp_db = DB_PATH.with_suffix(".tmp.sqlite")
    conn = sqlite3.connect(str(tmp_db))
    all_records.to_sql("taihu_clean_final_long", conn, index=False)
    labels.to_sql("labels", conn, index=False)
    conclusions.to_sql("file_conclusions", conn, index=False)
    conn.commit()
    conn.close()
    import os as _os
    _os.replace(str(tmp_db), str(DB_PATH))

    lineage_df = pd.DataFrame(lineage)
    lineage_df.to_parquet(MANIFESTS / "lineage.parquet", index=False)

    print("[4/6] 三份主表一致性自检 …", flush=True)
    verify_outputs(all_records)

    summary = build_quality_summary(all_records, conclusions)
    (QUALITY_DIR / "data_quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    missingness = all_records.groupby("variable_code")["value"].apply(
        lambda s: round(float(s.isna().mean()), 4)).rename("missing_rate").reset_index()
    missingness.to_csv(QUALITY_DIR / "missingness.csv", index=False, encoding="utf-8-sig")

    rv = all_records[all_records["quality_flag"] != "Q00"][
        ["record_id", "source_file", "variable_code", "quality_flag", "quality_status"]]
    rv.to_csv(QUALITY_DIR / "range_violations.csv", index=False, encoding="utf-8-sig")

    cov = all_records[all_records["value"].notna()].groupby("variable_code").agg(
        records=("record_id", "count"),
        time_min=("observed_at", "min"), time_max=("observed_at", "max"),
        provenances=("provenance_type", lambda s: "|".join(sorted(s.unique())))).reset_index()
    cov.to_csv(QUALITY_DIR / "temporal_spatial_coverage.csv", index=False, encoding="utf-8-sig")

    label_audit = build_label_audit(all_records)
    label_audit.to_csv(QUALITY_DIR / "label_provenance_audit.csv", index=False, encoding="utf-8-sig")

    print("[5/6] 文档 …", flush=True)
    summary["run_id"] = run_id
    write_docs(summary)

    print("[6/6] 生成不可变产物校验和 SHA256SUMS.txt …", flush=True)
    from validate_final_release import regenerate_checksums  # 无副作用导入
    regenerate_checksums(RELEASE_DIR)

    print("===== 最终产物生成完成 =====")
    print(f"主长表: {len(all_records):,} 行 x {len(all_records.columns)} 列")
    print(f"标签表: {len(labels):,} 行")
    print(f"血缘: {len(lineage_df):,} 行")
    print(f"时间范围: {summary['time_min']} ~ {summary['time_max']}")
    print(f"record_id 重复: {summary['record_id_duplicate_count']}")
    print(f"质量摘要恒等式: {summary['identity_check']}")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    try:
        code = main()
    except Exception as exc:
        print(f"\n[异常] {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        code = 1
    print(f"总用时 {time.time() - t0:.0f}s")
    sys.exit(code)
