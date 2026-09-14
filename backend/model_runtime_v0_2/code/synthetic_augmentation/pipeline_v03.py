"""Partitioned V0.3 pilot/full generation pipeline.

The pipeline deliberately keeps generated rows in Parquet partitions and never
materialises the full 2005-2025 grid-day table in memory.  Yearly generation
carries immutable driver/water-quality/mechanism states across block
boundaries, while forecast targets are resolved with a one-year look-ahead so
cross-year rows inside the same split are not mislabelled as embargoed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import GridSimulationConfig, SimulationConfig
from .drivers import DriverState, generate_driver_block
from .forecast import build_v03_forecast_samples
from .grid import build_adjacency, build_grid_metadata, load_experimental_grid
from .lineage import build_lineage, lineage_record, sha256_file
from .mechanism import MechanismState, advance_biomass
from .observation import apply_observation_process
from .quality import combine_partition_profiles, profile_partition_v03
from .random_streams import ComponentCode, make_rng
from .sources import build_anchor_registry, load_nasa_power, profile_training_anchors
from .targets import build_bloom_labels, build_latent_targets
from .transport import TransportConfig, transport_step
from .water_quality import WaterQualityState, generate_water_quality_block


OBSERVATION_RAW_COLUMNS = (
    "remote_chlorophyll_a_ug_L",
    "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L",
    "remote_fai_proxy",
    "remote_ndci_proxy",
)
OBSERVATION_EXTRA_COLUMNS = (
    "cloud_fraction",
    "remote_chlorophyll_a_detection_limit_ug_L",
    "remote_phycocyanin_detection_limit_ug_L",
    "remote_cyanobacteria_density_detection_limit_cells_L",
    "remote_fai_detection_limit",
    "remote_ndci_detection_limit",
)
LATENT_TARGET_COLUMNS = (
    "blue_algae_biomass_mg_L",
    "chlorophyll_a_ug_L",
    "phycocyanin_ug_L",
    "cyanobacteria_density_cells_L",
    "latent_bloom_probability",
    "latent_bloom_event",
)


@dataclass(frozen=True)
class BlockState:
    last_date: pd.Timestamp
    grid_ids: tuple[str, ...]
    driver: DriverState | None
    water_quality: WaterQualityState | None
    mechanism: MechanismState | None


def canonical_frame_hash(frame: pd.DataFrame, key_columns: tuple[str, ...]) -> str:
    """Return a deterministic row-order-normalised content hash."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("canonical_frame_hash requires a non-empty DataFrame")
    keys = list(key_columns)
    missing = sorted(set(keys) - set(frame.columns))
    if missing:
        raise ValueError(f"canonical hash key columns missing: {missing}")
    ordered = frame.copy(deep=True)
    for column in keys:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].dt.strftime("%Y-%m-%d")
        else:
            ordered[column] = ordered[column].astype(str)
    ordered = ordered.sort_values(keys, kind="mergesort").reset_index(drop=True)
    ordered = ordered.reindex(sorted(ordered.columns), axis=1)
    digest = hashlib.sha256()
    for column in ordered.columns:
        digest.update(column.encode("utf-8"))
        digest.update(b"\x00")
        values = pd.util.hash_pandas_object(ordered[column], index=False)
        digest.update(values.to_numpy(np.uint64).tobytes())
        digest.update(b"\xff")
    return digest.hexdigest()


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _state_payload(state) -> dict[str, object] | None:
    if state is None:
        return None
    if isinstance(state, DriverState):
        return {
            "kind": "driver",
            "last_date": str(state.last_date.date()),
            "grid_ids": list(state.grid_ids),
            "rainfall_memory": list(state.rainfall_memory),
            "air_micro": list(state.air_micro),
            "water_temperature": list(state.water_temperature),
            "water_level": list(state.water_level),
            "flow_speed": list(state.flow_speed),
            "mixing_index": list(state.mixing_index),
        }
    if isinstance(state, WaterQualityState):
        return {
            "kind": "water_quality",
            "last_date": str(state.last_date.date()),
            "grid_ids": list(state.grid_ids),
            "transformed_values": [list(row) for row in state.transformed_values],
        }
    if isinstance(state, MechanismState):
        return {
            "kind": "mechanism",
            "last_date": str(state.last_date.date()),
            "grid_ids": list(state.grid_ids),
            "biomass_mg_L": list(state.biomass_mg_L),
        }
    raise ValueError(f"unsupported block state type: {type(state)!r}")


