from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from ..provenance import build_asset_manifest, manifest_root, write_asset_manifest


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PACKAGE_ROOT / "storage" / "raw"


@dataclass
class IngestResult:
    source_id: str
    status: str
    request_url: str
    raw_path: str | None
    records: int
    retrieved_at: str
    error: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(url: str, timeout: int = 60, headers: Mapping[str, str] | None = None) -> tuple[int, str, Any]:
    request_headers = {"User-Agent": "A23-Taihu-data-pipeline/0.1", **dict(headers or {})}
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, content_type, payload


def write_raw_json(source_id: str, url: str, status: int, content_type: str, payload: Any) -> Path:
    target_dir = RAW_ROOT / source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = target_dir / f"{stamp}.json"
    envelope = {
        "request_url": url,
        "retrieved_at": utc_now(),
        "http_status": status,
        "content_type": content_type,
        "payload": payload,
    }
    output.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    asset_manifest = build_asset_manifest(
        source_id=source_id,
        asset_id=output.stem,
        request_url=url,
        local_path=output,
        retrieved_at_utc=envelope["retrieved_at"],
        http_status=status,
        response_headers={"Content-Type": content_type},
        status="completed" if status == 200 else "failed",
    )
    write_asset_manifest(
        asset_manifest,
        manifest_root(PACKAGE_ROOT) / f"raw_{source_id}_{stamp}.json",
    )
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    return int(status if status is not None else response.getcode())


def _download_manifest_path(source_id: str, asset_id: str) -> Path:
    safe_source = "".join(char if char.isalnum() or char in "-_" else "_" for char in source_id)
    safe_asset = "".join(char if char.isalnum() or char in "-_" else "_" for char in asset_id)
    return manifest_root(PACKAGE_ROOT) / f"download_{safe_source}_{safe_asset}.json"


def download_asset(
    source_id: str,
    asset_id: str,
    url: str,
    output_path: Path,
    *,
    expected_sha256: str | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: int = 120,
    retries: int = 0,
    headers: Mapping[str, str] | None = None,
    license_tag: str | None = None,
    redistribution_allowed: str | None = None,
    commercial_use: str | None = None,
) -> dict[str, Any]:
    """Download one asset with resumable ``.partial`` and checksum idempotency.

    A completed file is never overwritten when its source/asset/checksum match.
    Interrupted writes remain in ``<output>.partial`` and are resumed with an
    HTTP Range request when the server supports it. The final rename is atomic.
    """

    output_path = Path(output_path)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expected = expected_sha256.lower() if expected_sha256 else None
    manifest_path = _download_manifest_path(source_id, asset_id)
    attempts = 0

    if output_path.exists():
        actual = sha256_file(output_path)
        if expected and actual.lower() != expected:
            raise ValueError(f"existing asset checksum mismatch for {source_id}/{asset_id}")
        if not expected and manifest_path.exists():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = {}
            if previous.get("source_id") != source_id or previous.get("asset_id") != asset_id or previous.get("checksum_sha256") != actual:
                raise FileExistsError(
                    f"existing asset is not proven idempotent for {source_id}/{asset_id}; provide expected_sha256"
                )
        elif not expected:
            raise FileExistsError(
                f"existing asset requires expected_sha256 for idempotent reuse: {source_id}/{asset_id}"
            )
        manifest = build_asset_manifest(
            source_id=source_id,
            asset_id=asset_id,
            request_url=url,
            local_path=output_path,
            http_status=None,
            license_tag=license_tag,
            redistribution_allowed=redistribution_allowed,
            commercial_use=commercial_use,
            retries=0,
            status="skipped_existing",
        )
        write_asset_manifest(manifest, manifest_path)
        return {
            "status": "skipped_existing",
            "source_id": source_id,
            "asset_id": asset_id,
            "path": str(output_path),
            "checksum_sha256": actual,
            "size_bytes": output_path.stat().st_size,
            "resumed": False,
            "attempts": 0,
            "manifest": str(manifest_path),
        }

    opener = urlopen if opener is None else opener
    request_headers = {"User-Agent": "A23-Taihu-data-pipeline/0.3", **dict(headers or {})}
    while True:
        attempts += 1
        offset = partial_path.stat().st_size if partial_path.exists() else 0
        request_headers_for_attempt = dict(request_headers)
        if offset:
            request_headers_for_attempt["Range"] = f"bytes={offset}-"
        request = Request(url, headers=request_headers_for_attempt)
        try:
            with opener(request, timeout=timeout) as response:
                status = _response_status(response)
                resumed = offset > 0 and status == 206
                if offset and not resumed:
                    # The server ignored Range; restart the partial safely.
                    offset = 0
                    partial_path.unlink(missing_ok=True)
                mode = "ab" if resumed else "wb"
                with partial_path.open(mode) as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            actual = sha256_file(partial_path)
            if expected and actual.lower() != expected:
                raise ValueError(
                    f"download checksum mismatch for {source_id}/{asset_id}; partial retained at {partial_path}"
                )
            partial_path.replace(output_path)
            manifest = build_asset_manifest(
                source_id=source_id,
                asset_id=asset_id,
                request_url=url,
                local_path=output_path,
                http_status=status,
                license_tag=license_tag,
                redistribution_allowed=redistribution_allowed,
                commercial_use=commercial_use,
                retries=attempts - 1,
                status="completed",
            )
            write_asset_manifest(manifest, manifest_path)
            return {
                "status": "completed",
                "source_id": source_id,
                "asset_id": asset_id,
                "path": str(output_path),
                "checksum_sha256": actual,
                "size_bytes": output_path.stat().st_size,
                "resumed": resumed,
                "attempts": attempts,
                "manifest": str(manifest_path),
            }
        except ValueError:
            raise
        except Exception:
            if attempts > retries:
                raise
