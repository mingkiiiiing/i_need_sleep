import unittest

from pipeline.qc import DUPLICATE_KEY_FIELDS, RANGES, RULES, quality_control
from pipeline.impute import impute_short_gaps
from pipeline.fault_injection import evaluate_fault_fixture, run_fault_injection


class QualityControlTests(unittest.TestCase):
    def test_rules_are_loaded_from_versioned_config(self):
        self.assertEqual(RULES["version"], "1.0.0")
        self.assertIn("wind_speed", RANGES)
        self.assertEqual(DUPLICATE_KEY_FIELDS[-1], "variable_code")

    def test_missing_and_physical_outlier_are_not_cleaned_silently(self):
        records = [
            {
                "source_id": "test",
                "source_file": "fixture.json",
                "source_row": "1",
                "station_id": "S1",
                "observed_at": "2025-06-01T00:00:00+00:00",
                "variable_code": "wind_speed",
                "observed_value": 80,
                "clean_value": 80,
                "quality_flags": [],
            },
            {
                "source_id": "test",
                "source_file": "fixture.json",
                "source_row": "2",
                "station_id": "S1",
                "observed_at": "2025-06-01T01:00:00+00:00",
                "variable_code": "air_temperature",
                "observed_value": None,
                "clean_value": None,
                "quality_flags": [],
            },
        ]
        result = quality_control(records)
        self.assertEqual(len(result["cleaned"]), 0)
        self.assertEqual(len(result["imputation_candidates"]), 1)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(len(result["issues"]), 2)
        self.assertEqual(result["flag_counts"]["Q04"], 1)
        self.assertEqual(result["flag_counts"]["Q01"], 1)

    def test_short_gap_is_interpolated_and_long_gap_remains_pending(self):
        base = {
            "source_id": "test",
            "source_file": "fixture.json",
            "station_id": "S1",
            "scene_id": None,
            "variable_code": "air_temperature",
            "unit": "degC",
            "value_origin": "proxy",
            "is_imputed": False,
            "imputation_method": None,
            "imputation_confidence": None,
            "quality_flags": ["Q01"],
        }
        records = [
            {**base, "source_row": "1", "observed_at": "2025-06-01T00:00:00+00:00", "clean_value": 20.0},
            {**base, "source_row": "2", "observed_at": "2025-06-01T01:00:00+00:00", "clean_value": None},
            {**base, "source_row": "3", "observed_at": "2025-06-01T02:00:00+00:00", "clean_value": 24.0},
            {**base, "source_row": "4", "observed_at": "2025-06-01T03:00:00+00:00", "clean_value": None},
            {**base, "source_row": "5", "observed_at": "2025-06-01T08:00:00+00:00", "clean_value": 30.0},
        ]
        result = impute_short_gaps(records, max_gap_steps=3)
        self.assertEqual(len(result["imputed"]), 1)
        self.assertEqual(result["imputed"][0]["clean_value"], 22.0)
        self.assertEqual(result["imputed"][0]["value_origin"], "imputed")
        self.assertEqual(result["imputed"][0]["imputation_method"], "linear_time")
        self.assertEqual(len(result["pending"]), 1)

    def test_fault_fixture_recall_is_one(self):
        result = evaluate_fault_fixture()
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["false_negatives"], [])

    def test_fault_fixture_run_persists_auditable_result(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            result = run_fault_injection(Path(directory) / "fault")
            self.assertEqual(result["status"], "passed")
            self.assertTrue(Path(result["output"]).exists())
            self.assertTrue(Path(result["manifest"]).exists())


if __name__ == "__main__":
    unittest.main()
