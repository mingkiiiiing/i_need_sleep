import csv
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pipeline.quality_report import build_quality_report, run_quality_report


class UnifiedQualityReportTests(unittest.TestCase):
    def test_unified_counts_cover_missing_anomaly_imputation_proxy_and_conflict(self):
        normalized = [
            {"source_id": "station", "station_id": "S1", "observed_at": "2026-08-17T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "10", "value_origin": "observed", "quality_flags": "[]", "is_imputed": "False"},
            {"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "", "value_origin": "observed", "quality_flags": "[\"Q01\"]", "is_imputed": "False"},
            {"source_id": "weather", "station_id": "W1", "observed_at": "2026-08-10T00:00:00+00:00", "variable_code": "air_temperature", "unit": "degC", "clean_value": "28", "value_origin": "forecast_proxy", "quality_flags": "[]", "is_imputed": "True"},
        ]
        cleaned = [normalized[0], {**normalized[2], "is_imputed": "True"}]
        suspect = [{**normalized[0], "quality_flags": "[\"Q18\"]"}]
        rejected = [{"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T01:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "-1"}]
        pending = [{"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T02:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "", "value_origin": "observed"}]
        conflicts = [{"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T03:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "12"}]
        issues = [
            {"source_id": "station", "variable_code": "chlorophyll_a", "issue_code": "Q18"},
            {"source_id": "station", "variable_code": "chlorophyll_a", "issue_code": "Q41"},
        ]
        audits = [
            {"source_id": "station", "variable_code": "chlorophyll_a", "action": "deduplicated_exact"},
            {"source_id": "station", "variable_code": "chlorophyll_a", "action": "pending_conflict"},
        ]
        result = build_quality_report(
            cleaned,
            normalized_rows=normalized,
            suspect_rows=suspect,
            rejected_rows=rejected,
            pending_rows=pending,
            conflict_rows=conflicts,
            issue_rows=issues,
            duplicate_audit_rows=audits,
            as_of=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
        station = next(row for row in result["rows"] if row["source_id"] == "station")
        weather = next(row for row in result["rows"] if row["source_id"] == "weather")
        self.assertEqual(station["input_rows"], 2)
        self.assertEqual(station["cleaned_rows"], 1)
        self.assertEqual(station["missing_value_rows"], 1)
        self.assertEqual(station["rejected_rows"], 1)
        self.assertEqual(station["pending_imputation_rows"], 1)
        self.assertEqual(station["pending_conflict_rows"], 1)
        self.assertEqual(station["anomaly_rows"], 2)
        self.assertEqual(station["exact_duplicates_removed"], 1)
        self.assertEqual(station["conflict_audit_rows"], 1)
        self.assertIn('"Q18": 1', station["issue_code_counts"])
        self.assertEqual(weather["proxy_rows"], 1)
        self.assertEqual(weather["imputed_rows"], 1)
        self.assertEqual(result["overall"]["sources"], 2)
        self.assertEqual(result["overall"]["pending_conflict_rows"], 1)
        self.assertGreater(result["overall"]["anomaly_rate"], 0)

    def test_run_quality_report_ingests_all_artifact_files_and_exposes_overall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fields = ["source_id", "station_id", "observed_at", "variable_code", "unit", "clean_value", "value_origin", "quality_flags", "is_imputed"]
            for name, rows in {
                "normalized_observations.csv": [{"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "10", "value_origin": "observed", "quality_flags": "[]", "is_imputed": "False"}],
                "cleaned_observations.csv": [{"source_id": "station", "station_id": "S1", "observed_at": "2026-08-18T00:00:00+00:00", "variable_code": "chlorophyll_a", "unit": "ug/L", "clean_value": "10", "value_origin": "observed", "quality_flags": "[]", "is_imputed": "False"}],
                "suspect_records.csv": [], "rejected_records.csv": [], "imputation_candidates.csv": [], "pending_conflicts.csv": [], "duplicate_audit.csv": [],
            }.items():
                path = root / name
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
            issues = root / "qc_issues.csv"
            with issues.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["source_id", "variable_code", "issue_code"])
                writer.writeheader()
                writer.writerow({"source_id": "station", "variable_code": "chlorophyll_a", "issue_code": "Q18"})
            result = run_quality_report(root / "cleaned_observations.csv", root / "report", root / "report.db", normalized_path=root / "normalized_observations.csv", suspect_path=root / "suspect_records.csv", pending_conflicts_path=root / "pending_conflicts.csv", duplicate_audit_path=root / "duplicate_audit.csv", issues_path=issues)
            self.assertEqual(result["status"], "completed_with_warnings")
            overall = json.loads((root / "report" / "quality_report_overall.json").read_text(encoding="utf-8"))
            self.assertEqual(overall["input_rows"], 1)
            self.assertEqual(overall["anomaly_rows"], 1)
            connection = sqlite3.connect(root / "report.db")
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(quality_report)")}
                self.assertIn("anomaly_rate", columns)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
