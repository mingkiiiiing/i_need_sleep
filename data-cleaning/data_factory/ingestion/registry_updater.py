"""来源登记状态更新与变更留痕 (设计 §8/§17.3)."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def update_automation_status(source_id: str, new_status: str, *, registry_csv: Path, log: Path | None = None) -> bool:
    registry_csv = Path(registry_csv)
    if not registry_csv.exists():
        return False
    with registry_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = list(csv.DictReader(handle))
    fieldnames = list(reader[0].keys()) if reader else []
    updated = False
    for row in reader:
        if row.get("source_id") == source_id and row.get("automation_status") != new_status:
            row["automation_status"] = new_status
            updated = True
    if not updated:
        return False
    with registry_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
    if log is not None:
        entry = {
            "at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "action": "update_automation_status",
            "source_id": source_id,
            "new_status": new_status,
            "registry": str(registry_csv),
        }
        with Path(log).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True


def append_transformation_log(entry: dict, log: Path) -> None:
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with Path(log).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
