from __future__ import annotations

"""Compliance-first boundary probe for the MWR HFC water/rain service.

``https://hfc.mwr.cn/`` is an official public entry page, but a public page is
not proof of an openly documented machine API or redistribution permission.
This module never reverse-engineers Ajax requests.  It records the static
page signal and provides a parser for a legally supplied CSV/JSON/XLSX export.
"""

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from ..normalize import _row
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest
from ..time_contract import parse_time
from .common import PACKAGE_ROOT, RAW_ROOT, utc_now


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
MWR_HFC_URL = "https://hfc.mwr.cn/"
SOURCE_ID = "mwr_hfc"
DEFAULT_SOURCE_TIMEZONE = "Asia/Shanghai"
MISSING_CODES = {"", "-", "--", "-999", "-999.0", "999999", "999999.0", "na", "n/a", "nan", "null", "none", "缺测", "///"}

_ALIASES = {
    "station_id": {"站号", "站点编号", "测站编号", "站点编码", "station_id", "station_code", "site_id"},
    "station_name": {"站名", "站点名称", "测站名称", "station_name", "site_name"},
    "time": {"时间", "日期", "观测时间", "监测时间", "数据时间", "发布时间", "datetime", "date", "timestamp", "time"},
    "variable": {"指标", "要素", "变量", "参数", "监测指标", "variable", "variable_code", "parameter", "element"},
    "value": {"数值", "观测值", "测量值", "实测值", "值", "value", "observed_value", "measurement", "result"},
    "unit": {"单位", "量纲", "unit", "source_unit", "原始单位"},
    "quality": {"质量码", "质量标志", "质控码", "qc", "quality_code", "quality_flag", "status"},
    "missing": {"缺测码", "缺测标识", "missing_code", "missing"},
    "longitude": {"经度", "lon", "lng", "longitude"},
    "latitude": {"纬度", "lat", "latitude"},
}
_VARIABLES = {
    "水位": ("water_level", "m"),
    "water_level": ("water_level", "m"),
    "雨量": ("precipitation", "mm"),
    "降雨": ("precipitation", "mm"),
    "降水": ("precipitation", "mm"),
    "precipitation": ("precipitation", "mm"),
    "流量": ("discharge", "m3/s"),
    "入流": ("inflow_discharge", "m3/s"),
    "出流": ("outflow_discharge", "m3/s"),
    "discharge": ("discharge", "m3/s"),
}


def _key(value: Any) -> str:
    return re.sub(r"[\s_\-()/（）]+", "", str(value or "").strip()).casefold()


def _canonical(value: Any) -> str:
    key = _key(value)
    for name, aliases in _ALIASES.items():
        if key in {_key(item) for item in aliases}:
            return name
    return ""


def _first(row: dict[str, Any], field: str) -> Any:
    for header, value in row.items():
        if _canonical(header) == field:
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_rows(raw: bytes, suffix: str) -> tuple[list[dict[str, Any]], str]:
    suffix = suffix.casefold()
    if suffix == ".json":
        payload = json.loads(_decode(raw))
        if isinstance(payload, dict):
            payload = payload.get("records") or payload.get("data") or payload.get("rows") or []
        if not isinstance(payload, list):
            raise ValueError("MWR JSON export must contain a list or records/data/rows list")
        return [dict(item) for item in payload if isinstance(item, dict)], "json"
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = workbook.active
        values = list(sheet.values)
        if not values:
            return [], "xlsx"
        headers = [str(item or "") for item in values[0]]
        return [dict(zip(headers, row)) for row in values[1:] if any(item not in (None, "") for item in row)], "xlsx"
    text = _decode(raw)
    sample = "\n".join(text.splitlines()[:8])
    delimiter = "\t" if "\t" in sample else ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        pass
    return [dict(row) for row in csv.DictReader(io.StringIO(text), delimiter=delimiter)], "csv"


def _variable_rows(raw: dict[str, Any]):
    variable = _first(raw, "variable")
    value = _first(raw, "value")
    if variable not in (None, "") and value is not None:
        yield str(variable).strip(), value, _first(raw, "unit")
        return
    metadata = {"station_id", "station_name", "time", "unit", "quality", "missing", "longitude", "latitude"}
    for header, value in raw.items():
        if _canonical(header) in metadata or value in (None, ""):
            continue
        yield str(header).strip(), value, None


