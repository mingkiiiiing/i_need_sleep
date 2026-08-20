import unittest
from datetime import datetime, timezone

from pipeline.impute import handle_low_frequency_nutrients, impute_short_gaps


def row(variable, timestamp, value=None, source="station", frequency=None):
    result = {
        "source_id": source,
        "station_id": "S1",
        "variable_code": variable,
        "observed_at": timestamp,
        "clean_value": value,
        "quality_flags": [],
        "value_origin": "observed",
    }
    if frequency is not None:
        result["frequency"] = frequency
    return result


class LowFrequencyNutrientTests(unittest.TestCase):
    def test_monthly_native_frequency_and_age_aware_latest_reference(self):
        records = [
            row("total_nitrogen", "2026-01-01T00:00:00+00:00", 1.0),
            row("total_nitrogen", "2026-02-01T00:00:00+00:00", 2.0),
            row("total_nitrogen", "2026-03-01T00:00:00+00:00", 3.0),
            row("total_nitrogen", "2026-04-01T00:00:00+00:00", None),
            row("air_temperature", "2026-03-01T00:00:00+00:00", 20.0),
        ]
        result = handle_low_frequency_nutrients(records, as_of="2026-03-15T00:00:00+00:00", max_age_hours=720)
        self.assertEqual(result["row_count_before"], 5)
        self.assertEqual(result["row_count_after"], 5)
        self.assertEqual(result["nutrient_row_count"], 4)
        self.assertEqual(result["low_frequency_series"], 1)
        self.assertEqual(records[0]["native_frequency"], "monthly")
        self.assertEqual(records[0]["low_frequency_status"], "native_low_frequency")
        self.assertEqual(records[0]["preserved_native_frequency"], True)
        self.assertEqual(records[2]["latest_observed_value"], 3.0)
        self.assertEqual(records[2]["feature_value"], 3.0)
        self.assertEqual(records[2]["feature_value_observed_at"], "2026-03-01T00:00:00+00:00")
        missing = records[3]
        self.assertIsNone(missing["clean_value"])
        self.assertEqual(missing["feature_value"], 3.0)
        self.assertEqual(missing["feature_value_observed_at"], "2026-03-01T00:00:00+00:00")
        self.assertGreater(missing["feature_value_age_hours"], 0)
        self.assertEqual(missing["data_age_status"], "future_relative_to_as_of")
        self.assertNotIn("native_frequency", records[4])
        self.assertEqual(len(result["latest_value_table"]), 1)

    def test_declared_weekly_frequency_is_not_expanded_or_filled(self):
        records = [
            row("ammonia_nitrogen", "2026-08-01T00:00:00+00:00", 0.2, frequency="weekly"),
            row("ammonia_nitrogen", "2026-08-08T00:00:00+00:00", None, frequency="weekly"),
            row("ammonia_nitrogen", "2026-08-15T00:00:00+00:00", 0.4, frequency="weekly"),
        ]
        result = handle_low_frequency_nutrients(records, as_of=datetime(2026, 8, 20, tzinfo=timezone.utc))
        self.assertEqual(len(records), 3)
        self.assertEqual(result["frequency_counts"]["weekly"], 3)
        self.assertTrue(all(item["preserved_native_frequency"] for item in records))
        self.assertIsNone(records[1]["clean_value"])
        self.assertEqual(records[1]["feature_value"], 0.2)
        self.assertEqual(records[1]["feature_value_semantics"], "latest_observed_with_age")

    def test_impute_pipeline_exposes_low_frequency_summary_without_expansion(self):
        records = [
            row("total_phosphorus", "2026-01-01T00:00:00+00:00", 1.0),
            row("total_phosphorus", "2026-02-01T00:00:00+00:00", 2.0),
        ]
        result = impute_short_gaps(records, as_of="2026-02-15T00:00:00+00:00")
        self.assertIn("low_frequency_nutrients", result)
        self.assertEqual(result["low_frequency_nutrients"]["row_count_before"], 2)
        self.assertEqual(result["low_frequency_nutrients"]["row_count_after"], 2)
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
