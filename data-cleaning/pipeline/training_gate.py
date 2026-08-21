from __future__ import annotations

"""Machine-readable model-input gate for the Taihu cleaning pipeline.

The gate does not train a model.  It consolidates the independent coverage,
future-label and split audits into one conservative decision so downstream
code cannot mistake a historical demonstration batch for a short-term-ready
production dataset.
"""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().casefold() in {"true", "1", "yes", "passed", "ready"}


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


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


def _write_sqlite(path: Path, checks: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS training_gate_checks")
        connection.execute("DROP TABLE IF EXISTS training_gate_summary")
        connection.execute("CREATE TABLE training_gate_checks (check_name TEXT PRIMARY KEY, status TEXT, required INTEGER, observed_value TEXT, threshold TEXT, reason TEXT)")
        connection.executemany(
            "INSERT INTO training_gate_checks VALUES (?,?,?,?,?,?)",
            [(row.get("check_name"), row.get("status"), int(bool(row.get("required"))), str(row.get("observed_value")), str(row.get("threshold")), row.get("reason")) for row in checks],
        )
        connection.execute("CREATE TABLE training_gate_summary (gate_status TEXT, required_check_count INTEGER, passed_required_check_count INTEGER, blocked_check_count INTEGER, reasons TEXT)")
        connection.execute(
            "INSERT INTO training_gate_summary VALUES (?,?,?,?,?)",
            (summary["gate_status"], summary["required_check_count"], summary["passed_required_check_count"], summary["blocked_check_count"], json.dumps(summary["reasons"], ensure_ascii=False)),
        )
        connection.commit()
    finally:
        connection.close()


def evaluate_training_gate(
    coverage: dict[str, Any],
    label_rows: Iterable[dict[str, Any]],
    split_audit: dict[str, Any],
    split_summary: Iterable[dict[str, Any]],
    *,
    required_horizons: tuple[str, ...] = ("horizon_1_3d", "horizon_7_15d"),
    min_label_availability: float = 0.5,
    max_missing_feature_rate: float = 0.4,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, threshold: Any, reason: str, *, required: bool = True) -> None:
        checks.append({"check_name": name, "status": "passed" if passed else "blocked", "required": required, "observed_value": observed, "threshold": threshold, "reason": reason})

    add("coverage_historical", _bool(coverage.get("short_term_ready")), coverage.get("short_term_ready"), True, "历史目标和必需驱动覆盖门禁")
    add("coverage_operational", _bool(coverage.get("operational_short_term_ready")), coverage.get("operational_short_term_ready"), True, "最新数据新鲜度和频率门禁")

    label_by_horizon = {str(row.get("horizon")): row for row in label_rows}
    for horizon in required_horizons:
        row = label_by_horizon.get(horizon, {})
        availability = _float(row.get("availability_rate")) or 0.0
        passed = str(row.get("overall_status")) == "ready" and availability >= min_label_availability
        add(f"labels_{horizon}", passed, availability, min_label_availability, f"{horizon}未来标签可用率")

    duplicate_count = int(split_audit.get("duplicate_target_key_count") or 0)
    time_ok = _bool(split_audit.get("time_order_ok"))
    add("split_duplicate_keys", duplicate_count == 0, duplicate_count, 0, "目标键不得跨样本重复")
    add("split_time_order", time_ok, split_audit.get("time_order_ok"), True, "时间切分必须保持时间顺序")

    summaries = list(split_summary)
    missing_rates = [_float(row.get("missing_feature_rate")) for row in summaries if row.get("dataset_split") in {"train", "validation", "test"}]
    missing_rates = [value for value in missing_rates if value is not None]
    max_missing = max(missing_rates) if missing_rates else None
    add("feature_missing_rate", max_missing is not None and max_missing <= max_missing_feature_rate, max_missing, max_missing_feature_rate, "训练/验证/测试特征缺失率上限")

    reasons = [str(row["reason"]) for row in checks if row["required"] and row["status"] != "passed"]
    required_count = sum(bool(row["required"]) for row in checks)
    passed_count = sum(bool(row["required"]) and row["status"] == "passed" for row in checks)
    return {
        "gate_status": "ready" if not reasons else "blocked",
        "required_check_count": required_count,
        "passed_required_check_count": passed_count,
        "blocked_check_count": sum(row["status"] == "blocked" for row in checks),
        "reasons": reasons,
        "checks": checks,
        "thresholds": {"required_horizons": list(required_horizons), "min_label_availability": min_label_availability, "max_missing_feature_rate": max_missing_feature_rate},
    }


def run_training_gate(
    coverage_path: Path,
    labels_path: Path,
    split_audit_path: Path,
    split_summary_path: Path,
    output_root: Path | None = None,
    database: Path | None = None,
    *,
    manifest_path: Path | None = None,
    run_id: str | None = None,
    required_horizons: tuple[str, ...] = ("horizon_1_3d", "horizon_7_15d"),
    min_label_availability: float = 0.5,
    max_missing_feature_rate: float = 0.4,
) -> dict[str, Any]:
    coverage = _read_json(coverage_path)
    labels = _read_csv(labels_path)
    split_audit = _read_json(split_audit_path)
    split_summary = _read_csv(split_summary_path)
    result = evaluate_training_gate(coverage, labels, split_audit, split_summary, required_horizons=required_horizons, min_label_availability=min_label_availability, max_missing_feature_rate=max_missing_feature_rate)
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or root / "storage" / "exports" / "training_gate"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {"summary": output_root / "training_gate.json", "checks": output_root / "training_gate_checks.csv"}
    files["summary"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(files["checks"], result["checks"])
    database = database or root / "storage" / "data_cleaning.db"
    _write_sqlite(database, result["checks"], result)
    manifest = {"run_id": run_id or f"training_gate_{files['summary'].stem}", "status": result["gate_status"], "inputs": {"coverage": str(coverage_path), "labels": str(labels_path), "split_audit": str(split_audit_path), "split_summary": str(split_summary_path)}, "files": {key: str(value) for key, value in {**files, "database": database}.items()}, **result}
    manifest_path = manifest_path or root / "storage" / "manifests" / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
