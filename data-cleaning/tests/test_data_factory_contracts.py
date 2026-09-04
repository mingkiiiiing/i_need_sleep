"""data_factory 契约层测试：哈希、网格 ID、切分锁定。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_factory.contracts.spatial import cell_indices
from data_factory.contracts.splits import build_split_manifest
from data_factory.labeling.thresholds import bloom_binary, load_thresholds, risk_level_series
from data_factory.lineage.hashing import compute_sample_id, content_hash, row_hash


class TestHashing:
    def test_row_hash_deterministic_and_key_order_free(self):
        a = row_hash({"a": 1, "b": 2.0})
        b = row_hash({"b": 2.0, "a": 1})
        assert a == b
        assert len(a) == 64

    def test_row_hash_nan_inf_canonicalized(self):
        assert row_hash({"x": float("nan")}) == row_hash({"x": None})
        assert row_hash({"x": float("inf")}) == row_hash({"x": None})

    def test_row_hash_round6_stability(self):
        assert row_hash({"v": 0.123456789}) == row_hash({"v": 0.1234567})

    def test_content_hash(self):
        assert content_hash("abc") == content_hash("abc")
        assert content_hash("abc") != content_hash("abd")

    def test_compute_sample_id_stable(self):
        kwargs = dict(spatial_id="G00010001", issue_time="2024-03-01T12:00:00+08:00", target_date="2024-03-02", task_id="T1", horizon=1, dataset_version="mvp")
        assert compute_sample_id(**kwargs) == compute_sample_id(**kwargs)
        assert compute_sample_id(**kwargs) != compute_sample_id(**{**kwargs, "horizon": 3})


class TestCellIndices:
    def test_round_trip(self):
        grid_ids = pd.Series(["G00010002", "G00120034"])
        ix, iy = cell_indices(grid_ids)
        assert ix.tolist() == [1, 12]
        assert iy.tolist() == [2, 34]

    def test_shape(self):
        ix, iy = cell_indices([f"G{a:04d}{b:04d}" for a, b in [(0, 0), (3, 5), (10, 20)]])
        assert len(ix) == len(iy) == 3


class TestSplits:
    def test_proportions_and_monotonic(self):
        dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
        isolation_days = 30
        frame = build_split_manifest(dates, train_fraction=0.7, validation_fraction=0.15, isolation_days=isolation_days)
        assert len(frame) == len(dates)
        assert set(frame["split"]).issubset({"train", "validation", "test", "isolation"})
        by = {name: frame.loc[frame["split"] == name, "date"].sort_values() for name in ("train", "validation", "test", "isolation")}
        # 三个核心 split 严格按时间先后分隔
        assert by["train"].max() < by["validation"].min() < by["test"].min()
        assert by["validation"].max() < by["test"].max()
        # 隔离窗只出现在 train/validation 与 validation/test 交界处
        assert abs((by["isolation"].min() - by["train"].max()).days) <= isolation_days
        assert abs((by["isolation"].max() - by["validation"].max()).days) <= isolation_days

    def test_same_date_same_split(self):
        dates = pd.date_range("2024-01-01", periods=90, freq="D")
        frame = build_split_manifest(dates, train_fraction=0.7, validation_fraction=0.15, isolation_days=10)
        assert frame["date"].duplicated().sum() == 0


class TestThresholds:
    TH = {
        "threshold_set_id": "th-test",
        "frozen": True,
        "bloom": {"grid_fraction_positive": 0.05, "zone_area_km2_positive": 1.0, "lake_area_km2_positive": 10.0, "satellite_detection_min_fraction": 0.02},
        "chla_ug_l": {"warning": 30.0, "alert": 60.0},
    }

    def test_load_thresholds_requires_frozen(self):
        with pytest.raises(SystemExit):
            load_thresholds({**self.TH, "frozen": False})

    def test_bloom_binary_grid_fraction(self):
        th = load_thresholds(self.TH)
        assert bloom_binary(np.array([0.04, 0.05, 0.5]), "grid", th).tolist() == [0, 1, 1]

    def test_bloom_binary_zone_area(self):
        th = load_thresholds(self.TH)
        assert bloom_binary(np.array([0.9, 1.0, 12.0]), "zone", th).tolist() == [0, 1, 1]

    def test_risk_level_persistence(self):
        chla = np.full(10, 70.0)
        frac = np.array([0.0, 0.0, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06])
        levels = risk_level_series(chla, frac)
        assert levels[0] == 1  # chla 超警戒
        assert levels[4] == 2  # 连续 3 天 ≥0.05（第 3 天为 idx4）
        assert levels[9] == 3  # 连续 7 天 ≥0.05
        calm = risk_level_series(np.full(10, 5.0), np.full(10, 0.0))
        assert calm.tolist() == [0] * 10
