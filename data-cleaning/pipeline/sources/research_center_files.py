"""Adapter for legally downloaded national data-centre files.

This module is intentionally file-only: it does not automate account pages or
attempt to bypass an order.  A caller supplies the downloaded tabular file and
its metadata/authorization record.  The native monthly/quarterly cadence is
carried as metadata and is never expanded to daily records.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..normalize import _row
from ..time_contract import parse_time


MISSING_CODES = {"", "-", "--", "-999", "-999.0", "999999", "999999.0", "na", "n/a", "nan", "null", "none", "缺测", "///"}
_ALIASES = {
    "station_id": {"站号", "测站编号", "站点编号", "站点编码", "station_id", "station_code", "site_id"},
    "station_name": {"站名", "站点名称", "测站名称", "station_name", "site_name"},
    "time": {"时间", "日期", "观测时间", "采样时间", "监测时间", "date", "datetime", "timestamp", "time", "year_month", "month"},
    "variable": {"指标", "指标编码", "监测指标", "变量", "参数", "要素", "variable", "variable_code", "parameter", "element"},
    "value": {"数值", "观测值", "测量值", "实测值", "value", "observed_value", "measurement", "result"},
    "unit": {"单位", "量纲", "unit", "source_unit", "原始单位"},
    "quality": {"质量码", "质量标志", "质控码", "qc", "quality_code", "quality_flag"},
    "missing": {"缺测码", "缺测标识", "missing_code", "missing"},
    "longitude": {"经度", "lon", "lng", "longitude"},
    "latitude": {"纬度", "lat", "latitude"},
}
_META_HEADERS = {"station_id", "station_name", "time", "variable", "value", "unit", "longitude", "latitude", "quality", "missing"}
_UNITS = {
    "TN": ("total_nitrogen", "mg/L"), "TP": ("total_phosphorus", "mg/L"), "Chla": ("chlorophyll_a", "mg/L"),
    "chlorophyll_a": ("chlorophyll_a", "mg/L"), "DO": ("dissolved_oxygen", "mg/L"), "pH": ("pH", "pH"),
    "WT": ("water_temperature", "degC"), "water_temperature": ("water_temperature", "degC"),
}


def _key(value: Any) -> str:
    return re.sub(r"[\s_\-()/（）]+", "", str(value or "").strip()).casefold()


def _canonical(value: Any) -> str:
    k = _key(value)
    for name, aliases in _ALIASES.items():
        if k in {_key(item) for item in aliases}:
            return name
    return ""


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _delimiter(text: str, name: str) -> str:
    if Path(name).suffix.casefold() == ".tsv":
        return "\t"
    sample = "\n".join(text.splitlines()[:8])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return "\t" if "\t" in sample else ","


def _rows(raw: bytes, name: str) -> tuple[list[dict[str, Any]], str]:
    text, encoding = _decode(raw)
    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(text, name))
    return [dict(row) for row in reader], encoding


def _first(row: dict[str, Any], field: str) -> Any:
    for header, value in row.items():
        if _canonical(header) == field:
            return value
    return None


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _value(value: Any) -> tuple[Any, float | None, str | None]:
    if value is None:
        return None, None, None
    text = str(value).strip()
    if text.casefold() in MISSING_CODES:
        return value, None, text or ""
    try:
        return value, float(text), None
    except (TypeError, ValueError):
        return value, None, None


def _parse_metadata(metadata: dict[str, Any] | Path | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, Path):
        payload = json.loads(metadata.read_text(encoding="utf-8"))
    else:
        payload = dict(metadata)
    # Accept either a flat authorization record or a manifest-style license block.
    license_block = payload.get("license") if isinstance(payload.get("license"), dict) else {}
    for key in ("license_tag", "redistribution_allowed", "commercial_use", "attribution_text"):
        if key not in payload and key in license_block:
            payload[key] = license_block[key]
    payload["doi"] = payload.get("doi") or payload.get("dataset_doi")
    payload["application_number"] = payload.get("application_number") or payload.get("request_number") or payload.get("order_id")
    payload["native_frequency"] = payload.get("native_frequency") or payload.get("frequency") or payload.get("update_frequency")
    return payload


def _variables(row: dict[str, Any]):
    variable = _first(row, "variable")
    value = _first(row, "value")
    if variable not in (None, "") and value is not None:
        yield str(variable).strip(), value, _first(row, "unit")
        return
    for header, item in row.items():
        canonical = _canonical(header)
        if canonical in _META_HEADERS or canonical:
            continue
        if item not in (None, ""):
            yield str(header).strip(), item, _first(row, "unit")


def _normalize_rows(path_label: str, records: list[dict[str, Any]], metadata: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    source_timezone = metadata.get("source_timezone")
    native_frequency = metadata.get("native_frequency")
    observations: list[dict[str, Any]] = []
    for row_number, raw in enumerate(records, start=2):
        parsed_time = parse_time(_first(raw, "time"), source_timezone=source_timezone)
        station_id = _first(raw, "station_id")
        explicit_quality = _first(raw, "quality")
        explicit_missing = _first(raw, "missing")
        for parameter, raw_value_input, unit_input in _variables(raw):
            variable_code, inferred_unit = _UNITS.get(parameter, (parameter, None))
            raw_value, clean_value, missing_code = _value(raw_value_input)
            if explicit_missing not in (None, "") and str(explicit_missing).strip().casefold() not in {"0", "false", "no", "正常", "ok"}:
                missing_code = str(explicit_missing).strip()
                clean_value = None
            unit = str(unit_input).strip() if unit_input not in (None, "") else inferred_unit
            flags: list[str] = []
            if missing_code is not None:
                flags.append("RESEARCH_CENTER_MISSING")
            if not native_frequency:
                flags.append("NATIVE_FREQUENCY_UNDECLARED")
            if parsed_time["status"] != "accepted":
                flags.append("TIME_PENDING_METADATA")
            item = _row(
                source_id=source_id, source_file=Path(path_label), source_row=f"{row_number}:{parameter}",
                observed_at=parsed_time["utc"], variable_code=variable_code, observed_value=raw_value,
                clean_value=clean_value, unit=unit, value_origin="observed", station_id=str(station_id).strip() if station_id not in (None, "") else None,
                longitude=_num(_first(raw, "longitude")), latitude=_num(_first(raw, "latitude")), source_parameter=parameter,
                conversion_rule="research-centre source unit retained; native cadence not resampled", time_fields=parsed_time,
            )
            item.update({
                "raw_value": raw_value, "missing_code": missing_code, "quality_code": explicit_quality, "native_frequency": native_frequency,
                "frequency_source": "metadata" if native_frequency else None,
                "doi": metadata.get("doi"), "license_tag": metadata.get("license_tag"),
                "application_number": metadata.get("application_number"), "dataset_id": metadata.get("dataset_id"),
                "quality_flags": flags,
            })
            observations.append(item)
    return observations


def parse_research_center_bytes(raw: bytes, *, path_label: str, metadata: dict[str, Any] | None = None, source_id: str = "research_center_file") -> dict[str, Any]:
    meta = _parse_metadata(metadata)
    records, encoding = _rows(raw, path_label)
    observations = _normalize_rows(path_label, records, meta, source_id)
    return {"observations": observations, "input_rows": len(records), "encoding": encoding, "metadata": meta, "members": [path_label]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_research_center_file(input_path: Path, output_csv: Path | None = None, *, metadata: dict[str, Any] | Path | None = None, manifest_path: Path | None = None, source_id: str = "research_center_file") -> dict[str, Any]:
    """Parse a legally downloaded CSV/TXT/TSV/ZIP without changing cadence."""
    input_path = Path(input_path)
    meta = _parse_metadata(metadata)
    members: list[tuple[str, bytes]] = []
    if input_path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            members = [(name, archive.read(name)) for name in archive.namelist() if Path(name).suffix.casefold() in {".csv", ".txt", ".tsv"}]
    elif input_path.suffix.casefold() in {".csv", ".txt", ".tsv"}:
        members = [(input_path.name, input_path.read_bytes())]
    else:
        raise ValueError(f"unsupported research-centre file type: {input_path.suffix}")
    observations: list[dict[str, Any]] = []
    encodings: dict[str, str] = {}
    input_rows = 0
    for name, content in members:
        parsed = parse_research_center_bytes(content, path_label=f"{input_path}!{name}", metadata=meta, source_id=source_id)
        observations.extend(parsed["observations"])
        input_rows += parsed["input_rows"]
        encodings[name] = parsed["encoding"]
    if output_csv:
        _write_csv(Path(output_csv), observations)
    metadata_complete = bool(meta.get("doi") and meta.get("license_tag") and meta.get("application_number") and meta.get("native_frequency"))
    manifest = {
        "schema_version": "1.0", "manifest_type": "research_center_file", "source_id": source_id,
        "dataset_id": meta.get("dataset_id"), "doi": meta.get("doi"), "license_tag": meta.get("license_tag"),
        "redistribution_allowed": meta.get("redistribution_allowed"), "commercial_use": meta.get("commercial_use"),
        "attribution_text": meta.get("attribution_text"), "application_number": meta.get("application_number"),
        "native_frequency": meta.get("native_frequency"), "source_timezone": meta.get("source_timezone"),
        "provider": meta.get("provider"), "source_url": meta.get("source_url"), "authorization_evidence_path": meta.get("authorization_evidence_path"),
        "input_path": str(input_path), "checksum_sha256": _sha256(input_path), "members": [name for name, _ in members],
        "encodings": encodings, "input_rows": input_rows, "records": len(observations),
        "status": "completed" if metadata_complete else "BLOCKED_METADATA",
        "metadata_complete": metadata_complete, "cadence_policy": "native frequency retained; no upsampling or daily interpolation",
    }
    if manifest_path:
        manifest_path = Path(manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "output": str(output_csv) if output_csv else None, "manifest": str(manifest_path) if manifest_path else None}


__all__ = ["parse_research_center_bytes", "parse_research_center_file"]
