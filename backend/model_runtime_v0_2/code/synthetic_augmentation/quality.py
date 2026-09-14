from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


RANGE_RULES = {
    "air_temperature_C": (-25.0, 45.0),
    "water_temperature_C": (0.0, 40.0),
    "total_phosphorus_mg_L": (0.0, 1.0),
    "total_nitrogen_mg_L": (0.0, 15.0),
    "dissolved_oxygen_mg_L": (0.0, 25.0),
    "ph": (5.5, 11.0),
    "wind_speed_m_s": (0.0, 40.0),
    "precipitation_mm_day": (0.0, 500.0),
    "solar_radiation_MJ_m2_day": (0.0, 40.0),
    "water_level_m": (1.0, 6.0),
    "flow_speed_m_s": (0.0, 3.0),
    "chlorophyll_a_ug_L": (0.0, 500.0),
    "cyanobacteria_density_cells_L": (0.0, 1.0e9),
    "blue_algae_biomass_mg_L": (0.0, 40.0),
    "bloom_probability": (0.0, 1.0),
    "bloom_area_km2": (0.0, 2500.0),
}

PROVENANCE_EXPECTATIONS = {
    "data_mode": "simulation",
    "is_ground_truth": 0,
    "label_evidence": "simulation_mechanism",
    "claim_boundary": "synthetic_development_only",
}

CORRELATION_EXCLUDE_PREFIXES = (
    "target_",
    "bloom_",
)


def _longest_constant_run(series: pd.Series) -> int:
    values = series.to_numpy()
    if len(values) == 0:
        return 0
    longest = current = 1
    for index in range(1, len(values)):
        if pd.isna(values[index]) and pd.isna(values[index - 1]):
            current += 1
        elif values[index] == values[index - 1]:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
    return int(longest)


def _find_repeated_temporal_blocks(frame: pd.DataFrame) -> list[dict[str, object]]:
    numeric_columns = [
        column
        for column in frame.select_dtypes(include=[np.number]).columns
        if column not in {"is_ground_truth", "random_seed", "bloom_label"}
        and not column.startswith("target_")
    ]
    if not numeric_columns or "date" not in frame or "spatial_id" not in frame:
        return []
    repeats: list[dict[str, object]] = []
    working = frame[["spatial_id", "date", *numeric_columns]].copy()
    working["date"] = pd.to_datetime(working["date"])
    working["year"] = working["date"].dt.year
    working["month_day"] = working["date"].dt.strftime("%m-%d")
    for spatial_id, region in working.groupby("spatial_id", observed=True):
        years = sorted(region["year"].unique())
        for left_year, right_year in combinations(years, 2):
            left = region.loc[region["year"] == left_year, ["month_day", *numeric_columns]]
            right = region.loc[region["year"] == right_year, ["month_day", *numeric_columns]]
            merged = left.merge(right, on="month_day", suffixes=("_left", "_right"))
            if len(merged) < 360:
                continue
            left_values = merged[[f"{column}_left" for column in numeric_columns]].to_numpy(float)
            right_values = merged[[f"{column}_right" for column in numeric_columns]].to_numpy(float)
            if np.allclose(left_values, right_values, equal_nan=True, atol=1e-12, rtol=0.0):
                repeats.append(
                    {
                        "spatial_id": str(spatial_id),
                        "left_year": int(left_year),
                        "right_year": int(right_year),
                        "matching_days": int(len(merged)),
                    }
                )
    return repeats


def _mechanical_correlations(frame: pd.DataFrame) -> list[dict[str, object]]:
    if "bloom_probability" not in frame.columns:
        return []
    candidates = [
        column
        for column in frame.select_dtypes(include=[np.number]).columns
        if column != "bloom_probability"
        and not column.startswith(CORRELATION_EXCLUDE_PREFIXES)
        and column not in {"is_ground_truth", "random_seed", "region_area_km2"}
    ]
    findings = []
    for column in candidates:
        pair = frame[[column, "bloom_probability"]].dropna()
        if len(pair) < 20 or pair[column].nunique() < 2:
            continue
        correlation = float(pair[column].corr(pair["bloom_probability"]))
        if np.isfinite(correlation) and abs(correlation) >= 0.999999:
            findings.append({"feature": column, "correlation": correlation})
    return findings


def profile_quality(frame: pd.DataFrame) -> dict[str, object]:
    report: dict[str, object] = {
        "status": "PASS",
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "blocking_issues": [],
        "warnings": [],
    }
    blocking: list[str] = report["blocking_issues"]
    required_key = {"sample_id", "date", "spatial_id"}
    if required_key.issubset(frame.columns):
        duplicate_primary_keys = int(frame.duplicated(["spatial_id", "date"]).sum())
        duplicate_sample_ids = int(frame["sample_id"].duplicated().sum())
    else:
        duplicate_primary_keys = -1
        duplicate_sample_ids = -1
        blocking.append("missing primary-key columns")
    report["duplicate_primary_keys"] = duplicate_primary_keys
    report["duplicate_sample_ids"] = duplicate_sample_ids
    if duplicate_primary_keys > 0 or duplicate_sample_ids > 0:
        blocking.append("duplicate primary keys")

    exact_duplicates = int(frame.duplicated().sum())
    report["exact_duplicate_rows"] = exact_duplicates
    if exact_duplicates > 0:
        blocking.append("exact duplicate rows")

    missing_provenance = []
    for column, expected in PROVENANCE_EXPECTATIONS.items():
        if column not in frame.columns:
            missing_provenance.append(column)
        elif not frame[column].eq(expected).all():
            missing_provenance.append(column)
    report["missing_or_invalid_provenance"] = missing_provenance
    if missing_provenance:
        blocking.append("missing provenance")

    spatial_values = set(frame["spatial_id"].dropna().astype(str)) if "spatial_id" in frame else set()
    mixed_whole_grain = "TAIHU_WHOLE" in spatial_values and len(spatial_values) > 1
    report["mixed_whole_and_region_grain"] = mixed_whole_grain
    if mixed_whole_grain:
        blocking.append("mixed whole-lake and regional grain")

    calendar_gaps = {}
    if {"spatial_id", "date"}.issubset(frame.columns):
        for spatial_id, group in frame.groupby("spatial_id", observed=True):
            dates = pd.DatetimeIndex(pd.to_datetime(group["date"], errors="coerce").dropna().unique())
            if len(dates):
                expected_days = int((dates.max() - dates.min()).days + 1)
                gap_count = expected_days - len(dates)
                if gap_count:
                    calendar_gaps[str(spatial_id)] = int(gap_count)
    report["calendar_gap_days"] = calendar_gaps
    if calendar_gaps:
        blocking.append("non-continuous regional calendar")

    invalid_ranges = {}
    boundary_pileups = {}
    for column, (lower, upper) in RANGE_RULES.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid = int(((values < lower) | (values > upper)).sum())
        if invalid:
            invalid_ranges[column] = invalid
        non_null = values.dropna()
        if len(non_null):
            pileup = float(((non_null == lower) | (non_null == upper)).mean())
            if pileup >= 0.05:
                boundary_pileups[column] = pileup
    report["invalid_ranges"] = invalid_ranges
    report["boundary_pileup_rates"] = boundary_pileups
    if invalid_ranges:
        blocking.append("values outside allowed ranges")

    constant_runs = {}
    if {"spatial_id", "date"}.issubset(frame.columns):
        numeric = [column for column in RANGE_RULES if column in frame.columns]
        ordered = frame.sort_values(["spatial_id", "date"])
        for column in numeric:
            longest = max(
                (_longest_constant_run(group[column]) for _, group in ordered.groupby("spatial_id", observed=True)),
                default=0,
            )
            constant_runs[column] = int(longest)
    report["longest_constant_runs"] = constant_runs

    repeated_blocks = _find_repeated_temporal_blocks(frame)
    report["repeated_temporal_blocks"] = repeated_blocks
    if repeated_blocks:
        blocking.append("repeated temporal block")

    correlations = _mechanical_correlations(frame)
    report["mechanical_correlations"] = correlations
    if correlations:
        blocking.append("mechanical correlation")

    if "bloom_label_state" in frame.columns:
        report["label_state_counts"] = {
            str(key): int(value)
            for key, value in frame["bloom_label_state"].value_counts(dropna=False).items()
        }
    elif "bloom_label" in frame.columns:
        report["label_value_counts"] = {
            str(key): int(value)
            for key, value in frame["bloom_label"].value_counts(dropna=False).items()
        }

    if "dataset_split" in frame.columns:
        report["split_counts"] = {
            str(key): int(value)
            for key, value in frame["dataset_split"].value_counts(dropna=False).items()
        }
    report["null_rates"] = {
        column: float(rate)
        for column, rate in frame.isna().mean().items()
        if rate > 0
    }
    if blocking:
        report["status"] = "FAIL"
    return report


