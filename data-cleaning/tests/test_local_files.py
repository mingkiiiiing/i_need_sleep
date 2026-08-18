import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.qc import quality_control
from pipeline.sources.local_files import normalize_local_file


class LocalFileTests(unittest.TestCase):
    def test_wide_csv_aliases_become_standard_long_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "station.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["监测时间", "站点编号", "水温", "总磷"])
                writer.writeheader()
                writer.writerow({"监测时间": "2025-06-01 00:00:00", "站点编号": "T01", "水温": "26.5", "总磷": "0.08"})
            result = normalize_local_file(path)

        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual({row["variable_code"] for row in result["observations"]}, {"water_temperature", "total_phosphorus"})
        self.assertEqual({row["station_id"] for row in result["observations"]}, {"T01"})
        self.assertEqual(result["observations"][0]["observed_at"], "2025-05-31T16:00:00+00:00")

    def test_long_csv_and_invalid_timestamp_are_qc_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["time", "station_code", "variable", "value", "unit"])
                writer.writeheader()
                writer.writerow({"time": "2025060100", "station_code": "T01", "variable": "TN", "value": "1.2", "unit": "mg/L"})
                writer.writerow({"time": "not-a-time", "station_code": "T01", "variable": "TN", "value": "1.3", "unit": "mg/L"})
            records = normalize_local_file(path)["observations"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["variable_code"], "total_nitrogen")
        qc = quality_control(records)
        self.assertEqual(len(qc["rejected"]), 1)
        self.assertEqual(qc["flag_counts"]["Q03"], 1)
        self.assertEqual(qc["flag_counts"]["Q99"], 1)


if __name__ == "__main__":
    unittest.main()
