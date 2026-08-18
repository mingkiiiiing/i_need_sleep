from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CN_TZ = timezone(timedelta(hours=8))


def _iso_time(value: str | None) -> str | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc).isoformat()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y%m%d%H").replace(tzinfo=CN_TZ).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None


def _row(
    *,
    source_id: str,
    source_file: Path,
    source_row: str,
    observed_at: str | None,
    variable_code: str,
    observed_value: Any,
    clean_value: Any,
    unit: str | None,
    value_origin: str,
    station_id: str | None = None,
    longitude: float | None = None,
    latitude: float | None = None,
    scene_id: str | None = None,
    source_parameter: str | None = None,
    conversion_rule: str | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_file": str(source_file),
        "source_row": source_row,
        "station_id": station_id,
        "scene_id": scene_id,
        "observed_at": observed_at,
        "longitude": longitude,
        "latitude": latitude,
        "variable_code": variable_code,
        "source_parameter": source_parameter,
        "observed_value": observed_value,
        "clean_value": clean_value,
        "unit": unit,
        "source_unit": unit,
        "value_origin": value_origin,
        "conversion_rule": conversion_rule,
        "is_imputed": False,
        "imputation_method": None,
        "imputation_confidence": None,
        "quality_flags": [],
    }


def normalize_nasa_payload(path: Path, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    payload = envelope.get("payload", {})
    coords = payload.get("geometry", {}).get("coordinates", [None, None])
    longitude, latitude = coords[:2]
    station_id = f"NASA_POWER_{float(longitude):.3f}_{float(latitude):.3f}"
    parameters = payload.get("properties", {}).get("parameter", {})
    mapping = {
        "T2M": ("air_temperature", "degC", None),
        "WS10M": ("wind_speed", "m/s", None),
        "WD10M": ("wind_direction", "degree", None),
        "PRECTOTCORR": ("precipitation", "mm", "source mm/day divided by 24 for one-hour bucket"),
        "ALLSKY_SFC_SW_DWN": ("shortwave_radiation", "W/m2", "source Wh/m2 over one hour treated as average W/m2"),
    }
    times = sorted(parameters.get("T2M", {}).keys())
    rows: list[dict[str, Any]] = []
    for time_key in times:
        observed_at = _iso_time(time_key)
        for source_parameter, (variable_code, unit, conversion_rule) in mapping.items():
            observed_value = parameters.get(source_parameter, {}).get(time_key)
            clean_value = None if observed_value in (None, -999, -999.0) else float(observed_value)
            if clean_value is not None and source_parameter == "PRECTOTCORR":
                clean_value /= 24.0
            rows.append(
                _row(
                    source_id="nasa_power_hourly",
                    source_file=path,
                    source_row=f"{time_key}:{source_parameter}",
                    observed_at=observed_at,
                    variable_code=variable_code,
                    observed_value=observed_value,
                    clean_value=clean_value,
                    unit=unit,
                    value_origin="proxy",
                    station_id=station_id,
                    longitude=longitude,
                    latitude=latitude,
                    source_parameter=source_parameter,
                    conversion_rule=conversion_rule,
                )
            )
    return rows


def normalize_open_meteo_payload(path: Path, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    payload = envelope.get("payload", {})
    hourly = payload.get("hourly", {})
    units = payload.get("hourly_units", {})
    mapping = {
        "temperature_2m": ("air_temperature", "degC"),
        "wind_speed_10m": ("wind_speed", "m/s"),
        "wind_direction_10m": ("wind_direction", "degree"),
        "precipitation": ("precipitation", "mm"),
        "shortwave_radiation": ("shortwave_radiation", "W/m2"),
    }
    longitude = payload.get("longitude")
    latitude = payload.get("latitude")
    station_id = f"OPEN_METEO_{float(longitude):.3f}_{float(latitude):.3f}" if longitude is not None and latitude is not None else "OPEN_METEO_POINT"
    times = hourly.get("time", [])
    rows: list[dict[str, Any]] = []
    for index, time_value in enumerate(times, start=1):
        observed_at = _iso_time(str(time_value))
        for source_parameter, (variable_code, unit) in mapping.items():
            values = hourly.get(source_parameter, [])
            observed_value = values[index - 1] if index - 1 < len(values) else None
            clean_value = None if observed_value is None else float(observed_value)
            rows.append(
                _row(
                    source_id="open_meteo_forecast",
                    source_file=path,
                    source_row=f"{index}:{source_parameter}",
                    observed_at=observed_at,
                    variable_code=variable_code,
                    observed_value=observed_value,
                    clean_value=clean_value,
                    unit=unit,
                    value_origin="forecast_proxy",
                    station_id=station_id,
                    longitude=longitude,
                    latitude=latitude,
                    source_parameter=source_parameter,
                    conversion_rule=f"Open-Meteo hourly unit {units.get(source_parameter, 'unknown')}",
                )
            )
    return rows


def normalize_stac_payload(path: Path, envelope: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = envelope.get("payload", {})
    observations: list[dict[str, Any]] = []
    catalog: list[dict[str, Any]] = []
    for index, feature in enumerate(payload.get("features", []), start=1):
        properties = feature.get("properties", {})
        scene_id = feature.get("id")
        bbox = feature.get("bbox", [None, None, None, None])
        longitude = ((bbox[0] or 0) + (bbox[2] or 0)) / 2 if len(bbox) >= 4 else None
        latitude = ((bbox[1] or 0) + (bbox[3] or 0)) / 2 if len(bbox) >= 4 else None
        cloud = properties.get("eo:cloud_cover")
        observed_at = _iso_time(properties.get("datetime"))
        observations.append(
            _row(
                source_id="copernicus_sentinel2_stac",
                source_file=path,
                source_row=str(index),
                observed_at=observed_at,
                variable_code="cloud_cover",
                observed_value=cloud,
                clean_value=None if cloud is None else float(cloud),
                unit="percent",
                value_origin="remote_sensing",
                longitude=longitude,
                latitude=latitude,
                scene_id=scene_id,
                source_parameter="eo:cloud_cover",
            )
        )
        catalog.append(
            {
                "source_id": "copernicus_sentinel2_stac",
                "source_file": str(path),
                "source_row": str(index),
                "scene_id": scene_id,
                "acquisition_at": observed_at,
                "longitude": longitude,
                "latitude": latitude,
                "cloud_cover": cloud,
                "asset_names": sorted(feature.get("assets", {}).keys()),
                "product_href": feature.get("assets", {}).get("Product", {}).get("href"),
            }
        )
    return observations, catalog


def normalize_zenodo_payload(path: Path, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    payload = envelope.get("payload", {})
    files = payload.get("files", [])
    return [
        {
            "source_id": "taihu_thqbca_zenodo",
            "source_file": str(path),
            "source_row": str(index),
            "title": payload.get("metadata", {}).get("title"),
            "doi": payload.get("metadata", {}).get("doi"),
            "file_key": item.get("key"),
            "file_size_bytes": item.get("size"),
            "checksum": item.get("checksum"),
            "download_url": item.get("links", {}).get("self"),
            "archive_downloaded": False,
        }
        for index, item in enumerate(files, start=1)
    ]


def normalize_raw_file(path: Path) -> dict[str, Any]:
    source_id = path.parent.name
    if path.suffix.casefold() in {".csv", ".tsv", ".xlsx"}:
        from .sources.local_files import normalize_local_file

        return normalize_local_file(path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if source_id == "nasa_power_hourly":
        return {"observations": normalize_nasa_payload(path, envelope), "catalog": [], "archives": []}
    if source_id == "open_meteo_forecast":
        return {"observations": normalize_open_meteo_payload(path, envelope), "catalog": [], "archives": []}
    if source_id.startswith("water_station"):
        from .sources.water_station import normalize_water_station_payload

        return {"observations": normalize_water_station_payload(path, envelope), "catalog": [], "archives": []}
    if source_id == "copernicus_sentinel2_stac":
        observations, catalog = normalize_stac_payload(path, envelope)
        return {"observations": observations, "catalog": catalog, "archives": []}
    if source_id == "taihu_thqbca_zenodo":
        return {"observations": [], "catalog": [], "archives": normalize_zenodo_payload(path, envelope)}
    if path.suffix.casefold() in {".csv", ".tsv", ".xlsx"} or source_id in {"local", "local_files"}:
        from .sources.local_files import normalize_local_file

        return normalize_local_file(path)
    return {"observations": [], "catalog": [], "archives": []}
