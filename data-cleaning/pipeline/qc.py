from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
QC_RULES_PATH = PACKAGE_ROOT / "config" / "qc_rules.yml"


def _load_rules() -> dict[str, Any]:
    try:
        with QC_RULES_PATH.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return payload if isinstance(payload, dict) else {}
    except (OSError, yaml.YAMLError):
        # Keep the library importable in a minimal environment, but use the
        # conservative built-in rules until dependencies/config are restored.
        return {
            "hard_range_rules": {
                "air_temperature": [-60, 60],
                "wind_speed": [0, 60],
                "wind_direction": [0, 360],
                "precipitation": [0, 500],
                "shortwave_radiation": [0, 2000],
                "cloud_cover": [0, 100],
            },
            "duplicate_key": {"fields": ["source_id", "station_id", "scene_id", "observed_at", "variable_code"]},
            "normalization": {"wind_direction_360_to_zero": {"enabled": True}},
            "missing_value": {"issue_code": "Q01"},
            "rejection": {"issue_codes": ["Q02", "Q03", "Q04", "Q06", "Q07", "Q08", "Q10", "Q11"], "appended_flag": "Q99"},
        }


RULES = _load_rules()
RANGES: dict[str, tuple[float, float]] = {
    str(code): (float(bounds[0]), float(bounds[1]))
    for code, bounds in (RULES.get("hard_range_rules") or {}).items()
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2
}
DUPLICATE_KEY_FIELDS = tuple((RULES.get("duplicate_key") or {}).get("fields") or ["source_id", "station_id", "scene_id", "observed_at", "variable_code"])
REJECTION_CODES = set((RULES.get("rejection") or {}).get("issue_codes") or ["Q02", "Q03", "Q04", "Q06", "Q07", "Q10", "Q11", "Q08"])
REJECTION_FLAG = str((RULES.get("rejection") or {}).get("appended_flag") or "Q99")
NORMALIZE_WIND_DIRECTION = bool(((RULES.get("normalization") or {}).get("wind_direction_360_to_zero") or {}).get("enabled", True))
MISSING_CODE = str((RULES.get("missing_value") or {}).get("issue_code") or "Q01")


def _issue(row: dict[str, Any], code: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "source_file": row.get("source_file"),
        "source_row": row.get("source_row"),
        "variable_code": row.get("variable_code"),
        "issue_code": code,
        "severity": severity,
        "message": message,
        "observed_value": row.get("observed_value"),
    }


def quality_control(records: list[dict[str, Any]]) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    imputation_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    flag_counts: Counter[str] = Counter()
    for row in records:
        flags: list[str] = list(row.get("quality_flags") or [])
        key = tuple(row.get(field) for field in DUPLICATE_KEY_FIELDS)
        if key in seen:
            flags.append("Q08")
            issues.append(_issue(row, "Q08", "medium", "duplicate business key"))
        seen.add(key)

        if not row.get("observed_at"):
            flags.append("Q03")
            issues.append(_issue(row, "Q03", "high", "missing or invalid observation timestamp"))

        if row.get("unit_issue"):
            flags.append(row["unit_issue"])
            issues.append(_issue(row, row["unit_issue"], "high", row.get("unit_issue_message", "unit consistency failure")))

        for coordinate_name, bounds in (("longitude", (-180, 180)), ("latitude", (-90, 90))):
            coordinate = row.get(coordinate_name)
            if coordinate is None:
                continue
            try:
                numeric_coordinate = float(coordinate)
                if not math.isfinite(numeric_coordinate):
                    raise ValueError
            except (TypeError, ValueError):
                flags.append("Q06")
                issues.append(_issue(row, "Q06", "high", f"invalid {coordinate_name}"))
            else:
                if not (bounds[0] <= numeric_coordinate <= bounds[1]):
                    flags.append("Q07")
                    issues.append(_issue(row, "Q07", "high", f"{coordinate_name} outside allowed range {bounds}"))

        value = row.get("clean_value")
        if value is None:
            flags.append(MISSING_CODE)
            issues.append(_issue(row, MISSING_CODE, "high", "missing value"))
        elif not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            flags.append("Q02")
            issues.append(_issue(row, "Q02", "high", "non-numeric or non-finite value"))
        else:
            bounds = RANGES.get(row.get("variable_code"))
            if bounds and not (bounds[0] <= float(value) <= bounds[1]):
                flags.append("Q04")
                issues.append(_issue(row, "Q04", "critical", f"outside allowed range {bounds}"))
            if NORMALIZE_WIND_DIRECTION and row.get("variable_code") == "wind_direction" and float(value) == 360:
                row["clean_value"] = 0.0
                flags.append("Q21")
                issues.append(_issue(row, "Q21", "low", "wind direction normalized from 360 to 0"))

        row["quality_flags"] = flags or ["Q00"]
        if any(code in flags for code in REJECTION_CODES):
            row["quality_flags"].append(REJECTION_FLAG)
            rejected.append(row)
        elif MISSING_CODE in flags:
            # Missing observations remain traceable, but are kept out of the
            # modeling table until the explicit imputation stage handles them.
            imputation_candidates.append(row)
        else:
            cleaned.append(row)
        flag_counts.update(row["quality_flags"])

    return {
        "cleaned": cleaned,
        "imputation_candidates": imputation_candidates,
        "rejected": rejected,
        "issues": issues,
        "flag_counts": dict(flag_counts),
    }
