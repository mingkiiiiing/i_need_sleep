from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest
from .common import RAW_ROOT, utc_now


FEATURE_URL = "https://lake.geodata.cn/feature.html"
TAIHU_PHYTOPLANKTON_URL = "https://lake.geodata.cn/data/datadetails.html?dataguid=192717411773491&docId=2"
TAIHU_WATER_QUALITY_URL = "https://lake.geodata.cn/data/datadetails.html?dataguid=23392619680528&docId=3"


def _fetch_html(url: str, timeout: int = 60) -> tuple[int, str, bytes]:
    request = Request(url, headers={"User-Agent": "A23-Taihu-data-pipeline/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.headers.get("Content-Type", ""), response.read()


def summarize_lake_geodata_html(html: str) -> dict[str, object]:
    """Extract access and content signals without treating the page as data.

    The Lake-Watershed Science Data Center pages are metadata/order pages. This
    function deliberately reports access signals only; it never invents a
    water-quality value from page text.
    """

    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text).strip()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    years = sorted(set(re.findall(r"(?:19|20)\d{2}(?:\s*[-—至]\s*(?:19|20)?\d{2}|年至今)", text)))
    return {
        "html_bytes": len(html.encode("utf-8")),
        "title": re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else None,
        "mentions_sample": "下载数据样例" in text or "数据样例" in text,
        "order_required_language": "完整的数据可通过加入数据订单审核后获取" in text or "完整的数据可通过加入订单审核后获取" in text,
        "license_restriction_language": "未经本平台书面许可" in text,
        "mentions_taihu": "太湖" in text,
        "mentions_remote_bloom": "蓝藻水华" in text or "蓝藻反演" in text,
        "mentions_chlorophyll": "叶绿素" in text,
        "year_claims": years,
    }


def probe_lake_geodata_sources(output_root: Path | None = None, database: Path | None = None, *, urls: dict[str, str] | None = None) -> dict[str, object]:
    """Verify public metadata pages and record the authorization boundary.

    This is an access-validation step for NIGLAS/NESDC Lake-Watershed data.
    It fetches only the public HTML pages; sample/full data downloads remain
    subject to the platform's login/order and reuse terms.
    """

    root = Path(__file__).resolve().parents[2]
    output_root = output_root or root / "storage" / "exports" / "lake_geodata_probe"
    database = database or root / "storage" / "data_cleaning.db"
    output_root.mkdir(parents=True, exist_ok=True)
    source_urls = urls or {
        "niglas_lake_geodata_feature": FEATURE_URL,
        "niglas_taihu_phytoplankton": TAIHU_PHYTOPLANKTON_URL,
        "niglas_taihu_water_quality": TAIHU_WATER_QUALITY_URL,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = RAW_ROOT / "lake_geodata_probe"
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for source_id, url in source_urls.items():
        record: dict[str, object] = {"source_id": source_id, "url": url, "retrieved_at": utc_now()}
        try:
            status, content_type, body = _fetch_html(url)
            raw_path = raw_dir / f"{stamp}_{source_id}.html"
            raw_path.write_bytes(body)
            html = body.decode("utf-8", errors="replace")
            asset_manifest = build_asset_manifest(
                source_id=source_id,
                asset_id=raw_path.stem,
                request_url=url,
                local_path=raw_path,
                retrieved_at_utc=record["retrieved_at"],
                http_status=status,
                response_headers={"Content-Type": content_type},
                status="completed" if status == 200 else "failed",
            )
            asset_manifest_path = manifest_root(root) / f"raw_{source_id}_{stamp}.json"
            write_asset_manifest(asset_manifest, asset_manifest_path)
            record.update({"http_status": status, "content_type": content_type, "raw_path": str(raw_path), "asset_manifest": str(asset_manifest_path), "access_status": "metadata_verified_order_or_login_required", "summary": summarize_lake_geodata_html(html)})
        except Exception as exc:
            record.update({"http_status": None, "content_type": None, "raw_path": None, "asset_manifest": None, "access_status": "probe_failed", "error": str(exc), "summary": {}})
        results.append(record)

    manifest = {
        "run_id": f"lake_geodata_probe_{stamp}",
        "status": "completed",
        "source_count": len(results),
        "metadata_pages_http_200": sum(1 for item in results if item.get("http_status") == 200),
        "results": results,
        "authorization_boundary": "public metadata verified; sample/full data requires platform access review/order and is not copied automatically",
    }
    manifest_path = output_root / "lake_geodata_probe.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE IF EXISTS lake_geodata_probe")
        connection.execute("CREATE TABLE lake_geodata_probe (source_id TEXT PRIMARY KEY, url TEXT, http_status INTEGER, access_status TEXT, raw_path TEXT, summary_json TEXT, error TEXT)")
        connection.executemany(
            "INSERT INTO lake_geodata_probe VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(item["source_id"], item["url"], item.get("http_status"), item["access_status"], item.get("raw_path"), json.dumps(item.get("summary", {}), ensure_ascii=False), item.get("error")) for item in results],
        )
        connection.commit()
    finally:
        connection.close()
    manifest["manifest"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
