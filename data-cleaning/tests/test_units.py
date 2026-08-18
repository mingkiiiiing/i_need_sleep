import unittest

from pipeline.qc import quality_control
from pipeline.units import standardize_units


class UnitTests(unittest.TestCase):
    def _row(self, unit, value=1000.0):
        return {
            "source_id": "unit_fixture",
            "source_file": "unit.csv",
            "source_row": "1",
            "station_id": "T01",
            "observed_at": "2025-06-01T00:00:00+00:00",
            "variable_code": "total_nitrogen",
            "observed_value": value,
            "clean_value": value,
            "unit": unit,
            "value_origin": "observed",
            "is_imputed": False,
            "quality_flags": [],
        }

    def test_configured_conversion_keeps_source_unit(self):
        row = self._row("ug/L")
        standardize_units([row])
        self.assertEqual(row["source_unit"], "ug/L")
        self.assertEqual(row["unit"], "mg/L")
        self.assertEqual(row["clean_value"], 1.0)
        self.assertIn("ug/L->mg/L", row["conversion_rule"])
        self.assertIn("Q21", row["quality_flags"])

    def test_incompatible_unit_is_rejected_by_qc(self):
        row = self._row("m/s")
        standardize_units([row])
        qc = quality_control([row])
        self.assertEqual(len(qc["rejected"]), 1)
        self.assertEqual(qc["flag_counts"]["Q11"], 1)

    def test_missing_unit_is_rejected_by_qc(self):
        row = self._row(None)
        standardize_units([row])
        qc = quality_control([row])
        self.assertEqual(len(qc["rejected"]), 1)
        self.assertEqual(qc["flag_counts"]["Q10"], 1)


if __name__ == "__main__":
    unittest.main()
