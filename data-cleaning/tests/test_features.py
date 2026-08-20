import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.features import _build_rows, build_daily_direct_features, build_lag_rolling_features, build_mechanistic_features, build_reliability_features, run_daily_direct_features


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

    def test_daily_direct_features_keep_all_category_lineage_and_absence(self):
        observations = [
            {**obs("station", "S1", "pH", "2020-01-01T00:00:00+00:00", 8.0), "observed_at_local": "2020-01-01T08:00:00+08:00"},
            {**obs("weather", "W1", "air_temperature", "2020-01-01T00:00:00+00:00", 10.0), "observed_at_local": "2020-01-01T08:00:00+08:00"},
            {**obs("hydro", "H1", "water_level", "2020-01-01T00:00:00+00:00", 3.1), "observed_at_local": "2020-01-01T08:00:00+08:00"},
            {**obs("copernicus_sentinel2", None, "cloud_cover", "2020-01-01T00:00:00+00:00", 30.0), "scene_id": "SCENE", "observed_at_local": "2020-01-01T08:00:00+08:00"},
        ]
        with self.subTest("static parquet"):
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                static_path = Path(directory) / "static.parquet"
                pd.DataFrame([{"hybas_id": 1, "sub_area_km2": 10.0, "elevation_mean_m": 5.0, "source_dem": "DEM"}]).to_parquet(static_path, index=False)
                rows, lineage, audit = build_daily_direct_features(observations, static_features_path=static_path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["category_water_quality_available"], 1)
        self.assertEqual(row["category_meteorology_available"], 1)
        self.assertEqual(row["category_hydrology_available"], 1)
        self.assertEqual(row["category_remote_sensing_available"], 1)
        self.assertEqual(row["category_static_available"], 1)
        self.assertEqual(row["static_elevation_mean_m"], 5.0)
        self.assertTrue(any(item["feature_name"] == "direct_pH" for item in lineage))
        self.assertEqual(audit["daily_rows"], 1)

    def test_lag_and_rolling_features_are_strictly_causal(self):
        frame = pd.DataFrame({
            "feature_date": [f"2020-01-{day:02d}" for day in range(1, 11)],
            "direct_air_temperature": [float(day) for day in range(1, 11)],
        })
        result, lineage, audit = build_lag_rolling_features(frame)
        day4 = result[result["feature_date"] == "2020-01-04"].iloc[0]
        self.assertEqual(day4["direct_air_temperature_lag_1d"], 3.0)
        self.assertEqual(day4["direct_air_temperature_rolling_mean_3d"], 2.0)
        altered = frame.copy()
        altered.loc[altered["feature_date"] == "2020-01-10", "direct_air_temperature"] = 9999.0
        altered_result, _, _ = build_lag_rolling_features(altered)
        altered_day4 = altered_result[altered_result["feature_date"] == "2020-01-04"].iloc[0]
        self.assertEqual(altered_day4["direct_air_temperature_rolling_mean_3d"], 2.0)
        self.assertEqual(audit["leakage_violations"], 0)
        self.assertTrue(any(item["window_days"] == 90 for item in lineage))

    def test_mechanistic_features_do_not_invent_missing_drivers(self):
        frame = pd.DataFrame({
            "feature_date": ["2020-01-01", "2020-01-02"],
            "direct_air_temperature": [20.0, 30.0],
            "direct_shortwave_radiation": [100.0, 300.0],
            "direct_wind_speed": [2.0, 5.0],
            "direct_precipitation_rolling_mean_3d": [1.5, 2.0],
            "direct_precipitation_rolling_n_3d": [2, 3],
        })
        result, lineage, audit = build_mechanistic_features(frame)
        self.assertEqual(result.loc[0, "mechanism_temperature_response_q10"], 1.0)
        self.assertEqual(result.loc[0, "mechanism_temperature_basis"], "air_temperature_proxy")
        self.assertAlmostEqual(result.loc[0, "mechanism_light_limitation"], 0.5)
        self.assertEqual(result.loc[0, "mechanism_low_wind_indicator"], 1.0)
        self.assertEqual(result.loc[0, "mechanism_antecedent_rainfall_3d"], 3.0)
        self.assertTrue(pd.isna(result.loc[0, "mechanism_n_limitation_monod"]))
        self.assertTrue(pd.isna(result.loc[0, "mechanism_water_level_change_1d"]))
        self.assertTrue(pd.isna(result.loc[0, "mechanism_onshore_wind_component"]))
        self.assertEqual(audit["availability"]["nutrient_rows"], 0)
        self.assertTrue(any(item["feature_name"] == "mechanism_phenology_sin" for item in lineage))

    def test_reliability_features_preserve_unknown_metadata(self):
        frame = pd.DataFrame({
            "feature_date": ["2020-01-01", "2020-01-02", "2020-01-04"],
            "direct_air_temperature": [20.0, None, 21.0],
            "direct_air_temperature_rolling_std_7d": [None, 0.5, 0.7],
            "direct_air_temperature_observed_count": [1, 0, 1],
            "category_meteorology_available": [1, 0, 1],
            "category_meteorology_sources": ['["nasa_power"]', "[]", '["nasa_power"]'],
        })
        result, lineage, audit = build_reliability_features(frame)
        self.assertEqual(result.loc[1, "reliability_air_temperature_age_days"], 1.0)
        self.assertEqual(result.loc[2, "reliability_air_temperature_age_days"], 0.0)
        self.assertEqual(result.loc[0, "reliability_meteorology_proxy_flag"], 1)
        self.assertEqual(audit["direct_feature_count"], 1)
        self.assertTrue(pd.isna(result.loc[0, "reliability_remote_valid_pixel_fraction"]))
        self.assertTrue(pd.isna(result.loc[0, "reliability_imputed_fraction"]))
        self.assertIn("reliability_remote_valid_pixel_fraction", audit["explicitly_unavailable_fields"])
        self.assertTrue(any(item["feature_name"] == "reliability_calibrated_prediction_uncertainty" for item in lineage))


if __name__ == "__main__":
    unittest.main()
