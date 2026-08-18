from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


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


def request_json(url: str, timeout: int = 60) -> tuple[int, str, Any]:
    request = Request(url, headers={"User-Agent": "A23-Taihu-data-pipeline/0.1"})
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
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
