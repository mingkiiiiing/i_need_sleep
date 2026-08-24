import pandas as pd

from pipeline.release import _sqlite_projection, split_by_target_time


def test_split_by_target_time_is_group_safe_and_leakage_free():
    frame = pd.DataFrame({
        "feature_date": ["2020-01-01", "2020-01-02", "2020-02-01", "2020-03-01", "2020-04-01"] * 2,
        "target_time": ["2020-01-03", "2020-01-03", "2020-02-03", "2020-03-03", "2020-04-03"] * 2,
        "target_value": range(10),
    })
    splits, audit = split_by_target_time(frame)
    sets = {name: set(part.target_time) for name, part in splits.items()}
    assert sets["train"].isdisjoint(sets["validation"])
    assert sets["train"].isdisjoint(sets["test"])
    assert audit["feature_target_time_violations"] == 0
    assert all(value == 0 for value in audit["target_time_overlap"].values())


def test_sqlite_projection_is_explicit_and_bounded():
    frame = pd.DataFrame({f"x_{i}": [i] for i in range(10)} | {"target_value": [1]})
    projected, omitted = _sqlite_projection(frame, limit=5)
    assert "target_value" in projected
    assert len(projected.columns) == 5
    assert len(omitted) == 6
