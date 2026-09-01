from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.sources.copernicus_assets import (
    TARGET_ASSETS,
    build_download_plan,
    run_sentinel2_asset_download,
    s3_href_to_https,
    select_sentinel2_assets,
)


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def _scene() -> dict:
    assets = {}
    for band in TARGET_ASSETS:
        resolution = "20m" if band in {"B05", "B8A", "B11", "SCL"} else "10m"
        assets[f"{band}_{resolution}"] = {
            "href": f"s3://eodata/Sentinel-2/test/T51RTQ_{band}_{resolution}.jp2",
            "type": "image/jp2",
            "file:size": 4,
        }
    assets["Product"] = {"href": "https://download.dataspace.copernicus.eu/odata/v1/Products/large/$value", "file:size": 999999}
    return {"type": "Feature", "id": "S2A_TEST_T51RTQ", "collection": "sentinel-2-l2a", "properties": {"datetime": "2025-06-28T02:41:41Z", "eo:cloud_cover": 15.0}, "assets": assets}


def test_target_selector_excludes_product_and_keeps_all_required_bands():
    selected = select_sentinel2_assets(_scene())
    assert [item["band"] for item in selected] == list(TARGET_ASSETS)
    assert all(item["asset_key"] != "Product" for item in selected)


def test_s3_href_is_mapped_to_documented_cdse_endpoint():
    assert s3_href_to_https("s3://eodata/Sentinel-2/test.jp2") == "https://eodata.dataspace.copernicus.eu/Sentinel-2/test.jp2"


def test_plan_is_bounded_and_marks_missing_assets():
    scene = _scene()
    scene["assets"].pop("B11_20m")
    plan = build_download_plan(scene, output_root=str(STORAGE / "test-assets"))
    assert plan["selected_count"] == 7
    assert plan["missing_bands"] == ["B11"]
    assert plan["product_archive_selected"] is False
    assert all("Product" not in item["asset_key"] for item in plan["assets"])


def test_authorized_injected_downloader_writes_and_records_checksum(tmp_path):
    stac = tmp_path / "stac.json"
    stac.write_text(json.dumps({"type": "FeatureCollection", "features": [_scene()]}), encoding="utf-8")
    payload = b"JP2"

    def fake_downloader(item, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return {"status": "completed", "resumed": False}

    result = run_sentinel2_asset_download(stac, output_root=tmp_path / "out", manifest_path=tmp_path / "manifest.json", downloader=fake_downloader)
    assert result["status"] == "failed"  # STAC file:size=4 intentionally catches an incorrect asset write.
    assert len(result["failed"]) == 8

    def correct_downloader(item, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload + b"!")
        return {"status": "completed", "resumed": False}

    result = run_sentinel2_asset_download(stac, output_root=tmp_path / "out2", manifest_path=tmp_path / "manifest2.json", downloader=correct_downloader)
    assert result["status"] == "completed"
    assert len(result["downloaded"]) == 8
    assert all(item["checksum_status"] == "computed_not_verified" for item in result["downloaded"])
    assert json.loads((tmp_path / "manifest2.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_real_cdse_stac_metadata_produces_eight_asset_plan(tmp_path):
    raw = STORAGE / "raw/copernicus_sentinel2_stac/20260819T034225Z.json"
    if not raw.exists():
        return
    result = run_sentinel2_asset_download(raw, manifest_path=tmp_path / "test_p06_02_plan.json")
    assert result["status"] == "BLOCKED_AUTH"
    assert result["data_truth"] == "real_stac_asset_metadata"
    assert result["plan"]["selected_count"] == 8
    assert result["plan"]["product_archive_selected"] is False
