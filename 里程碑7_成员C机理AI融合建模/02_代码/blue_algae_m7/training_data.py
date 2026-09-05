"""数据工厂 member_c_training_samples.csv → 成员 C 训练行加载器.

纯 stdlib 实现（与 blue_algae_m7 运行时约束一致）。把契约 CSV 行映射为
predictor.predict(rows=...) 可用的训练行：spatial_id→station_id、
horizon_days→forecast_scale（与数据工厂 HORIZONS=(1,3,7,15,30) 对齐）、
按机理输入计算 mechanism_score、target_value 按指标 min-max 归一化到 [0,1]。

缺任一机理输入（水温/气温替代、TP、TN、辐射、风速）的行如实跳过并计数，
不回退到机理默认值——这正是 2026-09-05 接口收尾审计的缺口 #1。
"""

from __future__ import annotations

import csv
from pathlib import Path

from blue_algae_m7.mechanism import mechanism_risk_index
from blue_algae_m7.predictor import predict

HORIZON_TO_SCALE = {1: "short_term", 3: "short_term", 7: "mid_term", 15: "mid_term", 30: "long_term"}

INT_FIELDS = {"horizon_days"}
FLOAT_FIELDS = {
    "target_value",
    "water_temperature_C",
    "air_temperature_C",
    "total_phosphorus_mg_L",
    "total_nitrogen_mg_L",
    "ammonia_nitrogen_mg_L",
    "dissolved_oxygen_mg_L",
    "ph",
    "solar_radiation_MJ_m2_day",
    "wind_speed_m_s",
    "rainfall_mm_day",
    "relative_humidity_pct",
    "water_level_m",
    "chlorophyll_a_ug_L",
    "bloom_area_km2",
    "blue_algae_biomass_mg_L",
    "fai",
    "ndci",
}
MECHANISM_REQUIRED = ("total_phosphorus_mg_L", "total_nitrogen_mg_L", "solar_radiation_MJ_m2_day", "wind_speed_m_s")


def load_training_samples(csv_path, *, metrics=None, horizons=None, spatial_types=None, splits=None):
    """读取契约 CSV，返回 dict 行列表；数值列转 float/int，空串转 None。"""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"training csv not found: {path}")
    horizon_filter = {int(h) for h in horizons} if horizons is not None else None
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {}
            for key, value in raw.items():
                if key is None:
                    continue
                if value is None or value == "":
                    row[key] = None
                elif key in INT_FIELDS:
                    row[key] = int(float(value))
                elif key in FLOAT_FIELDS:
                    row[key] = float(value)
                else:
                    row[key] = value
            if metrics is not None and row.get("target_metric") not in metrics:
                continue
            if horizon_filter is not None and row.get("horizon_days") not in horizon_filter:
                continue
            if spatial_types is not None and row.get("spatial_type") not in spatial_types:
                continue
            if splits is not None and row.get("split") not in splits:
                continue
            rows.append(row)
    return rows


def _mechanism_temperature(row):
    if row.get("water_temperature_C") is not None:
        return row["water_temperature_C"]
    return row.get("air_temperature_C")


def to_predictor_rows(rows):
    """契约行 → predictor 训练行；返回 (predictor_rows, skipped_counts)。

    target 归一化：按 target_metric 分组 min-max；组内值全部相同时取 0.5（无区分度）。
    """
    values_by_metric = {}
    for row in rows:
        metric = row.get("target_metric")
        value = row.get("target_value")
        if metric is not None and value is not None:
            values_by_metric.setdefault(metric, []).append(value)
    ranges = {}
    for metric, values in values_by_metric.items():
        lo, hi = min(values), max(values)
        ranges[metric] = (lo, hi - lo)

    predictor_rows = []
    skipped = {"unsupported_horizon": 0, "missing_mechanism_inputs": 0, "missing_target": 0}
    for row in rows:
        horizon = row.get("horizon_days")
        scale = HORIZON_TO_SCALE.get(horizon) if horizon is not None else None
        if scale is None:
            skipped["unsupported_horizon"] += 1
            continue
        temp = _mechanism_temperature(row)
        if temp is None or any(row.get(field) is None for field in MECHANISM_REQUIRED):
            skipped["missing_mechanism_inputs"] += 1
            continue
        value = row.get("target_value")
        if value is None:
            skipped["missing_target"] += 1
            continue
        sample = {
            "station_id": row["spatial_id"],
            "forecast_scale": scale,
            "horizon_days": horizon,
            "metric_code": row["target_metric"],
            "issue_date": row.get("issue_date"),
            "split": row.get("split"),
            "water_temperature_C": temp,
            "total_phosphorus_mg_L": row["total_phosphorus_mg_L"],
            "total_nitrogen_mg_L": row["total_nitrogen_mg_L"],
            "solar_radiation_MJ_m2_day": row["solar_radiation_MJ_m2_day"],
            "wind_speed_m_s": row["wind_speed_m_s"],
        }
        sample["mechanism_score"] = mechanism_risk_index(sample)["risk_score"]
        lo, span = ranges[row["target_metric"]]
        sample["target"] = 0.5 if span == 0.0 else (value - lo) / span
        predictor_rows.append(sample)
    return predictor_rows, skipped


def train_and_predict(
    csv_path,
    station_id,
    forecast_scale,
    target_metrics,
    *,
    metrics=None,
    horizons=None,
    spatial_types=None,
    fit_split="train",
    eval_splits=("test",),
):
    """便捷入口：加载 CSV → 过滤 → train-only 拟合 → 预测 + 独立评估。

    只用 fit_split（默认 train）行拟合；eval_splits（默认 test）行用同一套
    已拟合模型评估、不参与拟合。metrics 缺省过滤为 target_metrics 本身。
    """
    if metrics is None:
        metrics = target_metrics
    rows = load_training_samples(csv_path, metrics=metrics, horizons=horizons, spatial_types=spatial_types)
    predictor_rows, skipped = to_predictor_rows(rows)
    fit_rows = [r for r in predictor_rows if r.get("split", fit_split) == fit_split]
    eval_rows = [r for r in predictor_rows if r.get("split") in set(eval_splits)] if eval_splits else []
    if not fit_rows:
        raise ValueError(
            f"no usable training rows in {csv_path} for fit_split={fit_split} "
            f"(loaded={len(rows)}, skipped={skipped})"
        )
    result = predict(station_id, forecast_scale, target_metrics, rows=fit_rows, eval_rows=eval_rows)
    result["training_summary"] = {
        "csv_path": str(csv_path),
        "rows_loaded": len(rows),
        "rows_fit": len(fit_rows),
        "fit_split": fit_split,
        "rows_eval": len(eval_rows),
        "eval_splits": list(eval_splits),
        "skipped": skipped,
    }
    return result
