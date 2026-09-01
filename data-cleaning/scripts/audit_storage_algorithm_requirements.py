from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATE_HINTS = ("date", "time", "issue", "valid", "target")
CRITICAL_HINTS = (
    "bloom", "chla", "chlorophyll", "algae", "cyan", "label", "target",
    "water_temp", "water_temperature", "quality", "flag", "source_file",
    "spatial", "station", "latitude", "longitude", "forecast", "lead",
)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def profile_table(path: Path, root_label: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "root": root_label,
        "path": str(path),
        "exists": path.exists(),
        "readable": False,
    }
    if not path.exists():
        return result
    try:
        df = read_table(path)
    except Exception as exc:  # audit must continue across corrupt assets
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result.update({
        "readable": True,
        "rows": int(len(df)),
        "columns_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "exact_duplicate_rows": int(df.duplicated().sum()),
    })

    date_ranges: dict[str, Any] = {}
    critical: dict[str, Any] = {}
    for col in df.columns:
        name = str(col)
        lower = name.lower()
        series = df[col]
        if any(h in lower for h in DATE_HINTS):
            parsed = pd.to_datetime(series, errors="coerce", utc=True)
            valid = parsed.notna()
            if valid.any():
                date_ranges[name] = {
                    "valid": int(valid.sum()),
                    "null_or_invalid": int((~valid).sum()),
                    "min": parsed[valid].min().isoformat(),
                    "max": parsed[valid].max().isoformat(),
                }
        if any(h in lower for h in CRITICAL_HINTS):
            item: dict[str, Any] = {
                "dtype": str(series.dtype),
                "nonnull": int(series.notna().sum()),
                "null_rate": float(series.isna().mean()) if len(df) else None,
                "distinct": int(series.nunique(dropna=True)),
            }
            if series.nunique(dropna=True) <= 20:
                counts = series.astype("string").fillna("<NA>").value_counts(dropna=False).head(20)
                item["value_counts"] = {str(k): int(v) for k, v in counts.items()}
            elif pd.api.types.is_numeric_dtype(series):
                vals = pd.to_numeric(series, errors="coerce").dropna()
                if not vals.empty:
                    item["numeric"] = {
                        "min": float(vals.min()),
                        "median": float(vals.median()),
                        "max": float(vals.max()),
                        "zero_count": int((vals == 0).sum()),
                    }
            critical[name] = item

    result["date_ranges"] = date_ranges
    result["critical_columns"] = critical

    date_col = next((c for c in df.columns if str(c).lower() in {"date", "issue_time", "prediction_date", "forecast_reference_time"}), None)
    target_col = next((c for c in df.columns if str(c).lower() in {"target_date", "valid_time", "label_date"}), None)
    if date_col is not None and target_col is not None:
        d0 = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        d1 = pd.to_datetime(df[target_col], errors="coerce", utc=True)
        comparable = d0.notna() & d1.notna()
        result["future_target_check"] = {
            "comparable": int(comparable.sum()),
            "strictly_future": int((d1[comparable] > d0[comparable]).sum()),
            "not_future": int((d1[comparable] <= d0[comparable]).sum()),
        }
    return result


def file_inventory(path: Path) -> dict[str, Any]:
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    sizes = [p.stat().st_size for p in files]
    names = [p.name for p in files]
    date_tokens: list[str] = []
    for name in names:
        for match in re.finditer(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)", name):
            y, m, d = match.groups()
            try:
                date_tokens.append(pd.Timestamp(f"{y}-{m}-{d}").date().isoformat())
            except ValueError:
                pass
    return {
        "path": str(path),
        "exists": path.exists(),
        "files": len(files),
        "bytes": int(sum(sizes)),
        "zero_byte_files": int(sum(s == 0 for s in sizes)),
        "small_files_under_1kb": int(sum(s < 1024 for s in sizes)),
        "filename_date_min": min(date_tokens) if date_tokens else None,
        "filename_date_max": max(date_tokens) if date_tokens else None,
        "dated_files": len(date_tokens),
        "extensions": dict(pd.Series([p.suffix.lower() or "<none>" for p in files], dtype="string").value_counts().to_dict()) if files else {},
    }


