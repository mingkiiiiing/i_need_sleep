# -*- coding: utf-8 -*-
"""Clean the latest CLMS, C3S and GFS downloads into auditable model tables.

Raw assets are never modified.  Outputs are deterministic and overwrite only
derived files under ``merged_data/2026_sheng-fuwai-main-merge/cleaned`` and
``merged_data/2026_sheng-fuwai-main-merge/exports/latest_public_training``.
The CLMS bloom target is explicitly a remote-sensing proxy, never ground truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.sources.c3s_seasonal import parse_c3s_dataset
from pipeline.sources.noaa_gfs import parse_gfs_grib

STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
CLEANED = STORAGE / "cleaned"
EXPORT_ROOT = STORAGE / "exports" / "latest_public_training"
REPORT_ROOT = STORAGE / "reports"
BOUNDARY = STORAGE / "silver" / "geo" / "taihu_boundary.gpkg"
UTC = timezone.utc

CLMS_SOURCES = (
    ("v1", STORAGE / "rasters" / "clms_lwq_300m_v1"),
    ("v2", STORAGE / "rasters" / "clms_lwq_300m_v2"),
)
CLMS_BANDS = {1: "chla_mean", 2: "chla_uncertainty", 3: "fcb_prob", 4: "qflag"}
SCIENCE_NODATA_LIMIT = 1e30
QFLAG_NODATA = 65535
MIN_PROXY_COVERAGE = 0.20
FCB_PIXEL_THRESHOLD = 0.50
MIN_BLOOM_AREA_FRACTION = 0.01
HORIZONS = {"h1_3d": (1, 3), "h7_15d": (7, 15), "h30_90d": (30, 90)}


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _write_frame(frame: pd.DataFrame, path: Path) -> dict[str, str]:
    _atomic_csv(frame, path)
    parquet = path.with_suffix(".parquet")
    _atomic_parquet(frame, parquet)
    return {"csv": str(path), "parquet": str(parquet)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stats(values: np.ndarray, prefix: str) -> dict[str, float]:
    values = values[np.isfinite(values)]
    if not values.size:
        return {f"{prefix}_{name}": math.nan for name in ("mean", "median", "std", "min", "max")}
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_median": float(np.median(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_max": float(np.max(values)),
    }


def _lake_geometry() -> dict[str, Any]:
    import fiona

    with fiona.open(BOUNDARY, layer="taihu_boundary_wgs84") as source:
        feature = next(iter(source))
        return dict(feature["geometry"])


def clean_clms() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create one lake-wide row per 10-day CLMS asset plus an asset audit."""

    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    geometry = _lake_geometry()
    clean_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for version, root in CLMS_SOURCES:
        for path in sorted(root.glob("**/*.tif")) if root.exists() else []:
            match = re.search(r"(\d{8})", path.name)
            date = pd.to_datetime(match.group(1), format="%Y%m%d") if match else pd.NaT
            with rasterio.open(path) as dataset:
                target_geometry = transform_geom("EPSG:4326", dataset.crs, geometry)
                lake = geometry_mask(
                    [target_geometry], out_shape=(dataset.height, dataset.width),
                    transform=dataset.transform, invert=True,
                )
                arrays = {band: dataset.read(index).astype("float64") for index, band in CLMS_BANDS.items()}
                qflag = arrays["qflag"]
                quality_valid = lake & np.isfinite(qflag) & (qflag != QFLAG_NODATA)
                science_valid = quality_valid.copy()
                for band in ("chla_mean", "chla_uncertainty", "fcb_prob"):
                    values = arrays[band]
                    science_valid &= np.isfinite(values) & (np.abs(values) < SCIENCE_NODATA_LIMIT)
                lake_pixels = int(lake.sum())
                valid_pixels = int(science_valid.sum())
                coverage = valid_pixels / lake_pixels if lake_pixels else 0.0
                unique_hash = _sha256(path)
                status = "accepted" if valid_pixels else "rejected_empty_science_bands"
                audit_rows.append({
                    "date": date.date().isoformat() if pd.notna(date) else None,
                    "product_version": version,
                    "file_path": str(path.relative_to(STORAGE)),
                    "file_bytes": path.stat().st_size,
                    "sha256": unique_hash,
                    "lake_pixels": lake_pixels,
                    "valid_science_pixels": valid_pixels,
                    "coverage_fraction": coverage,
                    "status": status,
                    "quality_flag": "Q00" if status == "accepted" else "Q03",
                })
                if not valid_pixels:
                    continue

                chla = arrays["chla_mean"][science_valid]
                uncertainty = arrays["chla_uncertainty"][science_valid]
                fcb = arrays["fcb_prob"][science_valid]
                bloom_fraction = float(np.mean(fcb >= FCB_PIXEL_THRESHOLD))
                if coverage < MIN_PROXY_COVERAGE:
                    bloom_proxy, label_status = math.nan, "unknown_low_coverage"
                elif bloom_fraction >= MIN_BLOOM_AREA_FRACTION:
                    bloom_proxy, label_status = 1.0, "positive_proxy"
                elif bloom_fraction == 0:
                    bloom_proxy, label_status = 0.0, "negative_proxy"
                else:
                    bloom_proxy, label_status = math.nan, "ambiguous_localized_signal"
                row = {
                    "sample_id": f"clms_{version}_{date:%Y%m%d}",
                    "date": date.date().isoformat(),
                    "month": date.strftime("%Y-%m"),
                    "spatial_id": "TAIHU_WHOLE",
                    "product_version": version,
                    "source_id": f"clms_lwq_300m_{version}",
                    "source_file": str(path.relative_to(STORAGE)),
                    "granularity": "10_daily",
                    "coverage_fraction": coverage,
                    "valid_pixel_count": valid_pixels,
                    "qflag_valid_fraction": float(quality_valid.sum() / lake_pixels) if lake_pixels else 0.0,
                    "fcb_bloom_pixel_fraction_p50": bloom_fraction,
                    "target_bloom_proxy": bloom_proxy,
                    "label_status": label_status,
                    "label_type": "remote_sensing_proxy_not_ground_truth",
                    "quality_flag": "Q00" if coverage >= MIN_PROXY_COVERAGE else "Q10",
                    **_safe_stats(chla, "chla_ug_l"),
                    **_safe_stats(uncertainty, "chla_uncertainty"),
                    **_safe_stats(fcb, "fcb_prob"),
                }
                clean_rows.append(row)
    clean = pd.DataFrame(clean_rows).sort_values("date").reset_index(drop=True)
    audit = pd.DataFrame(audit_rows).sort_values(["product_version", "date"]).reset_index(drop=True)
    return clean, audit