def _validate_inputs(inputs: dict) -> None:
    required = {"grid", "weather", "anchor_paths", "train_end"}
    missing = sorted(required - set(inputs))
    if missing:
        raise ValueError(f"pipeline inputs missing keys: {missing}")
    grid_path = Path(inputs["grid"])
    weather_path = Path(inputs["weather"])
    if not grid_path.is_file():
        raise FileNotFoundError(f"grid source missing: {grid_path}")
    if not weather_path.is_file():
        raise FileNotFoundError(f"weather source missing: {weather_path}")
    anchors = inputs["anchor_paths"]
    if not isinstance(anchors, dict) or not anchors:
        raise ValueError("anchor_paths must be a non-empty mapping")


def _canonical_input_map(inputs: dict) -> dict[str, Path]:
    result = {"grid": Path(inputs["grid"]), "weather": Path(inputs["weather"])}
    for asset, path in inputs["anchor_paths"].items():
        result[f"anchor:{asset}"] = Path(path)
    return result


def _hash_inputs(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256_file(path) for name, path in sorted(paths.items())}


def _validate_source_hash_equality(before: dict[str, str], after: dict[str, str]) -> None:
    if before != after:
        changed = sorted(set(before) | set(after))
        raise ValueError(f"source files changed during generation: {changed}")


def _load_generation_inputs(
    inputs: dict, config: GridSimulationConfig, weather_full_config: SimulationConfig
):
    grid = load_experimental_grid(Path(inputs["grid"]), GridSimulationConfig())
    if len(grid) != config.expected_grid_count:
        if config.expected_grid_count <= 0 or config.expected_grid_count > len(grid):
            raise ValueError(
                f"config expected_grid_count={config.expected_grid_count} is incompatible with {len(grid)} source grids"
            )
        grid = grid.iloc[: config.expected_grid_count].copy()
        grid["grid_numeric_id"] = np.arange(len(grid), dtype=np.int64)
    weather = load_nasa_power(Path(inputs["weather"]), weather_full_config)
    metadata = build_grid_metadata(grid, config)
    adjacency = build_adjacency(grid)
    coordinates = metadata.loc[:, ["centroid_x_m", "centroid_y_m"]].to_numpy(dtype=float)
    return grid, weather, metadata, adjacency, coordinates


def _merge_ordered_columns(target: pd.DataFrame, source: pd.DataFrame, columns: tuple[str, ...]) -> None:
    """Copy same-ordered source columns into target without an expensive merge."""
    for column in columns:
        if column not in source.columns:
            raise ValueError(f"source frame missing required column: {column}")
        target[column] = source[column].to_numpy()


