from datetime import date, timedelta

from blue_algae_m7.ai_models import MeanRegressor, WeightedRuleRegressor
from blue_algae_m7.evaluation import classification_metrics, ordinal_classification_metrics, regression_metrics
from blue_algae_m7.explainability import (
    feature_importance_by_correlation,
    uncertainty_interval,
)
from blue_algae_m7.fusion import cascade_fusion, residual_fusion
from blue_algae_m7.mechanism import mechanism_risk_index


METRIC_META = {
    "chlorophyll_a": {"name": "叶绿素a", "unit": "ug/L", "base": 35.0, "spread": 18.0},
    "bloom_area": {"name": "水华面积", "unit": "km2", "base": 2.0, "spread": 4.5},
    "blue_algae_biomass": {"name": "蓝藻生物量", "unit": "mg/L", "base": 0.8, "spread": 1.2},
    "risk_level": {"name": "风险等级", "unit": "level", "base": 0.0, "spread": 1.0},
    "blue_algae_density": {"name": "蓝藻密度", "unit": "10^4 cells/L", "base": 30.0, "spread": 270.0},
    "spatial_extent": {"name": "空间范围", "unit": "0/1"},
    "bloom_label": {"name": "水华发生", "unit": "0/1"},
}

# 概率型目标：value 即 probability（0/1 空间），无 base/spread 映射
PROBABILITY_METRICS = {"spatial_extent", "bloom_label"}
# 0/1 二值目标：独立评估时输出二分类指标（risk_level 是 0–3 有序等级，不属于此列）
BINARY_METRICS = {"spatial_extent", "bloom_label"}
# 有序等级目标：预测类按 _risk_level 分带映射，评估输出四分类指标
RISK_LEVEL_CLASSES = ("none", "low", "medium", "high")

# 与数据工厂 HORIZONS=(1,3,7,15,30) 统一（2026-09-05 接口收尾决议）
SCALE_DAYS = {
    "short_term": [1, 3],
    "mid_term": [7, 15],
    "long_term": [30],
}


def _risk_level(probability):
    if probability >= 0.75:
        return "high"
    if probability >= 0.50:
        return "medium"
    if probability >= 0.25:
        return "low"
    return "none"


def build_demo_rows():
    rows = []
    for scale, horizons in SCALE_DAYS.items():
        for horizon in horizons:
            for metric_code in ("chlorophyll_a", "bloom_area", "blue_algae_density", "spatial_extent", "bloom_label"):
                temp = 24.0 + min(horizon, 15) * 0.25
                wind = max(0.6, 2.8 - horizon * 0.04)
                sample = {
                    "station_id": "TH_CENTER",
                    "forecast_scale": scale,
                    "horizon_days": horizon,
                    "metric_code": metric_code,
                    "water_temperature_C": temp,
                    "total_phosphorus_mg_L": 0.06 + horizon * 0.001,
                    "total_nitrogen_mg_L": 1.0,
                    "solar_radiation_MJ_m2_day": 16.0 + min(horizon, 10) * 0.2,
                    "wind_speed_m_s": wind,
                }
                mechanism = mechanism_risk_index(sample)
                sample["mechanism_score"] = mechanism["risk_score"]
                sample["target"] = min(1.0, sample["mechanism_score"] * 0.85 + 0.08)
                rows.append(sample)
    return rows


def _metric_value(metric_code, probability):
    if metric_code == "risk_level":
        return _risk_level(probability)
    if metric_code in PROBABILITY_METRICS:
        return round(probability, 4)
    meta = METRIC_META[metric_code]
    return round(meta["base"] + meta["spread"] * probability, 3)


def _train_models(rows):
    mean_model = MeanRegressor().fit(rows, "target")
    rule_model = WeightedRuleRegressor().fit(rows, "target")
    return mean_model, rule_model


