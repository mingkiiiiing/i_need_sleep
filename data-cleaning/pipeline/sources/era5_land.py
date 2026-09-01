"""ERA5-Land CDS request, NetCDF parsing, and Silver CSV adapter."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import xarray as xr

from .common import PACKAGE_ROOT
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
DATASET = "reanalysis-era5-land"
DEFAULT_VARIABLES = (
    "2m_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
    "total_precipitation",
    "surface_solar_radiation_downwards",
)
VARIABLE_MAP = {
    "2m_temperature": {"names": ("t2m", "2m_temperature"), "code": "air_temperature", "source_unit": "K", "unit": "degC", "conversion": "K - 273.15"},
    "10m_u_component_of_wind": {"names": ("u10", "10m_u_component_of_wind"), "code": "wind_u", "source_unit": "m/s", "unit": "m/s", "conversion": None},
    "10m_v_component_of_wind": {"names": ("v10", "10m_v_component_of_wind"), "code": "wind_v", "source_unit": "m/s", "unit": "m/s", "conversion": None},
    "total_precipitation": {"names": ("tp", "total_precipitation"), "code": "precipitation", "source_unit": "m", "unit": "mm", "conversion": "m x 1000; hourly accumulation"},
    "surface_solar_radiation_downwards": {"names": ("ssrd", "surface_solar_radiation_downwards"), "code": "shortwave_radiation", "source_unit": "J/m^2", "unit": "W/m2", "conversion": "J/m2 per hour / 3600"},
    "volumetric_soil_water_layer_1": {"names": ("swvl1", "volumetric_soil_water_layer_1"), "code": "soil_moisture_layer_1", "source_unit": "m3/m3", "unit": "m3/m3", "conversion": None},
}


class CDSAuthRequired(RuntimeError):
    """Raised when an online CDS retrieval is requested without credentials."""


def build_cds_request(year: int, bbox: tuple[float, float, float, float], variables: Iterable[str] = DEFAULT_VARIABLES) -> dict[str, Any]:
    """Build a CDS request; bbox uses west, south, east, north order."""

    west, south, east, north = map(float, bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be (west, south, east, north) in WGS84")
    selected = list(variables)
    unknown = sorted(set(selected) - set(VARIABLE_MAP))
    if unknown:
        raise ValueError(f"unsupported ERA5-Land variables: {unknown}")
    return {
        "product_type": "reanalysis",
        "variable": selected,
        "year": f"{int(year):04d}",
        "month": [f"{month:02d}" for month in range(1, 13)],
        "day": [f"{day:02d}" for day in range(1, 32)],
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "area": [north, west, south, east],
        "format": "netcdf",
    }


def _find_dimension(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in dataset.dims or name in dataset.coords:
            return name
    return None


def _time_text(value: Any) -> str:
    if isinstance(value, np.datetime64):
        value = value.astype("datetime64[s]").astype(str)
    text = str(value).replace(" ", "T")
    if text.endswith(".000000000"):
        text = text[:-10]
    if not text.endswith("Z") and "+" not in text:
        text += "Z"
    return text


def _convert(value: float, spec: dict[str, Any]) -> float:
    conversion = spec.get("conversion")
    if conversion == "K - 273.15":
        return value - 273.15
    if conversion == "m x 1000; hourly accumulation":
        return value * 1000.0
    if conversion == "J/m2 per hour / 3600":
        return value / 3600.0
    return value


def parse_era5_land_netcdf(path: Path, bbox: tuple[float, float, float, float] | None = None) -> dict[str, Any]:
    """Parse an ERA5-Land NetCDF to hourly area-mean standard observations."""

    path = Path(path)
    dataset = xr.open_dataset(path)
    try:
        time_dim = _find_dimension(dataset, ("time", "valid_time"))
        lat_dim = _find_dimension(dataset, ("latitude", "lat"))
        lon_dim = _find_dimension(dataset, ("longitude", "lon"))
        if time_dim is None:
            raise ValueError("ERA5-Land NetCDF is missing time/valid_time dimension")
        if bbox and lat_dim and lon_dim:
            west, south, east, north = bbox
            lat_values = np.asarray(dataset[lat_dim].values)
            lat_slice = slice(north, south) if lat_values.size > 1 and lat_values[0] > lat_values[-1] else slice(south, north)
            dataset = dataset.sel({lat_dim: lat_slice, lon_dim: slice(west, east)})
        center_lon = float(np.nanmean(dataset[lon_dim].values)) if lon_dim else None
        center_lat = float(np.nanmean(dataset[lat_dim].values)) if lat_dim else None
        rows: list[dict[str, Any]] = []
        variables_seen: list[str] = []
        time_values = dataset[time_dim].values
        for requested_name, spec in VARIABLE_MAP.items():
            actual_name = next((name for name in spec["names"] if name in dataset.data_vars), None)
            if actual_name is None:
                continue
            variables_seen.append(requested_name)
            data = dataset[actual_name]
            reduce_dims = [dim for dim in data.dims if dim != time_dim]
            if reduce_dims:
                data = data.mean(dim=reduce_dims, skipna=True)
            for index, timestamp in enumerate(time_values):
                raw_value = data.isel({time_dim: index}).values
                if np.asarray(raw_value).size == 0 or not np.isfinite(raw_value).any():
                    observed_value = None
                    clean_value = None
                else:
                    observed_value = float(np.asarray(raw_value).reshape(-1)[0])
                    clean_value = _convert(observed_value, spec)
                rows.append({
                    "source_id": "era5_land",
                    "source_file": str(path),
                    "source_row": f"{index}:{actual_name}",
                    "station_id": f"ERA5_LAND_BBOX_{center_lon:.3f}_{center_lat:.3f}" if center_lon is not None else "ERA5_LAND_GRID",
                    "observed_at": _time_text(timestamp),
                    "observed_at_utc": _time_text(timestamp),
                    "observed_at_local": None,
                    "time_status": "accepted",
                    "source_timezone": "UTC",
                    "longitude": center_lon,
                    "latitude": center_lat,
                    "variable_code": spec["code"],
                    "source_parameter": actual_name,
                    "observed_value": observed_value,
                    "clean_value": clean_value,
                    "unit": spec["unit"],
                    "source_unit": spec["source_unit"],
                    "value_origin": "reanalysis",
                    "conversion_rule": spec["conversion"],
                    "is_imputed": False,
                    "imputation_method": None,
                    "imputation_confidence": None,
                    "quality_flags": [],
                })
        if not rows:
            raise ValueError("ERA5-Land NetCDF contains no recognized variables")
        return {
            "status": "parsed",
            "source_id": "era5_land",
            "source_file": str(path),
            "rows": rows,
            "record_count": len(rows),
            "variables": variables_seen,
            "time_range": [rows[0]["observed_at"], rows[-1]["observed_at"]],
            "bbox": list(bbox) if bbox else None,
            "data_truth": "real_external_netcdf_or_official_schema_fixture",
        }
    finally:
        dataset.close()


def write_era5_land_csv(rows: list[dict[str, Any]], output_csv: Path) -> dict[str, Any]:
    fields = list(rows[0]) if rows else [
        "source_id", "source_file", "source_row", "station_id", "observed_at", "observed_at_utc",
        "observed_at_local", "time_status", "source_timezone", "longitude", "latitude", "variable_code",
        "source_parameter", "observed_value", "clean_value", "unit", "source_unit", "value_origin",
        "conversion_rule", "is_imputed", "imputation_method", "imputation_confidence", "quality_flags",
    ]
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row.get(key), (dict, list)) else row.get(key) for key in fields})
    return {"output_csv": str(output_csv), "rows": len(rows)}


def _credentials_present() -> bool:
    if os.environ.get("TAIHU_CDS_API_KEY"):
        return True
    candidates = [Path.home() / ".cdsapirc", Path.home() / ".config" / "cdsapi" / "config"]
    return any(path.is_file() and "key:" in path.read_text(encoding="utf-8", errors="ignore") for path in candidates)


def run_era5_land(
    start_year: int,
    end_year: int,
    bbox: tuple[float, float, float, float],
    variables: Iterable[str] = DEFAULT_VARIABLES,
    *,
    raw_root: Path | None = None,
    silver_root: Path | None = None,
    manifest_path: Path | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Download and parse year chunks, or produce a truthful BLOCKED_AUTH plan."""

    raw_root = Path(raw_root or STORAGE / "raw" / "era5_land")
    silver_root = Path(silver_root or STORAGE / "silver" / "era5_land")
    manifest_path = Path(manifest_path or STORAGE / "manifests" / f"era5_land_{start_year}_{end_year}.json")
    requests = [{"year": year, "request": build_cds_request(year, bbox, variables)} for year in range(start_year, end_year + 1)]
    credentials = _credentials_present() if client_factory is None else True
    if client_factory is None and not credentials:
        result = {
            "task_id": "P04-04", "status": "BLOCKED_AUTH", "data_truth": "official_request_plan_only",
            "dataset": DATASET, "requests": requests, "raw_root": str(raw_root), "silver_root": str(silver_root),
            "auth_probe": str(STORAGE / "manifests" / "cds_auth_probe.json"),
            "error_class": "MissingCDSConfiguration",
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    if client_factory is None:
        try:
            import cdsapi
            client = cdsapi.Client()
        except Exception as exc:
            result = {"task_id": "P04-04", "status": "BLOCKED_AUTH", "data_truth": "official_request_plan_only", "requests": requests, "error_class": type(exc).__name__}
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
    else:
        client = client_factory()
    rows: list[dict[str, Any]] = []
    years: list[dict[str, Any]] = []
    for item in requests:
        year = item["year"]
        target = raw_root / f"era5_land_{year}.nc"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.retrieve(DATASET, item["request"], str(target))
            asset_manifest = build_asset_manifest(
                source_id="era5_land",
                asset_id=f"era5_land_{year}",
                request_url="https://cds.climate.copernicus.eu/api",
                local_path=target,
                http_status=200,
                license_tag="Copernicus-C3S-CC-BY-4.0",
                redistribution_allowed="conditional",
                commercial_use="conditional",
                status="completed",
            )
            asset_manifest_path = manifest_root(PACKAGE_ROOT) / f"raw_era5_land_{year}.json"
            write_asset_manifest(asset_manifest, asset_manifest_path)
            parsed = parse_era5_land_netcdf(target, bbox)
            rows.extend(parsed["rows"])
            years.append({"year": year, "status": "completed", "netcdf": str(target), "asset_manifest": str(asset_manifest_path), "records": parsed["record_count"], "variables": parsed["variables"], "time_range": parsed["time_range"]})
        except Exception as exc:
            years.append({"year": year, "status": "failed", "netcdf": str(target), "error": str(exc)})
    silver = write_era5_land_csv(rows, silver_root / f"era5_land_{start_year}_{end_year}.csv") if rows else None
    result = {
        "task_id": "P04-04",
        "status": "completed" if years and all(item["status"] == "completed" for item in years) else "failed",
        "data_truth": "real_external_netcdf",
        "dataset": DATASET,
        "bbox": list(bbox),
        "variables": list(variables),
        "requests": requests,
        "years": years,
        "silver": silver,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
