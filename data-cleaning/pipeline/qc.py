from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
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
RULES_VERSION = str(RULES.get("version") or "unversioned")
RANGES: dict[str, tuple[float, float]] = {
    str(code): (float(bounds[0]), float(bounds[1]))
    for code, bounds in (RULES.get("hard_range_rules") or {}).items()
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2
}
SOFT_RULES: dict[str, dict[str, Any]] = {
    str(code): dict(rule)
    for code, rule in (RULES.get("soft_range_rules") or RULES.get("advisory_rules") or {}).items()
    if isinstance(rule, dict) and isinstance(rule.get("range"), (list, tuple)) and len(rule["range"]) == 2
}
SOFT_RANGES: dict[str, tuple[float, float]] = {
    code: (float(rule["range"][0]), float(rule["range"][1]))
    for code, rule in SOFT_RULES.items()
}
DUPLICATE_KEY_FIELDS = tuple((RULES.get("duplicate_key") or {}).get("fields") or ["source_id", "station_id", "scene_id", "observed_at", "variable_code"])
REJECTION_CODES = set((RULES.get("rejection") or {}).get("issue_codes") or ["Q02", "Q03", "Q04", "Q06", "Q07", "Q10", "Q11", "Q08"])
REJECTION_FLAG = str((RULES.get("rejection") or {}).get("appended_flag") or "Q99")
NORMALIZE_WIND_DIRECTION = bool(((RULES.get("normalization") or {}).get("wind_direction_360_to_zero") or {}).get("enabled", True))
MISSING_CODE = str((RULES.get("missing_value") or {}).get("issue_code") or "Q01")
TEMPORAL_RULES = RULES.get("temporal_quality") or {}
TEMPORAL_MAX_GAP_HOURS = float(TEMPORAL_RULES.get("max_gap_hours", 24.0))
SENSOR_STUCK_MIN_POINTS = max(3, int(TEMPORAL_RULES.get("sensor_stuck_min_points", 6)))
SENSOR_STUCK_TOLERANCE = float(TEMPORAL_RULES.get("sensor_stuck_tolerance", 0.0))
FUTURE_TOLERANCE_MINUTES = float(TEMPORAL_RULES.get("future_tolerance_minutes", 0.0))
INTERVAL_CHANGE_RATIO = float(TEMPORAL_RULES.get("interval_change_ratio", 4.0))
INTERVAL_CHANGE_MIN_HOURS = float(TEMPORAL_RULES.get("interval_change_min_hours", 2.0))
SENSOR_STUCK_VARIABLES = {str(item) for item in (TEMPORAL_RULES.get("sensor_stuck_variables") or [])}
UNIVARIATE_RULES = RULES.get("univariate_quality") or {}
HAMPEL_RADIUS = max(1, int(UNIVARIATE_RULES.get("hampel_window_radius", 3)))
HAMPEL_N_SIGMA = float(UNIVARIATE_RULES.get("hampel_n_sigma", 3.0))
HAMPEL_MIN_POINTS = max(5, int(UNIVARIATE_RULES.get("hampel_min_points", 5)))
HAMPEL_VARIABLES = {str(item) for item in (UNIVARIATE_RULES.get("hampel_variables") or [])}
MAX_RATE_PER_HOUR = {str(code): float(value) for code, value in (UNIVARIATE_RULES.get("max_rate_per_hour") or {}).items()}
MULTIVARIATE_RULES = RULES.get("multivariate_quality") or {}
DO_TEMPERATURE_RULE = MULTIVARIATE_RULES.get("do_temperature") or {}
EC_TDS_RULE = MULTIVARIATE_RULES.get("ec_tds") or {}
NUTRIENT_COMPONENT_RULE = MULTIVARIATE_RULES.get("nutrient_components") or {}
PRECIPITATION_FLOW_RULE = MULTIVARIATE_RULES.get("precipitation_flow") or {}
CLOUD_RADIATION_RULE = MULTIVARIATE_RULES.get("cloud_radiation") or {}
SPATIAL_RULES = RULES.get("spatial_quality") or {}
SPATIAL_BOUNDARY_PATH = str(SPATIAL_RULES.get("boundary_path") or str(STORAGE / "silver/geo/taihu_boundary.gpkg"))
SPATIAL_BOUNDARY_LAYER = str(SPATIAL_RULES.get("boundary_layer") or "taihu_boundary_wgs84")
SPATIAL_BUFFER_M = float(SPATIAL_RULES.get("boundary_buffer_m", 5000.0))
STATION_DRIFT_M = float(SPATIAL_RULES.get("station_drift_m", 1000.0))
SPATIAL_SWAP_RULE = SPATIAL_RULES.get("coordinate_swap") or {}
SPATIAL_SWAP_LON_RANGE = tuple(float(value) for value in (SPATIAL_SWAP_RULE.get("longitude_range") or [119.5, 121.0]))
SPATIAL_SWAP_LAT_RANGE = tuple(float(value) for value in (SPATIAL_SWAP_RULE.get("latitude_range") or [30.8, 31.7]))
SPATIAL_ZERO_TOLERANCE = float(SPATIAL_RULES.get("zero_coordinate_tolerance", 0.000001))
SPATIAL_SWAP_CODE = str(SPATIAL_SWAP_RULE.get("issue_code") or "Q36")
SPATIAL_ZERO_CODE = str(SPATIAL_RULES.get("zero_coordinate_issue_code") or "Q37")
SPATIAL_OUTSIDE_CODE = str(SPATIAL_RULES.get("outside_boundary_issue_code") or "Q38")
SPATIAL_DRIFT_CODE = str(SPATIAL_RULES.get("station_drift_issue_code") or "Q39")
SPATIAL_EXPECTED_CRS = str(SPATIAL_RULES.get("expected_crs_epsg", 4326)).replace("EPSG:", "")
SPATIAL_CRS_CODE = str(SPATIAL_RULES.get("crs_issue_code") or "Q40")
UTC = timezone.utc


