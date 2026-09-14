from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lineage_record(
    path: str | Path,
    role: str,
    source_class: str,
    source_url: str = "",
    access_status: str = "available",
) -> dict[str, object]:
    file_path = Path(path)
    exists = file_path.exists()
    return {
        "path": str(file_path.resolve()) if exists else str(file_path),
        "role": role,
        "source_class": source_class,
        "source_url": source_url,
        "access_status": access_status if exists else "not_downloaded",
        "byte_size": file_path.stat().st_size if exists else 0,
        "sha256": sha256_file(file_path) if exists else "",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_lineage(records: list[dict[str, object]]) -> pd.DataFrame:
    columns = (
        "path",
        "role",
        "source_class",
        "source_url",
        "access_status",
        "byte_size",
        "sha256",
        "recorded_at_utc",
    )
    return pd.DataFrame(records, columns=columns)