def predict(station_id, forecast_scale, target_metrics, rows=None, eval_rows=None):
    """rows=None 走内置演示样本；传入数据工厂训练行时全链路用真实数据训练与预测。

    eval_rows：用同一套已拟合模型做独立评估（按 split 分组），不参与拟合。
    """
    if forecast_scale not in SCALE_DAYS:
        raise ValueError(f"unsupported forecast_scale: {forecast_scale}")
    unsupported = [metric for metric in target_metrics if metric not in METRIC_META]
    if unsupported:
        raise ValueError(f"unsupported target_metrics: {unsupported}")

    demo = rows is None
    if demo:
        rows = build_demo_rows()
    mean_model, rule_model = _train_models(rows)
    base_date = date(2026, 8, 20)
    selected_rows = [
        row for row in rows if row["station_id"] == station_id and row["forecast_scale"] == forecast_scale
    ]
    if not selected_rows:
        if demo:
            selected_rows = [
                dict(row, station_id=station_id)
                for row in rows
                if row["forecast_scale"] == forecast_scale
            ]
        else:
            raise ValueError(
                f"no training rows for station_id={station_id}, forecast_scale={forecast_scale}"
            )

    results = []
    probabilities = []
    rows_by_horizon = {}
    for row in selected_rows:
        rows_by_horizon.setdefault(int(row["horizon_days"]), row)

    for horizon in sorted(rows_by_horizon):
        row = rows_by_horizon[horizon]
        mechanism_score = row["mechanism_score"]
        ai_score = rule_model.predict_one(row)
        residual_score = ai_score - mean_model.predict_one(row)
        cascade_score = cascade_fusion(mechanism_score, ai_score)
        probability = residual_fusion(cascade_score, residual_score * 0.3)
        probabilities.append(probability)
        metrics = []
        for metric_code in target_metrics:
            meta = METRIC_META[metric_code]
            value = _metric_value(metric_code, probability)
            metric = {
                "metric_code": metric_code,
                "metric_name": meta["name"],
                "value": value,
                "unit": meta["unit"],
            }
            if metric_code != "risk_level":
                interval = uncertainty_interval(
                    [max(0.0, probability - 0.08), probability, min(1.0, probability + 0.08)],
                    confidence=0.8,
                )
                if metric_code in PROBABILITY_METRICS:
                    metric["lower_bound"] = round(max(0.0, interval["lower"]), 4)
                    metric["upper_bound"] = round(min(1.0, interval["upper"]), 4)
                else:
                    metric["lower_bound"] = round(meta["base"] + meta["spread"] * interval["lower"], 3)
                    metric["upper_bound"] = round(meta["base"] + meta["spread"] * interval["upper"], 3)
            metrics.append(metric)
        issue_date = row.get("issue_date")
        if issue_date:
            result_date = (date.fromisoformat(str(issue_date)[:10]) + timedelta(days=horizon)).isoformat()
        else:
            result_date = (base_date + timedelta(days=horizon)).isoformat()
        results.append(
            {
                "date": result_date,
                "horizon_days": horizon,
                "metrics": metrics,
                "risk_probability": round(probability, 4),
                "risk_level": _risk_level(probability),
                "model_outputs": {
                    "mechanism_score": round(mechanism_score, 4),
                    "ai_model_1": round(mean_model.predict_one(row), 4),
                    "ai_model_2": round(ai_score, 4),
                    "cascade_fusion": round(cascade_score, 4),
                    "residual_fusion": round(probability, 4),
                },
            }
        )

    evaluations = {}
    if eval_rows:
        grouped = {}
        for row in eval_rows:
            grouped.setdefault(row.get("split", "unknown"), []).append(row)
        for split, group_rows in sorted(grouped.items()):
            y_true = []
            y_prob = []
            y_true_raw = []
            for row in group_rows:
                ai = rule_model.predict_one(row)
                residual = ai - mean_model.predict_one(row)
                probability = residual_fusion(cascade_fusion(row["mechanism_score"], ai), residual * 0.3)
                y_true.append(row["target"])
                y_true_raw.append(row["target_raw"])
                y_prob.append(probability)
            entry = {
                "n": len(y_true),
                "metric_codes": sorted({row["metric_code"] for row in group_rows}),
                "target_space": "per_metric_minmax_0_1",
                "regression": regression_metrics(y_true, y_prob),
            }
            if all(row["metric_code"] in BINARY_METRICS for row in group_rows):
                entry["classification"] = classification_metrics(
                    y_true, [1 if p >= 0.5 else 0 for p in y_prob]
                )
            elif all(row["metric_code"] == "risk_level" for row in group_rows):
                entry["ordinal_classification"] = ordinal_classification_metrics(
                    [int(round(float(raw))) for raw in y_true_raw],
                    [RISK_LEVEL_CLASSES.index(_risk_level(p)) for p in y_prob],
                    len(RISK_LEVEL_CLASSES),
                )
            evaluations[split] = entry

    importance = feature_importance_by_correlation(
        rows,
        [
            "mechanism_score",
            "water_temperature_C",
            "solar_radiation_MJ_m2_day",
            "wind_speed_m_s",
        ],
        "target",
    )
    return {
        "station_id": station_id,
        "forecast_scale": forecast_scale,
        "claim_boundary": "sample_interface_only" if demo else "simulation_training_data_only",
        "effect_claim_allowed": False,
        "model_family": "mechanism_ai_fusion_framework_v0.1",
        "results": results,
        "evaluations": evaluations,
        "explainability": {
            "global_feature_importance": importance,
            "uncertainty": uncertainty_interval(probabilities, confidence=0.8),
        },
        "notes": (
            [
                "Current output uses sample rows to verify member C interfaces.",
                "Replace build_demo_rows with aligned real labels and features before training claims.",
            ]
            if demo
            else [
                "Trained and predicted on caller-supplied rows (data factory member_c_training_samples).",
                "SIM-V1 synthetic data: effect claims remain disallowed.",
                "spatial_extent is a zone/lake connectivity label (0/1); grid-level geometry is not predicted.",
            ]
        ),
    }
