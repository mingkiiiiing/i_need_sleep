"""Offline adapter for legally downloaded CMA historical station files.

The adapter deliberately does not log in to, scrape, or bypass any CMA service.
It accepts a user-provided CSV/TXT/ZIP export and converts it to the standard
observation contract while retaining the source row, station, local/UTC time,
missing marker, quality code, and source unit for auditability.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..normalize import _row
from ..time_contract import parse_time


DEFAULT_TZ = "Asia/Shanghai"
MISSING_CODES = {
    "", "-", "--", "-999", "-999.0", "999999", "999999.0", "9999999",
    "na", "n/a", "nan", "null", "none", "///", "...", "缺测", "缺省",
}

_ALIASES: dict[str, set[str]] = {
    "station_id": {"站号", "区站号", "站点编号", "站点编码", "测站编号", "station_id", "station_code", "station"},
    "station_name": {"站名", "站点名称", "测站名称", "station_name", "site_name"},
    "local_time": {"时间", "日期", "观测时间", "观测日期", "北京时", "北京时间", "本地时间", "local_time", "datetime", "date", "time", "obs_time"},
    "utc_time": {"utc时间", "utc时", "utc", "观测时间utc", "timestamp_utc", "utc_time"},
    "longitude": {"经度", "lon", "lng", "longitude"},
    "latitude": {"纬度", "lat", "latitude"},
    "variable": {"要素", "要素代码", "要素名", "变量", "变量代码", "参数", "element", "element_code", "variable", "variable_code", "parameter"},
    "value": {"数值", "观测值", "观测数据", "测量值", "value", "observed_value", "measurement", "result"},
    "unit": {"单位", "单位代码", "量纲", "unit", "source_unit", "原始单位"},
    "missing": {"缺测码", "缺测标识", "缺测值", "missing_code", "missing", "missing_flag"},
    "quality": {"质量码", "质量标志", "质控码", "质控标志", "质量控制码", "qc", "qa", "quality_code", "quality_flag", "status_code"},
}

_UNIT_BY_VARIABLE: dict[str, tuple[str, str]] = {
    "TEM": ("air_temperature", "degC"), "TEM_AVG": ("air_temperature", "degC"),
    "TEM_MAX": ("air_temperature", "degC"), "TEM_MIN": ("air_temperature", "degC"),
    "PRE": ("precipitation", "mm"), "PRE_1H": ("precipitation", "mm"), "PRE_DAY": ("precipitation", "mm"),
    "WIN_S_Avg": ("wind_speed", "m/s"), "WIN_S_Max": ("wind_speed", "m/s"), "WS10M": ("wind_speed", "m/s"),
    "WIN_D_Avg": ("wind_direction", "degree"), "WIN_D_Max": ("wind_direction", "degree"), "WD10M": ("wind_direction", "degree"),
    "RHU": ("relative_humidity", "%"), "RH": ("relative_humidity", "%"),
    "PRS": ("air_pressure", "hPa"), "PRS_SEA": ("air_pressure", "hPa"),
    "SSD": ("sunshine_duration", "h"), "SSH": ("shortwave_radiation", "W/m2"),
}


def _key(value: Any) -> str:
    return re.sub(r"[\s_\-()/（）]+", "", str(value or "").strip()).casefold()


def _canonical_header(value: Any) -> str:
    key = _key(value)
    for canonical, aliases in _ALIASES.items():
        if key in {_key(item) for item in aliases}:
            return canonical
    return ""


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _delimiter(text: str, suffix: str) -> str:
    if suffix.casefold() == ".tsv":
        return "\t"
    sample = "\n".join(text.splitlines()[:8])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return "\t" if "\t" in sample else ","


def _read_member(raw: bytes, name: str) -> tuple[list[dict[str, Any]], str]:
    text, encoding = _decode(raw)
    delimiter = _delimiter(text, Path(name).suffix)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [dict(row) for row in reader], encoding


def _value(raw: Any) -> tuple[Any, float | None, str | None]:
    if raw is None:
        return None, None, None
    text = str(raw).strip()
    if text.casefold() in MISSING_CODES:
        return raw, None, text or ""
    try:
        return raw, float(text), None
    except (TypeError, ValueError):
        return raw, None, None


def _first(raw: dict[str, Any], canonical: str) -> Any:
    for header, value in raw.items():
        if _canonical_header(header) == canonical:
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _time_fields(raw: dict[str, Any], source_timezone: str) -> tuple[dict[str, str | None], str | None]:
    utc_value = _first(raw, "utc_time")
    local_value = _first(raw, "local_time")
    if utc_value not in (None, ""):
        parsed = parse_time(utc_value, source_timezone="UTC")
        return parsed, "UTC"
    parsed = parse_time(local_value, source_timezone=source_timezone)
    return parsed, source_timezone


def _variables(raw: dict[str, Any]) -> Iterable[tuple[str, Any, Any]]:
    variable = _first(raw, "variable")
    value = _first(raw, "value")
    if variable not in (None, "") and value is not None:
        yield str(variable).strip(), value, _first(raw, "unit")
        return
    metadata = {"station_id", "station_name", "local_time", "utc_time", "longitude", "latitude", "unit", "missing", "quality"}
    for header, item in raw.items():
        if _canonical_header(header) in metadata or item in (None, ""):
            continue
        # A column that is itself a known control field is not a measurement.
        if _canonical_header(header) in {"variable", "value"}:
            continue
        yield str(header).strip(), item, _first(raw, "unit")


def _one_row(path_label: str, row_number: int, raw: dict[str, Any], source_id: str, source_timezone: str) -> list[dict[str, Any]]:
    time_fields, effective_tz = _time_fields(raw, source_timezone)
    station = _first(raw, "station_id")
    quality = _first(raw, "quality")
    explicit_missing = _first(raw, "missing")
    rows: list[dict[str, Any]] = []
    for variable_raw, value_raw, unit_raw in _variables(raw):
        variable_key = variable_raw.strip()
        variable_code, inferred_unit = _UNIT_BY_VARIABLE.get(variable_key, (variable_key, None))
        source_unit = str(unit_raw).strip() if unit_raw not in (None, "") else inferred_unit
        raw_value, clean_value, missing_code = _value(value_raw)
        if explicit_missing not in (None, "") and str(explicit_missing).strip().casefold() not in {"0", "false", "no", "正常", "ok"}:
            missing_code = str(explicit_missing).strip()
            clean_value = None
        flags: list[str] = []
        if missing_code is not None:
            flags.append("CMA_MISSING")
        if quality not in (None, ""):
            flags.append(f"CMA_QC_{str(quality).strip()}")
        if source_unit is None:
            flags.append("CMA_UNIT_PENDING")
        item = _row(
            source_id=source_id, source_file=Path(path_label), source_row=f"{row_number}:{variable_raw}",
            observed_at=time_fields.get("utc"), variable_code=variable_code,
            observed_value=raw_value, clean_value=clean_value, unit=source_unit,
            value_origin="observed", station_id=str(station).strip() if station not in (None, "") else None,
            longitude=_number(_first(raw, "longitude")), latitude=_number(_first(raw, "latitude")),
            source_parameter=variable_raw, conversion_rule="CMA source unit retained; no implicit conversion",
            time_fields=time_fields,
        )
        item.update({"raw_value": raw_value, "missing_code": missing_code, "quality_code": quality,
                     "source_unit": source_unit, "quality_flags": flags, "source_timezone": effective_tz})
        rows.append(item)
    return rows


def parse_cma_bytes(raw: bytes, *, path_label: str = "cma_file.csv", source_id: str = "cma_history_file", source_timezone: str = DEFAULT_TZ) -> dict[str, Any]:
    """Parse one CSV/TXT byte stream; public for deterministic unit tests."""
    records, encoding = _read_member(raw, path_label)
    observations = [item for index, row in enumerate(records, start=2) for item in _one_row(path_label, index, row, source_id, source_timezone)]
    return {"observations": observations, "encoding": encoding, "encodings": {path_label: encoding}, "rows": len(records), "members": [path_label]}


def parse_cma_file(input_path: Path, output_csv: Path | None = None, *, source_id: str = "cma_history_file", source_timezone: str = DEFAULT_TZ) -> dict[str, Any]:
    """Parse CSV/TXT or every tabular member of a ZIP archive."""
    input_path = Path(input_path)
    members: list[tuple[str, bytes]] = []
    if input_path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            members = [(name, archive.read(name)) for name in archive.namelist() if Path(name).suffix.casefold() in {".csv", ".txt", ".tsv"}]
    elif input_path.suffix.casefold() in {".csv", ".txt", ".tsv"}:
        members = [(input_path.name, input_path.read_bytes())]
    else:
        raise ValueError(f"unsupported CMA file type: {input_path.suffix}")
    all_rows: list[dict[str, Any]] = []
    encodings: dict[str, str] = {}
    input_rows = 0
    for name, content in members:
        parsed = parse_cma_bytes(content, path_label=f"{input_path}!{name}", source_id=source_id, source_timezone=source_timezone)
        all_rows.extend(parsed["observations"])
        input_rows += parsed["rows"]
        encodings[name] = parsed["encoding"]
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        fields = sorted({key for row in all_rows for key in row})
        with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
    missing = sum(1 for row in all_rows if row.get("missing_code") is not None)
    quality = sum(1 for row in all_rows if row.get("quality_code") not in (None, ""))
    return {"status": "completed", "input": str(input_path), "members": [name for name, _ in members], "encodings": encodings,
            "input_rows": input_rows, "records": len(all_rows), "missing_records": missing, "quality_code_records": quality,
            "output": str(output_csv) if output_csv else None, "source_timezone_default": source_timezone,
            "time_contract": "naive CMA timestamps interpreted as Asia/Shanghai and paired with UTC; explicit UTC is honored"}


__all__ = ["parse_cma_bytes", "parse_cma_file", "MISSING_CODES"]
