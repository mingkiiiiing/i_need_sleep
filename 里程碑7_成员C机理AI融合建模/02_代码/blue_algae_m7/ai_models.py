def _clip01(value):
    return max(0.0, min(1.0, float(value)))


class MeanRegressor:
    model_name = "mean_regressor"

    def __init__(self):
        self.mean_ = 0.0
        self.fitted_ = False

    def fit(self, rows, target_key):
        values = [float(row[target_key]) for row in rows if target_key in row]
        if not values:
            raise ValueError("training rows must contain target values")
        self.mean_ = sum(values) / len(values)
        self.fitted_ = True
        return self

    def predict_one(self, row):
        if not self.fitted_:
            raise RuntimeError("model must be fitted before prediction")
        return _clip01(self.mean_)


class WeightedRuleRegressor:
    model_name = "weighted_rule_regressor"

    def __init__(self, feature_weights=None):
        self.feature_weights = feature_weights or {
            "mechanism_score": 0.65,
            "water_temperature_C": 0.012,
            "solar_radiation_MJ_m2_day": 0.008,
            "wind_speed_m_s": -0.06,
        }
        self.bias_ = 0.0
        self.fitted_ = False

    def fit(self, rows, target_key):
        if not rows:
            raise ValueError("training rows must not be empty")
        target_values = [float(row[target_key]) for row in rows if target_key in row]
        if not target_values:
            raise ValueError("training rows must contain target values")
        raw_scores = [self._raw_score(row) for row in rows]
        self.bias_ = (sum(target_values) / len(target_values)) - (
            sum(raw_scores) / len(raw_scores)
        )
        self.fitted_ = True
        return self

    def _raw_score(self, row):
        return sum(float(row.get(key, 0.0)) * weight for key, weight in self.feature_weights.items())

    def predict_one(self, row):
        if not self.fitted_:
            raise RuntimeError("model must be fitted before prediction")
        return _clip01(self.bias_ + self._raw_score(row))

