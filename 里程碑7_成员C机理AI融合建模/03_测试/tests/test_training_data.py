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
    "target_unit", "label_status", "source_type", "quality_flag", "split", "horizon_days",
    "issue_date", "water_temperature_C", "air_temperature_C", "total_phosphorus_mg_L",
    "total_nitrogen_mg_L", "solar_radiation_MJ_m2_day", "wind_speed_m_s", "chlorophyll_a_ug_L",
]

ROWS = [
    {
        "sample_id": "s1", "date": "2024-07-02", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "40.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "split": "train", "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "26.5",
        "air_temperature_C": "28.0", "total_phosphorus_mg_L": "0.09", "total_nitrogen_mg_L": "1.4",
        "solar_radiation_MJ_m2_day": "18.0", "wind_speed_m_s": "1.5", "chlorophyll_a_ug_L": "38.0",
    },
    {
        "sample_id": "s2", "date": "2024-07-04", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "spatial_extent", "target_value": "1.0", "target_unit": "0/1",
        "label_status": "simulation_positive", "source_type": "simulated", "quality_flag": "pass",
        "split": "train", "horizon_days": "3", "issue_date": "2024-07-01", "water_temperature_C": "27.5",
        "air_temperature_C": "29.0", "total_phosphorus_mg_L": "0.11", "total_nitrogen_mg_L": "1.5",
        "solar_radiation_MJ_m2_day": "20.0", "wind_speed_m_s": "1.2", "chlorophyll_a_ug_L": "45.0",
    },
    {
        "sample_id": "s3", "date": "2024-07-04", "spatial_id": "G0002", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "20.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "split": "train", "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "25.0",
        "air_temperature_C": "27.0", "total_phosphorus_mg_L": "", "total_nitrogen_mg_L": "1.2",
        "solar_radiation_MJ_m2_day": "17.0", "wind_speed_m_s": "2.0", "chlorophyll_a_ug_L": "18.0",
    },
    {
        "sample_id": "s4", "date": "2024-07-04", "spatial_id": "G0001", "spatial_type": "grid",
        "target_metric": "chlorophyll_a", "target_value": "10.0", "target_unit": "ug/L",
        "label_status": "measured_value", "source_type": "simulated", "quality_flag": "pass",
        "split": "test", "horizon_days": "3", "issue_date": "2024-07-01", "water_temperature_C": "27.0",
        "air_temperature_C": "28.5", "total_phosphorus_mg_L": "0.10", "total_nitrogen_mg_L": "1.3",
        "solar_radiation_MJ_m2_day": "19.0", "wind_speed_m_s": "1.8", "chlorophyll_a_ug_L": "9.0",
    },
    {
        "sample_id": "s5", "date": "2024-07-02", "spatial_id": "G0001", "spatial_type": "zone",
        "target_metric": "bloom_label", "target_value": "1.0", "target_unit": "0/1",
        "label_status": "simulation_positive", "source_type": "simulated", "quality_flag": "pass",
        "split": "train", "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "26.8",
        "air_temperature_C": "28.2", "total_phosphorus_mg_L": "0.095", "total_nitrogen_mg_L": "1.45",
        "solar_radiation_MJ_m2_day": "18.5", "wind_speed_m_s": "1.4", "chlorophyll_a_ug_L": "41.0",
    },
    {
        "sample_id": "s6", "date": "2024-07-02", "spatial_id": "G0001", "spatial_type": "zone",
        "target_metric": "spatial_extent", "target_value": "1.0", "target_unit": "0/1",
        "label_status": "simulation_positive", "source_type": "simulated", "quality_flag": "pass",
        "split": "test", "horizon_days": "1", "issue_date": "2024-07-01", "water_temperature_C": "26.9",
        "air_temperature_C": "28.1", "total_phosphorus_mg_L": "0.098", "total_nitrogen_mg_L": "1.42",
        "solar_radiation_MJ_m2_day": "18.2", "wind_speed_m_s": "1.6", "chlorophyll_a_ug_L": "40.0",
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
        self.assertEqual(len(rows), 6)
        self.assertIsInstance(rows[0]["target_value"], float)
        self.assertIsInstance(rows[0]["horizon_days"], int)
        self.assertIsNone(rows[2]["total_phosphorus_mg_L"])

        filtered = load_training_samples(self.csv_path, metrics=["chlorophyll_a"], horizons=[1])
        self.assertEqual([row["sample_id"] for row in filtered], ["s1", "s3"])

        self.assertEqual([r["sample_id"] for r in load_training_samples(self.csv_path, splits=["test"])], ["s4", "s6"])
        self.assertEqual(load_training_samples(self.csv_path, spatial_types=["region"]), [])

    def test_to_predictor_rows_maps_and_skips(self):
        predictor_rows, skipped = to_predictor_rows(load_training_samples(self.csv_path))

        self.assertEqual(skipped["missing_mechanism_inputs"], 1)  # s3 缺 TP，不回退机理默认值
        self.assertEqual(len(predictor_rows), 5)

        row = next(r for r in predictor_rows if r["metric_code"] == "chlorophyll_a" and r["horizon_days"] == 1)
        self.assertEqual(row["station_id"], "G0001")
        self.assertEqual(row["forecast_scale"], "short_term")
        self.assertEqual(row["issue_date"], "2024-07-01")
        self.assertEqual(row["split"], "train")
        self.assertEqual(row["target"], 1.0)  # chla min-max: 40 为最大值
        self.assertGreaterEqual(row["mechanism_score"], 0.0)
        self.assertLessEqual(row["mechanism_score"], 1.0)

        degenerate = next(r for r in predictor_rows if r["metric_code"] == "spatial_extent")
        self.assertEqual(degenerate["target"], 0.5)  # 组内值全部相同 → 0.5

    def test_train_and_predict_uses_train_only_fit_and_evaluates_test(self):
        result = train_and_predict(
            self.csv_path, "G0001", "short_term", ["chlorophyll_a", "spatial_extent"]
        )

        self.assertEqual(result["claim_boundary"], "simulation_training_data_only")
        self.assertFalse(result["effect_claim_allowed"])
        # fit 行 = train 可用行 (s1, s2)；s4/s6 在 test，不参与拟合
        self.assertEqual([item["horizon_days"] for item in result["results"]], [1, 3])
        self.assertEqual(result["results"][0]["date"], "2024-07-02")  # issue_date + horizon

        summary = result["training_summary"]
        self.assertEqual(summary["rows_loaded"], 5)  # 指标过滤后 s1,s2,s3,s4,s6
        self.assertEqual(summary["rows_fit"], 2)
        self.assertEqual(summary["fit_split"], "train")
        self.assertEqual(summary["rows_eval"], 2)
        self.assertEqual(summary["skipped"]["missing_mechanism_inputs"], 1)

        evaluations = result["evaluations"]
        self.assertIn("test", evaluations)
        self.assertEqual(evaluations["test"]["n"], 2)
        self.assertEqual(evaluations["test"]["metric_codes"], ["chlorophyll_a", "spatial_extent"])
        self.assertIn("mae", evaluations["test"]["regression"])
        # 混有回归目标 → 不输出分类指标
        self.assertNotIn("classification", evaluations["test"])

    def test_train_and_predict_supports_t1_bloom_label(self):
        result = train_and_predict(self.csv_path, "G0001", "short_term", ["bloom_label"])

        metric = result["results"][0]["metrics"][0]
        self.assertEqual(metric["metric_code"], "bloom_label")
        self.assertEqual(metric["unit"], "0/1")
        self.assertGreaterEqual(metric["value"], 0.0)
        self.assertLessEqual(metric["value"], 1.0)
        self.assertIn("lower_bound", metric)
        self.assertGreaterEqual(metric["lower_bound"], 0.0)
        self.assertLessEqual(metric["upper_bound"], 1.0)
        self.assertEqual(result["training_summary"]["rows_fit"], 1)

    def test_eval_split_reports_classification_for_binary_metrics(self):
        result = train_and_predict(self.csv_path, "G0001", "short_term", ["bloom_label", "spatial_extent"])

        evaluations = result["evaluations"]
        self.assertIn("test", evaluations)
        self.assertEqual(evaluations["test"]["metric_codes"], ["spatial_extent"])
        self.assertIn("classification", evaluations["test"])  # 全为二值目标 → 输出分类指标
        self.assertEqual(result["training_summary"]["rows_fit"], 2)  # s2, s5

    def test_train_and_predict_rejects_unknown_station(self):
        with self.assertRaises(ValueError):
            train_and_predict(self.csv_path, "NO_SUCH", "short_term", ["chlorophyll_a"])

    def test_train_and_predict_rejects_empty_fit_split(self):
        with self.assertRaises(ValueError):
            train_and_predict(self.csv_path, "G0001", "short_term", ["chlorophyll_a"], fit_split="validation")


if __name__ == "__main__":
    unittest.main()
