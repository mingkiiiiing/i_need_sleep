"""输出表 schema 契约与校验 (设计 §9/§12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .enums import LabelStatus


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str  # float|int|str|bool|datetime
    nullable: bool = True
    unit: str = ""
    enum: tuple[str, ...] | None = None
    description: str = ""


def f(name: str, dtype: str, **kw: Any) -> Field:
    return Field(name=name, dtype=dtype, **kw)


GRID_METADATA = [
    f("grid_id", "str", nullable=False, description="G{ix:04d}{iy:04d}"),
    f("grid_version", "str", nullable=False),
    f("lon", "float", nullable=False, unit="deg"),
    f("lat", "float", nullable=False, unit="deg"),
    f("utm_x", "float", nullable=False, unit="m"),
    f("utm_y", "float", nullable=False, unit="m"),
    f("water_fraction", "float", nullable=False, unit="1"),
    f("effective_water_area_m2", "float", nullable=False, unit="m2"),
    f("lake_zone", "str", nullable=False),
    f("zone_code", "str", nullable=False),
    f("shoreline_dist_m", "float", unit="m"),
    f("depth_mean_m", "float", unit="m"),
    f("is_edge", "bool", nullable=False, description="邻接网格不完整则视为岸边/边界单元"),
]

STATION_GRID_MAPPING = [
    f("station_id", "str", nullable=False),
    f("station_name", "str"),
    f("station_type", "str"),
    f("lon", "float", unit="deg"),
    f("lat", "float", unit="deg"),
    f("grid_id", "str"),
    f("lake_zone", "str"),
    f("zone_code", "str"),
    f("outside_boundary", "bool", nullable=False),
    f("mapping_status", "str", nullable=False, enum=("mapped", "outside_boundary", "bad_coordinates", "unmapped_no_grid_cell")),
    f("unmapped_reason", "str"),
    f("map_distance_m", "float"),
    f("provenance_type", "str", nullable=False, enum=("observed", "derived", "proxy", "forecast_input", "simulated", "metadata_only")),
    f("registry_source", "str", nullable=False),
]

BLOOM_GRID_DAILY = [
    f("grid_id", "str", nullable=False),
    f("date", "datetime", nullable=False),
    f("bloom_fraction", "float", nullable=False, unit="1"),
    f("bloom_area_m2", "float", nullable=False, unit="m2"),
    f("surface_biomass_mg_l", "float", unit="mg/L"),
    f("dataset_version", "str", nullable=False),
    f("source_type", "str", nullable=False, enum=("simulated",)),
    f("is_ground_truth", "bool", nullable=False, enum=(False,)),
    f("scenario_id", "str", nullable=False),
    f("random_seed", "int", nullable=False),
    f("parameter_set_id", "str", nullable=False),
    f("generator_version", "str", nullable=False),
    f("generation_batch_id", "str", nullable=False),
]

BLOOM_LAKE_DAILY = [
    f("date", "datetime", nullable=False),
    f("spatial_id", "str", nullable=False, description="湖区 zone_code 或 TAIHU_WHOLE"),
    f("bloom_area_km2", "float", nullable=False, unit="km2"),
    f("bloom_fraction_mean", "float", unit="1"),
    f("effective_water_area_km2", "float", unit="km2"),
    f("domain_coverage_km2", "float", nullable=False, unit="km2", description="仿真有效面积（DG-001 部分域显式化）"),
    f("domain_coverage_fraction", "float", nullable=False, unit="1", description="仿真有效面积/冻结全湖面积"),
    f("is_partial_domain", "bool", nullable=False),
    f("dataset_version", "str", nullable=False),
    f("source_type", "str", nullable=False, enum=("simulated",)),
    f("is_ground_truth", "bool", nullable=False),
    f("scenario_id", "str", nullable=False),
    f("random_seed", "int", nullable=False),
    f("parameter_set_id", "str", nullable=False),
    f("generator_version", "str", nullable=False),
    f("generation_batch_id", "str", nullable=False),
]

TASK_LABELS = [
    f("task_id", "str", nullable=False, enum=tuple(f"T{i}" for i in range(1, 8))),
    f("spatial_id", "str", nullable=False),
    f("spatial_type", "str", nullable=False, enum=("grid", "zone", "lake", "station")),
    f("issue_date", "datetime", nullable=False),
    f("target_date", "datetime", nullable=False),
    f("label_value", "float"),
    f("label_unit", "str"),
    f("label_status", "str", nullable=False, enum=tuple(s.value for s in LabelStatus)),
    f("label_source_type", "str", nullable=False, enum=("simulation_truth", "satellite_observation", "station_observation", "threshold_rule")),
    f("label_quality", "str", nullable=False, enum=("pass", "warning", "fail")),
    f("horizon_days", "int", nullable=False),
    f("is_ground_truth", "bool", nullable=False),
    f("is_synthetic", "bool", nullable=False),
    f("method_version", "str", nullable=False),
    f("domain_coverage_fraction", "float", nullable=False, unit="1", description="标签所涉空间域的仿真覆盖率（grid/zone/station=1.0，lake=仿真面积/冻结全湖面积，DG-001）"),
    f("is_partial_domain", "bool", nullable=False),
    f("evidence_record_ids", "str"),
    f("dataset_version", "str", nullable=False),
]

STATION_OBSERVATIONS = [
    f("station_id", "str", nullable=False),
    f("station_name", "str"),
    f("grid_id", "str"),
    f("observed_time", "datetime", nullable=False),
    f("available_time", "datetime", nullable=False),
    f("variable_code", "str", nullable=False),
    f("value", "float"),
    f("unit", "str"),
    f("detection_limit", "float"),
    f("measurement_error_pct", "float"),
    f("quality_flag", "str", nullable=False),
    f("missing_reason", "str"),
    f("value_type", "str", nullable=False, enum=("simulated", "observed")),
    f("is_ground_truth", "bool", nullable=False),
    f("is_synthetic", "bool", nullable=False),
    f("source_type", "str", nullable=False),
    f("parent_record_ids", "str"),
    f("generator_version", "str", nullable=False),
    f("generation_batch_id", "str", nullable=False),
]

SATELLITE_OBSERVATIONS = [
    f("grid_id", "str", nullable=False),
    f("observed_time", "datetime", nullable=False),
    f("available_time", "datetime", nullable=False),
    f("variable_code", "str", nullable=False, enum=("ndci", "fai", "mci", "chla_retrieval")),
    f("value", "float"),
    f("unit", "str"),
    f("coverage_ratio", "float"),
    f("quality_flag", "str", nullable=False),
    f("missing_reason", "str"),
    f("value_type", "str", nullable=False),
    f("is_ground_truth", "bool", nullable=False),
    f("is_synthetic", "bool", nullable=False),
    f("source_type", "str", nullable=False),
    f("parent_record_ids", "str"),
    f("generator_version", "str", nullable=False),
    f("generation_batch_id", "str", nullable=False),
]

MODEL_TRAINING_SAMPLES = [
    f("sample_id", "str", nullable=False),
    f("spatial_id", "str", nullable=False),
    f("spatial_type", "str", nullable=False),
    f("issue_date", "datetime", nullable=False),
    f("target_date", "datetime", nullable=False),
    f("target_metric", "str", nullable=False),
    f("horizon_days", "int", nullable=False),
    f("label_value", "float"),
    f("label_unit", "str"),
    f("label_status", "str", nullable=False),
    f("label_source_type", "str", nullable=False),
    f("quality_flag", "str", nullable=False),
    f("split", "str", nullable=False, enum=("train", "validation", "test")),
    f("feature_window_note", "str"),
    f("dataset_version", "str", nullable=False),
    f("source_type", "str", nullable=False),
    f("is_ground_truth", "bool", nullable=False),
    f("is_synthetic", "bool", nullable=False),
    f("domain_coverage_fraction", "float", nullable=False, unit="1"),
    f("is_partial_domain", "bool", nullable=False),
    f("feature_observed_ratio", "float", unit="1", description="特征窗口内非缺失特征占比（DG-004 观测层特征缺测如实标注）"),
    f("features_json", "str", nullable=False),
]

PARAMETER_SETS = [
    f("parameter_set_id", "str", nullable=False),
    f("family", "str", nullable=False, enum=("weather", "water_temp", "nutrients", "algae", "hydrology", "obs")),
    f("scope_type", "str", nullable=False, enum=("global", "zone", "station", "month")),
    f("scope_id", "str", nullable=False),
    f("variable_code", "str"),
    f("parameter_key", "str", nullable=False),
    f("value", "float"),
    f("unit", "str"),
    f("n_samples", "int", nullable=False),
    f("method", "str", nullable=False),
    f("fitted_at_utc", "str", nullable=False),
]

ROW_LINEAGE = [
    f("record_id", "str", nullable=False),
    f("stage", "str", nullable=False),
    f("parent_record_ids", "str"),
    f("transformation", "str", nullable=False),
    f("generator_version", "str", nullable=False),
    f("scenario_id", "str"),
    f("random_seed", "int"),
    f("parameter_set_id", "str"),
    f("generation_batch_id", "str"),
    f("created_at_utc", "str", nullable=False),
]

SPLIT_MANIFEST = [
    f("date", "datetime", nullable=False),
    f("split", "str", nullable=False, enum=("train", "validation", "test", "isolation")),
    f("isolation_window", "bool", nullable=False),
]

SCHEMAS: dict[str, list[Field]] = {
    "grid_metadata": GRID_METADATA,
    "station_grid_mapping": STATION_GRID_MAPPING,
    "bloom_grid_daily": BLOOM_GRID_DAILY,
    "bloom_lake_daily": BLOOM_LAKE_DAILY,
    "task_labels": TASK_LABELS,
    "station_observations": STATION_OBSERVATIONS,
    "satellite_observations": SATELLITE_OBSERVATIONS,
    "model_training_samples": MODEL_TRAINING_SAMPLES,
    "parameter_sets": PARAMETER_SETS,
    "row_lineage": ROW_LINEAGE,
    "split_manifest": SPLIT_MANIFEST,
}

# DG-008：任务×粒度契约矩阵（仿真真值粒度显式登记）。
# station 粒度仅 T3/T4/T5 观测标签（真实采样日历驱动），见 TASK_GRAIN_OBSERVATION_EXTRA；
# 超出矩阵的粒度组合（如全湖 T3）未获契约支持。
TASK_GRAIN_MATRIX: dict[str, tuple[str, ...]] = {
    "T1": ("grid", "zone", "lake"),
    "T2": ("grid", "zone", "lake"),
    "T3": ("zone", "lake"),
    "T4": ("zone", "lake"),
    "T5": ("grid", "zone", "lake"),
    "T6": ("zone", "lake"),
    "T7": ("zone", "lake"),
}
TASK_GRAIN_OBSERVATION_EXTRA: dict[str, tuple[str, ...]] = {"T3": ("station",), "T4": ("station",), "T5": ("station",)}


def validate_schema(df: pd.DataFrame, table: str, *, strict: bool = False) -> list[str]:
    """返回 schema 违规清单；strict=True 时额外检查多余列。"""

    fields = SCHEMAS.get(table)
    if fields is None:
        return [f"unknown table schema: {table}"]
    issues: list[str] = []
    columns = set(df.columns)
    for spec in fields:
        if spec.name not in columns:
            if not spec.nullable:
                issues.append(f"{table}.{spec.name}: missing required column")
            continue
        series = df[spec.name]
        if not spec.nullable and series.isna().any():
            issues.append(f"{table}.{spec.name}: nulls in non-nullable column")
        if spec.enum is not None:
            values = set(series.dropna().unique().tolist())
            allowed = set(spec.enum)
            unexpected = values - allowed
            if unexpected:
                issues.append(f"{table}.{spec.name}: values outside enum: {sorted(map(str, unexpected))[:5]}")
    if strict:
        expected = {s.name for s in fields}
        extra = columns - expected
        if extra:
            issues.append(f"{table}: unexpected columns: {sorted(extra)[:5]}")
    return issues
