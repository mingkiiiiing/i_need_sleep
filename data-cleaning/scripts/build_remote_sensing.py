# -*- coding: utf-8 -*-
"""遥感数据处理: 栅格索引 + 全湖/站点月度特征提取。

- 保留原始栅格不动; 逐文件登记 remote_sensing_inventory.csv
- 每月(或年度)输出全湖统计(mean/median/std/min/max/覆盖度/云量) → remote_sensing_monthly_cleaned.csv
- 覆盖: Sentinel-2 CDSE 月合成(30m/20m)、CLMS LakeWaterQuality 300m(10日)、
  THQBCA-V2 Bio-optics 年度产品(FAC/Chl-a/SDD/TSI/植被)、Sentinel-2 反演指标(NDCI/MCI/FAI/NDWI)、
  EarthSearch 年度栅格、SNTP 检索实验产品。
- 已知低质量月份标记: 2022-11, 2024-04 (cloud_low_quality); 其余低覆盖/高云量阈值触发。

用法: python scripts/build_remote_sensing.py   [重复运行自动利用缓存]
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, CACHE_DIR, ROOT, STORAGE, flag_join, write_dataset

S2_ROOT = STORAGE / "rasters/sentinel2_monthly_30m_cdse"
S2_20M_ROOT = STORAGE / "rasters/sentinel2_monthly_20m"
CLMS_ROOTS = (
    ("v1", STORAGE / "rasters/clms_lwq_300m_v1"),
    ("v2", STORAGE / "rasters/clms_lwq_300m_v2"),
)
RETRIEVAL_ROOT = STORAGE / "gold/sentinel2_retrieval_20260802"
BIOOPT_ROOT = STORAGE / "THQBCA-V2/2.Bio-optics"
ANTHRO_ROOT = STORAGE / "THQBCA-V2/4.Anthropogenic"
BOUNDARY_GPKG = STORAGE / "silver/geo/taihu_boundary.gpkg"

CLMS_BANDS = {1: "chla_mean", 2: "chla_uncertainty", 3: "fcb_prob", 4: "qflag"}
CLMS_INVALID = 1e20          # COG 填充值
S2_CLOUD_CLASSES = (3, 8, 9, 10, 11)   # SCL: 云影/中概率云/高概率云/薄卷云/雪
VERY_LARGE = 1e18            # 无效大值阈值

STATS_FIELDS = ["mean", "median", "std", "min", "max", "valid_frac"]
CACHE = {}


def _cache_path():
    return CACHE_DIR / "remote_file_stats.json"


def _load_cache() -> None:
    p = _cache_path()
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            CACHE.update(json.load(fh))


def _save_cache() -> None:
    with open(_cache_path(), "w", encoding="utf-8") as fh:
        json.dump(CACHE, fh, ensure_ascii=False, indent=0)


def load_boundary():
    import fiona
    with fiona.open(BOUNDARY_GPKG) as src:
        feat = next(iter(src))
        return feat["geometry"]


def to_geom(crs_from, crs_to, geom):
    from rasterio.warp import transform_geom
    try:
        return transform_geom(crs_from, crs_to, geom)
    except Exception:
        return None


def _mask_array(ds, geom):
    import rasterio.mask
    arr = rasterio.mask.mask(ds, [geom], crop=False, filled=True, nodata=None)[0].astype("float32")
    if ds.nodata is not None:
        arr[arr == np.float32(ds.nodata)] = np.nan
    arr[(arr < -VERY_LARGE) | (arr > VERY_LARGE)] = np.nan
    return arr


def stats_of(full_arr: np.ndarray, target: np.ndarray | None = None) -> dict:
    """full_arr: 湖内掩码数组(无效已 NaN); target: 可选局部掩码。"""
    if target is None:
        sel = full_arr
    else:
        sel = np.where(target, full_arr, np.nan)
    valid = sel[np.isfinite(sel)]
    out = {k: float("nan") for k in STATS_FIELDS}
    if valid.size:
        out.update(mean=float(np.nanmean(valid)), median=float(np.nanmedian(valid)),
                   std=float(np.nanstd(valid)), min=float(np.nanmin(valid)),
                   max=float(np.nanmax(valid)),
                   valid_frac=float(valid.size / sel.size))
    return out


def file_stats(path: Path, band: int = 1, geom=None) -> dict:
    """单文件统计: 全网格有效比率 + (给定边界)湖内统计。缓存按 path+size+mtime。"""
    st = path.stat()
    key = f"{path.name}|{st.st_size}|{int(st.st_mtime)}|{band}"
    if key in CACHE:
        return CACHE[key]
    import rasterio
    with rasterio.open(path) as ds:
        crs = ds.crs.to_string() if ds.crs else ""
        res = float(ds.res[0]) if ds.res else 0.0
        w, h = ds.width, ds.height
        a = ds.read(1).astype("float32")
        nod = ds.nodata
        bad = (a == np.float32(nod)) if nod is not None else (np.abs(a) > VERY_LARGE)
        valid_grid = (~bad) & (np.abs(a) < VERY_LARGE) & np.isfinite(a)
        valid_frac = float(valid_grid.mean()) if valid_grid.size else 0.0
        lake = {}
        if geom is not None:
            g = to_geom("EPSG:4326", ds.crs.to_epsg() if ds.crs and ds.crs.to_epsg() else None, geom)
            if g is None:
                try:
                    from rasterio.warp import transform_geom
                    g = transform_geom("EPSG:4326", ds.crs, geom)
                except Exception:
                    g = None
            if g is not None:
                import rasterio.mask
                arr = rasterio.mask.mask(ds, [g], crop=False, filled=True, nodata=None)[0].astype("float32")
                if nod is not None:
                    arr[arr == np.float32(nod)] = np.nan
                arr[(arr < -VERY_LARGE) | (arr > VERY_LARGE)] = np.nan
                lake = stats_of(arr)
                lake = {f"lake_{k}": v for k, v in lake.items()}
        out = dict(valid_pixel_ratio=round(valid_frac, 4), crs=crs, resolution_m=round(res, 4),
                   width=w, height=h, **lake)
    CACHE[key] = out
    return out


# ----------------------------- S2 月度 -----------------------------
def s2_month_rows() -> tuple[list[dict], list[dict]]:
    inventory, monthly = [], []
    months = sorted(d.name for d in S2_ROOT.iterdir() if d.is_dir() and d.name != "lost+found")
    for month in months:
        d = S2_ROOT / month
        scl_p = d / f"taihu_s2_l2a_{month}_SCL_30m.tif"
        cloud_ratio = np.nan
        if scl_p.exists():
            st = file_stats(scl_p, 1)
            with rasterio_ds(scl_p) as ds0:
                a = ds0.read(1)
                bad = np.isin(a, list(S2_CLOUD_CLASSES))
                cloud_ratio = float(bad.mean())
        for band_file in sorted(d.glob(f"taihu_s2_l2a_{month}_*_30m.tif")):
            if "multiband" in band_file.name or "SCL" in band_file.name:
                # 仅登记
                inv = _inventory_row(band_file, month, "sentinel2_cdse_monthly", "scl" if "SCL" in band_file.name else "multiband",
                                     cloud_ratio)
                inventory.append(inv)
                continue
            m = re.search(r"_(B\d\d|NDCI|MCI|FAI|NDWI)_30m", band_file.name)
            if not m:
                continue
            variable = m.group(1)
            st = file_stats(band_file, 1, geom=GEO)
            inv = _inventory_row(band_file, month, "sentinel2_cdse_monthly", variable, cloud_ratio)
            inv.update(valid_pixel_ratio=st["valid_pixel_ratio"])
            inventory.append(inv)
            lake = {k.replace("lake_", ""): v for k, v in st.items() if k.startswith("lake_")}
            monthly.append(dict(
                month=month, product="sentinel2_cdse_monthly_30m", granularity="monthly",
                variable=variable, mean=lake.get("mean"), median=lake.get("median"),
                std=lake.get("std"), min=lake.get("min"), max=lake.get("max"),
                coverage_frac=lake.get("valid_frac"), cloud_ratio=cloud_ratio,
                n_files=1, quality_flag=_s2_quality(month, cloud_ratio, lake.get("valid_frac")),
                quality_note=_s2_note(month),
            ))
    # 20m 补片
    month_roots = sorted(p for p in S2_20M_ROOT.iterdir() if p.is_dir()) if S2_20M_ROOT.exists() else []
    for month_root in month_roots:
        month = month_root.name
        for band_file in sorted(month_root.glob("*.tif")):
            m = re.search(r"_(B\d\d)_20m", band_file.name)
            variable = m.group(1) if m else band_file.stem
            st = file_stats(band_file, 1, geom=GEO)
            inv = _inventory_row(band_file, month, "sentinel2_monthly_20m", variable, np.nan)
            inv.update(valid_pixel_ratio=st["valid_pixel_ratio"])
            inventory.append(inv)
            lake = {k.replace("lake_", ""): v for k, v in st.items() if k.startswith("lake_")}
            monthly.append(dict(
                month=month, product="sentinel2_monthly_20m", granularity="monthly",
                variable=variable, mean=lake.get("mean"), median=lake.get("median"),
                std=lake.get("std"), min=lake.get("min"), max=lake.get("max"),
                coverage_frac=lake.get("valid_frac"), cloud_ratio=np.nan,
                n_files=1, quality_flag="Q00",
                quality_note="20m 采样补片(2022-01/2026-01), 无 SCL 云量(未标注)",
            ))
    return inventory, monthly


def _inventory_row(path: Path, month: str, product: str, variable: str, cloud_ratio) -> dict:
    st = file_stats(path, 1)
    return dict(
        date=_date_of(month, path), month=month, product=product, variable=variable,
        band=variable, file_path=str(path.relative_to(STORAGE)), crs=st["crs"],
        resolution_m=st["resolution_m"], width=st["width"], height=st["height"],
        valid_pixel_ratio=st["valid_pixel_ratio"], cloud_ratio=cloud_ratio,
        quality_flag="Q00", notes="",
    )


def _date_of(month: str, path: Path) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return m.group(1)
    if len(month) == 7:
        return f"{month}-01"
    return ""


def _s2_quality(month: str, cloud_ratio, coverage_frac) -> str:
    flags = []
    if (not np.isnan(cloud_ratio)) and cloud_ratio > 0.45:
        flags.append("Q10")
    if coverage_frac is not None and not np.isnan(coverage_frac) and coverage_frac < 0.20:
        flags.append("Q10")
    if month in ("2022-11", "2024-04"):
        flags.append("Q10")
    return flag_join(flags)


def _s2_note(month: str) -> str:
    note = "CDSE 月度合成; SCL 云掩膜"
    d = S2_ROOT / month
    if (d / "exact_day_backup").exists():
        note += "; 低云量可用影像不足, 以精确当日影像补片(原月度合存在 exact_day_backup)"
    return note


# ----------------------------- CLMS 300m -----------------------------
def clms_rows() -> tuple[list[dict], list[dict]]:
    inventory, per_file = [], []
    for version, root in CLMS_ROOTS:
        if not root.exists():
            continue
        for year in sorted(p for p in root.iterdir() if p.is_dir()):
          for f in sorted(year.glob("*.tif")):
            m = re.search(r"(\d{8})", f.name)
            date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ""
            month = date[:7]
            with __import__("rasterio").open(f) as ds:
                crs = ds.crs.to_string() if ds.crs else ""
                res = round(float(ds.res[0]), 4)
                w, h = ds.width, ds.height
                nbands = ds.count
                g = to_geom("EPSG:4326", ds.crs.to_epsg(), GEO)
                product = f"clms_lwq_300m_10daily_{version}"
                out = dict(date=date, month=month, product=product, variable="",
                           band="", file_path=str(f.relative_to(STORAGE)), crs=crs, resolution_m=res,
                           width=w, height=h, valid_pixel_ratio=float("nan"), cloud_ratio=float("nan"),
                           quality_flag="Q00", notes="COG填充值>1e20判为无效")
                perb = {}
                for b in range(1, nbands + 1):
                    a = ds.read(b).astype("float32")
                    a[(a < -CLMS_INVALID) | (a > CLMS_INVALID)] = np.nan
                    grid_ok = np.isfinite(a)
                    if b == 1:
                        out["valid_pixel_ratio"] = round(float(grid_ok.mean()), 4)
                    if g is not None and b <= 3:
                        import rasterio.mask
                        masked = rasterio.mask.mask(
                            ds, [g], indexes=b, crop=False, filled=True, nodata=None
                        )[0].astype("float32")
                        masked[(masked < -CLMS_INVALID) | (masked > CLMS_INVALID)] = np.nan
                        sel_rows = masked[np.isfinite(masked)]
                        var = CLMS_BANDS.get(b, f"band{b}")
                        perb[var] = dict(
                            mean=float(np.nanmean(sel_rows)) if sel_rows.size else np.nan,
                            median=float(np.nanmedian(sel_rows)) if sel_rows.size else np.nan,
                            std=float(np.nanstd(sel_rows)) if sel_rows.size else np.nan,
                            min=float(np.nanmin(sel_rows)) if sel_rows.size else np.nan,
                            max=float(np.nanmax(sel_rows)) if sel_rows.size else np.nan,
                            coverage_frac=float(sel_rows.size / masked.size) if masked.size else np.nan,
                        )
                no_science = not perb or all(not np.isfinite(item["mean"]) for item in perb.values())
                all_science_zero = bool(perb) and all(
                    np.isfinite(item["min"]) and np.isfinite(item["max"])
                    and item["min"] == 0.0 and item["max"] == 0.0
                    for item in perb.values()
                )
                if no_science or all_science_zero:
                    out["quality_flag"] = "Q03"
                    out["notes"] += "; 科学波段为空或全部为0，排除"
                inventory.append(out)
                if out["quality_flag"] != "Q03":
                    for var, s in perb.items():
                        per_file.append(dict(month=month, product=product, granularity="10_daily",
                                             variable=var, **s, n_files=1, cloud_ratio=np.nan,
                                             quality_flag="Q00" if np.isfinite(s["mean"]) else "Q03",
                                             quality_note=f"CLMS LWQ {version} 300m 10日产品"))
    # 汇总为月度
    monthly = []
    df = pd.DataFrame(per_file)
    if len(df):
        for (month, product, var), g in df.groupby(["month", "product", "variable"]):
            for col in ("mean", "median", "std", "min", "max", "coverage_frac"):
                g[col] = pd.to_numeric(g[col], errors="coerce")
            monthly.append(dict(
                month=month, product=product, granularity="monthly",
                variable=var, mean=float(g["mean"].mean()), median=float(g["median"].mean()),
                std=float(g["std"].mean()), min=float(g["min"].min()), max=float(g["max"].max()),
                coverage_frac=float(g["coverage_frac"].mean()), cloud_ratio=np.nan,
                n_files=int(len(g)), quality_flag="Q00" if g["mean"].notna().any() else "Q03",
                quality_note="月内 10 日产品简单平均(min/max 取极值)",
            ))
    return inventory, monthly


# ----------------------------- 反演产品 -----------------------------
def retrieval_rows() -> tuple[list[dict], list[dict]]:
    inventory, monthly = [], []
    date = "2026-08-02"
    for f in sorted(RETRIEVAL_ROOT.glob("*.tif")):
        st = file_stats(f, 1, geom=GEO)
        lake = {k.replace("lake_", ""): v for k, v in st.items() if k.startswith("lake_")}
        variable = f.stem
        inv = _inventory_row(f, "2026-08", "sentinel2_retrieval_20260802", variable, np.nan)
        inv.update(valid_pixel_ratio=st["valid_pixel_ratio"], date=date)
        inv["notes"] = "Sentinel-2 单景(20260802) 反演实验指数"
        inventory.append(inv)
        monthly.append(dict(
            month="2026-08", product="sentinel2_retrieval_20260802", granularity="scene",
            variable=variable, mean=lake.get("mean"), median=lake.get("median"), std=lake.get("std"),
            min=lake.get("min"), max=lake.get("max"), coverage_frac=lake.get("valid_frac"),
            cloud_ratio=np.nan, n_files=1, quality_flag="Q00",
            quality_note="单景反演, 非月合成; chla 为实验模型输出(µg/L)",
        ))
    return inventory, monthly


# ----------------------------- THQBCA Bio-optics 年度 -----------------------------
def thqbca_bio_rows() -> tuple[list[dict], list[dict]]:
    inventory, annual = [], []
    patterns = [
        ("fac", BIOOPT_ROOT / "2.2FAC", r"TH_FAC_(\d{4})\.tif", "fac", "dimensionless", True),
        ("chla", BIOOPT_ROOT / "2.4Chla", r"TH_Chla_(\d{4})\.tif", "chla_retrieval_annual", "µg/L", True),
        ("sdd", BIOOPT_ROOT / "2.3SDD", r"TH_SDD_(\d{4})\.tif", "sdd_annual", "m", True),
        ("tsi", BIOOPT_ROOT / "2.5TSI", r"TH_TSI_(\d{4})\.tif", "tsi_annual", "index", True),
        ("vege", BIOOPT_ROOT / "2.1AquaticVegetation", r"TH_vege_(\d{4})-\d{2}-\d{2}\.tif", "aquatic_vegetation_class", "category", False),
    ]
    for name, d, pat, var, unit, numeric in patterns:
        if not d.exists():
            print(f"  [THQBCA] 目录不存在 {d.name}")
            continue
        for f in sorted(d.glob("*.tif")):
            m = re.search(pat, f.name)
            if not m:
                continue
            year = m.group(1)
            st = file_stats(f, 1, geom=GEO)
            lake = {k.replace("lake_", ""): v for k, v in st.items() if k.startswith("lake_")}
            inventory.append(dict(
                date=f"{year}-01-01", month="", product="thqbca_v2_biooptics", variable=var,
                band=var, file_path=str(f.relative_to(STORAGE)), crs=st["crs"],
                resolution_m=st["resolution_m"], width=st["width"], height=st["height"],
                valid_pixel_ratio=st["valid_pixel_ratio"], cloud_ratio=np.nan,
                quality_flag="Q00", notes=f"THQBCA-V2 {name} 年度产品",
            ))
            if numeric:
                annual.append(dict(
                    month="", year=year, product="thqbca_v2_biooptics", granularity="annual",
                    variable=var, mean=lake.get("mean"), median=lake.get("median"),
                    std=lake.get("std"), min=lake.get("min"), max=lake.get("max"),
                    coverage_frac=lake.get("valid_frac"), cloud_ratio=np.nan, n_files=1,
                    quality_flag="Q00", quality_note=f"THQBCA-V2 年度{name}(遥感反演, 非观测)",
                ))
    return inventory, annual


# ----------------------------- 其他栅格登记 -----------------------------
def extra_inventory() -> list[dict]:
    rows = []
    for root, product in ((STORAGE / "raw/earth_search_sentinel2_annual", "earth_search_annual_mosaic"),
                          (STORAGE / "raw/earth_search_sentinel2", "earth_search_scene")):
        if not root.exists():
            continue
        for f in sorted(root.rglob("*.tif")):
            m = re.search(r"(\d{8})", f.name)
            month = f"{m.group(1)[:4]}-{m.group(1)[4:6]}" if m else ""
            date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ""
            try:
                import rasterio
                with rasterio.open(f) as ds:
                    crs = ds.crs.to_string() if ds.crs else ""
                    res = round(float(ds.res[0]), 4) if ds.res else 0
                    w, h = ds.width, ds.height
                    a = ds.read(1).astype("float32")
                    nod = ds.nodata
                    mbad = (a == nod) if nod is not None else (np.abs(a) > VERY_LARGE)
                    vp = round(float((~mbad & np.isfinite(a)).mean()), 4)
            except Exception as e:
                crs, res, w, h, vp = "", 0, 0, 0, np.nan
                print(f"  [ext] {f.name} 读取失败 {e}")
            rows.append(dict(
                date=date, month=month, product=product, variable="mosaic_band" if "mosaic" in product else "scene_band",
                band=f.stem, file_path=str(f.relative_to(STORAGE)), crs=crs, resolution_m=res,
                width=w, height=h, valid_pixel_ratio=vp, cloud_ratio=np.nan,
                quality_flag="Q00", notes="EarthSearch 原始块(未做湖内统计)",
            ))
    return rows


def rasterio_ds(path):
    import rasterio
    return rasterio.open(path)


def main() -> None:
    global GEO
    t0 = time.time()
    print("== 遥感处理 ==")
    _load_cache()
    GEO = load_boundary()
    inventory, monthly = s2_month_rows()
    inv2, mon2 = clms_rows()
    inventory += inv2; monthly += mon2
    inv3, mon3 = retrieval_rows()
    inventory += inv3; monthly += mon3
    inv4, mon4 = thqbca_bio_rows()
    inventory += inv4; monthly += mon4
    inventory += extra_inventory()
    _save_cache()
    inv_df = pd.DataFrame(inventory)
    inv_df = inv_df.sort_values(["product", "date", "variable"]).reset_index(drop=True)
    out_inv = write_dataset(inv_df, "remote_sensing_inventory")
    mon_df = pd.DataFrame(monthly)
    mon_df = mon_df.sort_values(["month", "product", "variable"]).reset_index(drop=True)
    out_mon = write_dataset(mon_df, "remote_sensing_monthly_cleaned")
    print(f"  [遥感索引] {out_inv}  {inv_df.shape[0]} 文件行")
    print(f"  [遥感月度] {out_mon}  {mon_df.shape[0]} 行, 时长 {time.time()-t0:.0f}s")
    with open(CLEANED / "remote_sensing_run_summary.txt", "w", encoding="utf-8") as fh:
        fh.write(f"files={inv_df.shape[0]} monthly_rows={mon_df.shape[0]} elapsed_s={time.time()-t0:.0f}\n")
        fh.write("products:\n" + inv_df.groupby("product").size().to_string() + "\n")
    return inv_df, mon_df


if __name__ == "__main__":
    main()