def assert_quality_gates(report: dict[str, object]) -> None:
    issues = list(report.get("blocking_issues", []))
    if issues:
        raise ValueError("; ".join(issues))


# V0.3 is deliberately separate: no legacy constants or gates are changed.
import hashlib
import json
import math
import re
from collections import defaultdict
from types import MappingProxyType

from .forecast import V03_TARGET_COLUMNS
from .features import v03_feature_allowlist

V03_THRESHOLD_VERSION = "TAIHU_QA_DEVELOPMENT_V0.3.1"
V03_THRESHOLDS = MappingProxyType({
    "boundary_pileup_max": .02, "constant_run_max_days": 30,
    "histogram_bins": 1024, "mechanical_correlation_max": .999,
    "direction_min": 0., "direction_max": .98,
    "moran_min": .02, "moran_max": .98,
    "neighbor_correlation_min": .02, "neighbor_correlation_max": .98,
    "correlation_length_min_m": 1000., "correlation_length_max_m": 50000.,
    "transport_relative_error_max": 1e-8,
    "anchor_median_relative_error_max": .5, "anchor_quantile_relative_error_max": .75,
    "anchor_extreme_relative_error_max": 2., "anchor_rank_correlation_min": .3,
    "anchor_min_count": 10, "positive_lake_days_min": 30, "negative_lake_days_min": 90,
    "positive_grid_days_min": 1000, "processes_min": 2, "task_usable_min": 10000,
})
V03_RANGE_RULES = MappingProxyType({
    **RANGE_RULES, "blue_algae_biomass_mg_L": (0., 42.),
    "phytoplankton_biomass_mg_L": (0., 100.), "bloom_coverage_ratio": (0., 1.),
    "wind_direction_deg": (0., 360.), "relative_humidity_pct": (0., 100.),
    "surface_pressure_kPa": (80., 120.), "mixing_index": (0., 1.),
    "cloud_fraction": (0., 1.), "valid_pixel_ratio": (0., 1.),
})
# Event-defined zero area/coverage, dry days and missing-pixel coverage have
# physical point masses. Exemptions are explicit, never inferred from data.
V03_BOUNDARY_EXEMPT = frozenset(
    (
        "precipitation_mm_day",
        "cloud_fraction",
        "bloom_area_km2",
        "bloom_coverage_ratio",
        "valid_pixel_ratio",
    )
)
V03_CORE_COLUMNS = ("water_temperature_C", "total_nitrogen_mg_L", "total_phosphorus_mg_L",
                    "dissolved_oxygen_mg_L", "ph", "phytoplankton_biomass_mg_L")
V03_SEED_TOLERANCES = MappingProxyType({name: MappingProxyType({"atol":atol,"rtol":.1}) for name,atol in (
    ("water_temperature_C",2.),("total_nitrogen_mg_L",.2),("total_phosphorus_mg_L",.02),
    ("dissolved_oxygen_mg_L",.5),("ph",.2),("phytoplankton_biomass_mg_L",1.),
    ("bloom_probability",.05),("cyanobacteria_density_cells_L",1e6),
    ("blue_algae_biomass_mg_L",1.),("chlorophyll_a_ug_L",5.))})
V03_REQUIRED_UNITS = MappingProxyType({
    "water_temperature_C":"C","total_nitrogen_mg_L":"mg_L","total_phosphorus_mg_L":"mg_L",
    "dissolved_oxygen_mg_L":"mg_L","ph":"pH","phytoplankton_biomass_mg_L":"mg_L",
    **{f"{name}_{h}d":unit for name,unit in {
        "target_bloom":"binary","target_bloom_probability":"probability","target_bloom_area_km2":"km2",
        "target_bloom_coverage_ratio":"ratio","target_cyanobacteria_density_cells_L":"cells_L",
        "target_blue_algae_biomass_mg_L":"mg_L","target_chlorophyll_a_ug_L":"ug_L",
        "target_bloom_risk_level":"category"}.items() for h in (1,3,7,15,30)}})
_HORIZONS = (1, 3, 7, 15, 30)
_SPLITS = ("train", "validation", "test")
_COUNT_ISSUES = {
    "invalid_provenance_count": "provenance", "invalid_range_count": "range",
    "nonfinite_count": "nonfinite", "unknown_as_negative_count": "unknown encoded as negative",
    "invalid_label_count": "invalid label", "split_disagreement_count": "split disagreement",
    "target_violation_count": "target alignment/tail/embargo", "leakage_count": "leakage",
    "mixed_grain_count": "mixed grain", "duplicate_primary_keys": "duplicate primary keys",
}


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def v03_threshold_sha256():
    """Hash immutable development thresholds including units/ranges/exemptions."""
    return _digest({"version": V03_THRESHOLD_VERSION, "thresholds": dict(V03_THRESHOLDS),
                    "ranges": dict(V03_RANGE_RULES), "boundary_exempt": sorted(V03_BOUNDARY_EXEMPT),
                    "seed_tolerances":default_seed_tolerances(),"required_units":dict(V03_REQUIRED_UNITS)})


