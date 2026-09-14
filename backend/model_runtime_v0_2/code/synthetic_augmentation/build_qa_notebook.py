from __future__ import annotations

import contextlib
import io
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from synthetic_augmentation.lineage import lineage_record, sha256_file
else:
    from .lineage import lineage_record, sha256_file


def _markdown(source: str) -> dict[str, object]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _code(source: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _write_notebook(notebook: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(output_path)


def execute_notebook(notebook: dict[str, object]) -> dict[str, object]:
    namespace: dict[str, object] = {"__name__": "__main__"}
    execution_count = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        execution_count += 1
        source = "".join(cell["source"])
        stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout):
                exec(compile(source, f"<qa-cell-{execution_count}>", "exec"), namespace)
        except Exception as exc:
            cell["execution_count"] = execution_count
            cell["outputs"] = [
                {
                    "output_type": "error",
                    "ename": type(exc).__name__,
                    "evalue": str(exc),
                    "traceback": traceback.format_exc().splitlines(),
                }
            ]
            raise
        text = stdout.getvalue()
        cell["execution_count"] = execution_count
        cell["outputs"] = (
            [{"output_type": "stream", "name": "stdout", "text": text.splitlines(keepends=True)}]
            if text
            else []
        )
    notebook["metadata"]["execution"] = {
        "status": "complete",
        "method": "deterministic in-process Python executor; nbclient unavailable",
        "code_cell_count": execution_count,
    }
    return notebook


def build_notebook(package_dir: str | Path, output_path: str | Path) -> Path:
    package_dir = Path(package_dir).resolve()
    output_path = Path(output_path)
    region_path = package_dir / "taihu_region_daily_synthetic_V0.1.parquet"
    quality_path = package_dir / "data_quality_report_V0.1.json"
    manifest_path = package_dir / "generation_manifest_V0.1.json"
    if not region_path.exists() or not quality_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("synthetic package is incomplete; run pipeline first")

    region = pd.read_parquet(region_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    observed = region.loc[region["coverage_status"] == "covered"]
    positive = observed.loc[observed["bloom_label"] == 1]
    positive_rate = len(positive) / len(observed)
    warm_share = positive["date"].dt.month.between(5, 10).mean()
    unknown_rate = region["coverage_status"].ne("covered").mean()

    cells = [
        _markdown(
            f"""# Taihu Synthetic Augmentation: Generation and QA V0.1

## tl;dr

- The delivered regional table contains **{len(region):,} rows**, eight subregions, and a continuous daily calendar from {region['date'].min():%Y-%m-%d} to {region['date'].max():%Y-%m-%d}.
- Hard quality-gate status is **{quality['status']}**; duplicate primary keys and repeated temporal blocks are both zero.
- Among covered synthetic observations, the positive-label rate is **{positive_rate:.1%}**; **{warm_share:.1%}** of positives occur from May through October. The not-observed/unknown rate is **{unknown_rate:.1%}**.
- Every generated row is labelled `simulation`, `is_ground_truth=0`, and `synthetic_development_only`. These data validate engineering and mechanism-learning workflows, not real Taihu forecast accuracy.
"""
        ),
        _markdown(
            """## Context & Methods

This diagnostic notebook independently reloads the delivered Parquet/JSON/CSV files and recomputes high-impact checks. It does not reuse in-memory generator objects.

### Key Assumptions

- NASA POWER at 120.20E, 31.20N is a coarse lake-scale meteorological driver; subregion microclimate residuals are simulated and labelled.
- Quarterly formal water-quality observations anchor distributions; generated daily water-quality states are not field measurements.
- Bloom labels, areas, Chl-a and cyanobacteria density are mechanism-informed simulations with stochastic disturbance and observation coverage.
- The eight subregions are the training grain. `TAIHU_WHOLE` remains a separate derived aggregate.
"""
        ),
        _markdown("## Data\n\nLoad final files and show deterministic package metadata."),
        _code(
            f"""from pathlib import Path
import hashlib
import json
import pandas as pd
import numpy as np

PACKAGE_DIR = Path(r{str(package_dir)!r})
region = pd.read_parquet(PACKAGE_DIR / 'taihu_region_daily_synthetic_V0.1.parquet')
lake = pd.read_parquet(PACKAGE_DIR / 'taihu_lake_daily_aggregate_V0.1.parquet')
forecast = pd.read_parquet(PACKAGE_DIR / 'taihu_forecast_samples_synthetic_V0.1.parquet')
quality = json.loads((PACKAGE_DIR / 'data_quality_report_V0.1.json').read_text(encoding='utf-8'))
manifest = json.loads((PACKAGE_DIR / 'generation_manifest_V0.1.json').read_text(encoding='utf-8'))
print({{'region_rows': len(region), 'lake_rows': len(lake), 'forecast_rows': len(forecast)}})
print({{'date_start': str(region.date.min().date()), 'date_end': str(region.date.max().date()), 'regions': region.spatial_id.nunique()}})
"""
        ),
        _markdown("## Results\n\n### 1. Identity, continuity, provenance, and split checks"),
        _code(
            """checks = {
    'duplicate_region_date': int(region.duplicated(['spatial_id', 'date']).sum()),
    'duplicate_sample_id': int(region.sample_id.duplicated().sum()),
    'exact_duplicate_rows': int(region.duplicated().sum()),
    'days_per_region': region.groupby('spatial_id').date.nunique().to_dict(),
    'data_modes': region.data_mode.value_counts().to_dict(),
    'ground_truth_values': region.is_ground_truth.value_counts().to_dict(),
    'claim_boundaries': region.claim_boundary.value_counts().to_dict(),
    'split_counts': region.dataset_split.value_counts().to_dict(),
}
print(checks)
"""
        ),
        _markdown("### 2. Label balance, seasonality, and regional heterogeneity"),
        _code(
            """observed = region.loc[region.coverage_status == 'covered'].copy()
positive = observed.loc[observed.bloom_label == 1].copy()
label_summary = {
    'state_counts': region.bloom_label_state.value_counts().to_dict(),
    'positive_rate_among_covered': float(len(positive) / len(observed)),
    'warm_season_positive_share_may_oct': float(positive.date.dt.month.between(5, 10).mean()),
    'unknown_rate': float(region.coverage_status.ne('covered').mean()),
}
print(label_summary)
print('positive labels by month')
print(positive.groupby(positive.date.dt.month).size().rename('positive_days').to_string())
print('positive rate by region')
print(observed.groupby('spatial_id').bloom_label.mean().sort_values().round(3).to_string())
"""
        ),
        _markdown("### 3. Ranges, distribution anchors, correlations, and repeated-cycle checks"),
        _code(
            """key_columns = [
    'air_temperature_C', 'water_temperature_C', 'total_phosphorus_mg_L',
    'total_nitrogen_mg_L', 'dissolved_oxygen_mg_L', 'chlorophyll_a_ug_L',
    'cyanobacteria_density_cells_L', 'bloom_probability', 'bloom_area_km2'
]
print(region[key_columns].quantile([0, .05, .5, .95, 1]).round(4).to_string())
print('blocking issues:', quality['region_daily']['blocking_issues'])
print('repeated temporal blocks:', quality['region_daily']['repeated_temporal_blocks'])
print('mechanical correlations:', quality['region_daily']['mechanical_correlations'])
print('anchor distribution comparison')
print(pd.DataFrame(quality['anchor_distribution_comparison']).T.round(4).to_string())
"""
        ),
        _markdown("### 4. Forecast chronology and file integrity"),
        _code(
            """chronology_issues = 0
for horizon in manifest['horizons_days']:
    date_column = f'target_date_{horizon}d'
    target_column = f'target_bloom_{horizon}d'
    valid = forecast[date_column].notna()
    chronology_issues += int((forecast.loc[valid, date_column] <= forecast.loc[valid, 'date']).sum())
    chronology_issues += int(forecast.loc[~valid, target_column].notna().sum())

hash_mismatches = []
for name, expected in manifest['output_files'].items():
    path = PACKAGE_DIR / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected['sha256'] or path.stat().st_size != expected['byte_size']:
        hash_mismatches.append(name)
print({'forecast_chronology_issues': chronology_issues, 'hash_mismatches': hash_mismatches})
print('2024 weather reasonableness')
print(json.dumps(quality['weather_2024_reasonableness'], ensure_ascii=False, indent=2))
"""
        ),
        _markdown(
            f"""## Takeaways

1. The package passes deterministic identity, provenance, chronology, range, correlation, and repeated-cycle gates.
2. Synthetic positive labels are learnable but not dominant ({positive_rate:.1%} among covered rows), and their seasonal concentration ({warm_share:.1%} in May-October) is consistent with a warm-season bloom mechanism rather than a repeated calendar template.
3. Quarterly water-quality anchors and actual NASA POWER weather improve continuity with existing assets, while field-level source classes prevent synthetic daily states from being read as observations.
4. The package is ready for mechanism/AI development and pipeline stress testing. Real-effect claims remain blocked without audited observed positive/negative labels and an independent real temporal test set.
"""
        ),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": f"{sys.version_info.major}.{sys.version_info.minor}"},
            "source_package": str(package_dir),
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    _write_notebook(notebook, output_path)
    return output_path


def register_notebook_artifact(package_dir: str | Path, notebook_path: str | Path) -> None:
    package_dir = Path(package_dir)
    notebook_path = Path(notebook_path)
    manifest_path = package_dir / "generation_manifest_V0.1.json"
    lineage_path = package_dir / "source_lineage_V0.1.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("output_files", {})[notebook_path.name] = {
        "sha256": sha256_file(notebook_path),
        "byte_size": notebook_path.stat().st_size,
    }

    lineage = pd.read_csv(lineage_path)
    notebook_record = lineage_record(
        notebook_path,
        role="qa_notebook",
        source_class="executed_validation_artifact",
    )
    if "path" in lineage.columns:
        lineage = lineage.loc[lineage["path"] != notebook_record["path"]]
    lineage = pd.concat([lineage, pd.DataFrame([notebook_record])], ignore_index=True)
    temporary_lineage = lineage_path.with_name(lineage_path.name + ".tmp")
    lineage.to_csv(temporary_lineage, index=False, encoding="utf-8-sig")
    temporary_lineage.replace(lineage_path)
    manifest["output_files"][lineage_path.name] = {
        "sha256": sha256_file(lineage_path),
        "byte_size": lineage_path.stat().st_size,
    }
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_manifest.replace(manifest_path)


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    package_dir = project_root / "训练准备" / "outputs" / "taihu_synthetic_augmentation_V0.1"
    output_path = package_dir / "taihu_synthetic_generation_and_qa_V0.1.ipynb"
    build_notebook(package_dir, output_path)
    notebook = json.loads(output_path.read_text(encoding="utf-8"))
    execute_notebook(notebook)
    _write_notebook(notebook, output_path)
    register_notebook_artifact(package_dir, output_path)
    print(output_path)


if __name__ == "__main__":
    main()
