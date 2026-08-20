from __future__ import annotations

"""Backward-compatible JSON envelope shared by all CLI responses."""

from collections.abc import Mapping
from typing import Any


def contract_response(payload: Mapping[str, Any], *, command: str | None = None) -> dict[str, Any]:
    result = dict(payload)
    status = result.get("status") or "completed"
    run_id = result.get("run_id") or result.get("task_id") or result.get("source_id") or command or "cli"
    rows_read = result.get("rows_read", result.get("input_rows", result.get("records", 0)))
    rows_written = result.get("rows_written", result.get("output_rows", result.get("records", result.get("row_count", 0))))
    rows_rejected = result.get("rows_rejected", result.get("rejected_rows", 0))
    outputs = result.get("outputs")
    if outputs is None:
        outputs = {key: result[key] for key in ("output", "database", "csv", "parquet") if result.get(key)}
    warnings = result.get("warnings", [])
    if isinstance(warnings, str):
        warnings = [warnings]
    envelope = {
        "status": status,
        "run_id": str(run_id),
        "rows_read": int(rows_read or 0),
        "rows_written": int(rows_written or 0),
        "rows_rejected": int(rows_rejected or 0),
        "outputs": outputs,
        "manifest": result.get("manifest"),
        "warnings": list(warnings),
        "next_action": result.get("next_action"),
    }
    # Preserve command-specific fields for compatibility while making the
    # common contract unconditionally available.
    return {**result, **envelope}
