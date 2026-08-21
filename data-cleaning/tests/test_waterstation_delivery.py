from __future__ import annotations

import json
from pathlib import Path

from pipeline.waterstation_delivery import run_waterstation_delivery


def test_empty_inbox_is_blocked_and_templates_are_not_authorized(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "authorization_template.yml").write_text("DRAFT_READY\n", encoding="utf-8")
    result = run_waterstation_delivery(inbox_root=inbox, inventory_path=tmp_path / "inventory.csv", manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["delivery_count"] == 0
    assert "ignored_not_delivery" in (tmp_path / "inventory.csv").read_text(encoding="utf-8-sig")
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["data_truth"] == "no_authorized_delivery"


def test_valid_delivery_isolated_with_checksum_and_no_copy(tmp_path):
    inbox = tmp_path / "inbox"
    delivery = inbox / "delivery_20260819_001"
    delivery.mkdir(parents=True)
    data = delivery / "station.csv"
    data.write_text("station_id,observed_at,variable,value,unit\nS1,2026-08-19T08:00:00+08:00,chlorophyll_a,12,ug/L\n", encoding="utf-8")
    (delivery / "authorization.yml").write_text(
        "provider_name: Taihu Provider\nvalid_from: 2026-01-01\nvalid_until: 2026-12-31\nauthorization_type: research permission\nexternal_request_id: REQ-001\ndelivery_id: delivery_20260819_001\n",
        encoding="utf-8",
    )
    (delivery / "delivery_manifest.json").write_text(
        '{"delivery_id":"delivery_20260819_001","provider_name":"Taihu Provider","files":["station.csv"],"delivery_date":"2026-08-19"}',
        encoding="utf-8",
    )
    result = run_waterstation_delivery(inbox_root=inbox, inventory_path=tmp_path / "inventory.csv", manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "isolated"
    assert result["deliveries"][0]["data_file_count"] == 1
    assert result["deliveries"][0]["authorization_evidence_count"] == 1
    assert result["deliveries"][0]["delivery_manifest_count"] == 1
    assert data.exists()
    assert result["deliveries"][0]["authorization_evidence"][0]["sha256"]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "isolated"


def test_delivery_without_valid_authorization_stays_blocked(tmp_path):
    delivery = tmp_path / "inbox" / "delivery_bad"
    delivery.mkdir(parents=True)
    (delivery / "station.csv").write_text("station_id,value\nS1,1\n", encoding="utf-8")
    (delivery / "authorization_template.yml").write_text("DRAFT_READY\n", encoding="utf-8")
    result = run_waterstation_delivery(inbox_root=tmp_path / "inbox", inventory_path=tmp_path / "inventory.csv", manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["deliveries"][0]["authorization_evidence_count"] == 0
    assert result["deliveries"][0]["data_file_count"] == 1
