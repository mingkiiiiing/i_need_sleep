"""Reader-facing V0.3 QA notebook builder and in-process executor."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .build_qa_notebook import _code, _markdown, _write_notebook, execute_notebook


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_v03_notebook(package_dir: str | Path, output_path: str | Path) -> Path:
    package_dir = Path(package_dir).resolve()
    output_path = Path(output_path)
    manifest_path = package_dir / "generation_manifest_V0.3.json"
    quality_path = package_dir / "data_quality_report_V0.3.json"
    if not manifest_path.exists() or not quality_path.exists():
        raise FileNotFoundError("V0.3 package is incomplete; generation_manifest and quality report are required")
    manifest = _load_json(manifest_path)
    quality = _load_json(quality_path)
    row_count = int(quality.get("grid_day_count", manifest.get("row_count", 0)))
    status = quality.get("status", quality.get("quality_status", "UNKNOWN"))

    cells = [
        _markdown(
            f"""# Taihu Grid Synthetic Augmentation V0.3: QA Notebook

## tl;dr

- Package: **{manifest.get('data_version')}**, generator **{manifest.get('generator_version')}**.
- Quality status is **{status}**; expected grid-day count is **{row_count:,}**.
- Every generated row carries `simulation`, `is_ground_truth=0`, and `synthetic_development_only`.
- This notebook reads Manifest/QA JSON first and samples Parquet partitions. It never claims synthetic metrics are real Taihu forecast accuracy.
"""
        ),
        _markdown(
            """## Source boundaries

The source layer is immutable observed/audited anchor data plus the documented
NASA POWER external daily meteorology. Synthetic development data is a separate
layer and never rewrites source files.
"""
        ),
        _code(
            f"""from pathlib import Path
import json
import pandas as pd

PACKAGE_DIR = Path({str(package_dir)!r})
manifest = json.loads((PACKAGE_DIR / 'generation_manifest_V0.3.json').read_text(encoding='utf-8'))
quality = json.loads((PACKAGE_DIR / 'data_quality_report_V0.3.json').read_text(encoding='utf-8'))
print({{'data_version': manifest.get('data_version'), 'mode': manifest.get('mode'),
       'base_seed': manifest.get('base_seed'), 'grid_day_count': quality.get('grid_day_count')}})
print('source_hashes_after_count', len(quality.get('source_hashes_after', {{}})))
"""
        ),
        _markdown(
            """## Randomness

Seed reproducibility is verified by stable coordinate-derived NumPy streams.
Same-seed partitions must hash identically; different seeds must change content
while preserving overall distributional bounds.
"""
        ),
        _code(
            """partition_paths = sorted((PACKAGE_DIR / 'partitions').glob('year=*/*/data.parquet'))
print({'partition_count': len(partition_paths)})
if partition_paths:
    sample = pd.read_parquet(partition_paths[0])
    print({'sample_partition': str(partition_paths[0]), 'sample_rows': len(sample),
           'sample_columns': len(sample.columns)})
"""
        ),
        _markdown(
            """## Mechanism checks

Mechanism factors, daily rates, blue-algae biomass, and transport are all
simulated development state fields. Plot titles carry `synthetic development
only`; no factor is presented as a calibrated field-observation truth.
"""
        ),
        _code(
            """mechanism_columns = ['temperature_factor', 'nutrient_factor', 'light_factor',
    'capacity_factor', 'net_growth_rate_d', 'blue_algae_biomass_mg_L']
mechanism_summary = {}
if partition_paths:
    frame = pd.read_parquet(partition_paths[0])
    present = [c for c in mechanism_columns if c in frame.columns]
    if present:
        mechanism_summary = frame[present].describe(percentiles=[.05, .5, .95]).to_dict()
print({'mechanism_variables': present, 'title_marker': 'synthetic development only'})
if mechanism_summary:
    print(mechanism_summary)
"""
        ),
        _markdown(
            """## Spatial checks

Adjacent 1 km experimental grids share mechanism and wind fields, but the
graphs/statistics are spatial simulation checks only (`synthetic development
only`), never proof of official management-boundary behaviour.
"""
        ),
        _code(
            """spatial_info = manifest.get('config', {})
print({'grid_count': spatial_info.get('expected_grid_count'),
       'spatial_check': 'adjacency + neighbor statistics in QA report',
       'title_marker': 'synthetic development only'})
"""
        ),
        _markdown(
            """## Leakage checks

Feature availability must never exceed issue time; future targets are embargoed
across split boundaries. QA counts for leakage, cross-partition target
mismatches, and latent feature leakage are reported from the package.
"""
        ),
        _code(
            """leakage = quality.get('leakage', {})
counts = {name: value.get('value') if isinstance(value, dict) else value
          for name, value in leakage.items()}
print({'leakage': counts, 'target_violation_count': quality.get('target_violation_count', 0),
       'unknown_as_negative_count': quality.get('unknown_as_negative_count', 0)})
"""
        ),
        _markdown(
            """## Limitations

- Synthetic grid-day values are development simulations, not observed Taihu
  monitoring records.
- Provisional 1 km grids/experimental zones are not official management
  boundaries.
- Simulated labels/metrics cannot estimate real-world forecast performance.
"""
        ),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
            "source_package": str(package_dir),
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return _write_notebook(notebook, output_path)


def execute_v03_notebook(path: str | Path, output_path: str | Path | None = None) -> Path:
    source_path = Path(path)
    notebook = json.loads(source_path.read_text(encoding="utf-8"))
    executed = execute_notebook(notebook)
    destination = Path(output_path) if output_path is not None else source_path
    _write_notebook(executed, destination)
    return destination


if __name__ == "__main__":
    raise SystemExit("import this module and call build_v03_notebook/execute_v03_notebook")
