"""路径、版本与时区常量 (设计 §13 contracts)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pipeline.provenance import STORAGE

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # data-cleaning/
CONFIG_DIR = PACKAGE_ROOT / "config" / "data_factory"
FACTORY_RUNS = Path(os.environ.get("DATA_FACTORY_RUNS") or (STORAGE / "runs" / "data_factory"))
RELEASE_ROOT = Path(os.environ.get("DATA_FACTORY_RELEASE") or (STORAGE / "releases" / "data_factory_release"))
RAW_ROOT = STORAGE / "raw"
BOUNDARY_GPKG = STORAGE / "silver" / "geo" / "taihu_boundary.gpkg"
BOUNDARY_MANIFEST = STORAGE / "silver" / "geo" / "taihu_boundary_manifest.json"
DEFAULT_RELEASE_TABLES = STORAGE / "final_cleaned" / "TAIHU_CLEAN_FINAL_V1_20260831"
SOURCE_REGISTRY_CSV = PACKAGE_ROOT / "config" / "data_source_registry.csv"
TAIHUGURAD_STATIONS = PACKAGE_ROOT.parents[1] / "taihugurad" / "data" / "stations.json"
# 合并站点注册表：taihugurad 61 站 + MEE 国控断面（坐标缺失站如实登记待补），
# freeze-grid 默认源（审计 2026-09-06：站点-网格映射覆盖 MEE 实时断面）
STATION_REGISTRY_MERGED = CONFIG_DIR / "stations.json"
# MEE 实时站点三层结构（Snapshot→Station 目录→完整缺测观测）落盘根
MEE_REALTIME_CATALOG_DIR = STORAGE / "silver" / "mee_realtime"
NASA_POWER_RAW = PACKAGE_ROOT.parents[1] / "02_全部原始数据" / "01_当前主原始数据" / "nasa_power_hourly"
TIMEZONE = "Asia/Shanghai"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_dir(dataset: str) -> Path:
    return FACTORY_RUNS / dataset


def yaml_path(name: str) -> Path:
    return CONFIG_DIR / name
