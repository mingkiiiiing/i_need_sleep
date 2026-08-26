import unittest

from blue_algae_m7.ai_models import MeanRegressor, WeightedRuleRegressor


class AiModelInterfaceTest(unittest.TestCase):
    def test_mean_regressor_predicts_training_target_mean(self):
        rows = [
            {"target": 0.2, "x": 1.0},
            {"target": 0.6, "x": 2.0},
            {"target": 1.0, "x": 3.0},
        ]

        model = MeanRegressor().fit(rows, "target")

        self.assertAlmostEqual(model.predict_one({"x": 99.0}), 0.6)
        self.assertEqual(model.model_name, "mean_regressor")

    def test_weighted_rule_regressor_uses_feature_direction(self):
        rows = [
            {"target": 0.1, "mechanism_score": 0.1, "wind_speed_m_s": 4.0},
            {"target": 0.8, "mechanism_score": 0.9, "wind_speed_m_s": 1.0},
        ]

        model = WeightedRuleRegressor(
            feature_weights={"mechanism_score": 0.8, "wind_speed_m_s": -0.1}
        ).fit(rows, "target")

        low = model.predict_one({"mechanism_score": 0.2, "wind_speed_m_s": 4.0})
        high = model.predict_one({"mechanism_score": 0.9, "wind_speed_m_s": 1.0})

        self.assertGreater(high, low)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)


if __name__ == "__main__":
    unittest.main()
