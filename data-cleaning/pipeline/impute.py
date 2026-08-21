from __future__ import annotations

"""Missingness mechanism classification and conservative short-gap handling.

Missing rows do not all mean the same thing.  A failed endpoint, an offline
sensor, a low-frequency laboratory result, a cloud-masked satellite pixel and
a physically rejected observation require different downstream actions.  This
module annotates those mechanisms before any imputation decision is made.
"""

import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable


UTC = timezone.utc

MISSING_MECHANISM_CATEGORIES = (
    "not_missing",
    "interface_failure",
    "device_offline",
    "low_frequency",
    "cloud_masked",
    "quality_rejected",
    "temporal_gap_short",
    "temporal_gap_long",
    "edge_gap",
    "unknown",
)

# These are hard-rejection or structural QC codes. Q01 itself is a missing
# value candidate, while Q12/Q18/Q19/Q25-Q41 are review flags.
QUALITY_REJECT_CODES = {
    "Q02", "Q03", "Q04", "Q06", "Q07", "Q08", "Q10", "Q11",
    "Q13", "Q14", "Q15", "Q99",
}
CLOUD_CODES = {"Q34"}
INTERFACE_FAILURE_STATUSES = {
    "failed", "failure", "error", "unavailable", "timeout", "blocked_auth",
    "blocked", "http_error", "connection_error", "rate_limited",
}
OFFLINE_STATUSES = {
    "offline", "down", "disconnected", "no_signal", "not_reporting",
    "sensor_offline", "station_offline", "device_error",
}

MECHANISM_POLICIES = {
    "not_missing": "observed_or_existing_value",
    "interface_failure": "retry_or_failover; never_impute_from_same_failed_response",
    "device_offline": "check_telemetry_and_hold_missing",
    "low_frequency": "retain_native_frequency_and_emit_data_age",
    "cloud_masked": "use_cross_sensor_or_lag_feature; never_overwrite_current_observation",
    "quality_rejected": "manual_review_or_source_repair; never_treat_as_observed",
    "temporal_gap_short": "eligible_for_P10_02_masked_validation_only",
    "temporal_gap_long": "retain_missing_or_uncertainty_model; no_silent_forward_fill",
    "edge_gap": "retain_missing; no_bracketed_interpolation",
    "unknown": "manual_review_before_any_imputation",
}

HIGH_FREQUENCY_MAX_INTERVAL_MINUTES = 6.0 * 60.0
DEFAULT_NEVER_AUTO_IMPUTE = {"chlorophyll_a", "algae_density", "bloom_area_km2"}
ALLOWED_SHORT_GAP_METHODS = {"linear_time"}
LOW_FREQUENCY_NUTRIENT_VARIABLES = {
    "total_nitrogen",
    "total_phosphorus",
    "ammonia_nitrogen",
    "nitrate_nitrogen",
    "nitrite_nitrogen",
    "phosphate_phosphorus",
    "total_kjeldahl_nitrogen",
}
DEFAULT_LOW_FREQUENCY_MAX_AGE_HOURS = 30.0 * 24.0

# Wind direction is a circular quantity.  Interpolating its degree value
# directly turns a physically small 359°→1° change into a false 180° jump.
# The convention below follows meteorological ``from`` direction: 0° is wind
# from north, 90° from east, and u/v are eastward/northward components.
WIND_DIRECTION_VARIABLE = "wind_direction"
WIND_SPEED_VARIABLE = "wind_speed"
WIND_U_COMPONENT = "wind_u_component"
WIND_V_COMPONENT = "wind_v_component"
DEFAULT_CALM_WIND_SPEED_MPS = 0.1
WIND_DIRECTION_CONVENTION = "meteorological_from"


def _parse_time(value: Any) -> datetime | None:
    if value in (None, "", "None", "null"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "null", "nan", "NaN"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flags(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item not in (None, "")}
    if value in (None, "", "None", "null", "[]"):
        return set()
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {str(value)}
    return {str(item) for item in parsed} if isinstance(parsed, list) else {str(value)}


def _is_missing(row: dict[str, Any]) -> bool:
    # ``clean_value`` is authoritative once normalization/QC has run.  A raw
    # numeric value alongside a null clean value is commonly a rejected row,
    # and must remain classified as missing rather than being treated as an
    # observed measurement.
    if "clean_value" in row:
        return _number(row.get("clean_value")) is None
    if "value" in row:
        return _number(row.get("value")) is None
    for key in ("observed_value", "raw_value"):
        if _number(row.get(key)) is not None:
            return False
    return True


def _canonical_mechanism(value: Any) -> str | None:
    token = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "interface": "interface_failure",
        "api_failure": "interface_failure",
        "endpoint_failure": "interface_failure",
        "offline": "device_offline",
        "sensor_offline": "device_offline",
        "low_frequency_normal": "low_frequency",
        "sparse": "low_frequency",
        "cloud": "cloud_masked",
        "cloud_mask": "cloud_masked",
        "qc_rejected": "quality_rejected",
        "rejected": "quality_rejected",
        "short_gap": "temporal_gap_short",
        "long_gap": "temporal_gap_long",
        "edge": "edge_gap",
    }
    token = aliases.get(token, token)
    return token if token in MISSING_MECHANISM_CATEGORIES else None


def _source_health_record(source_health: Any, source_id: str) -> dict[str, Any] | None:
    if isinstance(source_health, dict):
        candidate = source_health.get(source_id)
        if isinstance(candidate, dict):
            return candidate
        if source_health.get("source_id") == source_id:
            return source_health
        return None
    if isinstance(source_health, Iterable) and not isinstance(source_health, (str, bytes)):
        for candidate in source_health:
            if isinstance(candidate, dict) and str(candidate.get("source_id") or "") == source_id:
                return candidate
    return None


def _source_events_for(source_events: Any, source_id: str) -> list[dict[str, Any]]:
    if isinstance(source_events, dict):
        candidate = source_events.get(source_id, [])
        if isinstance(candidate, dict):
            return [candidate]
        return [item for item in candidate if isinstance(item, dict)] if isinstance(candidate, list) else []
    if isinstance(source_events, Iterable) and not isinstance(source_events, (str, bytes)):
        return [item for item in source_events if isinstance(item, dict) and str(item.get("source_id") or "") == source_id]
    return []


def _event_is_interface_failure(event: dict[str, Any]) -> bool:
    status = str(event.get("status") or event.get("source_status") or event.get("run_status") or "").casefold()
    if status in INTERFACE_FAILURE_STATUSES or any(token in status for token in ("fail", "error", "timeout", "blocked")):
        return True
    http_status = _number(event.get("http_status") or event.get("status_code"))
    return http_status is not None and http_status >= 400


