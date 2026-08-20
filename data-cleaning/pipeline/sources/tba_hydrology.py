from __future__ import annotations

"""Compliance-first adapter for the Taihu Basin Authority water-level page.

The TBA portal is an official public page, but the repository's collection
policy does not yet authorize automated polling or reverse-engineering a
private endpoint.  This adapter therefore accepts a legally saved HTML page
as its normal input.  It preserves the exact HTML, page timestamp, retrieval
timestamp and a structural DOM fingerprint.  If the fingerprint changes, no
observations are published and a schema-drift alarm is emitted.
"""

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from ..normalize import _row
from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest
from ..time_contract import parse_time
from .common import PACKAGE_ROOT, RAW_ROOT, sha256_file, utc_now


TBA_PORTAL_URL = "https://www.tba.gov.cn/"
SOURCE_ID = "tba_current_level"
DEFAULT_SOURCE_TIMEZONE = "Asia/Shanghai"
REQUIRED_MARKERS = ("代表站", "水位", "水位(米)")
DEFAULT_STATIONS = ("延福门", "太湖水位", "平望", "琳桥", "张桥", "苏州", "无锡", "常州", "嘉兴", "杭长桥", "兰溪")
_TIMESTAMP_PATTERNS = (
    re.compile(r"(?:更新时间|更新于|数据时间|报送时间|发布时间|截至)\s*[:：]?\s*(20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)"),
)


