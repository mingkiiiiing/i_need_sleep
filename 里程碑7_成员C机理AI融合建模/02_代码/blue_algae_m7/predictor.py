from datetime import date, timedelta

from blue_algae_m7.ai_models import MeanRegressor, WeightedRuleRegressor
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
}

SCALE_DAYS = {
    "short_term": [1, 2, 3],
    "mid_term": [7, 10, 15],
    "long_term": [30, 60, 90],
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
            for metric_code in ("chlorophyll_a", "bloom_area"):
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
    meta = METRIC_META[metric_code]
    if metric_code == "risk_level":
        return _risk_level(probability)
    return round(meta["base"] + meta["spread"] * probability, 3)


def _train_demo_models(rows):
    mean_model = MeanRegressor().fit(rows, "target")
    rule_model = WeightedRuleRegressor().fit(rows, "target")
    return mean_model, rule_model


def predict(station_id, forecast_scale, target_metrics):
    if forecast_scale not in SCALE_DAYS:
        raise ValueError(f"unsupported forecast_scale: {forecast_scale}")
    unsupported = [metric for metric in target_metrics if metric not in METRIC_META]
    if unsupported:
        raise ValueError(f"unsupported target_metrics: {unsupported}")

    rows = build_demo_rows()
    mean_model, rule_model = _train_demo_models(rows)
    base_date = date(2026, 8, 20)
    selected_rows = [
        row for row in rows if row["station_id"] == station_id and row["forecast_scale"] == forecast_scale
    ]
    if not selected_rows:
        selected_rows = [
            dict(row, station_id=station_id)
            for row in rows
            if row["forecast_scale"] == forecast_scale
        ]

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
                metric["lower_bound"] = round(meta["base"] + meta["spread"] * interval["lower"], 3)
                metric["upper_bound"] = round(meta["base"] + meta["spread"] * interval["upper"], 3)
            metrics.append(metric)
        results.append(
            {
                "date": (base_date + timedelta(days=horizon)).isoformat(),
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
        "claim_boundary": "sample_interface_only",
        "effect_claim_allowed": False,
        "model_family": "mechanism_ai_fusion_framework_v0.1",
        "results": results,
        "explainability": {
            "global_feature_importance": importance,
            "uncertainty": uncertainty_interval(probabilities, confidence=0.8),
        },
        "notes": [
            "Current output uses sample rows to verify member C interfaces.",
            "Replace build_demo_rows with aligned real labels and features before training claims.",
        ],
    }
