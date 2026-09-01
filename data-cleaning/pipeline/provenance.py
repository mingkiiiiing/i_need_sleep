from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "secret",
    "signature",
    "token",
    " X-api-key".strip().lower(),
}
_SENSITIVE_HEADER_KEYS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
}


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))


def manifest_root(package_root: Path) -> Path:
    """Return the manifest directory, allowing test runs to stay isolated."""

    override = os.environ.get("A23_MANIFEST_ROOT")
    return Path(override) if override else STORAGE / "manifests"


def staging_root(package_root: Path) -> Path:
    """Return the staging directory, allowing test runs to stay isolated."""

    override = os.environ.get("A23_STAGING_ROOT")
    return Path(override) if override else STORAGE / "staging"


def sanitize_url(url: str) -> str:
    """Remove credentials and bearer-like query values from a URL."""

    if not url:
        return url
    parsed = urlsplit(str(url))
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        safe_value = "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else value
        query.append((key, safe_value))
    return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment))


def sanitize_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """Preserve response-header names while redacting credential-bearing values."""

    safe: dict[str, str] = {}
    for key, value in (headers or {}).items():
        name = str(key)
        safe[name] = "[REDACTED]" if name.lower() in _SENSITIVE_HEADER_KEYS else str(value)
    return safe


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_asset_manifest(
    *,
    source_id: str,
    asset_id: str,
    request_url: str | None = None,
    local_path: Path | str | None = None,
    requested_at_utc: str | None = None,
    retrieved_at_utc: str | None = None,
    http_status: int | None = None,
    response_headers: Mapping[str, Any] | None = None,
    license_tag: str | None = None,
    redistribution_allowed: str | None = None,
    commercial_use: str | None = None,
    retries: int = 0,
    status: str = "completed",
    error: str | None = None,
) -> dict[str, Any]:
    """Build the shared raw-asset provenance contract used by source adapters."""

    path = Path(local_path) if local_path is not None else None
    exists = bool(path and path.exists() and path.is_file())
    return {
        "schema_version": "1.0",
        "manifest_type": "raw_asset",
        "source_id": source_id,
        "asset_id": asset_id,
        "request_url": sanitize_url(request_url or ""),
        "local_path": str(path) if path is not None else None,
        "requested_at_utc": requested_at_utc,
        "retrieved_at_utc": retrieved_at_utc,
        "http_status": http_status,
        "response_headers": sanitize_headers(response_headers),
        "checksum_sha256": sha256_file(path) if exists else None,
        "size_bytes": path.stat().st_size if exists else None,
        "license": {
            "license_tag": license_tag,
            "redistribution_allowed": redistribution_allowed,
            "commercial_use": commercial_use,
        },
        "retries": int(retries),
        "status": status,
        "error": error,
    }


def write_asset_manifest(manifest: Mapping[str, Any], output_path: Path) -> Path:
    """Persist a JSON manifest with a stable, UTF-8 encoded contract."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path
