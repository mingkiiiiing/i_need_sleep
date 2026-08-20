import numpy as np
import pandas as pd

from pipeline.retrieval_calibration import FEATURES, calibrate_chlorophyll


def test_calibration_uses_leave_date_out_groups():
    rows = []
    for group, date in enumerate(["2020-01-01", "2021-01-01", "2022-01-01"]):
        for index in range(6):
            ndci = 0.02 * index + 0.01 * group
            row = {feature: ndci + offset * 0.001 for offset, feature in enumerate(FEATURES)}
            row.update(observed_at=f"{date}T00:00:00+00:00", chlorophyll_a_ug_l=5 + 40 * ndci)
            rows.append(row)
    _, audit, metrics = calibrate_chlorophyll(pd.DataFrame(rows))
    assert audit["date_groups"] == 3
    assert audit["validation"].startswith("leave_one_date_out")
    assert set(metrics["model"]) == {"linear", "random_forest"}
