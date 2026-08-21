from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from pipeline.sources.research_center_files import parse_research_center_bytes, parse_research_center_file


METADATA = {
    "dataset_id": "geodata_taihu_2000_2020",
    "doi": "10.1234/taihu.example",
    "license_tag": "dataset-specific-research-only",
    "redistribution_allowed": "no",
    "commercial_use": "no",
    "application_number": "NESDC-TEST-001",
    "native_frequency": "quarterly",
    "source_timezone": "Asia/Shanghai",
    "provider": "国家地球系统科学数据中心",
}


def _quarterly() -> bytes:
    return (
        "站号,观测时间,TN,TP,质量码\n"
        "TH-01,2020-03-31,1.2,0.04,0\n"
        "TH-01,2020-06-30,-999,0.05,1\n"
    ).encode("gb18030")


def test_research_center_preserves_native_quarterly_cadence_and_metadata() -> None:
    result = parse_research_center_bytes(_quarterly(), path_label="quarterly.csv", metadata=METADATA)
    rows = result["observations"]
    assert len(rows) == 4
    assert {row["native_frequency"] for row in rows} == {"quarterly"}
    assert {row["station_id"] for row in rows} == {"TH-01"}
    assert {row["observed_at_local"][:10] for row in rows} == {"2020-03-31", "2020-06-30"}
    assert next(row for row in rows if row["source_parameter"] == "TN" and row["observed_at_local"].startswith("2020-06"))["clean_value"] is None
    assert result["metadata"]["doi"] == "10.1234/taihu.example"
    assert result["metadata"]["application_number"] == "NESDC-TEST-001"
    assert result["encoding"] == "gb18030"


def test_research_center_zip_writes_manifest_and_does_not_upsample(tmp_path: Path) -> None:
    archive = tmp_path / "download.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("data/quarterly.txt", _quarterly())
    output = tmp_path / "standard.csv"
    manifest = tmp_path / "manifest.json"
    result = parse_research_center_file(archive, output, metadata=METADATA, manifest_path=manifest)
    assert result["status"] == "completed"
    assert result["input_rows"] == 2
    assert result["records"] == 4
    assert result["members"] == ["data/quarterly.txt"]
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["doi"] == METADATA["doi"]
    assert saved["license_tag"] == METADATA["license_tag"]
    assert saved["application_number"] == METADATA["application_number"]
    assert saved["native_frequency"] == "quarterly"
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4


def test_missing_authorization_metadata_is_blocked_not_invented(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_bytes(_quarterly())
    result = parse_research_center_file(source, metadata={"native_frequency": "monthly"}, manifest_path=tmp_path / "manifest.json")
    assert result["status"] == "BLOCKED_METADATA"
    assert result["metadata_complete"] is False
