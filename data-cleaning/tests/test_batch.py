import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.batch import run_data_cleaning_batch


class BatchRunTests(unittest.TestCase):
    def test_batch_creates_isolated_database_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw" / "local"
            raw.mkdir(parents=True)
            with (raw / "station.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["监测时间", "站点编号", "水温", "总磷"])
                writer.writeheader()
                writer.writerow({"监测时间": "2026-08-18 00:00:00", "站点编号": "T01", "水温": "26.5", "总磷": "0.08"})
            result = run_data_cleaning_batch(raw, runs_root=root / "runs", run_id="batch_test")
            self.assertEqual(result["status"], "completed")
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["files"]["database"]).exists())
            connection = sqlite3.connect(result["files"]["database"])
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"pipeline_run", "cleaned_observations", "quality_report"}.issubset(tables))
                self.assertEqual(connection.execute("SELECT run_id FROM pipeline_run").fetchone()[0], "batch_test")
            finally:
                connection.close()

    def test_batch_can_run_through_coverage_without_global_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw" / "local"
            raw.mkdir(parents=True)
            with (raw / "station.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["监测时间", "站点编号", "水温", "总磷", "风速"])
                writer.writeheader()
                writer.writerow({"监测时间": "2026-08-18 00:00:00", "站点编号": "T01", "水温": "26.5", "总磷": "0.08", "风速": "2.1"})
                writer.writerow({"监测时间": "2026-08-19 00:00:00", "站点编号": "T01", "水温": "26.8", "总磷": "0.08", "风速": "1.8"})
            result = run_data_cleaning_batch(raw, runs_root=root / "runs", run_id="batch_downstream", through="coverage")
            self.assertIn(result["status"], {"completed", "completed_with_warnings"})
            self.assertEqual(set(result["stages"]) , {"cleaning", "quality_report", "resample", "align", "features", "coverage"})
            self.assertTrue(Path(result["stages"]["coverage"]["files"]["audit"]).exists())
            self.assertTrue(Path(result["files"]["feature_dataset"]).exists())
            self.assertFalse(list((root / "runs" / "batch_downstream" / "manifests").glob("*.json")) == [])


if __name__ == "__main__":
    unittest.main()