def default_seed_tolerances():
    """Return an independent copy of native-unit core q10/q50/q90 tolerances."""
    return {name:dict(tolerance) for name,tolerance in V03_SEED_TOLERANCES.items()}


def _split_vector(dates):
    return np.where(dates.dt.year <= 2017, "train", np.where(dates.dt.year <= 2021, "validation", "test"))


def profile_v04_long_horizons(frame, config):
    """Validate V0.4 T+60/T+90 dates, embargoes, ranges, and split counts."""
    expected_horizons = (1, 3, 7, 15, 30, 60, 90)
    if tuple(getattr(config, "horizons", ())) != expected_horizons:
        raise ValueError("invalid V0.4 quality config horizons")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("empty or invalid V0.4 partition")
    if not frame.columns.is_unique or not {"grid_id", "date", "dataset_split"}.issubset(frame):
        raise ValueError("V0.4 partition requires unique columns and grid/date/split")

    working = frame.copy(deep=True)
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    issues = []
    violations = 0
    if working["date"].isna().any() or not working["date"].eq(working["date"].dt.normalize()).all():
        issues.append("invalid date")
    if working["grid_id"].isna().any() or working.duplicated(["grid_id", "date"]).any():
        issues.append("invalid or duplicate primary key")
    if issues:
        return {
            "schema_version": "v04-long-horizon-profile-1",
            "status": "FAIL",
            "blocking_issues": sorted(set(issues)),
            "row_count": int(len(working)),
            "target_violation_count": int(len(working)),
            "horizon_counts": {},
        }

    start = pd.Timestamp(config.start_date).normalize()
    end = pd.Timestamp(config.end_date).normalize()
    if working["date"].lt(start).any() or working["date"].gt(end).any():
        issues.append("date outside V0.4 config")
    expected_split = pd.Series(_split_vector(working["date"]), index=working.index)
    split_mismatch = ~working["dataset_split"].eq(expected_split)
    violations += int(split_mismatch.sum())
    if split_mismatch.any():
        issues.append("split disagreement")

    horizon_counts = {}
    for horizon in (60, 90):
        future_date = working["date"] + pd.Timedelta(days=horizon)
        same_split = pd.Series(_split_vector(future_date), index=working.index).eq(expected_split)
        eligible = future_date.le(end) & same_split
        embargo = ~eligible
        date_name = f"target_date_{horizon}d"
        flag_name = f"target_embargo_{horizon}d"
        required = {
            date_name,
            flag_name,
            *(f"{prefix}_{horizon}d" for prefix in V03_TARGET_COLUMNS.values()),
        }
        missing = sorted(required - set(working.columns))
        if missing:
            issues.append(f"missing V0.4 target family {horizon}d")
            violations += len(working) * len(missing)
            continue

        actual_date = pd.to_datetime(working[date_name], errors="coerce")
        expected_date = future_date.where(eligible)
        date_matches = (actual_date.isna() & expected_date.isna()) | actual_date.eq(expected_date)
        flag_matches = working[flag_name].eq(embargo.astype("int8"))
        violations += int((~date_matches).sum() + (~flag_matches).sum())

        by_split = {}
        for split in _SPLITS:
            split_rows = expected_split.eq(split)
            target_nonnull = {
                prefix: int(working.loc[split_rows, f"{prefix}_{horizon}d"].notna().sum())
                for prefix in V03_TARGET_COLUMNS.values()
            }
            by_split[split] = {
                "rows": int(split_rows.sum()),
                "eligible": int((split_rows & eligible).sum()),
                "embargoed": int((split_rows & embargo).sum()),
                "target_nonnull": target_nonnull,
            }
        horizon_counts[f"{horizon}d"] = by_split

        for source, prefix in V03_TARGET_COLUMNS.items():
            name = f"{prefix}_{horizon}d"
            violations += int((embargo & working[name].notna()).sum())
            if source == "bloom_risk_level":
                valid_value = working[name].isna() | working[name].isin(
                    ("none", "low", "medium", "high", "severe", "unknown")
                )
            elif source == "bloom_label":
                valid_value = working[name].isna() | working[name].isin((0, 1))
            else:
                numeric = pd.to_numeric(working[name], errors="coerce")
                lower, upper = V03_RANGE_RULES[source]
                valid_value = working[name].isna() | numeric.between(lower, upper)
            violations += int((~valid_value).sum())

    if violations:
        issues.append("V0.4 target alignment/tail/embargo")
    return {
        "schema_version": "v04-long-horizon-profile-1",
        "status": "FAIL" if issues else "PASS",
        "blocking_issues": sorted(set(issues)),
        "row_count": int(len(working)),
        "columns": sorted(working.columns),
        "split_counts": {
            split: int(expected_split.eq(split).sum()) for split in _SPLITS
        },
        "target_violation_count": int(violations),
        "horizon_counts": horizon_counts,
        "normalized_content_hash": _row_hash(
            working.sort_values(["grid_id", "date"], kind="mergesort").reset_index(drop=True)
        ),
    }


def _config_identity(config):
    if tuple(config.horizons) != _HORIZONS or config.expected_grid_count <= 0 or len(config.dates) == 0:
        raise ValueError("invalid V0.3 quality config")
    return {"start_date": str(config.dates[0].date()), "end_date": str(config.dates[-1].date()),
            "expected_grid_count": int(config.expected_grid_count), "horizons": list(_HORIZONS)}


def _row_hash(frame):
    """Canonical column-order/dtype-independent hash in the current row order.

    Numeric columns normalize to float64 and timestamps to ISO strings. pandas
    row hashes feed SHA-256; this is reproducibility evidence, NOT a key registry.
    The pinned pandas version is part of the manifest runtime contract.
    """
    normalized = {}
    for name in sorted(frame.columns):
        values = frame[name]
        if pd.api.types.is_numeric_dtype(values):
            normalized[name] = pd.to_numeric(values).astype(float)
        elif pd.api.types.is_datetime64_any_dtype(values):
            normalized[name] = values.astype("string").fillna("<NULL>")
        else:
            normalized[name] = values.astype("string").fillna("<NULL>")
    canonical = pd.DataFrame(normalized, index=frame.index)
    row_hashes = pd.util.hash_pandas_object(canonical, index=False).to_numpy(dtype="<u8")
    digest = hashlib.sha256(_canonical_json(sorted(normalized)).encode("utf-8"))
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()


