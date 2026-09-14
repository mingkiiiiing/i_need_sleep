"""Non-destructively extend a verified V0.3 package with T+60/T+90 targets."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import pandas as pd

from .config import GridSimulationConfig, GridSimulationConfigV04
from .forecast import V03_TARGET_COLUMNS, build_v04_forecast_samples
from .lineage import sha256_file
from .pipeline_v03 import (
    _atomic_write_json,
    _atomic_write_parquet,
    _atomic_write_text,
    _digest,
    _read_json,
    verify_v03_package,
)
from .quality import profile_partition_v03, profile_v04_long_horizons


LONG_HORIZONS = (60, 90)
ALL_HORIZONS = (1, 3, 7, 15, 30, 60, 90)


def _config_from_manifest(manifest: dict, cls):
    try:
        return cls(
            base_seed=int(manifest["base_seed"]),
            start_date=str(manifest["start_date"]),
            end_date=str(manifest["end_date"]),
            expected_grid_count=int(manifest["expected_grid_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("source manifest configuration is invalid") from exc


def _partition_registry(partition_hashes: dict[str, str]) -> dict[tuple[int, str], str]:
    registry = {}
    for relative in partition_hashes:
        parts = Path(relative).parts
        try:
            year_part = next(part for part in parts if part.startswith("year="))
            zone_part = next(
                part for part in parts if part.startswith("experimental_zone_id=")
            )
            year = int(year_part.split("=", 1)[1])
            zone = zone_part.split("=", 1)[1]
        except (StopIteration, ValueError) as exc:
            raise ValueError(f"invalid V0.3 partition path: {relative}") from exc
        key = (year, zone)
        if key in registry:
            raise ValueError(f"duplicate V0.3 partition registry key: {key}")
        registry[key] = relative
    return registry


def _long_target_columns() -> tuple[str, ...]:
    columns = []
    for horizon in LONG_HORIZONS:
        columns.extend(
            [
                f"target_embargo_{horizon}d",
                f"target_date_{horizon}d",
                *(f"{prefix}_{horizon}d" for prefix in V03_TARGET_COLUMNS.values()),
            ]
        )
    return tuple(columns)


def _extend_partition(
    source: Path,
    relative: str,
    next_relative: str | None,
    config: GridSimulationConfigV04,
) -> pd.DataFrame:
    current = pd.read_parquet(source / relative)
    lookup_columns = ["grid_id", "date", *V03_TARGET_COLUMNS]
    lookup = current.loc[:, lookup_columns].copy()
    if next_relative is not None:
        following = pd.read_parquet(source / next_relative, columns=lookup_columns)
        cutoff = pd.to_datetime(current["date"]).max() + pd.Timedelta(days=max(LONG_HORIZONS))
        following = following.loc[pd.to_datetime(following["date"]).le(cutoff)]
        lookup = pd.concat([lookup, following], ignore_index=True)

    forecast = build_v04_forecast_samples(lookup, config)
    target_columns = list(_long_target_columns())
    aligned = current.loc[:, ["grid_id", "date"]].merge(
        forecast.loc[:, ["grid_id", "date", *target_columns]],
        on=["grid_id", "date"],
        how="left",
        sort=False,
        validate="one_to_one",
    )
    extended = current.copy(deep=True)
    for column in target_columns:
        extended[column] = aligned[column].array
    return extended


def _aggregate_profiles(profiles: list[tuple[str, dict]]) -> dict:
    if not profiles:
        raise ValueError("V0.4 extension produced no partition profiles")
    columns = profiles[0][1]["columns"]
    if any(profile["columns"] != columns for _, profile in profiles):
        raise ValueError("V0.4 partition schemas disagree")
    horizon_counts = {
        f"{horizon}d": {
            split: {
                "rows": 0,
                "eligible": 0,
                "embargoed": 0,
                "target_nonnull": {prefix: 0 for prefix in V03_TARGET_COLUMNS.values()},
            }
            for split in ("train", "validation", "test")
        }
        for horizon in LONG_HORIZONS
    }
    split_counts = {split: 0 for split in ("train", "validation", "test")}
    for _, profile in profiles:
        for split, count in profile["split_counts"].items():
            split_counts[split] += int(count)
        for horizon, split_rows in profile["horizon_counts"].items():
            for split, values in split_rows.items():
                destination = horizon_counts[horizon][split]
                for key in ("rows", "eligible", "embargoed"):
                    destination[key] += int(values[key])
                for target, count in values["target_nonnull"].items():
                    destination["target_nonnull"][target] += int(count)
    blocking = sorted(
        set(
            issue
            for _, profile in profiles
            for issue in profile.get("blocking_issues", [])
        )
    )
    violations = sum(
        int(profile.get("target_violation_count", 0)) for _, profile in profiles
    )
    return {
        "schema_version": "quality-report-v04-1",
        "status": "FAIL" if blocking or violations else "PASS",
        "quality_status": "FAIL" if blocking or violations else "PASS",
        "blocking_issues": blocking,
        "target_violation_count": violations,
        "grid_day_count": sum(int(profile["row_count"]) for _, profile in profiles),
        "column_count": len(columns),
        "columns": columns,
        "partition_count": len(profiles),
        "split_counts": split_counts,
        "horizon_counts": horizon_counts,
        "partition_hashes": {
            relative: profile["normalized_content_hash"]
            for relative, profile in profiles
        },
        "normalized_content_hash": _digest(
            [profile["normalized_content_hash"] for _, profile in profiles]
        ),
    }


def _v04_metadata(source: Path, profiles: list[tuple[str, dict]]) -> tuple[dict, dict, dict]:
    source_ready = _read_json(source / "READY.json")
    source_manifest = _read_json(source / "generation_manifest_V0.3.json")
    report = _aggregate_profiles(profiles)
    report["data_version"] = "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4"
    report["generator_version"] = "V0.4"
    report["claim_boundary"] = "synthetic_development_only"
    report["horizons"] = list(ALL_HORIZONS)
    report["source_v03_ready_sha256"] = sha256_file(source / "READY.json")
    report["source_v03_canonical_data_hash"] = source_ready["canonical_data_hash"]

    manifest = {
        "data_version": report["data_version"],
        "generator_version": report["generator_version"],
        "claim_boundary": report["claim_boundary"],
        "base_seed": source_manifest["base_seed"],
        "start_date": source_manifest["start_date"],
        "end_date": source_manifest["end_date"],
        "expected_grid_count": source_manifest["expected_grid_count"],
        "horizons": list(ALL_HORIZONS),
        "row_count": report["grid_day_count"],
        "column_count": report["column_count"],
        "partition_count": report["partition_count"],
        "canonical_data_hash": report["normalized_content_hash"],
        "partition_hashes": report["partition_hashes"],
        "source_v03_ready_sha256": report["source_v03_ready_sha256"],
        "source_v03_canonical_data_hash": report["source_v03_canonical_data_hash"],
        "source_v03_partition_hashes": source_manifest["partition_hashes"],
        "quality_report_sha256": _digest(report),
    }
    ready = {
        "data_version": manifest["data_version"],
        "generator_version": manifest["generator_version"],
        "base_seed": manifest["base_seed"],
        "canonical_data_hash": manifest["canonical_data_hash"],
        "manifest_sha256": _digest(manifest),
        "quality_report_sha256": _digest(report),
        "row_count": manifest["row_count"],
        "column_count": manifest["column_count"],
        "partition_count": manifest["partition_count"],
        "claim_boundary": manifest["claim_boundary"],
        "horizons": list(ALL_HORIZONS),
        "source_v03_ready_sha256": manifest["source_v03_ready_sha256"],
    }
    return report, manifest, ready


def _require_same(field: str, *values) -> None:
    if not values or any(value != values[0] for value in values[1:]):
        raise ValueError(f"V0.4 metadata mismatch: {field}")


def verify_v04_package(
    source_v03: str | Path,
    output_v04: str | Path,
    *,
    verify_source: bool = True,
) -> dict[str, object]:
    """Read and independently verify a V0.4 package and its V0.3 parent."""
    source = Path(source_v03)
    output = Path(output_v04)
    if verify_source:
        verify_v03_package(source)
    ready = _read_json(output / "READY.json")
    manifest = _read_json(output / "generation_manifest_V0.4.json")
    report = _read_json(output / "data_quality_report_V0.4.json")
    if _digest(manifest) != ready.get("manifest_sha256"):
        raise ValueError("V0.4 manifest digest mismatch")
    if _digest(report) != ready.get("quality_report_sha256"):
        raise ValueError("V0.4 quality report digest mismatch")
    if _digest(report) != manifest.get("quality_report_sha256"):
        raise ValueError("V0.4 manifest/report digest mismatch")
    if sha256_file(source / "READY.json") != ready.get("source_v03_ready_sha256"):
        raise ValueError("V0.4 parent V0.3 digest mismatch")
    for field in (
        "data_version",
        "generator_version",
        "base_seed",
        "canonical_data_hash",
        "row_count",
        "column_count",
        "partition_count",
        "claim_boundary",
        "horizons",
    ):
        _require_same(field, ready.get(field), manifest.get(field))
    if ready.get("data_version") != "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4":
        raise ValueError("unexpected V0.4 data version")
    if ready.get("horizons") != list(ALL_HORIZONS):
        raise ValueError("unexpected V0.4 horizon contract")
    if ready.get("claim_boundary") != "synthetic_development_only":
        raise ValueError("invalid V0.4 claim boundary")

    source_manifest = _read_json(source / "generation_manifest_V0.3.json")
    source_report = _read_json(source / "data_quality_report_V0.3.json")
    v03_config = _config_from_manifest(source_manifest, GridSimulationConfig)
    v04_config = _config_from_manifest(manifest, GridSimulationConfigV04)
    expected_paths = manifest.get("partition_hashes")
    if not isinstance(expected_paths, dict) or not expected_paths:
        raise ValueError("V0.4 partition registry is missing")
    actual_paths = sorted(
        str(path.relative_to(output))
        for path in (output / "partitions").rglob("*.parquet")
    )
    if set(actual_paths) != set(expected_paths):
        raise ValueError("V0.4 partition paths do not match manifest")

    base_columns = source_report["columns"]
    source_hashes = source_manifest["partition_hashes"]
    profiles = []
    for relative in actual_paths:
        frame = pd.read_parquet(output / relative)
        missing_base = sorted(set(base_columns) - set(frame.columns))
        if missing_base:
            raise ValueError(f"V0.4 partition lost V0.3 columns: {relative}")
        base_profile = profile_partition_v03(frame.loc[:, base_columns], v03_config)
        if base_profile["normalized_content_hash"] != source_hashes.get(relative):
            raise ValueError(f"V0.4 changed V0.3 values: {relative}")
        profile = profile_v04_long_horizons(frame, v04_config)
        if profile["normalized_content_hash"] != expected_paths[relative]:
            raise ValueError(f"V0.4 partition content hash mismatch: {relative}")
        if profile["status"] != "PASS":
            raise ValueError(f"V0.4 partition quality failed: {relative}")
        profiles.append((relative, profile))

    recomputed = _aggregate_profiles(profiles)
    for field in (
        "status",
        "quality_status",
        "blocking_issues",
        "target_violation_count",
        "grid_day_count",
        "column_count",
        "columns",
        "partition_count",
        "split_counts",
        "horizon_counts",
        "partition_hashes",
        "normalized_content_hash",
    ):
        _require_same(f"recomputed {field}", recomputed.get(field), report.get(field))
    if recomputed["status"] != "PASS":
        raise ValueError("recomputed V0.4 quality status is not PASS")
    return {
        "status": "PASS",
        "data_version": ready["data_version"],
        "horizons": ready["horizons"],
        "row_count": int(ready["row_count"]),
        "column_count": int(ready["column_count"]),
        "partition_count": int(ready["partition_count"]),
        "canonical_data_hash": ready["canonical_data_hash"],
        "claim_boundary": ready["claim_boundary"],
    }


def extend_v03_package(
    source_v03: str | Path, output_v04: str | Path
) -> dict[str, object]:
    """Create and verify an immutable V0.4 sibling without modifying V0.3."""
    source = Path(source_v03).resolve()
    output = Path(output_v04).resolve()
    if source == output or source in output.parents:
        raise ValueError("V0.4 output must not be inside the immutable V0.3 source")
    if output.exists():
        raise FileExistsError(f"immutable V0.4 output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".{output.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    temporary.mkdir()

    verify_v03_package(source)
    source_manifest = _read_json(source / "generation_manifest_V0.3.json")
    config = _config_from_manifest(source_manifest, GridSimulationConfigV04)
    partition_hashes = source_manifest["partition_hashes"]
    registry = _partition_registry(partition_hashes)
    profiles = []
    for (year, zone), relative in sorted(registry.items()):
        next_relative = registry.get((year + 1, zone))
        extended = _extend_partition(source, relative, next_relative, config)
        profile = profile_v04_long_horizons(extended, config)
        if profile["status"] != "PASS":
            raise ValueError(
                f"V0.4 partition quality failed before publication: {relative}"
            )
        destination = temporary / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_parquet(extended, destination)
        profiles.append((relative, profile))

    report, manifest, ready = _v04_metadata(source, profiles)
    if report["status"] != "PASS":
        raise ValueError("V0.4 aggregate quality failed before publication")
    _atomic_write_json(report, temporary / "data_quality_report_V0.4.json")
    _atomic_write_json(manifest, temporary / "generation_manifest_V0.4.json")
    _atomic_write_text(
        "# Known Limitations V0.4\n\n"
        "V0.4 only extends the verified synthetic V0.3 package with exact-date "
        "T+60/T+90 targets. It remains synthetic development data and does not "
        "establish real Taihu operational accuracy.\n",
        temporary / "known_limitations_V0.4.md",
    )
    _atomic_write_json(ready, temporary / "READY.json")
    result = verify_v04_package(source, temporary, verify_source=False)
    temporary.replace(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Extend verified V0.3 data to V0.4")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_only:
            result = verify_v04_package(args.source, args.output)
        else:
            result = extend_v03_package(args.source, args.output)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
