import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.resample import resample_records, run_resampling


def row(variable, timestamp, value, *, source="station", station="S1", imputed=False):
    return {
        "source_id": source,
        "source_file": "fixture.csv",
        "source_row": timestamp,
        "station_id": station,
        "scene_id": None,
        "observed_at": timestamp,
        "longitude": 120.0,
        "latitude": 31.2,
        "variable_code": variable,
        "observed_value": value,
        "clean_value": value,
        "unit": "mm" if variable == "precipitation" else "mg/L",
        "source_unit": "mm" if variable == "precipitation" else "mg/L",
        "value_origin": "imputed" if imputed else "observed",
        "is_imputed": imputed,
        "imputation_confidence": 0.7 if imputed else None,
        "quality_flags": ["Q20"] if imputed else ["Q00"],
        "observed_flag": 0 if imputed else 1,
        "imputation_flag": 1 if imputed else 0,
    }


class MultiFrequencyResampleTests(unittest.TestCase):
    def test_decadal_bucket_uses_local_first_tenth_twenty_first(self):
        rows = [
            row("air_temperature", "2025-06-02T16:00:00+00:00", 20.0),
            row("air_temperature", "2025-06-12T16:00:00+00:00", 22.0),
            row("air_temperature", "2025-06-22T16:00:00+00:00", 24.0),
        ]
        result = resample_records(rows, target_frequency="decadal")
        self.assertEqual([item["time_bucket"] for item in result["records"]], [
            "2025-05-31T16:00:00+00:00",
            "2025-06-10T16:00:00+00:00",
            "2025-06-20T16:00:00+00:00",
        ])
        self.assertTrue(all(item["frequency"] == "decadal" for item in result["records"]))

    def test_monthly_flux_is_sum_and_robust_state_is_median(self):
        rows = [
            row("precipitation", "2025-01-01T00:00:00+00:00", 1.0),
            row("precipitation", "2025-01-15T00:00:00+00:00", 2.0),
            row("precipitation", "2025-02-01T00:00:00+00:00", 4.0),
            row("chlorophyll_a", "2025-01-01T00:00:00+00:00", 1.0),
            row("chlorophyll_a", "2025-01-15T00:00:00+00:00", 100.0),
            row("chlorophyll_a", "2025-01-20T00:00:00+00:00", 3.0),
        ]
        result = resample_records(rows, target_frequency="monthly")
        values = {(item["variable_code"], item["time_bucket"]): item for item in result["records"]}
        january = "2024-12-31T16:00:00+00:00"
        self.assertEqual(values[("precipitation", january)]["clean_value"], 3.0)
        self.assertEqual(values[("precipitation", january)]["aggregation_method"], "sum")
        self.assertEqual(values[("chlorophyll_a", january)]["clean_value"], 3.0)
        self.assertEqual(values[("chlorophyll_a", january)]["aggregation_method"], "median")

    def test_explicit_hourly_request_does_not_upsample_monthly_source(self):
        rows = [
            row("total_phosphorus", "2025-01-01T00:00:00+00:00", 0.1),
            row("total_phosphorus", "2025-02-01T00:00:00+00:00", 0.2),
        ]
        result = resample_records(rows, target_frequency="hourly")
        self.assertEqual(len(result["records"]), 2)
        self.assertTrue(all(item["frequency"] == "native" for item in result["records"]))
        self.assertTrue(all(item["resample_status"] == "no_upsampling" for item in result["records"]))
        self.assertEqual(result["gaps"], [])

    def test_coverage_and_imputation_flags_survive_aggregation(self):
        rows = [
            row("air_temperature", "2025-06-01T00:00:00+00:00", 20.0),
            row("air_temperature", "2025-06-01T01:00:00+00:00", 21.0, imputed=True),
        ]
        result = resample_records(rows, target_frequency="daily")
        output = result["records"][0]
        self.assertEqual(output["aggregation_coverage"], 1.0)
        self.assertEqual(output["imputation_flag"], 1)
        self.assertEqual(output["observed_flag"], 0)
        self.assertEqual(output["is_imputed"], True)

    def test_run_resampling_writes_frequency_manifest_and_sqlite_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            self._assert_run_resampling_contract(tmp_path)

    def _assert_run_resampling_contract(self, tmp_path: Path):
        input_path = tmp_path / "input.csv"
        rows = [row("air_temperature", "2025-06-01T00:00:00+00:00", 20.0), row("air_temperature", "2025-06-01T12:00:00+00:00", 22.0)]
        with input_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        result = run_resampling(input_path, tmp_path / "out", tmp_path / "resampled.sqlite", frequency="daily", run_id="resample-test")
        self.assertEqual(result["target_frequency"], "daily")
        self.assertTrue(Path(result["manifest"]).exists())
        connection = sqlite3.connect(result["files"]["database"])
        try:
            columns = {item[1] for item in connection.execute("PRAGMA table_info(resampled_observations)")}
            self.assertTrue({"observed_flag", "imputation_flag", "resample_status"}.issubset(columns))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
