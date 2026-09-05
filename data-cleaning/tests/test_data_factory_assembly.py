"""data_factory 装配层测试：member C 适配器与样本契约。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from data_factory.assembly.horizons import FEATURE_LAGS, FEATURE_ROLLS, _augment_frame, _augment_grid_weather, _features_at, expand_samples
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
                "sample_id": compute_sample_id(spatial_id=f"TAIHU_ML{i}", issue_time="2024-06-01T12:00:00+08:00", target_date="2024-06-02", task_id=task, horizon=1, dataset_version="mvp", scenario_id="baseline_replay", random_seed=20260904, driver_hash="d" * 64),
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

    def test_t3_t7_formal_metrics_included(self):
        out, summary = to_member_c(_sample_frame(), track="SIM-V1")
        # 2026-09-05 契约收尾：T3→blue_algae_density、T7→spatial_extent 正式进入枚举，不再剔除
        assert {"blue_algae_density", "spatial_extent"} <= set(out["target_metric"])
        assert summary["rows_excluded_open_enum"] == 0
        statuses = set(out["label_status"])
        assert "simulation_positive" in statuses  # simulation_* 已入契约枚举（第二轮验收对齐）
        assert summary["open_enum_note"]  # V04 依赖该说明字段存在

    def test_split_column_preserved(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1")
        assert "split" in out.columns
        assert set(out["split"]) == {"train", "test"}

    def test_unit_mapping(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1")
        chla_rows = out[out["target_metric"] == "chlorophyll_a"]
        assert (chla_rows["target_unit"] == "ug/L").all() if not chla_rows.empty else True
        t7_rows = out[out["target_metric"] == "spatial_extent"]
        assert (t7_rows["target_unit"] == "0/1").all() if not t7_rows.empty else True


def _contract_enum(field_name: str) -> set[str]:
    import csv
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "里程碑7_成员C机理AI融合建模"
        / "01_成果"
        / "member_c_modeling_framework"
        / "required_training_schema_V0.1.csv"
    )
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["field_name"] == field_name:
                return set(row["unit_or_allowed_values"].split("|"))
    raise AssertionError(f"field {field_name} not found in contract")


class TestContractAlignment:
    """适配器实际输出值必须落在成员 C 契约枚举内（第二轮验收缺口 #3 的回归门）。"""

    def test_adapter_output_within_contract_enums(self):
        out, _ = to_member_c(_sample_frame(), track="SIM-V1")
        assert set(out["spatial_type"]) <= _contract_enum("spatial_type")
        assert set(out["label_status"]) <= _contract_enum("label_status")
        assert set(out["source_type"]) <= _contract_enum("source_type")
        assert set(out["target_metric"]) <= _contract_enum("target_metric")
        assert set(out["target_unit"]) <= _contract_enum("target_unit")
        assert set(out["split"]) <= _contract_enum("split")


