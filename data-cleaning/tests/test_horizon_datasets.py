import tempfile
import unittest
from pathlib import Path

import pandas as pd

from pipeline.horizon_datasets import assess_horizon_readiness, build_supervised_horizon, run_horizon_dataset_gate


class HorizonDatasetGateTests(unittest.TestCase):
    def test_public_features_cannot_be_mislabeled_as_trainable(self):
        frame = pd.DataFrame({"feature_date": ["2020-01-01"], "direct_air_temperature": [20.0]})
        short = assess_horizon_readiness(frame, "h1_3d")
        long = assess_horizon_readiness(frame, "h30_90d")
        self.assertEqual(short["status"], "BLOCKED_DATA")
        self.assertEqual(long["status"], "BLOCKED_AUTH")
        self.assertEqual(len(long["blockers"]), 2)

    def test_gate_writes_only_candidate_when_target_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "features.parquet"
            pd.DataFrame({"feature_date": ["2020-01-01"], "x": [1]}).to_parquet(source, index=False)
            result = run_horizon_dataset_gate(source, root / "out", horizon="h7_15d")
            self.assertFalse(result["trainable"])
            self.assertTrue(Path(result["candidate_labelled_dataset"]).exists())
            self.assertFalse((root / "out" / "dataset_h7_15d.parquet").exists())

    def test_real_future_targets_are_selected_without_interpolation(self):
        frame = pd.DataFrame({"feature_date": pd.date_range("2020-01-01", "2020-01-20").astype(str), "direct_phytoplankton_biomass": [None] * 11 + [5.0] + [None] * 8})
        result, audit = build_supervised_horizon(frame, "h7_15d")
        self.assertGreater(len(result), 0)
        self.assertTrue((pd.to_datetime(result["target_time"]) > pd.to_datetime(result["feature_date"])).all())
        self.assertTrue((result["target_interpolated"] == 0).all())
        self.assertEqual(audit["leakage_violations"], 0)
