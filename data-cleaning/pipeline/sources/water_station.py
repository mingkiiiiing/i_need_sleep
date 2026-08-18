from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .common import IngestResult, request_json, utc_now, write_raw_json
from .local_files import _as_time, _canonical, _coordinate, _first, _key, _load_alias_map, _read_rows, _value
from ..normalize import _row


DEFAULT_UNITS = {
    "chlorophyll_a": "mg/L",
    "algae_density": "cells/L",
    "water_temperature": "degC",
    "total_nitrogen": "mg/L",
    "total_phosphorus": "mg/L",
    "pH": "pH",
    "dissolved_oxygen": "mg/L",
    "ammonia_nitrogen": "mg/L",
    "cod_mn": "mg/L",
    "water_level": "m",
    "flow_velocity": "m/s",
}
_VALUE_HEADERS = {"value", "observed_value", "clean_value", "measurement", "measure", "val", "数值"}
_METADATA = {"observed_at", "acquisition_at", "source_id", "station_id", "station_name", "lake_zone", "longitude", "latitude", "depth_m", "unit", "source_unit", "conversion_rule", "value_origin", "quality_flags", "is_imputed"}


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("records", "rows", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
        return [payload]
    return []


def normalize_water_station_rows(path: Path, rows: list[dict[str, Any]], *, source_id: str = "water_station_endpoint") -> list[dict[str, Any]]:
    """Normalize MEE-compatible wide/long station records.

    The parser accepts Chinese names, standard aliases and MEE protocol codes
    such as ``w01016`` (chlorophyll-a), ``w19011`` (algae density) and
    ``e01001`` (water temperature). It does not infer units when a variable is
    unknown; configured defaults are only used for the listed protocol fields.
    """

    aliases = _load_alias_map()
    observations: list[dict[str, Any]] = []
    for row_number, raw in enumerate(rows, start=1):
        time_value = _first(raw, "observed_at", aliases) or _first(raw, "acquisition_at", aliases)
        observed_at = _as_time(time_value)
        row_source = _first(raw, "source_id", aliases) or source_id
        station_id = _first(raw, "station_id", aliases)
        longitude = _first(raw, "longitude", aliases)
        latitude = _first(raw, "latitude", aliases)
        explicit_unit = _first(raw, "unit", aliases)
        source_unit = _first(raw, "source_unit", aliases) or explicit_unit
        value_origin = _first(raw, "value_origin", aliases) or "observed"
        variable_value = _first(raw, "variable_code", aliases)
        long_value = None
        for key, value in raw.items():
            if _key(key) in {_key(item) for item in _VALUE_HEADERS}:
                long_value = value
                break
        if variable_value is not None and long_value is not None:
            variable_code = _canonical(variable_value, aliases) or "unknown_variable"
            observed_value, clean_value = _value(long_value)
            unit = explicit_unit or DEFAULT_UNITS.get(variable_code)
            observations.append(_row(source_id=str(row_source), source_file=path, source_row=str(row_number), observed_at=observed_at, variable_code=variable_code, observed_value=observed_value, clean_value=clean_value, unit=unit, value_origin=str(value_origin), station_id=str(station_id) if station_id not in (None, "") else None, longitude=_coordinate(longitude), latitude=_coordinate(latitude), source_parameter=str(variable_value)))
            observations[-1]["source_unit"] = source_unit or unit
            observations[-1]["conversion_rule"] = _first(raw, "conversion_rule", aliases)
            continue
        for header, raw_value in raw.items():
            variable_code = _canonical(header, aliases)
            if not variable_code or variable_code in _METADATA or variable_code not in DEFAULT_UNITS:
                continue
            observed_value, clean_value = _value(raw_value)
            unit = explicit_unit or DEFAULT_UNITS.get(variable_code)
            observations.append(_row(source_id=str(row_source), source_file=path, source_row=f"{row_number}:{header}", observed_at=observed_at, variable_code=variable_code, observed_value=observed_value, clean_value=clean_value, unit=unit, value_origin=str(value_origin), station_id=str(station_id) if station_id not in (None, "") else None, longitude=_coordinate(longitude), latitude=_coordinate(latitude), source_parameter=header))
            observations[-1]["source_unit"] = source_unit or unit
    return observations


def normalize_water_station_file(path: Path, *, source_id: str | None = None) -> list[dict[str, Any]]:
    return normalize_water_station_rows(path, _read_rows(path), source_id=source_id or f"water_station_{path.stem}")


def write_water_station_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if columns:
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def run_water_station_parse(input_path: Path, output_path: Path, *, source_id: str | None = None) -> dict[str, Any]:
    rows = normalize_water_station_file(input_path, source_id=source_id)
    count = write_water_station_csv(output_path, rows)
    return {"status": "completed", "input": str(input_path), "output": str(output_path), "rows": count, "variables": sorted({row["variable_code"] for row in rows})}


def normalize_water_station_payload(path: Path, envelope: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_water_station_rows(path, _payload_rows(envelope.get("payload", {})), source_id=path.parent.name)


def ingest_water_station_endpoint(url: str, *, source_id: str = "water_station_endpoint") -> IngestResult:
    """Fetch an authenticated/public station JSON endpoint and preserve raw data.

    No endpoint URL is hard-coded because official portals commonly require
    station authorization. The caller must supply the endpoint and handle any
    required gateway credentials outside the repository.
    """

    retrieved_at = utc_now()
    try:
        status, content_type, payload = request_json(url)
        records = len(_payload_rows(payload))
        raw_path = write_raw_json(source_id, url, status, content_type, payload)
        return IngestResult(source_id, "ingested" if status == 200 and records else "failed", url, str(raw_path), records, retrieved_at, metadata={"record_count": records, "endpoint_supplied_by_user": True})
    except Exception as exc:
        return IngestResult(source_id, "failed", url, None, 0, retrieved_at, str(exc))
