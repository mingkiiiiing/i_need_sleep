import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.modeling import _is_excluded, _mechanism_features, train_experiment


def _row(index: int, split: str, value: float) -> dict[str, str]:
    return {
        "target_variable_code": "phytoplankton_biomass",
        "target_clean_value": str(value),
        "target_feature_row_key": f"k{index}",
        "target_time_bucket": f"2020-01-{index + 1:02d}T00:00:00+00:00",
        "target_station_id": "S1",
        "dataset_split": split,
        "feature_phytoplankton_biomass": str(value),  # must be excluded as same-time target
        "feature_total_nitrogen": str(0.5 + index * 0.01),
        "feature_total_phosphorus": str(0.03 + index * 0.001),
        "feature_air_temperature": str(20 + index * 0.1),
        "feature_shortwave_radiation": "150",
        "feature_wind_speed": "2",
        "feature_observed_count": "5",
    }


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ModelingTests(unittest.TestCase):
    def test_mechanism_factors_are_bounded_and_missing_is_flagged(self):
        result = _mechanism_features({"feature_air_temperature": "28", "feature_total_nitrogen": "1", "feature_total_phosphorus": "0.1", "feature_shortwave_radiation": "200", "feature_wind_speed": "2"})
        self.assertEqual(result["mechanism_temperature_basis"], "air_temperature")
        self.assertGreaterEqual(result["mechanism_growth_index"], 0)
        self.assertLessEqual(result["mechanism_growth_index"], 1)
        missing = _mechanism_features({})
        self.assertEqual(missing["mechanism_missing_count"], 5)

    def test_same_target_feature_and_target_rolling_are_excluded(self):
        self.assertTrue(_is_excluded("feature_phytoplankton_biomass", "phytoplankton_biomass"))
        self.assertTrue(_is_excluded("target_rolling_mean_7d", "phytoplankton_biomass"))
        self.assertFalse(_is_excluded("feature_total_nitrogen", "phytoplankton_biomass"))

    def test_training_writes_metrics_and_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "split"
            input_dir.mkdir()
            _write(input_dir / "train.csv", [_row(index, "train", 1 + index * 0.1) for index in range(8)])
            _write(input_dir / "validation.csv", [_row(index, "validation", 1.3 + index * 0.1) for index in range(3)])
            _write(input_dir / "test.csv", [_row(index, "test", 1.6 + index * 0.1) for index in range(3)])
            output_dir = Path(directory) / "model"
            result = train_experiment(input_dir, output_dir, Path(directory) / "data.db", target_variable="phytoplankton_biomass", random_state=7)
            self.assertEqual(result["status"], "completed")
            self.assertTrue((output_dir / "predictions.csv").exists())
            self.assertTrue((output_dir / "metrics.csv").exists())
            self.assertTrue((output_dir / "model.pkl").exists())
            with (output_dir / "feature_importance.csv").open(encoding="utf-8-sig") as handle:
                importance_rows = list(__import__("csv").DictReader(handle))
            self.assertNotIn("feature_phytoplankton_biomass", [row["feature"] for row in importance_rows])

    def test_residual_training_labels_median_fallback_when_no_target_lag(self):
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory) / "split"
            input_dir.mkdir()
            for split, start in (("train", 0), ("validation", 8), ("test", 11)):
                _write(input_dir / f"{split}.csv", [_row(index, split, 1 + index * 0.1) for index in range(start, start + (8 if split == "train" else 3))])
            result = train_experiment(input_dir, Path(directory) / "model", Path(directory) / "data.db", fusion="mechanistic_residual")
            self.assertEqual(result["fusion"], "mechanistic_residual")
            with (Path(directory) / "model" / "predictions.csv").open(encoding="utf-8-sig") as handle:
                prediction_rows = list(__import__("csv").DictReader(handle))
            self.assertTrue(prediction_rows)
            self.assertEqual(prediction_rows[0]["mechanism_state_source"], "train_median_fallback")


if __name__ == "__main__":
    unittest.main()
