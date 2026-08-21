import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.forecast_labels import build_horizon_labels, run_horizon_labels


def row(day: int, value: float, station: str = "S1", split: str = "train") -> dict[str, str]:
    return {
        "target_feature_row_key": f"{station}-{day}",
        "target_source_id": "source",
        "target_station_id": station,
        "target_scene_id": "",
        "target_variable_code": "phytoplankton_biomass",
        "target_time_bucket": f"2020-01-{day:02d}T00:00:00+00:00",
        "target_clean_value": str(value),
        "dataset_split": split,
    }


class ForecastLabelTests(unittest.TestCase):
    def test_future_values_are_matched_only_in_same_series(self):
        rows = [row(1, 1), row(3, 3), row(12, 12), row(31, 31), row(1, 100, station="S2")]
        result = build_horizon_labels(rows, target_variable="phytoplankton_biomass")
        first = next(item for item in result["rows"] if item["target_station_id"] == "S1" and item["target_time_bucket"].startswith("2020-01-01"))
        self.assertEqual(first["horizon_1_3d_status"], "accepted")
        self.assertEqual(first["horizon_1_3d_value"], "3")
        self.assertEqual(first["horizon_7_15d_status"], "accepted")
        self.assertEqual(first["horizon_7_15d_value"], "12")
        self.assertEqual(first["horizon_30_90d_status"], "accepted")
        self.assertEqual(first["horizon_30_90d_value"], "31")

    def test_no_interpolation_for_missing_horizon(self):
        rows = [row(1, 1), row(20, 20)]
        result = build_horizon_labels(rows, target_variable="phytoplankton_biomass")
        first = result["rows"][0]
        self.assertEqual(first["horizon_1_3d_status"], "no_observation_in_window")
        self.assertIsNone(first["horizon_1_3d_value"])
        self.assertEqual(first["horizon_30_90d_status"], "no_observation_in_window")

    def test_run_writes_audit_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "experiment_dataset.csv"
            rows = [row(1, 1), row(3, 3), row(12, 12)]
            with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            output_root = Path(directory) / "labels"
            manifest = run_horizon_labels(input_path, output_root, Path(directory) / "data.db")
            self.assertEqual(manifest["status"], "completed")
            self.assertTrue((output_root / "forecast_label_dataset.csv").exists())
            self.assertTrue((output_root / "forecast_label_audit.json").exists())


if __name__ == "__main__":
    unittest.main()
