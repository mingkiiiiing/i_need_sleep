import csv
import tempfile
import unittest
from pathlib import Path

from pipeline.experiment import run_split, split_dataset


def row(day, station="S1", key=None):
    return {
        "target_feature_row_key": key or f"{station}|{day}",
        "target_time_bucket": f"2020-01-{day:02d}T00:00:00+00:00",
        "target_station_id": station,
        "target_variable_code": "pH",
        "feature_observed_count": "2",
        "feature_missing_count": "0",
        "leakage_check": "passed",
    }


class ExperimentSplitTests(unittest.TestCase):
    def test_time_split_keeps_same_day_together_and_is_chronological(self):
        rows = [row(day, key=f"k{day}a") for day in range(1, 11)] + [row(day, key=f"k{day}b") for day in range(1, 11)]
        result = split_dataset(rows, train_fraction=0.6, validation_fraction=0.2)
        by_day = {}
        for item in result["rows"]:
            day = item["split_time_group"]
            by_day.setdefault(day, set()).add(item["dataset_split"])
        self.assertTrue(all(len(splits) == 1 for splits in by_day.values()))
        self.assertTrue(result["audit"]["time_order_ok"])
        self.assertEqual(result["audit"]["duplicate_target_key_count"], 0)

    def test_group_split_holds_out_requested_station(self):
        rows = [row(day, station="S1") for day in range(1, 4)] + [row(day, station="S2") for day in range(1, 4)]
        result = split_dataset(rows, strategy="group", group_field="target_station_id", validation_groups={"S1"}, test_groups={"S2"})
        splits = {item["target_station_id"]: item["dataset_split"] for item in result["rows"]}
        self.assertEqual(splits["S1"], "validation")
        self.assertEqual(splits["S2"], "test")

    def test_missing_time_is_excluded(self):
        rows = [row(1), {**row(2), "target_time_bucket": "invalid"}]
        result = split_dataset(rows)
        self.assertEqual(len(result["excluded"]), 1)
        self.assertEqual(result["audit"]["excluded_missing_time_count"], 1)

    def test_duplicate_target_key_is_audited(self):
        rows = [row(1, key="same"), row(1, key="same")]
        result = split_dataset(rows)
        self.assertEqual(result["audit"]["duplicate_target_key_count"], 1)

    def test_run_split_accepts_batch_manifest_and_database_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "features.csv"
            with input_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row(1).keys()))
                writer.writeheader()
                for day in range(1, 5):
                    writer.writerow(row(day, key=f"key{day}"))
            manifest_path = root / "manifests" / "split.json"
            result = run_split(input_path, root / "out", root / "batch.db", manifest_path=manifest_path, run_id="batch_split")
            self.assertEqual(result["run_id"], "batch_split")
            self.assertTrue(manifest_path.exists())
            self.assertTrue(Path(result["files"]["train"]).exists())


if __name__ == "__main__":
    unittest.main()
