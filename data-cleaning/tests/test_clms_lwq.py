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


def test_run_archives_real_shape_and_writes_selected_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(clms, "PACKAGE_ROOT", tmp_path)
    responses = {
        clms.CATALOG_ROOT: _Response(INDEX_HTML.encode()),
        "https://csv.dataspace.copernicus.eu/CLMS/bio-geophysical/lake_water_quality/lwq-nrt_global_300m_10daily_v2/": _Response(PRODUCT_HTML.encode()),
        "https://example.test/lwq-nrt_global_300m_10daily_v2_cog.csv": _Response(CSV_TEXT.encode(), "text/csv"),
    }

    def fake_opener(request, timeout=60):
        return responses[str(request.full_url)]

    output = tmp_path / "staging"
    manifest = tmp_path / "manifest.json"
    result = clms.run_clms_lwq_catalog(as_of="2025-06-30T00:00:00Z", output_root=output, manifest_path=manifest, opener=fake_opener)
    assert result["status"] == "completed"
    assert result["real_batch"] is True
    assert result["records"] == 3
    assert result["latest"]["catalog_id"] == "new"
    assert len(result["raw_assets"]) == 3
    assert Path(result["selected"]).exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["latest"]["catalog_id"] == "new"


def test_unknown_product_is_rejected():
    try:
        clms.discover_product_page(INDEX_HTML, product="lwq-nrt_global_300m_10daily_v9")
    except LookupError:
        return
    raise AssertionError("unknown product must not be silently substituted")
