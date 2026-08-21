import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.station_validate import validate_station_rows, run_station_validation


def row(variable: str, hour: int, value: float, unit: str, station: str = "S1") -> dict[str, str]:
    return {
        "source_id": "water_station_test",
        "source_row": str(hour),
        "station_id": station,
        "observed_at": f"2026-08-18T{hour:02d}:00:00+00:00",
        "variable_code": variable,
        "observed_value": str(value),
        "clean_value": str(value),
        "unit": unit,
        "source_unit": unit,
        "value_origin": "observed",
    }


class StationValidationTests(unittest.TestCase):
    def test_complete_four_hour_series_passes(self):
        rows = []
        for hour in (0, 4, 8):
            rows.extend([
                row("chlorophyll_a", hour, 30, "ug/L"),
                row("water_temperature", hour, 28, "degC"),
                row("total_nitrogen", hour, 1.2, "mg/L"),
                row("total_phosphorus", hour, 0.04, "mg/L"),
            ])
        result = validate_station_rows(rows)
        self.assertEqual(result["summary"]["status"], "ready")
        self.assertEqual(result["summary"]["issue_rows"], 0)

    def test_missing_driver_and_duplicate_are_blocked(self):
        rows = [row("chlorophyll_a", 0, 30, "ug/L"), row("chlorophyll_a", 0, 30, "ug/L"), row("total_nitrogen", 0, 1.2, "mg/L")]
        result = validate_station_rows(rows)
        self.assertEqual(result["summary"]["status"], "blocked_missing_drivers")
        self.assertIn("duplicate_key", result["summary"]["issue_counts"])

    def test_protocol_chlorophyll_mg_l_is_converted_to_internal_ug_l(self):
        rows = [row("chlorophyll_a", 0, 0.03, "mg/L")]
        result = validate_station_rows(rows)
        self.assertEqual(result["rows"][0]["unit"], "ug/L")
        self.assertAlmostEqual(float(result["rows"][0]["clean_value"]), 30.0)

    def test_run_writes_validation_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "station.csv"
            rows = [row("chlorophyll_a", 0, 30, "ug/L")]
            with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            output = Path(directory) / "validation"
            result = run_station_validation(input_path, output, Path(directory) / "data.db")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["validation_status"], "blocked_missing_drivers")
            self.assertTrue((output / "station_validation_issues.csv").exists())


if __name__ == "__main__":
    unittest.main()