class _TableParser(HTMLParser):
    """Collect table rows and a stable tag/attribute structure signature."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self.tags.append(tag)
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", unescape("".join(self._cell))).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def _dom_fingerprint(html: str, rows: list[list[str]], tags: list[str]) -> str:
    """Fingerprint structure and headers, excluding changing numeric values."""

    headers = [cell for row in rows[:4] for cell in row if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell)]
    structural = "|".join(tags) + "||" + "|".join(headers[:40]) + "||" + str(max(len(row) for row in rows) if rows else 0)
    return hashlib.sha256(structural.encode("utf-8")).hexdigest()


def _page_timestamp(html: str, *, source_timezone: str = DEFAULT_SOURCE_TIMEZONE) -> dict[str, Any]:
    text = _text(html)
    for pattern in _TIMESTAMP_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match.group(1).replace("/", "-").replace(" ", "T")
            parsed = parse_time(candidate, source_timezone=source_timezone)
            if parsed.get("status") == "accepted":
                return {"raw": match.group(1), "utc": parsed.get("utc"), "local": parsed.get("local"), "status": "accepted", "source": "page_text"}
    return {"raw": None, "utc": None, "local": None, "status": "missing", "source": None}


def _station_name(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def _parse_number(value: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value or "")
    return float(match.group(0)) if match else None


def parse_tba_html(
    html: str,
    *,
    page_url: str = TBA_PORTAL_URL,
    retrieved_at_utc: str | None = None,
    expected_dom_fingerprint: str | None = None,
    source_timezone: str = DEFAULT_SOURCE_TIMEZONE,
    source_id: str = SOURCE_ID,
) -> dict[str, Any]:
    """Parse a TBA page while refusing to publish on DOM drift or missing time."""

    retrieved = retrieved_at_utc or utc_now()
    parser = _TableParser()
    parser.feed(html)
    text = _text(html)
    fingerprint = _dom_fingerprint(html, parser.rows, parser.tags)
    timestamp = _page_timestamp(html, source_timezone=source_timezone)
    markers_present = all(marker in text for marker in REQUIRED_MARKERS)
    drift = bool(expected_dom_fingerprint and expected_dom_fingerprint != fingerprint)
    schema_status = "ok" if markers_present and parser.rows else "missing_required_dom"
    if drift:
        schema_status = "drift"

    observations: list[dict[str, Any]] = []
    if schema_status == "ok" and not drift and timestamp["status"] == "accepted":
        for row_number, row in enumerate(parser.rows, start=1):
            if len(row) < 2:
                continue
            station = _station_name(row[0])
            if station not in DEFAULT_STATIONS and not station.endswith("水位"):
                continue
            value = _parse_number(row[1])
            if value is None:
                continue
            item = _row(
                source_id=source_id,
                source_file=Path(f"{page_url}#html"),
                source_row=f"tr:{row_number}",
                observed_at=timestamp["utc"],
                variable_code="water_level",
                observed_value=row[1],
                clean_value=value,
                unit="m",
                value_origin="observed",
                station_id=f"tba:{station}",
                longitude=None,
                latitude=None,
                source_parameter="水位(米)",
                conversion_rule="TBA page unit retained; vertical datum not inferred",
                time_fields={"utc": timestamp["utc"], "local": timestamp["local"], "status": "accepted", "source_timezone": source_timezone},
            )
            item.update({
                "station_name": station,
                "raw_value": row[1],
                "page_url": page_url,
                "page_timestamp_raw": timestamp["raw"],
                "retrieved_at_utc": retrieved,
                "water_level_datum": None,
                "datum_status": "pending_confirmation",
                "quality_code": "TBA_DOM_OK_DATUM_PENDING",
                "quality_flags": ["TBA_DATUM_PENDING"],
                "proxy_flag": 0,
                "page_dom_fingerprint": fingerprint,
            })
            observations.append(item)

    status = "completed" if observations and schema_status == "ok" and timestamp["status"] == "accepted" else "BLOCKED_SCHEMA_DRIFT" if drift else "BLOCKED_DATA"
    warnings: list[str] = []
    if drift:
        warnings.append("TBA_DOM_SCHEMA_DRIFT_STOP_PUBLISH")
    if not markers_present:
        warnings.append("TBA_REQUIRED_MARKERS_MISSING")
    if timestamp["status"] != "accepted":
        warnings.append("TBA_PAGE_TIMESTAMP_MISSING")
    if observations:
        warnings.append("TBA_WATER_LEVEL_DATUM_PENDING")
    return {
        "source_id": source_id,
        "source_url": page_url,
        "retrieved_at_utc": retrieved,
        "page_timestamp": timestamp,
        "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "html_bytes": len(html.encode("utf-8")),
        "dom_fingerprint": fingerprint,
        "expected_dom_fingerprint": expected_dom_fingerprint,
        "schema_status": schema_status,
        "status": status,
        "observations": observations if status == "completed" else [],
        "parsed_rows": len(observations),
        "warnings": warnings,
        "datum_policy": "vertical datum is not inferred; observation remains pending confirmation",
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


def run_tba_hydrology(
    *,
    input_path: Path | str | None = None,
    output_csv: Path | str | None = None,
    manifest_path: Path | str | None = None,
    expected_dom_fingerprint: str | None = None,
    source_url: str = TBA_PORTAL_URL,
    source_timezone: str = DEFAULT_SOURCE_TIMEZONE,
    allow_public_snapshot: bool = False,
    authorization_evidence_path: Path | str | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Parse a legally saved page; network fetch requires explicit evidence."""

    root = PACKAGE_ROOT
    output = Path(output_csv) if output_csv else root / "storage" / "staging" / "tba_hydrology" / "water_level.csv"
    manifest = Path(manifest_path) if manifest_path else root / "storage" / "manifests" / "tba_hydrology.json"
    evidence = Path(authorization_evidence_path) if authorization_evidence_path else None
    run_result: dict[str, Any] = {
        "task_id": "P07-01",
        "source_id": SOURCE_ID,
        "source_url": source_url,
        "status": "BLOCKED_POLICY",
        "data_truth": "no_input_page",
        "input_path": str(input_path) if input_path else None,
        "output_csv": str(output),
        "manifest": str(manifest),
        "authorization_evidence_path": str(evidence) if evidence else None,
        "raw_html_path": None,
        "page_timestamp": None,
        "retrieved_at_utc": utc_now(),
        "html_sha256": None,
        "dom_fingerprint": None,
        "observations": 0,
        "warnings": [],
    }
    if input_path is None and not allow_public_snapshot:
        run_result["next_action"] = "在条款/书面许可允许后保存一份TBA页面HTML，或提供人工导出的公开水情文件；当前不自动轮询"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(run_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_result
    if allow_public_snapshot and (evidence is None or not evidence.exists()):
        run_result["warnings"].append("TBA_AUTHORIZATION_EVIDENCE_REQUIRED")
        run_result["next_action"] = "补充书面许可/条款证据后才能执行单次公开页面快照"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(run_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_result

    retrieved = utc_now()
    if input_path is not None:
        input_file = Path(input_path)
        body = input_file.read_bytes()
        content_type = "text/html"
    else:
        status, content_type, body = _fetch_html(source_url, opener=opener)
        if status != 200:
            run_result.update(status="FAILED", http_status=status, data_truth="real_tba_html_failed")
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(run_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return run_result
    raw_dir = RAW_ROOT / "tba_hydrology"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = raw_dir / f"{stamp}.html"
    raw_path.write_bytes(body)
    html = body.decode("utf-8", errors="replace")
    parsed = parse_tba_html(html, page_url=source_url, retrieved_at_utc=retrieved, expected_dom_fingerprint=expected_dom_fingerprint, source_timezone=source_timezone)
    asset = build_asset_manifest(
        source_id=SOURCE_ID,
        asset_id=raw_path.stem,
        request_url=source_url,
        local_path=raw_path,
        retrieved_at_utc=retrieved,
        http_status=200,
        response_headers={"Content-Type": content_type},
        license_tag="TBA_PUBLIC_PAGE_PENDING_REUSE_REVIEW",
        redistribution_allowed="pending_review",
        commercial_use="pending_review",
        status="completed" if parsed["status"] == "completed" else "blocked",
    )
    asset_manifest_path = manifest_root(root) / f"raw_tba_hydrology_{stamp}.json"
    write_asset_manifest(asset, asset_manifest_path)
    observations = parsed.get("observations", [])
    if observations and output:
        _write_csv(output, observations)
    run_result.update({
        "status": parsed["status"],
        "data_truth": "real_tba_html_input" if input_path else "real_tba_html_authorized_snapshot",
        "retrieved_at_utc": retrieved,
        "raw_html_path": str(raw_path),
        "asset_manifest": str(asset_manifest_path),
        "page_timestamp": parsed["page_timestamp"],
        "html_sha256": parsed["html_sha256"],
        "html_bytes": parsed["html_bytes"],
        "dom_fingerprint": parsed["dom_fingerprint"],
        "schema_status": parsed["schema_status"],
        "observations": len(observations),
        "warnings": parsed["warnings"],
        "datum_policy": parsed["datum_policy"],
        "output_csv": str(output) if observations else None,
    })
    if parsed["status"] == "BLOCKED_SCHEMA_DRIFT":
        run_result["next_action"] = "停止发布并人工复核DOM/字段变更；更新指纹前不得继续"
    elif parsed["status"] == "BLOCKED_DATA":
        run_result["next_action"] = "补齐页面时间或合法水情文件；不得用抓取时间替代观测时间"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(run_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run_result


__all__ = ["DEFAULT_SOURCE_TIMEZONE", "SOURCE_ID", "TBA_PORTAL_URL", "parse_tba_html", "run_tba_hydrology"]