def _add_quantiles(stats, bounds):
    histogram = np.asarray(stats["histogram"], dtype=np.int64)
    n = int(histogram.sum()); lower, upper = bounds
    width = (upper-lower)/len(histogram)
    if n:
        cumulative = histogram.cumsum()
        # Interpolate the two order statistics as numpy's linear quantile does.
        ranks = np.array([.1, .5, .9])*(n-1)
        left = np.searchsorted(cumulative, np.floor(ranks)+1)
        right = np.searchsorted(cumulative, np.ceil(ranks)+1)
        stats["quantiles"] = (lower + (left+.5+(right-left)*(ranks-np.floor(ranks)))*width).tolist()
    else:
        stats["quantiles"] = [None, None, None]
    stats["quantile_error_bound"] = width/2
    stats["quantile_method"] = "fixed_range_histogram_linear_ranks_v1"


def _numeric_summary(values, bounds):
    finite = values[np.isfinite(values)]
    n = len(finite)
    mean = float(np.mean(finite)) if n else 0.
    result = {"count": n, "sum": float(np.sum(finite, dtype=np.longdouble)),
              "sumsq": float(np.sum(finite.astype(np.longdouble)**2)), "mean": mean,
              "m2": float(np.sum((finite-mean).astype(np.longdouble)**2)),
              "min": float(finite.min()) if n else None, "max": float(finite.max()) if n else None,
              "boundary_count": int(np.count_nonzero((finite == bounds[0]) | (finite == bounds[1]))),
              "histogram": np.histogram(finite, bins=V03_THRESHOLDS["histogram_bins"], range=bounds)[0].tolist()}
    _add_quantiles(result, bounds)
    return result


def _lag_stats(left, right):
    valid = np.isfinite(left) & np.isfinite(right)
    x, y = left[valid], right[valid]
    return {"count": int(valid.sum()), "sum_x": float(np.sum(x, dtype=np.longdouble)),
            "sum_y": float(np.sum(y, dtype=np.longdouble)), "sum_xx": float(np.sum(x.astype(np.longdouble)**2)),
            "sum_yy": float(np.sum(y.astype(np.longdouble)**2)), "sum_xy": float(np.sum(x.astype(np.longdouble)*y))}


def _run_summary(values):
    equal = (values[1:] == values[:-1]) & np.isfinite(values[1:]) & np.isfinite(values[:-1])
    lengths = np.diff(np.r_[0, np.flatnonzero(~equal)+1, len(values)])
    return {"length": len(values), "first": float(values[0]) if np.isfinite(values[0]) else None,
            "last": float(values[-1]) if np.isfinite(values[-1]) else None,
            "prefix": int(lengths[0]), "suffix": int(lengths[-1]), "max": int(lengths.max())}


def _sequence_hash(values):
    # Composable polynomial fingerprint; used conservatively to flag repeated
    # value blocks, never to certify uniqueness or coverage. uint64 wrap is defined.
    hashes = pd.util.hash_pandas_object(values, index=False).to_numpy(np.uint64)
    powers = np.power(np.uint64(1000003), np.arange(len(hashes)-1,-1,-1,dtype=np.uint64))
    return int(np.sum(hashes*powers,dtype=np.uint64))


