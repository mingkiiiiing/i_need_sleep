from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from pipeline.sources.cma_files import parse_cma_bytes, parse_cma_file


def _wide_csv() -> bytes:
    text = (
        "站号,站名,观测时间,经度,纬度,TEM,PRE,质量码\n"
        "58321,太湖站,2020-06-01 08:00:00,120.3,31.2,25.5,-999,0\n"
        "58321,太湖站,2020-06-01 09:00:00,120.3,31.2,26.0,1.2,1\n"
    )
    return text.encode("gb18030")


def test_cma_csv_retains_time_missing_quality_and_units() -> None:
    result = parse_cma_bytes(_wide_csv(), path_label="taihu.csv")
    rows = result["observations"]
    assert len(rows) == 4
    tem = next(row for row in rows if row["source_parameter"] == "TEM" and row["observed_at_local"].startswith("2020-06-01T08:00"))
    rain = next(row for row in rows if row["source_parameter"] == "PRE" and row["observed_at_local"].startswith("2020-06-01T08:00"))
    assert tem["station_id"] == "58321"
    assert tem["unit"] == "degC"
    assert tem["observed_at_utc"] == "2020-06-01T00:00:00+00:00"
    assert rain["clean_value"] is None
    assert rain["missing_code"] == "-999"
    assert "CMA_MISSING" in rain["quality_flags"]
    assert tem["quality_code"] == "0"
    assert "CMA_QC_0" in tem["quality_flags"]
    assert result["encodings"]["taihu.csv"] == "gb18030"


def test_cma_long_form_honors_explicit_utc_and_source_unit() -> None:
    raw = "station_id,UTC时间,要素代码,观测值,单位,缺测码,质控码\n58321,2020-06-01T00:00:00Z,TEM,25.5,degC,,A\n".encode()
    rows = parse_cma_bytes(raw, path_label="long.txt")["observations"]
    assert len(rows) == 1
    assert rows[0]["observed_at_utc"] == "2020-06-01T00:00:00+00:00"
    assert rows[0]["source_timezone"] == "UTC"
    assert rows[0]["source_unit"] == "degC"
    assert rows[0]["quality_code"] == "A"


def test_cma_zip_writes_standard_csv(tmp_path: Path) -> None:
    archive = tmp_path / "cma.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("2020/a.csv", _wide_csv())
        handle.writestr("README.md", "not a data member")
    output = tmp_path / "cleaned.csv"
    result = parse_cma_file(archive, output)
    assert result["members"] == ["2020/a.csv"]
    assert result["records"] == 4
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["station_id"] for row in rows} == {"58321"}
