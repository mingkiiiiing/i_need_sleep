import unittest

from pipeline.impute import impute_short_gaps, impute_wind_direction_uv


def wind_row(variable, timestamp, value, source="wind", station="S1"):
    return {
        "source_id": source,
        "station_id": station,
        "variable_code": variable,
        "observed_at": timestamp,
        "clean_value": value,
        "value_origin": "observed",
        "quality_flags": [],
    }


def paired(timestamp, direction, speed, **kwargs):
    return [
        wind_row("wind_direction", timestamp, direction, **kwargs),
        wind_row("wind_speed", timestamp, speed, **kwargs),
    ]


class WindUvImputationTests(unittest.TestCase):
    def test_wraparound_359_to_1_is_interpolated_near_north(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 359.0, 2.0)
            + paired("2026-01-01T01:00:00+00:00", None, 2.0)
            + paired("2026-01-01T02:00:00+00:00", 1.0, 2.0)
        )
        result = impute_wind_direction_uv(records)
        target = next(row for row in records if row["variable_code"] == "wind_direction" and "01:00" in row["observed_at"])
        self.assertEqual(result["imputed_rows"], 1)
        self.assertEqual(target["wind_uv_status"], "imputed")
        self.assertTrue(target["clean_value"] <= 1.0 or target["clean_value"] >= 359.0)
        self.assertAlmostEqual(target["wind_uv_speed_from_vector"], 2.0, places=3)
        self.assertEqual(target["observed_flag"], 0)
        self.assertEqual(target["imputation_flag"], 1)
        self.assertEqual(result["direction_convention"], "meteorological_from")

    def test_calm_wind_does_not_fabricate_direction(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 90.0, 0.0)
            + paired("2026-01-01T01:00:00+00:00", None, 0.0)
            + paired("2026-01-01T02:00:00+00:00", 270.0, 0.0)
        )
        result = impute_wind_direction_uv(records)
        target = next(row for row in records if row["variable_code"] == "wind_direction" and "01:00" in row["observed_at"])
        self.assertEqual(target["wind_uv_status"], "calm_undefined")
        self.assertIsNone(target["clean_value"])
        self.assertEqual(target["observed_flag"], 0)
        self.assertEqual(target["imputation_flag"], 1)
        self.assertGreaterEqual(result["calm_rows"], 1)

    def test_calm_pair_missing_has_one_audit_per_timestamp(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 90.0, 0.0)
            + paired("2026-01-01T01:00:00+00:00", None, None)
            + paired("2026-01-01T02:00:00+00:00", 270.0, 0.0)
        )
        result = impute_wind_direction_uv(records)
        target_audits = [a for a in result["audit"] if "01:00" in a["observed_at"]]
        self.assertEqual(len(target_audits), 1)
        self.assertEqual(result["imputed_rows"], 1)

    def test_missing_speed_is_filled_from_vector_and_direction_is_preserved(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 180.0, 4.0)
            + paired("2026-01-01T01:00:00+00:00", 180.0, None)
            + paired("2026-01-01T02:00:00+00:00", 180.0, 6.0)
        )
        result = impute_wind_direction_uv(records)
        target = next(row for row in records if row["variable_code"] == "wind_speed" and "01:00" in row["observed_at"])
        self.assertEqual(target["wind_uv_status"], "imputed")
        self.assertAlmostEqual(target["clean_value"], 5.0, places=3)
        self.assertEqual(result["imputed_rows"], 1)

    def test_missing_paired_donor_and_long_gap_remain_pending(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 0.0, 2.0)
            + paired("2026-01-01T01:00:00+00:00", None, None)
            + paired("2026-01-01T06:00:00+00:00", 10.0, 2.0)
        )
        result = impute_wind_direction_uv(records, max_gap_steps=3)
        target = next(row for row in records if row["variable_code"] == "wind_direction" and "01:00" in row["observed_at"])
        self.assertEqual(target["wind_uv_status"], "pending")
        self.assertIn(target["wind_uv_block_reason"], {"gap_not_regular_or_short", "missing_paired_wind_donor"})
        self.assertEqual(result["imputed_rows"], 0)

    def test_non_wind_rows_and_row_count_are_unchanged(self):
        records = [
            {"variable_code": "water_temperature", "clean_value": 20.0},
            {"variable_code": "wind_direction", "observed_at": "2026-01-01T00:00:00+00:00", "clean_value": 0.0, "source_id": "x", "station_id": "s"},
            {"variable_code": "wind_speed", "observed_at": "2026-01-01T00:00:00+00:00", "clean_value": 1.0, "source_id": "x", "station_id": "s"},
        ]
        before = len(records)
        result = impute_wind_direction_uv(records)
        self.assertEqual(len(records), before)
        self.assertEqual(records[0]["clean_value"], 20.0)
        self.assertEqual(result["row_count_before"], result["row_count_after"])

    def test_short_gap_pipeline_does_not_fall_back_to_degree_interpolation(self):
        records = (
            paired("2026-01-01T00:00:00+00:00", 359.0, 2.0)
            + paired("2026-01-01T01:00:00+00:00", None, 2.0)
            + paired("2026-01-01T02:00:00+00:00", 1.0, 2.0)
        )
        result = impute_short_gaps(records)
        target = next(row for row in records if row["variable_code"] == "wind_direction" and "01:00" in row["observed_at"])
        self.assertAlmostEqual(target["clean_value"], 0.0, places=3)
        self.assertEqual(result["wind_uv"]["imputed_rows"], 1)


if __name__ == "__main__":
    unittest.main()
