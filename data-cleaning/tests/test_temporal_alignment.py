import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.align import align_records, run_alignment, _category
from pipeline.resample import _parse_time


def aligned_row(source, variable, timestamp, value, *, station=None, scene=None, lon=120.0, lat=31.2):
    row = {
        "source_id": source,
        "station_id": station,
        "scene_id": scene,
        "variable_code": variable,
        "observed_at": timestamp,
        "time_bucket": timestamp,
        "clean_value": value,
        "longitude": lon,
        "latitude": lat,
        "quality_flags": [],
    }
    row["_time"] = _parse_time(timestamp)
    row["_category"] = _category(row)
    return row


class TemporalAlignmentTests(unittest.TestCase):
    def test_ground_remote_pair_is_ideal_within_three_hours(self):
        rows = [
            aligned_row("copernicus_sentinel2", "remote_bloom_area", "2025-06-01T12:00:00+00:00", 100.0, scene="S2"),
            aligned_row("taihu_station", "chlorophyll_a", "2025-06-01T14:00:00+00:00", 20.0, station="S1"),
        ]
        result = align_records(rows)
        match = next(item for item in result["records"] if item["feature_variable_code"] == "chlorophyll_a")
        self.assertEqual(match["time_match_class"], "ideal_3h")
        self.assertEqual(match["time_window_hours"], 3.0)
        self.assertEqual(match["time_gap_hours"], 2.0)
        self.assertEqual(match["time_gap_signed_hours"], 2.0)
        self.assertEqual(match["match_status"], "matched_temporal_spatial")

    def test_ground_remote_between_three_and_twenty_four_hours_is_regular(self):
        rows = [
            aligned_row("copernicus_sentinel2", "remote_bloom_area", "2025-06-01T12:00:00+00:00", 100.0, scene="S2"),
            aligned_row("taihu_station", "chlorophyll_a", "2025-06-01T20:00:00+00:00", 20.0, station="S1"),
        ]
        result = align_records(rows)
        match = next(item for item in result["records"] if item["feature_variable_code"] == "chlorophyll_a")
        self.assertEqual(match["time_match_class"], "regular_24h")
        self.assertEqual(match["time_window_hours"], 24.0)
        self.assertEqual(match["time_gap_hours"], 8.0)

    def test_ground_remote_over_twenty_four_hours_is_unmatched(self):
        rows = [
            aligned_row("copernicus_sentinel2", "remote_bloom_area", "2025-06-01T12:00:00+00:00", 100.0, scene="S2"),
            aligned_row("taihu_station", "chlorophyll_a", "2025-06-02T13:00:00+00:00", 20.0, station="S1"),
        ]
        result = align_records(rows)
        match = next(item for item in result["records"] if item["feature_variable_code"] == "chlorophyll_a")
        self.assertEqual(match["match_status"], "unmatched")
        self.assertEqual(match["time_match_class"], "unmatched")
        self.assertIsNone(match["time_gap_hours"])

    def test_ordinary_driver_uses_nearest_twenty_four_hour_window(self):
        rows = [
            aligned_row("taihu_station", "chlorophyll_a", "2025-06-01T12:00:00+00:00", 20.0, station="S1"),
            aligned_row("nasa_power_hourly", "air_temperature", "2025-06-02T08:00:00+00:00", 25.0, station=None, scene=None, lon=120.0, lat=31.2),
        ]
        result = align_records(rows)
        match = next(item for item in result["records"] if item["feature_variable_code"] == "air_temperature")
        self.assertEqual(match["time_match_class"], "regular_24h")
        self.assertEqual(match["time_gap_hours"], 20.0)
        self.assertEqual(match["time_gap_signed_hours"], 20.0)

    def test_run_alignment_persists_time_audit_fields(self):
        rows = [
            aligned_row("taihu_station", "chlorophyll_a", "2025-06-01T12:00:00+00:00", 20.0, station="S1"),
            aligned_row("nasa_power_hourly", "air_temperature", "2025-06-01T13:00:00+00:00", 25.0, lon=120.0, lat=31.2),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "resampled.csv"
            serializable = [{key: value for key, value in item.items() if not key.startswith("_")} for item in rows]
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=serializable[0].keys())
                writer.writeheader()
                writer.writerows(serializable)
            result = run_alignment(input_path, root / "out", root / "align.sqlite", run_id="align-test")
            self.assertEqual(result["thresholds"]["max_time_diff_hours"], 24.0)
            connection = sqlite3.connect(result["database"])
            try:
                columns = {item[1] for item in connection.execute("PRAGMA table_info(temporal_alignments)")}
                self.assertTrue({"time_gap_signed_hours", "time_window_hours", "time_match_class", "matching_strategy", "alignment_reason"}.issubset(columns))
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
