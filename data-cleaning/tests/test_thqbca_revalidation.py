import csv
import json

from pipeline.thqbca_revalidation import _csv_summary


def test_csv_summary_counts_rows_variables_and_time_range(tmp_path):
    path = tmp_path / "observations.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variable_code", "observed_at"])
        writer.writeheader()
        writer.writerows([
            {"variable_code": "air_temperature", "observed_at": "2020-01-02T00:00:00+00:00"},
            {"variable_code": "air_temperature", "observed_at": "2020-01-01T00:00:00+00:00"},
            {"variable_code": "water_level", "observed_at": "2020-01-01T00:00:00+00:00"},
        ])
    assert _csv_summary(path) == {
        "records": 3,
        "by_variable": {"air_temperature": 2, "water_level": 1},
        "observed_at_min": "2020-01-01T00:00:00+00:00",
        "observed_at_max": "2020-01-02T00:00:00+00:00",
    }
