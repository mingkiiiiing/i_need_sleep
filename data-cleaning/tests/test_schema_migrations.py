import sqlite3

import pytest

from pipeline.schema_migrations import LATEST_SCHEMA_VERSION, migrate_database


def test_empty_database_is_created_from_zero(tmp_path):
    database = tmp_path / "empty.db"
    result = migrate_database(database)
    assert result["previous_version"] == 0
    assert result["current_version"] == LATEST_SCHEMA_VERSION
    assert result["applied_migrations"] == [1, 2]
    with sqlite3.connect(database) as connection:
        versions = connection.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        metadata = connection.execute("SELECT value FROM database_metadata WHERE key='schema_contract'").fetchone()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(database_metadata)")}
    assert versions == [(1,), (2,)]
    assert metadata == ("taihu_a23",)
    assert "updated_at_utc" in columns


def test_legacy_tables_and_rows_survive_upgrade(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy_observations(id INTEGER PRIMARY KEY, value REAL)")
        connection.execute("INSERT INTO legacy_observations VALUES (1, 3.14)")
    result = migrate_database(database)
    assert result["status"] == "migrated"
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT value FROM legacy_observations WHERE id=1").fetchone()
    assert row == (3.14,)


def test_repeated_migration_is_idempotent(tmp_path):
    database = tmp_path / "repeat.db"
    first = migrate_database(database)
    second = migrate_database(database)
    assert first["applied_migrations"] == [1, 2]
    assert second["applied_migrations"] == []
    assert second["status"] == "already_current"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_version").fetchone() == (2,)


def test_downgrade_is_rejected_without_mutation(tmp_path):
    database = tmp_path / "downgrade.db"
    migrate_database(database)
    with pytest.raises(ValueError, match="downgrade"):
        migrate_database(database, target_version=1)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone() == (2,)
