import unittest

from pipeline.impute import handle_long_gap_uncertainty, impute_short_gaps


def row(timestamp, value=None, source_row=None):
    return {
        "source_id": "station",
        "source_file": "fixture.csv",
        "source_row": source_row or timestamp,
        "station_id": "S1",
        "variable_code": "water_temperature",
        "observed_at": timestamp,
        "clean_value": value,
        "quality_flags": [],
        "is_imputed": False,
    }


class LongGapUncertaintyTests(unittest.TestCase):
    def test_long_gap_preserves_null_and_emits_bounded_uncertainty(self):
        records = [
            row("2026-08-18T00:00:00+00:00", 10.0, "1"),
            row("2026-08-18T05:00:00+00:00", None, "2"),
            row("2026-08-18T10:00:00+00:00", 20.0, "3"),
        ]
        result = handle_long_gap_uncertainty(records)
        target = records[1]
        self.assertEqual(result["long_gap_rows"], 1)
        self.assertEqual(result["bounded_rows"], 1)
        self.assertEqual(target["missing_mechanism"], "temporal_gap_long")
        self.assertIsNone(target["clean_value"])
        self.assertEqual(target["observed_flag"], 0)
        self.assertEqual(target["imputation_flag"], 1)
        self.assertEqual(target["uncertainty_status"], "bounded_donor_envelope")
        self.assertEqual(target["uncertainty_method"], "local_donor_envelope")
        self.assertEqual(target["uncertainty_center"], 15.0)
        self.assertEqual(target["uncertainty_lower"], 5.0)
        self.assertEqual(target["uncertainty_upper"], 25.0)
        self.assertEqual(target["imputation_gap_steps"], 9)
        self.assertEqual(target["imputation_interval_minutes"], 60.0)
        self.assertEqual(target["imputation_donor_left"], "fixture.csv:1")
        self.assertEqual(target["imputation_donor_right"], "fixture.csv:3")
        self.assertTrue(result["audit"][0]["clean_value_preserved_null"])

    def test_short_gap_and_long_gap_flags_are_distinct_and_no_forward_fill(self):
        records = [
            row("2026-08-18T00:00:00+00:00", 10.0, "1"),
            row("2026-08-18T01:00:00+00:00", None, "2"),
            row("2026-08-18T02:00:00+00:00", 12.0, "3"),
            row("2026-08-18T07:00:00+00:00", None, "4"),
            row("2026-08-18T12:00:00+00:00", 22.0, "5"),
        ]
        result = impute_short_gaps(records)
        short = records[1]
        long = records[3]
        self.assertEqual(short["observed_flag"], 0)
        self.assertEqual(short["imputation_flag"], 1)
        self.assertEqual(short["imputation_status"], "imputed")
        self.assertEqual(long["observed_flag"], 0)
        self.assertEqual(long["imputation_flag"], 1)
        self.assertEqual(long["imputation_status"], "uncertain")
        self.assertIsNone(long["clean_value"])
        self.assertEqual(result["long_gap_uncertainty"]["long_gap_rows"], 1)

    def test_no_donor_long_gap_is_unbounded_and_not_filled(self):
        records = [row("2026-08-18T05:00:00+00:00", None, "1")]
        result = handle_long_gap_uncertainty(records)
        # A singleton cannot be called a bracketed long gap; it remains an
        # edge gap with an explicit non-observed flag and no estimate.
        self.assertEqual(result["long_gap_rows"], 0)
        self.assertIsNone(records[0]["clean_value"])
        self.assertEqual(records[0]["observed_flag"], 0)
        self.assertEqual(records[0]["imputation_flag"], 0)

        forced = [row("2026-08-18T05:00:00+00:00", None, "2")]
        forced[0]["missing_mechanism"] = "temporal_gap_long"
        forced_result = handle_long_gap_uncertainty(forced)
        self.assertEqual(forced_result["long_gap_rows"], 1)
        self.assertEqual(forced_result["unbounded_rows"], 1)
        self.assertEqual(forced[0]["uncertainty_status"], "unbounded_no_donors")
        self.assertEqual(forced[0]["observed_flag"], 0)
        self.assertEqual(forced[0]["imputation_flag"], 1)
        self.assertIsNone(forced[0]["clean_value"])


if __name__ == "__main__":
    unittest.main()
