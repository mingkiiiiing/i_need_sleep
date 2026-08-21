from __future__ import annotations

"""Download the open satellite-ground synchronous Taihu water dataset."""

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

RECORD_ID = "10434391"
API = f"https://zenodo.org/api/records/{RECORD_ID}"


def run_zenodo_taihu_insitu(output_root: Path, *, manifest_path: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    metadata = requests.get(API, timeout=timeout)
    metadata.raise_for_status()
    record = metadata.json()
    selected = [item for item in record.get("files") or [] if str(item.get("key") or "").startswith("Lake Taihu_")]
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = []
    for item in selected:
        name = Path(unquote(str(item["key"]))).name
        path = output_root / name
        response = requests.get(item["links"]["self"], timeout=timeout)
        response.raise_for_status()
        path.write_bytes(response.content)
        md5 = hashlib.md5(response.content).hexdigest()
        expected = str(item.get("checksum") or "").removeprefix("md5:")
        outputs.append({"path": str(path), "bytes": len(response.content), "md5": md5, "expected_md5": expected, "checksum_ok": md5 == expected})
    status = "completed" if outputs and all(item["checksum_ok"] for item in outputs) else "failed_checksum"
    manifest_path = manifest_path or output_root / "manifest.json"
    manifest = {"source_id": "zenodo_taihu_satellite_ground_insitu", "record_id": RECORD_ID, "doi": record.get("doi"), "status": status, "authorization": "none", "file_count": len(outputs), "outputs": outputs, "manifest": str(manifest_path)}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
