import csv
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pipeline.quality_report import build_quality_report, run_quality_report


class QualityReportTests(unittest.TestCase):
    def test_report_counts_duplicates_proxies_and_low_frequency(self):
        rows = [
            {"source_id": "station", "station_id": "S1", "observed_at": "2026-08-16T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "10", "value_origin": "observed", "quality_flags": "[]", "is_imputed": "False"},
            {"source_id": "station", "station_id": "S1", "observed_at": "2026-08-16T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "11", "value_origin": "observed", "quality_flags": "[\"Q_DUP\"]", "is_imputed": "False"},
            {"source_id": "weather", "station_id": "W1", "observed_at": "2026-08-01T00:00:00+00:00", "variable_code": "air_temperature", "unit": "degC", "clean_value": "28", "value_origin": "forecast_proxy", "quality_flags": "[]", "is_imputed": "False"},
            {"source_id": "weather", "station_id": "W1", "observed_at": "2026-08-03T00:00:00+00:00", "variable_code": "air_temperature", "unit": "degC", "clean_value": "29", "value_origin": "forecast_proxy", "quality_flags": "[]", "is_imputed": "False"},
        ]
        result = build_quality_report(rows, as_of=datetime(2026, 8, 18, tzinfo=timezone.utc))
        station = next(row for row in result["rows"] if row["source_id"] == "station")
        weather = next(row for row in result["rows"] if row["source_id"] == "weather")
        self.assertEqual(station["duplicate_key_rows"], 1)
        self.assertEqual(station["quality_flagged_rows"], 1)
        self.assertEqual(weather["proxy_rows"], 2)
        self.assertEqual(weather["status"], "low_frequency")

    def test_run_writes_csv_json_and_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cleaned = root / "cleaned_observations.csv"
            with cleaned.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_id", "station_id", "observed_at", "variable_code", "unit", "clean_value", "value_origin", "quality_flags", "is_imputed"])
                writer.writeheader()
                writer.writerow({"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "10", "value_origin": "observed", "quality_flags": "[]", "is_imputed": "False"})
            database = root / "data.db"
            result = run_quality_report(cleaned, root / "report", database)
            self.assertEqual(result["status"], "completed")
            self.assertTrue((root / "report" / "quality_report.csv").exists())
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM quality_report").fetchone()[0], 1)
            finally:
                connection.close()

    def test_issue_only_group_exposes_issue_count(self):
        result = build_quality_report([], issue_rows=[{"source_id": "station", "variable_code": "chlorophyll_a"}])
        self.assertEqual(result["rows"][0]["status"], "issue_only")
        self.assertEqual(result["rows"][0]["issue_rows"], 1)


if __name__ == "__main__":
    unittest.main()
