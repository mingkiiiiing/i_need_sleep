from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _unit_key(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "").replace("·", "")


def _load_policy() -> tuple[dict[str, str], dict[str, str], dict[tuple[str, str], float]]:
    root = Path(__file__).resolve().parents[1]
    units = yaml.safe_load((root / "config" / "units.yml").read_text(encoding="utf-8")) or {}
    variables = yaml.safe_load((root / "config" / "variables.yml").read_text(encoding="utf-8")) or {}
    aliases: dict[str, str] = {}
    for canonical, values in (units.get("unit_aliases") or {}).items():
        aliases[_unit_key(canonical)] = canonical
        for value in values or []:
            aliases[_unit_key(value)] = canonical
    expected = {
        item.get("code"): item.get("unit")
        for item in variables.get("variables", [])
        if item.get("code")
    }
    conversions = {
        (_unit_key(item.get("from")), _unit_key(item.get("to"))): float(item.get("multiplier", 1.0))
        for item in units.get("conversions", [])
    }
    return aliases, expected, conversions


def _append_rule(existing: str | None, rule: str) -> str:
    return f"{existing}; {rule}" if existing else rule


def standardize_units(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize aliases and apply only explicitly configured conversions.

    The original source unit is copied to ``source_unit`` before ``unit`` is
    replaced. Unknown or missing units are marked for QC instead of guessed.
    """
    aliases, expected_units, conversions = _load_policy()
    for row in records:
        # Preserve an immutable source pair before any aliasing or numerical
        # conversion.  Older callers may only provide observed_value/unit;
        # backfill the audit fields without changing their behavior.
        row.setdefault("raw_value", row.get("observed_value", row.get("clean_value")))
        row.setdefault("raw_unit", row.get("source_unit") or row.get("unit"))
        source_unit = row.get("source_unit") or row.get("unit")
        row["source_unit"] = source_unit
        variable_code = row.get("variable_code")
        expected = expected_units.get(variable_code)
        if not expected or expected in {"null", "None"}:
            row["unit_valid"] = True
            continue
        if source_unit in (None, ""):
            row["unit_issue"] = "Q10"
            row["unit_issue_message"] = f"missing source unit; expected {expected}"
            row["unit_valid"] = False
            continue
        source_canonical = aliases.get(_unit_key(source_unit), str(source_unit).strip())
        expected_canonical = aliases.get(_unit_key(expected), expected)
        row["source_unit"] = source_unit
        if _unit_key(source_canonical) == _unit_key(expected_canonical):
            row["unit"] = expected_canonical
            row["unit_valid"] = True
            continue
        multiplier = conversions.get((_unit_key(source_canonical), _unit_key(expected_canonical)))
        if multiplier is None:
            row["unit"] = source_canonical
            row["unit_issue"] = "Q11"
            row["unit_issue_message"] = f"incompatible unit {source_unit}; expected {expected}"
            row["unit_valid"] = False
            continue
        if row.get("clean_value") is not None:
            try:
                row["clean_value"] = float(row["clean_value"]) * multiplier
            except (TypeError, ValueError):
                pass
        row["unit"] = expected_canonical
        row["conversion_rule"] = _append_rule(
            row.get("conversion_rule"),
            f"{source_canonical}->{expected_canonical} x {multiplier:g}",
        )
        flags = list(row.get("quality_flags") or [])
        if "Q21" not in flags:
            flags.append("Q21")
        row["quality_flags"] = flags
        row["unit_valid"] = True
    return {"records": records}
