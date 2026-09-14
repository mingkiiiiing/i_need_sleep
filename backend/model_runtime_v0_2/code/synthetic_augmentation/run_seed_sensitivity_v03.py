"""Lightweight V0.3 seed-sensitivity summary runner.

The 21-year full package is generated once with the frozen base seed.  This
module reruns the same generator for ten derived realisation seeds on a 10%
stratified one-year summary grid and records annual q10/q50/q90 statistics,
content hashes, and same-seed replicability.  It intentionally does not write
ten complete grid-day tables.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from synthetic_augmentation.config import GridSimulationConfig
    from synthetic_augmentation.config import SimulationConfig
    from synthetic_augmentation.pipeline_v03 import (
        _default_inputs,
        _generate_block,
        _load_generation_inputs,
        _validate_inputs,
        _write_checkpoint,
        canonical_frame_hash,
    )
    from synthetic_augmentation.quality import default_seed_tolerances, check_seed_sensitivity
    from synthetic_augmentation.quality import profile_partition_v03
    from synthetic_augmentation.sources import build_anchor_registry, profile_training_anchors
else:
    from .config import GridSimulationConfig
    from .config import SimulationConfig
    from .pipeline_v03 import (
        _default_inputs,
        _generate_block,
        _load_generation_inputs,
        _validate_inputs,
        _write_checkpoint,
        canonical_frame_hash,
    )
    from .quality import default_seed_tolerances, check_seed_sensitivity
    from .quality import profile_partition_v03
    from .sources import build_anchor_registry, profile_training_anchors


SUMMARY_GRID_COUNT = 152
SUMMARY_YEAR = 2005


def _summary_config(seed: int) -> GridSimulationConfig:
    return GridSimulationConfig(
        base_seed=int(seed),
        start_date=f"{SUMMARY_YEAR}-01-01",
        end_date=f"{SUMMARY_YEAR}-12-31",
        expected_grid_count=SUMMARY_GRID_COUNT,
    )


def _summary_row(seed: int, replicate: str, frame: pd.DataFrame, config) -> dict:
    profile = profile_partition_v03(frame, config)
    numeric_stats = profile["numeric_stats"]
    tolerances = default_seed_tolerances()
    missing = sorted(set(tolerances) - set(numeric_stats))
    if missing:
        raise ValueError(f"seed summary missing tolerance variables: {missing}")
    quantiles = {
        name: [float(value) for value in numeric_stats[name]["quantiles"]]
        for name in tolerances
    }
    return {
        "seed": int(seed),
        "replicate_id": replicate,
        "content_hash": profile["normalized_content_hash"],
        "row_count": int(len(frame)),
        "quantiles": quantiles,
    }


def run_seed_sensitivity(output_dir: str | Path) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = _default_inputs()
    _validate_inputs(inputs)
    base_config = _summary_config(20260901)
    grid, weather, metadata, adjacency, coordinates = _load_generation_inputs(
        inputs, base_config, SimulationConfig()
    )
    registry = build_anchor_registry(inputs["anchor_paths"], inputs["train_end"])
    profile = profile_training_anchors(registry)
    dates = base_config.dates
    seeds = [20260901 + offset for offset in range(10)]
    rows = []
    # Ten registered realisation seeds plus one deterministic same-seed rerun.
    for seed in seeds:
        config = _summary_config(seed)
        frame, state = _generate_block(
            dates, config, metadata, adjacency, coordinates, weather, profile, None
        )
        rows.append(_summary_row(seed, f"{seed}-A", frame, config))
        if seed == seeds[0]:
            frame_repeat, _ = _generate_block(
                dates, config, metadata, adjacency, coordinates, weather, profile, None
            )
            rows.append(_summary_row(seed, f"{seed}-B", frame_repeat, config))

    summary = {
        "schema_version": "seed-summary-v03-1",
        "summary_grid_count": SUMMARY_GRID_COUNT,
        "summary_year": SUMMARY_YEAR,
        "registered_seed_count": len(seeds),
        "summary_rows": rows,
        "tolerances": default_seed_tolerances(),
    }
    check = check_seed_sensitivity(rows, default_seed_tolerances())
    summary_path = output / "seed_sensitivity_summaries_V0.3.json"
    check_path = output / "seed_sensitivity_check_V0.3.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    check_path.write_text(
        json.dumps(check, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {"summary_path": str(summary_path), "check_path": str(check_path), "check": check}


if __name__ == "__main__":
    target = (
        Path(__file__).resolve().parents[2]
        / "训练准备"
        / "outputs"
        / "taihu_grid_synthetic_augmentation_V0.3"
    )
    print(json.dumps(run_seed_sensitivity(target), ensure_ascii=False, indent=2))
