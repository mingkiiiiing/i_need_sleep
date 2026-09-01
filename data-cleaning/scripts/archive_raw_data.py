# -*- coding: utf-8 -*-
"""第一步：扫描、分类、归档原始数据。

- 扫描 data-cleaning/storage 下所有数据文件（含 raw/rasters/silver/staging 等）
- 按数据类别复制到 merged_data/2026_sheng-fuwai-main-merge/raw_organized/<category>/<source>/，不删除/移动/覆盖原始文件
- 相同内容（sha256 全量哈希)只归档一次
- 产出 merged_data/2026_sheng-fuwai-main-merge/manifests/raw_data_inventory.csv
- 严格说为派生产物(silver/gold/runs/exports/releases/databases/manifests)的
  文件保留原位、登记清单但不复制；授权申请文档类不视为数据。

用法: python scripts/archive_raw_data.py [--copy-only-new]
"""
from __future__ import annotations

import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (  # noqa: E402
    ROOT, STORAGE, MANIFESTS, ARCHIVE, file_sha256, read_table, bnow,
)

# 数据文件扩展名
DATA_EXTS = {
    ".csv", ".xlsx", ".xls", ".json", ".jsonl", ".txt", ".tsv", ".parquet",
    ".tif", ".tiff", ".nc", ".nc4", ".hdf", ".h5", ".he5", ".grib", ".grib2",
    ".shp", ".shx", ".dbf", ".prj", ".sbn", ".sbx", ".gpkg", ".geojson",
    ".pdf", ".zip", ".rar", ".7z", ".xml", ".html", ".sqlite", ".db", ".sqlit",
}
# 视为派生/非数据而排除的顶层目录
EXCLUDED_DIRS = {
    "runs", "exports", "releases", "databases", "authorization", "raw_organized", "cleaned",
}
# 检查范围（相对于 storage）
SCAN_ROOTS = ["raw", "rasters", "silver", "staging", "gold", "manifests", "."]

OUT = MANIFESTS / "raw_data_inventory.csv"


