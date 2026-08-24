import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.sources.water_station import normalize_water_station_rows, run_water_station_parse


class WaterStationTests(unittest.TestCase):
    def test_protocol_codes_and_wide_records_are_normalized(self):
        rows = normalize_water_station_rows(Path("station.json"), [{
            "监测时间": "2026-08-18 00:00:00",
            "站点编号": "TAIHU_AUTO_01",
            "经度": 120.30,
            "纬度": 31.20,
            "w01016": 0.035,
            "w19011": 120000,
            "e01001": 29.1,
            "总氮": 1.2,
            "总磷": 0.04,
        }], source_id="water_station_test")
        self.assertEqual(len(rows), 5)
        by_variable = {row["variable_code"]: row for row in rows}
        self.assertEqual(by_variable["chlorophyll_a"]["unit"], "mg/L")
        self.assertEqual(by_variable["algae_density"]["unit"], "cells/L")
        self.assertEqual(by_variable["water_temperature"]["unit"], "degC")
        self.assertEqual(by_variable["total_nitrogen"]["clean_value"], 1.2)
        self.assertEqual(by_variable["water_temperature"]["station_id"], "TAIHU_AUTO_01")

    def test_long_records_keep_explicit_units(self):
        rows = normalize_water_station_rows(Path("station.csv"), [{
            "时间": "2026-08-18T00:00:00Z",
            "站点编号": "S1",
            "指标编码": "w01016",
            "数值": "0.04",
            "单位": "mg/L",
        }])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["variable_code"], "chlorophyll_a")
        self.assertEqual(rows[0]["source_unit"], "mg/L")

    def test_parse_file_writes_standard_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "station.csv"
            output_path = Path(directory) / "standard.csv"
            with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["时间", "站点编号", "叶绿素a"])
                writer.writeheader()
                writer.writerow({"时间": "2026-08-18T00:00:00Z", "站点编号": "S1", "叶绿素a": "0.03"})
            result = run_water_station_parse(input_path, output_path, source_id="water_station_file")
            self.assertEqual(result["rows"], 1)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()

