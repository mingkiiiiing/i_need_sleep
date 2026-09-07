"""Build web overlay PNGs + manifest from THQBCA-V2 annual Chla/FAC GeoTIFFs.

Input : ../../../水华原始数据包_2026-09-02/03_THQBCA-V2原始数据集/解压内容/2.Bio-optics/
Output: backend/rs_overlays/{chla,fac}/*.png + backend/rs_overlays/manifest.json

The colour scale is FIXED across all years (not per-year stretched) so that
A/B year comparison stays honest. Nodata / negative retrievals → transparent.
Run once with the system Python (rasterio + numpy + Pillow required).
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

BASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
    "水华原始数据包_2026-09-02",
    "03_THQBCA-V2原始数据集", "解压内容", "2.Bio-optics",
)
OUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend", "rs_overlays"
)

MAX_LONG_SIDE = 1200  # output PNG cap on the long edge (native ≈ 2341)
ALPHA = 235

# 全期固定色标（与前端热力渐变一致：绿→黄→橙→红→深红）
STOPS = [
    (0.00, (22, 163, 74)),
    (0.25, (234, 179, 8)),
    (0.50, (249, 115, 22)),
    (0.75, (239, 68, 68)),
    (1.00, (220, 38, 38)),
]

LAYERS = [
    {
        "id": "chla",
        "name": "叶绿素 a 浓度",
        "unit": "μg/L",
        "vmin": 0.0,
        "vmax": 60.0,
        "subdir": "chla",
        "glob": "2.4Chla/*.tif",
        "prefix": "TH_Chla_",
        "drop_negative": True,
        "resampling": Resampling.bilinear,
    },
    {
        "id": "fac",
        "name": "漂浮藻类覆盖率",
        "unit": "%",
        "vmin": 0.0,
        "vmax": 15.0,
        "subdir": "fac",
        "glob": "2.2FAC/*.tif",
        "prefix": "TH_FAC_",
        "drop_negative": False,
        "resampling": Resampling.bilinear,
    },
]


def colorize(values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    t = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    xs = [s[0] for s in STOPS]
    chans = list(zip(*[s[1] for s in STOPS]))
    rgba = np.empty(values.shape + (4,), dtype=np.uint8)
    for i, channel in enumerate(chans):
        rgba[..., i] = np.interp(t, xs, channel).astype(np.uint8)
    rgba[..., 3] = np.where(np.isnan(values), 0, ALPHA).astype(np.uint8)
    return rgba


def target_grid(src) -> tuple:
    if src.crs.to_string() == "EPSG:4326":
        return src.transform, src.width, src.height
    transform, w, h = calculate_default_transform(
        src.crs, "EPSG:4326", src.width, src.height, *src.bounds
    )
    long_side = max(w, h)
    if long_side > MAX_LONG_SIDE:
        w = max(1, int(round(w * MAX_LONG_SIDE / long_side)))
        h = max(1, int(round(h * MAX_LONG_SIDE / long_side)))
        transform = transform * rasterio.Affine.scale(src.width / w, src.height / h)
    return transform, w, h


def convert_layer(layer: dict) -> list[dict]:
    files = sorted(glob.glob(os.path.join(BASE, layer["glob"])))
    if not files:
        raise SystemExit(f"no input files for layer {layer['id']}: {layer['glob']}")
    out_dir = os.path.join(OUT_DIR, layer["subdir"])
    os.makedirs(out_dir, exist_ok=True)
    years = []
    for path in files:
        year = int(os.path.basename(path)[len(layer["prefix"]):][:4])
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nod = src.nodata
            valid = np.isfinite(arr)
            if nod is not None:
                valid &= arr != nod
            if layer["drop_negative"]:
                valid &= arr >= 0
            stats_vals = arr[valid]
            stats = {
                "valid_pct": round(100.0 * valid.mean(), 1),
                "min": round(float(stats_vals.min()), 2),
                "mean": round(float(stats_vals.mean()), 2),
                "p95": round(float(np.percentile(stats_vals, 95)), 2),
                "max": round(float(stats_vals.max()), 2),
            }
            dst_transform, dst_w, dst_h = target_grid(src)
            dst = np.full((dst_h, dst_w), np.nan, dtype="float64")
            reproject(
                source=arr,
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=nod,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                dst_nodata=np.nan,
                resampling=layer["resampling"],
            )
            if layer["drop_negative"]:
                dst[dst < 0] = np.nan
        valid_dst = np.isfinite(dst)
        b = rasterio.transform.array_bounds(dst_h, dst_w, dst_transform)
        south, west, north, east = b[1], b[0], b[3], b[2]
        png = colorize(dst, layer["vmin"], layer["vmax"])
        out_path = os.path.join(out_dir, os.path.basename(path).replace(".tif", ".png"))
        Image.fromarray(png, "RGBA").save(out_path, optimize=True)
        size_kb = os.path.getsize(out_path) // 1024
        print(f"{layer['id']} {year} ok  {dst_w}x{dst_h}  {size_kb} KB  stats={stats}")
        years.append(
            {
                "year": year,
                "png": f"{layer['subdir']}/{os.path.basename(out_path)}",
                "bounds": [[south, west], [north, east]],
                "stats": stats,
            }
        )
    return years


def main() -> None:
    tz = timezone(timedelta(hours=8))
    layers_out = []
    for layer in LAYERS:
        years = convert_layer(layer)
        layers_out.append(
            {
                "id": layer["id"],
                "name": layer["name"],
                "unit": layer["unit"],
                "vmin": layer["vmin"],
                "vmax": layer["vmax"],
                "legend_stops": [[t, "#%02x%02x%02x" % rgb] for t, rgb in STOPS],
                "years": years,
            }
        )
    manifest = {
        "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
        "source_dataset": "THQBCA-V2原始数据集 · 2.Bio-optics（30m 年度反演产品）",
        "note": (
            "年度卫星遥感反演产品：真实历史观测（非实时、非模拟）。"
            "色标为全期固定尺度，跨年对比有意义；透明区域为无效像元（湖外或缺测）。"
        ),
        "layers": layers_out,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print("manifest ->", os.path.normpath(manifest_path))


if __name__ == "__main__":
    main()
