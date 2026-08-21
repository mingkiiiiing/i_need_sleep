from __future__ import annotations

import json
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .time_contract import parse_time
from .units import standardize_units


CN_TZ = timezone(timedelta(hours=8))


def _iso_time(value: str | None, *, source_timezone: str | None = None) -> str | None:
    return parse_time(value, source_timezone=source_timezone)["utc"]


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
    time_fields: dict[str, str | None] | None = None,
    raw_unit: str | None = None,
) -> dict[str, Any]:
    parsed_time = time_fields or {
        "status": "accepted" if observed_at else "pending_timezone",
        "utc": observed_at,
        "local": None,
        "source_timezone": None,
    }
    return {
        "source_id": source_id,
        "source_file": str(source_file),
        "source_row": source_row,
        "station_id": station_id,
        "scene_id": scene_id,
        "observed_at": observed_at,
        "observed_at_utc": parsed_time.get("utc"),
        "observed_at_local": parsed_time.get("local"),
        "time_status": parsed_time.get("status"),
        "source_timezone": parsed_time.get("source_timezone"),
        "longitude": longitude,
        "latitude": latitude,
        "variable_code": variable_code,
        "source_parameter": source_parameter,
        "observed_value": observed_value,
        # The raw pair is immutable lineage.  ``observed_value`` remains for
        # backwards compatibility, while these fields are consumed by the
        # standardized SQLite/CSV contract and must survive unit conversion.
        "raw_value": observed_value,
        "clean_value": clean_value,
        "unit": unit,
        "source_unit": unit,
        "raw_unit": raw_unit if raw_unit is not None else unit,
        "value_origin": value_origin,
        "conversion_rule": conversion_rule,
        "is_imputed": False,
        "imputation_method": None,
        "imputation_confidence": None,
        "quality_flags": [],
    }


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_station_mapping(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load an explicit station master mapping; never infer IDs from names."""

    if path is None or not Path(path).exists():
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    path = Path(path)
    if path.suffix.casefold() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("stations", payload.get("records", []))
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        canonical = str(item.get("station_id") or item.get("canonical_station_id") or "").strip()
        if not canonical:
            continue
        value = dict(item)
        for key in ("source_station_id", "station_id", "station_name", "source_station_name", "name"):
            token = str(item.get(key) or "").strip()
            if token:
                mapping[token.casefold()] = value
    return mapping


def standardize_observation_rows(
    records: list[dict[str, Any]],
    *,
    station_mapping_path: Path | None = None,
    default_timezone: str | None = None,
) -> dict[str, Any]:
    """Apply the P09-02 field/type/time/coordinate/station contract.

    This operation is intentionally non-destructive: source values and units
    are copied to ``raw_value``/``raw_unit`` before canonical unit conversion.
    Naive timestamps remain ``pending_timezone`` unless an explicit row or
    caller timezone is supplied.  Station IDs are mapped only through an
    explicit master file; unresolved names are flagged rather than guessed.
    """

    station_map = _load_station_mapping(station_mapping_path)
    for row in records:
        if "raw_value" not in row:
            row["raw_value"] = row.get("observed_value", row.get("clean_value"))
        if "raw_unit" not in row:
            row["raw_unit"] = row.get("source_unit", row.get("unit"))

        # Canonical scalar types.  Do not overwrite raw_value.
        if row.get("clean_value") is not None:
            converted = _as_float(row.get("clean_value"))
            if converted is not None:
                row["clean_value"] = converted
        row["longitude"] = _as_float(row.get("longitude"))
        row["latitude"] = _as_float(row.get("latitude"))
        row["depth_m"] = _as_float(row.get("depth_m"))
        if row.get("station_id") not in (None, ""):
            row["station_id"] = str(row["station_id"]).strip()

        # Explicit station master mapping.  A station_id already equal to the
        # canonical key is accepted as identity; otherwise unresolved values
        # stay visible for P09-07/P09-08 instead of being renamed heuristically.
        station_token = str(row.get("station_id") or row.get("station_name") or "").strip()
        mapped = station_map.get(station_token.casefold()) if station_token else None
        if mapped:
            row["station_id_raw"] = row.get("station_id")
            row["station_id"] = str(mapped.get("station_id") or mapped.get("canonical_station_id")).strip()
            row["station_mapping_status"] = "mapped"
            if row.get("station_name") in (None, ""):
                row["station_name"] = mapped.get("station_name") or mapped.get("name")
            if row.get("longitude") is None:
                row["longitude"] = _as_float(mapped.get("longitude"))
            if row.get("latitude") is None:
                row["latitude"] = _as_float(mapped.get("latitude"))
        elif station_token:
            row["station_id_raw"] = row.get("station_id")
            row["station_mapping_status"] = "identity" if row.get("station_id") else "unmapped"
        else:
            row["station_mapping_status"] = "missing"

        # Time contract: keep the input field, derive UTC/local only with an
        # explicit timezone, and expose a deterministic status for QC.
        if not row.get("observed_at_utc") and row.get("observed_at") not in (None, ""):
            source_timezone = row.get("source_timezone") or default_timezone
            parsed = parse_time(row.get("observed_at"), source_timezone=source_timezone)
            row["observed_at_utc"] = parsed.get("utc")
            row["observed_at_local"] = parsed.get("local")
            row["time_status"] = parsed.get("status")
            row["source_timezone"] = parsed.get("source_timezone")
        elif "time_status" not in row:
            row["time_status"] = "missing" if row.get("observed_at") in (None, "") else "accepted"

        lon, lat = row.get("longitude"), row.get("latitude")
        row["coordinate_status"] = "missing"
        if lon is not None and lat is not None:
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                row["coordinate_status"] = "accepted"
                if 119.5 <= lon <= 121.0 and 30.8 <= lat <= 31.7:
                    row["study_area_coordinate"] = True
                else:
                    row["study_area_coordinate"] = False
            else:
                row["coordinate_status"] = "out_of_range"
                row["study_area_coordinate"] = False
        row.setdefault("crs_epsg", 4326)

    standardized = standardize_units(records)["records"]
    # Unit conversion must never mutate the raw pair.
    for row in standardized:
        row.setdefault("raw_value", row.get("observed_value"))
        row.setdefault("raw_unit", row.get("source_unit", row.get("unit")))
    return {"records": standardized, "station_mapping_count": sum(1 for row in standardized if row.get("station_mapping_status") == "mapped")}


def normalize_nasa_payload(path: Path, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    payload = envelope.get("payload", {})
    coords = payload.get("geometry", {}).get("coordinates", [None, None])
    longitude, latitude = coords[:2]
    station_id = f"NASA_POWER_{float(longitude):.3f}_{float(latitude):.3f}"
    parameters = payload.get("properties", {}).get("parameter", {})
    header = payload.get("header", {})
    # NASA POWER compact timestamps are timezone-naive. Only use a timezone
    # when the payload explicitly supplies one; otherwise records are marked
    # pending instead of being silently interpreted as UTC.
    source_timezone = header.get("timezone") if isinstance(header, dict) else None
    if not source_timezone and isinstance(header, dict):
        time_standard = str(header.get("time_standard") or "").upper()
        if time_standard == "UTC":
            source_timezone = "UTC"
        elif time_standard == "LST":
            # NASA POWER's LST is local standard time.  Taihu is at roughly
            # 120E, so retain the explicit Asia/Shanghai mapping in lineage.
            source_timezone = "Asia/Shanghai"
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
        time_fields = parse_time(time_key, source_timezone=source_timezone)
        observed_at = time_fields["utc"]
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
                    time_fields=time_fields,
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
    source_timezone = payload.get("timezone")
    station_id = f"OPEN_METEO_{float(longitude):.3f}_{float(latitude):.3f}" if longitude is not None and latitude is not None else "OPEN_METEO_POINT"
    times = hourly.get("time", [])
    rows: list[dict[str, Any]] = []
    for index, time_value in enumerate(times, start=1):
        time_fields = parse_time(str(time_value), source_timezone=source_timezone)
        observed_at = time_fields["utc"]
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
                    time_fields=time_fields,
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
        time_fields = parse_time(properties.get("datetime"))
        observed_at = time_fields["utc"]
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
                time_fields=time_fields,
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
