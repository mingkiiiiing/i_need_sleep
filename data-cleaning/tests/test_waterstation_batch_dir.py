import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.waterstation_batch_dir import run_water_station_batch_directory


class WaterStationBatchDirectoryTests(unittest.TestCase):
    def test_directory_deduplicates_by_hash_and_records_parse_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_root = root / "incoming"
            input_root.mkdir()
            content = "时间,站点编号,叶绿素a\n2026-08-18T00:00:00Z,S1,0.03\n"
            (input_root / "a.csv").write_text(content, encoding="utf-8-sig")
            (input_root / "same.csv").write_text(content, encoding="utf-8-sig")
            (input_root / "broken.json").write_text("{not-json", encoding="utf-8")
            cleaning = {"files": {"cleaned_observations": str(root / "cleaned.csv"), "database": str(root / "data.db")}}
            validation = {"validation_status": "blocked_missing_drivers", "summary": {"status": "blocked_missing_drivers"}}
            with patch("pipeline.waterstation_batch_dir.run_cleaning", return_value=cleaning), patch("pipeline.waterstation_batch_dir.run_station_validation", return_value=validation):
                result = run_water_station_batch_directory(input_root, root / "out", root / "data.db")
            self.assertEqual(result["files_discovered"], 3)
            self.assertEqual(result["files_parsed"], 1)
            self.assertEqual(result["duplicate_files_skipped"], 1)
            self.assertEqual(result["parse_failures"], 1)
            self.assertEqual(result["status"], "blocked_by_quality_gate")
            self.assertTrue((root / "out" / "input_inventory.csv").exists())


if __name__ == "__main__":
    unittest.main()

