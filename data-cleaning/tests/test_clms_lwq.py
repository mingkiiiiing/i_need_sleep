from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pipeline.sources.clms_lwq as clms


INDEX_HTML = '''<a href="/CLMS/bio-geophysical/lake_water_quality/lwq-nrt_global_100m_10daily_v2/">100m</a>
<a href="/CLMS/bio-geophysical/lake_water_quality/lwq-nrt_global_300m_10daily_v2/">300m</a>'''
PRODUCT_HTML = '''<a href="https://example.test/wrong.csv">wrong</a>
<a href="https://example.test/lwq-nrt_global_300m_10daily_v2_cog.csv">cog</a>'''
CSV_TEXT = '''id;name;content_length;ingestion_date;content_date_start;content_date_end;nominal_date;modification_date;checksum_algorithm;checksum_value;s3_path;bbox
old;c_gls_LWQ300_202506010000_GLOBE_OLCI_V2.1.0_cog;10;2025-06-02T00:00:00.000;2025-06-01T00:00:00.000;2025-06-10T23:59:59.999;2025-06-01T00:00:00.000;2025-06-02T00:00:00.000;MD5;abc;s3://eodata/old;POLYGON(...)
new;c_gls_LWQ300_202506110000_GLOBE_OLCI_V2.1.1_cog;11;2025-06-12T00:00:00.000;2025-06-11T00:00:00.000;2025-06-20T23:59:59.999;2025-06-11T00:00:00.000;2025-06-12T00:00:00.000;MD5;def;s3://eodata/new;POLYGON(...)
future;c_gls_LWQ300_202507010000_GLOBE_OLCI_V2.1.1_cog;12;2025-07-02T00:00:00.000;2025-07-01T00:00:00.000;2025-07-10T23:59:59.999;2025-07-01T00:00:00.000;2025-07-02T00:00:00.000;MD5;ghi;s3://eodata/future;POLYGON(...)
'''


class _Response:
    def __init__(self, payload: bytes, content_type: str = "text/html"):
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_catalog_discovery_selects_exact_product_and_cog():
    page = clms.discover_product_page(INDEX_HTML, product=clms.DEFAULT_PRODUCT)
    assert page.endswith("lwq-nrt_global_300m_10daily_v2/")
    csv_url = clms.discover_csv_url(PRODUCT_HTML, page)
    assert csv_url.endswith("lwq-nrt_global_300m_10daily_v2_cog.csv")


def test_parse_and_as_of_selection_does_not_use_future_product():
    rows = clms.parse_lwq_catalog(CSV_TEXT)
    assert len(rows) == 3
    assert rows[0]["content_length_bytes"] == 10
    selected = clms.select_latest_lwq_product(rows, as_of="2025-06-30T00:00:00Z")
    assert selected["catalog_id"] == "new"
    assert selected["target_variables"] == ["CHLAMEAN", "CHLAUNC", "FCBPROB"]


def test_run_archives_real_shape_and_writes_selected_manifest(tmp_path):
    storage_root = tmp_path / "storage"
    responses = {
        clms.CATALOG_ROOT: _Response(INDEX_HTML.encode()),
        "https://csv.dataspace.copernicus.eu/CLMS/bio-geophysical/lake_water_quality/lwq-nrt_global_300m_10daily_v2/": _Response(PRODUCT_HTML.encode()),
        "https://example.test/lwq-nrt_global_300m_10daily_v2_cog.csv": _Response(CSV_TEXT.encode(), "text/csv"),
    }

    def fake_opener(request, timeout=60):
        return responses[str(request.full_url)]

    output = tmp_path / "staging"
    manifest = tmp_path / "manifest.json"
    result = clms.run_clms_lwq_catalog(
        as_of="2025-06-30T00:00:00Z",
        output_root=output,
        manifest_path=manifest,
        opener=fake_opener,
        storage_root=storage_root,
    )
    assert result["status"] == "completed"
    # 审计 2026-09-06：注入 opener 的抓取一律 test_fixture，不得标 real_batch=true
    assert result["data_truth"] == "test_fixture"
    assert result["real_batch"] is False
    assert result["records"] == 3
    assert result["latest"]["catalog_id"] == "new"
    assert len(result["raw_assets"]) == 3
    assert Path(result["selected"]).exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["latest"]["catalog_id"] == "new"
    # 落盘只进传入的 storage_root，不污染正式 storage（2026-09-05 泄漏事故回归）
    assert (storage_root / "raw" / "clms_lwq_catalog").is_dir()
    assert (storage_root / "manifests").is_dir()
    assert list((storage_root / "raw" / "clms_lwq_catalog").glob("*_index.html"))


def test_non_official_host_with_real_fetch_is_not_marked_real():
    # 未注入 opener 但响应 URL 越出官方主机（如 example.test）→ unverified_source
    truth = clms.classify_catalog_truth(
        opener_used=False,
        request_urls=[clms.CATALOG_ROOT, "https://example.test/lwq-nrt_global_300m_10daily_v2_cog.csv"],
    )
    assert truth == "unverified_source"


def test_classify_catalog_truth_matrix():
    official_csv = "https://s3.waw3-1.cloudferro.com/swift/v1/CatalogueCSV/bio-geophysical/lake_water_quality/lwq-nrt_global_300m_10daily_v2/lwq-nrt_global_300m_10daily_v2_cog.csv"
    # 目录入口必须在官方主机；CSV 直链允许官方对象存储（CloudFerro WAW3-1，2026-09-06 实测）
    assert clms.classify_catalog_truth(opener_used=False, request_urls=[clms.CATALOG_ROOT, official_csv]) == "real_official_catalogue"
    assert clms.classify_catalog_truth(opener_used=True, request_urls=["https://example.test/x.csv"]) == "test_fixture"
    assert clms.classify_catalog_truth(opener_used=False, request_urls=[]) == "unverified_source"
    assert clms.classify_catalog_truth(opener_used=False, request_urls=["https://example.test/x.csv"]) == "unverified_source"
    # 缺少官方目录入口（只抓了对象存储）也不可信
    assert clms.classify_catalog_truth(opener_used=False, request_urls=[official_csv]) == "unverified_source"


def test_unknown_product_is_rejected():
    try:
        clms.discover_product_page(INDEX_HTML, product="lwq-nrt_global_300m_10daily_v9")
    except LookupError:
        return
    raise AssertionError("unknown product must not be silently substituted")
