import unittest

from blue_algae_m7.predictor import build_demo_rows, predict


class PredictorContractTest(unittest.TestCase):
    def test_build_demo_rows_contains_multiple_metrics_and_scales(self):
        rows = build_demo_rows()

        self.assertGreaterEqual(len(rows), 6)
        self.assertIn("chlorophyll_a", {row["metric_code"] for row in rows})
        self.assertIn("bloom_area", {row["metric_code"] for row in rows})
        self.assertIn("short_term", {row["forecast_scale"] for row in rows})

    def test_predict_returns_backend_compatible_json(self):
        result = predict(
            station_id="TH_CENTER",
            forecast_scale="short_term",
            target_metrics=["chlorophyll_a", "bloom_area"],
        )

        self.assertEqual(result["station_id"], "TH_CENTER")
        self.assertEqual(result["forecast_scale"], "short_term")
        self.assertEqual(result["claim_boundary"], "sample_interface_only")
        self.assertGreaterEqual(len(result["results"]), 1)

        first = result["results"][0]
        self.assertIn("date", first)
        self.assertIn("metrics", first)
        self.assertIn("risk_probability", first)
        self.assertIn("risk_level", first)
        self.assertEqual(
            {"chlorophyll_a", "bloom_area"},
            {metric["metric_code"] for metric in first["metrics"]},
        )

    def test_predict_returns_one_result_per_horizon(self):
        result = predict(
            station_id="TH_CENTER",
            forecast_scale="short_term",
            target_metrics=["chlorophyll_a", "bloom_area", "risk_level"],
        )

        horizons = [item["horizon_days"] for item in result["results"]]

        self.assertEqual([1, 3], horizons)
        self.assertEqual(len(horizons), len(set(horizons)))


if __name__ == "__main__":
    unittest.main()
