import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.waterstation_batch import _stage_water_station_file, run_water_station_batch


class WaterStationBatchTests(unittest.TestCase):
    def test_stage_supports_fetched_raw_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "fetched.json"
            input_path.write_text(json.dumps({"payload": {"records": [{"监测时间": "2026-08-18T00:00:00Z", "站点编号": "S1", "w01016": 0.03}]}}, ensure_ascii=False), encoding="utf-8")
            staged = _stage_water_station_file(input_path, root / "raw" / "water_station" / "standard.csv", source_id="taihu_water_station_batch")
            self.assertEqual(staged["rows"], 1)
            self.assertIn("chlorophyll_a", staged["variables"])

    def test_batch_manifest_blocks_when_gate_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "station.csv"
            input_path.write_text("时间,站点编号,叶绿素a\n2026-08-18T00:00:00Z,S1,0.03\n", encoding="utf-8-sig")
            cleaning = {"files": {"cleaned_observations": str(root / "cleaned.csv"), "database": str(root / "data.db")}}
            validation = {"validation_status": "blocked_missing_drivers", "summary": {"status": "blocked_missing_drivers"}}
            with patch("pipeline.waterstation_batch.run_cleaning", return_value=cleaning), patch("pipeline.waterstation_batch.run_station_validation", return_value=validation):
                result = run_water_station_batch(input_path, root / "out", root / "data.db")
            self.assertEqual(result["status"], "blocked_by_quality_gate")
            self.assertTrue((root / "out" / "batch_summary.json").exists())


if __name__ == "__main__":
    unittest.main()

