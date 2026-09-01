from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def _safe_run_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._")
    if not cleaned:
        raise ValueError("run_id must contain at least one alphanumeric character")
    return cleaned


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_root: Path
    database: Path
    manifest_path: Path
    stages_root: Path
    created_at: str

    @classmethod
    def create(cls, *, run_id: str | None = None, runs_root: Path | None = None) -> "RunContext":
        created_at = datetime.now(UTC).isoformat()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        normalized_id = _safe_run_id(run_id or f"run_{stamp}")
        root = Path(runs_root) if runs_root is not None else STORAGE / "runs"
        run_root = root / normalized_id
        if run_root.exists():
            raise FileExistsError(f"run directory already exists: {run_root}")
        stages_root = run_root / "stages"
        stages_root.mkdir(parents=True, exist_ok=False)
        return cls(
            run_id=normalized_id,
            run_root=run_root,
            database=run_root / "data_cleaning.db",
            manifest_path=run_root / "run_manifest.json",
            stages_root=stages_root,
            created_at=created_at,
        )

    def write_metadata(self, *, status: str, raw_root: Path | None = None, rules_version: str | None = None) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_run (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_root TEXT,
                    rules_version TEXT
                )
                """
            )
            now = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO pipeline_run(run_id, created_at, updated_at, status, raw_root, rules_version)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET updated_at=excluded.updated_at,
                    status=excluded.status, raw_root=excluded.raw_root, rules_version=excluded.rules_version
                """,
                (self.run_id, self.created_at, now, status, str(raw_root) if raw_root else None, rules_version),
            )
            connection.commit()
        finally:
            connection.close()

    def write_manifest(self, payload: dict[str, Any]) -> Path:
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.manifest_path
