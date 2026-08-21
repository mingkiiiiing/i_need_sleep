import unittest

from blue_algae_m7.mechanism import (
    mechanism_risk_index,
    monod_limit,
    temperature_limit,
)


class MechanismModelTest(unittest.TestCase):
    def test_monod_limit_increases_with_resource(self):
        low = monod_limit(0.02, 0.05)
        high = monod_limit(0.20, 0.05)

        self.assertGreater(high, low)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_temperature_limit_peaks_near_optimum(self):
        near_optimum = temperature_limit(28.0)
        cold = temperature_limit(10.0)
        hot = temperature_limit(36.0)

        self.assertGreater(near_optimum, cold)
        self.assertGreater(near_optimum, hot)

    def test_mechanism_risk_index_returns_explainable_components(self):
        sample = {
            "water_temperature_C": 29.0,
            "total_phosphorus_mg_L": 0.08,
            "total_nitrogen_mg_L": 1.2,
            "solar_radiation_MJ_m2_day": 20.0,
            "wind_speed_m_s": 1.2,
        }

        result = mechanism_risk_index(sample)

        self.assertEqual(result["model"], "logistic_monod_mechanism")
        self.assertGreater(result["risk_score"], 0.0)
        self.assertLessEqual(result["risk_score"], 1.0)
        self.assertIn("temperature_limit", result["components"])
        self.assertIn("phosphorus_limit", result["components"])


if __name__ == "__main__":
    unittest.main()
