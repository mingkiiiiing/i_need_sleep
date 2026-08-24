import unittest

from pipeline.align import align_records, _category
from pipeline.resample import _parse_time, resample_records


def observation(source_id, station_id, variable, time, value, *, unit="degC", lon=None, lat=None):
    return {
        "source_id": source_id,
        "source_file": "fixture.csv",
        "source_row": time,
        "station_id": station_id,
        "scene_id": None,
        "observed_at": time,
        "longitude": lon,
        "latitude": lat,
        "variable_code": variable,
        "observed_value": value,
        "clean_value": value,
        "unit": unit,
        "source_unit": unit,
        "value_origin": "observed",
        "is_imputed": False,
        "quality_flags": ["Q00"],
    }


class ResampleAlignTests(unittest.TestCase):
    def test_hourly_aggregation_uses_sum_and_circular_mean(self):
        rows = [
            observation("nasa_power_hourly", "S1", "air_temperature", "2025-06-01T00:05:00+00:00", 20.0),
            observation("nasa_power_hourly", "S1", "air_temperature", "2025-06-01T00:55:00+00:00", 22.0),
            observation("nasa_power_hourly", "S1", "precipitation", "2025-06-01T00:05:00+00:00", 1.0, unit="mm"),
            observation("nasa_power_hourly", "S1", "precipitation", "2025-06-01T00:55:00+00:00", 2.0, unit="mm"),
            observation("nasa_power_hourly", "S1", "wind_direction", "2025-06-01T00:05:00+00:00", 350.0, unit="degree"),
            observation("nasa_power_hourly", "S1", "wind_direction", "2025-06-01T00:55:00+00:00", 10.0, unit="degree"),
        ]
        result = resample_records(rows)
        values = {(row["variable_code"], row["clean_value"]): row for row in result["records"]}
        self.assertAlmostEqual(values[("air_temperature", 21.0)]["n_obs"], 2)
        self.assertAlmostEqual(values[("precipitation", 3.0)]["n_obs"], 2)
        self.assertAlmostEqual(values[("wind_direction", 0.0)]["n_obs"], 2)

    def test_daily_bucket_uses_china_local_day(self):
        rows = [
            observation("taihu_thqbca_history", "S1", "air_temperature", "2025-05-31T16:30:00+00:00", 20.0),
            observation("taihu_thqbca_history", "S1", "air_temperature", "2025-06-01T16:30:00+00:00", 21.0),
        ]
        result = resample_records(rows)
        self.assertEqual(result["records"][0]["time_bucket"], "2025-05-31T16:00:00+00:00")
        self.assertEqual(result["records"][0]["source_granularity"], "daily")

    def test_annual_series_is_native_and_not_upsampled(self):
        rows = [
            observation("taihu_thqbca_history", "TAIHU_WHOLE", "algae_density", f"{year}-12-31T16:00:00+00:00", float(year), unit="cells/L")
            for year in (2019, 2020, 2021)
        ]
        result = resample_records(rows)
        self.assertEqual(len(result["records"]), 3)
        self.assertTrue(all(row["frequency"] == "native" for row in result["records"]))
        self.assertEqual(result["gaps"], [])

    def test_alignment_marks_missing_spatial_metadata(self):
        rows = [
            observation("taihu_thqbca_history", "TAIHU_WHOLE", "pH", "2020-01-31T16:00:00+00:00", 8.0, unit="pH"),
            observation("taihu_thqbca_history", "TAIHU_CLIMATE", "air_temperature", "2020-01-31T16:00:00+00:00", 12.0),
        ]
        resampled = resample_records(rows)["records"]
        for row in resampled:
            row["_time"] = _parse_time(row["time_bucket"])
            row["_category"] = _category(row)
        result = align_records(resampled, max_time_diff_hours=24)
        matches = [row for row in result["records"] if row["feature_variable_code"] == "air_temperature"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["match_status"], "matched_temporal_only")
        self.assertIsNone(matches[0]["space_gap_m"])
        self.assertIn("Q23", matches[0]["quality_flags"])


if __name__ == "__main__":
    unittest.main()
