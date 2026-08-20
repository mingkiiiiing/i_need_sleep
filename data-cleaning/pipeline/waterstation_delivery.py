from __future__ import annotations

"""P08-01 delivery isolation for authorized station/buoy files.

This step is intentionally metadata-only.  It never parses a station file,
copies it into a cleaning directory, or marks a template as authorization.
It records delivery IDs, authorization evidence paths, checksums and an
inventory so P08-02 can perform the read-only preflight later.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import manifest_root
from .sources.common import PACKAGE_ROOT, sha256_file, utc_now


SUPPORTED_DATA_SUFFIXES = {".json", ".csv", ".tsv", ".xlsx"}
EVIDENCE_NAMES = {"authorization.yml", "authorization.yaml", "authorization.json", "authorization.md", "receipt.md", "delivery_manifest.json", "delivery_manifest.yml", "delivery_manifest.yaml"}
DEFAULT_INBOX = PACKAGE_ROOT / "storage" / "raw" / "authorized_waterstation" / "inbox"
DEFAULT_INVENTORY = PACKAGE_ROOT / "storage" / "reports" / "waterstation_delivery_inventory.csv"
DEFAULT_MANIFEST = PACKAGE_ROOT / "storage" / "manifests" / "waterstation_delivery_p08_01.json"


def _is_template(path: Path) -> bool:
    name = path.name.casefold()
    if "template" in name or name in {"readme.md", "readme.txt"}:
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:20000]
    except OSError:
        return False
    markers = ("DRAFT_READY", "PENDING_MANUAL_SUBMISSION", "[填写]", "[提交后填写")
    return any(marker in text for marker in markers)


def _looks_like_evidence(path: Path) -> bool:
    return path.name.casefold() in EVIDENCE_NAMES or "authorization" in path.name.casefold() or "receipt" in path.name.casefold()


def _load_evidence(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "readable": False, "provider_name": None, "valid_from": None, "valid_until": None, "authorization_type": None, "external_request_id": None, "template_like": _is_template(path)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result["error"] = str(exc)
        return result
    result["readable"] = True
    result["sha256"] = sha256_file(path)
    # Evidence files are not copied into the manifest; only non-sensitive
    # field presence is retained.  YAML/Markdown/JSON all get a conservative
    # marker-based extraction without echoing contact details or tokens.
    for field in ("provider_name", "valid_from", "valid_until", "authorization_type", "external_request_id"):
        marker = f"{field}:"
        for line in text.splitlines():
            if line.strip().casefold().startswith(marker):
                value = line.split(":", 1)[1].strip().strip('"\'`')
                result[field] = value if value and value not in {"[填写]", "[提交后填写，不要编造]"} else None
                break
    result["has_authorization_language"] = any(token in text.casefold() for token in ("authorized", "授权", "permission", "许可", "research"))
    result["has_delivery_identifier"] = any(token in text.casefold() for token in ("delivery_id", "delivery-id", "交付id", "工单"))
    return result


def _write_inventory(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["delivery_id", "relative_path", "file_role", "suffix", "size_bytes", "sha256", "template_like", "authorization_evidence", "status", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run_waterstation_delivery(
    *,
    inbox_root: Path | str = DEFAULT_INBOX,
    inventory_path: Path | str = DEFAULT_INVENTORY,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    delivery_id: str | None = None,
) -> dict[str, Any]:
    """Inspect delivery inbox and create a checksum/authorization manifest."""

    inbox = Path(inbox_root)
    inbox.mkdir(parents=True, exist_ok=True)
    inventory_file = Path(inventory_path)
    manifest_file = Path(manifest_path)
    delivery_dirs = sorted(path for path in inbox.iterdir() if path.is_dir() and (delivery_id is None or path.name == delivery_id))
    rows: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    if not delivery_dirs:
        # Root-level templates are intentionally inventoried as ignored; this
        # makes the first run auditable without pretending a delivery exists.
        for path in sorted(inbox.iterdir()):
            if path.is_file():
                rows.append({"delivery_id": None, "relative_path": path.name, "file_role": "template_or_unexpected_root_file", "suffix": path.suffix.casefold(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path), "template_like": _is_template(path), "authorization_evidence": False, "status": "ignored_not_delivery", "error": "files must be placed under inbox/<delivery_id>/"})
        result = {"task_id": "P08-01", "status": "BLOCKED_AUTH", "data_truth": "no_authorized_delivery", "inbox_root": str(inbox), "delivery_count": 0, "deliveries": [], "inventory": str(inventory_file), "next_action": "obtain the signed authorization/receipt and place the original export under inbox/<delivery_id>/; do not use templates"}
        _write_inventory(inventory_file, rows)
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(json.dumps({**result, "manifest": str(manifest_file), "retrieved_at_utc": utc_now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    for delivery_dir in delivery_dirs:
        delivery_name = delivery_dir.name
        files = sorted(path for path in delivery_dir.rglob("*") if path.is_file())
        evidence = [path for path in files if _looks_like_evidence(path)]
        delivery_manifest_files = [path for path in evidence if path.name.casefold() in {"delivery_manifest.json", "delivery_manifest.yml", "delivery_manifest.yaml"}]
        authorization_files = [path for path in evidence if path not in delivery_manifest_files]
        data_files = [path for path in files if path.suffix.casefold() in SUPPORTED_DATA_SUFFIXES and path not in evidence and not _is_template(path)]
        evidence_records = [_load_evidence(path) for path in authorization_files]
        delivery_manifest_records = [_load_evidence(path) for path in delivery_manifest_files]
        valid_evidence = [item for item in evidence_records if item.get("readable") and not item.get("template_like") and item.get("has_authorization_language")]
        valid_delivery_manifests = [item for item in delivery_manifest_records if item.get("readable") and not item.get("template_like") and item.get("has_delivery_identifier")]
        delivery_status = "isolated" if data_files and valid_evidence and valid_delivery_manifests else "BLOCKED_AUTH"
        for path in files:
            role = "data" if path in data_files else "authorization_evidence" if path in authorization_files else "delivery_manifest" if path in delivery_manifest_files else "supporting_file"
            rows.append({"delivery_id": delivery_name, "relative_path": str(path.relative_to(delivery_dir)), "file_role": role, "suffix": path.suffix.casefold(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path), "template_like": _is_template(path), "authorization_evidence": path in evidence, "status": delivery_status if role == "data" else "recorded", "error": None if delivery_status == "isolated" or role != "data" else "missing_valid_authorization_evidence"})
        deliveries.append({"delivery_id": delivery_name, "status": delivery_status, "data_files": [str(path.relative_to(delivery_dir)) for path in data_files], "data_file_count": len(data_files), "authorization_evidence": evidence_records, "authorization_evidence_count": len(valid_evidence), "delivery_manifests": delivery_manifest_records, "delivery_manifest_count": len(valid_delivery_manifests), "delivery_path": str(delivery_dir)})

    overall = "isolated" if deliveries and all(item["status"] == "isolated" for item in deliveries) else "BLOCKED_AUTH"
    result = {"task_id": "P08-01", "status": overall, "data_truth": "authorized_delivery_metadata_only" if overall == "isolated" else "delivery_present_but_authorization_incomplete", "inbox_root": str(inbox), "delivery_count": len(deliveries), "deliveries": deliveries, "inventory": str(inventory_file), "next_action": "P08-02 read-only preflight" if overall == "isolated" else "obtain a non-template authorization/receipt with scope, validity and delivery identifier; keep files isolated"}
    _write_inventory(inventory_file, rows)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps({**result, "manifest": str(manifest_file), "retrieved_at_utc": utc_now()}, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


__all__ = ["DEFAULT_INBOX", "DEFAULT_INVENTORY", "DEFAULT_MANIFEST", "run_waterstation_delivery"]
