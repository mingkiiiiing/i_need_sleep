import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.remote import calibrate_chlorophyll, index_pixels, pair_remote_ground


class RemoteTests(unittest.TestCase):
    def test_index_masks_cloud_and_calculates_indices(self):
        rows = [
            {
                "scene_id": "S1", "acquisition_at": "2025-06-01T02:00:00Z", "pixel_id": "p1",
                "longitude": 120.3, "latitude": 31.2, "pixel_area_km2": 0.01,
                "band_b03_reflectance": 0.10, "band_b04_reflectance": 0.05, "band_b05_reflectance": 0.10, "band_b08_reflectance": 0.20, "band_b11_reflectance": 0.05,
                "scene_classification": 6, "cloud_probability": 10,
            },
            {
                "scene_id": "S1", "acquisition_at": "2025-06-01T02:00:00Z", "pixel_id": "p2",
                "longitude": 120.31, "latitude": 31.2, "pixel_area_km2": 0.01,
                "band_b03_reflectance": 0.10, "band_b04_reflectance": 0.05, "band_b05_reflectance": 0.06, "band_b08_reflectance": 0.08, "band_b11_reflectance": 0.04,
                "scene_classification": 9, "cloud_probability": 90,
            },
        ]
        result = index_pixels(rows, fai_threshold=0.0)
        self.assertEqual(len(result["pixels"]), 2)
        self.assertTrue(result["pixels"][0]["valid_pixel"])
        self.assertEqual(result["pixels"][0]["remote_bloom_class"], "suspected_bloom")
        self.assertGreater(result["pixels"][0]["fai"], 0)
        self.assertFalse(result["pixels"][1]["valid_pixel"])
        self.assertEqual(result["summaries"][0]["remote_bloom_area_km2"], 0.01)

    def test_pair_and_temporal_holdout_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote_path = root / "remote.csv"
            ground_path = root / "ground.csv"
            with remote_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["scene_id", "acquisition_at", "longitude", "latitude", "mean_fai", "mean_mci", "mean_ndwi", "remote_bloom_area_km2"])
                writer.writeheader()
                for index in range(12):
                    writer.writerow({"scene_id": f"S{index}", "acquisition_at": f"2020-01-{index+1:02d}T02:00:00+00:00", "longitude": 120.3, "latitude": 31.2, "mean_fai": 0.01 * index, "mean_mci": 0.02 * index, "mean_ndwi": 0.1, "remote_bloom_area_km2": 1.0})
            with ground_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["station_id", "observed_at", "longitude", "latitude", "chlorophyll_a"])
                writer.writeheader()
                for index in range(12):
                    writer.writerow({"station_id": "T01", "observed_at": f"2020-01-{index+1:02d}T03:00:00+00:00", "longitude": 120.3, "latitude": 31.2, "chlorophyll_a": 2.0 + 0.2 * index})
            paired = pair_remote_ground(remote_path, ground_path, max_time_diff_hours=2, max_space_m=1000)
            self.assertEqual(paired["counts"]["matched_temporal_spatial"], 12)
            pair_path = root / "pairs.csv"
            with pair_path.open("w", encoding="utf-8", newline="") as handle:
                fieldnames = ["acquisition_at", "mean_fai", "mean_mci", "mean_ndwi", "ground_chlorophyll_a"]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for index in range(12):
                    writer.writerow({"acquisition_at": f"2020-01-{index+1:02d}T02:00:00+00:00", "mean_fai": 0.01 * index, "mean_mci": 0.02 * index, "mean_ndwi": 0.1, "ground_chlorophyll_a": 2.0 + 0.2 * index})
            model = calibrate_chlorophyll(pair_path, min_pairs=10)
            self.assertEqual(model["status"], "completed")
            self.assertEqual(model["model"]["validation_metrics"]["n"], 2)
            blocked = calibrate_chlorophyll(pair_path, min_pairs=20)
            self.assertEqual(blocked["status"], "blocked_insufficient_ground_truth")


if __name__ == "__main__":
    unittest.main()
