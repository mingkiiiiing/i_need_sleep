"""年度反演产品 PNG → 像元场 → 月度站点残差修正 → 连续栅格 PNG + 水华边界 GeoJSON。

spatial_method = "calibrated_annual_product_plus_station_residual"：
- 基底：THQBCA-V2 年度 30m Chla PNG（全期固定色标 0-60 μg/L，线性反解像元值）；
- 月度修正：站点月度 chla 观测（ground_truth）+ CLMS 湖泊月均（remote_retrieval）为锚点，
  基底在锚点处的残差经 IDW 扩散到全湖；
- 水华边界：修正场 ≥ 20 μg/L 阈值分割（rasterio.features.shapes）→ GeoJSON + 面积。
色标反解存在 8-bit 量化误差，如实披露于 colorbar_inversion_note。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from rasterio import features
from rasterio.transform import from_bounds

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "model_runtime_v0_3" / "code"))

from modeling_real.contracts_real import clean_tables_dir  # noqa: E402

OUT_DIR = ROOT / "backend" / "rs_overlays" / "monthly_v3"
BLOOM_THRESHOLD = 20.0
LAKE_CENTROID = (120.10, 31.20)


def load_annual_manifest() -> tuple[dict, dict]:
    manifest = json.loads(
        (ROOT / "backend" / "rs_overlays" / "manifest.json").read_text(encoding="utf-8")
    )
    layer = next(l for l in manifest["layers"] if l["id"] == "chla")
    by_year = {entry["year"]: entry for entry in layer["years"]}
    return layer, by_year


def colorbar_lut(stops: list, vmin: float, vmax: float, steps: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    fractions = np.linspace(0.0, 1.0, steps)
    colors = np.zeros((steps, 3), dtype=np.float64)
    palette = [(float(t), tuple(int(c[i : i + 2], 16) for i in (1, 3, 5))) for t, c in stops]
    for i, frac in enumerate(fractions):
        for (t0, c0), (t1, c1) in zip(palette[:-1], palette[1:]):
            if t0 <= frac <= t1:
                w = 0.0 if t1 == t0 else (frac - t0) / (t1 - t0)
                colors[i] = np.array(c0) * (1 - w) + np.array(c1) * w
                break
        else:
            colors[i] = palette[-1][1]
    return colors, np.linspace(vmin, vmax, steps)


def invert_png(path: Path, lut_colors: np.ndarray, lut_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    image = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)
    rgb, alpha = image[..., :3], image[..., 3]
    flat = rgb.reshape(-1, 3)
    unique, inverse = np.unique(flat, axis=0, return_inverse=True)
    idx = np.empty(len(unique), dtype=np.int64)
    chunk = max(1, int(4_000_000 / max(len(lut_colors), 1)))
    for start in range(0, len(unique), chunk):
        block = unique[start : start + chunk]
        d2 = (
            np.sum(block**2, axis=1)[:, None]
            - 2.0 * block @ lut_colors.T
            + np.sum(lut_colors**2, axis=1)[None, :]
        )
        idx[start : start + chunk] = np.argmin(d2, axis=1)
    values = lut_values[idx[inverse.reshape(rgb.shape[:2])]]
    valid = alpha >= 128
    return values, valid


def render_png(values: np.ndarray, valid: np.ndarray, lut_colors: np.ndarray, lut_values: np.ndarray, path: Path) -> None:
    grid = values
    indices = np.clip(
        np.searchsorted(lut_values, grid, side="right") - 1, 0, len(lut_values) - 1
    )
    rgb = lut_colors[indices].astype(np.uint8)
    rgba = np.dstack([rgb, np.where(valid, 255, 0).astype(np.uint8)])
    Image.fromarray(rgba, mode="RGBA").save(path)


def polygon_area_km2(coords: list) -> float:
    """等经纬近似面积（赤道度→公里，按多边形平均纬度缩放），结果为近似值并披露。"""
    lons = np.array([p[0] for p in coords])
    lats = np.array([p[1] for p in coords])
    lat_mean = float(lats.mean())
    x = lons * 111.320 * np.cos(np.radians(lat_mean))
    y = lats * 110.574
    if len(x) < 3:
        return 0.0
    return abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2.0)


def build_boundary(values: np.ndarray, valid: np.ndarray, bounds, threshold: float) -> tuple[dict, float]:
    lat_min, lon_min = bounds[0]
    lat_max, lon_max = bounds[1]
    height, width = values.shape
    transform = from_bounds(lon_min, lat_min, lon_max, lat_max, width, height)
    mask = (values >= threshold) & valid
    if not mask.any():
        return {"type": "FeatureCollection", "features": []}, 0.0
    shapes = features.shapes(
        mask.astype(np.uint8), mask=mask, transform=transform, connectivity=8
    )
    feature_list, total_area = [], 0.0
    for geom, _value in shapes:
        polygons = geom["coordinates"] if geom["type"] == "Polygon" else []
        area = sum(polygon_area_km2(ring) for ring in polygons)
        total_area += area
        feature_list.append({
            "type": "Feature",
            "properties": {"threshold_ug_l": threshold, "area_km2_approx": round(area, 3)},
            "geometry": geom,
        })
    return {"type": "FeatureCollection", "features": feature_list}, round(total_area, 3)


def load_anchors() -> pd.DataFrame:
    """月度锚点：地面站点 chla（ground_truth）+ CLMS 湖泊月均（remote_retrieval）。"""
    tables = clean_tables_dir()
    anchors = []
    wq = pd.read_parquet(tables / "water_quality.parquet")
    wq = wq[(wq["is_ground_truth"] == True) & (wq["variable_code"] == "chla")]  # noqa: E712
    wq = wq.assign(
        station_id=wq["aux"].map(
            lambda a: json.loads(a).get("station_id") if isinstance(a, str) else None
        )
    )
    wq["month"] = pd.to_datetime(wq["observed_at"]).dt.strftime("%Y-%m")
    md = pd.read_parquet(tables / "model_dataset.parquet")
    coords = (
        md.groupby("station_id")[["static_station_longitude", "static_station_latitude"]]
        .first()
    )
    for (station, month), group in wq.groupby(["station_id", "month"]):
        lon = float(coords.loc[station, "static_station_longitude"])
        lat = float(coords.loc[station, "static_station_latitude"])
        anchors.append({
            "month": month, "kind": "station_ground_truth",
            "station_id": station, "lon": lon, "lat": lat,
            "chla_ug_l": float(pd.to_numeric(group["value"], errors="coerce").mean()),
            "provenance": "ground_truth",
        })
    rs = pd.read_parquet(tables / "remote_sensing.parquet")
    clms = rs[rs["variable_code"] == "chla_mean"].copy()
    clms["month"] = pd.to_datetime(clms["observed_at"]).dt.strftime("%Y-%m")
    for month, group in clms.groupby("month"):
        anchors.append({
            "month": month, "kind": "clms_lake_mean",
            "station_id": "TAIHU_LAKE", "lon": LAKE_CENTROID[0], "lat": LAKE_CENTROID[1],
            "chla_ug_l": float(pd.to_numeric(group["value"], errors="coerce").mean()),
            "provenance": "remote_retrieval",
        })
    return pd.DataFrame(anchors)


def idw_correction(
    base: np.ndarray, valid: np.ndarray, bounds, anchors: pd.DataFrame
) -> np.ndarray:
    lat_min, lon_min = bounds[0]
    lat_max, lon_max = bounds[1]
    height, width = base.shape
    lons = np.linspace(lon_min, lon_max, width)
    lats = np.linspace(lat_max, lat_min, height)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    correction = np.zeros_like(base)
    weight_sum = np.zeros_like(base)
    for anchor in anchors.itertuples(index=False):
        dist2 = (lon_grid - anchor.lon) ** 2 + (lat_grid - anchor.lat) ** 2
        dist2 = np.maximum(dist2, 1e-8)
        col = int(np.clip(np.searchsorted(lons, anchor.lon), 0, width - 1))
        row = int(np.clip(np.searchsorted(-lats[::-1], -anchor.lat), 0, height - 1))
        row = int(np.clip(np.argmin(np.abs(lats - anchor.lat)), 0, height - 1))
        col = int(np.clip(np.argmin(np.abs(lons - anchor.lon)), 0, width - 1))
        base_at_anchor = base[row, col]
        residual = anchor.chla_ug_l - base_at_anchor
        weight = 1.0 / dist2
        weight = np.where(valid, weight, 0.0)
        correction += residual * weight
        weight_sum += weight
    with np.errstate(invalid="ignore", divide="ignore"):
        field = np.where(weight_sum > 0, correction / np.maximum(weight_sum, 1e-12), 0.0)
    return base + field


def main() -> dict:
    layer, by_year = load_annual_manifest()
    vmin, vmax = float(layer["vmin"]), float(layer["vmax"])
    bounds = layer["years"][0]["bounds"]
    lut_colors, lut_values = colorbar_lut(layer["legend_stops"], vmin, vmax)
    anchors = load_anchors()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    boundaries_dir = OUT_DIR / "boundaries"
    boundaries_dir.mkdir(exist_ok=True)

    layers = []
    for month in sorted(anchors["month"].unique()):
        year = int(month[:4])
        if year not in by_year:
            year = min(by_year, key=lambda y: abs(y - int(month[:4])))
        entry = by_year[year]
        base, valid = invert_png(ROOT / "backend" / "rs_overlays" / entry["png"], lut_colors, lut_values)
        month_anchors = anchors[anchors["month"] == month]
        corrected = idw_correction(base, valid, bounds, month_anchors)
        corrected = np.maximum(corrected, 0.0)
        # 校准证据：基底在锚点处 vs 观测
        base_at_anchor, observed = [], []
        lats = np.linspace(bounds[1][0], bounds[0][0], base.shape[0])
        lons = np.linspace(bounds[0][1], bounds[1][1], base.shape[1])
        for anchor in month_anchors.itertuples(index=False):
            row = int(np.argmin(np.abs(lats - anchor.lat)))
            col = int(np.argmin(np.abs(lons - anchor.lon)))
            if valid[row, col]:
                base_at_anchor.append(float(base[row, col]))
                observed.append(float(anchor.chla_ug_l))
        calibration = {"pair_count": len(observed), "r2": None, "rmse": None, "status": "annual_base_only"}
        if observed:
            obs_arr, base_arr = np.asarray(observed), np.asarray(base_at_anchor)
            ss_tot = float(np.sum((obs_arr - obs_arr.mean()) ** 2))
            residual = obs_arr - base_arr
            calibration = {
                "pair_count": len(observed),
                "r2": None if ss_tot == 0 else round(float(1 - np.sum(residual**2) / ss_tot), 4),
                "rmse": round(float(np.sqrt(np.mean(residual**2))), 4),
                "status": "calibrated",
                "anchor_provenance": sorted(set(month_anchors["provenance"].tolist())),
            }
        png_rel = f"monthly_v3/chla_{month}.png"
        render_png(corrected, valid, lut_colors, lut_values, ROOT / "backend" / "rs_overlays" / png_rel)
        boundary, area = build_boundary(corrected, valid, bounds, BLOOM_THRESHOLD)
        geojson_rel = f"monthly_v3/boundaries/chla_{month}.geojson"
        (ROOT / "backend" / "rs_overlays" / geojson_rel).write_text(
            json.dumps(boundary, ensure_ascii=False), encoding="utf-8"
        )
        layers.append({
            "month": month,
            "year_base": int(year),
            "png": png_rel,
            "boundary_geojson": geojson_rel,
            "bounds": bounds,
            "vmin": vmin,
            "vmax": vmax,
            "unit": layer["unit"],
            "boundary": {"threshold_ug_l": BLOOM_THRESHOLD, "area_km2": area,
                          "feature_count": len(boundary["features"])},
            "calibration": calibration,
            "anchor_count": int(len(month_anchors)),
            "spatial_method": "calibrated_annual_product_plus_station_residual",
        })
        print(f"[raster] {month} anchors={len(month_anchors)} calib={calibration} bloom_area={area}km2")
    manifest = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "source": "THQBCA-V2 2.Bio-optics 年度 30m 反演产品 + 站点月度 chla 观测残差修正",
        "spatial_method": "calibrated_annual_product_plus_station_residual",
        "claim_boundary": "half_empirical_monthly_field_retrieval_proxy",
        "colorbar_inversion_note": (
            "年度 PNG 色标为全期固定尺度（0-60 μg/L，5 段线性渐变），按最近邻颜色线性反解像元值，"
            "存在 8-bit 量化误差；修正场仅用于连续空间格局展示，不替代站点实测。"
        ),
        "idw_note": "锚点残差按 1/d² 反距离加权扩散；无锚点月不出图（不虚构）。",
        "bloom_threshold_ug_l": BLOOM_THRESHOLD,
        "layers": layers,
    }
    (OUT_DIR / "raster_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[raster] layers={len(layers)} → raster_manifest.json")
    return manifest


if __name__ == "__main__":
    main()
