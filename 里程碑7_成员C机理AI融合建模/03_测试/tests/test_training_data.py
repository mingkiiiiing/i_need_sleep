import csv
import tempfile
import unittest
from pathlib import Path

from blue_algae_m7.training_data import (
    load_training_samples,
    to_predictor_rows,
    train_and_predict,
)


HEADER = [
    "sample_id", "date", "spatial_id", "spatial_type", "target_metric", "target_value",
    "target_unit", "label_status", "source_type", "quality_flag", "horizon_days", "issue_date",
    "water_temperature_C", "air_temperature_C", "total_phosphorus_mg_L", "total_nitrogen_mg_L",
    "solar_radiation_MJ_m2_day", "wind_speed_m_s", "chlorophyll_a_ug_L",
]

ROWS = [
    {
        "sample_id": "s1", "date": "2024-07-02", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "40.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "26.5",
        "air_temperature_C": "28.0", "total_phosphorus_mg_L": "0.09", "total_nitrogen_mg_L": "1.4",
        "solar_radiation_MJ_m2_day": "18.0", "wind_speed_m_s": "1.5", "chlorophyll_a_ug_L": "38.0",
    },
    {
        "sample_id": "s2", "date": "2024-07-04", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "spatial_extent", "target_value": "1.0", "target_unit": "0/1",
        "label_status": "simulation_positive", "source_type": "simulated", "quality_flag": "pass",
        "horizon_days": "3", "issue_date": "2024-07-01", "water_temperature_C": "27.5",
        "air_temperature_C": "29.0", "total_phosphorus_mg_L": "0.11", "total_nitrogen_mg_L": "1.5",
        "solar_radiation_MJ_m2_day": "20.0", "wind_speed_m_s": "1.2", "chlorophyll_a_ug_L": "45.0",
    },
    {
        "sample_id": "s3", "date": "2024-07-04", "spatial_id": "G0002", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "20.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "25.0",
        "air_temperature_C": "27.0", "total_phosphorus_mg_L": "", "total_nitrogen_mg_L": "1.2",
        "solar_radiation_MJ_m2_day": "17.0", "wind_speed_m_s": "2.0", "chlorophyll_a_ug_L": "18.0",
    },
    {
        "sample_id": "s4", "date": "2024-07-04", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "10.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "horizon_days": "3", "issue_date": "2024-07-01", "water_temperature_C": "27.0",
        "air_temperature_C": "28.5", "total_phosphorus_mg_L": "0.10", "total_nitrogen_mg_L": "1.3",
        "solar_radiation_MJ_m2_day": "19.0", "wind_speed_m_s": "1.8", "chlorophyll_a_ug_L": "9.0",
    },
]


class TrainingDataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.csv_path = Path(self._tmp.name) / "member_c_training_samples.csv"
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(ROWS)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_training_samples_filters_and_casts(self):
        rows = load_training_samples(self.csv_path)
        self.assertEqual(len(rows), 4)
        self.assertIsInstance(rows[0]["target_value"], float)
        self.assertIsInstance(rows[0]["horizon_days"], int)
        self.assertIsNone(rows[2]["total_phosphorus_mg_L"])

        filtered = load_training_samples(self.csv_path, metrics=["chlorophyll_a"], horizons=[1])
        self.assertEqual([row["sample_id"] for row in filtered], ["s1", "s3"])

        by_type = load_training_samples(self.csv_path, spatial_types=["region"])
        self.assertEqual(by_type, [])

    def test_to_predictor_rows_maps_and_skips(self):
        predictor_rows, skipped = to_predictor_rows(load_training_samples(self.csv_path))

        self.assertEqual(skipped["missing_mechanism_inputs"], 1)  # s3 缺 TP，不回退机理默认值
        self.assertEqual(len(predictor_rows), 3)

        row = next(r for r in predictor_rows if r["metric_code"] == "chlorophyll_a" and r["horizon_days"] == 1)
        self.assertEqual(row["station_id"], "G0001")
        self.assertEqual(row["forecast_scale"], "short_term")
        self.assertEqual(row["issue_date"], "2024-07-01")
        self.assertEqual(row["target"], 1.0)  # chla min-max: 40 为最大值
        self.assertGreaterEqual(row["mechanism_score"], 0.0)
        self.assertLessEqual(row["mechanism_score"], 1.0)

        degenerate = next(r for r in predictor_rows if r["metric_code"] == "spatial_extent")
        self.assertEqual(degenerate["target"], 0.5)  # 组内值唯一 → 0.5

    def test_train_and_predict_uses_real_rows(self):
        result = train_and_predict(
            self.csv_path, "G0001", "short_term", ["chlorophyll_a", "spatial_extent"]
        )

        self.assertEqual(result["claim_boundary"], "simulation_training_data_only")
        self.assertFalse(result["effect_claim_allowed"])
        self.assertEqual([item["horizon_days"] for item in result["results"]], [1, 3])
        self.assertEqual(result["results"][0]["date"], "2024-07-02")  # issue_date + horizon

        first_metrics = {m["metric_code"]: m for m in result["results"][0]["metrics"]}
        self.assertIn("spatial_extent", first_metrics)
        self.assertGreaterEqual(first_metrics["spatial_extent"]["lower_bound"], 0.0)
        self.assertLessEqual(first_metrics["spatial_extent"]["upper_bound"], 1.0)

        summary = result["training_summary"]
        self.assertEqual(summary["rows_loaded"], 4)
        self.assertEqual(summary["rows_usable"], 3)
        self.assertEqual(summary["skipped"]["missing_mechanism_inputs"], 1)

    def test_train_and_predict_rejects_unknown_station(self):
        with self.assertRaises(ValueError):
            train_and_predict(self.csv_path, "NO_SUCH", "short_term", ["chlorophyll_a"])

    def test_train_and_predict_rejects_empty_usable_rows(self):
        with self.assertRaises(ValueError):
            train_and_predict(
                self.csv_path, "G0002", "short_term", ["chlorophyll_a"]
            )  # G0002 唯一行缺 TP → 全跳过


if __name__ == "__main__":
    unittest.main()