def _category(p: Path) -> tuple[str, str, str]:
    """返回 (data_category, source_dir, status)。status: raw | parse_artifact | derived | metadata | other_in_place。"""
    s = p.as_posix()
    rel = s.replace("\\", "/")
    low = rel.lower()

    def under(seg):
        return f"/{seg.lower()}/" in low or low.startswith(f"{seg.lower()}/")

    def under2(seg1, seg2):
        return f"/{seg1.lower()}/{seg2.lower()}/" in low

    if "/gold/" in low:
        if "sentinel2_retrieval_20260802" in low:
            return "remote_sensing", "s2_retrieval_20260802_derived", "derived_in_place"
        return "model_features", low.split("/gold/", 1)[1].split("/")[0], "derived_in_place"
    if "/manifests/" in low or low.startswith("manifests/"):
        return "metadata", "pipeline_manifests", "metadata_in_place"
    if "/silver/" in low:
        if "/nasa_power/" in low:
            return "meteorology", "nasa_power_cleaned", "derived"
        if "/mee_taihu_monthly/" in low:
            return "reports", "mee_taihu_monthly_parsed", "derived"
        if "/taihu_insitu/" in low:
            return "field_samples", "taihu_insitu_cleaned", "derived"
        if "/geo/" in low:
            return "static_features", "silver_geo_clips", "derived"
        if "/forecast/" in low:
            return "meteorology", "forecast_derived", "derived"
        base = Path(p).name.lower()
        if base == "normalized_observations.csv":
            return "unknown", "derived_mixed_long_table", "derived"
        if base.startswith("nasa_power"):
            return "meteorology", "nasa_power_cleaned", "derived"
        return "unknown", "silver_other", "derived"
    if "/staging/" in low:
        if "waterstation" in low:
            return "water_quality", "water_station_batch", "parse_artifact"
        if "hydrobasins" in low:
            return "static_features", "hydrobasins", "raw"
        if "clms_lwq_catalog" in low:
            return "remote_sensing", "clms_lwq_catalog", "raw"
        return "unknown", "staging_other", "parse_artifact"
    if under("taihu_thqbca_zenodo"):
        if "3.climate" in low or "(3cl)imat" in low:
            return "meteorology", "taihu_thqbca_v2_3climate", "raw"
        return "water_quality", "taihu_thqbca_v2", "raw"
    if under("taihu_thqbca_parsed"):
        return "water_quality", "taihu_thqbca_v2_parsed", "parse_artifact"
    if under("authorized_waterstation"):
        return "water_quality", "authorized_waterstation", "raw"
    if under("mee_surface_water_realtime"):
        return "water_quality", "mee_surface_water_realtime", "raw"
    if under("zenodo_taihu_insitu"):
        return "field_samples", "zenodo_taihu_insitu", "raw"
    if under("nasa_power_hourly"):
        return "meteorology", "nasa_power_hourly", "raw"
    if under("mee_surface_water_monthly"):
        return "reports", "mee_surface_water_monthly", "raw"
    if under("mwr_hfc"):
        return "hydrology", "mwr_hfc", "raw"
    if under("tba_hydrology"):
        return "hydrology", "tba_hydrology_download_failed", "raw"
    if under("hydrolakes"):
        return "static_features", "hydrolakes", "raw"
    if under("hydrobasins"):
        return "static_features", "hydrobasins", "raw"
    if under("static_geo"):
        if "worldcover" in low:
            return "static_features", "esa_worldcover_2021_v200", "raw"
        return "static_features", "copernicus_dem_glo30", "raw"
    if under("lake_geodata_probe"):
        return "unknown", "lake_geodata_probes", "raw"
    if under("earth_search_sentinel2"):
        return "remote_sensing", "earth_search_sentinel2", "raw"
    if "earth_search_sentinel2_annual" in low:
        return "remote_sensing", "earth_search_sentinel2_annual", "raw"
    if "/clms_lwq_catalog/" in low or low.startswith("clms_lwq_catalog/"):
        return "remote_sensing", "clms_lwq_catalog", "raw"
    if under("copernicus_sentinel2_stac"):
        return "remote_sensing", "sentinel2_stac", "raw"
    # storage 根目录 THQBCA-V2 全量解压
    if "/2.bio-optics/" in low:
        return "remote_sensing", "thqbca_v2_biooptics", "raw"
    if "/4.anthropogenic/" in low:
        return "static_features", "thqbca_v2_anthropogenic", "raw"
    if "/1.waterquality/" in low:
        return "water_quality", "taihu_thqbca_v2", "raw"
    if "/3.climate/" in low:
        return "meteorology", "taihu_thqbca_v2_3climate", "raw"
    if re.search(r"(^|/)thqbca-v2(\.rar)?(/|$)|^thqbca-v2", low, re.I) or low == "thqbca-v2.rar":
        return "water_quality", "taihu_thqbca_v2", "raw"
    if re.search(r"(^|/)data_cleaning\.(db|sqlite)$", low):
        return "unknown", "derived_database", "derived_in_place"
    if re.search(r"(^|/)reports/(?!raw_organized)", low) and re.search(r"(^|/)reports/[^/]+\.(csv|json|db|sqlite)$", low):
        return "model_features", "audit_reports", "derived_in_place"
    if under("meteorology"):
        if "gfs" in low or "grib" in low:
            return "meteorology", "noaa_gfs", "raw"
        if "ecmwf" in low:
            return "meteorology", "ecmwf_open_data", "raw"
        return "meteorology", "meteorology_other", "raw"
    if under("open_meteo_forecast"):
        return "meteorology", "open_meteo_forecast", "raw"
    if under("open_meteo_seasonal"):
        return "meteorology", "open_meteo_seasonal", "raw"
    if "/rasters/" in low or low.startswith("rasters/"):
        if "clms" in low:
            return "remote_sensing", "clms_lwq_300m", "raw"
        if "sentinel2" in low:
            return "remote_sensing", "sentinel2_monthly", "raw"
        return "remote_sensing", "rasters_other", "raw"
    if Path(p).name.lower() == "thqbca-v2.rar" or low.startswith("thqbca-v2.rar"):
        return "water_quality", "taihu_thqbca_v2", "raw"
    # 项目根下或 samples 等
    if "samples" in low:
        return "unknown", "sample_payloads", "raw"
    return "unknown", "unclassified", "raw"