def profile_partition_v03(frame, config):
    """Summarize one nonempty partition without retaining rows or full key lists.

    Exact key contract: each grid must contain unique contiguous midnight days
    within config. Arbitrary input row order is normalized and recorded. A grid
    with holes is rejected, not compressed into a misleading min/max proof.
    Summary size O(C*1024 + G*C + G*calendar_blocks); frame work O(N*C).
    Returned profile is not a full-package release authorization.
    """
    identity = _config_identity(config)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("empty or invalid partition")
    if not frame.columns.is_unique or not {"grid_id", "date"}.issubset(frame):
        raise ValueError("partition requires unique columns and grid_id/date")
    f = frame.copy(deep=True)
    f["date"] = pd.to_datetime(f.date, errors="coerce")
    invalid_grid = f.grid_id.isna() | f.grid_id.astype(str).str.strip().str.casefold().isin(("", "nan", "none", "null", "<na>"))
    if invalid_grid.any() or f.date.isna().any() or not f.date.eq(f.date.dt.normalize()).all():
        raise ValueError("invalid partition grid_id/date")
    f["grid_id"] = f.grid_id.astype(str)
    if f.date.lt(config.dates[0]).any() or f.date.gt(config.dates[-1]).any():
        raise ValueError("partition dates outside config")
    ordered_hash = _row_hash(f)
    f = f.sort_values(["grid_id", "date"], kind="mergesort").reset_index(drop=True)
    p = {"schema_version": "partition-profile-v03-1", "config": identity,
         "threshold_sha256": v03_threshold_sha256(), "row_count": len(f), "columns": sorted(f.columns),
         "ordered_content_hash": ordered_hash, "normalized_content_hash": _row_hash(f),
         "input_sorted": ordered_hash == _row_hash(f), "blocking_issues": [],
         "null_counts": {c:int(v) for c,v in f.isna().sum().items()},
         "numeric_stats": {}, "key_intervals": [], "grid_summaries": {}, "temporal_blocks": [],
         "label_state_counts": {}, "split_counts": {}, "target_counts": {}}
    p.update({key:0 for key in _COUNT_ISSUES})
    p["duplicate_primary_keys"] = int(f.duplicated(["grid_id", "date"]).sum())
    p["key_min"] = [f.grid_id.iloc[0], str(f.date.iloc[0].date())]
    p["key_max"] = [f.grid_id.iloc[-1], str(f.date.iloc[-1].date())]
    for column, expected in (("data_mode","simulation"),("is_ground_truth",0),("claim_boundary","synthetic_development_only")):
        p["invalid_provenance_count"] += len(f) if column not in f else int((~f[column].eq(expected).fillna(False)).sum())
    evidence = {"simulation_truth", "simulation_truth_masked_by_observation_process", "simulation_mechanism"}
    p["invalid_provenance_count"] += len(f) if "label_evidence" not in f else int((~f.label_evidence.isin(evidence)).sum())
    p["mixed_grain_count"] = int(f.grid_id.str.startswith("TAIHU_WHOLE").sum())
    if {"label_state", "bloom_label"}.issubset(f):
        unknown = f.label_state.eq("simulation_unknown")
        p["unknown_as_negative_count"] = int((unknown & f.bloom_label.eq(0).fillna(False)).sum())
        valid_label = ((unknown & f.bloom_label.isna()) | (f.label_state.eq("simulation_positive") & f.bloom_label.eq(1).fillna(False)) | (f.label_state.eq("simulation_negative") & f.bloom_label.eq(0).fillna(False)))
        p["invalid_label_count"] = int((~valid_label).sum())
        p["label_state_counts"] = {str(k):int(v) for k,v in f.label_state.value_counts(dropna=False).items()}
    else:
        p["invalid_label_count"] = len(f)
    expected_split = _split_vector(f.date)
    p["split_disagreement_count"] = len(f) if "dataset_split" not in f else int((~f.dataset_split.eq(expected_split)).sum())
    if "dataset_split" in f:
        p["split_counts"] = {str(k):int(v) for k,v in f.dataset_split.value_counts(dropna=False).items()}
    for horizon in _HORIZONS:
        future = f.date + pd.Timedelta(days=horizon)
        tail = future.gt(config.dates[-1]); embargo = tail | (_split_vector(future) != expected_split)
        # Check target values wherever the future source is inside this
        # partition. Task 10 must additionally supply cross-partition joins.
        source_names=[name for name in V03_TARGET_COLUMNS if name in f]
        future_source=f[["grid_id","date",*source_names]].copy()
        future_source["date"]-=pd.Timedelta(days=horizon)
        future_source["_source_present"]=True
        future_source=f[["grid_id","date"]].merge(future_source,on=["grid_id","date"],how="left",sort=False)
        present=future_source["_source_present"].eq(True) & ~embargo
        date_name, flag = f"target_date_{horizon}d", f"target_embargo_{horizon}d"
        if date_name not in f or flag not in f:
            p["blocking_issues"].append("missing target family")
        else:
            actual = pd.to_datetime(f[date_name], errors="coerce")
            p["target_violation_count"] += int(((~embargo & ~actual.eq(future)) | (embargo & actual.notna()) | ~f[flag].eq(embargo.astype(int))).sum())
        for source,prefix in V03_TARGET_COLUMNS.items():
            name=f"{prefix}_{horizon}d"
            if name not in f:
                p["blocking_issues"].append("missing target family"); continue
            p["target_counts"][name] = {"nonnull":int(f[name].notna().sum()), "tail_null":int((tail & f[name].isna()).sum()), "embargo_nonnull":int((embargo & f[name].notna()).sum())}
            p["target_violation_count"] += p["target_counts"][name]["embargo_nonnull"]
            if source=="bloom_risk_level":
                valid=f[name].isna() | f[name].isin(("none","low","medium","high","severe","unknown"))
            elif source=="bloom_label":
                valid=f[name].isna() | f[name].isin((0,1))
            else:
                target_values=pd.to_numeric(f[name],errors="coerce")
                lower,upper=V03_RANGE_RULES[source]
                valid=f[name].isna() | (target_values.ge(lower) & target_values.le(upper))
            p["target_violation_count"]+=int((~valid).sum())
            if source in source_names and not p["duplicate_primary_keys"]:
                expected=future_source[source]
                matches=(f[name].isna() & expected.isna()) | f[name].eq(expected).fillna(False)
                p["target_violation_count"]+=int((present & ~matches).sum())
    for name in ("available_time", "feature_max_available_time", "mechanism_driver_cutoff_time"):
        if name in f:
            if "issue_time" not in f:
                p["leakage_count"] += int(f[name].notna().sum())
            else:
                available=pd.to_datetime(f[name],errors="coerce"); issue=pd.to_datetime(f.issue_time,errors="coerce")
                p["leakage_count"] += int((f[name].notna() & (available.isna() | issue.isna() | available.gt(issue))).sum())
    numeric = [c for c in V03_RANGE_RULES if c in f]
    # Every numeric output is checked for infinity, including features/targets
    # outside the bounded continuous-variable histogram contract.
    for name in f.select_dtypes(include=[np.number]).columns:
        if name not in numeric:
            p["nonfinite_count"]+=int(np.isinf(f[name].to_numpy(dtype=float,na_value=np.nan)).sum())
    for name in numeric:
        values = pd.to_numeric(f[name],errors="coerce").to_numpy(dtype=float,na_value=np.nan)
        p["nonfinite_count"] += int(np.isinf(values).sum() + (f[name].notna().to_numpy() & np.isnan(values)).sum())
        lower,upper=V03_RANGE_RULES[name]
        p["invalid_range_count"] += int(((values<lower)|(values>upper)).sum())
        p["numeric_stats"][name] = _numeric_summary(values,V03_RANGE_RULES[name])
    # A group loop is bounded by grid count, never a Python loop over rows.
    for grid,group in f.groupby("grid_id",sort=True,observed=True):
        first,last=group.date.iloc[0],group.date.iloc[-1]
        contiguous = not group.date.duplicated().any() and len(group)==(last-first).days+1
        p["key_intervals"].append({"grid_id":grid,"start":str(first.date()),"end":str(last.date()),"count":len(group),"contiguous":bool(contiguous)})
        if not contiguous: p["blocking_issues"].append("non-contiguous partition keys")
        summaries={}
        consecutive=group.date.diff().eq(pd.Timedelta(days=1)).to_numpy()[1:]
        for name in numeric:
            values=pd.to_numeric(group[name],errors="coerce").to_numpy(dtype=float,na_value=np.nan)
            summaries[name]={"run":_run_summary(values),"lag":_lag_stats(values[:-1][consecutive],values[1:][consecutive])}
        p["grid_summaries"][grid]=summaries
        block_columns=[c for c in RANGE_RULES if c in group and c not in V03_BOUNDARY_EXEMPT]
        if block_columns:
            for frequency in ("M","Y"):
                for period,block in group.groupby(group.date.dt.to_period(frequency),sort=True):
                    p["temporal_blocks"].append({"grid_id":grid,"frequency":frequency,"period":str(period),
                        "start":str(block.date.iloc[0].date()),"end":str(block.date.iloc[-1].date()),
                        "count":len(block),"hash":_sequence_hash(block[block_columns])})
    _profile_issues(p)
    p["summary_sha256"]=_digest(p)
    return p


def _profile_issues(p):
    issues=list(p["blocking_issues"])
    for name,label in _COUNT_ISSUES.items():
        if p.get(name,0): issues.append(label)
    p["boundary_pileup_rates"]={name:s["boundary_count"]/s["count"] for name,s in p["numeric_stats"].items() if s["count"]}
    if any(rate>=V03_THRESHOLDS["boundary_pileup_max"] for name,rate in p["boundary_pileup_rates"].items() if name not in V03_BOUNDARY_EXEMPT): issues.append("boundary pileup")
    if "longest_constant_runs" not in p:
        p["longest_constant_runs"]={name:max((g[name]["run"]["max"] for g in p["grid_summaries"].values()),default=0) for name in p["numeric_stats"]}
    if any(count>V03_THRESHOLDS["constant_run_max_days"] for name,count in p["longest_constant_runs"].items() if name not in V03_BOUNDARY_EXEMPT): issues.append("long constant run")
    p["blocking_issues"]=sorted(set(issues));p["status"]="FAIL" if issues else "PASS"


def _merge_stats(rows,bounds):
    n=sum(s["count"] for s in rows)
    total=math.fsum(s["sum"] for s in rows);mean=total/n if n else 0.
    result={"count":n,"sum":total,"sumsq":math.fsum(s["sumsq"] for s in rows),"mean":mean,
            "m2":math.fsum(s["m2"]+s["count"]*(s["mean"]-mean)**2 for s in rows),
            "min":min((s["min"] for s in rows if s["count"]),default=None),
            "max":max((s["max"] for s in rows if s["count"]),default=None),
            "boundary_count":sum(s["boundary_count"] for s in rows),
            "histogram":np.asarray([s["histogram"] for s in rows],dtype=np.int64).sum(axis=0).tolist()}
    _add_quantiles(result,bounds);return result


