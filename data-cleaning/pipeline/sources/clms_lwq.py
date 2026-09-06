from __future__ import annotations

"""Copernicus CLMS Lake Water Quality catalogue adapter.

This task only discovers and archives the official catalogue metadata.  It
does not download multi-gigabyte global rasters; P06-06 will use the selected
object metadata for an authenticated Taihu window request.
"""

import csv
import io
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from ..provenance import build_asset_manifest, write_asset_manifest
from .common import PACKAGE_ROOT, sha256_file, utc_now


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[2] / "storage"))
CATALOG_ROOT = "https://csv.dataspace.copernicus.eu/CLMS/bio-geophysical/lake_water_quality/"
# 官方目录入口 + Copernicus Data Space 官方对象存储（目录 CSV 的 s3_path 直链
# 指向 CloudFerro WAW3-1，为 Data Space 官方基础设施，2026-09-06 实测确认）
OFFICIAL_CATALOG_HOSTS = frozenset({"csv.dataspace.copernicus.eu", "s3.waw3-1.cloudferro.com"})
OFFICIAL_CATALOG_HOST = urlsplit(CATALOG_ROOT).netloc.lower()
DEFAULT_PRODUCT = "lwq-nrt_global_300m_10daily_v2"
DEFAULT_VARIANT = "cog"
TARGET_VARIABLES = ("CHLAMEAN", "CHLAUNC", "FCBPROB")