def _normalize_rows(records: list[dict[str, Any]], *, source_file: str, source_timezone: str) -> tuple[list[dict[str, Any]], list[str]]:
    observations: list[dict[str, Any]] = []
    warnings: list[str] = []
    for row_number, raw in enumerate(records, start=2):
        time_fields = parse_time(_first(raw, "time"), source_timezone=source_timezone)
        station = _first(raw, "station_id") or _first(raw, "station_name")
        for variable_raw, value_raw, unit_raw in _variable_rows(raw):
            variable_key = variable_raw.strip()
            variable_code, inferred_unit = _VARIABLES.get(variable_key, _VARIABLES.get(variable_key.casefold(), (variable_key, None)))
            raw_text = "" if value_raw is None else str(value_raw).strip()
            missing_code = raw_text if raw_text.casefold() in MISSING_CODES else None
            clean_value = None if missing_code else _number(value_raw)
            unit = str(unit_raw).strip() if unit_raw not in (None, "") else inferred_unit
            flags: list[str] = []
            if missing_code:
                flags.append("MWR_MISSING")
            if time_fields.get("status") != "accepted":
                flags.append("MWR_TIME_PENDING")
            if unit is None:
                flags.append("MWR_UNIT_PENDING")
            item = _row(
                source_id=SOURCE_ID,
                source_file=Path(source_file),
                source_row=f"{row_number}:{variable_raw}",
                observed_at=time_fields.get("utc"),
                variable_code=variable_code,
                observed_value=value_raw,
                clean_value=clean_value,
                unit=unit,
                value_origin="observed",
                station_id=str(station).strip() if station not in (None, "") else None,
                longitude=_number(_first(raw, "longitude")),
                latitude=_number(_first(raw, "latitude")),
                source_parameter=variable_raw,
                conversion_rule="MWR manual-export unit retained; no inferred unit conversion",
                time_fields=time_fields,
            )
            item.update({
                "station_name": _first(raw, "station_name"),
                "raw_value": value_raw,
                "quality_code": _first(raw, "quality"),
                "missing_code": missing_code,
                "quality_flags": flags,
                "proxy_flag": 0,
                "source_timezone": source_timezone,
            })
            observations.append(item)
    if not observations:
        warnings.append("MWR_NO_NORMALIZABLE_RECORDS")
    return observations, warnings


def inspect_mwr_hfc_html(html: str, *, page_url: str = MWR_HFC_URL) -> dict[str, Any]:
    """Classify only the public page shell; do not discover private endpoints."""

    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    has_table = bool(re.search(r"<table\b", html, flags=re.I))
    has_json_bootstrap = bool(re.search(r"__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__", html, flags=re.I))
    scripts = len(re.findall(r"<script\b", html, flags=re.I))
    fingerprint = hashlib.sha256((re.sub(r"\d+", "#", text[:2000]) + f"|table={has_table}|scripts={scripts}").encode("utf-8")).hexdigest()
    return {
        "source_id": SOURCE_ID,
        "page_url": page_url,
        "title": re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else None,
        "html_bytes": len(html.encode("utf-8")),
        "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "dom_fingerprint": fingerprint,
        "has_table": has_table,
        "has_json_bootstrap": has_json_bootstrap,
        "script_count": scripts,
        "mentions_water_rain": any(word in text for word in ("水位", "雨情", "水情")),
        "machine_api_verified": False,
        "classification": "PUBLIC_HTML_DATA_PAGE_ENDPOINT_UNVERIFIED" if has_table else "PUBLIC_HTML_SHELL_ENDPOINT_UNVERIFIED",
        "policy_status": "BLOCKED_POLICY",
        "warning": "Static public page does not establish a documented, reusable machine API; do not reverse-engineer private requests.",
    }