def combine_partition_profiles(profiles,config):
    """Consume summaries only; canonicalize partition order and audit exact keys.

    Registry: O(P*G) continuous grid/date intervals, not O(total grid-days).
    Overlap multiplicity is computed from integer interval endpoints exactly.
    Noncontiguous partitions fail closed and are not granted exact coverage.
    Hashes of canonical ordered leaves require a fixed partition layout for
    seed comparisons; they are not claimed invariant under repartitioning.
    """
    identity=_config_identity(config);rows=list(profiles)
    if not rows: raise ValueError("empty partition summaries")
    try:
        for p in rows:
            checksum=p["summary_sha256"]
            if p["schema_version"]!="partition-profile-v03-1" or p["config"]!=identity or p["threshold_sha256"]!=v03_threshold_sha256(): raise ValueError()
            if checksum!=_digest({k:v for k,v in p.items() if k!="summary_sha256"}): raise ValueError()
            if sum(i["count"] for i in p["key_intervals"])!=p["row_count"]: raise ValueError()
            if p["row_count"]<=0: raise ValueError()
        rows=sorted(rows,key=lambda p:(p["key_min"],p["key_max"],p["normalized_content_hash"],p["ordered_content_hash"]))
        if any(p["columns"]!=rows[0]["columns"] for p in rows): raise ValueError()
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        raise ValueError("malformed partition summary or incompatible schema/config") from exc
    report={"schema_version":"quality-report-v03-1","threshold_version":V03_THRESHOLD_VERSION,
            "threshold_sha256":v03_threshold_sha256(),"grid_day_count":sum(p["row_count"] for p in rows),
            "columns":list(rows[0]["columns"]),"blocking_issues":sorted(set(x for p in rows for x in p["blocking_issues"] if x not in ("boundary pileup","long constant run"))),
            "numeric_stats":{},"lag1":{},"longest_constant_runs":{},"target_counts":{},
            "normalized_content_hash":_digest([p["normalized_content_hash"] for p in rows]),
            "ordered_content_hash":_digest([p["ordered_content_hash"] for p in rows]),
            "partition_hashes":[p["normalized_content_hash"] for p in rows]}
    for key in _COUNT_ISSUES: report[key]=sum(p[key] for p in rows)
    for field in ("null_counts","label_state_counts","split_counts"):
        report[field]={key:sum(p[field].get(key,0) for p in rows) for key in sorted(set().union(*(p[field] for p in rows)))}
    for name in sorted(set().union(*(p["target_counts"] for p in rows))):
        report["target_counts"][name]={k:sum(p["target_counts"].get(name,{}).get(k,0) for p in rows) for k in ("nonnull","tail_null","embargo_nonnull")}
    registry=defaultdict(list)
    for p in rows:
        for interval in p["key_intervals"]: registry[interval["grid_id"]].append((interval,p))
    coverage={};union_dates=np.zeros(len(config.dates),dtype=bool)
    for grid,entries in sorted(registry.items()):
        entries.sort(key=lambda item:(item[0]["start"],item[0]["end"],item[1]["normalized_content_hash"]))
        covered=0;end=-1
        for interval,p in entries:
            if not interval["contiguous"]: continue
            first=(pd.Timestamp(interval["start"])-config.dates[0]).days;last=(pd.Timestamp(interval["end"])-config.dates[0]).days
            if interval["count"]!=last-first+1: raise ValueError("malformed interval proof")
            report["duplicate_primary_keys"]+=max(0,min(last,end)-first+1)
            covered+=max(0,last-max(end,first-1));end=max(end,last)
            union_dates[first:last+1]=True
        coverage[grid]=covered
    report.update(grid_count=len(registry),date_count=int(union_dates.sum()),
                  start_date=min(i["start"] for p in rows for i in p["key_intervals"]),
                  end_date=max(i["end"] for p in rows for i in p["key_intervals"]),
                  grid_date_count_min=min(coverage.values()),grid_date_count_max=max(coverage.values()),
                  calendar_gap_days=sum(len(config.dates)-v for v in coverage.values())+max(0,config.expected_grid_count-len(registry))*len(config.dates))
    if report["grid_day_count"]!=config.expected_grid_day_count: report["blocking_issues"].append("grid-day count")
    if report["grid_count"]!=config.expected_grid_count: report["blocking_issues"].append("grid count")
    if report["calendar_gap_days"]: report["blocking_issues"].append("date coverage")
    for name in rows[0]["numeric_stats"]:
        report["numeric_stats"][name]=_merge_stats([p["numeric_stats"][name] for p in rows],V03_RANGE_RULES[name])
        lag_parts=[];longest=0
        for grid,entries in sorted(registry.items()):
            prior=None;run=None
            for interval,p in entries:
                s=p["grid_summaries"][grid][name];lag_parts.append(s["lag"]);current=s["run"]
                adjacent=prior is not None and pd.Timestamp(interval["start"])-pd.Timestamp(prior["end"])==pd.Timedelta(days=1)
                if adjacent:
                    lag_parts.append(_lag_stats(np.array([run["last"]],dtype=float),np.array([current["first"]],dtype=float)))
                same=adjacent and run["last"] is not None and run["last"]==current["first"]
                joined=run["suffix"]+current["prefix"] if same else 0
                longest=max(longest,current["max"],joined)
                suffix=run["suffix"]+current["suffix"] if same and current["suffix"]==current["length"] else current["suffix"]
                run={**current,"suffix":suffix};prior=interval
        report["lag1"][name]={k:(sum(s[k] for s in lag_parts) if k=="count" else math.fsum(s[k] for s in lag_parts)) for k in ("count","sum_x","sum_y","sum_xx","sum_yy","sum_xy")}
        report["longest_constant_runs"][name]=longest
    blocks=defaultdict(list)
    for p in rows:
        for block in p["temporal_blocks"]: blocks[(block["grid_id"],block["frequency"],block["period"])].append(block)
    fingerprints=defaultdict(set);repeated=0
    for (grid,frequency,period),parts in sorted(blocks.items()):
        parts.sort(key=lambda b:b["start"]);value=0;count=0
        for part in parts:
            value=(value*pow(1000003,part["count"],2**64)+part["hash"])%(2**64);count+=part["count"]
        period_obj=pd.Period(period,freq=frequency)
        complete=(parts[0]["start"]==str(period_obj.start_time.date()) and parts[-1]["end"]==str(period_obj.end_time.date()) and count==(period_obj.end_time.normalize()-period_obj.start_time).days+1)
        if complete:
            fingerprint=(count,value);seen=fingerprints[(grid,frequency)]
            if fingerprint in seen: repeated+=1
            seen.add(fingerprint)
    report["repeated_temporal_block_count"]=repeated
    if repeated: report["blocking_issues"].append("repeated temporal block")
    _profile_issues(report)
    return report


