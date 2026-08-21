from __future__ import annotations

import json

from pipeline.sources.tba_hydrology import parse_tba_html, run_tba_hydrology


HTML = """
<html><head><title>太湖网</title></head><body>
<div>数据更新时间：2026-08-19 08:00</div>
<table><thead><tr><th>代表站(8时)</th><th>水位(米)</th><th>警戒水位(米)</th></tr></thead>
<tbody>
<tr><td>太湖水位</td><td>3.01</td><td>0.0</td></tr>
<tr><td>无锡</td><td>3.39</td><td>0.0</td></tr>
<tr><td>苏州</td><td>3.23</td><td>0.0</td></tr>
</tbody></table></body></html>
"""


def test_parse_preserves_page_time_retrieval_time_and_pending_datum():
    result = parse_tba_html(HTML, retrieved_at_utc="2026-08-19T01:00:00+00:00")
    assert result["status"] == "completed"
    assert result["page_timestamp"]["utc"] == "2026-08-19T00:00:00+00:00"
    assert result["retrieved_at_utc"] == "2026-08-19T01:00:00+00:00"
    assert result["parsed_rows"] == 3
    assert result["observations"][0]["clean_value"] == 3.01
    assert result["observations"][0]["unit"] == "m"
    assert result["observations"][0]["datum_status"] == "pending_confirmation"
    assert "TBA_DATUM_PENDING" in result["observations"][0]["quality_flags"]


def test_dom_drift_stops_publication_and_emits_alarm():
    baseline = parse_tba_html(HTML)
    changed = HTML.replace("水位(米)", "水位（米）")
    result = parse_tba_html(changed, expected_dom_fingerprint=baseline["dom_fingerprint"])
    assert result["status"] == "BLOCKED_SCHEMA_DRIFT"
    assert result["observations"] == []
    assert "TBA_DOM_SCHEMA_DRIFT_STOP_PUBLISH" in result["warnings"]


def test_missing_page_timestamp_is_not_replaced_by_ingestion_time():
    result = parse_tba_html(HTML.replace("数据更新时间：2026-08-19 08:00", ""), retrieved_at_utc="2026-08-19T01:00:00Z")
    assert result["status"] == "BLOCKED_DATA"
    assert result["observations"] == []
    assert "TBA_PAGE_TIMESTAMP_MISSING" in result["warnings"]


def test_run_without_input_is_policy_blocked_and_does_not_fetch(tmp_path):
    manifest = tmp_path / "manifest.json"
    result = run_tba_hydrology(manifest_path=manifest)
    assert result["status"] == "BLOCKED_POLICY"
    assert result["observations"] == 0
    assert manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "BLOCKED_POLICY"


def test_run_saved_html_persists_raw_asset_and_normalized_csv(tmp_path):
    input_path = tmp_path / "tba.html"
    input_path.write_text(HTML, encoding="utf-8")
    output = tmp_path / "water_level.csv"
    manifest = tmp_path / "manifest.json"
    result = run_tba_hydrology(input_path=input_path, output_csv=output, manifest_path=manifest)
    assert result["status"] == "completed"
    assert result["data_truth"] == "real_tba_html_input"
    assert result["observations"] == 3
    assert output.exists()
    assert result["raw_html_path"]
    assert result["asset_manifest"]
    assert json.loads(manifest.read_text(encoding="utf-8"))["html_sha256"] == result["html_sha256"]