def _parse_timestamp(row: dict[str, Any]) -> datetime | None:
    value = row.get("observed_at_utc") or row.get("observed_at") or row.get("time_bucket") or row.get("target_time_bucket")
    if value in (None, "", "None", "null"):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _temporal_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in ("source_id", "station_id", "scene_id", "variable_code"))


def _temporal_issue_map(
    records: list[dict[str, Any]],
    *,
    as_of: datetime | None,
    max_gap_hours: float,
    interval_change_ratio: float,
    interval_change_min_hours: float,
    stuck_min_points: int,
    stuck_tolerance: float,
) -> tuple[dict[int, list[tuple[str, str, str]]], dict[str, int], str]:
    """Return row-indexed temporal findings without reordering source rows."""

    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    issue_map: dict[int, list[tuple[str, str, str]]] = {}
    counts: Counter[str] = Counter()
    groups: dict[tuple[Any, ...], list[tuple[int, datetime]]] = {}
    for index, row in enumerate(records):
        timestamp = _parse_timestamp(row)
        if timestamp is not None:
            groups.setdefault(_temporal_key(row), []).append((index, timestamp))
            tolerance = timedelta(minutes=FUTURE_TOLERANCE_MINUTES)
            if timestamp > now + tolerance:
                issue_map.setdefault(index, []).append(("Q15", "high", f"timestamp is in the future relative to {now.isoformat()}"))
                counts["Q15"] += 1

    for items in groups.values():
        # Duplicate timestamp and source-order checks use the original row
        # sequence; intervals use sorted unique timestamps.
        timestamp_indices: dict[datetime, list[int]] = {}
        previous: datetime | None = None
        for index, timestamp in items:
            timestamp_indices.setdefault(timestamp, []).append(index)
            if previous is not None and timestamp < previous:
                issue_map.setdefault(index, []).append(("Q14", "high", "timestamps are out of order within a source/station/variable series"))
                counts["Q14"] += 1
            previous = timestamp
        for timestamp, indices in timestamp_indices.items():
            if len(indices) > 1:
                for index in indices:
                    issue_map.setdefault(index, []).append(("Q13", "high", "duplicate timestamp within a source/station/variable series"))
                    counts["Q13"] += 1

        ordered = sorted(timestamp_indices)
        intervals = [(left, right, (right - left).total_seconds() / 3600.0) for left, right in zip(ordered, ordered[1:])]
        positive_intervals = [item[2] for item in intervals if item[2] > 0]
        median_interval = sorted(positive_intervals)[len(positive_intervals) // 2] if positive_intervals else None
        # A stable low-frequency laboratory/aggregate series must not be
        # judged against the global 24-hour sensor threshold. Require at
        # least three established intervals before adapting the baseline;
        # sparse two-point series keep the conservative absolute rule.
        adaptive_gap_limit = max_gap_hours
        if median_interval and len(positive_intervals) >= 3 and median_interval > max_gap_hours:
            adaptive_gap_limit = median_interval * interval_change_ratio
        for left, right, gap_hours in intervals:
            gap_hours = (right - left).total_seconds() / 3600.0
            ratio_jump = False
            if median_interval and median_interval > 0 and gap_hours >= interval_change_min_hours:
                ratio_jump = gap_hours / median_interval >= interval_change_ratio
            if gap_hours > adaptive_gap_limit or ratio_jump:
                for index in timestamp_indices[right]:
                    reason = f"timestamp gap {gap_hours:g}h exceeds adaptive limit {adaptive_gap_limit:g}h" if gap_hours > adaptive_gap_limit else f"timestamp interval jump {gap_hours:g}h versus median {median_interval:g}h"
                    issue_map.setdefault(index, []).append(("Q16", "medium", reason))
                    counts["Q16"] += 1

        # Constant numeric runs are a suspect signal, not an automatic reject.
        numeric_items: list[tuple[int, datetime, float]] = []
        variable_code = str(records[items[0][0]].get("variable_code") or "") if items else ""
        if variable_code not in SENSOR_STUCK_VARIABLES:
            continue
        for index, timestamp in sorted(items, key=lambda item: item[1]):
            value = records[index].get("clean_value")
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                numeric_items.append((index, timestamp, number))
        run: list[tuple[int, datetime, float]] = []
        for item in numeric_items:
            if not run or abs(item[2] - run[-1][2]) <= stuck_tolerance:
                run.append(item)
            else:
                if len(run) >= stuck_min_points:
                    for index, _, _ in run:
                        issue_map.setdefault(index, []).append(("Q17", "medium", f"sensor value is constant for {len(run)} consecutive records"))
                        counts["Q17"] += 1
                run = [item]
        if len(run) >= stuck_min_points:
            for index, _, _ in run:
                issue_map.setdefault(index, []).append(("Q17", "medium", f"sensor value is constant for {len(run)} consecutive records"))
                counts["Q17"] += 1
    return issue_map, dict(counts), now.isoformat()


def _univariate_issue_map(
    records: list[dict[str, Any]],
    *,
    hampel_radius: int,
    hampel_n_sigma: float,
    hampel_min_points: int,
    hampel_variables: set[str],
    max_rate_per_hour: dict[str, float],
) -> tuple[dict[int, list[tuple[str, str, str]]], dict[str, int]]:
    """Find robust local outliers and implausible single-step changes."""

    groups: dict[tuple[Any, ...], list[tuple[int, datetime, float]]] = {}
    for index, row in enumerate(records):
        variable = str(row.get("variable_code") or "")
        if hampel_variables and variable not in hampel_variables and variable not in max_rate_per_hour:
            continue
        timestamp = _parse_timestamp(row)
        try:
            value = float(row.get("clean_value"))
        except (TypeError, ValueError):
            continue
        if timestamp is None or not math.isfinite(value):
            continue
        groups.setdefault(_temporal_key(row), []).append((index, timestamp, value))

    issue_map: dict[int, list[tuple[str, str, str]]] = {}
    counts: Counter[str] = Counter()
    for items in groups.values():
        ordered = sorted(items, key=lambda item: (item[1], item[0]))
        variable = str(records[ordered[0][0]].get("variable_code") or "")
        values = [item[2] for item in ordered]
        if variable in hampel_variables and len(values) >= hampel_min_points:
            for position, (index, _, value) in enumerate(ordered):
                left = max(0, position - hampel_radius)
                right = min(len(values), position + hampel_radius + 1)
                window = values[left:right]
                median_value = sorted(window)[len(window) // 2]
                deviations = sorted(abs(item - median_value) for item in window)
                mad = deviations[len(deviations) // 2]
                robust_sigma = 1.4826 * mad
                if robust_sigma > 0:
                    is_outlier = abs(value - median_value) > hampel_n_sigma * robust_sigma
                else:
                    # With a flat neighbourhood, a distinct isolated value is
                    # still a valid Hampel/MAD signal; a fully flat run is not.
                    is_outlier = len(set(window)) > 1 and value != median_value and abs(value - median_value) > 0
                if is_outlier:
                    issue_map.setdefault(index, []).append(("Q18", "medium", f"Hampel/MAD outlier: value={value:g}, local_median={median_value:g}, mad={mad:g}"))
                    counts["Q18"] += 1

        threshold = max_rate_per_hour.get(variable)
        if threshold is not None:
            for previous, current in zip(ordered, ordered[1:]):
                interval_hours = (current[1] - previous[1]).total_seconds() / 3600.0
                if interval_hours <= 0:
                    continue
                rate = abs(current[2] - previous[2]) / interval_hours
                if rate > threshold:
                    issue_map.setdefault(current[0], []).append(("Q19", "medium", f"rate of change {rate:g}/h exceeds {threshold:g}/h"))
                    counts["Q19"] += 1
    return issue_map, dict(counts)


def _oxygen_saturation_mg_l(temperature_c: float) -> float:
    """Approximate freshwater oxygen saturation at 1 atm.

    This is a screening relation only: salinity, pressure, and photosynthetic
    supersaturation are not available in the first-release record contract.
    The rule therefore uses a generous configurable multiplier and emits a
    review flag rather than rejecting the observation.
    """

    temperature_c = max(0.0, min(40.0, temperature_c))
    saturation = (
        14.652
        - 0.41022 * temperature_c
        + 0.0079910 * temperature_c**2
        - 0.000077774 * temperature_c**3
    )
    return max(0.1, saturation)


def _multivariate_key(row: dict[str, Any]) -> tuple[Any, ...] | None:
    timestamp = _parse_timestamp(row)
    if timestamp is None:
        return None
    # Keep source/station/scene/depth separate. Exact timestamps are used here;
    # temporal resampling and nearest-neighbour matching belong to P10.
    return (
        row.get("source_id"),
        row.get("station_id"),
        row.get("scene_id"),
        row.get("depth_m"),
        timestamp,
    )


def _multivariate_issue_map(
    records: list[dict[str, Any]],
) -> tuple[dict[int, list[tuple[str, str, str]]], dict[str, int]]:
    """Find same-time cross-variable contradictions as review-only signals.

    The checks are deliberately conservative and configuration-driven. They
    never infer missing values, and no participating row is automatically
    deleted. A contradiction is recorded on every participating observation
    so a reviewer can trace the complete pair or component set.
    """

    groups: dict[tuple[Any, ...], dict[str, list[tuple[int, float]]]] = {}
    for index, row in enumerate(records):
        key = _multivariate_key(row)
        if key is None:
            continue
        variable = str(row.get("variable_code") or "")
        try:
            value = float(row.get("clean_value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        groups.setdefault(key, {}).setdefault(variable, []).append((index, value))

    issue_map: dict[int, list[tuple[str, str, str]]] = {}
    counts: Counter[str] = Counter()
    marked: set[tuple[int, str]] = set()

    def mark(code: str, indices: list[int], message: str) -> None:
        for index in dict.fromkeys(indices):
            marker = (index, code)
            if marker in marked:
                continue
            marked.add(marker)
            issue_map.setdefault(index, []).append((code, "medium", message))
            counts[code] += 1

    def values_for(group: dict[str, list[tuple[int, float]]], variable: str) -> list[tuple[int, float]]:
        return group.get(variable, [])

    # DO—temperature: flag negative DO or values well above freshwater
    # saturation at the observed temperature. The 2x default allows bloom-
    # driven photosynthetic supersaturation and therefore avoids hard rejects.
    do_code = str(DO_TEMPERATURE_RULE.get("issue_code") or "Q25")
    do_ratio = float(DO_TEMPERATURE_RULE.get("max_do_saturation_ratio", 2.0))
    do_min_temp = float(DO_TEMPERATURE_RULE.get("min_temperature_c", -2.0))
    do_max_temp = float(DO_TEMPERATURE_RULE.get("max_temperature_c", 45.0))
    for group in groups.values():
        do_values = values_for(group, "dissolved_oxygen")
        temperature_values = values_for(group, "water_temperature")
        for do_index, dissolved_oxygen in do_values:
            for temperature_index, temperature in temperature_values:
                if temperature < do_min_temp or temperature > do_max_temp:
                    continue
                saturation = _oxygen_saturation_mg_l(temperature)
                if dissolved_oxygen < 0 or dissolved_oxygen > saturation * do_ratio:
                    mark(
                        do_code,
                        [do_index, temperature_index],
                        f"DO-temperature inconsistency: DO={dissolved_oxygen:g} mg/L, temperature={temperature:g} C, saturation≈{saturation:g} mg/L",
                    )

    # EC—TDS: the ratio is a screening interval because ionic composition and
    # temperature correction differ by station. Values are standard units:
    # conductivity uS/cm and TDS mg/L.
    ec_code = str(EC_TDS_RULE.get("issue_code") or "Q26")
    ratio_min = float(EC_TDS_RULE.get("tds_to_ec_min", 0.3))
    ratio_max = float(EC_TDS_RULE.get("tds_to_ec_max", 1.2))
    for group in groups.values():
        ec_values = values_for(group, "conductivity")
        tds_values = values_for(group, "tds")
        for ec_index, conductivity in ec_values:
            for tds_index, tds in tds_values:
                ratio = math.inf if conductivity == 0 and tds > 0 else (tds / conductivity if conductivity > 0 else 0.0)
                if conductivity < 0 or tds < 0 or (conductivity == 0 and tds > 0) or not (ratio_min <= ratio <= ratio_max):
                    mark(
                        ec_code,
                        [ec_index, tds_index],
                        f"EC-TDS inconsistency: conductivity={conductivity:g} uS/cm, TDS={tds:g} mg/L, ratio={ratio:g}",
                    )

    # TN/TP and component checks. Inorganic nitrogen is a lower-bound subset
    # of TN, and phosphate is a subset of TP; only impossible over-sums are
    # flagged, never ordinary nutrient-ratio variation.
    nutrient_code = str(NUTRIENT_COMPONENT_RULE.get("issue_code") or "Q27")
    nutrient_relative_tolerance = float(NUTRIENT_COMPONENT_RULE.get("relative_tolerance", 0.25))
    nutrient_absolute_tolerance = float(NUTRIENT_COMPONENT_RULE.get("absolute_tolerance_mg_l", 0.01))
    for group in groups.values():
        tn_values = values_for(group, "total_nitrogen")
        nitrogen_components = [
            item
            for variable in ("ammonia_nitrogen", "nitrate_nitrogen", "nitrite_nitrogen")
            for item in values_for(group, variable)
        ]
        if tn_values and nitrogen_components:
            component_sum = sum(value for _, value in nitrogen_components)
            for tn_index, total_nitrogen in tn_values:
                if component_sum > total_nitrogen * (1.0 + nutrient_relative_tolerance) + nutrient_absolute_tolerance:
                    mark(
                        nutrient_code,
                        [tn_index] + [index for index, _ in nitrogen_components],
                        f"TN component sum exceeds TN: TN={total_nitrogen:g} mg/L, components={component_sum:g} mg/L",
                    )
        tp_values = values_for(group, "total_phosphorus")
        phosphate_values = values_for(group, "phosphate_phosphorus")
        for tp_index, total_phosphorus in tp_values:
            for phosphate_index, phosphate in phosphate_values:
                if phosphate > total_phosphorus * (1.0 + nutrient_relative_tolerance) + nutrient_absolute_tolerance:
                    mark(
                        nutrient_code,
                        [tp_index, phosphate_index],
                        f"phosphate exceeds TP: TP={total_phosphorus:g} mg/L, phosphate-P={phosphate:g} mg/L",
                    )

    # Precipitation—flow: a heavy-rain/zero-discharge pair is only a review
    # signal because catchment lag and gate operations can explain it. Negative
    # inflow/outflow is also flagged for sign-convention review.
    hydro_code = str(PRECIPITATION_FLOW_RULE.get("issue_code") or "Q28")
    heavy_precipitation = float(PRECIPITATION_FLOW_RULE.get("heavy_precipitation_mm_per_h", 50.0))
    zero_flow_tolerance = float(PRECIPITATION_FLOW_RULE.get("zero_flow_tolerance", 0.0))
    for group in groups.values():
        precipitation_values = values_for(group, "precipitation")
        flow_values = values_for(group, "inflow_discharge") + values_for(group, "outflow_discharge")
        if not flow_values:
            continue
        for flow_index, flow in flow_values:
            if flow < -zero_flow_tolerance:
                mark(hydro_code, [flow_index] + [index for index, _ in precipitation_values], f"negative discharge requires sign-convention review: flow={flow:g}")
            if precipitation_values and any(precipitation >= heavy_precipitation for _, precipitation in precipitation_values) and flow <= zero_flow_tolerance:
                mark(hydro_code, [flow_index] + [index for index, _ in precipitation_values], f"heavy precipitation with near-zero discharge: precipitation≥{heavy_precipitation:g} mm/h, flow={flow:g}")

    # Cloud—radiation: high cloud and high shortwave radiation at the same
    # observation time are a likely unit/field mismatch. Clear-sky low
    # radiation is not flagged because nighttime and solar-angle effects are
    # legitimate.
    cloud_code = str(CLOUD_RADIATION_RULE.get("issue_code") or "Q29")
    high_cloud = float(CLOUD_RADIATION_RULE.get("high_cloud_percent", 90.0))
    high_radiation = float(CLOUD_RADIATION_RULE.get("high_radiation_w_m2", 500.0))
    for group in groups.values():
        cloud_values = values_for(group, "cloud_cover")
        radiation_values = values_for(group, "shortwave_radiation")
        for cloud_index, cloud_cover in cloud_values:
            for radiation_index, radiation in radiation_values:
                if cloud_cover >= high_cloud and radiation > high_radiation:
                    mark(cloud_code, [cloud_index, radiation_index], f"cloud-radiation inconsistency: cloud={cloud_cover:g}%, shortwave={radiation:g} W/m2")

    return issue_map, dict(counts)


def _spatial_issue_map(
    records: list[dict[str, Any]],
    *,
    boundary_path: Path | str | None,
    boundary_layer: str,
    boundary_buffer_m: float,
    station_drift_m: float,
) -> tuple[dict[int, list[tuple[str, str, str]]], dict[str, int], str, str | None]:
    """Find coordinate swaps, sentinel coordinates, boundary misses, and drift.

    The frozen HydroLAKES polygon is used only for records with a station ID;
    scene centroids are allowed to fall outside the lake because a satellite
    footprint can cover the target lake while its metadata centroid is on
    land. All spatial findings are review flags. Existing global coordinate
    validity rules (Q06/Q07) still apply independently.
    """

    issue_map: dict[int, list[tuple[str, str, str]]] = {}
    counts: Counter[str] = Counter()
    marked: set[tuple[int, str]] = set()

    def mark(code: str, indices: list[int], message: str) -> None:
        for index in dict.fromkeys(indices):
            marker = (index, code)
            if marker in marked:
                continue
            marked.add(marker)
            issue_map.setdefault(index, []).append((code, "medium", message))
            counts[code] += 1

    resolved_boundary: Path | None = None
    if boundary_path:
        resolved_boundary = Path(boundary_path)
        if not resolved_boundary.is_absolute():
            # 配置中的相对路径以 data-cleaning 根为基准（如 storage/silver/...），
            # 而 STORAGE 已指向 storage/；依次回退尝试，避免拼接成 storage/storage/...
            candidates = [STORAGE / resolved_boundary, STORAGE.parent / resolved_boundary]
            resolved_boundary = next((c for c in candidates if c.exists()), candidates[0])

    boundary_geometry = None
    transformer = None
    boundary_status = "not_requested"
    if resolved_boundary is not None:
        try:
            import fiona
            from pyproj import Transformer
            from shapely.geometry import Point, shape
            from shapely.ops import transform

            with fiona.open(resolved_boundary, layer=boundary_layer) as layer:
                feature = next(iter(layer), None)
                if feature is None or not feature.get("geometry"):
                    raise ValueError("boundary layer has no geometry")
                source_crs = layer.crs.to_string() if layer.crs else "EPSG:4326"
                boundary_geometry = shape(feature["geometry"])
            transformer = Transformer.from_crs(source_crs, "EPSG:32651", always_xy=True)
            boundary_geometry = transform(transformer.transform, boundary_geometry)
            if not boundary_geometry.is_valid:
                boundary_geometry = boundary_geometry.buffer(0)
            boundary_geometry = boundary_geometry.buffer(max(0.0, float(boundary_buffer_m)))
            boundary_status = "loaded"
        except Exception as exc:  # pragma: no cover - exercised by blocked deployments
            boundary_geometry = None
            transformer = None
            boundary_status = f"unavailable:{type(exc).__name__}"

    station_points: dict[tuple[Any, Any], list[tuple[int, float, float]]] = {}
    for index, row in enumerate(records):
        lon = row.get("longitude")
        lat = row.get("latitude")
        try:
            lon_value = float(lon)
            lat_value = float(lat)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lon_value) and math.isfinite(lat_value)):
            continue

        crs_value = str(row.get("crs_epsg") or "4326").upper().replace("EPSG:", "").strip()
        if crs_value != SPATIAL_EXPECTED_CRS:
            mark(SPATIAL_CRS_CODE, [index], f"coordinate CRS {crs_value or '<missing>'} differs from expected EPSG:{SPATIAL_EXPECTED_CRS}")

        if abs(lon_value) <= SPATIAL_ZERO_TOLERANCE and abs(lat_value) <= SPATIAL_ZERO_TOLERANCE:
            mark(SPATIAL_ZERO_CODE, [index], "coordinate is sentinel (0,0)")
            continue

        swapped = (
            SPATIAL_SWAP_LAT_RANGE[0] <= lon_value <= SPATIAL_SWAP_LAT_RANGE[1]
            and SPATIAL_SWAP_LON_RANGE[0] <= lat_value <= SPATIAL_SWAP_LON_RANGE[1]
        )
        if swapped:
            mark(SPATIAL_SWAP_CODE, [index], f"longitude/latitude appear exchanged: longitude={lon_value:g}, latitude={lat_value:g}")
            continue

        globally_valid = -180.0 <= lon_value <= 180.0 and -90.0 <= lat_value <= 90.0
        if not globally_valid:
            continue

        station_id = row.get("station_id")
        if station_id not in (None, ""):
            station_key = (row.get("source_id"), str(station_id))
            station_points.setdefault(station_key, []).append((index, lon_value, lat_value))
            if boundary_geometry is not None and transformer is not None:
                x_value, y_value = transformer.transform(lon_value, lat_value)
                if not boundary_geometry.covers(Point(x_value, y_value)):
                    mark(SPATIAL_OUTSIDE_CODE, [index], f"station coordinate is outside Taihu boundary plus {boundary_buffer_m:g} m buffer: ({lon_value:g}, {lat_value:g})")

    # Robust station relocation/drift check: compare every station point with
    # the station's coordinate median in projected metres. A single relocation
    # is flagged; the coordinate is not rewritten automatically.
    for points in station_points.values():
        if len(points) < 2:
            continue
        if transformer is not None:
            projected = [(index, *transformer.transform(lon, lat)) for index, lon, lat in points]
            median_x = median(item[1] for item in projected)
            median_y = median(item[2] for item in projected)
            for index, x_value, y_value in projected:
                distance = math.hypot(x_value - median_x, y_value - median_y)
                if distance > station_drift_m:
                    mark(SPATIAL_DRIFT_CODE, [index], f"station coordinate drift {distance:g} m exceeds {station_drift_m:g} m from station median")
        else:
            # Fallback for minimal environments without pyproj: local
            # equirectangular metres are sufficient for the review threshold.
            median_lon = median(item[1] for item in points)
            median_lat = median(item[2] for item in points)
            for index, lon_value, lat_value in points:
                dx = (lon_value - median_lon) * 111320.0 * math.cos(math.radians(median_lat))
                dy = (lat_value - median_lat) * 110540.0
                distance = math.hypot(dx, dy)
                if distance > station_drift_m:
                    mark(SPATIAL_DRIFT_CODE, [index], f"station coordinate drift {distance:g} m exceeds {station_drift_m:g} m from station median")

    return issue_map, dict(counts), boundary_status, str(resolved_boundary) if resolved_boundary is not None else None


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
        "raw_value": row.get("raw_value", row.get("observed_value")),
        "raw_unit": row.get("raw_unit", row.get("source_unit", row.get("unit"))),
    }


def quality_control(
    records: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
    max_gap_hours: float = TEMPORAL_MAX_GAP_HOURS,
    interval_change_ratio: float = INTERVAL_CHANGE_RATIO,
    interval_change_min_hours: float = INTERVAL_CHANGE_MIN_HOURS,
    stuck_min_points: int = SENSOR_STUCK_MIN_POINTS,
    stuck_tolerance: float = SENSOR_STUCK_TOLERANCE,
    hampel_radius: int = HAMPEL_RADIUS,
    hampel_n_sigma: float = HAMPEL_N_SIGMA,
    hampel_min_points: int = HAMPEL_MIN_POINTS,
    hampel_variables: set[str] | None = None,
    max_rate_per_hour: dict[str, float] | None = None,
    boundary_path: Path | str | None = SPATIAL_BOUNDARY_PATH,
    boundary_layer: str = SPATIAL_BOUNDARY_LAYER,
    boundary_buffer_m: float = SPATIAL_BUFFER_M,
    station_drift_m: float = STATION_DRIFT_M,
) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    imputation_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    suspect: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    flag_counts: Counter[str] = Counter()
    temporal_map, temporal_counts, as_of_utc = _temporal_issue_map(
        records,
        as_of=as_of,
        max_gap_hours=max_gap_hours,
        interval_change_ratio=interval_change_ratio,
        interval_change_min_hours=interval_change_min_hours,
        stuck_min_points=stuck_min_points,
        stuck_tolerance=stuck_tolerance,
    )
    univariate_map, univariate_counts = _univariate_issue_map(
        records,
        hampel_radius=hampel_radius,
        hampel_n_sigma=hampel_n_sigma,
        hampel_min_points=hampel_min_points,
        hampel_variables=hampel_variables if hampel_variables is not None else HAMPEL_VARIABLES,
        max_rate_per_hour=max_rate_per_hour if max_rate_per_hour is not None else MAX_RATE_PER_HOUR,
    )
    multivariate_map, multivariate_counts = _multivariate_issue_map(records)
    spatial_map, spatial_counts, spatial_boundary_status, spatial_boundary_resolved = _spatial_issue_map(
        records,
        boundary_path=boundary_path,
        boundary_layer=boundary_layer,
        boundary_buffer_m=boundary_buffer_m,
        station_drift_m=station_drift_m,
    )
    for index, row in enumerate(records):
        flags: list[str] = list(row.get("quality_flags") or [])
        soft_issue = False
        key = tuple(row.get(field) for field in DUPLICATE_KEY_FIELDS)
        if key in seen:
            flags.append("Q08")
            issues.append(_issue(row, "Q08", "medium", "duplicate business key"))
        seen.add(key)

        hard_issue = False
        soft_issue = False
        parsed_timestamp = _parse_timestamp(row)
        if not row.get("observed_at") or parsed_timestamp is None:
            flags.append("Q03")
            issues.append(_issue(row, "Q03", "high", "missing or invalid observation timestamp"))
            hard_issue = True

        if row.get("unit_issue"):
            flags.append(row["unit_issue"])
            issues.append(_issue(row, row["unit_issue"], "high", row.get("unit_issue_message", "unit consistency failure")))
            hard_issue = True

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
                hard_issue = True
            else:
                if not (bounds[0] <= numeric_coordinate <= bounds[1]):
                    flags.append("Q07")
                    issues.append(_issue(row, "Q07", "high", f"{coordinate_name} outside allowed range {bounds}"))
                    hard_issue = True

        value = row.get("clean_value")
        if value is None:
            flags.append(MISSING_CODE)
            issues.append(_issue(row, MISSING_CODE, "high", "missing value"))
            hard_issue = False  # missing values are traceable candidates, not rejected
        elif not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            flags.append("Q02")
            issues.append(_issue(row, "Q02", "high", "non-numeric or non-finite value"))
            hard_issue = True
        else:
            bounds = RANGES.get(row.get("variable_code"))
            if bounds and not (bounds[0] <= float(value) <= bounds[1]):
                flags.append("Q04")
                issues.append(_issue(row, "Q04", "critical", f"outside allowed range {bounds}"))
                hard_issue = True
            soft_rule = SOFT_RULES.get(str(row.get("variable_code")))
            soft_bounds = SOFT_RANGES.get(str(row.get("variable_code")))
            if soft_bounds and not (soft_bounds[0] <= float(value) <= soft_bounds[1]):
                soft_code = str((soft_rule or {}).get("issue_code") or "Q12")
                soft_severity = str((soft_rule or {}).get("severity") or "medium")
                flags.append(soft_code)
                issues.append(_issue(row, soft_code, soft_severity, f"outside soft review range {soft_bounds}"))
                soft_issue = True
            if NORMALIZE_WIND_DIRECTION and row.get("variable_code") == "wind_direction" and float(value) == 360:
                row["clean_value"] = 0.0
                flags.append("Q21")
                issues.append(_issue(row, "Q21", "low", "wind direction normalized from 360 to 0"))

        for code, severity, message in temporal_map.get(index, []):
            if code not in flags:
                flags.append(code)
                issues.append(_issue(row, code, severity, message))
            if code in {"Q16", "Q17"}:
                soft_issue = True
        for code, severity, message in univariate_map.get(index, []):
            if code not in flags:
                flags.append(code)
                issues.append(_issue(row, code, severity, message))
            if code in {"Q18", "Q19"}:
                soft_issue = True
        for code, severity, message in multivariate_map.get(index, []):
            if code not in flags:
                flags.append(code)
                issues.append(_issue(row, code, severity, message))
            if code in {"Q25", "Q26", "Q27", "Q28", "Q29"}:
                soft_issue = True
        for code, severity, message in spatial_map.get(index, []):
            if code not in flags:
                flags.append(code)
                issues.append(_issue(row, code, severity, message))
            if code in {SPATIAL_SWAP_CODE, SPATIAL_ZERO_CODE, SPATIAL_OUTSIDE_CODE, SPATIAL_DRIFT_CODE, SPATIAL_CRS_CODE}:
                soft_issue = True

        row["quality_flags"] = flags or ["Q00"]
        if any(code in flags for code in REJECTION_CODES):
            row["quality_flags"].append(REJECTION_FLAG)
            rejected.append(row)
        elif MISSING_CODE in flags:
            # Missing observations remain traceable, but are kept out of the
            # modeling table until the explicit imputation stage handles them.
            imputation_candidates.append(row)
        elif soft_issue:
            # Soft physical bounds are retained for review and are never
            # silently dropped. They are excluded from the clean model table.
            row["record_status"] = "suspect"
            suspect.append(row)
        else:
            cleaned.append(row)
        flag_counts.update(row["quality_flags"])

    return {
        "cleaned": cleaned,
        "imputation_candidates": imputation_candidates,
        "rejected": rejected,
        "suspect": suspect,
        "issues": issues,
        "flag_counts": dict(flag_counts),
        "rules_version": RULES_VERSION,
        "temporal_issue_counts": temporal_counts,
        "univariate_issue_counts": univariate_counts,
        "multivariate_issue_counts": multivariate_counts,
        "spatial_issue_counts": spatial_counts,
        "spatial_boundary_status": spatial_boundary_status,
        "spatial_boundary_path": spatial_boundary_resolved,
        "temporal_as_of_utc": as_of_utc,
        "temporal_max_gap_hours": max_gap_hours,
        "temporal_interval_change_ratio": interval_change_ratio,
        "sensor_stuck_min_points": stuck_min_points,
    }
