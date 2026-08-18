from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ..normalize import _iso_time, _row


_CONTROL_ALIASES = {
    "value", "observed_value", "clean_value", "measurement", "measure", "val", "数值",
    "variable_code", "variable", "指标", "指标编码", "监测指标", "unit", "单位",
}
_CONTROL_CANONICAL = {
    "value": "value",
    "observedvalue": "observed_value",
    "cleanvalue": "clean_value",
    "measurement": "value",
    "measure": "value",
    "val": "value",
    "数值": "value",
    "variablecode": "variable_code",
    "variable": "variable_code",
    "指标": "variable_code",
    "指标编码": "variable_code",
    "监测指标": "variable_code",
    "unit": "unit",
    "单位": "unit",
    "sourceunit": "source_unit",
    "原始单位": "source_unit",
    "conversionrule": "conversion_rule",
    "转换规则": "conversion_rule",
}
_MISSING = {"", "-", "--", "na", "n/a", "null", "none", "nan", "-999", "-999.0"}


def _key(value: Any) -> str:
    return re.sub(r"[\s_\-()/]+", "", str(value).strip()).casefold()


def _load_alias_map(alias_path: Path | None = None) -> dict[str, str]:
    path = alias_path or Path(__file__).resolve().parents[2] / "config" / "aliases.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result: dict[str, str] = {}
    for canonical, aliases in (payload.get("aliases") or {}).items():
        result[_key(canonical)] = canonical
        for alias in aliases or []:
            result[_key(alias)] = canonical
    return result


def _canonical(value: Any, aliases: dict[str, str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    key = _key(text)
    return aliases.get(key) or _CONTROL_CANONICAL.get(key) or (text if text else None)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            values = list(sheet.iter_rows(values_only=True))
            if not values:
                return []
            headers = [str(value).strip() if value is not None else "" for value in values[0]]
            return [dict(zip(headers, row)) for row in values[1:]]
        finally:
            workbook.close()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ("records", "rows", "data", "items"):
                if isinstance(payload.get(key), list):
                    return [row for row in payload[key] if isinstance(row, dict)]
            return [payload]
    raise ValueError(f"unsupported local file type: {path.suffix}")


def _as_time(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    text = str(value).strip()
    normalized = _iso_time(text)
    if normalized:
        return normalized
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).isoformat() + "+00:00"
        except ValueError:
            continue
    return None


def _value(value: Any) -> tuple[Any, Any]:
    if value is None or str(value).strip().casefold() in _MISSING:
        return None, None
    try:
        return value, float(value)
    except (TypeError, ValueError):
        return value, value


def _coordinate(value: Any) -> Any:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _first(row: dict[str, Any], canonical: str, aliases: dict[str, str]) -> Any:
    for key, value in row.items():
        if _canonical(key, aliases) == canonical:
            return value
    return None


def normalize_local_file(path: Path, alias_path: Path | None = None) -> dict[str, Any]:
    """Convert a local wide or long table into the standard observation long form."""
    aliases = _load_alias_map(alias_path)
    rows = _read_rows(path)
    source_id = f"local_{path.stem}"
    observations: list[dict[str, Any]] = []
    for row_number, raw in enumerate(rows, start=2):
        canonical_headers = {_canonical(key, aliases): key for key in raw if _canonical(key, aliases)}
        time_value = _first(raw, "observed_at", aliases) or _first(raw, "acquisition_at", aliases)
        observed_at = _as_time(time_value)
        row_source = _first(raw, "source_id", aliases) or source_id
        station_id = _first(raw, "station_id", aliases)
        longitude = _first(raw, "longitude", aliases)
        latitude = _first(raw, "latitude", aliases)
        unit = _first(raw, "unit", aliases)
        source_unit = _first(raw, "source_unit", aliases) or unit
        conversion_rule = _first(raw, "conversion_rule", aliases)
        value_origin = _first(raw, "value_origin", aliases) or "observed"

        variable_value = _first(raw, "variable_code", aliases)
        long_value = None
        for key, value in raw.items():
            if _key(key) in {_key(item) for item in _CONTROL_ALIASES}:
                if _key(key) in {_key(item) for item in ("value", "observed_value", "clean_value", "measurement", "measure", "val", "数值")}:
                    long_value = value
                    break
        if variable_value is not None and long_value is not None:
            variable_code = _canonical(variable_value, aliases)
            observed_value, clean_value = _value(long_value)
            observations.append(
                _row(
                    source_id=str(row_source), source_file=path, source_row=str(row_number),
                    observed_at=observed_at, variable_code=variable_code or "unknown_variable",
                    observed_value=observed_value, clean_value=clean_value, unit=unit,
                    value_origin=str(value_origin), station_id=str(station_id) if station_id not in (None, "") else None,
                    longitude=_coordinate(longitude),
                    latitude=_coordinate(latitude),
                    source_parameter=str(variable_value),
                )
            )
            observations[-1]["source_unit"] = source_unit
            observations[-1]["conversion_rule"] = conversion_rule
            continue

        metadata = {"observed_at", "acquisition_at", "source_id", "station_id", "station_name", "lake_zone", "longitude", "latitude", "depth_m", "unit", "source_unit", "conversion_rule", "value_origin", "quality_flags", "is_imputed"}
        for header, raw_value in raw.items():
            variable_code = _canonical(header, aliases)
            if not variable_code or variable_code in metadata:
                continue
            observed_value, clean_value = _value(raw_value)
            observations.append(
                _row(
                    source_id=str(row_source), source_file=path, source_row=f"{row_number}:{header}",
                    observed_at=observed_at, variable_code=variable_code,
                    observed_value=observed_value, clean_value=clean_value, unit=unit,
                    value_origin=str(value_origin), station_id=str(station_id) if station_id not in (None, "") else None,
                    longitude=_coordinate(longitude),
                    latitude=_coordinate(latitude),
                    source_parameter=header,
                )
            )
    return {"observations": observations, "catalog": [], "archives": []}
