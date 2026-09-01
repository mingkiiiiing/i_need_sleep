# -*- coding: utf-8 -*-
"""最终发布版清洗框架：统一记录模式、血缘、结论登记。

所有 TAIHU_CLEAN_FINAL_V1_20260831 清洗器共用此模块，保证：
  - 记录字段与规划第 7 节一致；
  - record_id 稳定（基于源文件哈希 + 定位 + 变量 + 时间 + 空间）；
  - provenance_type 只允许 5 种合法值；
  - 文件级结论只能是 6 种终态之一。
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent                                   # data-cleaning/
PROJECT_ROOT = HERE.parents[2]                               # 项目完整汇总_2026-08-31/
RAW_ROOT = PROJECT_ROOT / "02_全部原始数据"

RELEASE_ID = "TAIHU_CLEAN_FINAL_V1_20260831"
RELEASE_DIR = PACKAGE_ROOT / "storage" / "final_cleaned" / RELEASE_ID
MANIFESTS = RELEASE_DIR / "manifests"
WORK_DIR = RELEASE_DIR / "work"
TABLES = RELEASE_DIR / "tables"

BEIJING = timezone(timedelta(hours=8))
CLEANER_VERSION = "1.0.0"

# 文件级终态
FILE_STATUSES = ("CLEANED", "METADATA_ONLY", "DUPLICATE", "QUARANTINED", "REJECTED", "BLOCKED_AUTH")

# 标签来源类型（规划第 5 阶段）
PROVENANCE_TYPES = ("ground_truth", "derived", "proxy", "filled/interpolated", "forecast_input")

# 主长表字段（规划第 7 节 + 统计辅助列）
RECORD_COLUMNS = [
    "release_id", "run_id", "record_id", "source_id", "source_file", "source_file_sha256",
    "source_locator", "observed_at", "acquired_at", "spatial_id", "longitude", "latitude",
    "variable_code", "value", "unit", "quality_flag", "quality_status",
    "provenance_type", "is_ground_truth", "is_interpolated",
    "label_source", "label_quality", "cleaner_name", "cleaner_version",
    "value_count", "value_min", "value_max", "value_p50", "value_p90", "aux",
]

# 清洗器登记表：name -> version
NEW_CLEANERS = [
    "clean_modis_ocean_color", "clean_modis_land_surface", "clean_mee_monthly_pdf",
    "review_quarantined_assets", "clean_catalog_responses", "clean_bloom_archive",
    "inspect_data_archive", "clean_zip_wrapped_netcdf", "clean_sentinel3_status",
    "classify_and_deduplicate_legacy",
    "exception_zero_byte", "exception_lockfile", "exception_unreadable", "exception_temporary",
]

TAIHU_BBOX = dict(lon_min=119.5, lon_max=121.0, lat_min=30.5, lat_max=31.7)


def now_bj() -> str:
    return datetime.now(BEIJING).isoformat(timespec="seconds")


def run_id_of(inventory_csv: Path) -> str:
    """沿用清点阶段产生的 run_id，保持全链路一致。"""
    df = pd.read_csv(inventory_csv, usecols=["run_id"], nrows=1)
    return str(df["run_id"].iloc[0])


def record_id(source_sha: str, locator: str, variable: str, observed_at: str, lon, lat) -> str:
    h = hashlib.sha256()
    for part in (source_sha, locator, variable, str(observed_at),
                 "" if lon is None else f"{float(lon):.6f}",
                 "" if lat is None else f"{float(lat):.6f}"):
        h.update(str(part).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def make_record(*, source_id: str, source_file: str, source_sha: str, source_locator: str,
                observed_at: str = "", acquired_at: str = "", spatial_id: str = "",
                longitude=None, latitude=None, variable_code: str, value=None, unit: str = "",
                quality_flag: str = "Q00", quality_status: str = "valid",
                provenance_type: str, is_ground_truth: bool = False, is_interpolated: bool = False,
                label_source: str = "", label_quality: str = "",
                cleaner_name: str, value_count=None, value_min=None, value_max=None,
                value_p50=None, value_p90=None, aux: dict | None = None,
                run_id: str = "") -> dict:
    """构造一条标准化记录；provenance_type 必须合法，ground_truth 必须显式声明。"""
    if provenance_type not in PROVENANCE_TYPES:
        raise ValueError(f"非法 provenance_type: {provenance_type!r}，只允许 {PROVENANCE_TYPES}")
    if provenance_type == "ground_truth" and not is_ground_truth:
        is_ground_truth = True
    if is_ground_truth and provenance_type != "ground_truth":
        raise ValueError("is_ground_truth=True 只允许出现在 provenance_type=ground_truth")
    rec = {
        "release_id": RELEASE_ID, "run_id": run_id,
        "record_id": record_id(source_sha, source_locator, variable_code, observed_at, longitude, latitude),
        "source_id": source_id, "source_file": source_file, "source_file_sha256": source_sha,
        "source_locator": source_locator,
        "observed_at": observed_at, "acquired_at": acquired_at,
        "spatial_id": spatial_id,
        "longitude": None if longitude is None else float(longitude),
        "latitude": None if latitude is None else float(latitude),
        "variable_code": variable_code,
        "value": None if value is None or (isinstance(value, float) and not math.isfinite(value)) else float(value),
        "unit": unit,
        "quality_flag": quality_flag, "quality_status": quality_status,
        "provenance_type": provenance_type,
        "is_ground_truth": bool(is_ground_truth), "is_interpolated": bool(is_interpolated),
        "label_source": label_source, "label_quality": label_quality,
        "cleaner_name": cleaner_name, "cleaner_version": CLEANER_VERSION,
        "value_count": value_count, "value_min": value_min, "value_max": value_max,
        "value_p50": value_p50, "value_p90": value_p90,
        "aux": json.dumps(aux, ensure_ascii=False) if aux else "",
    }
    return rec


def empty_file_result(path: str, sha: str, cleaner: str, status: str, notes: str,
                      record_count: int = 0) -> dict:
    if status not in FILE_STATUSES:
        raise ValueError(f"非法文件结论: {status!r}")
    return {"relative_path": path, "sha256": sha, "cleaner_name": cleaner,
            "cleaner_version": CLEANER_VERSION, "status": status,
            "record_count": record_count, "notes": notes}


def records_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for c in RECORD_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[RECORD_COLUMNS]


def file_results_frame(rows: list[dict]) -> pd.DataFrame:
    cols = ["relative_path", "sha256", "cleaner_name", "cleaner_version",
            "status", "record_count", "notes"]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def save_cleaner_output(cleaner: str, records: pd.DataFrame, results: pd.DataFrame) -> tuple[Path, Path]:
    out = WORK_DIR / cleaner
    out.mkdir(parents=True, exist_ok=True)
    records.to_parquet(out / "records.parquet", index=False)
    results.to_parquet(out / "file_results.parquet", index=False)
    return out / "records.parquet", out / "file_results.parquet"


def load_cleaner_output(cleaner: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = WORK_DIR / cleaner
    return (pd.read_parquet(out / "records.parquet"),
            pd.read_parquet(out / "file_results.parquet"))


# ---------------------------------------------------------------- 读文件辅助
def open_hdf5(path: Path):
    """h5py 打开非 ASCII 路径的稳妥方式（Windows 下用 UTF-8 bytes）。"""
    import h5py
    return h5py.File(str(Path(path).resolve()).encode("utf-8"), "r")


def bbox_slice_indices(lat: np.ndarray, lon: np.ndarray,
                       bbox: dict = TAIHU_BBOX) -> tuple[slice, slice]:
    """返回覆盖太湖 bbox 的 (lat_slice, lon_slice)，对升序/降序坐标都成立。"""
    lat_desc = lat[0] > lat[-1]
    lon_desc = lon[0] > lon[-1]
    lo_lat, hi_lat = bbox["lat_min"], bbox["lat_max"]
    lo_lon, hi_lon = bbox["lon_min"], bbox["lon_max"]
    if lat_desc:
        i0 = int(np.searchsorted(-lat, -hi_lat, side="left"))
        i1 = int(np.searchsorted(-lat, -lo_lat, side="right"))
    else:
        i0 = int(np.searchsorted(lat, lo_lat, side="left"))
        i1 = int(np.searchsorted(lat, hi_lat, side="right"))
    if lon_desc:
        j0 = int(np.searchsorted(-lon, -hi_lon, side="left"))
        j1 = int(np.searchsorted(-lon, -lo_lon, side="right"))
    else:
        j0 = int(np.searchsorted(lon, lo_lon, side="left"))
        j1 = int(np.searchsorted(lon, hi_lon, side="right"))
    return slice(max(0, i0), max(0, i1)), slice(max(0, j0), max(0, j1))


def summarize(values: np.ndarray) -> dict:
    """对有效数值做统计；空数组返回全 NaN。"""
    v = np.asarray(values, dtype="float64").ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return dict(value_count=0, value=None, value_min=None, value_max=None,
                    value_p50=None, value_p90=None)
    return dict(value_count=int(v.size), value=float(np.mean(v)),
                value_min=float(np.min(v)), value_max=float(np.max(v)),
                value_p50=float(np.percentile(v, 50)), value_p90=float(np.percentile(v, 90)))
