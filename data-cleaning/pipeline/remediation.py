from __future__ import annotations

"""Turn a training-gate result into an actionable P0 data request package."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
ACTION_CATALOG: dict[str, dict[str, str]] = {
    "coverage_historical": {
        "priority": "P0",
        "data_product": "历史高频目标与驱动数据",
        "required_fields": "chlorophyll_a/algae_density/bloom_area_km2; water_temperature; total_nitrogen; total_phosphorus",
        "minimum_cadence": "目标≤72小时；水温≤24小时；TN/TP≤72小时",
        "acceptance": "coverage.short_term_ready=true",
    },
    "coverage_operational": {
        "priority": "P0",
        "data_product": "准实时水站/浮标增量数据",
        "required_fields": "站点ID、经纬度、观测时间、目标字段和驱动字段",
        "minimum_cadence": "连续更新；最新数据距审计时间≤30天",
        "acceptance": "coverage.operational_short_term_ready=true",
    },
    "labels_horizon_1_3d": {
        "priority": "P0",
        "data_product": "1—3天目标序列",
        "required_fields": "同站点/同变量连续未来观测",
        "minimum_cadence": "日级或更高；每个目标样本存在1—3天未来值",
        "acceptance": "availability_rate≥0.5且overall_status=ready",
    },
    "labels_horizon_7_15d": {
        "priority": "P0",
        "data_product": "7—15天目标序列",
        "required_fields": "同站点/同变量连续未来观测",
        "minimum_cadence": "日级或更高；每个目标样本存在7—15天未来值",
        "acceptance": "availability_rate≥0.5且overall_status=ready",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_sqlite(path: Path, requests: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS p0_data_requests")
        connection.execute("DROP TABLE IF EXISTS remediation_summary")
        connection.execute("CREATE TABLE p0_data_requests (check_name TEXT PRIMARY KEY, status TEXT, priority TEXT, data_product TEXT, required_fields TEXT, minimum_cadence TEXT, acceptance TEXT, observed_value TEXT, threshold TEXT, reason TEXT)")
        connection.executemany(
            "INSERT INTO p0_data_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
            [tuple(row.get(key) for key in ("check_name", "status", "priority", "data_product", "required_fields", "minimum_cadence", "acceptance", "observed_value", "threshold", "reason")) for row in requests],
        )
        connection.execute("CREATE TABLE remediation_summary (gate_status TEXT, open_request_count INTEGER, resolved_check_count INTEGER, next_run_command TEXT)")
        connection.execute("INSERT INTO remediation_summary VALUES (?,?,?,?)", (summary["gate_status"], summary["open_request_count"], summary["resolved_check_count"], summary["next_run_command"]))
        connection.commit()
    finally:
        connection.close()


def build_remediation(gate: dict[str, Any], *, next_run_command: str = "python -m pipeline run-batch --through gate") -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for check in gate.get("checks", []):
        name = str(check.get("check_name") or "")
        catalog = ACTION_CATALOG.get(name)
        if catalog is None:
            continue
        requests.append({"check_name": name, "status": "open" if check.get("status") != "passed" else "resolved", **catalog, "observed_value": check.get("observed_value"), "threshold": check.get("threshold"), "reason": check.get("reason")})
    open_count = sum(row["status"] == "open" for row in requests)
    resolved_count = sum(row["status"] == "resolved" for row in requests)
    return {"gate_status": gate.get("gate_status", "blocked"), "open_request_count": open_count, "resolved_check_count": resolved_count, "next_run_command": next_run_command, "requests": requests}


def run_remediation(
    gate_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    manifest_path: Path | None = None,
    run_id: str | None = None,
    next_run_command: str = "python -m pipeline run-batch --through gate",
) -> dict[str, Any]:
    gate = _read_json(gate_path)
    result = build_remediation(gate, next_run_command=next_run_command)
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or STORAGE / "exports" / "p0_remediation"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {"summary": output_root / "p0_remediation.json", "requests": output_root / "p0_data_requests.csv"}
    files["summary"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(files["requests"], result["requests"])
    database = database or STORAGE / "data_cleaning.db"
    _write_sqlite(database, result["requests"], result)
    manifest = {"run_id": run_id or "p0_remediation", "status": "completed", "input": str(gate_path), "files": {key: str(value) for key, value in {**files, "database": database}.items()}, **result}
    manifest_path = manifest_path or STORAGE / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