def guess_dates(p: Path) -> tuple[str, str]:
    """从路径/文件名提取日期范围（保守猜测, 失败返回空）。"""
    name = p.name
    m = re.findall(r"((?:19|20)\d{2})[-_]?(\d{2})?[-_]?(\d{2})?", name)
    for y, mo, d in m:
        if mo and d:
            try:
                return f"{y}-{mo}-{d}", f"{y}-{mo}-{d}"
            except ValueError:
                pass
        elif mo and 1 <= int(mo) <= 12 and len(name) < 60:
            return f"{y}-{mo}-01", f"{y}-{mo}-31"
        else:
            return f"{y}-01-01", f"{y}-12-31"
    return "", ""


def row_count_for(p: Path, ext: str) -> int:
    """尽力统计表格行数（小文件）；否则返回 0 表示未知。"""
    try:
        size = p.stat().st_size
        if ext == ".csv":
            if size < 80_000_000:
                with open(p, "rb") as fh:
                    return 1 + sum(len(line) < 1_000_000 for line in fh)
            return 0
        if ext in (".xlsx", ".xls"):
            if size < 40_000_000:
                import openpyxl
                wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
                total = 0
                for ws in wb.worksheets:
                    total += ws.max_row or 0
                wb.close()
                return total
            return 0
    except Exception:
        return 0
    return 0


def raster_meta(p: Path):
    try:
        import rasterio
        with rasterio.open(p) as ds:
            crs = ds.crs.to_string() if ds.crs else ""
            res = ds.res
            return crs, round(float(res[0]), 4), ds.width, ds.height
    except Exception:
        return "", 0.0, 0, 0


def scan_files() -> list[dict]:
    rows: list[dict] = []
    seen_paths = set()
    for root_rel in SCAN_ROOTS:
        root = (STORAGE / root_rel) if root_rel != "." else STORAGE
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in DATA_EXTS:
                continue
            pp = p.resolve()
            if pp in seen_paths:
                continue
            seen_paths.add(pp)
            low = p.relative_to(STORAGE).as_posix().lower()
            if low.startswith("cleaned/") or "/cleaned/" in f"/{low}":
                continue  # 清洗输出目录不属于原始数据
            if any(f"/{x}/" in f"/{low}" for x in EXCLUDED_DIRS) or any(low.startswith(x + "/") for x in EXCLUDED_DIRS):
                rows.append(_base_row(p, "other_artifacts_dirs", None, "派生产品目录，登记不复制"))
                continue
            rows.append(_base_row(p, None, None))
    return rows


def _base_row(p: Path, status_override=None, cat_override=None, note="") -> dict:
    ext = p.suffix.lower()
    cat, src, status = _category(p)
    if status_override:
        status = status_override
    if cat_override:
        cat = cat_override
    return dict(
        source_path=p.relative_to(STORAGE).as_posix(),
        organized_path="", file_name=p.name, file_type=ext,
        data_category=cat, source_dir=src, file_size=int(p.stat().st_size),
        modified_time=datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        hash="", start_date="", end_date="", row_count=0,
        crs="", resolution_m=0.0, width=0, height=0, status=status, notes=note,
    )


