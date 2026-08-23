from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
RASTER_ROOT = ROOT / "storage" / "rasters" / "sentinel2_monthly_30m_cdse"


def write_float(path: Path, values: np.ndarray, profile: dict) -> None:
    output = np.where(np.isfinite(values), values, -9999.0).astype("float32")
    target_profile = profile.copy()
    target_profile.update(count=1, dtype="float32", nodata=-9999.0, compress="deflate", tiled=True, blockxsize=512, blockysize=512)
    with rasterio.open(path, "w", **target_profile) as target:
        target.write(output, 1)


def main() -> None:
    rows = []
    for month_root in sorted(path for path in RASTER_ROOT.iterdir() if path.is_dir()):
        month = month_root.name
        paths = {band: month_root / f"taihu_s2_l2a_{month}_{band}_30m.tif" for band in ("B03", "B04", "B05", "B08", "B11", "SCL")}
        if not all(path.exists() for path in paths.values()):
            rows.append({"month": month, "status": "missing_source_band"})
            continue
        arrays = {}
        profile = None
        for band, path in paths.items():
            with rasterio.open(path) as source:
                arrays[band] = source.read(1).astype("float32")
                profile = source.profile.copy()
        clear = (~np.isin(arrays["SCL"], [0, 1, 3, 7, 8, 9, 10, 11]))
        for band in ("B03", "B04", "B05", "B08", "B11"):
            clear &= arrays[band] > 0
            arrays[band] /= 10000.0
        green, red, rededge, nir, swir = (arrays[name] for name in ("B03", "B04", "B05", "B08", "B11"))
        with np.errstate(divide="ignore", invalid="ignore"):
            indices = {
                "NDCI": (rededge - red) / (rededge + red),
                "MCI": rededge - red - (nir - red) * ((705.0 - 665.0) / (842.0 - 665.0)),
                "FAI": nir - (red + (swir - red) * ((842.0 - 665.0) / (1610.0 - 665.0))),
                "NDWI": (green - nir) / (green + nir),
            }
        for name, values in indices.items():
            values[~clear] = np.nan
            write_float(month_root / f"taihu_s2_l2a_{month}_{name}_30m.tif", values, profile)
        rows.append({"month": month, "status": "completed", "clear_pixels": int(clear.sum()), "clear_fraction_of_grid": float(clear.mean())})
        print(month, rows[-1]["status"], flush=True)
    output = RASTER_ROOT / "sentinel2_monthly_indices_inventory.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month", "status", "clear_pixels", "clear_fraction_of_grid"])
        writer.writeheader()
        writer.writerows(rows)
    print(output)


if __name__ == "__main__":
    main()