def _generate_block(
    dates: pd.DatetimeIndex,
    config: GridSimulationConfig,
    metadata: pd.DataFrame,
    adjacency,
    coordinates: np.ndarray,
    weather: pd.DataFrame,
    anchor_profile: dict,
    previous: BlockState | None,
) -> tuple[pd.DataFrame, BlockState]:
    year = int(dates[0].year)
    driver_block, driver_state = generate_driver_block(
        dates, metadata, weather, None if previous is None else previous.driver, config
    )
    water_block, water_state = generate_water_quality_block(
        driver_block,
        anchor_profile,
        None if previous is None else previous.water_quality,
        config,
    )

    mechanism_input = driver_block.copy()
    _merge_ordered_columns(
        mechanism_input,
        water_block,
        tuple(
            name
            for name in water_block.columns
            if name not in mechanism_input.columns
            or name
            in {
                "total_phosphorus_mg_L",
                "total_nitrogen_mg_L",
                "dissolved_oxygen_mg_L",
                "ph",
                "phytoplankton_biomass_mg_L",
            }
        ),
    )
    mechanism_rng = make_rng(config, ComponentCode.MECHANISM, year, 0, 0)
    mechanism_block, mechanism_state = advance_biomass(
        mechanism_input,
        None if previous is None else previous.mechanism,
        mechanism_rng,
    )

    grid_ids = tuple(metadata["grid_id"].astype(str))
    width = len(grid_ids)
    if len(mechanism_block) != len(dates) * width:
        raise ValueError("mechanism block row count does not match date-grid contract")
    final_biomass = np.asarray(mechanism_state.biomass_mg_L, dtype=float)
    transport = TransportConfig()
    for day_index, date in enumerate(dates):
        start = day_index * width
        stop = start + width
        day_rows = driver_block.iloc[start:stop]
        wind_speed = day_rows["wind_speed_m_s"].to_numpy(dtype=float)
        wind_direction = day_rows["wind_direction_deg"].to_numpy(dtype=float)
        radians = np.deg2rad(wind_direction)
        wind_u = wind_speed * np.cos(radians)
        wind_v = wind_speed * np.sin(radians)
        transported = transport_step(
            mechanism_block.loc[start:stop - 1, "blue_algae_biomass_mg_L"].to_numpy(dtype=float),
            coordinates,
            adjacency,
            wind_u,
            wind_v,
            transport,
        )
        mechanism_block.loc[start:stop - 1, "blue_algae_biomass_mg_L"] = transported
        if day_index == len(dates) - 1:
            final_biomass = transported
    mechanism_state = MechanismState(
        last_date=pd.Timestamp(dates[-1]),
        grid_ids=grid_ids,
        biomass_mg_L=tuple(float(value) for value in final_biomass),
    )

    target_rng = make_rng(config, ComponentCode.TARGETS, year, 0, 0)
    latent = build_latent_targets(mechanism_block, target_rng, config)
    observation_rng = make_rng(config, ComponentCode.OBSERVATION, year, 0, 0)
    observed = apply_observation_process(latent, driver_block, observation_rng, config)
    labels = build_bloom_labels(latent, observed, metadata, config)

    frame = mechanism_block.copy()
    _merge_ordered_columns(frame, latent, LATENT_TARGET_COLUMNS)
    _merge_ordered_columns(frame, observed, (*OBSERVATION_RAW_COLUMNS, *OBSERVATION_EXTRA_COLUMNS))
    label_columns = tuple(
        column
        for column in labels.columns
        if column not in frame.columns
        or column
        in {
            "water_area_m2",
            "latent_bloom_label",
            "latent_bloom_area_km2",
            "latent_bloom_coverage_ratio",
            "bloom_label",
            "label_state",
            "bloom_area_km2",
            "bloom_coverage_ratio",
            "bloom_risk_level",
            "coverage_status",
            "missing_reason",
            "quality_status",
            "censoring_status",
            "valid_pixel_ratio",
            "observed_time",
            "available_time",
            "observed_at",
            "available_at",
            "issue_time",
            "remote_chlorophyll_a_below_detection_limit",
            "remote_phycocyanin_below_detection_limit",
            "remote_cyanobacteria_density_below_detection_limit",
            "remote_fai_below_detection_limit",
            "remote_ndci_below_detection_limit",
            "risk_threshold_version",
            "risk_threshold_sha256",
            "risk_threshold_basis",
            "data_role",
            "value_type",
            "label_evidence",
            "data_mode",
            "is_ground_truth",
            "is_model_feature",
            "claim_boundary",
        }
    )
    _merge_ordered_columns(frame, labels, label_columns)
    frame["bloom_probability"] = latent["latent_bloom_probability"].to_numpy()
    frame["experimental_zone_id"] = labels["experimental_zone_id"].to_numpy()
    next_state = BlockState(
        last_date=pd.Timestamp(dates[-1]),
        grid_ids=grid_ids,
        driver=driver_state,
        water_quality=water_state,
        mechanism=mechanism_state,
    )
    return frame, next_state


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _atomic_write_text(text: str, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_write_json(payload: dict, path: Path) -> None:
    _atomic_write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), path)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"required package file missing: {path.name}") from None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid package JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"package JSON must contain an object: {path.name}")
    return value


