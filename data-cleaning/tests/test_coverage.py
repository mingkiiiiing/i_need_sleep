import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pipeline.coverage import build_coverage_audit, run_coverage


def row(variable: str, day: int, value: float, source: str = "S", origin: str = "observed", frequency: str = "hourly") -> dict[str, str]:
    return {
        "source_id": source,
        "station_id": "TAIHU_1",
        "observed_at": f"2025-01-{day:02d}T00:00:00+00:00",
        "time_bucket": f"2025-01-{day:02d}T00:00:00+00:00",
        "variable_code": variable,
        "observed_value": str(value),
        "clean_value": str(value),
        "value_origin": origin,
        "frequency": frequency,
    }


class CoverageTests(unittest.TestCase):
    def test_missing_target_and_low_frequency_are_gaps(self):
        rows = [row("water_temperature", 1, 20), row("water_temperature", 2, 21), row("total_nitrogen", 1, 1, frequency="quarterly"), row("total_nitrogen", 30, 2, frequency="quarterly")]
        result = build_coverage_audit(rows, as_of=datetime(2025, 1, 3, tzinfo=timezone.utc))
        matrix = {item["variable_code"]: item for item in result["matrix"]}
        self.assertEqual(matrix["chlorophyll_a"]["status"], "missing")
        self.assertEqual(matrix["total_nitrogen"]["status"], "low_frequency")
        self.assertFalse(result["short_term_ready"])

    def test_proxy_target_is_not_treated_as_observed(self):
        result = build_coverage_audit([row("chlorophyll_a", 1, 10, origin="proxy"), row("chlorophyll_a", 2, 11, origin="proxy")], as_of=datetime(2025, 1, 3, tzinfo=timezone.utc))
        item = next(item for item in result["matrix"] if item["variable_code"] == "chlorophyll_a")
        self.assertEqual(item["status"], "proxy_only")
        self.assertFalse(result["target_ready"])

    def test_run_writes_matrix_and_gap_files(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "observations.csv"
            rows = [row("water_temperature", 1, 20), row("water_temperature", 2, 21)]
            with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            output = Path(directory) / "coverage"
            result = run_coverage(input_path, output, Path(directory) / "data.db", as_of=datetime(2025, 1, 3, tzinfo=timezone.utc))
            self.assertEqual(result["status"], "completed")
            self.assertTrue((output / "coverage_matrix.csv").exists())
            self.assertTrue((output / "coverage_gaps.csv").exists())


if __name__ == "__main__":
    unittest.main()