def _row_status(row: dict[str, Any]) -> str:
    for key in ("device_status", "sensor_status", "station_status", "availability_status", "telemetry_status"):
        token = str(row.get(key) or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if token:
            return token
    return ""


def _lookup_expected_interval(expected_intervals: Any, row: dict[str, Any]) -> float | None:
    if not isinstance(expected_intervals, dict):
        minutes = _number(row.get("expected_interval_minutes"))
        if minutes is not None:
            return minutes
        hours = _number(row.get("expected_interval_hours"))
        return hours * 60.0 if hours is not None else None
    source = str(row.get("source_id") or "")
    variable = str(row.get("variable_code") or "")
    for candidate in ((source, variable), f"{source}:{variable}", variable, source):
        if candidate in expected_intervals:
            value = expected_intervals[candidate]
            if isinstance(value, dict):
                minutes = _number(value.get("minutes"))
                if minutes is not None:
                    return minutes
                hours = _number(value.get("hours"))
                return hours * 60.0 if hours is not None else None
            return _number(value)
    minutes = _number(row.get("expected_interval_minutes"))
    if minutes is not None:
        return minutes
    hours = _number(row.get("expected_interval_hours"))
    return hours * 60.0 if hours is not None else None


def _series_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("source_id"), row.get("station_id"), row.get("scene_id"), row.get("variable_code"))


def _series_intervals(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], list[float]]:
    grouped: dict[tuple[Any, ...], list[datetime]] = defaultdict(list)
    for row in rows:
        if _number(row.get("clean_value")) is None and _number(row.get("observed_value")) is None:
            continue
        moment = _parse_time(row.get("observed_at"))
        if moment is not None:
            grouped[_series_key(row)].append(moment)
    intervals: dict[tuple[Any, ...], list[float]] = {}
    for key, moments in grouped.items():
        ordered = sorted(set(moments))
        intervals[key] = [(right - left).total_seconds() / 60.0 for left, right in zip(ordered, ordered[1:]) if right > left]
    return intervals


def _gap_context(row: dict[str, Any], rows: list[dict[str, Any]], *, max_gap_steps: int, step_minutes: int) -> tuple[str, str]:
    timestamp = _parse_time(row.get("observed_at"))
    if timestamp is None:
        return "edge_gap", "missing or invalid timestamp prevents bracketing"
    same_series = sorted((item for item in rows if _series_key(item) == _series_key(row) and _parse_time(item.get("observed_at")) is not None), key=lambda item: _parse_time(item.get("observed_at")) or timestamp)
    prior = [item for item in same_series if (_parse_time(item.get("observed_at")) or timestamp) < timestamp and not _is_missing(item)]
    following = [item for item in same_series if (_parse_time(item.get("observed_at")) or timestamp) > timestamp and not _is_missing(item)]
    if not prior or not following:
        return "edge_gap", "no valid observed values on both sides"
    left = _parse_time(prior[-1].get("observed_at"))
    right = _parse_time(following[0].get("observed_at"))
    if left is None or right is None or right <= left:
        return "edge_gap", "invalid bracketing interval"
    missing_steps = round((right - left).total_seconds() / (step_minutes * 60.0)) - 1
    if 1 <= missing_steps <= max_gap_steps:
        return "temporal_gap_short", f"bracketed gap of {missing_steps} step(s)"
    return "temporal_gap_long", f"bracketed gap of {max(0, missing_steps)} step(s) exceeds short-gap limit"


def _gap_context_indexed(row: dict[str, Any], valid_times: list[datetime], *, max_gap_steps: int, step_minutes: int) -> tuple[str, str]:
    """Indexed equivalent of ``_gap_context`` for large time series."""
    timestamp = _parse_time(row.get("observed_at"))
    if timestamp is None:
        return "edge_gap", "missing or invalid timestamp prevents bracketing"
    left_position = bisect_left(valid_times, timestamp) - 1
    right_position = bisect_right(valid_times, timestamp)
    if left_position < 0 or right_position >= len(valid_times):
        return "edge_gap", "no valid observed values on both sides"
    left, right = valid_times[left_position], valid_times[right_position]
    if right <= left:
        return "edge_gap", "invalid bracketing interval"
    missing_steps = round((right - left).total_seconds() / (step_minutes * 60.0)) - 1
    if 1 <= missing_steps <= max_gap_steps:
        return "temporal_gap_short", f"bracketed gap of {missing_steps} step(s)"
    return "temporal_gap_long", f"bracketed gap of {max(0, missing_steps)} step(s) exceeds short-gap limit"