def _require_same(field: str, *values) -> None:
    if not values or any(value != values[0] for value in values[1:]):
        raise ValueError(f"package metadata mismatch: {field}")


def verify_v03_package(output_dir: str | Path) -> dict[str, object]:
    """Read and independently validate a frozen V0.3 package.

    Verification never writes into ``output_dir``.  It authenticates the JSON
    envelope, current source inputs, partition registry, partition contents,
    combined quality result, and the synthetic-only claim boundary.
    """
    output = Path(output_dir)
    if not output.is_dir():
        raise ValueError(f"V0.3 package directory missing: {output}")

    ready = _read_json(output / "READY.json")
    manifest = _read_json(output / "generation_manifest_V0.3.json")
    report = _read_json(output / "data_quality_report_V0.3.json")

    if _digest(manifest) != ready.get("manifest_sha256"):
        raise ValueError("manifest digest mismatch")
    if _digest(report) != ready.get("quality_report_sha256"):
        raise ValueError("quality report digest mismatch")
    if _digest(report) != manifest.get("quality_report_sha256"):
        raise ValueError("manifest quality report digest mismatch")

    for field in (
        "data_version",
        "generator_version",
        "base_seed",
        "canonical_data_hash",
        "row_count",
        "column_count",
        "partition_count",
        "claim_boundary",
    ):
        _require_same(field, ready.get(field), manifest.get(field))
    _require_same(
        "canonical_data_hash",
        ready.get("canonical_data_hash"),
        report.get("normalized_content_hash"),
    )
    _require_same("row_count", ready.get("row_count"), report.get("grid_day_count"))
    _require_same("column_count", ready.get("column_count"), len(report.get("columns", [])))

    if ready.get("data_version") != "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.3":
        raise ValueError("unexpected V0.3 data version")
    if ready.get("generator_version") != "V0.3":
        raise ValueError("unexpected V0.3 generator version")
    if ready.get("claim_boundary") != "synthetic_development_only":
        raise ValueError("invalid package claim boundary")
    if manifest.get("horizons") != [1, 3, 7, 15, 30]:
        raise ValueError("unexpected V0.3 horizon contract")
    if report.get("status") != "PASS" or report.get("quality_status") != "PASS":
        raise ValueError("quality report status is not PASS")
    if report.get("blocking_issues"):
        raise ValueError("quality report contains blocking issues")
    for field in (
        "duplicate_primary_keys",
        "invalid_label_count",
        "invalid_provenance_count",
        "leakage_count",
        "split_disagreement_count",
        "target_violation_count",
        "unknown_as_negative_count",
    ):
        if report.get(field) != 0:
            raise ValueError(f"quality blocker is nonzero: {field}")

    input_hashes = manifest.get("input_hashes")
    _require_same("source hashes", input_hashes, manifest.get("source_hashes_after"))
    _require_same("source hashes before", input_hashes, report.get("source_hashes_before"))
    _require_same("source hashes after", input_hashes, report.get("source_hashes_after"))
    try:
        actual_input_hashes = _hash_inputs(_canonical_input_map(_default_inputs()))
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("cannot verify package source inputs") from exc
    if actual_input_hashes != input_hashes:
        raise ValueError("source input hash mismatch")

    partition_hashes = manifest.get("partition_hashes")
    if not isinstance(partition_hashes, dict) or not partition_hashes:
        raise ValueError("manifest partition registry is missing")
    actual_paths = sorted(
        str(path.relative_to(output))
        for path in (output / "partitions").rglob("*.parquet")
    )
    if set(actual_paths) != set(partition_hashes):
        raise ValueError("manifest partition paths do not match package")
    _require_same("partition_count", len(actual_paths), ready.get("partition_count"))

    try:
        config = GridSimulationConfig(
            base_seed=int(manifest["base_seed"]),
            start_date=str(manifest["start_date"]),
            end_date=str(manifest["end_date"]),
            expected_grid_count=int(manifest["expected_grid_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("manifest generation configuration is invalid") from exc

    profiles = []
    for relative_path in actual_paths:
        try:
            frame = pd.read_parquet(output / relative_path)
            profile = profile_partition_v03(frame, config)
        except Exception as exc:
            raise ValueError(f"partition verification failed: {relative_path}") from exc
        if profile["normalized_content_hash"] != partition_hashes[relative_path]:
            raise ValueError(f"partition content hash mismatch: {relative_path}")
        profiles.append(profile)

    recomputed = combine_partition_profiles(profiles, config)
    for field in (
        "grid_day_count",
        "grid_count",
        "date_count",
        "start_date",
        "end_date",
        "columns",
        "normalized_content_hash",
        "target_counts",
        "split_counts",
        "blocking_issues",
        "status",
    ):
        _require_same(f"recomputed {field}", recomputed.get(field), report.get(field))
    if recomputed.get("status") != "PASS":
        raise ValueError("recomputed quality status is not PASS")

    return {
        "status": "PASS",
        "data_version": ready["data_version"],
        "canonical_data_hash": ready["canonical_data_hash"],
        "row_count": int(ready["row_count"]),
        "column_count": int(ready["column_count"]),
        "partition_count": int(ready["partition_count"]),
        "claim_boundary": ready["claim_boundary"],
    }


def _partition_frame(frame: pd.DataFrame, year: int, output_dir: Path, config) -> list[dict]:
    partition_dir = output_dir / "partitions" / f"year={year}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    profiles = []
    for zone, group in frame.groupby("experimental_zone_id", sort=True, observed=True):
        zone_path = partition_dir / f"experimental_zone_id={zone}"
        zone_path.mkdir(parents=True, exist_ok=True)
        parquet_path = zone_path / "data.parquet"
        _atomic_write_parquet(group, parquet_path)
        profile = profile_partition_v03(group, config)
        profiles.append(
            {
                "path": str(parquet_path.relative_to(output_dir)),
                "profile": profile,
            }
        )
    return profiles


def _write_checkpoint(state: BlockState, year: int, output_dir: Path) -> None:
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "year": year,
        "last_date": str(state.last_date.date()),
        "grid_count": len(state.grid_ids),
        "grid_ids": list(state.grid_ids),
        "driver": _state_payload(state.driver),
        "water_quality": _state_payload(state.water_quality),
        "mechanism": _state_payload(state.mechanism),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(payload, checkpoint_dir / f"block_state_{year}.json")


def _known_limitations() -> str:
    return """# Known Limitations V0.3

1. This package is transparent synthetic development data, not field-observed
   bloom truth.  Synthetic test metrics do not estimate real Taihu forecast
   accuracy.
2. The 1,520 experimental 1 km grids and experimental zones are provisional.
3. Daily nutrient/water-quality values are conditioned on training-period
   observed anchors, not observed daily measurements.
4. The compact cyanobacteria mechanism and sparse neighbor transport are
   development approximations, not a three-dimensional hydrodynamic solver.
5. Remote-sensing observation is represented by a simulated coverage and
   measurement process; not_observed rows are never converted into negatives.
6. Real-effect claims remain blocked until audited field/full-coverage labels
   and an independent real temporal test set are available.
"""


def _build_manifest_and_report(
    profiles: list[dict],
    report: dict,
    config,
    mode: str,
    before_hashes: dict,
    after_hashes: dict,
) -> dict:
    partition_hashes = {
        item["path"]: item["profile"]["normalized_content_hash"] for item in profiles
    }
    manifest = {
        "data_version": config.data_version,
        "generator_version": config.generator_version,
        "claim_boundary": config.claim_boundary,
        "mode": mode,
        "base_seed": int(config.base_seed),
        "start_date": str(pd.Timestamp(config.start_date).date()),
        "end_date": str(pd.Timestamp(config.end_date).date()),
        "expected_grid_count": int(config.expected_grid_count),
        "horizons": list(config.horizons),
        "input_hashes": before_hashes,
        "source_hashes_after": after_hashes,
        "partition_hashes": partition_hashes,
        "canonical_data_hash": report["normalized_content_hash"],
        "row_count": int(report["grid_day_count"]),
        "partition_count": len(profiles),
        "column_count": len(report["columns"]),
        "quality_report_sha256": _digest(report),
    }
    return manifest


def run_v03_pipeline(
    inputs: dict,
    output_dir: str | Path,
    config: GridSimulationConfig,
    mode: str = "pilot",
) -> dict[str, object]:
    if mode not in {"pilot", "full"}:
        raise ValueError("mode must be 'pilot' or 'full'")
    if not isinstance(config, GridSimulationConfig):
        raise ValueError("config must be a GridSimulationConfig")
    output = Path(output_dir)
    _validate_inputs(inputs)
    output.mkdir(parents=True, exist_ok=True)

    full_weather_config = SimulationConfig()
    source_paths = _canonical_input_map(inputs)
    before_hashes = _hash_inputs(source_paths)
    grid, weather, metadata, adjacency, coordinates = _load_generation_inputs(
        inputs, config, full_weather_config
    )
    registry = build_anchor_registry(inputs["anchor_paths"], inputs["train_end"])
    anchor_profile = profile_training_anchors(registry)
    dates = pd.DatetimeIndex(config.dates)
    year_groups = [dates[dates.year == year] for year in sorted(set(dates.year))]

    profiles: list[dict] = []
    pending: tuple[int, pd.DataFrame] | None = None
    previous_state: BlockState | None = None
    expected_grid_ids = tuple(metadata["grid_id"].astype(str))
    for year_dates in year_groups:
        year = int(year_dates[0].year)
        frame, state = _generate_block(
            year_dates,
            config,
            metadata,
            adjacency,
            coordinates,
            weather,
            anchor_profile,
            previous_state,
        )
        previous_state = state
        _write_checkpoint(state, year, output)
        if pending is not None:
            pending_year, pending_frame = pending
            combined = pd.concat([pending_frame, frame], ignore_index=True)
            forecast = build_v03_forecast_samples(combined, config)
            pending_forecast = forecast[
                forecast["date"].dt.year.eq(pending_year)
            ].reset_index(drop=True)
            profiles.extend(_partition_frame(pending_forecast, pending_year, output, config))
        pending = (year, frame)

    if pending is None:
        raise RuntimeError("no date block was generated")
    final_year, final_frame = pending
    final_forecast = build_v03_forecast_samples(final_frame, config)
    profiles.extend(_partition_frame(final_forecast, final_year, output, config))
    if not profiles:
        raise RuntimeError("no partition profiles were produced")
    if any(item["profile"]["columns"] != profiles[0]["profile"]["columns"] for item in profiles):
        raise ValueError("partition schemas disagree after generation")

    after_hashes = _hash_inputs(source_paths)
    _validate_source_hash_equality(before_hashes, after_hashes)
    report = combine_partition_profiles([item["profile"] for item in profiles], config)
    if report["blocking_issues"]:
        raise ValueError("V0.3 quality gates failed: " + "; ".join(sorted(report["blocking_issues"])))
    if report.get("status") != "PASS":
        raise ValueError("V0.3 quality report status is not PASS")

    report["source_hashes_before"] = before_hashes
    report["source_hashes_after"] = after_hashes
    report["output_hashes"] = {
        item["path"]: item["profile"]["normalized_content_hash"] for item in profiles
    }
    report["quality_status"] = "PASS"
    quality_path = output / "data_quality_report_V0.3.json"
    _atomic_write_json(report, quality_path)

    manifest = _build_manifest_and_report(
        profiles,
        report,
        config,
        mode,
        before_hashes,
        after_hashes,
    )
    manifest_path = output / "generation_manifest_V0.3.json"
    _atomic_write_json(manifest, manifest_path)
    _atomic_write_text(_known_limitations(), output / "known_limitations_V0.3.md")

    lineage_rows = []
    for name, path in source_paths.items():
        role = "grid_source" if name == "grid" else "weather_source" if name == "weather" else "anchor_source"
        lineage_rows.append(
            lineage_record(path, role=role, source_class="observed_or_external_development_input")
        )
    for item in profiles:
        lineage_rows.append(
            lineage_record(
                output / item["path"],
                role="generated_partition",
                source_class="synthetic_development_only",
            )
        )
    lineage = build_lineage(lineage_rows)
    _atomic_write_text(
        lineage.to_csv(index=False, encoding="utf-8-sig"),
        output / "source_lineage_V0.3.csv",
    )

    ready = {
        "data_version": config.data_version,
        "generator_version": config.generator_version,
        "base_seed": int(config.base_seed),
        "canonical_data_hash": report["normalized_content_hash"],
        "manifest_sha256": _digest(manifest),
        "quality_report_sha256": _digest(report),
        "row_count": int(report["grid_day_count"]),
        "column_count": len(report["columns"]),
        "partition_count": len(profiles),
        "claim_boundary": config.claim_boundary,
    }
    ready_path = output / "READY.json"
    _atomic_write_json(ready, ready_path)
    return {
        "quality_status": "PASS",
        "canonical_data_hash": report["normalized_content_hash"],
        "manifest_path": str(manifest_path),
        "quality_path": str(quality_path),
        "ready_path": str(ready_path),
        "row_count": int(report["grid_day_count"]),
        "partition_count": len(profiles),
        "columns": sorted(report["columns"]),
    }


def _default_inputs() -> dict:
    project_root = Path(__file__).resolve().parents[2]
    processed = project_root / "训练准备" / "processed_existing_data_V0.2"
    return {
        "grid": (
            project_root
            / "里程碑5_水华标签工程与时空对齐"
            / "01_成果"
            / "milestone_5_label_engineering"
            / "grid_definition_provisional_V0.1.geojson"
        ),
        "weather": (
            project_root
            / "训练准备"
            / "synthetic_augmentation"
            / "inputs"
            / "nasa_power_taihu_2005_2025.json"
        ),
        "anchor_paths": {
            "quarterly_tp": processed / "quarterly_tp_forecast_candidate.parquet",
            "quarterly_tn": processed / "quarterly_tn_forecast_candidate.parquet",
            "quarterly_do": processed / "quarterly_do_forecast_candidate.parquet",
            "quarterly_phyto_biomass": processed / "quarterly_phyto_biomass_forecast_candidate.parquet",
            "annual_cyanobacteria": processed / "annual_cyanobacteria_review.csv",
            "field_chla": processed / "field_chla_observations_normalized.csv",
            "remote_chla": processed / "remote_sensing_chla_proxy.parquet",
        },
        "train_end": "2017-12-31",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate partitioned V0.3 Taihu synthetic grid data")
    parser.add_argument("--mode", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output", required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        try:
            print(_canonical_json(verify_v03_package(args.output)))
        except (OSError, ValueError) as exc:
            print(_canonical_json({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
            sys.exit(1)
        return
    config = GridSimulationConfig(
        start_date=f"{args.start_year:04d}-01-01",
        end_date=f"{args.end_year:04d}-12-31",
    )
    result = run_v03_pipeline(_default_inputs(), args.output, config, mode=args.mode)
    print(_canonical_json(result))


if __name__ == "__main__":
    main()