def _fetch_html(url: str, *, timeout: int = 60, opener: Callable[..., Any] | None = None) -> tuple[int, str, bytes]:
    request = Request(url, headers={"User-Agent": "A23-Taihu-data-pipeline/0.1", "Accept": "text/html"})
    with (urlopen if opener is None else opener)(request, timeout=timeout) as response:
        status_value = getattr(response, "status", None)
        if status_value is None:
            status_value = response.getcode()
        return int(status_value), response.headers.get("Content-Type", ""), response.read()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_mwr_hfc_probe(
    *,
    input_path: Path | str | None = None,
    output_csv: Path | str | None = None,
    manifest_path: Path | str | None = None,
    source_url: str = MWR_HFC_URL,
    source_timezone: str = DEFAULT_SOURCE_TIMEZONE,
    allow_public_snapshot: bool = False,
    authorization_evidence_path: Path | str | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Probe HFC boundary; parse manual export only when evidence is supplied."""

    root = PACKAGE_ROOT
    output = Path(output_csv) if output_csv else STORAGE / "staging" / "mwr_hfc" / "observations.csv"
    manifest = Path(manifest_path) if manifest_path else STORAGE / "manifests" / "mwr_hfc_probe.json"
    evidence = Path(authorization_evidence_path) if authorization_evidence_path else None
    result: dict[str, Any] = {
        "task_id": "P07-02",
        "source_id": SOURCE_ID,
        "source_url": source_url,
        "status": "BLOCKED_POLICY",
        "data_truth": "no_input_page_or_export",
        "input_path": str(input_path) if input_path else None,
        "authorization_evidence_path": str(evidence) if evidence else None,
        "machine_api_verified": False,
        "interface_class": "official_entry_page_endpoint_unverified",
        "raw_asset_path": None,
        "asset_manifest": None,
        "output_csv": None,
        "records": 0,
        "warnings": [],
        "retrieved_at_utc": utc_now(),
    }
    if input_path is None and not allow_public_snapshot:
        result["browser_observation"] = "official HFC entry page is reachable; static machine API and reuse permission remain unverified"
        result["next_action"] = "obtain documented public endpoint permission or a legally exported CSV/JSON/XLSX file; do not reverse-engineer Ajax"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    if input_path is None and (evidence is None or not evidence.exists()):
        result["warnings"].append("MWR_AUTHORIZATION_EVIDENCE_REQUIRED")
        result["next_action"] = "provide written permission/terms evidence before a single low-frequency public snapshot"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    retrieved = utc_now()
    content_type = ""
    if input_path is not None:
        input_file = Path(input_path)
        body = input_file.read_bytes()
        suffix = input_file.suffix
    else:
        status, content_type, body = _fetch_html(source_url, opener=opener)
        if status != 200:
            result.update(status="FAILED", http_status=status, data_truth="real_mwr_hfc_html_failed")
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return result
        parsed_page = inspect_mwr_hfc_html(body.decode("utf-8", errors="replace"), page_url=source_url)
        result.update({"status": "BLOCKED_POLICY", "data_truth": "real_mwr_hfc_html_authorized_snapshot", "page_inspection": parsed_page, "next_action": "static page observed; machine endpoint remains unverified"})
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    raw_dir = RAW_ROOT / "mwr_hfc"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = raw_dir / f"{stamp}{suffix.lower() or '.bin'}"
    raw_path.write_bytes(body)
    records, encoding = _read_rows(body, suffix.lower())
    observations, warnings = _normalize_rows(records, source_file=str(raw_path), source_timezone=source_timezone)
    authorized = bool(evidence and evidence.exists())
    if authorized and observations:
        _write_csv(output, observations)
    asset = build_asset_manifest(
        source_id=SOURCE_ID,
        asset_id=raw_path.stem,
        request_url=source_url,
        local_path=raw_path,
        retrieved_at_utc=retrieved,
        http_status=200,
        response_headers={"Content-Type": content_type or "application/octet-stream"},
        license_tag="MWR_MANUAL_EXPORT_TERMS_PENDING_REVIEW",
        redistribution_allowed="conditional",
        commercial_use="conditional",
        status="completed" if authorized and observations else "blocked",
    )
    asset_manifest_path = manifest_root(root) / f"raw_mwr_hfc_{stamp}.json"
    write_asset_manifest(asset, asset_manifest_path)
    result.update({
        "status": "completed" if authorized and observations else "BLOCKED_POLICY" if not authorized else "BLOCKED_DATA",
        "data_truth": "user_supplied_manual_export",
        "raw_asset_path": str(raw_path),
        "asset_manifest": str(asset_manifest_path),
        "encoding": encoding,
        "records": len(observations),
        "output_csv": str(output) if authorized and observations else None,
        "warnings": warnings + ([] if authorized else ["MWR_EXPORT_AUTHORIZATION_NOT_VERIFIED"]),
        "next_action": None if authorized and observations else "register written permission/terms and validate station/time/unit coverage before modelling",
    })
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = ["DEFAULT_SOURCE_TIMEZONE", "MWR_HFC_URL", "SOURCE_ID", "inspect_mwr_hfc_html", "run_mwr_hfc_probe"]
