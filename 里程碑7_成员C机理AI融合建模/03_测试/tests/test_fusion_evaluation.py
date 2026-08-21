import unittest

from blue_algae_m7.evaluation import classification_metrics, regression_metrics
from blue_algae_m7.explainability import (
    feature_importance_by_correlation,
    sensitivity_curve,
    uncertainty_interval,
)
from blue_algae_m7.fusion import cascade_fusion, residual_fusion


class FusionEvaluationTest(unittest.TestCase):
    def test_cascade_fusion_stays_bounded(self):
        fused = cascade_fusion(0.9, 0.4, mechanism_weight=0.25)

        self.assertAlmostEqual(fused, 0.525)
        self.assertGreaterEqual(fused, 0.0)
        self.assertLessEqual(fused, 1.0)

    def test_residual_fusion_adds_residual_then_clips(self):
        self.assertEqual(residual_fusion(0.8, 0.5), 1.0)
        self.assertEqual(residual_fusion(0.2, -0.5), 0.0)

    def test_regression_metrics_report_basic_errors(self):
        metrics = regression_metrics([1.0, 2.0, 3.0], [1.0, 2.5, 2.5])

        self.assertAlmostEqual(metrics["mae"], 1.0 / 3.0)
        self.assertAlmostEqual(metrics["rmse"], (0.5 / 3.0) ** 0.5)
        self.assertIn("r2", metrics)

    def test_classification_metrics_report_precision_recall_f1(self):
        metrics = classification_metrics([1, 0, 1, 0], [1, 1, 0, 0])

        self.assertAlmostEqual(metrics["precision"], 0.5)
        self.assertAlmostEqual(metrics["recall"], 0.5)
        self.assertAlmostEqual(metrics["f1"], 0.5)

    def test_feature_importance_orders_correlated_feature_first(self):
        rows = [
            {"target": 0.1, "temp": 10.0, "noise": 7.0},
            {"target": 0.5, "temp": 20.0, "noise": 7.0},
            {"target": 0.9, "temp": 30.0, "noise": 7.0},
        ]

        ranking = feature_importance_by_correlation(rows, ["temp", "noise"], "target")

        self.assertEqual(ranking[0]["feature"], "temp")
        self.assertGreater(ranking[0]["importance"], ranking[1]["importance"])

    def test_uncertainty_interval_uses_prediction_distribution(self):
        interval = uncertainty_interval([0.2, 0.4, 0.8, 0.9], confidence=0.5)

        self.assertEqual(interval["method"], "empirical_prediction_interval")
        self.assertGreaterEqual(interval["upper"], interval["lower"])
        self.assertGreaterEqual(interval["mean"], interval["lower"])
        self.assertLessEqual(interval["mean"], interval["upper"])

    def test_sensitivity_curve_changes_one_feature(self):
        def scoring(row):
            return row["water_temperature_C"] / 40.0

        curve = sensitivity_curve(
            {"water_temperature_C": 20.0},
            "water_temperature_C",
            [10.0, 20.0, 30.0],
            scoring,
        )

        self.assertEqual([point["feature_value"] for point in curve], [10.0, 20.0, 30.0])
        self.assertLess(curve[0]["score"], curve[-1]["score"])


if __name__ == "__main__":
    unittest.main()
