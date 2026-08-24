# -*- coding: utf-8 -*-
"""静态空间特征清洗: 湖泊/流域/站点 的 DEM 高程、坡度、ESA 土地覆盖、HydroLAKES 属性。

数据源(原始):
- 边界: storage/silver/geo/taihu_boundary.gpkg (HydroLAKES Taihu)
- DEM: storage/silver/geo/copernicus_dem_glo30_taihu.tif (+slope)、storage/raw/static_geo/copernicus_dem_glo30/*
- 土地覆盖: storage/silver/geo/worldcover_2021_taihu.tif、storage/raw/static_geo/esa_worldcover_2021_v200/*
- 流域: storage/staging/hydrobasins/hybas_as_lev08_v1c.zip
- 湖泊属性: storage/raw/geo/hydrolakes/asia/HydroLAKES_Asia.shp (Taihu 记录)
- 站点: 有坐标的站点(NASA POWER 格点等)

输出: storage/cleaned/static_features_cleaned.csv (+ .parquet), 长表(每行=一个特征)
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, ROOT, STORAGE, bnow, flag_join, write_dataset

BOUNDARY = STORAGE / "silver/geo/taihu_boundary.gpkg"
DEM_CLIP = STORAGE / "silver/geo/copernicus_dem_glo30_taihu.tif"
SLOPE_CLIP = STORAGE / "silver/geo/copernicus_dem_glo30_taihu_slope.tif"
WC_CLIP = STORAGE / "silver/geo/worldcover_2021_taihu.tif"
DEM_RAW = STORAGE / "raw/static_geo/copernicus_dem_glo30"
WC_RAW = STORAGE / "raw/static_geo/esa_worldcover_2021_v200"
HYBAS_ZIP = STORAGE / "raw/hydrobasins/hybas_as_lev08_v1c.zip"
HLAKES = STORAGE / "raw/geo/hydrolakes/asia/HydroLAKES_Asia.shp"

ESA_CLASSES = {
    10: "tree", 20: "shrubland", 30: "grassland", 40: "cropland", 50: "built_up",
    60: "bare_sparse", 70: "snow_ice", 80: "permanent_water", 90: "herbaceous_wetland",
    95: "mangroves", 100: "moss_lichen",
}


def _mask_stats(files: list[Path], geom, var_scale: str = "elevation_m", units="m") -> dict:
    """对多个栅格(通常 clip + 原始块)在 geom 内做窗口统计, 返回 stats + 覆盖文件。"""
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.warp import transform_geom
    import fiona
    out: dict = {}
    src_used = None
    for p in files:
        if not p.exists():
            continue
        try:
            with rasterio.open(p) as ds:
                crs_from = "EPSG:4326"
                g = transform_geom(crs_from, ds.crs, geom)
                arr = rio_mask(ds, [g], crop=True, filled=True, nodata=np.float32(ds.nodata) if ds.nodata is not None else np.nan)[0].astype("float32")
        except Exception as e:
            continue
        if hasattr(ds, "nodata") and ds.nodata is not None:
            arr[arr == np.float32(ds.nodata)] = np.nan
        arr[(arr < -1e18) | (arr > 1e18)] = np.nan
        v = arr[(arr > -1e6) & np.isfinite(arr)]
        if v.size < 100:
            continue
        src_used = p
        out = dict(mean=float(np.nanmean(v)), median=float(np.nanmedian(v)),
                   std=float(np.nanstd(v)), min=float(np.nanmin(v)), max=float(np.nanmax(v)),
                   valid_frac=float(v.size / arr.size), n_pixels=int(v.size))
        break
    return {**out, "source_file": str(src_used.relative_to(ROOT)) if src_used else ""}


def _landcover_shares(files: list[Path], geom) -> dict:
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.warp import transform_geom
    shares = {c: np.nan for c in ESA_CLASSES.values()}
    src_used = ""
    for p in files:
        if not p.exists():
            continue
        try:
            with rasterio.open(p) as ds:
                g = transform_geom("EPSG:4326", ds.crs, geom)
                arr = rio_mask(ds, [g], crop=True, filled=True, nodata=255)[0]
            nod = ds.nodata
            if nod is not None:
                arr = arr[(arr != nod)]
            else:
                arr = arr[arr != 255]
            if arr.size < 100:
                continue
            src_used = p
        except Exception:
            continue
        vals, counts = np.unique(arr, return_counts=True)
        for cls_id, counts_i in zip(vals, counts):
            name = ESA_CLASSES.get(int(cls_id))
            if name:
                shares[name] = float(counts_i / arr.size)
        break
    return shares


def _read_boundary():
    import fiona
    with fiona.open(BOUNDARY) as src:
        feat = next(iter(src))
        from shapely.geometry import shape
        return feat["geometry"], shape(feat["geometry"]), dict(feat["properties"])


def _taihu_hydrolakes_record() -> dict:
    """HydroLAKES Asia shp 中检索太湖记录(含深度/面积等属性)。"""
    import fiona
    with fiona.open(HLAKES) as src:
        schema_fields = list(src.schema["properties"].keys())
        idx = None
        for i, f in enumerate(src):
            props = f["properties"]
            name = str(props.get("Lake_name", props.get("lake_name", "")))
            if "taihu" in name.lower() or str(props.get("Hylak_id", props.get("hylak_id", ""))) == "27":
                idx = i
                break
        if idx is None:
            return {"found": False, "fields": schema_fields[:40]}
        import fiona
        with fiona.open(HLAKES) as src:
            for i, f in enumerate(src):
                if i == idx:
                    p = dict(f["properties"])
                    out = {"found": True, "fields": []}
                    for k in sorted(p.keys(), key=str.lower):
                        v = p[k]
                        if isinstance(v, (int, float, str)):
                            out[f"hylakes_{k}"] = v
                    return out


def main() -> pd.DataFrame:
    print("== 静态特征清洗 ==")
    geom, lake_geom, props = _read_boundary()
    rows: list[dict] = []

    def add(entity_type, entity_id, feature, value, unit, source, note="", flags=None, file=None):
        rows.append(dict(
            entity_type=entity_type, entity_id=entity_id, feature_name=feature,
            value=value, unit=unit, quality_flag=flag_join(flags or []),
            quality_note=note, source_name=source, source_file=file or "",
            acquisition_date=bnow().strftime("%Y-%m-%d %H:%M:%S"),
        ))

    # ---- 湖泊层 ----
    add("lake", "TAIHU", "area_km2_calc", props.get("area_km2_calc", np.nan), "km²", "taihu_boundary_gpkg",
        note="边界计算面积")
    for k in ("source_area_km2", "area_km2_calc"):
        if k in props:
            add("lake", "TAIHU", f"boundary_{k}", props[k], "km²", "taihu_boundary_gpkg")
    hydl = _taihu_hydrolakes_record()
    if hydl.get("found"):
        for k, v in hydl.items():
            if k in ("found", "fields"):
                continue
            add("lake", "TAIHU", k, v, "", "hydrolakes_asia",
                note="HydroLAKES 属性(单位随字段定义, 见 lake_dataset 文档)")
    else:
        add("lake", "TAIHU", "hydrolakes_record_status", 0, "", "hydrolakes_asia",
            note=f"HydroLAKES 检索失败/未找到太湖记录, schema={hydl.get('fields')[:10]}", flags=["Q12"])

    dem_files = [DEM_CLIP, *sorted(DEM_RAW.glob("*.tif"))]
    wc_files = [WC_CLIP, *sorted(WC_RAW.glob("*.tif"))]
    ds = _mask_stats(dem_files, geom)
    add("lake", "TAIHU", "elevation_mean_m", ds.get("mean"), "m", "copernicus_dem_glo30",
        note="湖泊边界内 GLO-30 高程", file=ds.get("source_file"))
    for k in ("median", "std", "min", "max"):
        add("lake", "TAIHU", f"elevation_{k}_m", ds.get(k), "m", "copernicus_dem_glo30",
            note="湖泊边界内 GLO-30 高程")
    add("lake", "TAIHU", "dem_valid_frac", ds.get("valid_frac"), "fraction", "copernicus_dem_glo30")
    lc = _landcover_shares(wc_files, geom)
    for cls, share in lc.items():
        add("lake", "TAIHU", f"landcover_{cls}_pct", share, "%", "esa_worldcover_2021",
            note="ESA WorldCover 2021 类别占比, 样本为湖盆边界内像元")

    # ---- 流域层 ----
    basin_records = []
    try:
        import fiona
        tmp = None
        if HYBAS_ZIP.exists():
            with zipfile.ZipFile(HYBAS_ZIP) as zf:
                shp_names = [n for n in zf.namelist() if n.endswith(".shp")]
                dest = CLEANED / ".cache/hydrobasins_extract"
                if shp_names and not (dest / shp_names[0]).exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    zf.extractall(dest)
                if shp_names:
                    tmp = dest / shp_names[0]
        if tmp and tmp.exists():
            from shapely.geometry import shape as to_shapely
            b = lake_geom.bounds
            bbox = (b[0] - 0.5, b[1] - 0.5, b[2] + 0.5, b[3] + 0.5)
            # fiona 对 shapefile 忽略 bbox 过滤, 手动按包围盒预筛
            with fiona.open(tmp) as src:
                for f in src:
                    props_b = dict(f["properties"])
                    g = to_shapely(f["geometry"])
                    gb = g.bounds
                    if gb[0] > bbox[2] or gb[2] < bbox[0] or gb[1] > bbox[3] or gb[3] < bbox[1]:
                        continue
                    basin_records.append((str(props_b.get("HYBAS_ID", props_b.get("hybas_id", f.get("id")))), g, props_b))
    except Exception as e:
        print(f"  [流域] 读取失败: {e}")
    print(f"  [流域] 读取 {len(basin_records)} 个 basins")
    from shapely.geometry import Point
    for bid, g, props_b in basin_records:
        area = props_b.get("SUB_AREA", props_b.get("sub_area"))
        add("basin", f"HYBAS_{bid}", "area_km2", area, "km²", "hydrobasins_lev08",
            note="HydroBASINS 汇水区域面积(SUB_AREA 单位 km²)")
        centroid = g.representative_point()
        from shapely.ops import nearest_points
        try:
            npt = nearest_points(g, lake_geom)[1]
            d_km = _haversine_km(npt.x, npt.y, centroid.x, centroid.y)
        except Exception:
            d_km = np.nan
        add("basin", f"HYBAS_{bid}", "distance_to_taihu_boundary_km", d_km, "km", "hydrobasins_lev08",
            note="流域质心到太湖边界距离(球面近似)")
        bds = _mask_stats(dem_files, g.__geo_interface__)
        add("basin", f"HYBAS_{bid}", "elevation_mean_m", bds.get("mean"), "m", "copernicus_dem_glo30",
            file=bds.get("source_file"))
        for k in ("median", "std", "min", "max"):
            add("basin", f"HYBAS_{bid}", f"elevation_{k}_m", bds.get(k), "m", "copernicus_dem_glo30",
                file=bds.get("source_file"))
        add("basin", f"HYBAS_{bid}", "elevation_valid_frac", bds.get("valid_frac"), "fraction",
            "copernicus_dem_glo30")
        blc = _landcover_shares(wc_files, g.__geo_interface__)
        for cls, share in blc.items():
            add("basin", f"HYBAS_{bid}", f"landcover_{cls}_pct", share, "%", "esa_worldcover_2021")

    # ---- 站点层 ----
    station_points = [
        ("NASA_POWER_120.300_31.200", "NASA POWER 格点(湖心附近)", 120.3, 31.2),
    ]
    # 现场采样点也加入站点静态(坐标来自实测)
    try:
        fsc = pd.read_csv(CLEANED / "field_samples_cleaned.csv", encoding="utf-8-sig")
        for _, r in fsc.iterrows():
            if pd.notna(r.get("longitude")) and pd.notna(r.get("latitude")):
                station_points.append((f"IN_SITU_{round(r['longitude'], 4)}_{round(r['latitude'], 4)}",
                                       "现场采样点", r["longitude"], r["latitude"]))
    except Exception:
        pass
    from shapely.geometry import Point as ShapelyPoint
    for sid, sname, lon, lat in station_points:
        pt = ShapelyPoint(lon, lat)
        add("station", sid, "longitude", lon, "°E", "station_coordinates")
        add("station", sid, "latitude", lat, "°N", "station_coordinates")
        inside = lake_geom.contains(pt)
        add("station", sid, "inside_lake", 1 if inside else 0, "flag", "taihu_boundary_gpkg")
        dem_files2 = [DEM_CLIP, *sorted(DEM_RAW.glob("*.tif"))]
        found = False
        for p in dem_files2:
            if not p.exists():
                continue
            import rasterio
            try:
                with rasterio.open(p) as ds:
                    from rasterio.warp import transform_geom
                    g = transform_geom("EPSG:4326", ds.crs, pt.__geo_interface__)
                    x, y = g["coordinates"][0]
                    vals = list(ds.sample([(x, y)]))
                    v = vals[0][0]
                    if v is not None and not np.isnan(float(v)):
                        found = True
                        add("station", sid, "elevation_m", float(v), "m", "copernicus_dem_glo30", file=str(p.relative_to(ROOT)))
                        break
            except Exception:
                continue
        if not found:
            add("station", sid, "elevation_m", np.nan, "m", "copernicus_dem_glo30", note="无覆盖")
        # landcover
        for p in wc_files:
            if not p.exists():
                continue
            import rasterio
            try:
                with rasterio.open(p) as ds:
                    from rasterio.warp import transform_geom
                    g = transform_geom("EPSG:4326", ds.crs, pt.__geo_interface__)
                    x, y = g["coordinates"][0]
                    v = int(list(ds.sample([(x, y)]))[0][0])
                    name = ESA_CLASSES.get(v, str(v))
                    add("station", sid, f"landcover_class_{v}", name, "category", "esa_worldcover_2021",
                        note=f"ESA class {v}", file=str(p.relative_to(ROOT)))
                    break
            except Exception:
                continue

    df = pd.DataFrame(rows)
    path = write_dataset(df, "static_features_cleaned")
    print(f"  [输出] {path}  {df.shape[0]} 行 x {df.shape[1]} 列; "
          f"实体数: {df.groupby('entity_type').size().to_dict() if len(df) else {}}")
    return df


def _haversine_km(lon1, lat1, lon2, lat2) -> float:
    from math import asin, cos, radians, sin, sqrt
    R = 6371.0
    la1, lo1, la2, lo2 = map(radians, (lat1, lon1, lat2, lon2))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * R * asin(sqrt(h))


if __name__ == "__main__":
    main()