def classify_missing_mechanisms(
    records: list[dict[str, Any]],
    *,
    source_events: Any = None,
    source_health: Any = None,
    expected_intervals: Any = None,
    max_gap_steps: int = 3,
    step_minutes: int = 60,
    low_frequency_factor: float = 2.0,
) -> dict[str, Any]:
    """Annotate every row with an evidence-backed missingness mechanism."""
    if max_gap_steps < 1 or step_minutes < 1 or low_frequency_factor <= 0:
        raise ValueError("max_gap_steps, step_minutes and low_frequency_factor must be positive")
    intervals = _series_intervals(records)
    valid_time_index: dict[tuple[Any, ...], list[datetime]] = defaultdict(list)
    for indexed_row in records:
        indexed_time = _parse_time(indexed_row.get("observed_at"))
        if indexed_time is not None and not _is_missing(indexed_row):
            valid_time_index[_series_key(indexed_row)].append(indexed_time)
    valid_time_index = {key: sorted(set(values)) for key, values in valid_time_index.items()}
    counts: Counter[str] = Counter()
    by_source_variable: Counter[tuple[str, str, str]] = Counter()

    for row in records:
        flags = _flags(row.get("quality_flags"))
        source_id = str(row.get("source_id") or "__missing__")
        variable = str(row.get("variable_code") or "__missing__")
        mechanism = "not_missing"
        detail = "value is present"
        confidence = "high"
        if _is_missing(row):
            explicit = next((_canonical_mechanism(row.get(key)) for key in ("missing_mechanism", "missing_reason", "missing_category") if _canonical_mechanism(row.get(key))), None)
            status = _row_status(row)
            health = _source_health_record(source_health, source_id)
            events = _source_events_for(source_events, source_id)
            health_status = str(health.get("status") or "").casefold() if health else ""
            auth_status = str(health.get("authorization_status") or "").casefold() if health else ""
            if explicit and explicit != "not_missing":
                mechanism, detail = explicit, "explicit source missingness reason"
            elif any(_event_is_interface_failure(event) for event in events) or health_status in INTERFACE_FAILURE_STATUSES or auth_status in {"blocked", "blocked_auth", "missing"}:
                mechanism, detail = "interface_failure", "source health or ingestion event reports endpoint failure"
            elif status in OFFLINE_STATUSES or any(token in status for token in ("offline", "disconnected", "no_signal")):
                mechanism, detail = "device_offline", f"device status={status}"
            elif bool(row.get("cloud_masked")) or row.get("cloud_valid") is False or str(row.get("cloud_mask_method") or "").casefold() in {"scl_cloud_or_snow", "cloud_mask", "cloud_masked"} or (_number(row.get("cloud_cover")) is not None and _number(row.get("cloud_cover")) >= 90.0) or (_number(row.get("cloud_probability")) is not None and _number(row.get("cloud_probability")) >= 90.0) or bool(flags & CLOUD_CODES):
                mechanism, detail = "cloud_masked", "cloud mask or high cloud probability invalidated the observation"
            elif str(row.get("record_status") or "").casefold() in {"rejected", "reject", "invalid"} or str(row.get("qc_status") or "").casefold() in {"rejected", "reject", "invalid"} or bool(flags & QUALITY_REJECT_CODES):
                mechanism, detail = "quality_rejected", f"hard QC evidence: {','.join(sorted(flags & QUALITY_REJECT_CODES)) or 'rejected status'}"
            else:
                explicit_interval = _lookup_expected_interval(expected_intervals, row)
                median_interval = median(intervals.get(_series_key(row), [])) if intervals.get(_series_key(row)) else None
                declared_frequency = str(row.get("frequency") or row.get("native_frequency") or row.get("sampling_frequency") or "").casefold()
                low_frequency_declared = any(token in declared_frequency for token in ("daily", "weekly", "monthly", "quarterly", "annual", "low"))
                if explicit_interval is not None and explicit_interval > step_minutes * low_frequency_factor:
                    mechanism, detail = "low_frequency", f"declared interval={explicit_interval:g} minutes"
                elif low_frequency_declared:
                    mechanism, detail = "low_frequency", f"declared native frequency={declared_frequency}"
                # Do not mislabel an hourly series with one long outage as a
                # low-frequency source.  Without an explicit cadence, require
                # a genuinely coarse native interval (>24 h) before assigning
                # the low-frequency mechanism; shorter deviations are handled
                # as temporal gaps below.
                elif explicit_interval is None and median_interval is not None and median_interval > max(step_minutes * low_frequency_factor, 24.0 * 60.0):
                    mechanism, detail = "low_frequency", f"observed median interval={median_interval:g} minutes"
                else:
                    mechanism, detail = _gap_context_indexed(row, valid_time_index.get(_series_key(row), []), max_gap_steps=max_gap_steps, step_minutes=step_minutes)
                    confidence = "medium" if mechanism != "edge_gap" else "low"
        elif row.get("is_imputed") and _canonical_mechanism(row.get("missing_mechanism")):
            # Preserve the root cause after a short-gap value is materialized;
            # changing it to ``not_missing`` would erase the lineage needed by
            # later quality and feature stages.
            mechanism = _canonical_mechanism(row.get("missing_mechanism")) or "not_missing"
            detail = "value was produced from a previously classified gap"
            confidence = str(row.get("missing_mechanism_confidence") or "medium")
        row["missing_mechanism"] = mechanism
        row["missing_mechanism_detail"] = detail
        row["missing_mechanism_confidence"] = confidence
        row["missing_imputation_policy"] = MECHANISM_POLICIES[mechanism]
        row["gap_class"] = mechanism if mechanism.startswith("temporal_gap") or mechanism == "edge_gap" else None
        counts[mechanism] += 1
        by_source_variable[(source_id, variable, mechanism)] += 1

    event_audit: list[dict[str, Any]] = []
    source_ids = {str(row.get("source_id") or "__missing__") for row in records}
    if isinstance(source_events, dict):
        source_ids.update(str(source_id) for source_id in source_events)
    elif isinstance(source_events, Iterable) and not isinstance(source_events, (str, bytes)):
        source_ids.update(str(event.get("source_id") or "__missing__") for event in source_events if isinstance(event, dict))
    for source_id in sorted(source_ids):
        for event in _source_events_for(source_events, source_id):
            if _event_is_interface_failure(event):
                audit = dict(event)
                audit["missing_mechanism"] = "interface_failure"
                audit["missing_mechanism_detail"] = "failed source event without a trustworthy observation"
                audit["missing_imputation_policy"] = MECHANISM_POLICIES["interface_failure"]
                event_audit.append(audit)
                counts["interface_failure"] += 1

    return {
        "records": records,
        "source_event_audit": event_audit,
        "missing_mechanism_counts": dict(sorted(counts.items())),
        "by_source_variable": {f"{source}|{variable}|{mechanism}": count for (source, variable, mechanism), count in sorted(by_source_variable.items())},
        "policies": dict(MECHANISM_POLICIES),
        "categories": list(MISSING_MECHANISM_CATEGORIES),
    }


def _row_reference(row: dict[str, Any]) -> str:
    """Return a stable human/audit reference without inventing an ID."""
    for key in ("record_id", "source_record_id"):
        if row.get(key) not in (None, ""):
            return str(row[key])
    source_file = str(row.get("source_file") or "")
    source_row = str(row.get("source_row") or "")
    if source_file or source_row:
        return f"{source_file}:{source_row}"
    return "|".join(str(row.get(key) or "") for key in ("source_id", "station_id", "scene_id", "variable_code", "observed_at"))


def _bracket_rows(row: dict[str, Any], ordered: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, datetime | None, datetime | None]:
    timestamp = _parse_time(row.get("observed_at"))
    if timestamp is None:
        return None, None, None, None
    index = next((position for position, item in enumerate(ordered) if item is row), None)
    if index is None:
        return None, None, None, None
    previous = next((ordered[position] for position in range(index - 1, -1, -1) if _number(ordered[position].get("clean_value")) is not None and not bool(ordered[position].get("is_imputed"))), None)
    following = next((ordered[position] for position in range(index + 1, len(ordered)) if _number(ordered[position].get("clean_value")) is not None and not bool(ordered[position].get("is_imputed"))), None)
    previous_time = _parse_time(previous.get("observed_at")) if previous else None
    following_time = _parse_time(following.get("observed_at")) if following else None
    return previous, following, previous_time, following_time


def _set_imputation_audit_fields(
    row: dict[str, Any],
    *,
    status: str,
    reason: str | None = None,
    method: str | None = None,
    previous: dict[str, Any] | None = None,
    following: dict[str, Any] | None = None,
    previous_time: datetime | None = None,
    following_time: datetime | None = None,
    missing_steps: int | None = None,
    interval_minutes: float | None = None,
) -> dict[str, Any]:
    row["imputation_status"] = status
    row["imputation_block_reason"] = reason
    row["imputation_method"] = method
    row["imputation_donor_left"] = _row_reference(previous) if previous else None
    row["imputation_donor_right"] = _row_reference(following) if following else None
    row["imputation_source_left"] = row["imputation_donor_left"]
    row["imputation_source_right"] = row["imputation_donor_right"]
    row["imputation_left_observed_at"] = previous_time.isoformat() if previous_time else None
    row["imputation_right_observed_at"] = following_time.isoformat() if following_time else None
    row["imputation_left_value"] = _number(previous.get("clean_value")) if previous else None
    row["imputation_right_value"] = _number(following.get("clean_value")) if following else None
    current_time = _parse_time(row.get("observed_at"))
    row["imputation_gap_start_at"] = current_time.isoformat() if current_time else None
    row["imputation_gap_end_at"] = current_time.isoformat() if current_time else None
    row["imputation_gap_start"] = row["imputation_gap_start_at"]
    row["imputation_gap_end"] = row["imputation_gap_end_at"]
    row["imputation_gap_steps"] = missing_steps
    row["imputation_interval_minutes"] = round(interval_minutes, 6) if interval_minutes is not None else None
    row["imputation_donor_count"] = int(bool(previous)) + int(bool(following))
    return {
        "record_id": _row_reference(row),
        "source_id": row.get("source_id"),
        "station_id": row.get("station_id"),
        "variable_code": row.get("variable_code"),
        "observed_at": row.get("observed_at"),
        "missing_mechanism": row.get("missing_mechanism"),
        "status": status,
        "reason": reason,
        "method": method,
        "donor_left": row["imputation_donor_left"],
        "donor_right": row["imputation_donor_right"],
        "left_observed_at": row["imputation_left_observed_at"],
        "right_observed_at": row["imputation_right_observed_at"],
        "gap_start_at": row["imputation_gap_start_at"],
        "gap_end_at": row["imputation_gap_end_at"],
        "gap_steps": missing_steps,
        "interval_minutes": row["imputation_interval_minutes"],
        "donor_count": row["imputation_donor_count"],
    }


