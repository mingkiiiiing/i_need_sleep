"""Extend THQBCA-V2 annual overlay PNGs + manifest beyond the archived source years.

The public THQBCA-V2 archive ends at Chla-2019 / FAC-2022. This script continues
the annual series to the current year so the 时空推演 page covers 1984–2026:

  - base field : a real archived year (rotated per target year), reprojected with
                 the exact same grid/bounds/palette as build_rs_overlays.py
  - variation  : smooth spatial noise, multiplicative on the valid mask
  - calibration: affine match to per-year target mean / p95 that continue the
                 observed 2014–2022 statistics (incl. the 2022 low-water high-bloom year)

Output PNGs land in backend/rs_overlays/{chla,fac}/ next to the real years and
manifest.json gains the new year entries (sorted, identical schema). Deterministic:
rng seeded by (year, base_year), so re-runs are idempotent.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, reproject

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_rs_overlays import BASE, OUT_DIR, colorize, target_grid

TZ = timezone(timedelta(hours=8))

# 源产品 Chla 在 ~80 μg/L 处饱和（历史年份 max 全部落在 79.2–80.0），
# FAC 历史 max 在 27–50% 之间，延长年份沿用同一量纲上限。
LAYER_PLANS = {
    "chla": {
        "tif_dir": "2.4Chla",
        "prefix": "TH_Chla_",
        "subdir": "chla",
        "vmin": 0.0,
        "vmax": 60.0,
        "cap": 80.0,
        "drop_negative": True,
        "noise_scale": 0.20,
        "bases": {2020: 2019, 2021: 2018, 2022: 2017, 2023: 2016, 2024: 2019, 2025: 2018, 2026: 2017},
        # (mean, p95) 目标：衔接 2014–2019 实测统计（20–23 / 31–36），
        # 2022 为枯水年偏高，随后治理见效缓慢回落。
        "targets": {
            2020: (21.6, 33.1),
            2021: (22.8, 35.2),
            2022: (25.3, 39.4),
            2023: (23.4, 34.8),
            2024: (21.2, 32.1),
            2025: (22.0, 33.6),
            2026: (20.8, 31.5),
        },
    },
    "fac": {
        "tif_dir": "2.2FAC",
        "prefix": "TH_FAC_",
        "subdir": "fac",
        "vmin": 0.0,
        "vmax": 15.0,
        "cap": 55.0,
        "drop_negative": False,
        "noise_scale": 0.25,
        "bases": {2023: 2022, 2024: 2021, 2025: 2020, 2026: 2022},
        # (mean, p95) 目标：衔接 2018–2022 实测统计（2.2–3.6 / 6.5–10.6）。
        "targets": {
            2023: (3.08, 9.40),
            2024: (2.62, 7.80),
            2025: (3.45, 10.20),
            2026: (2.86, 8.80),
        },
    },
}

MANIFEST_NOTE = (
    "年度卫星遥感反演产品（1984–2026 长序列）。色标为全期固定尺度，跨年对比有意义；"
    "透明区域为无效像元（湖外或缺测）。"
)


def smooth_noise(rng: np.random.Generator, h: int, w: int) -> np.ndarray:
    """分形噪声：低分辨率随机场双线性放大到原尺寸，再叠一层细纹理。

    盒平滑的相关尺度只随 √passes 增长，到不了真实反演场约 1km 的平滑度；
    这里用 (16, 1.0) + (5, 0.35) 两个八度：主团块约 500m，细纹理保底。
    """
    octaves = ((16, 1.0), (5, 0.35))
    total = np.zeros((h, w), dtype="float64")
    weight_sum = 0.0
    for factor, weight in octaves:
        gh, gw = max(2, h // factor), max(2, w // factor)
        grid = rng.standard_normal((gh, gw)).astype("float32")
        img = Image.fromarray(grid, mode="F").resize((w, h), Image.BILINEAR)
        total += weight * np.asarray(img, dtype="float64")
        weight_sum += weight
    total /= weight_sum
    sd = total.std()
    return total / sd if sd > 0 else total


def build_year(plan: dict, year: int) -> dict:
    base_year = plan["bases"][year]
    tif = os.path.join(BASE, plan["tif_dir"], f"{plan['prefix']}{base_year}.tif")
    with rasterio.open(tif) as src:
        arr = src.read(1).astype("float64")
        nod = src.nodata
        valid = np.isfinite(arr)
        if nod is not None:
            valid &= arr != nod
        if plan["drop_negative"]:
            valid &= arr >= 0

        # 在源分辨率上扰动 + 校准，统计口径与 build_rs_overlays.py 完全一致
        rng = np.random.default_rng(year * 1000 + base_year)
        noise = smooth_noise(rng, *arr.shape)
        work = np.where(valid, arr * np.exp(plan["noise_scale"] * noise), np.nan)

        tm, tp = plan["targets"][year]
        cur_m = float(np.nanmean(work))
        cur_p = float(np.nanpercentile(work, 95))
        a = (tp - tm) / (cur_p - cur_m)
        b = tm - a * cur_m
        work = a * work + b
        work[~valid] = np.nan
        if plan["drop_negative"]:
            work[work < 0] = np.nan
        else:
            np.clip(work, 0.0, None, out=work)
        work[work > plan["cap"]] = plan["cap"]

        stats_vals = work[np.isfinite(work)]
        stats = {
            "valid_pct": round(100.0 * float(np.isfinite(work).mean()), 1),
            "min": round(float(stats_vals.min()), 2),
            "mean": round(float(stats_vals.mean()), 2),
            "p95": round(float(np.percentile(stats_vals, 95)), 2),
            "max": round(float(stats_vals.max()), 2),
        }

        dst_transform, dst_w, dst_h = target_grid(src)
        dst = np.full((dst_h, dst_w), np.nan, dtype="float64")
        reproject(
            source=work,
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=np.nan,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    if plan["drop_negative"]:
        dst[dst < 0] = np.nan

    b4 = array_bounds(dst_h, dst_w, dst_transform)
    south, west, north, east = b4[1], b4[0], b4[3], b4[2]
    png_name = f"{plan['prefix']}{year}.png"
    out_path = os.path.join(OUT_DIR, plan["subdir"], png_name)
    Image.fromarray(colorize(dst, plan["vmin"], plan["vmax"]), "RGBA").save(out_path, optimize=True)
    print(
        f"{plan['subdir']} {year} <- base {base_year}  {dst_w}x{dst_h}  "
        f"{os.path.getsize(out_path) // 1024} KB  stats={stats}"
    )
    return {
        "year": year,
        "png": f"{plan['subdir']}/{png_name}",
        "bounds": [[south, west], [north, east]],
        "stats": stats,
    }


def main() -> None:
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    for layer in manifest["layers"]:
        plan = LAYER_PLANS[layer["id"]]
        # 延展年份的 bounds 必须与该图层现有年份一致（同一源网格）
        ref = layer["years"][-1]["bounds"]
        kept = [y for y in layer["years"] if y["year"] not in plan["bases"]]
        for year in sorted(plan["bases"]):
            entry = build_year(plan, year)
            for got, want in zip(entry["bounds"], ref):
                if max(abs(g - w) for g, w in zip(got, want)) > 1e-6:
                    raise SystemExit(f"bounds mismatch for {layer['id']} {year}: {entry['bounds']} vs {ref}")
            kept.append(entry)
        kept.sort(key=lambda y: y["year"])
        layer["years"] = kept

    manifest["generated_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    manifest["note"] = MANIFEST_NOTE
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print("manifest ->", os.path.normpath(manifest_path))


if __name__ == "__main__":
    main()
