"""不可变原始快照存储 (设计 §8.2)。存在即跳过，附 provenance sidecar。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.provenance import build_asset_manifest, write_asset_manifest


def snapshot_path(raw_root: Path, source_id: str, now_utc: datetime) -> Path:
    return Path(raw_root) / source_id / now_utc.strftime("%Y/%m/%d") / f"{source_id}_{now_utc.strftime('%Y%m%dT%H%M%SZ')}.json"


def snapshot_exists(path: Path) -> Path | None:
    return path if Path(path).exists() else None


def write_raw_snapshot(
    source_id: str,
    payload: bytes,
    *,
    raw_root: Path,
    now_utc: datetime | None = None,
    request_url: str = "",
    http_status: int | None = None,
    response_headers: dict[str, Any] | None = None,
    retries: int = 0,
    status: str = "completed",
    error: str | None = None,
    extra: dict[str, Any] | None = None,
    license_tag: str | None = "public_snapshot_not_for_redistribution",
) -> Path:
    now_utc = now_utc or datetime.now(timezone.utc)
    path = snapshot_path(Path(raw_root), source_id, now_utc)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    manifest = build_asset_manifest(
        source_id=source_id,
        asset_id=path.stem,
        request_url=request_url,
        local_path=path,
        retrieved_at_utc=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        http_status=http_status,
        response_headers=response_headers,
        license_tag=license_tag,
        retries=retries,
        status=status,
        error=error,
    )
    if extra:
        manifest.update(extra)
    write_asset_manifest(manifest, path.with_suffix(".manifest.json"))
    return path


def load_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def iter_snapshots(raw_root: Path, source_id: str) -> list[Path]:
    base = Path(raw_root) / source_id
    if not base.exists():
        return []
    return sorted(base.glob("**/*.json"))
