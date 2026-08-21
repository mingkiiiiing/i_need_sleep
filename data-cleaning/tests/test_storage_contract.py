import sqlite3
from pathlib import Path

from pipeline.schema_reference import CORE_TABLES, create_schema_reference


CONTRACT = Path(__file__).parents[1] / "docs" / "storage_contract.md"


def test_storage_contract_covers_required_large_file_types_and_forbids_blob():
    text = CONTRACT.read_text(encoding="utf-8")
    for marker in ("栅格", "GRIB", "NetCDF", "Parquet", "GeoTIFF", "BLOB", "checksum_sha256", "raw_assets"):
        assert marker in text
    assert "结果必须为空" in text


def test_reference_schema_has_no_blob_columns_and_has_external_file_index(tmp_path):
    database = tmp_path / "schema_reference.sqlite"
    create_schema_reference(database)
    with sqlite3.connect(database) as connection:
        blob_columns = connection.execute(
            """
            SELECT m.name, p.name
            FROM sqlite_master AS m
            JOIN pragma_table_info(m.name) AS p
            WHERE m.type='table' AND upper(p.type)='BLOB'
            """
        ).fetchall()
        raw_columns = {row[1] for row in connection.execute("PRAGMA table_info(raw_assets)")}
    assert blob_columns == []
    assert {"local_path", "checksum_sha256", "size_bytes"}.issubset(raw_columns)