def _finite_number(value):
    return isinstance(value,(int,float,np.integer,np.floating)) and not isinstance(value,(bool,np.bool_)) and math.isfinite(float(value))


def _hash_map(value):
    return isinstance(value,dict) and bool(value) and all(isinstance(k,str) and bool(k.strip()) and isinstance(v,str) and re.fullmatch(r"[0-9a-f]{64}",v) for k,v in value.items())


def check_seed_sensitivity(summaries,tolerances):
    """Require a repeated seed AND another seed, with distinct run identifiers.

    ``quantiles`` maps every tolerance variable to [q10,q50,q90] in that
    variable's native unit. At least one seed must have two independent runs.
    Different-seed comparisons are all-pairs, symmetric absolute+relative
    tolerance using max(abs(left),abs(right)). Tolerance values are explicit
    development choices; full release uses a nonempty core-variable contract.
    No boolean self-attestation is accepted by the package gate.
    """
    result={"same_seed_deterministic":False,"different_content_hashes":False,"distribution_stable":False,"blocking_issues":[]}
    issues=result["blocking_issues"]
    try:
        if not isinstance(tolerances,dict) or not tolerances: raise ValueError()
        for name,tol in tolerances.items():
            if not isinstance(name,str) or not name or set(tol)!={"atol","rtol"} or any(not _finite_number(v) or v<0 for v in tol.values()): raise ValueError()
        rows=list(summaries)
        if not rows: raise ValueError()
        for row in rows:
            if not isinstance(row["seed"],int) or isinstance(row["seed"],bool) or row["seed"]<0: raise ValueError()
            if not isinstance(row["replicate_id"],str) or not row["replicate_id"]: raise ValueError()
            if not _hash_map({"content":row["content_hash"]}): raise ValueError()
            for name in tolerances:
                q=row["quantiles"][name]
                if not isinstance(q,(list,tuple)) or len(q)!=3 or not all(_finite_number(v) for v in q) or list(q)!=sorted(q): raise ValueError()
        rows.sort(key=lambda r:(r["seed"],r["replicate_id"]))
        if len({(r["seed"],r["replicate_id"]) for r in rows})!=len(rows): raise ValueError()
    except (KeyError,TypeError,ValueError,OverflowError):
        issues.append("malformed seed evidence or tolerances");return result
    groups=defaultdict(list)
    for row in rows: groups[row["seed"]].append(row)
    if len(groups)<2: issues.append("missing different-seed replicate")
    if not any(len(g)>=2 for g in groups.values()): issues.append("missing same-seed replicate")
    same=all(len({r["content_hash"] for r in g})==1 and len({_digest(r["quantiles"]) for r in g})==1 for g in groups.values())
    result["same_seed_deterministic"]=same and any(len(g)>=2 for g in groups.values())
    if not same: issues.append("same-seed nondeterminism")
    different=True;stable=True;max_errors={name:0. for name in tolerances}
    for left,right in combinations(rows,2):
        if left["seed"]==right["seed"]: continue
        if left["content_hash"]==right["content_hash"]: different=False
        for name,tol in tolerances.items():
            a=np.asarray(left["quantiles"][name]);b=np.asarray(right["quantiles"][name]);delta=np.abs(a-b)
            allowed=tol["atol"]+tol["rtol"]*np.maximum(np.abs(a),np.abs(b))
            stable=stable and bool(np.all(delta<=allowed))
            max_errors[name]=max(max_errors[name],float(delta.max()))
    result["different_content_hashes"]=different and len(groups)>=2
    result["distribution_stable"]=stable and len(groups)>=2
    result["maximum_quantile_absolute_differences"]=max_errors
    if not different: issues.append("identical different-seed content")
    if not stable: issues.append("seed distribution drift")
    result["blocking_issues"]=sorted(set(issues));return result


