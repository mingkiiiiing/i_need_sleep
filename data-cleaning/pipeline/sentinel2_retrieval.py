from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np


def _write_float(path: Path, data: np.ndarray, profile: dict[str, Any]) -> None:
    import rasterio

    output = np.where(np.isfinite(data), data, -9999.0).astype("float32")
    target_profile = profile.copy()
    target_profile.update(driver="GTiff", dtype="float32", count=1, nodata=-9999.0, compress="deflate", tiled=True)
    with rasterio.open(path, "w", **target_profile) as target:
        target.write(output, 1)


def run_sentinel2_retrieval(scene_root: Path, boundary_path: Path, calibration_model: Path, output_root: Path) -> dict[str, Any]:
    import fiona
    import pandas as pd
    import rasterio
    from rasterio.features import rasterize
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import Resampling, transform_geom
    from shapely.geometry import box, shape

    output_root.mkdir(parents=True, exist_ok=True)
    with rasterio.open(scene_root / "rededge1.tif") as reference:
        profile = reference.profile.copy()
        re1 = reference.read(1).astype("float32") / 10000.0
        arrays = {"rrs_rededge_705": re1}
        mapping = {"rrs_green_560": "green", "rrs_red_665": "red", "rrs_nir_842": "nir", "swir16": "swir16", "scl": "scl"}
        for name, asset in mapping.items():
            with rasterio.open(scene_root / f"{asset}.tif") as source:
                resampling = Resampling.nearest if asset == "scl" else Resampling.bilinear
                with WarpedVRT(source, crs=reference.crs, transform=reference.transform, width=reference.width, height=reference.height, resampling=resampling) as vrt:
                    values = vrt.read(1).astype("float32")
                    arrays[name] = values if asset == "scl" else values / 10000.0
        with fiona.open(boundary_path, layer="taihu_boundary_wgs84") as layer:
            feature = next(iter(layer))
            geometry = transform_geom(layer.crs, reference.crs, feature["geometry"])
        boundary_geometry = shape(geometry)
        footprint = box(*reference.bounds)
        footprint_fraction = float(boundary_geometry.intersection(footprint).area / boundary_geometry.area) if boundary_geometry.area else 0.0
        lake_mask = rasterize([(geometry, 1)], out_shape=(reference.height, reference.width), transform=reference.transform, fill=0, dtype="uint8").astype(bool)
        scl = arrays["scl"]
        valid = lake_mask & (scl == 6)
        for name in ("rrs_green_560", "rrs_red_665", "rrs_rededge_705", "rrs_nir_842", "swir16"):
            valid &= np.isfinite(arrays[name]) & (arrays[name] > 0)
        green, red, rededge, nir, swir = (arrays[name] for name in ("rrs_green_560", "rrs_red_665", "rrs_rededge_705", "rrs_nir_842", "swir16"))
        with np.errstate(divide="ignore", invalid="ignore"):
            ndci = (rededge - red) / (rededge + red)
            mci = rededge - red - (nir - red) * ((705 - 665) / (842 - 665))
            fai = nir - (red + (swir - red) * ((842 - 665) / (1610 - 665)))
            ndwi = (green - nir) / (green + nir)
        for array in (ndci, mci, fai, ndwi):
            array[~valid] = np.nan
        package = joblib.load(calibration_model)
        model_features = {
            "ndci_field": ndci, "mci_field": mci, "rrs_green_560": green,
            "rrs_red_665": red, "rrs_rededge_705": rededge, "rrs_nir_842": nir,
        }
        positions = np.where(valid)
        x = np.column_stack([model_features[name][positions] for name in package["features"]])
        chlorophyll = np.full(ndci.shape, np.nan, dtype="float32")
        chlorophyll[positions] = np.maximum(0.0, package["model"].predict(x)).astype("float32")
        out_of_domain = np.zeros(len(x), dtype=bool)
        for index, name in enumerate(package["features"]):
            limits = package.get("feature_ranges", {}).get(name)
            if limits:
                out_of_domain |= (x[:, index] < limits["min"]) | (x[:, index] > limits["max"])
        bloom = valid & (fai > 0.004)
        pixel_area_km2 = abs(reference.transform.a * reference.transform.e) / 1_000_000.0
        files = {}
        for name, data in {"ndci": ndci, "mci": mci, "fai": fai, "ndwi": ndwi, "chlorophyll_a_experimental_ug_l": chlorophyll}.items():
            path = output_root / f"{name}.tif"
            _write_float(path, data, profile)
            files[name] = str(path)
    summary = {
        "scene_root": str(scene_root), "lake_footprint_coverage_fraction": footprint_fraction,
        "valid_water_pixels": int(valid.sum()), "valid_pixel_fraction_within_rasterized_lake": float(valid.sum() / lake_mask.sum()) if lake_mask.sum() else 0.0,
        "bloom_pixels_fai_gt_0_004": int(bloom.sum()), "bloom_area_partial_km2": float(bloom.sum() * pixel_area_km2),
        "chlorophyll_mean_experimental_ug_l": float(np.nanmean(chlorophyll)) if np.isfinite(chlorophyll).any() else None,
        "model_domain_exceedance_fraction": float(out_of_domain.mean()) if len(out_of_domain) else None,
        "calibration_status": package["audit"]["status"], "uncertainty_residual_std_ug_l": package["audit"]["uncertainty_residual_std_ug_l"],
        "operational_use": False, "reason": "single-tile partial coverage and low-generalization field-spectral transfer calibration",
    }
    summary_path, manifest_path = output_root / "scene_summary.csv", output_root / "manifest.json"
    pd.DataFrame([summary]).to_csv(summary_path, index=False, encoding="utf-8-sig")
    manifest = {"status": "experimental_not_operational", **summary, "files": {**files, "summary": str(summary_path)}, "manifest": str(manifest_path)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
