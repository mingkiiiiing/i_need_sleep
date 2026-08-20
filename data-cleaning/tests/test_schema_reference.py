import sqlite3

from pipeline.schema_reference import CORE_TABLES, create_schema_reference


def test_reference_database_has_all_core_tables_indexes_and_constraints(tmp_path):
    database = tmp_path / "schema_reference.sqlite"
    result = create_schema_reference(database)
    assert result["core_table_count"] == len(CORE_TABLES)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        observations_pk = [
            row for row in connection.execute("PRAGMA table_info(observations_long)") if row[5]
        ]
        raw_unique = [row for row in connection.execute("PRAGMA index_list(raw_assets)") if row[2]]
    assert set(CORE_TABLES).issubset(tables)
    assert "idx_observations_time" in indexes
    assert "idx_stations_lon_lat" in indexes
    assert len(observations_pk) == 5
    assert raw_unique


def test_reference_database_creation_is_idempotent(tmp_path):
    database = tmp_path / "schema_reference.sqlite"
    first = create_schema_reference(database)
    second = create_schema_reference(database)
    assert first["core_table_count"] == len(CORE_TABLES)
    assert second["core_table_count"] == len(CORE_TABLES)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone() == (2,)
        assert connection.execute("SELECT COUNT(*) FROM schema_version").fetchone() == (2,)
