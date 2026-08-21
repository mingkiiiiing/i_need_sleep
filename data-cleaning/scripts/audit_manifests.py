from __future__ import annotations

"""Classify production and historical test manifests without deleting evidence."""

import csv
import json
import re
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = PACKAGE_ROOT / "storage" / "manifests"
OUTPUT = PACKAGE_ROOT / "storage" / "exports" / "manifest_audit.csv"
TEMP_PATTERN = re.compile(r"AppData[\\/]Local[\\/]Temp|pytest-|tmp[a-zA-Z0-9_\\/-]+", re.IGNORECASE)


def classify(path: Path) -> dict[str, str | int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        serialized = json.dumps(payload, ensure_ascii=False)
        parse_status = "valid"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        payload = {}
        serialized = ""
        parse_status = f"invalid:{type(exc).__name__}"
    artifact_class = "test_fixture" if TEMP_PATTERN.search(serialized) else "production_or_manual"
    input_value = payload.get("input")
    input_path = Path(str(input_value)) if input_value else None
    if input_path is not None and not input_path.is_absolute():
        input_path = PACKAGE_ROOT / input_path
    return {
        "manifest": str(path),
        "run_id": str(payload.get("run_id") or path.stem),
        "status": str(payload.get("status") or "__missing__"),
        "artifact_class": artifact_class,
        "parse_status": parse_status,
        "input_exists": int(bool(input_path and input_path.exists())),
        "file_count": len(payload.get("files") or {}) if isinstance(payload.get("files"), dict) else 0,
    }


def main() -> None:
    rows = [classify(path) for path in sorted(MANIFEST_ROOT.glob("*.json"))]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["manifest"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": str(OUTPUT), "manifest_count": len(rows), "test_fixture_count": sum(row["artifact_class"] == "test_fixture" for row in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
