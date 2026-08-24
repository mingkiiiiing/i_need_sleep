import unittest

from pipeline.impute import impute_short_gaps


def row(variable, timestamp, value=None, source="station", station="S1", source_row=None):
    return {
        "source_id": source,
        "source_file": "fixture.csv",
        "source_row": source_row or timestamp,
        "station_id": station,
        "variable_code": variable,
        "observed_at": timestamp,
        "clean_value": value,
        "quality_flags": [],
        "is_imputed": False,
    }


class ShortGapImputationTests(unittest.TestCase):
    def test_high_frequency_two_step_gap_has_complete_donor_and_interval_audit(self):
        records = [
            row("water_temperature", "2026-08-18T00:00:00+00:00", 10.0, source_row="1"),
            row("water_temperature", "2026-08-18T01:00:00+00:00", source_row="2"),
            row("water_temperature", "2026-08-18T02:00:00+00:00", source_row="3"),
            row("water_temperature", "2026-08-18T03:00:00+00:00", 16.0, source_row="4"),
        ]
        result = impute_short_gaps(records, expected_intervals={("station", "water_temperature"): 60})
        self.assertEqual([round(item["clean_value"], 6) for item in records[1:3]], [12.0, 14.0])
        self.assertEqual(len(result["imputed"]), 2)
        self.assertEqual(len(result["pending"]), 0)
        self.assertEqual(len(result["imputation_audit"]), 2)
        for item in records[1:3]:
            self.assertEqual(item["imputation_status"], "imputed")
            self.assertEqual(item["imputation_method"], "linear_time")
            self.assertEqual(item["imputation_donor_left"], "fixture.csv:1")
            self.assertEqual(item["imputation_donor_right"], "fixture.csv:4")
            self.assertEqual(item["imputation_gap_steps"], 2)
            self.assertEqual(item["imputation_interval_minutes"], 60.0)
            self.assertEqual(item["imputation_donor_count"], 2)
            self.assertEqual(item["imputation_left_value"], 10.0)
            self.assertEqual(item["imputation_right_value"], 16.0)
            self.assertEqual(item["imputation_left_observed_at"], "2026-08-18T00:00:00+00:00")
            self.assertEqual(item["imputation_right_observed_at"], "2026-08-18T03:00:00+00:00")

    def test_low_frequency_and_protected_variables_are_not_imputed(self):
        records = [
            row("total_phosphorus", "2026-08-01T00:00:00+00:00", 1.0, source="lab"),
            row("total_phosphorus", "2026-08-02T00:00:00+00:00", None, source="lab"),
            row("total_phosphorus", "2026-08-03T00:00:00+00:00", 3.0, source="lab"),
            row("chlorophyll_a", "2026-08-18T00:00:00+00:00", 10.0, source="station"),
            row("chlorophyll_a", "2026-08-18T01:00:00+00:00", None, source="station"),
            row("chlorophyll_a", "2026-08-18T02:00:00+00:00", 12.0, source="station"),
        ]
        result = impute_short_gaps(records, expected_intervals={("lab", "total_phosphorus"): 1440, ("station", "chlorophyll_a"): 60})
        self.assertEqual(len(result["imputed"]), 0)
        lab_pending = next(item for item in result["pending"] if item["source_id"] == "lab")
        chlorophyll_pending = next(item for item in result["pending"] if item["variable_code"] == "chlorophyll_a")
        self.assertEqual(lab_pending["imputation_block_reason"], "mechanism_low_frequency_not_eligible")
        self.assertEqual(chlorophyll_pending["imputation_block_reason"], "variable_policy_forbids_auto_imputation")
        self.assertIsNone(lab_pending["clean_value"])
        self.assertIsNone(chlorophyll_pending["clean_value"])

    def test_nonregular_gap_is_pending_with_gap_audit_and_method_is_validated(self):
        records = [
            row("water_temperature", "2026-08-18T00:00:00+00:00", 10.0),
            row("water_temperature", "2026-08-18T01:00:00+00:00"),
            row("water_temperature", "2026-08-18T05:00:00+00:00", 15.0),
        ]
        result = impute_short_gaps(records, max_gap_steps=3)
        self.assertEqual(len(result["imputed"]), 0)
        self.assertEqual(result["pending"][0]["imputation_block_reason"], "gap_not_regular_or_short")
        self.assertEqual(result["pending"][0]["imputation_gap_steps"], 4)
        self.assertEqual(result["pending"][0]["imputation_interval_minutes"], 60.0)
        with self.assertRaises(ValueError):
            impute_short_gaps([], method="kalman")


if __name__ == "__main__":
    unittest.main()
