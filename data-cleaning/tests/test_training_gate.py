import unittest

from pipeline.training_gate import evaluate_training_gate


class TrainingGateTests(unittest.TestCase):
    def test_blocks_short_term_when_required_horizons_are_missing(self):
        result = evaluate_training_gate(
            {"short_term_ready": False, "operational_short_term_ready": False},
            [
                {"horizon": "horizon_1_3d", "availability_rate": "0", "overall_status": "blocked_no_labels"},
                {"horizon": "horizon_7_15d", "availability_rate": "0", "overall_status": "blocked_no_labels"},
            ],
            {"duplicate_target_key_count": 0, "time_order_ok": True},
            [
                {"dataset_split": "train", "missing_feature_rate": "0.2"},
                {"dataset_split": "validation", "missing_feature_rate": "0.2"},
                {"dataset_split": "test", "missing_feature_rate": "0.3"},
            ],
        )
        self.assertEqual(result["gate_status"], "blocked")
        self.assertTrue(any("horizon_1_3d" in reason for reason in result["reasons"]))
        self.assertEqual(result["blocked_check_count"], 4)

    def test_passes_when_all_required_checks_meet_thresholds(self):
        result = evaluate_training_gate(
            {"short_term_ready": True, "operational_short_term_ready": True},
            [
                {"horizon": "horizon_1_3d", "availability_rate": "0.8", "overall_status": "ready"},
                {"horizon": "horizon_7_15d", "availability_rate": "0.6", "overall_status": "ready"},
            ],
            {"duplicate_target_key_count": 0, "time_order_ok": True},
            [
                {"dataset_split": "train", "missing_feature_rate": "0.2"},
                {"dataset_split": "validation", "missing_feature_rate": "0.2"},
                {"dataset_split": "test", "missing_feature_rate": "0.3"},
            ],
        )
        self.assertEqual(result["gate_status"], "ready")
        self.assertEqual(result["blocked_check_count"], 0)


if __name__ == "__main__":
    unittest.main()