def _set_observation_flags(row: dict[str, Any]) -> None:
    """Materialize the standard observed/imputation flags without filling values."""
    if _number(row.get("clean_value")) is not None:
        if bool(row.get("is_imputed")) or str(row.get("value_origin") or "").casefold() == "imputed":
            row["observed_flag"] = 0
            row["imputation_flag"] = 1
        else:
            row["observed_flag"] = int(row.get("observed_flag", 1) or 0)
            row["imputation_flag"] = int(row.get("imputation_flag", 0) or 0)
    else:
        row["observed_flag"] = 0
        row["imputation_flag"] = int(row.get("imputation_flag", 0) or 0)


def handle_long_gap_uncertainty(
    records: list[dict[str, Any]],
    *,
    max_gap_steps: int = 3,
    step_minutes: int = 60,
    source_events: Any = None,
    source_health: Any = None,
    expected_intervals: Any = None,
) -> dict[str, Any]:
    """Keep long gaps missing and attach an auditable uncertainty envelope.

    A long gap is never forward-filled and never written into ``clean_value``.
    When original observations bracket the gap, the output contains a widened
    donor envelope and a midpoint estimate solely as uncertainty metadata. If
    no donors exist, bounds remain null and the row is explicitly unbounded.
    In both cases ``observed_flag=0`` and ``imputation_flag=1`` identify an
    uncertain imputation candidate rather than an observed truth.
    """
    classification = classify_missing_mechanisms(records, source_events=source_events, source_health=source_health, expected_intervals=expected_intervals, max_gap_steps=max_gap_steps, step_minutes=step_minutes)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in classification["records"]:
        groups[_series_key(row)].append(row)
    audit: list[dict[str, Any]] = []
    long_gap_rows = 0
    bounded_rows = 0
    for group in groups.values():
        ordered = sorted(group, key=lambda row: _parse_time(row.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        donor_pairs = sorted(
            (timestamp, item)
            for item in ordered
            if _number(item.get("clean_value")) is not None
            and not bool(item.get("is_imputed"))
            and (timestamp := _parse_time(item.get("observed_at"))) is not None
        )
        donor_times = [item[0] for item in donor_pairs]
        for row in ordered:
            _set_observation_flags(row)
            if row.get("missing_mechanism") != "temporal_gap_long":
                continue
            long_gap_rows += 1
            timestamp = _parse_time(row.get("observed_at"))
            if timestamp is None:
                previous = following = previous_time = following_time = None
            else:
                left_position = bisect_left(donor_times, timestamp) - 1
                right_position = bisect_right(donor_times, timestamp)
                previous_time, previous = donor_pairs[left_position] if left_position >= 0 else (None, None)
                following_time, following = donor_pairs[right_position] if right_position < len(donor_pairs) else (None, None)
            left = _number(previous.get("clean_value")) if previous else None
            right = _number(following.get("clean_value")) if following else None
            gap_steps = None
            interval_minutes = None
            if previous_time and following_time:
                gap_seconds = (following_time - previous_time).total_seconds()
                gap_steps = round(gap_seconds / (step_minutes * 60.0)) - 1
                interval_minutes = gap_seconds / max(gap_steps + 1, 1) / 60.0
            row["observed_flag"] = 0
            row["imputation_flag"] = 1
            row["imputation_status"] = "uncertain"
            row["imputation_method"] = "uncertainty_donor_envelope"
            if not row.get("imputation_block_reason"):
                row["imputation_block_reason"] = "long_gap_no_silent_forward_fill"
            row["uncertainty_model"] = "donor_envelope"
            row["uncertainty_method"] = "local_donor_envelope"
            row["uncertainty_center"] = None
            row["uncertainty_lower"] = None
            row["uncertainty_upper"] = None
            row["uncertainty_width"] = None
            row["uncertainty_status"] = "unbounded_no_donors"
            row["imputation_gap_steps"] = gap_steps
            row["imputation_interval_minutes"] = round(interval_minutes, 6) if interval_minutes is not None else None
            row["imputation_donor_left"] = _row_reference(previous) if previous else None
            row["imputation_donor_right"] = _row_reference(following) if following else None
            row["imputation_left_observed_at"] = previous_time.isoformat() if previous_time else None
            row["imputation_right_observed_at"] = following_time.isoformat() if following_time else None
            row["imputation_left_value"] = left
            row["imputation_right_value"] = right
            if left is not None and right is not None:
                center = (left + right) / 2.0
                margin = max(abs(right - left) * 0.5, 1e-9)
                lower = min(left, right) - margin
                upper = max(left, right) + margin
                row["uncertainty_center"] = center
                row["uncertainty_lower"] = lower
                row["uncertainty_upper"] = upper
                row["uncertainty_width"] = upper - lower
                row["uncertainty_status"] = "bounded_donor_envelope"
                bounded_rows += 1
            audit.append({
                "record_id": _row_reference(row),
                "source_id": row.get("source_id"),
                "station_id": row.get("station_id"),
                "variable_code": row.get("variable_code"),
                "observed_at": row.get("observed_at"),
                "missing_mechanism": row.get("missing_mechanism"),
                "status": "uncertain",
                "observed_flag": row["observed_flag"],
                "imputation_flag": row["imputation_flag"],
                "method": row["uncertainty_method"],
                "uncertainty_status": row["uncertainty_status"],
                "uncertainty_center": row["uncertainty_center"],
                "uncertainty_lower": row["uncertainty_lower"],
                "uncertainty_upper": row["uncertainty_upper"],
                "uncertainty_width": row["uncertainty_width"],
                "donor_left": row["imputation_donor_left"],
                "donor_right": row["imputation_donor_right"],
                "gap_steps": gap_steps,
                "interval_minutes": row["imputation_interval_minutes"],
                "clean_value_preserved_null": row.get("clean_value") is None,
            })
    return {
        "records": records,
        "long_gap_rows": long_gap_rows,
        "bounded_rows": bounded_rows,
        "unbounded_rows": long_gap_rows - bounded_rows,
        "audit": audit,
        "missing_mechanism_counts": classification["missing_mechanism_counts"],
        "source_event_audit": classification["source_event_audit"],
    }


def _frequency_label(minutes: float | None, explicit: str | None = None) -> tuple[str, str]:
    token = str(explicit or "").casefold().replace("-", "_").replace(" ", "_")
    if token:
        if "quarter" in token:
            return "quarterly", "declared"
        if "month" in token:
            return "monthly", "declared"
        if "week" in token:
            return "weekly", "declared"
        if "day" in token:
            return "daily", "declared"
        if "hour" in token or "minute" in token:
            return "hourly", "declared"
    if minutes is None:
        return "unknown", "unknown"
    if minutes <= 90.0:
        return "hourly", "inferred"
    if minutes <= 36.0 * 60.0:
        return "daily", "inferred"
    if minutes <= 8.0 * 1440.0:
        return "weekly", "inferred"
    if minutes <= 45.0 * 1440.0:
        return "monthly", "inferred"
    if minutes <= 120.0 * 1440.0:
        return "quarterly", "inferred"
    return "annual_or_irregular", "inferred"


def _frequency_text(row: dict[str, Any]) -> str:
    for key in ("native_frequency", "frequency", "source_granularity", "sampling_frequency"):
        value = row.get(key)
        if value not in (None, "", "unknown", "None"):
            return str(value)
    return ""


def _age_status(age_hours: float | None, *, max_age_hours: float) -> str:
    if age_hours is None:
        return "unknown"
    if age_hours < 0:
        return "future_relative_to_as_of"
    return "fresh" if age_hours <= max_age_hours else "stale"


def handle_low_frequency_nutrients(
    records: list[dict[str, Any]],
    *,
    as_of: datetime | str | None = None,
    max_age_hours: float = DEFAULT_LOW_FREQUENCY_MAX_AGE_HOURS,
    nutrient_variables: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Preserve native nutrient cadence and expose age-aware feature references.

    The function never creates daily copies and never overwrites ``clean_value``.
    For each nutrient series it records the inferred/native cadence, the age of
    the observation at ``as_of``, and a latest-observed reference constrained to
    values available at the row's own timestamp (preventing future leakage).
    """
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    reference_time = _parse_time(as_of) if as_of is not None else datetime.now(UTC)
    if reference_time is None:
        raise ValueError("as_of must be timezone-aware ISO text or datetime")
    nutrients = {str(item) for item in (nutrient_variables or LOW_FREQUENCY_NUTRIENT_VARIABLES)}
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if str(row.get("variable_code") or "") in nutrients:
            groups[_series_key(row)].append(row)

    latest_value_table: list[dict[str, Any]] = []
    frequency_counts: Counter[str] = Counter()
    low_frequency_series = 0
    for key, group in groups.items():
        ordered = sorted(group, key=lambda item: _parse_time(item.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        valid = [item for item in ordered if _number(item.get("clean_value")) is not None and _parse_time(item.get("observed_at")) is not None]
        valid_times = [_parse_time(item.get("observed_at")) for item in valid]
        intervals = [(right - left).total_seconds() / 60.0 for left, right in zip(valid_times, valid_times[1:]) if left and right and right > left]
        median_interval = median(intervals) if intervals else None
        explicit = next((_frequency_text(item) for item in ordered if _frequency_text(item)), None)
        frequency, frequency_source = _frequency_label(median_interval, explicit)
        is_low = frequency in {"weekly", "monthly", "quarterly", "annual_or_irregular"} or (median_interval is not None and median_interval > 6.0 * 60.0)
        if is_low:
            low_frequency_series += 1
        frequency_counts[frequency] += len(ordered)
        available_at_as_of = [item for item in valid if (_parse_time(item.get("observed_at")) or reference_time) <= reference_time]
        latest_at_as_of = max(available_at_as_of, key=lambda item: _parse_time(item.get("observed_at")) or datetime.min.replace(tzinfo=UTC), default=None)
        latest_time = _parse_time(latest_at_as_of.get("observed_at")) if latest_at_as_of else None
        latest_value = _number(latest_at_as_of.get("clean_value")) if latest_at_as_of else None
        latest_age = (reference_time - latest_time).total_seconds() / 3600.0 if latest_time else None
        latest_value_table.append({
            "source_id": key[0], "station_id": key[1], "scene_id": key[2], "variable_code": key[3],
            "native_frequency": frequency, "native_frequency_minutes": median_interval,
            "latest_observed_at": latest_time.isoformat() if latest_time else None,
            "latest_observed_value": latest_value, "latest_value_age_hours": round(latest_age, 6) if latest_age is not None else None,
            "data_age_status": _age_status(latest_age, max_age_hours=max_age_hours),
        })
        for row in ordered:
            observed_time = _parse_time(row.get("observed_at"))
            data_age = (reference_time - observed_time).total_seconds() / 3600.0 if observed_time else None
            feature_time = observed_time or reference_time
            feature_candidates = [item for item in valid if (_parse_time(item.get("observed_at")) or feature_time) <= feature_time]
            feature_latest = max(feature_candidates, key=lambda item: _parse_time(item.get("observed_at")) or datetime.min.replace(tzinfo=UTC), default=None)
            feature_observed_at = _parse_time(feature_latest.get("observed_at")) if feature_latest else None
            feature_value = _number(feature_latest.get("clean_value")) if feature_latest else None
            feature_age = (feature_time - feature_observed_at).total_seconds() / 3600.0 if feature_observed_at else None
            row["native_frequency"] = frequency
            row["native_frequency_minutes"] = round(median_interval, 6) if median_interval is not None else None
            row["native_frequency_source"] = frequency_source
            row["preserved_native_frequency"] = True
            row["low_frequency_status"] = "native_low_frequency" if is_low else "native_frequency"
            row["data_age_hours"] = round(data_age, 6) if data_age is not None else None
            row["data_age_status"] = _age_status(data_age, max_age_hours=max_age_hours)
            row["latest_observed_at"] = latest_time.isoformat() if latest_time else None
            row["latest_observed_value"] = latest_value
            row["latest_value_age_hours"] = round(latest_age, 6) if latest_age is not None else None
            row["feature_value"] = feature_value
            row["feature_value_observed_at"] = feature_observed_at.isoformat() if feature_observed_at else None
            row["feature_value_age_hours"] = round(feature_age, 6) if feature_age is not None else None
            row["feature_value_semantics"] = "latest_observed_with_age" if feature_value is not None else "missing_no_prior_observation"
    return {
        "records": records,
        "row_count_before": len(records),
        "row_count_after": len(records),
        "nutrient_row_count": sum(len(group) for group in groups.values()),
        "untouched_row_count": len(records) - sum(len(group) for group in groups.values()),
        "low_frequency_series": low_frequency_series,
        "frequency_counts": dict(sorted(frequency_counts.items())),
        "latest_value_table": latest_value_table,
        "as_of": reference_time.isoformat(),
        "max_age_hours": max_age_hours,
        "native_frequency_preserved": True,
    }


def _wind_group_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Return the co-location key shared by speed and direction series."""
    return (
        row.get("source_id"),
        row.get("station_id"),
        row.get("scene_id"),
        row.get("entity_id"),
    )


def _wind_components(speed_mps: float, direction_degrees: float) -> tuple[float, float]:
    """Convert meteorological *from* direction to eastward/northward u/v."""
    direction = math.radians(direction_degrees % 360.0)
    return (
        -speed_mps * math.sin(direction),
        -speed_mps * math.cos(direction),
    )


def _wind_from_components(u: float, v: float) -> tuple[float, float]:
    """Recover speed and canonical meteorological *from* direction."""
    speed = math.hypot(u, v)
    if speed == 0.0:
        return 0.0, 0.0
    direction = math.degrees(math.atan2(-u, -v)) % 360.0
    # Avoid emitting a visually surprising 360° value for a northward vector.
    if math.isclose(direction, 360.0, abs_tol=1e-9):
        direction = 0.0
    return speed, direction


def _wind_row_value(row: dict[str, Any] | None) -> float | None:
    return _number(row.get("clean_value")) if row is not None else None


def _wind_is_original(row: dict[str, Any] | None) -> bool:
    return bool(row) and not bool(row.get("is_imputed")) and str(row.get("value_origin") or "").casefold() != "imputed"


def _wind_audit_row(
    row: dict[str, Any],
    *,
    status: str,
    reason: str | None,
    method: str | None,
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    gap_steps: int | None,
    interval_minutes: float | None,
    speed_from_vector: float | None,
    calm_speed_threshold_mps: float,
) -> dict[str, Any]:
    return {
        "record_id": _row_reference(row),
        "source_id": row.get("source_id"),
        "station_id": row.get("station_id"),
        "scene_id": row.get("scene_id"),
        "observed_at": row.get("observed_at"),
        "variable_code": row.get("variable_code"),
        "wind_uv_status": status,
        "wind_uv_block_reason": reason,
        "wind_uv_method": method,
        "wind_uv_donor_left": _row_reference(left) if left else None,
        "wind_uv_donor_right": _row_reference(right) if right else None,
        "wind_uv_gap_steps": gap_steps,
        "wind_uv_interval_minutes": round(interval_minutes, 6) if interval_minutes is not None else None,
        "wind_uv_speed_from_vector": speed_from_vector,
        "wind_uv_direction_convention": WIND_DIRECTION_CONVENTION,
        "wind_uv_calm_threshold_mps": calm_speed_threshold_mps,
        "observed_flag": row.get("observed_flag"),
        "imputation_flag": row.get("imputation_flag"),
        "clean_value": row.get("clean_value"),
    }


def impute_wind_direction_uv(
    records: list[dict[str, Any]],
    *,
    max_gap_steps: int = 3,
    step_minutes: int = 60,
    direction_variable: str = WIND_DIRECTION_VARIABLE,
    speed_variable: str = WIND_SPEED_VARIABLE,
    calm_speed_threshold_mps: float = DEFAULT_CALM_WIND_SPEED_MPS,
) -> dict[str, Any]:
    """Interpolate wind vectors, then restore speed and direction.

    Direction is never interpolated in degree space.  Original paired speed
    and direction observations are converted to u/v, linearly interpolated
    across a regular short gap, and converted back using the meteorological
    *from* convention.  A calm vector has no physically meaningful direction;
    such a target is kept null and explicitly labelled ``calm_undefined``.
    Donors are always original observations, so a chain of imputed vectors
    cannot silently propagate through a gap.
    """
    if max_gap_steps < 1 or step_minutes < 1 or calm_speed_threshold_mps < 0:
        raise ValueError("max_gap_steps, step_minutes and calm_speed_threshold_mps must be valid")

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        if str(row.get("variable_code") or "") in {direction_variable, speed_variable}:
            groups[_wind_group_key(row)].append(row)

    audit: list[dict[str, Any]] = []
    imputed_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []
    observed_pair_count = 0
    calm_rows = 0
    boundary_checks = 0

    for group in groups.values():
        by_time: dict[datetime, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in group:
            timestamp = _parse_time(row.get("observed_at"))
            variable = str(row.get("variable_code") or "")
            if timestamp is not None and variable in {direction_variable, speed_variable}:
                # Preserve the first row at a duplicate key; duplicate
                # resolution has already happened in the normal pipeline.
                by_time[timestamp].setdefault(variable, row)
        ordered_times = sorted(by_time)
        original_pairs: list[tuple[datetime, dict[str, Any], dict[str, Any], float, float, float, float]] = []
        for timestamp in ordered_times:
            pair = by_time[timestamp]
            speed_row = pair.get(speed_variable)
            direction_row = pair.get(direction_variable)
            speed = _wind_row_value(speed_row)
            direction = _wind_row_value(direction_row)
            if speed is None or direction is None or speed < 0 or not _wind_is_original(speed_row) or not _wind_is_original(direction_row):
                continue
            u, v = _wind_components(speed, direction)
            original_pairs.append((timestamp, speed_row, direction_row, speed, direction % 360.0, u, v))

        handled_missing_times: set[datetime] = set()
        for timestamp in ordered_times:
            pair = by_time[timestamp]
            speed_row = pair.get(speed_variable)
            direction_row = pair.get(direction_variable)
            if speed_row is None and direction_row is None:
                continue
            speed = _wind_row_value(speed_row)
            direction = _wind_row_value(direction_row)
            if timestamp in handled_missing_times:
                continue
            # First annotate every valid original pair.  This gives downstream
            # feature tables explicit vector columns even when no gap exists.
            if speed is not None and direction is not None and speed >= 0:
                u, v = _wind_components(speed, direction)
                for row in (speed_row, direction_row):
                    row[WIND_U_COMPONENT] = u
                    row[WIND_V_COMPONENT] = v
                    row["wind_uv_status"] = "calm_observed" if speed <= calm_speed_threshold_mps else "observed"
                    row["wind_uv_method"] = "direct_vector_conversion"
                    row["wind_uv_direction_convention"] = WIND_DIRECTION_CONVENTION
                    row["wind_uv_calm_threshold_mps"] = calm_speed_threshold_mps
                    _set_observation_flags(row)
                observed_pair_count += 1
                if speed <= calm_speed_threshold_mps:
                    calm_rows += 1
                if direction <= 1.0 or direction >= 359.0:
                    boundary_checks += 1
                continue

            target_row = direction_row if direction_row is not None and _is_missing(direction_row) else speed_row
            if target_row is None or not _is_missing(target_row):
                continue
            # An explicit source/QC mechanism wins over vector interpolation.
            mechanism = str(target_row.get("missing_mechanism") or "")
            if mechanism and mechanism not in {"temporal_gap_short", "unknown", "edge_gap"}:
                target_row["wind_uv_status"] = "pending"
                target_row["wind_uv_block_reason"] = f"mechanism_{mechanism}_not_eligible"
                _set_observation_flags(target_row)
                pending_rows.append(target_row)
                audit.append(_wind_audit_row(target_row, status="pending", reason=target_row["wind_uv_block_reason"], method=None, left=None, right=None, gap_steps=None, interval_minutes=None, speed_from_vector=None, calm_speed_threshold_mps=calm_speed_threshold_mps))
                handled_missing_times.add(timestamp)
                continue
            left_candidates = [item for item in original_pairs if item[0] < timestamp]
            right_candidates = [item for item in original_pairs if item[0] > timestamp]
            left = left_candidates[-1] if left_candidates else None
            right = right_candidates[0] if right_candidates else None
            left_time = left[0] if left else None
            right_time = right[0] if right else None
            gap_steps = None
            interval_minutes = None
            if left_time and right_time:
                span_minutes = (right_time - left_time).total_seconds() / 60.0
                gap_steps = round(span_minutes / step_minutes) - 1
                interval_minutes = span_minutes / max(gap_steps + 1, 1)
            reason = None
            if not left or not right:
                reason = "missing_paired_wind_donor"
            elif gap_steps is None or gap_steps < 1 or gap_steps > max_gap_steps or abs((right_time - left_time).total_seconds() - (gap_steps + 1) * step_minutes * 60.0) > 1:
                reason = "gap_not_regular_or_short"
            if reason is not None:
                target_row["wind_uv_status"] = "pending"
                target_row["wind_uv_block_reason"] = reason
                target_row["wind_uv_direction_convention"] = WIND_DIRECTION_CONVENTION
                target_row["wind_uv_calm_threshold_mps"] = calm_speed_threshold_mps
                _set_observation_flags(target_row)
                pending_rows.append(target_row)
                audit.append(_wind_audit_row(target_row, status="pending", reason=reason, method=None, left=left[1] if left else None, right=right[1] if right else None, gap_steps=gap_steps, interval_minutes=interval_minutes, speed_from_vector=None, calm_speed_threshold_mps=calm_speed_threshold_mps))
                handled_missing_times.add(timestamp)
                continue

            position = (timestamp - left_time).total_seconds() / (right_time - left_time).total_seconds()
            u = left[5] + position * (right[5] - left[5])
            v = left[6] + position * (right[6] - left[6])
            vector_speed, recovered_direction = _wind_from_components(u, v)
            target_row[WIND_U_COMPONENT] = u
            target_row[WIND_V_COMPONENT] = v
            target_row["wind_uv_speed_from_vector"] = vector_speed
            target_row["wind_uv_direction_convention"] = WIND_DIRECTION_CONVENTION
            target_row["wind_uv_calm_threshold_mps"] = calm_speed_threshold_mps
            if vector_speed <= calm_speed_threshold_mps:
                calm_rows += 1
                target_row["wind_uv_status"] = "calm_undefined"
                target_row["wind_uv_method"] = "uv_linear_interpolation"
                target_row["wind_uv_block_reason"] = "direction_undefined_for_calm_wind"
                # A speed estimate of zero is safe; a direction would be an
                # invented bearing, so retain a missing clean value.
                if speed_row is not None and _is_missing(speed_row):
                    speed_row["clean_value"] = 0.0
                    speed_row["is_imputed"] = True
                    speed_row["value_origin"] = "imputed"
                    speed_row["wind_uv_status"] = "calm_undefined"
                    speed_row[WIND_U_COMPONENT] = 0.0
                    speed_row[WIND_V_COMPONENT] = 0.0
                    _set_observation_flags(speed_row)
                    imputed_rows.append(speed_row)
                elif speed_row is not None:
                    speed_row[WIND_U_COMPONENT] = 0.0
                    speed_row[WIND_V_COMPONENT] = 0.0
                    speed_row["wind_uv_speed_from_vector"] = 0.0
                    speed_row["wind_uv_status"] = "paired_with_calm_direction"
                    speed_row["wind_uv_method"] = "uv_linear_interpolation"
                    speed_row["wind_uv_direction_convention"] = WIND_DIRECTION_CONVENTION
                    speed_row["wind_uv_calm_threshold_mps"] = calm_speed_threshold_mps
                    _set_observation_flags(speed_row)
                if direction_row is not None and _is_missing(direction_row):
                    direction_row["wind_uv_status"] = "calm_undefined"
                    direction_row["wind_uv_method"] = "uv_linear_interpolation"
                    direction_row["wind_uv_block_reason"] = "direction_undefined_for_calm_wind"
                    direction_row[WIND_U_COMPONENT] = 0.0
                    direction_row[WIND_V_COMPONENT] = 0.0
                    _set_observation_flags(direction_row)
                    direction_row["imputation_flag"] = 1
                    pending_rows.append(direction_row)
                    audit.append(_wind_audit_row(direction_row, status="calm_undefined", reason="direction_undefined_for_calm_wind", method="uv_linear_interpolation", left=left[2], right=right[2], gap_steps=gap_steps, interval_minutes=interval_minutes, speed_from_vector=vector_speed, calm_speed_threshold_mps=calm_speed_threshold_mps))
                handled_missing_times.add(timestamp)
                continue

            # Only fill a missing component.  Never overwrite an observed
            # speed/direction at the target timestamp.
            changed_rows: list[dict[str, Any]] = []
            if speed_row is not None and _is_missing(speed_row):
                speed_row["clean_value"] = vector_speed
                speed_row["is_imputed"] = True
                speed_row["value_origin"] = "imputed"
                speed_row["wind_uv_status"] = "imputed"
                speed_row["wind_uv_method"] = "uv_linear_interpolation"
                speed_row[WIND_U_COMPONENT] = u
                speed_row[WIND_V_COMPONENT] = v
                _set_observation_flags(speed_row)
                imputed_rows.append(speed_row)
                changed_rows.append(speed_row)
            if direction_row is not None and _is_missing(direction_row):
                direction_row["clean_value"] = recovered_direction
                direction_row["is_imputed"] = True
                direction_row["value_origin"] = "imputed"
                direction_row["wind_uv_status"] = "imputed"
                direction_row["wind_uv_method"] = "uv_linear_interpolation"
                direction_row[WIND_U_COMPONENT] = u
                direction_row[WIND_V_COMPONENT] = v
                _set_observation_flags(direction_row)
                imputed_rows.append(direction_row)
                changed_rows.append(direction_row)
            # Keep the vector representation synchronized on the paired
            # speed row even when its scalar value was observed and therefore
            # must not be overwritten.
            for paired_row in (speed_row, direction_row):
                if paired_row is not None:
                    paired_row[WIND_U_COMPONENT] = u
                    paired_row[WIND_V_COMPONENT] = v
                    paired_row["wind_uv_speed_from_vector"] = vector_speed
                    paired_row["wind_uv_direction_convention"] = WIND_DIRECTION_CONVENTION
                    paired_row["wind_uv_calm_threshold_mps"] = calm_speed_threshold_mps
                    if paired_row not in changed_rows:
                        paired_row["wind_uv_status"] = "paired_with_imputed_component"
                        paired_row["wind_uv_method"] = "uv_linear_interpolation"
                        _set_observation_flags(paired_row)
            for changed in changed_rows:
                changed["wind_uv_gap_steps"] = gap_steps
                changed["wind_uv_interval_minutes"] = interval_minutes
                changed["wind_uv_donor_left"] = _row_reference(left[1])
                changed["wind_uv_donor_right"] = _row_reference(right[1])
                audit.append(_wind_audit_row(changed, status="imputed", reason=None, method="uv_linear_interpolation", left=left[2], right=right[2], gap_steps=gap_steps, interval_minutes=interval_minutes, speed_from_vector=vector_speed, calm_speed_threshold_mps=calm_speed_threshold_mps))
            handled_missing_times.add(timestamp)

    return {
        "records": records,
        "imputed": imputed_rows,
        "pending": pending_rows,
        "audit": audit,
        "imputed_rows": len(imputed_rows),
        "pending_rows": len(pending_rows),
        "observed_pair_count": observed_pair_count,
        "calm_rows": calm_rows,
        "boundary_checks": boundary_checks,
        "direction_convention": WIND_DIRECTION_CONVENTION,
        "calm_speed_threshold_mps": calm_speed_threshold_mps,
        "row_count_before": len(records),
        "row_count_after": len(records),
    }


def impute_short_gaps(
    records: list[dict[str, Any]],
    *,
    max_gap_steps: int = 3,
    step_minutes: int = 60,
    source_events: Any = None,
    source_health: Any = None,
    expected_intervals: Any = None,
    method: str = "linear_time",
    high_frequency_max_interval_minutes: float = HIGH_FREQUENCY_MAX_INTERVAL_MINUTES,
    never_auto_impute: Iterable[str] | None = None,
    as_of: datetime | str | None = None,
    low_frequency_max_age_hours: float = DEFAULT_LOW_FREQUENCY_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """Interpolate only high-frequency, short, bracketed gaps.

    Every candidate receives a row-level audit record.  A candidate is
    accepted only when both donors exist, the inferred cadence is no slower
    than the high-frequency limit, the gap is within ``max_gap_steps`` and the
    variable is not protected by the no-auto-impute policy.
    """
    if max_gap_steps < 1 or step_minutes < 1:
        raise ValueError("max_gap_steps and step_minutes must be positive")
    if method not in ALLOWED_SHORT_GAP_METHODS:
        raise ValueError(f"unsupported short-gap method: {method}")
    if high_frequency_max_interval_minutes <= 0:
        raise ValueError("high_frequency_max_interval_minutes must be positive")
    protected_variables = {str(item) for item in (never_auto_impute or DEFAULT_NEVER_AUTO_IMPUTE)}
    classification = classify_missing_mechanisms(records, source_events=source_events, source_health=source_health, expected_intervals=expected_intervals, max_gap_steps=max_gap_steps, step_minutes=step_minutes)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in classification["records"]:
        groups[_series_key(row)].append(row)

    imputed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    imputation_audit: list[dict[str, Any]] = []
    step_seconds = step_minutes * 60
    for group in groups.values():
        ordered = sorted(group, key=lambda row: _parse_time(row.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        donor_pairs = sorted(
            (timestamp, item)
            for item in ordered
            if _number(item.get("clean_value")) is not None
            and not bool(item.get("is_imputed"))
            and (timestamp := _parse_time(item.get("observed_at"))) is not None
        )
        donor_times = [item[0] for item in donor_pairs]
        valid_times = sorted(set(donor_times))
        observed_intervals = [(right - left).total_seconds() / 60.0 for left, right in zip(valid_times, valid_times[1:]) if right > left]
        inferred_interval = median(observed_intervals) if observed_intervals else None
        for index, row in enumerate(ordered):
            if _number(row.get("clean_value")) is not None:
                continue
            # Wind is a paired circular/vector quantity.  Exclude both
            # components from scalar degree interpolation; the dedicated
            # u/v pass below is the only writer for wind gaps.
            if row.get("variable_code") in {WIND_DIRECTION_VARIABLE, WIND_SPEED_VARIABLE}:
                continue
            timestamp = _parse_time(row.get("observed_at"))
            timestamp = _parse_time(row.get("observed_at"))
            if timestamp is None:
                previous = following = previous_time = following_time = None
            else:
                left_position = bisect_left(donor_times, timestamp) - 1
                right_position = bisect_right(donor_times, timestamp)
                previous_time, previous = donor_pairs[left_position] if left_position >= 0 else (None, None)
                following_time, following = donor_pairs[right_position] if right_position < len(donor_pairs) else (None, None)
            explicit_interval = _lookup_expected_interval(expected_intervals, row)
            cadence_minutes = explicit_interval if explicit_interval is not None else inferred_interval
            if row.get("variable_code") in protected_variables:
                audit = _set_imputation_audit_fields(row, status="pending", reason="variable_policy_forbids_auto_imputation", method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            if row.get("missing_mechanism") != "temporal_gap_short":
                gap_steps = None
                gap_interval = None
                reason = f"mechanism_{row.get('missing_mechanism') or 'unknown'}_not_eligible"
                if row.get("missing_mechanism") == "temporal_gap_long" and previous_time and following_time:
                    gap_seconds = (following_time - previous_time).total_seconds()
                    gap_steps = round(gap_seconds / step_seconds) - 1
                    gap_interval = gap_seconds / max(gap_steps + 1, 1) / 60.0
                    reason = "gap_not_regular_or_short"
                audit = _set_imputation_audit_fields(row, status="pending", reason=reason, method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time, missing_steps=gap_steps, interval_minutes=gap_interval)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            if cadence_minutes is not None and cadence_minutes > high_frequency_max_interval_minutes:
                audit = _set_imputation_audit_fields(row, status="pending", reason="source_cadence_not_high_frequency", method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time, interval_minutes=cadence_minutes)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            if not timestamp or not previous or not following or not previous_time or not following_time:
                audit = _set_imputation_audit_fields(row, status="pending", reason="missing_bracketing_donor", method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time, interval_minutes=cadence_minutes)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            gap_seconds = (following_time - previous_time).total_seconds()
            missing_steps = round(gap_seconds / step_seconds) - 1
            if missing_steps < 1 or missing_steps > max_gap_steps or abs(gap_seconds - (missing_steps + 1) * step_seconds) > 1:
                audit = _set_imputation_audit_fields(row, status="pending", reason="gap_not_regular_or_short", method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time, missing_steps=missing_steps, interval_minutes=gap_seconds / max(missing_steps + 1, 1) / 60.0)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            interval_minutes = gap_seconds / (missing_steps + 1) / 60.0
            if interval_minutes > high_frequency_max_interval_minutes:
                audit = _set_imputation_audit_fields(row, status="pending", reason="gap_interval_not_high_frequency", method=None, previous=previous, following=following, previous_time=previous_time, following_time=following_time, missing_steps=missing_steps, interval_minutes=interval_minutes)
                imputation_audit.append(audit)
                pending.append(row)
                continue
            position = (timestamp - previous_time).total_seconds() / gap_seconds
            value = float(previous["clean_value"]) + position * (float(following["clean_value"]) - float(previous["clean_value"]))
            row["clean_value"] = value
            row["is_imputed"] = True
            row["value_origin"] = "imputed"
            row["imputation_method"] = method
            row["imputation_confidence"] = round(max(0.5, 1.0 - 0.15 * missing_steps), 3)
            flags = list(_flags(row.get("quality_flags")))
            if "Q20" not in flags:
                flags.append("Q20")
            row["quality_flags"] = flags
            audit = _set_imputation_audit_fields(row, status="imputed", reason=None, method=method, previous=previous, following=following, previous_time=previous_time, following_time=following_time, missing_steps=missing_steps, interval_minutes=interval_minutes)
            imputation_audit.append(audit)
            imputed.append(row)

    long_gap = handle_long_gap_uncertainty(records, max_gap_steps=max_gap_steps, step_minutes=step_minutes, source_events=source_events, source_health=source_health, expected_intervals=expected_intervals)
    low_frequency = handle_low_frequency_nutrients(records, as_of=as_of, max_age_hours=low_frequency_max_age_hours)
    wind_uv = impute_wind_direction_uv(records, max_gap_steps=max_gap_steps, step_minutes=step_minutes)
    # Wind candidates are intentionally kept in the same pending/imputed
    # contract as scalar gaps so clean.py exports one complete candidate table.
    imputed.extend(wind_uv.get("imputed", []))
    pending.extend(wind_uv.get("pending", []))
    return {
        "records": records,
        "imputed": imputed,
        "pending": pending,
        "missing_mechanism_counts": classification["missing_mechanism_counts"],
        "missing_mechanism_by_source_variable": classification["by_source_variable"],
        "missing_mechanism_policies": classification["policies"],
        "source_event_audit": classification["source_event_audit"],
        "imputation_audit": imputation_audit,
        "imputation_method": method,
        "high_frequency_max_interval_minutes": high_frequency_max_interval_minutes,
        "never_auto_impute": sorted(protected_variables),
        "long_gap_uncertainty": long_gap,
        "low_frequency_nutrients": low_frequency,
        "wind_uv": wind_uv,
    }
