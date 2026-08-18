from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def impute_short_gaps(
    records: list[dict[str, Any]],
    *,
    max_gap_steps: int = 3,
    step_minutes: int = 60,
) -> dict[str, Any]:
    """Interpolate only short, bracketed gaps in a station-variable series.

    The function never fills an edge gap, a long gap, a non-hourly gap, a
    duplicate, or a record that already failed a physical-range check. Missing
    records remain in ``pending`` so downstream models can use a mask rather
    than receiving an invented value without provenance.
    """
    if max_gap_steps < 1 or step_minutes < 1:
        raise ValueError("max_gap_steps and step_minutes must be positive")

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        key = (
            row.get("source_id"),
            row.get("station_id"),
            row.get("scene_id"),
            row.get("variable_code"),
        )
        groups[key].append(row)

    imputed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    step_seconds = step_minutes * 60

    for group in groups.values():
        ordered = sorted(group, key=lambda row: _parse_time(row.get("observed_at")) or datetime.max)
        for index, row in enumerate(ordered):
            if row.get("clean_value") is not None:
                continue
            timestamp = _parse_time(row.get("observed_at"))
            previous = next(
                (ordered[position] for position in range(index - 1, -1, -1) if ordered[position].get("clean_value") is not None),
                None,
            )
            following = next(
                (ordered[position] for position in range(index + 1, len(ordered)) if ordered[position].get("clean_value") is not None),
                None,
            )
            previous_time = _parse_time(previous.get("observed_at")) if previous else None
            following_time = _parse_time(following.get("observed_at")) if following else None
            if not timestamp or not previous or not following or not previous_time or not following_time:
                pending.append(row)
                continue
            gap_seconds = (following_time - previous_time).total_seconds()
            missing_steps = round(gap_seconds / step_seconds) - 1
            if (
                missing_steps < 1
                or missing_steps > max_gap_steps
                or abs(gap_seconds - (missing_steps + 1) * step_seconds) > 1
            ):
                pending.append(row)
                continue
            position = (timestamp - previous_time).total_seconds() / gap_seconds
            value = float(previous["clean_value"]) + position * (float(following["clean_value"]) - float(previous["clean_value"]))
            row["clean_value"] = value
            row["is_imputed"] = True
            row["value_origin"] = "imputed"
            row["imputation_method"] = "linear_time"
            row["imputation_confidence"] = round(max(0.5, 1.0 - 0.15 * missing_steps), 3)
            flags = list(row.get("quality_flags") or [])
            if "Q20" not in flags:
                flags.append("Q20")
            row["quality_flags"] = flags
            imputed.append(row)

    return {"records": records, "imputed": imputed, "pending": pending}
