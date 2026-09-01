"""NASA GPM IMERG half-hourly precipitation adapter.

The adapter is deliberately conservative: it requests only individual
0.1-degree granules covering the Taihu window, preserves the precipitation
quality index, and represents missing source pixels/windows as ``None``.  A
NASA Earthdata token is required for GES DISC granule retrieval; when absent,
the CLI writes an auditable request plan and does not pretend that metadata is
an observation batch.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote

import numpy as np

from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest
from .common import PACKAGE_ROOT, download_asset


UTC = timezone.utc
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
EARTHDATA_TOKEN_ENV = "TAIHU_EARTHDATA_TOKEN"
DEFAULT_BBOX = (119.90, 30.90, 120.75, 31.65)
DEFAULT_VERSION = "07"
DEFAULT_RUN = "early"
GES_DISC_DATA_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGHH.07"
GES_DISC_OPENDAP_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGHH.07"
RUN_PREFIX = {
    "early": "3B-HHR-E.MS.MRG.3IMERG",
    "late": "3B-HHR-L.MS.MRG.3IMERG",
    "final": "3B-HHR.MS.MRG.3IMERG",
}


def _as_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(second=0, microsecond=0)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _doy(value: datetime) -> int:
    return int(value.strftime("%j"))


def _minute_offset(value: datetime) -> int:
    return value.hour * 60 + value.minute


def build_imerg_filename(timestamp: str | datetime, *, run: str = DEFAULT_RUN, version: str = DEFAULT_VERSION) -> str:
    """Build the official 30-minute IMERG HDF5 filename."""

    moment = _as_utc(timestamp)
    if moment.minute not in {0, 30} or moment.second:
        raise ValueError("IMERG granule time must be aligned to minute 00 or 30")
    run = str(run).lower()
    if run not in RUN_PREFIX:
        raise ValueError(f"unsupported IMERG run: {run}")
    start = _minute_offset(moment)
    end = start + 29
    start_hour, start_minute = divmod(start, 60)
    end_hour, end_minute = divmod(end, 60)
    return (
        f"{RUN_PREFIX[run]}.{moment:%Y%m%d}-S{start_hour:02d}{start_minute:02d}00-E{end_hour:02d}{end_minute:02d}59."
        f"{start:04d}.V{str(version).lstrip('V')}.HDF5"
    )


def build_imerg_access_urls(
    timestamp: str | datetime,
    *,
    run: str = DEFAULT_RUN,
    version: str = DEFAULT_VERSION,
) -> dict[str, str]:
    """Return direct GES DISC and OPeNDAP URLs for one granule."""

    moment = _as_utc(timestamp)
    filename = build_imerg_filename(moment, run=run, version=version)
    path = f"{moment:%Y}/{_doy(moment):03d}/{quote(filename)}"
    return {
        "file": f"{GES_DISC_DATA_BASE}/{path}",
        "opendap": f"{GES_DISC_OPENDAP_BASE}/{path}",
    }


def _decode_attr(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.size == 1:
        return _decode_attr(value.reshape(-1)[0])
    return value


def _find_dataset(handle: Any, names: Iterable[str]) -> Any | None:
    wanted = {str(name).lower() for name in names}
    found: list[Any] = []

    def visitor(_name: str, item: Any) -> None:
        if hasattr(item, "shape") and _name.rsplit("/", 1)[-1].lower() in wanted:
            found.append(item)

    handle.visititems(visitor)
    return found[0] if found else None


def _read_hdf_dataset(dataset: Any) -> tuple[np.ndarray, dict[str, Any]]:
    values = np.asarray(dataset[...], dtype=float)
    attrs = {str(key): _decode_attr(value) for key, value in dataset.attrs.items()}
    fill_values = [attrs.get("_FillValue"), attrs.get("missing_value")]
    for fill in fill_values:
        if fill is not None:
            try:
                values[values == float(fill)] = np.nan
            except (TypeError, ValueError):
                pass
    values[values <= -9000] = np.nan
    return values, attrs


def _orient_grid(values: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    if values.shape == (len(lat), len(lon)):
        return values
    if values.shape == (len(lon), len(lat)):
        return values.T
    raise ValueError(f"IMERG grid shape {values.shape} does not match lat/lon {len(lat)}/{len(lon)}")


def _mean_in_bbox(values: np.ndarray, lat: np.ndarray, lon: np.ndarray, bbox: tuple[float, float, float, float]) -> tuple[float | None, int, int]:
    west, south, east, north = bbox
    lat_mask = (lat >= south) & (lat <= north)
    lon_mask = (lon >= west) & (lon <= east)
    subset = values[np.ix_(lat_mask, lon_mask)]
    valid = np.isfinite(subset)
    count = int(valid.sum())
    total = int(subset.size)
    return (float(np.nanmean(subset)) if count else None, count, total)


def _quality_mean(dataset: Any, lat: np.ndarray, lon: np.ndarray, bbox: tuple[float, float, float, float]) -> tuple[float | None, str | None]:
    quality = _find_dataset(dataset, ("precipitationQualityIndex", "PrecipitationQualityIndex", "qualityIndex"))
    if quality is None:
        return None, None
    values, _attrs = _read_hdf_dataset(quality)
    values = _orient_grid(values, lat, lon)
    mean, _valid, _total = _mean_in_bbox(values, lat, lon, bbox)
    return mean, "precipitationQualityIndex"


def parse_imerg_hdf5(
    path: Path,
    *,
    observed_at: str | datetime | None = None,
    run: str = DEFAULT_RUN,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
) -> dict[str, Any]:
    """Parse one IMERG HDF5 granule into a Taihu area-mean observation row."""

    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - environment dependent
        return {"status": "BLOCKED_DEPENDENCY", "error": str(exc), "rows": []}
    path = Path(path)
    moment = _as_utc(observed_at) if observed_at is not None else _as_utc(datetime.fromtimestamp(path.stat().st_mtime, tz=UTC))
    with h5py.File(path, "r") as handle:
        lat_ds = _find_dataset(handle, ("lat", "latitude"))
        lon_ds = _find_dataset(handle, ("lon", "longitude"))
        precip_ds = _find_dataset(handle, ("precipitationCal", "precipitation"))
        if lat_ds is None or lon_ds is None or precip_ds is None:
            raise ValueError("IMERG HDF5 is missing lat/lon/precipitationCal datasets")
        lat = np.asarray(lat_ds[...], dtype=float).reshape(-1)
        lon = np.asarray(lon_ds[...], dtype=float).reshape(-1)
        precipitation, attrs = _read_hdf_dataset(precip_ds)
        precipitation = _orient_grid(precipitation, lat, lon)
        mean_rate, valid_count, total_count = _mean_in_bbox(precipitation, lat, lon, bbox)
        unit_text = str(attrs.get("units", "mm/hr")).lower()
        if mean_rate is None:
            value = None
            conversion = "missing_source_value"
        elif "mm/hr" in unit_text or "mm h" in unit_text:
            value = mean_rate * 0.5
            conversion = "rate_mm_per_hour_to_30min_mm"
        elif unit_text.strip() in {"mm", "millimeter", "millimeters"}:
            value = mean_rate
            conversion = "source_accumulation_mm"
        else:
            raise ValueError(f"unsupported IMERG precipitation units: {unit_text}")
        quality, quality_source = _quality_mean(handle, lat, lon, bbox)
    row = {
        "source_id": "gpm_imerg",
        "station_id": "TAIHU_AREA_MEAN",
        "run": str(run).lower(),
        "observed_at": _timestamp_text(moment),
        "variable_code": "precipitation_30min",
        "value": value,
        "unit": "mm",
        "source_parameter": "precipitationCal",
        "source_unit": str(attrs.get("units", "mm/hr")),
        "conversion_rule": conversion,
        "quality_index": quality,
        "quality_index_source": quality_source,
        "valid_pixel_count": valid_count,
        "total_pixel_count": total_count,
        "missing_pixel_count": total_count - valid_count,
        "bbox_west": bbox[0], "bbox_south": bbox[1], "bbox_east": bbox[2], "bbox_north": bbox[3],
        "source_file": str(path),
        "value_origin": "remote_sensing",
        "is_imputed": False,
        "quality_flags": "[]" if value is not None else "[\"missing_source_value\"]",
    }
    return {"status": "parsed", "source_id": "gpm_imerg", "rows": [row], "record_count": 1, "row": row}


def aggregate_imerg_windows(rows: Iterable[Mapping[str, Any]], windows_hours: Iterable[int] = (6, 24, 72)) -> list[dict[str, Any]]:
    """Create trailing accumulations while retaining missing-window states."""

    ordered = sorted((dict(row) for row in rows), key=lambda row: _as_utc(row["observed_at"]))
    result: list[dict[str, Any]] = []
    for row in ordered:
        end = _as_utc(row["observed_at"])
        for window in windows_hours:
            window = int(window)
            expected = window * 2
            start = end - timedelta(hours=window) + timedelta(minutes=30)
            selected = [item for item in ordered if start <= _as_utc(item["observed_at"]) <= end]
            selected_times = {_as_utc(item["observed_at"]) for item in selected}
            expected_times = {start + timedelta(minutes=30 * index) for index in range(expected)}
            missing_samples = len(expected_times - selected_times)
            values = [item.get("value") for item in selected]
            complete = missing_samples == 0 and len(values) == expected and all(value is not None for value in values)
            result.append({
                "source_id": "gpm_imerg", "station_id": row.get("station_id", "TAIHU_AREA_MEAN"),
                "run": row.get("run", DEFAULT_RUN), "observed_at": _timestamp_text(end),
                "window_hours": window, "variable_code": f"precipitation_{window}h",
                "value": float(sum(values)) if complete else None, "unit": "mm",
                "expected_samples": expected, "actual_samples": len(selected), "missing_samples": missing_samples,
                "quality_index_mean": float(np.nanmean([item["quality_index"] for item in selected if item.get("quality_index") is not None])) if any(item.get("quality_index") is not None for item in selected) else None,
                "aggregation_status": "complete" if complete else "missing_input",
                "value_origin": "remote_sensing", "is_imputed": False,
            })
    return result


def _write_csv(rows: list[dict[str, Any]], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["source_id", "observed_at", "variable_code", "value", "unit"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def _credentials_present() -> bool:
    return bool(os.environ.get(EARTHDATA_TOKEN_ENV, "").strip())


def run_gpm_imerg(
    start_time: str,
    end_time: str,
    *,
    run: str = DEFAULT_RUN,
    version: str = DEFAULT_VERSION,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
    raw_root: Path | None = None,
    silver_root: Path | None = None,
    manifest_path: Path | None = None,
    downloader: Callable[[str, Path, Mapping[str, str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Download/parse an aligned IMERG window or return BLOCKED_AUTH plan."""

    start = _as_utc(start_time)
    end = _as_utc(end_time)
    if start.minute not in {0, 30} or end.minute not in {0, 30} or start > end:
        raise ValueError("start_time/end_time must be aligned 30-minute UTC values")
    timestamps: list[datetime] = []
    cursor = start
    while cursor <= end:
        timestamps.append(cursor)
        cursor += timedelta(minutes=30)
    raw_root = Path(raw_root or STORAGE / "raw" / "meteorology" / "gpm_imerg")
    silver_root = Path(silver_root or STORAGE / "silver" / "gpm_imerg")
    manifest_path = Path(manifest_path or STORAGE / "manifests" / f"gpm_imerg_{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}.json")
    plan = [{"observed_at": _timestamp_text(moment), "urls": build_imerg_access_urls(moment, run=run, version=version)} for moment in timestamps]
    if not _credentials_present() and downloader is None:
        result = {
            "task_id": "P05-05", "status": "BLOCKED_AUTH", "data_truth": "official_request_plan_only",
            "source_id": "gpm_imerg", "run": run, "version": version, "bbox": list(bbox),
            "granules": plan, "granule_count": len(plan), "raw_root": str(raw_root), "silver_root": str(silver_root),
            "auth_probe": str(STORAGE / "manifests" / "earthdata_auth_probe.json"),
            "required_env": EARTHDATA_TOKEN_ENV, "credentials_present": False,
            "error_class": "MissingEarthdataToken",
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    token = os.environ.get(EARTHDATA_TOKEN_ENV, "")
    raw_rows: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for moment in timestamps:
        filename = build_imerg_filename(moment, run=run, version=version)
        target = raw_root / f"{moment:%Y%m%dT%H%M}_{filename}"
        url = build_imerg_access_urls(moment, run=run, version=version)["file"]
        try:
            if downloader is None:
                download_result = download_asset(
                    "gpm_imerg", target.stem, url, target,
                    headers={"Authorization": f"Bearer {token}"},
                    license_tag="NASA-GPM-IMERG", redistribution_allowed="conditional", commercial_use="conditional",
                )
            else:
                download_result = downloader(url, target, {"Authorization": f"Bearer {token}"})
            parsed = parse_imerg_hdf5(target, observed_at=moment, run=run, bbox=bbox)
            raw_rows.extend(parsed["rows"])
            assets.append({"observed_at": _timestamp_text(moment), "status": "completed", "path": str(target), "download": download_result})
        except Exception as exc:
            assets.append({"observed_at": _timestamp_text(moment), "status": "failed", "path": str(target), "error": str(exc)})
    accumulated = aggregate_imerg_windows(raw_rows)
    raw_output = _write_csv(raw_rows, silver_root / f"gpm_imerg_{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}_30min.csv") if raw_rows else None
    accumulation_output = _write_csv(accumulated, silver_root / f"gpm_imerg_{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}_accumulations.csv") if accumulated else None
    result = {
        "task_id": "P05-05", "status": "completed" if assets and all(item["status"] == "completed" for item in assets) else "failed",
        "data_truth": "real_external_earthdata", "source_id": "gpm_imerg", "run": run, "version": version,
        "bbox": list(bbox), "granule_count": len(timestamps), "assets": assets, "raw_records": len(raw_rows),
        "accumulation_records": len(accumulated), "raw_output": raw_output, "accumulation_output": accumulation_output,
        "missing_policy": "missing_input_is_null_and_statused; never filled with zero",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


__all__ = [
    "DEFAULT_BBOX", "aggregate_imerg_windows", "build_imerg_access_urls", "build_imerg_filename",
    "parse_imerg_hdf5", "run_gpm_imerg",
]
