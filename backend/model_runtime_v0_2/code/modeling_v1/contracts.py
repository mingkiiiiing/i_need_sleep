"""Frozen task, target, horizon, and run contracts for model training V1.

The exact horizon tuple, split boundaries, claim boundary, and task/target
mapping are pre-registered acceptance contracts, not implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd
import yaml

DATA_VERSION = "TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4"
CLAIM_BOUNDARY = "synthetic_development_only"
HORIZONS: tuple[int, ...] = (1, 3, 7, 15, 30, 60, 90)
SPLITS: tuple[str, ...] = ("train", "validation", "test")
DEFAULT_SEED = 20260907
SEEDS: tuple[int, ...] = (20260907, 20260908, 20260909)
RISK_CLASSES: tuple[str, ...] = ("none", "low", "medium", "high", "severe")
HIGH_RISK_CLASSES: tuple[str, ...] = ("high", "severe")

_POLICY = yaml.safe_load(
    (Path(__file__).with_name("policy_v1.yaml")).read_text(encoding="utf-8")
)
BINARY_MIN_RECALL = float(_POLICY["t1_min_recall"])
T6_HIGH_SEVERE_MIN_RECALL = float(_POLICY["t6_high_severe_min_recall"])
DECISION_THRESHOLD_POLICY = "max_f1_subject_to_min_recall"

ProblemType = Literal["binary", "ordinal", "regression", "probability", "spatial"]


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    variant: str
    target_family: str
    problem_type: ProblemType
    primary_metric: str
    feature_groups: tuple[str, ...] = ("dynamic", "mechanism")


@dataclass(frozen=True)
class RunSpec:
    task: TaskSpec
    horizon_days: int
    seed: int = DEFAULT_SEED

    @property
    def run_id(self) -> str:
        return (
            f"{self.task.task_id}-{self.task.variant}-"
            f"{self.horizon_days}d-s{self.seed}"
        )


@dataclass(frozen=True)
class WindowSpec:
    window_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str


ROLLING_WINDOWS: tuple[WindowSpec, ...] = (
    WindowSpec(
        window_id="W1",
        train_start="2005-01-01",
        train_end="2013-12-31",
        validation_start="2014-01-01",
        validation_end="2015-12-31",
    ),
    WindowSpec(
        window_id="W2",
        train_start="2005-01-01",
        train_end="2015-12-31",
        validation_start="2016-01-01",
        validation_end="2017-12-31",
    ),
    WindowSpec(
        window_id="W3",
        train_start="2005-01-01",
        train_end="2017-12-31",
        validation_start="2018-01-01",
        validation_end="2019-12-31",
    ),
    WindowSpec(
        window_id="W4",
        train_start="2005-01-01",
        train_end="2019-12-31",
        validation_start="2020-01-01",
        validation_end="2021-12-31",
    ),
)


# Observable issue-time fields persisted in every V0.4 grid-day partition.
# These names come from the closed V0.3 causal-feature contract, restricted to
# columns physically present in the frozen V0.4 schema.
OBSERVABLE_DYNAMIC_COLUMNS = (
    "air_temperature_C",
    "precipitation_mm_day",
    "wind_speed_m_s",
    "wind_direction_deg",
    "solar_radiation_MJ_m2_day",
    "relative_humidity_pct",
    "surface_pressure_kPa",
    "water_temperature_C",
    "water_level_m",
    "flow_speed_m_s",
    "mixing_index",
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "phytoplankton_biomass_mg_L",
    "remote_chlorophyll_a_ug_L",
    "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L",
    "remote_fai_proxy",
    "remote_ndci_proxy",
    "cloud_fraction",
    "valid_pixel_ratio",
)

MECHANISM_COLUMNS = (
    "temperature_factor",
    "nitrogen_factor",
    "phosphorus_factor",
    "nutrient_factor",
    "light_factor",
    "capacity_factor",
    "gross_growth_rate_d",
    "respiration_rate_d",
    "mortality_rate_d",
    "mixing_loss_rate_d",
    "net_growth_rate_d",
)

SEASONAL_COLUMNS = (
    "calendar_day_of_year_sin",
    "calendar_day_of_year_cos",
    "calendar_day_of_week_sin",
    "calendar_day_of_week_cos",
)

STATIC_COLUMNS = ("water_area_m2",)

MODEL_FEATURE_COLUMNS = tuple(
    dict.fromkeys(
        (
            *OBSERVABLE_DYNAMIC_COLUMNS,
            *MECHANISM_COLUMNS,
            *STATIC_COLUMNS,
            *SEASONAL_COLUMNS,
        )
    )
)

HISTORY_STATE_COLUMNS: tuple[str, ...] = (
    "water_temperature_C",
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "phytoplankton_biomass_mg_L",
    "remote_chlorophyll_a_ug_L",
    "remote_phycocyanin_ug_L",
    "remote_cyanobacteria_density_cells_L",
)

HISTORY_LAG_DAYS: tuple[int, ...] = (1, 3, 7, 14, 30)


def history_feature_names() -> tuple[str, ...]:
    """Return stable names for generated issue-time lag/rolling fields."""
    names: list[str] = []
    for column in HISTORY_STATE_COLUMNS:
        for lag in HISTORY_LAG_DAYS:
            names.append(f"{column}_lag_{lag}d")
        names.append(f"{column}_rolling7_mean")
        names.append(f"{column}_rolling7_std")
        names.append(f"{column}_change_1d")
        names.append(f"{column}_change_7d")
    return tuple(names)


HISTORY_FEATURE_COLUMNS = history_feature_names()

ENRICHED_FEATURE_COLUMNS = tuple(
    dict.fromkeys((*MODEL_FEATURE_COLUMNS, *HISTORY_FEATURE_COLUMNS))
)

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "water_temperature": ("water_temperature_C",),
    "weather": (
        "air_temperature_C",
        "precipitation_mm_day",
        "solar_radiation_MJ_m2_day",
        "relative_humidity_pct",
        "surface_pressure_kPa",
    ),
    "wind": (
        "wind_speed_m_s",
        "wind_direction_deg",
    ),
    "light": ("solar_radiation_MJ_m2_day",),
    "nutrients": (
        "total_phosphorus_mg_L",
        "total_nitrogen_mg_L",
        "dissolved_oxygen_mg_L",
        "ph",
        "phytoplankton_biomass_mg_L",
    ),
    "flow_and_mixing": (
        "flow_speed_m_s",
        "mixing_index",
        "water_level_m",
    ),
    "remote_sensing": (
        "remote_chlorophyll_a_ug_L",
        "remote_phycocyanin_ug_L",
        "remote_cyanobacteria_density_cells_L",
        "remote_fai_proxy",
        "remote_ndci_proxy",
        "cloud_fraction",
        "valid_pixel_ratio",
    ),
    "mechanism": MECHANISM_COLUMNS,
    "seasonal": SEASONAL_COLUMNS,
    "static": STATIC_COLUMNS,
}

T1 = TaskSpec("T1", "bloom", "bloom", "binary", "pr_auc")
T2_AREA = TaskSpec("T2", "area", "bloom_area_km2", "regression", "mae")
T2_COVERAGE = TaskSpec(
    "T2", "coverage", "bloom_coverage_ratio", "regression", "mae"
)
T3 = TaskSpec(
    "T3",
    "density",
    "cyanobacteria_density_cells_L",
    "regression",
    "log1p_mae",
)
T4 = TaskSpec(
    "T4", "biomass", "blue_algae_biomass_mg_L", "regression", "mae"
)
T5 = TaskSpec("T5", "chla", "chlorophyll_a_ug_L", "regression", "mae")
T6_RISK = TaskSpec(
    "T6", "risk_level", "bloom_risk_level", "ordinal", "macro_f1"
)
T6_PROBABILITY = TaskSpec(
    "T6", "probability", "bloom_probability", "probability", "brier_score"
)
T7_SPATIAL = TaskSpec(
    "T7", "spatial", "bloom_area_km2", "spatial", "area_weighted_iou",
    feature_groups=("dynamic", "mechanism", "static"),
)

TASK_SPECS: tuple[TaskSpec, ...] = (
    T1,
    T2_AREA,
    T2_COVERAGE,
    T3,
    T4,
    T5,
    T6_RISK,
    T6_PROBABILITY,
    T7_SPATIAL,
)


def target_column(target_family: str, horizon_days: int) -> str:
    """Return the frozen V0.4 target column name for a family and horizon."""
    horizon = int(horizon_days)
    if horizon not in HORIZONS:
        raise ValueError(f"unsupported forecast horizon: {horizon}")
    return f"target_{target_family}_{horizon}d"


def build_run_matrix() -> pd.DataFrame:
    """Return one row per supervised task/variant/horizon combination."""
    rows = []
    for task in TASK_SPECS:
        for horizon in HORIZONS:
            rows.append(
                {
                    "task_id": task.task_id,
                    "variant": task.variant,
                    "target_family": task.target_family,
                    "target_column": target_column(task.target_family, horizon),
                    "horizon_days": horizon,
                    "problem_type": task.problem_type,
                    "primary_metric": task.primary_metric,
                    "run_id": f"{task.task_id}-{task.variant}-{horizon}d",
                }
            )
    return pd.DataFrame(rows)


def task_spec(task_id: str, variant: str) -> TaskSpec:
    for spec in TASK_SPECS:
        if spec.task_id == task_id and spec.variant == variant:
            return spec
    raise ValueError(f"unknown task/variant: {task_id}/{variant}")


def _forbidden_feature_columns(columns: Sequence[str]) -> set[str]:
    forbidden: set[str] = set()
    for column in columns:
        lowered = str(column).lower()
        if lowered.startswith(("target_", "latent_", "simulation_")):
            forbidden.add(str(column))
        elif lowered.startswith(("target_date_", "target_embargo_")):
            forbidden.add(str(column))
        elif lowered in {
            "date",
            "issue_time",
            "available_time",
            "observed_time",
            "available_at",
            "observed_at",
            "dataset_split",
            "data_version",
            "claim_boundary",
            "grid_id",
            "grid_numeric_id",
        }:
            forbidden.add(str(column))
        elif lowered in {
            "bloom_label",
            "bloom_probability",
            "bloom_area_km2",
            "bloom_coverage_ratio",
            "bloom_risk_level",
            "blue_algae_biomass_mg_L",
            "chlorophyll_a_ug_L",
            "phycocyanin_ug_L",
            "cyanobacteria_density_cells_L",
            "is_model_feature",
            "is_ground_truth",
            "label_state",
            "data_role",
            "value_type",
        }:
            forbidden.add(str(column))
    return forbidden


def validate_feature_columns(columns: Sequence[str]) -> None:
    """Reject any label, latent-truth, target-derived, or key/provenance field."""
    if isinstance(columns, (str, bytes)):
        raise TypeError("feature columns must be a sequence of names")
    names = list(columns)
    if not names or any(not str(name).strip() for name in names):
        raise ValueError("feature columns must be non-empty")
    forbidden = _forbidden_feature_columns(names)
    if forbidden:
        raise ValueError(
            "forbidden feature columns: " + ", ".join(sorted(forbidden))
        )
