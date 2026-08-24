import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pipeline.remediation import build_remediation, run_remediation


class RemediationTests(unittest.TestCase):
    def test_builds_open_p0_requests_from_gate_checks(self):
        result = build_remediation(
            {
                "gate_status": "blocked",
                "checks": [
                    {"check_name": "coverage_historical", "status": "blocked", "observed_value": False, "threshold": True, "reason": "coverage missing"},
                    {"check_name": "split_time_order", "status": "passed", "observed_value": True, "threshold": True, "reason": "ordered"},
                ],
            }
        )
        self.assertEqual(result["open_request_count"], 1)
        self.assertEqual(result["resolved_check_count"], 0)
        self.assertEqual(result["requests"][0]["priority"], "P0")
        self.assertEqual(result["requests"][0]["check_name"], "coverage_historical")

    def test_run_writes_csv_json_and_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate_path = root / "gate.json"
            gate_path.write_text(json.dumps({"gate_status": "blocked", "checks": [{"check_name": "coverage_historical", "status": "blocked", "observed_value": False, "threshold": True, "reason": "missing"}]}), encoding="utf-8")
            result = run_remediation(gate_path, root / "out", root / "data.db", manifest_path=root / "manifest.json", run_id="remediation_test")
            self.assertEqual(result["open_request_count"], 1)
            self.assertTrue(Path(result["files"]["requests"]).exists())
            connection = sqlite3.connect(root / "data.db")
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM p0_data_requests").fetchone()[0], 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
