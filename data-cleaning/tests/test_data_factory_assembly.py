"""data_factory 装配层测试：member C 适配器与样本契约。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from data_factory.assembly.horizons import FEATURE_LAGS, FEATURE_ROLLS, _augment_frame, _features_at, expand_samples
from data_factory.assembly.member_c_adapter import FEATURE_COLUMNS, TASK_TO_MEMBER_C, to_member_c
from data_factory.calibration.fitter import _local_naive
from data_factory.lineage.hashing import compute_sample_id


def _sample_frame() -> pd.DataFrame:
    rows = []
    for i, (task, metric_status) in enumerate(
        [("T1", "simulation_positive"), ("T1", "simulation_negative"), ("T3", "measured_value"), ("T7", "simulation_positive"), ("T2", "measured_value")]
    ):
        features = {"water_temperature": 22.5 + i, "wind_speed": 3.1, "shortwave_radiation": 18.4, "unmapped_internal": 1.0}
        rows.append(
            {
                "sample_id": compute_sample_id(spatial_id=f"TAIHU_ML{i}", issue_time="2024-06-01T12:00:00+08:00", target_date="2024-06-02", task_id=task, horizon=1, dataset_version="mvp"),
                "target_date": pd.Timestamp("2024-06-02"),
                "issue_date": pd.Timestamp("2024-06-01"),
                "horizon_days": 1,
                "task_id": task,
                "target_metric": task,  # horizons 装配约定：target_metric 列存 task_id，适配器再映射
                "spatial_id": f"TAIHU_ML{i}",
                "spatial_type": "zone",
                "split": "train" if i % 2 == 0 else "test",
                "label_value": 1.0 if "positive" in metric_status else (0.0 if "negative" in metric_status else 12.5),
                "label_status": metric_status,
                "label_source_type": "simulation_truth",
                "source_type": "simulated",
                "quality_flag": "pass",
                "dataset_version": "mvp",
                "feature_window_note": "lags[1,3,7,14,30]+rolls[3,7,14,30] ending at issue_date",
                "features_json": json.dumps(features, sort_keys=True),
            }
        )
    return pd.DataFrame(rows)


class TestMemberCAdapter:
    def test_columns_and_track(self):
        out, summary = to_member_c(_sample_frame(), track="SIM-V1")
        assert "data_track" in out.columns
        assert (out["data_track"] == "SIM-V1").all()
        assert (out["source_type"] == "simulated").all()
        for external in FEATURE_COLUMNS.values():
            assert external in out.columns, external

    def test_feature_mapping_values(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1")
        row = out.iloc[0]
        assert row["water_temperature_C"] == 22.5
        assert row["wind_speed_m_s"] == 3.1
        assert pd.isna(row["relative_humidity_pct"])  # 未提供内部特征 → 空列

    def test_open_enum_preserved_and_excluded_counted(self):
        out, summary = to_member_c(_sample_frame(), track="SIM-V1", include_open_enum=True)
        # T3→blue_algae_density 属开放枚举，保留并计数；T7 不在成员 C 任务里
        assert "blue_algae_density" in set(out["target_metric"])
        assert summary["rows_excluded_open_enum"] >= 1
        statuses = set(out["label_status"])
        assert "simulation_positive" in statuses  # 枚举外 label_status 原样保留（登记开放问题）

    def test_excludes_t7_when_strict(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1", include_open_enum=False)
        assert "blue_algae_density" not in set(out["target_metric"])
        assert (out["target_metric"].isin({"bloom_label", "bloom_area", "blue_algae_biomass", "chlorophyll_a", "risk_level"})).all()

    def test_unit_mapping(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1")
        chla_rows = out[out["target_metric"] == "chlorophyll_a"]
        assert (chla_rows["target_unit"] == "ug/L").all() if not chla_rows.empty else True


class TestSampleContract:
    def test_sample_id_differs_by_task_and_horizon(self):
        base = dict(spatial_id="X", issue_time="2024-01-01T12:00:00+08:00", target_date="2024-01-02", task_id="T1", horizon=1, dataset_version="v")
        ids = {compute_sample_id(**{**base, **override}) for override in ({}, {"task_id": "T2"}, {"horizon": 7})}
        assert len(ids) == 3

    def test_local_naive_mixed_tz(self):
        series = pd.Series(pd.to_datetime(["2024-03-01T04:00:00+00:00", "2024-03-01T12:00:00+08:00"], utc=True))
        local = _local_naive(series)
        assert local.dt.tz is None
        assert local.iloc[0] == pd.Timestamp("2024-03-01 12:00:00")
        assert local.iloc[1] == pd.Timestamp("2024-03-01 12:00:00")

    def test_local_naive_handles_none(self):
        series = pd.Series([None, "2024-03-01T04:00:00Z"], dtype="object")
        local = _local_naive(series)
        assert pd.isna(local.iloc[0])


class TestHorizonsFeatures:
    def _daily_frame(self) -> pd.DataFrame:
        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        frame = pd.DataFrame({"air_temperature": np.arange(60, dtype=float)}, index=idx)
        frame.loc[idx[10], "air_temperature"] = np.nan
        return frame

    def test_augmented_frame_matches_slice_semantics(self):
        frame = self._daily_frame()
        augmented = _augment_frame(frame)
        series = frame["air_temperature"]
        for date in list(frame.index[35:45]) + [frame.index[0], frame.index[-1]]:
            feats = _features_at(augmented, date, "Z1", "zone", None)
            assert feats["air_temperature"] == round(float(series.loc[date]), 6)
            for lag in FEATURE_LAGS:
                expected = series.get(date - pd.Timedelta(days=lag))
                key = f"air_temperature_lag{lag}"
                if expected is not None and np.isfinite(expected):
                    assert feats[key] == round(float(expected), 6)
                else:
                    assert key not in feats
            for window in FEATURE_ROLLS:
                seg = series.loc[:date].tail(window)
                key = f"air_temperature_roll{window}"
                if len(seg) and np.isfinite(seg.mean()):
                    assert abs(feats[key] - round(float(seg.mean()), 6)) <= 1.5e-6
                else:
                    assert key not in feats

    def test_expand_samples_uses_cache_without_mutation(self):
        frame = self._daily_frame()
        labels = pd.DataFrame(
            [
                {
                    "task_id": "T1",
                    "spatial_id": "Z1",
                    "spatial_type": "zone",
                    "target_date": pd.Timestamp("2024-02-20") + pd.Timedelta(days=off),
                    "label_value": 1.0,
                    "label_unit": "",
                    "label_status": "simulation_positive",
                    "label_source_type": "simulation_truth",
                    "label_quality": "pass",
                    "is_ground_truth": False,
                    "is_synthetic": True,
                }
                for off in range(3)
            ]
        )
        split_of_date = {pd.Timestamp(t).normalize(): "train" for t in labels["target_date"]}
        samples = expand_samples({}, labels=labels, frame=_augment_frame(frame), frac_pivot=None, split_of_date=split_of_date, dataset="t", horizons=(1,))
        assert len(samples) == 3
        for row in samples.itertuples(index=False):
            expected = json.dumps(
                _features_at(_augment_frame(frame), row.issue_date, "Z1", "zone", None), ensure_ascii=False, sort_keys=True
            )
            assert row.features_json == expected