def sample_asset(path: Path) -> dict[str, Any]:
    result = {"path": str(path), "readable": False}
    try:
        suffix = path.suffix.lower()
        if suffix in {".tif", ".tiff"}:
            import rasterio
            with rasterio.open(path) as ds:
                arr = ds.read(1, masked=True)
                result.update({
                    "readable": True,
                    "driver": ds.driver,
                    "shape": [ds.height, ds.width],
                    "bands": ds.count,
                    "crs": str(ds.crs),
                    "valid_pixels": int(arr.count()),
                    "total_pixels": int(arr.size),
                })
        elif suffix == ".nc":
            import xarray as xr
            with xr.open_dataset(path, decode_times=False) as ds:
                result.update({
                    "readable": True,
                    "variables": list(ds.data_vars),
                    "coordinates": list(ds.coords),
                    "dimensions": {str(k): int(v) for k, v in ds.sizes.items()},
                })
        elif suffix in {".hdf", ".h5", ".hdf5"}:
            import h5py
            with h5py.File(path, "r") as handle:
                result.update({"readable": True, "top_level": list(handle.keys())})
        else:
            with path.open("rb") as handle:
                handle.read(64)
            result["readable"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-root", type=Path, required=True)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    table_specs = [
        ("new", args.new_root / "cleaned/model_dataset_monthly.parquet"),
        ("new", args.new_root / "cleaned/water_quality_cleaned.parquet"),
        ("new", args.new_root / "cleaned/field_samples_cleaned.parquet"),
        ("new", args.new_root / "cleaned/clms_lwq_10daily_cleaned.parquet"),
        ("new", args.new_root / "cleaned/c3s_seasonal_cleaned.parquet"),
        ("new", args.new_root / "cleaned/noaa_gfs_cleaned.parquet"),
        ("new", args.new_root / "cleaned/remote_sensing_monthly_cleaned.parquet"),
        ("new", args.new_root / "exports/latest_public_training/feature_dataset.parquet"),
        ("new", args.new_root / "exports/latest_public_training/forecast_label_dataset.parquet"),
        ("new", args.new_root / "exports/latest_public_training/resampled_observations.parquet"),
        ("new", args.new_root / "exports/latest_public_training/temporal_alignments.parquet"),
        ("new", args.new_root / "processed/training/public_training_candidates.parquet"),
        ("old", args.old_root / "releases/taihu_public_v1/tables/taihu_observations_long.parquet"),
        ("old", args.old_root / "releases/taihu_public_v1/tables/taihu_daily_features.parquet"),
        ("old", args.old_root / "releases/taihu_public_v1/tables/dataset_h1_3d.parquet"),
        ("old", args.old_root / "releases/taihu_public_v1/tables/dataset_h7_15d.parquet"),
        ("old", args.old_root / "releases/taihu_public_v1/tables/candidate_h30_90d.parquet"),
        ("old", args.old_root / "gold/integrated_horizon_datasets/dataset_h1_3d.parquet"),
        ("old", args.old_root / "gold/integrated_horizon_datasets/dataset_h7_15d.parquet"),
        ("old", args.old_root / "gold/integrated_horizon_datasets/candidate_dataset_h30_90d.parquet"),
    ]
    profiles = [profile_table(path, label) for label, path in table_specs]

    inventories = {
        "new_root": file_inventory(args.new_root),
        "old_root": file_inventory(args.old_root),
        "clms_v1": file_inventory(args.new_root / "rasters/clms_lwq_300m_v1"),
        "clms_v2": file_inventory(args.new_root / "rasters/clms_lwq_300m_v2"),
        "sentinel2_monthly": file_inventory(args.new_root / "rasters/sentinel2_monthly_30m_cdse"),
        "gfs_raw": file_inventory(args.new_root / "raw/meteorology/noaa_gfs"),
        "gfs_silver": file_inventory(args.new_root / "silver/forecast/noaa_gfs"),
        "gfs_extended_raw": file_inventory(args.new_root / "raw/meteorology/noaa_gfs_extended"),
        "gfs_extended_silver": file_inventory(args.new_root / "silver/forecast/noaa_gfs_extended"),
        "c3s_raw": file_inventory(args.new_root / "raw/meteorology/c3s_seasonal"),
        "c3s_silver": file_inventory(args.new_root / "silver/forecast/c3s_seasonal"),
        "era5_lake_temp": file_inventory(args.new_root / "raw/meteorology/era5_lake_temp"),
        "modis_chla": file_inventory(args.new_root / "raw/ocean_color/modis_aqua_chla"),
        "sentinel3_olci": file_inventory(args.new_root / "raw/ocean_color/sentinel3_olci"),
        "bloom_2019": file_inventory(args.new_root / "raw/bloom/taihu_2019_rf"),
        "thqbca": file_inventory(args.new_root / "raw/taihu_thqbca_zenodo"),
        "zenodo_insitu": file_inventory(args.new_root / "raw/zenodo_taihu_insitu"),
    }

    sample_candidates: list[Path] = []
    for folder, pattern in [
        (args.new_root / "rasters/clms_lwq_300m_v1", "*.tif"),
        (args.new_root / "rasters/clms_lwq_300m_v2", "*.tif"),
        (args.new_root / "rasters/sentinel2_monthly_30m_cdse", "*.tif"),
        (args.new_root / "raw/ocean_color/modis_aqua_chla", "*.nc"),
        (args.new_root / "raw/meteorology/era5_lake_temp", "*.nc"),
        (args.new_root / "raw/land_surface/modis_lst", "*.hdf"),
    ]:
        matches = sorted(folder.rglob(pattern)) if folder.exists() else []
        if matches:
            sample_candidates.extend([matches[0], matches[len(matches) // 2], matches[-1]])
    samples = [sample_asset(path) for path in dict.fromkeys(sample_candidates)]

    result = {
        "generated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "new_root": str(args.new_root),
        "old_root": str(args.old_root),
        "table_profiles": profiles,
        "inventories": inventories,
        "sample_assets": samples,
    }
    output_json = args.output / "storage_algorithm_audit.json"
    output_json.write_text(json.dumps(json_safe(result), ensure_ascii=False, indent=2), encoding="utf-8")

    flat_tables = []
    for p in profiles:
        flat_tables.append({
            "root": p.get("root"),
            "path": p.get("path"),
            "exists": p.get("exists"),
            "readable": p.get("readable"),
            "rows": p.get("rows"),
            "columns_count": p.get("columns_count"),
            "exact_duplicate_rows": p.get("exact_duplicate_rows"),
            "date_columns": ";".join((p.get("date_ranges") or {}).keys()),
            "critical_columns": ";".join((p.get("critical_columns") or {}).keys()),
            "error": p.get("error"),
        })
    pd.DataFrame(flat_tables).to_csv(args.output / "table_profile_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"dataset": k, **v} for k, v in inventories.items()]).to_csv(
        args.output / "source_inventory_summary.csv", index=False, encoding="utf-8-sig"
    )
    print(json.dumps({
        "output": str(output_json),
        "tables": len(profiles),
        "readable_tables": sum(bool(p.get("readable")) for p in profiles),
        "sample_assets": len(samples),
        "readable_assets": sum(bool(p.get("readable")) for p in samples),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
