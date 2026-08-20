import unittest

from pipeline.impute import classify_missing_mechanisms, impute_short_gaps


def _row(source, variable, timestamp, value=None, **extra):
    row = {
        "source_id": source,
        "station_id": extra.pop("station_id", "S1"),
        "variable_code": variable,
        "observed_at": timestamp,
        "clean_value": value,
        "quality_flags": [],
    }
    row.update(extra)
    return row


class MissingMechanismTests(unittest.TestCase):
    def test_classifies_required_mechanisms_and_keeps_distinct_policies(self):
        rows = [
            _row("station", "water_temperature", "2026-08-18T00:00:00+00:00", 20.0),
            _row("station", "water_temperature", "2026-08-18T01:00:00+00:00"),
            _row("station", "water_temperature", "2026-08-18T03:00:00+00:00", 23.0),
            _row("station", "water_temperature", "2026-08-18T06:00:00+00:00"),
            _row("station", "water_temperature", "2026-08-18T10:00:00+00:00", 27.0),
            _row("satellite", "chlorophyll_a", "2026-08-18T02:00:00+00:00", cloud_valid=False, cloud_mask_method="SCL_cloud_or_snow"),
            _row("buoy", "dissolved_oxygen", "2026-08-18T02:00:00+00:00", sensor_status="offline"),
            _row("api", "air_temperature", "2026-08-18T02:00:00+00:00"),
            _row("station", "pH", "2026-08-18T02:00:00+00:00", quality_flags=["Q99"]),
            _row("lab", "total_phosphorus", "2026-08-01T00:00:00+00:00", frequency="monthly"),
            _row("station", "water_temperature", "2026-08-18T11:00:00+00:00", 28.0),
        ]
        result = classify_missing_mechanisms(
            rows,
            source_health={"api": {"source_id": "api", "status": "failed"}},
            expected_intervals={("station", "water_temperature"): 60},
            source_events=[{"source_id": "no_row_api", "status": "timeout", "http_status": 504}],
        )
        by_time = {row.get("observed_at"): row for row in rows}
        self.assertEqual(by_time["2026-08-18T01:00:00+00:00"]["missing_mechanism"], "temporal_gap_short")
        self.assertEqual(by_time["2026-08-18T06:00:00+00:00"]["missing_mechanism"], "temporal_gap_long")
        self.assertEqual(by_time["2026-08-18T02:00:00+00:00"]["missing_mechanism"], "quality_rejected")
        self.assertEqual(next(row for row in rows if row["source_id"] == "satellite")["missing_mechanism"], "cloud_masked")
        self.assertEqual(next(row for row in rows if row["source_id"] == "buoy")["missing_mechanism"], "device_offline")
        self.assertEqual(next(row for row in rows if row["source_id"] == "api")["missing_mechanism"], "interface_failure")
        self.assertEqual(next(row for row in rows if row["source_id"] == "lab")["missing_mechanism"], "low_frequency")
        self.assertEqual(result["source_event_audit"][0]["missing_mechanism"], "interface_failure")
        self.assertNotEqual(result["policies"]["cloud_masked"], result["policies"]["low_frequency"])
        self.assertNotEqual(result["policies"]["quality_rejected"], result["policies"]["temporal_gap_short"])

    def test_short_gap_only_is_eligible_and_other_mechanisms_remain_pending(self):
        rows = [
            _row("station", "water_temperature", "2026-08-18T00:00:00+00:00", 20.0),
            _row("station", "water_temperature", "2026-08-18T01:00:00+00:00"),
            _row("station", "water_temperature", "2026-08-18T02:00:00+00:00", 22.0),
            _row("satellite", "chlorophyll_a", "2026-08-18T01:00:00+00:00", cloud_valid=False),
            _row("station", "pH", "2026-08-18T01:00:00+00:00", quality_flags=["Q99"]),
        ]
        result = impute_short_gaps(rows)
        short = next(row for row in rows if row["source_id"] == "station" and row["variable_code"] == "water_temperature" and row["clean_value"] == 21.0)
        self.assertEqual(short["missing_mechanism"], "temporal_gap_short")
        self.assertEqual(short["imputation_method"], "linear_time")
        self.assertEqual(short["is_imputed"], True)
        pending_sources = {(row["source_id"], row["variable_code"], row["missing_mechanism"]) for row in result["pending"]}
        self.assertIn(("satellite", "chlorophyll_a", "cloud_masked"), pending_sources)
        self.assertIn(("station", "pH", "quality_rejected"), pending_sources)
        self.assertEqual(len(result["imputed"]), 1)


if __name__ == "__main__":
    unittest.main()
