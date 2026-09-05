"""成员 C 训练契约适配器 (设计 §12 / required_training_schema_V0.1.csv).

列对齐 required 11 列 + recommended 特征列。
2026-09-05 接口收尾：T3(blue_algae_density)/T7(spatial_extent) 经契约评审正式进入
target_metric 枚举；label_status=simulation_* 与 source_type=simulated 仍为枚举外延，
原样保留并登记为开放问题，不伪造成 observed_*。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from data_factory.contracts.enums import MEMBER_C_METRICS

# 训练样本 target_metric(task_id) → 成员 C target_metric 枚举（T1–T7 全部正式接收）
TASK_TO_MEMBER_C = {
    "T1": "bloom_label",
    "T2": "bloom_area",
    "T3": "blue_algae_density",
    "T4": "blue_algae_biomass",
    "T5": "chlorophyll_a",
    "T6": "risk_level",
    "T7": "spatial_extent",
}

FEATURE_COLUMNS = {
    "water_temperature": "water_temperature_C",
    "air_temperature": "air_temperature_C",
    "total_phosphorus": "total_phosphorus_mg_L",
    "total_nitrogen": "total_nitrogen_mg_L",
    "ammonia_nitrogen": "ammonia_nitrogen_mg_L",
    "dissolved_oxygen": "dissolved_oxygen_mg_L",
    "pH": "ph",
    "shortwave_radiation": "solar_radiation_MJ_m2_day",
    "wind_speed": "wind_speed_m_s",
    "precipitation": "rainfall_mm_day",
    "relative_humidity": "relative_humidity_pct",
    "water_level": "water_level_m",
    "chlorophyll_a": "chlorophyll_a_ug_L",
    "bloom_area_km2": "bloom_area_km2",
    "blue_algae_biomass": "blue_algae_biomass_mg_L",
    "fai": "fai",
    "ndci": "ndci",
}

VALUE_UNIT_BY_METRIC = {
    "bloom_label": "0/1",
    "bloom_area": "km2",
    "blue_algae_biomass": "mg/L",
    "chlorophyll_a": "ug/L",
    "risk_level": "level",
    "blue_algae_density": "10^4 cells/L",
    "spatial_extent": "0/1",
}


def to_member_c(samples: pd.DataFrame, *, track: str = "SIM-V1") -> tuple[pd.DataFrame, dict[str, Any]]:
    """model_training_samples → 成员 C 训练表。返回 (frame, 摘要)。"""

    frame = samples.copy()
    frame["member_c_metric"] = frame["target_metric"].map(TASK_TO_MEMBER_C)
    supported = frame["member_c_metric"].isin(MEMBER_C_METRICS)
    excluded = int((~supported).sum())
    frame = frame[supported]

    features = frame["features_json"].map(json.loads)
    out = pd.DataFrame(index=frame.index)
    out["sample_id"] = frame["sample_id"]
    out["date"] = pd.to_datetime(frame["target_date"]).dt.strftime("%Y-%m-%d")
    out["spatial_id"] = frame["spatial_id"]
    out["spatial_type"] = frame["spatial_type"]
    out["target_metric"] = frame["member_c_metric"]
    out["target_value"] = frame["label_value"]
    out["target_unit"] = frame["member_c_metric"].map(VALUE_UNIT_BY_METRIC)
    out["label_status"] = frame["label_status"]
    out["source_type"] = "simulated" if track.startswith("SIM") else frame["source_type"]
    out["quality_flag"] = frame["quality_flag"]
    out["label_status_evidence"] = frame["label_source_type"]
    out["horizon_days"] = frame["horizon_days"]
    out["issue_date"] = pd.to_datetime(frame["issue_date"]).dt.strftime("%Y-%m-%d")
    out["data_track"] = track
    out["dataset_version"] = frame["dataset_version"]
    out["split"] = frame["split"]
    for identity_col in ("scenario_id", "random_seed", "driver_type", "driver_hash"):
        if identity_col in frame.columns:
            out[identity_col] = frame[identity_col]
    out["feature_window_note"] = frame["feature_window_note"]

    for internal, external in FEATURE_COLUMNS.items():
        out[external] = features.map(lambda d, k=internal: d.get(k))
    out["source_file"] = "data_factory assembly model_training_samples.parquet"

    # DG-004：观测层特征缺测如实呈现为空值，并在摘要中标注缺失率
    feature_missing_rates = {
        external: round(float(out[external].isna().mean()), 4) for external in FEATURE_COLUMNS.values() if external in out.columns and len(out)
    }

    column_order = [c for c in out.columns if c != "source_file"] + ["source_file"]
    summary = {
        "rows": int(len(out)),
        "rows_excluded_open_enum": excluded,
        "open_enum_note": "生物量(T4 mg/L)与密度(T3 10^4 cells/L)为独立目标且单位已入契约枚举；spatial_type 含 zone|lake 为湖区/全湖聚合粒度；label_status=simulation_* 与 source_type=simulated 已纳入 V0.1 枚举（2026-09-05 验收第二轮对齐）",
        "metrics": {k: int(v) for k, v in out.groupby("target_metric").size().items()} if not out.empty else {},
        "label_statuses": {k: int(v) for k, v in out.groupby("label_status").size().items()} if not out.empty else {},
        "feature_missing_rates": feature_missing_rates,
        "feature_note": "DG-004 特征装配（df-0.3.0）：气象=仿真 run 驱动表（observed_replay 真实历史重放或合成气候态），grid 逐格、zone/lake 均值，与标签同源（driver_hash 逐行携带）；water_temperature/total_phosphorus/total_nitrogen 来自站点观测（TP/TN 为仿真观测层，含测量误差与发布延迟）；chlorophyll_a/bloom_fraction 来自卫星观测，缺过境/采样日为空值；latent 变量（水位/生物量/密度）不作为特征输出",
    }
    return out[column_order], summary


def write_member_c_csv(samples: pd.DataFrame, out_path: Path, *, track: str = "SIM-V1") -> dict[str, Any]:
    frame, summary = to_member_c(samples, track=track)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_path, index=False, encoding="utf-8")
    summary["output"] = str(out_path)
    return summary