def assert_v03_quality_gates(report):
    """Fail closed with sorted, aggregated gate names; never mutate evidence.

    The report schema combines measured partition statistics with mandatory
    whole-package measurements from Tasks 10/12. Numerical metrics require
    explicit units. Passing booleans cannot replace evidence. These are
    synthetic development checks, not environmental/regulatory standards.
    """
    if not isinstance(report,dict): raise ValueError("malformed quality report")
    issues=[]
    existing=report.get("blocking_issues")
    if not isinstance(existing,list) or not all(isinstance(v,str) for v in existing): issues.append("malformed blocking issues")
    else: issues.extend(existing)

    def fail(condition,name):
        if not condition: issues.append(name)

    def number(value,minimum=None,maximum=None,integer=False,strict_min=False,strict_max=False):
        return (_finite_number(value) and (not integer or float(value).is_integer())
                and (minimum is None or (value>minimum if strict_min else value>=minimum))
                and (maximum is None or (value<maximum if strict_max else value<=maximum)))

    def measurement(group,key,unit,minimum=None,maximum=None,integer=False,strict_min=False,strict_max=False):
        entry=group.get(key) if isinstance(group,dict) else None
        return (isinstance(entry,dict) and entry.get("unit")==unit
                and number(entry.get("value"),minimum,maximum,integer,strict_min,strict_max))

    fail(report.get("schema_version")=="quality-report-v03-1","report schema")
    fail(report.get("threshold_version")==V03_THRESHOLD_VERSION and report.get("threshold_sha256")==v03_threshold_sha256(),"threshold lineage")
    for name,want,label in (("grid_day_count",11658400,"grid-day count"),("grid_count",1520,"grid count"),
                            ("date_count",7670,"date coverage"),("grid_date_count_min",7670,"date coverage"),
                            ("grid_date_count_max",7670,"date coverage"),("calendar_gap_days",0,"date coverage")):
        fail(number(report.get(name),want,want,True),label)
    fail(report.get("start_date")=="2005-01-01" and report.get("end_date")=="2025-12-31","date coverage")
    for name,label in {**_COUNT_ISSUES,"invalid_geometry_count":"geometry","repeated_temporal_block_count":"repeated temporal block"}.items():
        # Local timestamp checks supplement mandatory external leakage evidence.
        if name=="leakage_count" and name not in report: continue
        fail(number(report.get(name),0,0,True),label)
    for name,threshold in (("boundary_pileup_rates",V03_THRESHOLDS["boundary_pileup_max"]),("longest_constant_runs",V03_THRESHOLDS["constant_run_max_days"])):
        values=report.get(name);label="boundary pileup" if name=="boundary_pileup_rates" else "long constant run"
        fail(isinstance(values,dict) and bool(values),label)
        fail(isinstance(values,dict) and set(V03_CORE_COLUMNS).issubset(values),label+" core evidence")
        if isinstance(values,dict):
            for column,value in values.items():
                fail(number(value,0,1 if name=="boundary_pileup_rates" else 7670, name!="boundary_pileup_rates"),label)
                if column not in V03_BOUNDARY_EXEMPT:
                    fail(number(value,0,threshold,strict_max=name=="boundary_pileup_rates"),label)
    targets=report.get("target_counts",{})
    expected_targets={f"{prefix}_{horizon}d" for prefix in V03_TARGET_COLUMNS.values() for horizon in _HORIZONS}
    fail(isinstance(targets,dict) and set(targets)==expected_targets,"missing target family")
    if isinstance(targets,dict):
        for name in sorted(expected_targets):
            value=targets.get(name,{});horizon=int(name.rsplit("_",1)[1][:-1])
            fail(isinstance(value,dict) and number(value.get("nonnull"),1,11658400,True)
                 and number(value.get("tail_null"),1520*horizon,1520*horizon,True)
                 and number(value.get("embargo_nonnull"),0,0,True),"target counts/tail/embargo")
    split_metrics=report.get("split_metrics",{})
    for split in _SPLITS:
        metrics=split_metrics.get(split,{}) if isinstance(split_metrics,dict) else {}
        for key,threshold in (("positive_lake_days",30),("negative_lake_days",90),("positive_grid_days",1000),("positive_processes",2),("negative_processes",2)):
            fail(isinstance(metrics,dict) and number(metrics.get(key),threshold,11658400,True),f"split minimum {split}/{key}")
        if isinstance(metrics,dict):
            days=4748 if split=="train" else 1461
            positive,negative=metrics.get("positive_lake_days"),metrics.get("negative_lake_days")
            fail(number(positive,0,days,True) and number(negative,0,days,True)
                 and positive+negative<=days,"split day counts "+split)
            fail(number(metrics.get("positive_grid_days"),0,days*1520,True),"split grid counts "+split)
    task_counts=report.get("task_usable_counts",{})
    expected_tasks={f"{task}_{h}d" for task in ("mechanism","xgboost","hybrid") for h in _HORIZONS}
    fail(isinstance(task_counts,dict) and set(task_counts)==expected_tasks,"task schema")
    for task in sorted(expected_tasks):
        fail(isinstance(task_counts,dict) and number(task_counts.get(task),10000,11658400,True),"task minimum "+task)
    seed=check_seed_sensitivity(report.get("seed_summaries"),report.get("seed_tolerances"))
    fail(report.get("seed_tolerances")==default_seed_tolerances(),"seed tolerance/core schema")
    issues.extend(seed["blocking_issues"])
    for key in ("late_features","future_weather","nontrain_fit_rows","resampled_test_rows","latent_features","late_mechanism_drivers","cross_partition_target_mismatches"):
        fail(measurement(report.get("leakage"),key,"count",0,0,True),"leakage "+key)
    anchors=report.get("anchor_metrics",{})
    for name in V03_CORE_COLUMNS[1:]:
        group=anchors.get(name) if isinstance(anchors,dict) else None
        for key,unit,minimum,maximum in (("seasonal_median_relative_error","ratio",0,.5),
             ("quantile_relative_error","ratio",0,.75),("extreme_relative_error","ratio",0,2.),
             ("zone_rank_correlation","correlation",.3,1.),("fit_end_year","year",2005,2017),
             ("anchor_count","count",10,None)):
            fail(measurement(group,key,unit,minimum,maximum,unit in ("year","count")),"anchor "+name+"/"+key)
    for key in ("temperature","low_wind","light","nutrients"):
        fail(measurement(report.get("directionality"),key,"spearman",0,.98,strict_min=True,strict_max=True),"directionality "+key)
    fail(measurement({"v":report.get("mechanical_correlation")},"v","absolute_correlation",0,.999,strict_max=True),"mechanical correlation")
    for key,unit,minimum,maximum in (("moran_i","dimensionless",.02,.98),("neighbor_correlation","correlation",.02,.98),("correlation_length","m",1000.,50000.)):
        fail(measurement(report.get("spatial"),key,unit,minimum,maximum,strict_min=True,strict_max=True),"spatial "+key)
    fail(measurement(report.get("transport"),"minimum_biomass","mg_L",0,None),"transport nonnegative")
    fail(measurement(report.get("transport"),"max_relative_mass_error","ratio",0,1e-8,strict_max=True),"transport conservation")
    fail(measurement(report.get("transport"),"step_count","count",1,None,True),"transport steps")
    columns=report.get("columns");metadata=report.get("field_metadata")
    fail(isinstance(columns,list) and bool(columns) and all(isinstance(c,str) and c for c in columns)
         and len(set(columns))==len(columns) and isinstance(metadata,dict) and set(metadata)==set(columns),"field metadata schema")
    fail(isinstance(columns,list) and all(isinstance(c,str) for c in columns)
         and set(V03_CORE_COLUMNS).union(expected_targets).issubset(columns),"required core/target columns")
    if isinstance(metadata,dict):
        for name,entry in metadata.items():
            fail(isinstance(entry,dict) and all(isinstance(entry.get(k),str) and entry[k].strip() for k in ("unit","role","source_category","allowed_claim"))
                 and entry.get("allowed_claim")=="synthetic_development_only","field metadata "+str(name))
            if isinstance(entry,dict) and entry.get("role")=="feature":
                fail(name in v03_feature_allowlist(),"feature allowlist")
            if name in V03_REQUIRED_UNITS:
                fail(isinstance(entry,dict) and entry.get("unit")==V03_REQUIRED_UNITS[name],"field unit "+name)
    before,after,outputs=(report.get(k) for k in ("source_hashes_before","source_hashes_after","output_hashes"))
    fail(_hash_map(before) and _hash_map(after) and before==after,"source hashes/unchanged originals")
    fail(_hash_map(outputs),"output hashes")
    manifest=report.get("manifest")
    if not isinstance(manifest,dict): issues.append("manifest lineage")
    else:
        fail(manifest.get("input_hashes")==before and _hash_map(manifest.get("input_hashes")),"manifest input hashes")
        fail(manifest.get("partition_hashes")==outputs and _hash_map(manifest.get("partition_hashes")),"manifest partition hashes")
        fail(isinstance(manifest.get("seed_tree"),dict) and bool(manifest["seed_tree"]),"manifest seed tree")
        fail(isinstance(manifest.get("code_version"),str) and bool(manifest["code_version"].strip()),"manifest code version")
        config=manifest.get("config")
        fail(isinstance(config,dict) and config.get("start_date")=="2005-01-01" and config.get("end_date")=="2025-12-31"
             and config.get("expected_grid_count")==1520 and config.get("horizons")==list(_HORIZONS),"manifest config")
    if issues: raise ValueError("; ".join(sorted(set(issues))))
