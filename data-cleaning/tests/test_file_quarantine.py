from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from pipeline.file_quarantine import run_file_quarantine


def _read_report(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_file_quarantine_detects_empty_schema_encoding_and_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "empty.csv").write_bytes(b"")
    (root / "good.csv").write_text("time,value\n2026-01-01,1\n", encoding="utf-8")
    (root / "copy.csv").write_bytes((root / "good.csv").read_bytes())
    (root / "bad.csv").write_text("a,b\n1\n", encoding="utf-8")
    (root / "gb.csv").write_bytes("时间,值\n2026-01-01,1\n".encode("gb18030"))
    report = tmp_path / "reports" / "file_quarantine.csv"
    manifest = tmp_path / "manifests" / "file_quarantine.json"
    result = run_file_quarantine(root, report, manifest)

    assert result["status"] == "completed_with_issues"
    rows = {row["relative_path"]: row for row in _read_report(report)}
    assert "empty_file" in rows["empty.csv"]["issue_codes"]
    assert any("duplicate_checksum" in row["issue_codes"] for row in rows.values())
    assert "schema_row_width_mismatch" in rows["bad.csv"]["issue_codes"]
    assert rows["gb.csv"]["encoding"] == "gb18030"
    assert "encoding_non_utf8" in rows["gb.csv"]["issue_codes"]
    assert json.loads(manifest.read_text(encoding="utf-8"))["file_count"] == 5


def test_file_quarantine_detects_corrupt_zip_and_valid_json(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "broken.zip").write_bytes(b"not a zip")
    with zipfile.ZipFile(root / "valid.zip", "w") as archive:
        archive.writestr("payload.txt", "ok")
    (root / "data.json").write_text(json.dumps([{"value": 1}]), encoding="utf-8")
    report = tmp_path / "file_quarantine.csv"
    result = run_file_quarantine(root, report, tmp_path / "manifest.json")

    rows = {row["relative_path"]: row for row in _read_report(report)}
    assert "compressed_corrupt" in rows["broken.zip"]["issue_codes"]
    assert rows["valid.zip"]["archive_check"] == "valid"
    assert rows["data.json"]["schema_status"] == "valid_json"
    assert result["issue_count"] == 1


def test_file_quarantine_does_not_modify_input(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    payload = root / "payload.txt"
    payload.write_text("unchanged", encoding="utf-8")
    before = payload.read_bytes()
    run_file_quarantine(root, tmp_path / "report.csv", tmp_path / "manifest.json")
    assert payload.read_bytes() == before