class TestSampleContract:
    def test_sample_id_differs_by_task_and_horizon(self):
        base = dict(
            spatial_id="X",
            issue_time="2024-01-01T12:00:00+08:00",
            target_date="2024-01-02",
            task_id="T1",
            horizon=1,
            dataset_version="v",
            scenario_id="baseline_replay",
            random_seed=20260904,
            driver_hash="d" * 64,
        )
        ids = {compute_sample_id(**{**base, **override}) for override in ({}, {"task_id": "T2"}, {"horizon": 7}, {"scenario_id": "heatwave_calm"}, {"random_seed": 7})}
        assert len(ids) == 5

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
        samples = expand_samples(
            {},
            labels=labels,
            frames={"Z1": _augment_frame(frame)},
            grid_weather=None,
            frac_pivot=None,
            split_of_date=split_of_date,
            dataset="t",
            identity={"scenario_id": "baseline_replay", "random_seed": 20260904, "driver_hash": "d" * 64, "driver_type": "observed_replay"},
            horizons=(1,),
        )
        assert len(samples) == 3
        for row in samples.itertuples(index=False):
            expected = json.dumps(
                _features_at(_augment_frame(frame), row.issue_date, "Z1", "zone", None), ensure_ascii=False, sort_keys=True
            )
            assert row.features_json == expected

    def test_grid_samples_use_per_grid_driver_weather(self):
        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        zone = pd.DataFrame({"air_temperature": np.full(60, 20.0), "wind_speed": np.full(60, 3.0)}, index=idx)
        long_rows = []
        for grid_id, temp in (("G1", 21.5), ("G2", 18.5)):
            for date in idx:
                long_rows.append({"grid_id": grid_id, "date": date, "air_temperature": temp, "wind_speed": 3.0})
        grid_weather = _augment_grid_weather(pd.DataFrame(long_rows))
        labels = pd.DataFrame(
            [
                {
                    "task_id": "T1",
                    "spatial_id": grid_id,
                    "spatial_type": "grid",
                    "target_date": pd.Timestamp("2024-02-20"),
                    "label_value": 1.0,
                    "label_unit": "",
                    "label_status": "simulation_positive",
                    "label_source_type": "simulation_truth",
                    "label_quality": "pass",
                    "is_ground_truth": False,
                    "is_synthetic": True,
                }
                for grid_id in ("G1", "G2")
            ]
            + [
                {  # 同帧同日的 zone 样本：不得复用 grid 的 AUX 缓存（回归：缓存命名空间）
                    "task_id": "T1",
                    "spatial_id": "TAIHU_ML",
                    "spatial_type": "zone",
                    "target_date": pd.Timestamp("2024-02-20"),
                    "label_value": 0.0,
                    "label_unit": "",
                    "label_status": "simulation_negative",
                    "label_source_type": "simulation_truth",
                    "label_quality": "pass",
                    "is_ground_truth": False,
                    "is_synthetic": True,
                }
            ]
        )
        samples = expand_samples(
            {},
            labels=labels,
            frames={"TAIHU_ML": _augment_frame(zone)},
            grid_weather=grid_weather,
            frac_pivot=None,
            split_of_date={pd.Timestamp("2024-02-20"): "train"},
            dataset="t",
            identity={"scenario_id": "s", "random_seed": 1, "driver_hash": "d" * 64, "driver_type": "observed_replay"},
            grid_zone_of={"G1": "TAIHU_ML", "G2": "TAIHU_ML"},
            horizons=(1,),
        )
        assert len(samples) == 3
        by_grid = {row.spatial_id: json.loads(row.features_json) for row in samples.itertuples(index=False)}
        assert by_grid["G1"]["air_temperature"] == 21.5  # 逐格驱动值，非 zone 均值 20
        assert by_grid["G2"]["air_temperature"] == 18.5
        assert by_grid["G1"]["air_temperature_lag1"] == 21.5  # lag/roll 也按格内序列
        assert by_grid["TAIHU_ML"]["air_temperature"] == 20.0  # zone 样本用驱动 zone 均值
        assert "air_temperature_lag1" in by_grid["TAIHU_ML"]

    def test_min_issue_date_rejects_early_issue_window(self):
        frame = self._daily_frame()
        labels = pd.DataFrame(
            [
                {
                    "task_id": "T1",
                    "spatial_id": "Z1",
                    "spatial_type": "zone",
                    "target_date": pd.Timestamp("2024-02-20"),
                    "label_value": 1.0,
                    "label_unit": "",
                    "label_status": "simulation_positive",
                    "label_source_type": "simulation_truth",
                    "label_quality": "pass",
                    "is_ground_truth": False,
                    "is_synthetic": True,
                }
            ]
        )
        common = dict(
            labels=labels,
            frames={"Z1": _augment_frame(frame)},
            grid_weather=None,
            frac_pivot=None,
            split_of_date={pd.Timestamp("2024-02-20"): "train"},
            dataset="t",
            identity={"scenario_id": "s", "random_seed": 1, "driver_hash": "d" * 64, "driver_type": "synthetic"},
            horizons=(1,),
        )
        assert len(expand_samples({}, **common)) == 1
        rejected = expand_samples({}, **common, min_issue_date=pd.Timestamp("2024-02-20"))
        assert rejected.empty  # issue_date 2024-02-19 < min_issue_date → 整行拒绝