DATA_TRUTH_REAL = "real_official_catalogue"
DATA_TRUTH_TEST_FIXTURE = "test_fixture"
DATA_TRUTH_UNVERIFIED = "unverified_source"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def parse_catalog_links(html: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    return [urljoin(base_url, href) for href in parser.hrefs]


def discover_product_page(index_html: str, *, product: str = DEFAULT_PRODUCT, base_url: str = CATALOG_ROOT) -> str:
    """Select the exact 300 m V2 product page, never a 100 m or reprocessed page."""

    expected = f"/{product}/"
    candidates = [url for url in parse_catalog_links(index_html, base_url) if urlsplit(url).path.endswith(expected)]
    if not candidates:
        raise LookupError(f"CLMS product page not found in catalogue: {product}")
    return candidates[0]


def discover_csv_url(product_html: str, product_page_url: str, *, variant: str = DEFAULT_VARIANT) -> str:
    links = parse_catalog_links(product_html, product_page_url)
    suffix = f"_{variant}.csv"
    candidates = [url for url in links if urlsplit(url).path.lower().endswith(suffix)]
    if not candidates:
        raise LookupError(f"CLMS {variant} CSV not found on product page")
    return candidates[0]


def _parse_number(value: Any) -> int | None:
    try:
        return int(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return text


def parse_lwq_catalog(csv_text: str, *, product: str = DEFAULT_PRODUCT, variant: str = DEFAULT_VARIANT) -> list[dict[str, Any]]:
    """Parse the semicolon-delimited CLMS catalogue while retaining provenance fields."""

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")), delimiter=";")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        row = {str(key).strip(): (value.strip() if isinstance(value, str) else value) for key, value in raw.items()}
        if not row.get("name") and not row.get("s3_path"):
            continue
        rows.append(
            {
                "source_id": "clms_lwq_catalog",
                "product": product,
                "variant": variant,
                "catalog_id": row.get("id"),
                "name": row.get("name"),
                "content_length_bytes": _parse_number(row.get("content_length")),
                "ingestion_date": _parse_datetime(row.get("ingestion_date")),
                "content_date_start": _parse_datetime(row.get("content_date_start")),
                "content_date_end": _parse_datetime(row.get("content_date_end")),
                "nominal_date": _parse_datetime(row.get("nominal_date")),
                "modification_date": _parse_datetime(row.get("modification_date")),
                "checksum_algorithm": row.get("checksum_algorithm"),
                "checksum_value": row.get("checksum_value"),
                "s3_path": row.get("s3_path"),
                "bbox": row.get("bbox"),
                "target_variables": list(TARGET_VARIABLES),
            }
        )
    return rows


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = _parse_datetime(value)
    if not parsed:
        return None
    try:
        return datetime.fromisoformat(parsed.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def select_latest_lwq_product(rows: Iterable[Mapping[str, Any]], *, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Select the latest product available at the reference time.

    The as-of filter prevents a historical replay from using a catalogue row
    that was not yet available at its forecast/reference time.
    """

    reference = _as_datetime(as_of) if as_of is not None else datetime.now(timezone.utc)
    candidates = []
    for row in rows:
        nominal = _as_datetime(row.get("nominal_date"))
        if nominal is None or (reference is not None and nominal > reference):
            continue
        candidates.append((nominal, dict(row)))
    if not candidates:
        raise LookupError("no CLMS LWQ product is available at the requested as-of time")
    candidates.sort(key=lambda item: (item[0], item[1].get("modification_date") or ""), reverse=True)
    selected = candidates[0][1]
    selected["selection_rule"] = "max nominal_date <= as_of"
    selected["as_of"] = reference.isoformat() if reference else None
    return selected


def classify_catalog_truth(*, opener_used: bool, request_urls: Iterable[str]) -> str:
    """判定目录抓取的可信等级。

    审计 2026-09-06 整改：只有"真实网络抓取（未注入 opener）且全部请求 URL
    落在官方目录主机"才可标 real_official_catalogue；注入 opener（单元测试/
    回放）一律 test_fixture，URL 越界一律 unverified_source，不得再无条件
    标记 real_batch=true。
    """

    if opener_used:
        return DATA_TRUTH_TEST_FIXTURE
    hosts = {urlsplit(str(url)).netloc.lower() for url in request_urls}
    if not hosts or not hosts.issubset(OFFICIAL_CATALOG_HOSTS) or OFFICIAL_CATALOG_HOST not in hosts:
        return DATA_TRUTH_UNVERIFIED
    return DATA_TRUTH_REAL


def _fetch_bytes(url: str, *, timeout: int = 60, opener: Callable[..., Any] | None = None) -> tuple[int, str, bytes]:
    request = Request(url, headers={"User-Agent": "A23-Taihu-data-pipeline/0.4", "Accept": "text/html,text/csv,*/*"})
    with (urlopen if opener is None else opener)(request, timeout=timeout) as response:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        return int(status), response.headers.get("Content-Type", ""), response.read()


def _write_raw_bytes(source_id: str, asset_id: str, url: str, status: int, content_type: str, payload: bytes, *, storage_root: Path) -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = storage_root / "raw" / source_id
    root.mkdir(parents=True, exist_ok=True)
    extension = ".csv" if "csv" in content_type.lower() or asset_id.endswith("csv") else ".html"
    path = root / f"{stamp}_{asset_id}{extension}"
    path.write_bytes(payload)
    manifest = build_asset_manifest(
        source_id=source_id,
        asset_id=asset_id,
        request_url=url,
        local_path=path,
        retrieved_at_utc=utc_now(),
        http_status=status,
        response_headers={"Content-Type": content_type},
        license_tag="COPERNICUS_TERMS_REVIEW_REQUIRED",
        redistribution_allowed="conditional",
        commercial_use="conditional",
        status="completed" if status == 200 else "failed",
    )
    manifest_path = storage_root / "manifests" / f"raw_{source_id}_{asset_id}_{stamp}.json"
    write_asset_manifest(manifest, manifest_path)
    return str(path), str(manifest_path)


def run_clms_lwq_catalog(
    *,
    product: str = DEFAULT_PRODUCT,
    variant: str = DEFAULT_VARIANT,
    as_of: datetime | str | None = None,
    output_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
    opener: Callable[..., Any] | None = None,
    storage_root: Path | str | None = None,
) -> dict[str, Any]:
    """Fetch, archive and select the latest official CLMS LWQ catalogue row.

    storage_root 显式落盘根（默认全局 STORAGE）：单元测试必须传入临时目录，
    防止 fixture 数据泄漏进正式 storage/raw（2026-09-05 污染事故根因）。
    """

    storage = Path(storage_root) if storage_root is not None else STORAGE
    output_root = Path(output_root) if output_root is not None else storage / "staging" / "clms_lwq_catalog"
    output_root.mkdir(parents=True, exist_ok=True)
    final_manifest = Path(manifest_path) if manifest_path else storage / "manifests" / "clms_lwq_catalog.json"
    request_urls: list[str] = []
    result: dict[str, Any] = {
        "task_id": "P06-05",
        "source_id": "clms_lwq_catalog",
        "status": "failed",
        "retrieved_at_utc": utc_now(),
        "catalog_root": CATALOG_ROOT,
        "product": product,
        "variant": variant,
        "target_variables": list(TARGET_VARIABLES),
        "data_truth": DATA_TRUTH_UNVERIFIED,
        "real_batch": False,
        "opener_injected": opener is not None,
        "raw_assets": [],
        "selected": None,
        "warnings": [],
        "manifest": str(final_manifest),
    }
    try:
        status, content_type, index_bytes = _fetch_bytes(CATALOG_ROOT, opener=opener)
        request_urls.append(CATALOG_ROOT)
        index_path, index_manifest = _write_raw_bytes("clms_lwq_catalog", "index", CATALOG_ROOT, status, content_type, index_bytes, storage_root=storage)
        result["raw_assets"].append({"kind": "index_html", "path": index_path, "manifest": index_manifest, "http_status": status, "request_url": CATALOG_ROOT})
        product_page = discover_product_page(index_bytes.decode("utf-8", "replace"), product=product)
        page_status, page_type, page_bytes = _fetch_bytes(product_page, opener=opener)
        request_urls.append(product_page)
        page_path, page_manifest = _write_raw_bytes("clms_lwq_catalog", product, product_page, page_status, page_type, page_bytes, storage_root=storage)
        result["raw_assets"].append({"kind": "product_html", "path": page_path, "manifest": page_manifest, "http_status": page_status, "request_url": product_page})
        csv_url = discover_csv_url(page_bytes.decode("utf-8", "replace"), product_page, variant=variant)
        csv_status, csv_type, csv_bytes = _fetch_bytes(csv_url, timeout=120, opener=opener)
        request_urls.append(csv_url)
        csv_path, csv_manifest = _write_raw_bytes("clms_lwq_catalog", f"{product}_{variant}", csv_url, csv_status, csv_type, csv_bytes, storage_root=storage)
        result["raw_assets"].append({"kind": "catalog_csv", "path": csv_path, "manifest": csv_manifest, "http_status": csv_status, "request_url": csv_url})
        rows = parse_lwq_catalog(csv_bytes.decode("utf-8-sig", "replace"), product=product, variant=variant)
        selected = select_latest_lwq_product(rows, as_of=as_of)
        selected_path = output_root / f"{product}_{variant}_selected_latest.json"
        selected_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.update({"status": "completed", "records": len(rows), "catalog_url": csv_url, "latest": selected, "selected": str(selected_path), "rows": rows})
    except Exception as exc:
        result["error"] = str(exc)
        result["next_action"] = "检查CLMS目录结构或网络响应后重试；不要把目录发现当作栅格下载"
    finally:
        result["data_truth"] = classify_catalog_truth(opener_used=opener is not None, request_urls=request_urls)
        result["real_batch"] = result["data_truth"] == DATA_TRUTH_REAL
    final_manifest.parent.mkdir(parents=True, exist_ok=True)
    final_manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = [
    "CATALOG_ROOT",
    "DATA_TRUTH_REAL",
    "DATA_TRUTH_TEST_FIXTURE",
    "DATA_TRUTH_UNVERIFIED",
    "DEFAULT_PRODUCT",
    "DEFAULT_VARIANT",
    "OFFICIAL_CATALOG_HOST",
    "TARGET_VARIABLES",
    "classify_catalog_truth",
    "discover_csv_url",
    "discover_product_page",
    "parse_catalog_links",
    "parse_lwq_catalog",
    "run_clms_lwq_catalog",
    "select_latest_lwq_product",
]