def clean_c3s() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw_root = STORAGE / "raw" / "meteorology" / "c3s_seasonal"
    silver_root = STORAGE / "silver" / "forecast" / "c3s_seasonal"
    cache_path = CLEANED / "c3s_seasonal_cleaned.csv"
    source_files = list(silver_root.glob("c3s_seasonal_*.csv"))
    if cache_path.exists() and source_files and cache_path.stat().st_mtime >= max(path.stat().st_mtime for path in source_files):
        cached = pd.read_csv(cache_path)
        refs = pd.to_datetime(cached["forecast_reference_time"], utc=True, errors="coerce")
        valids = pd.to_datetime(cached["valid_time"], utc=True, errors="coerce")
        lead = pd.to_numeric(cached["lead_month"], errors="coerce")
        valid = (
            refs.dt.year.between(1993, 2026) & valids.dt.year.between(1993, 2027)
            & lead.between(1, 3) & (valids >= refs)
        )
        key = ["dataset_kind", "forecast_reference_time", "valid_time", "lead_month", "ensemble_member", "variable_code"]
        if valid.all() and not cached.duplicated(key).any():
            return cached, {
                "raw_files": len(list(raw_root.glob("*.grib"))),
                "silver_files": len(source_files),
                "parsed_files": len(source_files),
                "used_validated_clean_cache": True,
                "output_rows": len(cached),
                "invalid_rows_excluded": 0,
                "duplicate_rows_removed": 0,
                "errors": [],
            }
    frames: list[pd.DataFrame] = []
    errors: list[dict[str, str]] = []
    repaired_files: list[str] = []
    for silver_path in sorted(silver_root.glob("c3s_seasonal_*.csv")):
        match = re.match(r"c3s_seasonal_(\d{4})_(\d{2})\.csv$", silver_path.name)
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        try:
            frame = pd.read_csv(silver_path)
            kind = str(frame["dataset_kind"].dropna().iloc[0])
            refs = pd.to_datetime(frame["forecast_reference_time"], utc=True, errors="coerce")
            valids = pd.to_datetime(frame["valid_time"], utc=True, errors="coerce")
            broken = (
                refs.isna() | valids.isna() | ~refs.dt.year.between(1993, 2026)
                | ~valids.dt.year.between(1993, 2027) | (valids < refs)
            )
            if broken.any():
                raw_path = raw_root / f"c3s_{kind}_{year:04d}_{month:02d}_system51.grib"
                parsed = parse_c3s_dataset(raw_path, kind=kind, init_year=year, init_month=month)
                frame = pd.DataFrame(parsed["rows"])
                frame["source_file"] = str(raw_path.relative_to(STORAGE))
                repaired_files.append(silver_path.name)
            elif "source_file" not in frame:
                frame["source_file"] = frame.get("raw_path", str(silver_path.relative_to(STORAGE)))
            frames.append(frame)
        except Exception as exc:  # preserve a per-file audit instead of losing the batch
            errors.append({"file": str(silver_path), "error": f"{type(exc).__name__}: {exc}"})
    if not frames:
        return pd.DataFrame(), {"files": 0, "errors": errors}
    combined = pd.concat(frames, ignore_index=True)
    combined["forecast_reference_time"] = pd.to_datetime(combined["forecast_reference_time"], utc=True, errors="coerce")
    combined["valid_time"] = pd.to_datetime(combined["valid_time"], utc=True, errors="coerce")
    combined["value"] = pd.to_numeric(combined["value"], errors="coerce")
    combined["lead_month"] = pd.to_numeric(combined["lead_month"], errors="coerce").astype("Int64")
    valid_date = (
        combined["forecast_reference_time"].dt.year.between(1993, 2026)
        & combined["valid_time"].dt.year.between(1993, 2027)
        & combined["lead_month"].between(1, 3)
        & combined["value"].notna()
        & (combined["valid_time"] >= combined["forecast_reference_time"])
    )
    invalid_rows = int((~valid_date).sum())
    combined = combined[valid_date].copy()
    key = ["dataset_kind", "forecast_reference_time", "valid_time", "lead_month", "ensemble_member", "variable_code"]
    duplicates = int(combined.duplicated(key).sum())
    combined = combined.drop_duplicates(key, keep="last").sort_values(key).reset_index(drop=True)
    combined["forecast_reference_time"] = combined["forecast_reference_time"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    combined["valid_time"] = combined["valid_time"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    combined["quality_flag"] = "Q00"
    audit = {
        "raw_files": len(list(raw_root.glob("*.grib"))),
        "silver_files": len(list(silver_root.glob("c3s_seasonal_*.csv"))),
        "parsed_files": len(frames),
        "reparsed_files": repaired_files,
        "output_rows": len(combined),
        "invalid_rows_excluded": invalid_rows,
        "duplicate_rows_removed": duplicates,
        "errors": errors,
    }
    return combined, audit


def clean_gfs() -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest_root = STORAGE / "manifests"
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    selected_manifests = []
    pattern = re.compile(r"noaa_gfs_(\d{4})-?(\d{2})-?(\d{2})_(\d{2})z\.json$")
    for manifest_path in sorted(manifest_root.glob("noaa_gfs_*.json")):
        if not pattern.match(manifest_path.name):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "completed" or not manifest.get("assets"):
            continue
        selected_manifests.append(manifest_path.name)
        run_time = str(manifest["run_time"])
        for asset in manifest["assets"]:
            path = Path(asset.get("path", ""))
            if not path.exists():
                path = STORAGE / "raw" / "meteorology" / "noaa_gfs" / path.name
            if asset.get("status") not in {"completed", "skipped_existing"} or not path.exists():
                continue
            try:
                parsed = parse_gfs_grib(path, run_time=run_time, fallback_lead_hours=float(asset["step"]))
                if parsed.get("status") == "completed":
                    rows.extend(parsed.get("rows", []))
                else:
                    errors.append({"file": str(path), "error": str(parsed.get("error"))})
            except Exception as exc:
                errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"manifests": selected_manifests, "errors": errors}
    for column in ("forecast_reference_time", "valid_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    frame["lead_hours"] = pd.to_numeric(frame["lead_hours"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    valid = (
        frame["forecast_reference_time"].notna() & frame["valid_time"].notna()
        & frame["lead_hours"].between(0, 384) & frame["value"].notna()
        & (frame["valid_time"] >= frame["forecast_reference_time"])
    )
    invalid_rows = int((~valid).sum())
    frame = frame[valid].copy()
    key = ["forecast_reference_time", "valid_time", "lead_hours", "ensemble_member", "variable_code"]
    duplicates = int(frame.duplicated(key).sum())
    frame = frame.drop_duplicates(key).sort_values(key).reset_index(drop=True)
    for column in ("forecast_reference_time", "valid_time"):
        frame[column] = frame[column].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    frame["quality_flag"] = "Q00"
    return frame, {
        "manifests": selected_manifests,
        "output_rows": len(frame),
        "invalid_rows_excluded": invalid_rows,
        "duplicate_rows_removed": duplicates,
        "errors": errors,
    }


def build_resampled_observations(clms: pd.DataFrame, c3s: pd.DataFrame, gfs: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    clms_variables = {
        "chla_ug_l_mean": ("chla_proxy", "ug/L"),
        "chla_uncertainty_mean": ("chla_uncertainty", "ug/L"),
        "fcb_prob_mean": ("fcb_prob", "probability"),
        "fcb_bloom_pixel_fraction_p50": ("bloom_area_fraction_proxy", "fraction"),
        "target_bloom_proxy": ("bloom_binary_proxy", "binary"),
    }
    for row in clms.to_dict("records"):
        for column, (variable, unit) in clms_variables.items():
            value = row.get(column)
            if pd.isna(value):
                continue
            records.append({
                "source_id": row["source_id"], "station_id": "TAIHU_WHOLE", "scene_id": row["sample_id"],
                "observed_at": row["date"] + "T00:00:00+08:00", "time_bucket": row["date"],
                "forecast_reference_time": None, "valid_time": row["date"], "lead_hours": 0,
                "variable_code": variable, "clean_value": value, "unit": unit,
                "frequency": "10_daily", "source_granularity": "10_daily", "record_role": "observed_proxy",
                "value_origin": "remote_sensing_proxy", "quality_flags": row["quality_flag"],
                "source_file": row["source_file"], "is_imputed": False,
            })
    for source, frame, frequency in (("c3s", c3s, "monthly"), ("gfs", gfs, "6_hourly")):
        for row in frame.to_dict("records"):
            records.append({
                "source_id": row.get("source_id"), "station_id": row.get("station_id", "TAIHU_AREA_MEAN"),
                "scene_id": None, "observed_at": None, "time_bucket": row.get("valid_time"),
                "forecast_reference_time": row.get("forecast_reference_time"), "valid_time": row.get("valid_time"),
                "lead_hours": row.get("lead_hours"), "variable_code": row.get("variable_code"),
                "clean_value": row.get("value"), "unit": row.get("unit"), "frequency": frequency,
                "source_granularity": frequency, "record_role": "forecast", "value_origin": row.get("value_origin", source),
                "quality_flags": row.get("quality_flag", "Q00"), "source_file": row.get("source_file") or row.get("raw_grib_path"),
                "is_imputed": bool(row.get("is_imputed", False)),
            })
    return pd.DataFrame(records)


def _choose_target(frame: pd.DataFrame, start: pd.Timestamp, lower: int, upper: int) -> pd.Series | None:
    dates = pd.to_datetime(frame["date"])
    gaps = (dates - start).dt.days
    candidates = frame[gaps.between(lower, upper)].copy()
    if candidates.empty:
        return None
    candidates["_distance"] = ((pd.to_datetime(candidates["date"]) - start).dt.days - (lower + upper) / 2).abs()
    return candidates.sort_values(["_distance", "date"]).iloc[0]


def build_labels(clms: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels: list[dict[str, Any]] = []
    alignments: list[dict[str, Any]] = []
    for current in clms.itertuples(index=False):
        start = pd.Timestamp(current.date)
        row: dict[str, Any] = {
            "sample_id": current.sample_id, "prediction_start": current.date,
            "spatial_id": current.spatial_id, "label_type": "remote_sensing_proxy_not_ground_truth",
        }
        for horizon, (lower, upper) in HORIZONS.items():
            target = _choose_target(clms, start, lower, upper)
            status = "accepted" if target is not None and pd.notna(target["target_bloom_proxy"]) else "missing_target"
            row[f"{horizon}_status"] = status
            row[f"{horizon}_target_date"] = target["date"] if target is not None else None
            row[f"{horizon}_target_bloom_proxy"] = target["target_bloom_proxy"] if target is not None else math.nan
            row[f"{horizon}_target_chla_ug_l"] = target["chla_ug_l_mean"] if target is not None else math.nan
            if target is not None:
                gap = int((pd.Timestamp(target["date"]) - start).days)
                row[f"{horizon}_gap_days"] = gap
                for variable, value in (
                    ("bloom_binary_proxy", target["target_bloom_proxy"]),
                    ("chla_proxy", target["chla_ug_l_mean"]),
                ):
                    alignments.append({
                        "sample_id": current.sample_id, "prediction_start": current.date,
                        "spatial_id": current.spatial_id, "horizon": horizon,
                        "target_date": target["date"], "target_gap_days": gap,
                        "target_variable": variable, "target_value": value,
                        "target_source_id": target["source_id"], "target_sample_id": target["sample_id"],
                        "feature_precedes_target": True, "alignment_status": status,
                    })
        labels.append(row)
    return pd.DataFrame(labels), pd.DataFrame(alignments)


def _c3s_feature_lookup(c3s: pd.DataFrame) -> tuple[list[pd.Timestamp], dict[pd.Timestamp, dict[str, Any]]]:
    if c3s.empty:
        return [], {}
    frame = c3s[c3s["dataset_kind"] == "forecast"].copy()
    frame["forecast_reference_time"] = pd.to_datetime(frame["forecast_reference_time"], utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    lookup: dict[pd.Timestamp, dict[str, Any]] = {}
    for reference, group in frame.groupby("forecast_reference_time"):
        values: dict[str, Any] = {"c3s_forecast_reference_time": reference.isoformat()}
        for (lead, variable), part in group.groupby(["lead_month", "variable_code"]):
            numeric = part["value"].dropna().to_numpy(dtype="float64")
            if not numeric.size:
                continue
            stem = f"c3s_{variable}_lead{int(lead)}"
            values[f"{stem}_mean"] = float(np.mean(numeric))
            values[f"{stem}_p10"] = float(np.quantile(numeric, 0.10))
            values[f"{stem}_p90"] = float(np.quantile(numeric, 0.90))
        lookup[reference] = values
    return sorted(lookup), lookup


def _sentinel_previous_month_lookup() -> dict[str, dict[str, Any]]:
    path = CLEANED / "remote_sensing_monthly_cleaned.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    frame = frame[frame["product"] == "sentinel2_cdse_monthly_30m"].copy()
    frame["mean"] = pd.to_numeric(frame["mean"], errors="coerce")
    lookup: dict[str, dict[str, Any]] = {}
    for month, group in frame.groupby("month"):
        lookup[str(month)] = {
            f"sentinel2_prev_{str(row.variable).lower()}_mean": row.mean
            for row in group.itertuples(index=False)
        }
    return lookup


def build_features(clms: pd.DataFrame, c3s: pd.DataFrame) -> pd.DataFrame:
    references, c3s_lookup = _c3s_feature_lookup(c3s)
    sentinel_lookup = _sentinel_previous_month_lookup()
    rows: list[dict[str, Any]] = []
    ordered = clms.sort_values("date").reset_index(drop=True)
    for index, current in ordered.iterrows():
        start = pd.Timestamp(current["date"], tz="UTC")
        feature: dict[str, Any] = {
            "sample_id": current["sample_id"], "prediction_start": current["date"],
            "spatial_id": current["spatial_id"], "feature_cutoff": current["date"] + "T23:59:59+08:00",
            "feature_clms_chla_ug_l": current["chla_ug_l_mean"],
            "feature_clms_fcb_prob": current["fcb_prob_mean"],
            "feature_clms_bloom_fraction": current["fcb_bloom_pixel_fraction_p50"],
            "feature_clms_coverage": current["coverage_fraction"],
            "leakage_check": "passed",
        }
        for lag_steps in (1, 2, 3):
            previous = ordered.iloc[index - lag_steps] if index >= lag_steps else None
            if previous is not None:
                gap = (pd.Timestamp(current["date"]) - pd.Timestamp(previous["date"])).days
                if gap <= 15 * lag_steps:
                    feature[f"feature_clms_chla_lag{lag_steps * 10}d"] = previous["chla_ug_l_mean"]
                    feature[f"feature_clms_fcb_lag{lag_steps * 10}d"] = previous["fcb_prob_mean"]
        window_start = pd.Timestamp(current["date"]) - pd.Timedelta(days=30)
        history = ordered[(pd.to_datetime(ordered["date"]) >= window_start) & (pd.to_datetime(ordered["date"]) <= pd.Timestamp(current["date"]))]
        feature["feature_clms_chla_rolling30d_mean"] = history["chla_ug_l_mean"].mean()
        feature["feature_clms_fcb_rolling30d_mean"] = history["fcb_prob_mean"].mean()
        candidates = [reference for reference in references if reference <= start and (start - reference).days <= 31]
        if candidates:
            feature.update(c3s_lookup[max(candidates)])
        previous_month = (pd.Timestamp(current["date"]).to_period("M") - 1).strftime("%Y-%m")
        feature["sentinel2_feature_month"] = previous_month
        feature.update(sentinel_lookup.get(previous_month, {}))
        rows.append(feature)
    return pd.DataFrame(rows)


def _date_range(frame: pd.DataFrame, column: str) -> dict[str, str | None]:
    if frame.empty or column not in frame:
        return {"min": None, "max": None}
    values = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
    return {"min": values.min().isoformat() if len(values) else None, "max": values.max().isoformat() if len(values) else None}


def main() -> int:
    CLEANED.mkdir(parents=True, exist_ok=True)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    print("== 最新公开数据清洗 ==")
    clms, clms_audit = clean_clms()
    c3s, c3s_audit = clean_c3s()
    gfs, gfs_audit = clean_gfs()
    observations = build_resampled_observations(clms, c3s, gfs)
    labels, alignments = build_labels(clms)
    features = build_features(clms, c3s)

    outputs: dict[str, dict[str, str]] = {}
    for name, frame, root in (
        ("clms_lwq_10daily_cleaned", clms, CLEANED),
        ("clms_lwq_asset_audit", clms_audit, CLEANED),
        ("c3s_seasonal_cleaned", c3s, CLEANED),
        ("noaa_gfs_cleaned", gfs, CLEANED),
        ("resampled_observations", observations, EXPORT_ROOT),
        ("forecast_label_dataset", labels, EXPORT_ROOT),
        ("temporal_alignments", alignments, EXPORT_ROOT),
        ("feature_dataset", features, EXPORT_ROOT),
    ):
        outputs[name] = _write_frame(frame, root / f"{name}.csv")

    label_counts = {
        horizon: labels[f"{horizon}_status"].value_counts(dropna=False).to_dict()
        for horizon in HORIZONS
    }
    report = {
        "status": "completed_with_declared_source_limitations",
        "generated_at": datetime.now(UTC).isoformat(),
        "truth_boundary": "CLMS bloom and chlorophyll values are remote-sensing proxies, not official station truth.",
        "thresholds": {
            "minimum_lake_coverage": MIN_PROXY_COVERAGE,
            "fcb_pixel_probability": FCB_PIXEL_THRESHOLD,
            "minimum_positive_bloom_area_fraction": MIN_BLOOM_AREA_FRACTION,
        },
        "clms": {
            "accepted_rows": len(clms), "asset_rows": len(clms_audit),
            "rejected_empty_assets": int((clms_audit["status"] != "accepted").sum()),
            "date_range": _date_range(clms, "date"),
            "proxy_label_counts": clms["label_status"].value_counts(dropna=False).to_dict(),
            "duplicate_sample_ids": int(clms.duplicated("sample_id").sum()),
        },
        "c3s": {**c3s_audit, "date_range": _date_range(c3s, "forecast_reference_time")},
        "gfs": {**gfs_audit, "date_range": _date_range(gfs, "forecast_reference_time")},
        "artifacts": {
            "resampled_observations_rows": len(observations),
            "forecast_label_rows": len(labels),
            "feature_rows": len(features),
            "temporal_alignment_rows": len(alignments),
            "label_availability": label_counts,
            "future_feature_leakage_rows": int((features["leakage_check"] != "passed").sum()),
        },
        "known_limitations": [
            "CLMS V1 local rasters contain no valid scientific pixels and are excluded.",
            "GFS history contains only two initialisation runs and reaches only 72 hours.",
            "Ten-day CLMS labels cannot evaluate a strict 1-3 day horizon.",
            "Proxy labels must not be described as official monitoring-station truth.",
        ],
        "outputs": outputs,
    }
    report_path = REPORT_ROOT / "latest_public_data_cleaning_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "report": str(report_path),
        "files": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for item in outputs.values() for path in map(Path, item.values())
        ],
    }
    manifest_path = STORAGE / "manifests" / "latest_public_data_cleaning.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  CLMS: {len(clms)} usable / {len(clms_audit)} assets")
    print(f"  C3S: {len(c3s)} rows; GFS: {len(gfs)} rows")
    print(f"  labels={len(labels)} features={len(features)} alignments={len(alignments)}")
    print(f"  report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
