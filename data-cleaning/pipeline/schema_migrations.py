"""Explicit, transactional SQLite schema migrations for the Taihu pipeline."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


LATEST_SCHEMA_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at_utc TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )


def _migration_v1(connection: sqlite3.Connection) -> None:
    """Introduce a metadata table without touching legacy application tables."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS database_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO database_metadata(key, value) VALUES (?, ?)",
        ("schema_contract", "taihu_a23"),
    )


def _migration_v2(connection: sqlite3.Connection) -> None:
    """Add an audit timestamp to metadata, idempotently."""

    columns = {row[1] for row in connection.execute("PRAGMA table_info(database_metadata)")}
    if "updated_at_utc" not in columns:
        connection.execute("ALTER TABLE database_metadata ADD COLUMN updated_at_utc TEXT")
    connection.execute(
        "UPDATE database_metadata SET updated_at_utc = COALESCE(updated_at_utc, ?)",
        (_utc_now(),),
    )


MIGRATIONS: dict[int, tuple[str, Callable[[sqlite3.Connection], None]]] = {
    1: ("create database metadata", _migration_v1),
    2: ("add metadata audit timestamp", _migration_v2),
}


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the highest applied migration, or zero for an unversioned DB."""

    try:
        row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0)


def migrate_database(database: Path, target_version: int = LATEST_SCHEMA_VERSION) -> dict[str, object]:
    """Upgrade a SQLite database transactionally and repeatably.

    Existing application tables are never dropped or silently recreated. A
    migration failure rolls back the entire version step and leaves the
    database at its previous version.
    """

    database = Path(database)
    if target_version < 0 or target_version > LATEST_SCHEMA_VERSION:
        raise ValueError(f"target_version must be between 0 and {LATEST_SCHEMA_VERSION}")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _ensure_version_table(connection)
        previous_version = current_schema_version(connection)
        if target_version < previous_version:
            raise ValueError(
                f"downgrade is not supported: database={previous_version}, target={target_version}"
            )
        applied: list[int] = []
        for version in range(previous_version + 1, target_version + 1):
            description, migration = MIGRATIONS[version]
            try:
                connection.execute("SAVEPOINT schema_migration")
                migration(connection)
                connection.execute(
                    "INSERT INTO schema_version(version, applied_at_utc, description) VALUES (?, ?, ?)",
                    (version, _utc_now(), description),
                )
                connection.execute("RELEASE schema_migration")
                applied.append(version)
            except Exception:
                connection.execute("ROLLBACK TO schema_migration")
                connection.execute("RELEASE schema_migration")
                raise
        current = current_schema_version(connection)
    return {
        "database": str(database),
        "previous_version": previous_version,
        "current_version": current,
        "target_version": target_version,
        "applied_migrations": applied,
        "status": "migrated" if applied else "already_current",
    }

