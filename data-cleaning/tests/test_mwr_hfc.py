from __future__ import annotations

import json

from pipeline.sources.mwr_hfc import inspect_mwr_hfc_html, run_mwr_hfc_probe


def test_public_hfc_shell_is_not_claimed_as_machine_api():
    html = """
    <html><head><title>全国水情预警公共服务系统</title></head>
    <body><div id='app'>水情服务</div><script src='/static/app.js'></script></body></html>
    """
    result = inspect_mwr_hfc_html(html)
    assert result["classification"] == "PUBLIC_HTML_SHELL_ENDPOINT_UNVERIFIED"
    assert result["machine_api_verified"] is False
    assert result["policy_status"] == "BLOCKED_POLICY"
    assert result["html_sha256"]


def test_no_input_stops_before_network_and_writes_boundary_manifest(tmp_path):
    manifest = tmp_path / "mwr_hfc_probe.json"
    result = run_mwr_hfc_probe(manifest_path=manifest)
    assert result["status"] == "BLOCKED_POLICY"
    assert result["machine_api_verified"] is False
    assert result["records"] == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "BLOCKED_POLICY"


def test_authorized_manual_csv_is_normalized_without_unit_or_time_guessing(tmp_path):
    input_path = tmp_path / "mwr_export.csv"
    input_path.write_text(
        "站点编号,站点名称,时间,指标,数值,单位,质量码\n"
        "TH-01,太湖代表站,2026-08-19 08:00,水位,3.01,m,0\n"
        "TH-01,太湖代表站,2026-08-19 08:00,雨量,5.2,mm,0\n",
        encoding="utf-8",
    )
    evidence = tmp_path / "authorization.txt"
    evidence.write_text("用户提供的授权或公开导出凭证", encoding="utf-8")
    output = tmp_path / "normalized.csv"
    manifest = tmp_path / "manifest.json"
    result = run_mwr_hfc_probe(
        input_path=input_path,
        output_csv=output,
        manifest_path=manifest,
        authorization_evidence_path=evidence,
    )
    assert result["status"] == "completed"
    assert result["records"] == 2
    assert output.exists()
    assert result["data_truth"] == "user_supplied_manual_export"
    assert "water_level" in output.read_text(encoding="utf-8-sig")


def test_manual_file_without_authorization_is_preserved_but_not_published(tmp_path):
    input_path = tmp_path / "mwr_export.csv"
    input_path.write_text("站点编号,时间,指标,数值\nTH-01,2026-08-19 08:00,水位,3.01\n", encoding="utf-8")
    output = tmp_path / "normalized.csv"
    result = run_mwr_hfc_probe(input_path=input_path, output_csv=output, manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_POLICY"
    assert result["raw_asset_path"]
    assert result["output_csv"] is None
    assert not output.exists()