def main(copy_only_new: bool = False) -> None:
    t0 = time.time()
    rows = scan_files()
    print(f"扫描到 {len(rows)} 个数据文件")

    # metadata 预处理（只对将归档的文件计算全量哈希）
    for r in rows:
        p = ROOT / r["source_path"]
        ext = r["file_type"]
        if r["status"] not in ("derived_in_place", "metadata_in_place", "other_artifacts_dirs"):
            r["hash"] = file_sha256(p)
        r["start_date"], r["end_date"] = guess_dates(p)
        if ext in (".tif", ".tiff"):
            crs, res, w, h = raster_meta(p)
            r["crs"], r["resolution_m"], r["width"], r["height"] = crs, res, w, h
        elif ext in (".csv", ".xlsx", ".xls"):
            r["row_count"] = row_count_for(p, ext)

    # 哈希去重并复制
    seen_hash: dict[str, str] = {}   # hash -> 已归档 absolute path
    dest_hashes: dict[Path, str] = {}  # 目标文件 -> 其内容hash(跨运行判定)
    copied = duplicated = skipped = failed = 0
    for i, r in enumerate(rows):
        p = ROOT / r["source_path"]
        if not p.exists():
            r["status"] = "missing_source"
            continue
        h = r["hash"]
        if r["status"] in ("derived_in_place", "metadata_in_place", "other_artifacts_dirs"):
            r["notes"] = (r["notes"] + "; 派生/元数据资产保留原位").strip("; ")
            skipped += 1
            continue
        if h in seen_hash:
            r["status"] = "duplicate_skipped"
            r["organized_path"] = seen_hash[h].replace(str(STORAGE), "").lstrip("\\/").replace("\\", "/")
            r["notes"] = (r["notes"] + "; 与前者内容一致(hash相同)免重复复制").strip("; ")
            duplicated += 1
            continue
        # 复制
        rel_dir = r["source_dir"]
        dest_dir = ARCHIVE / r["data_category"] / rel_dir
        dest = dest_dir / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 目标已存在时: 用已有的 dest->hash 映射判定是否同一内容(而非仅大小)
        if dest.exists():
            hd = dest_hashes.get(dest)
            if hd is None:
                hd = file_sha256(dest)
                dest_hashes[dest] = hd
            same_content = (hd == h) or (hd == "" and dest.stat().st_size == r["file_size"])
        else:
            same_content = False
        if dest.exists() and same_content:
            r["status"] = "already_archived"
        else:
            # 同名但内容不同(不同源的同名文件) → 加哈希后缀, 避免覆盖
            if dest.exists() and not same_content:
                dest = dest.with_name(f"{dest.stem}_{h[:8]}{dest.suffix}")
                r["notes"] = (r["notes"] + "; 与同名文件内容不同, 已加哈希后缀").strip("; ")
            try:
                shutil.copy2(p, dest)
                r["status"] = "raw_archived" if r["status"] in ("raw", "parse_artifact") else r["status"]
                copied += 1
            except Exception as e:
                r["status"] = "copy_failed"
                r["notes"] = f"{r['notes']}; {e}".strip("; ")
                failed += 1
        seen_hash[h] = dest.as_posix()
        r["organized_path"] = dest.relative_to(STORAGE).as_posix()
        if i % 200 == 0:
            print(f"  {i}/{len(rows)} ...")

    df = pd.DataFrame(rows)
    df = df.sort_values(["data_category", "source_dir", "file_name"]).reset_index(drop=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n清单已写入: {OUT}")
    print(f"复制 {copied} 个, 哈希去重跳过 {duplicated} 个, 保留原位 {skipped} 个, 失败 {failed} 个, 用时 {time.time()-t0:.0f}s")
    # 汇总
    print("\n== 分类汇总 ==")
    print(df.groupby(["data_category", "status"]).size().to_string())
    print("\n== 各类别总大小(已归档) ==")
    d = df[df["organized_path"] != ""]
    if len(d):
        d = d.copy()
        d["size_gb"] = d["file_size"] / 1e9
        print(d.groupby("data_category")["size_gb"].sum().round(2).to_string())


if __name__ == "__main__":
    main(copy_only_new="--copy-only-new" in sys.argv)
