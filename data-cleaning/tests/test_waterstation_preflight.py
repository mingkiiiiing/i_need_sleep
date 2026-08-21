import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.waterstation_preflight import run_water_station_preflight


class WaterStationPreflightTests(unittest.TestCase):
    def test_empty_directory_is_blocked_without_touching_global_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input").mkdir()
            result = run_water_station_preflight(root / "input", root / "out")
            self.assertEqual(result["status"], "blocked_no_valid_files")
            self.assertTrue(Path(result["files"]["inventory"]).exists())
            self.assertTrue(Path(result["files"]["database"]).exists())

    def test_valid_p0_file_passes_read_only_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "input"
            input_root.mkdir()
            path = input_root / "station.csv"
            fields = ["observed_at", "station_id", "variable_code", "value", "unit"]
            variables = [("chlorophyll_a", "0.02", "mg/L"), ("water_temperature", "25", "degC"), ("total_nitrogen", "1.2", "mg/L"), ("total_phosphorus", "0.08", "mg/L")]
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for hour in (0, 6, 12):
                    for variable, value, unit in variables:
                        writer.writerow({"observed_at": f"2026-08-18T{hour:02d}:00:00+00:00", "station_id": "T01", "variable_code": variable, "value": value, "unit": unit})
            result = run_water_station_preflight(input_root, root / "out", root / "preflight.db")
            self.assertEqual(result["status"], "ready")
            connection = sqlite3.connect(root / "preflight.db")
            try:
                self.assertEqual(connection.execute("SELECT status FROM preflight_summary").fetchone()[0], "ready")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
