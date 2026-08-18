import unittest
from datetime import datetime, timezone

from pipeline.features import _build_rows


def obs(source, station, variable, time, value):
    return {
        "source_id": source,
        "station_id": station,
        "scene_id": None,
        "variable_code": variable,
        "time_bucket": time,
        "clean_value": value,
        "observed_at": time,
        "quality_flags": ["Q22"],
    }


def aligned(variable, value, *, feature_time="2020-01-03T00:00:00+00:00", source="S2", station="CLIMATE", status="matched_temporal_only"):
    return {
        "target_source_id": "WQ",
        "target_station_id": "WHOLE",
        "target_scene_id": None,
        "target_variable_code": "pH",
        "target_time_bucket": "2020-01-03T00:00:00+00:00",
        "target_clean_value": 8.0,
        "target_category": "water_quality",
        "feature_source_id": source if value is not None else None,
        "feature_station_id": station if value is not None else None,
        "feature_scene_id": None,
        "feature_variable_code": variable,
        "feature_time_bucket": feature_time if value is not None else None,
        "feature_clean_value": value,
        "time_gap_hours": 0.0 if value is not None else None,
        "space_gap_m": None,
        "feature_category": "meteorology" if variable == "air_temperature" else "water_quality",
        "spatial_status": "not_available",
        "match_status": status,
        "quality_flags": [],
    }


class FeatureTests(unittest.TestCase):
    def test_features_are_causal_and_ratio_is_derived(self):
        observations = [
            obs("WQ", "WHOLE", "pH", "2020-01-01T00:00:00+00:00", 7.5),
            obs("WQ", "WHOLE", "pH", "2020-01-02T00:00:00+00:00", 7.8),
            obs("WQ", "WHOLE", "pH", "2020-01-03T00:00:00+00:00", 8.0),
            obs("S2", "CLIMATE", "total_nitrogen", "2020-01-03T00:00:00+00:00", 1.2),
            obs("S2", "CLIMATE", "total_phosphorus", "2020-01-03T00:00:00+00:00", 0.2),
            obs("S2", "CLIMATE", "air_temperature", "2020-01-02T00:00:00+00:00", 10.0),
            obs("S2", "CLIMATE", "air_temperature", "2020-01-03T00:00:00+00:00", 12.0),
            obs("S2", "CLIMATE", "air_temperature", "2020-01-04T00:00:00+00:00", 99.0),
        ]
        alignments = [
            aligned("total_nitrogen", 1.2, source="S2", station="CLIMATE"),
            aligned("total_phosphorus", 0.2, source="S2", station="CLIMATE"),
            aligned("air_temperature", 99.0, feature_time="2020-01-04T00:00:00+00:00", source="S2", station="CLIMATE"),
        ]
        rows, quality, leakage = _build_rows(alignments, observations)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row["tn_tp_ratio"], 6.0)
        self.assertIsNone(row["feature_air_temperature"])
        self.assertEqual(row["feature_air_temperature_match_status"], "future_blocked")
        self.assertIn("Q24", row["quality_flags"])
        self.assertEqual(row["leakage_check"], "future_values_blocked")
        self.assertEqual(leakage["accepted_future_values"], 0)
        self.assertEqual(leakage["blocked_future_values"], 1)
        self.assertAlmostEqual(row["target_rolling_mean_3d"], (7.5 + 7.8 + 8.0) / 3)


if __name__ == "__main__":
    unittest.main()

