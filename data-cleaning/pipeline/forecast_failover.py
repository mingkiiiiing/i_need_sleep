"""Deterministic ECMWF/GFS/Open-Meteo forecast-source failover.

Selection is performed on already-ingested, schema-compatible CSV batches. A
candidate is usable only when its source/model identity is correct and its
forecast coverage reaches the requested horizon. Every candidate health check
and the final selection are written to the shared source-health SQLite file.
Only one source is copied to the selected output, so model rows are never
silently mixed.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .source_health import record_forecast_source_switch, update_source_health


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
REQUIRED_FIELDS = {
    "source_id", "model_name", "forecast_reference_time", "valid_time",
    "lead_hours", "variable_code", "value", "unit",
}


class ForecastSourceSelectionError(RuntimeError):
    """Raised when no configured source satisfies the requested horizon."""


def load_forecast_priority(path: Path | None = None) -> dict[str, Any]:
    config_path = Path(path or PACKAGE_ROOT / "config" / "forecast_source_priority.yml")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sources = payload.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise ValueError("forecast source priority must contain a non-empty sources list")
    priorities = [int(item.get("priority", 999)) for item in sources]
    if len(priorities) != len(set(priorities)):
        raise ValueError("forecast source priorities must be unique")
    return {"path": str(config_path), **payload, "sources": sorted(sources, key=lambda item: int(item.get("priority", 999)))}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("forecast times must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read_candidate(path: Path, *, source_id: str, model_name: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"forecast candidate does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_FIELDS - fields)
        if missing:
            raise ValueError(f"{path} missing forecast fields: {missing}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"forecast candidate is empty: {path}")
    source_values = sorted({str(row.get("source_id", "")) for row in rows})
    model_values = sorted({str(row.get("model_name", "")) for row in rows})
    if source_values != [source_id]:
        raise ValueError(f"source identity mismatch: expected {source_id}, got {source_values}")
    if model_values != [model_name]:
        raise ValueError(f"model identity mismatch for {source_id}: expected {model_name}, got {model_values}")
    numeric_leads: list[float] = []
    valid_times: list[datetime] = []
    variables: set[str] = set()
    missing_values = 0
    for row in rows:
        try:
            numeric_leads.append(float(row["lead_hours"]))
            valid_times.append(_parse_time(row["valid_time"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid forecast time/lead in {path}: {exc}") from exc
        variables.add(str(row.get("variable_code", "")))
        if row.get("value") in {None, "", "nan", "NaN"}:
            missing_values += 1
    return rows, {
        "row_count": len(rows),
        "coverage_hours": max(numeric_leads),
        "latest_valid_time": max(valid_times).isoformat().replace("+00:00", "Z"),
        "variables": sorted(variables),
        "missing_values": missing_values,
        "total_values": len(rows),
        "fields": sorted(fields),
    }


def evaluate_forecast_candidates(
    candidates: Mapping[str, Path | str],
    *,
    config: Mapping[str, Any] | None = None,
    environment: str = "production",
    required_horizon_hours: float = 72.0,
    health_database: Path | None = None,
    run_id: str = "forecast-failover",
    checked_at_utc: str | None = None,
) -> dict[str, Any]:
    """Evaluate candidates, write health rows, and record the selected source."""

    config = dict(config or load_forecast_priority())
    source_specs = list(config.get("sources") or [])
    statuses: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    first_failed_source: str | None = None
    for spec in sorted(source_specs, key=lambda item: int(item.get("priority", 999))):
        source_id = str(spec["source_id"])
        model_name = str(spec["model_name"])
        rank = int(spec.get("priority", 999))
        allowed = {str(item) for item in spec.get("environments", ["production", "development"])}
        status: dict[str, Any] = {"source_id": source_id, "model_name": model_name, "priority": rank, "role": spec.get("role"), "status": "skipped", "reason": None}
        path_value = candidates.get(source_id)
        if environment not in allowed:
            status.update(reason=f"not_allowed_in_{environment}")
            statuses.append(status)
            continue
        if path_value is None:
            status.update(status="failed", reason="candidate_path_not_provided")
            if first_failed_source is None:
                first_failed_source = source_id
            statuses.append(status)
            if health_database:
                update_source_health(health_database, source_id=source_id, run_id=f"{run_id}:{source_id}", success=False, checked_at_utc=checked_at_utc, authorization_status=str(spec.get("authorization_status", "unknown")), error_message=status["reason"])
            continue
        try:
            rows, metrics = _read_candidate(Path(path_value), source_id=source_id, model_name=model_name)
            if metrics["coverage_hours"] < required_horizon_hours:
                raise ValueError(f"coverage {metrics['coverage_hours']}h is below required {required_horizon_hours}h")
            status.update(status="ready", reason="identity_and_coverage_valid", path=str(path_value), **metrics)
            if health_database:
                update_source_health(
                    health_database, source_id=source_id, run_id=f"{run_id}:{source_id}", success=True,
                    checked_at_utc=checked_at_utc, latest_observed_at_utc=metrics["latest_valid_time"],
                    row_count=metrics["row_count"], expected_fields=spec.get("required_variables", []),
                    actual_fields=metrics["variables"], missing_values=metrics["missing_values"],
                    total_values=metrics["total_values"], authorization_status=str(spec.get("authorization_status", "unknown")),
                )
            if selected is None:
                selected = {"source_id": source_id, "model_name": model_name, "priority": rank, "path": str(path_value), "rows": rows, "metrics": metrics, "role": spec.get("role")}
        except Exception as exc:
            status.update(status="failed", reason=str(exc), path=str(path_value))
            if first_failed_source is None:
                first_failed_source = source_id
            if health_database:
                update_source_health(
                    health_database, source_id=source_id, run_id=f"{run_id}:{source_id}", success=False,
                    checked_at_utc=checked_at_utc, authorization_status=str(spec.get("authorization_status", "unknown")), error_message=str(exc),
                )
        statuses.append(status)

    if selected is None:
        reason = "no_candidate_satisfies_identity_and_horizon"
        if health_database:
            record_forecast_source_switch(
                health_database, run_id=run_id, environment=environment,
                selected_source_id="NONE", selected_model_name="NONE", selected_rank=999,
                selection_reason=reason, fallback_from_source_id=first_failed_source,
                candidate_statuses=statuses, checked_at_utc=checked_at_utc,
            )
        return {"status": "no_source", "selected": None, "candidates": statuses, "reason": reason}

    switched = selected["priority"] > min((int(item.get("priority", 999)) for item in source_specs), default=selected["priority"])
    reason = "primary_selected" if not switched else "primary_unavailable_fallback_selected"
    switch = None
    if health_database:
        switch = record_forecast_source_switch(
            health_database, run_id=run_id, environment=environment,
            selected_source_id=selected["source_id"], selected_model_name=selected["model_name"],
            selected_rank=selected["priority"], selection_reason=reason,
            fallback_from_source_id=first_failed_source if switched else None,
            candidate_statuses=statuses, checked_at_utc=checked_at_utc,
        )
    return {"status": "selected", "selected": {key: value for key, value in selected.items() if key != "rows"}, "rows": selected["rows"], "candidates": statuses, "switch": switch, "selection_reason": reason}


def _write_selected(rows: list[dict[str, Any]], output: Path) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else sorted(REQUIRED_FIELDS)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return str(output)


def run_forecast_failover(
    candidates: Mapping[str, Path | str],
    *,
    priority_config: Path | None = None,
    environment: str = "production",
    required_horizon_hours: float = 72.0,
    output: Path | None = None,
    health_database: Path | None = None,
    manifest_path: Path | None = None,
    run_id: str = "forecast-failover",
    checked_at_utc: str | None = None,
) -> dict[str, Any]:
    config = load_forecast_priority(priority_config)
    health_database = Path(health_database or STORAGE / "databases" / "forecast_source_health.sqlite")
    decision = evaluate_forecast_candidates(
        candidates, config=config, environment=environment, required_horizon_hours=required_horizon_hours,
        health_database=health_database, run_id=run_id, checked_at_utc=checked_at_utc,
    )
    output_path = None
    if decision["status"] == "selected":
        output_path = _write_selected(decision["rows"], Path(output or STORAGE / "silver" / "forecast" / "selected" / "forecast_selected.csv"))
    result = {
        "task_id": "P05-06", "status": "completed" if decision["status"] == "selected" else "blocked",
        "selection": {key: value for key, value in decision.items() if key != "rows"},
        "selected_output": output_path, "health_database": str(health_database),
        "priority_config": str(config["path"]), "environment": environment,
        "required_horizon_hours": required_horizon_hours,
    }
    manifest_path = Path(manifest_path or STORAGE / "manifests" / f"forecast_failover_{run_id}.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


__all__ = ["ForecastSourceSelectionError", "evaluate_forecast_candidates", "load_forecast_priority", "run_forecast_failover"]
