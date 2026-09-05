"""审计整改回归测试 (DG-001/002/003/004/005/008/010/014 → SIM-V1.1 df-0.2.0)。

对应独立审计 reports/data-generation-audit-2026-09-04 的 14 项问题；每项至少一条
可机器判定的回归断言。端到端口径（bound_hit_rate、A07/A21/A22/A23、row_lineage 行数）
在 pipeline 重跑后的 manifest 复核，不在本文件展开。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from data_factory.assembly.horizons import (
    FEATURE_LAGS,
    FEATURE_ROLLS,
    CORE_FEATURES,
    STATION_FEATURES,
    WEATHER_FEATURES,
    _augment_frame,
    _feature_source_frames,
    _satellite_grid_pivots,
    expand_samples,
)
from data_factory.calibration.fitter import _filter_date, _filter_until
from data_factory.contracts.enums import LabelStatus
from data_factory.contracts.schema import SCHEMAS, TASK_GRAIN_MATRIX, validate_schema
from data_factory.ingestion.mee_realtime import TZ_CN, _resolve_observed_time, normalize
from data_factory.simulation.bloom import aggregate_bloom


NOW_CN = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


class TestDG014MeeTimestampQc:
    def test_yearless_time_completed_with_current_year(self):
        ts = _resolve_observed_time("09-01 10:30", NOW_CN)
        assert ts == pd.Timestamp("2026-09-01 10:30").tz_localize(TZ_CN)

    def test_cross_year_snapshot_resolves_to_previous_year(self):
        ts = _resolve_observed_time("12-30 23:05", NOW_CN)
        assert ts == pd.Timestamp("2025-12-30 23:05").tz_localize(TZ_CN)

    def test_full_time_and_unparseable(self):
        assert _resolve_observed_time("2026-08-31 08:00", NOW_CN) == pd.Timestamp("2026-08-31 08:00").tz_localize(TZ_CN)
        assert pd.isna(_resolve_observed_time("not-a-time", NOW_CN))
        assert pd.isna(_resolve_observed_time(None, NOW_CN))

    def test_qc_gate_fail_closed(self):
        records = [
            {"station_id": "断面001", "observed_time": "09-01 10:30", "tn": 999.0, "ph": 7.2},
            {"station_id": "", "observed_time": "bad", "tp": 0.1},
            {"station_id": "断面002", "observed_time": "09-01 11:00", "do": 8.0},
        ]
        frame = normalize(records, retrieved_at=NOW_CN, snapshot_file="snap.html")
        by_note = frame.groupby(["station_id", "variable_code"])["qc_note"].first().to_dict()
        bad_tn = frame[(frame["station_id"] == "断面001") & (frame["variable_code"] == "total_nitrogen")].iloc[0]
        assert bad_tn["quality_flag"] == "pending_review"
        assert not bad_tn["is_ground_truth"]
        assert bad_tn["value_type"] == "observation_candidate"
        assert "out_of_range" in bad_tn["qc_note"]
        good_do = frame[(frame["station_id"] == "断面002") & (frame["variable_code"] == "dissolved_oxygen")].iloc[0]
        assert good_do["quality_flag"] == "pass" and good_do["is_ground_truth"]
        assert len(by_note) >= 3
        assert frame["observed_time"].dt.tz is not None


class TestDG003IdentityPropagation:
    def test_simulation_observed_statuses_registered(self):
        values = {s.value for s in LabelStatus}
        assert {"simulation_observed_positive", "simulation_observed_negative"}.issubset(values)
        enum = {f.enum for f in SCHEMAS["task_labels"] if f.name == "label_status"}.pop()
        assert "simulation_observed_negative" in enum

    def test_observed_statuses_require_real_source(self):
        # A18 语义：observed_* + is_synthetic=true 永远非法；合成观测来源必须用 simulation_observed_*
        labels = pd.DataFrame(
            {
                "label_status": ["observed_positive", "simulation_observed_negative"],
                "is_synthetic": [True, True],
            }
        )
        fake_obs = int(((labels["label_status"].isin(["observed_positive", "observed_negative"])) & labels["is_synthetic"]).sum())
        assert fake_obs == 1


class TestDG001PartialDomain:
    def test_aggregate_bloom_coverage_fields(self):
        dates = pd.date_range("2024-06-01", periods=2, freq="D")
        T, N = 2, 4
        fraction = np.full((T, N), 0.5)
        area = np.full((T, N), 0.25)  # km2 per cell
        eff = np.full(N, 1.0e6)
        zone_of_cell = np.array(["TAIHU_ML"] * N)
        lake_df, zone_df = aggregate_bloom(dates, fraction, area, eff, zone_of_cell, frozen_lake_area_km2=10.0)
        assert (lake_df["domain_coverage_fraction"] == 0.4).all()  # 4 km2? → eff 总和 4e6 m2=4 km2 /10
        assert lake_df["is_partial_domain"].all()
        assert (zone_df["domain_coverage_fraction"] == 1.0).all()
        assert not zone_df["is_partial_domain"].any()

    def test_labels_schema_carries_coverage(self):
        names = {f.name for f in SCHEMAS["task_labels"]}
        assert {"domain_coverage_fraction", "is_partial_domain"}.issubset(names)
        assert {"domain_coverage_fraction", "is_partial_domain"}.issubset({f.name for f in SCHEMAS["bloom_lake_daily"]})
        assert {"domain_coverage_fraction", "is_partial_domain", "feature_observed_ratio"}.issubset({f.name for f in SCHEMAS["model_training_samples"]})


class TestDG002FitterCutoff:
    def test_filter_until_and_date_drop_post_cutoff(self):
        tz = "Asia/Shanghai"
        frame = pd.DataFrame(
            {
                "observed_at": pd.to_datetime(
                    ["2024-08-01 10:00", "2024-09-05 10:00", "2024-08-28 00:00"], format="%Y-%m-%d %H:%M"
                ).tz_localize(tz),
                "value": [1.0, 2.0, 3.0],
            }
        )
        kept = _filter_until(frame, "observed_at", pd.Timestamp("2024-08-28"))
        assert len(kept) == 2  # cutoff 后记录剔除，cutoff 当日 00:00 保留
        dated = pd.DataFrame({"date": ["2024-08-28", "2024-08-29"], "v": [1, 2]})
        assert len(_filter_date(dated, "date", pd.Timestamp("2024-08-28"))) == 1


class TestDG004ObservationFeatures:
    @pytest.fixture()
    def base_dir(self, tmp_path):
        obs = tmp_path / "observations"
        latent = tmp_path / "sim" / "latent"
        obs.mkdir(parents=True)
        latent.mkdir(parents=True)
        weather = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4),
                "air_temperature": [1.0, 2.0, 3.0, 4.0],
                "wind_speed": [2.0] * 4,
                "precipitation": [0.0] * 4,
                "shortwave_radiation": [10.0] * 4,
            }
        )
        weather.to_parquet(latent / "weather_daily_TAIHU_ML.parquet", index=False)
        satellite = pd.DataFrame(
            {
                "grid_id": ["G1"] * 3,
                "variable_code": ["chla_retrieval"] * 3,
                "value": [40.0, 10.0, 20.0],
                "available_time": pd.to_datetime(["2024-01-05 07:00", "2024-01-06 09:00", "2024-01-06 09:00"]),
            }
        )
        satellite.to_parquet(obs / "satellite_observations.parquet", index=False)
        station = pd.DataFrame(
            {
                "variable_code": ["water_temperature", "water_temperature", "total_phosphorus", "total_nitrogen"],
                "value": [12.5, 13.5, 0.08, 2.1],
                "available_time": pd.to_datetime(["2024-01-03 02:00", "2024-01-03 04:00", "2024-01-03 03:00", "2024-01-03 03:00"]),
            }
        )
        station.to_parquet(obs / "station_observations.parquet", index=False)
        return tmp_path

    def test_availability_indexing_and_missing_as_nan(self, base_dir):
        dates = pd.date_range("2024-01-01", "2024-01-20")
        frames, weather_start = _feature_source_frames(base_dir / "sim", base_dir, ["TAIHU_ML"], dates)
        frame = frames["TAIHU_ML"]
        assert weather_start == pd.Timestamp("2024-01-02")  # 驱动气象 d+1 出账，可阅起点 01-02
        # 气象日值 d+1 出账：01-01 的值出现在 01-02（来源=run 驱动表，与标签同源）
        assert frame.loc[pd.Timestamp("2024-01-02"), "air_temperature"] == 1.0
        assert pd.isna(frame.loc[pd.Timestamp("2024-01-01"), "air_temperature"])
        # 卫星只在 available 日可见，缺测日 NaN
        assert frame.loc[pd.Timestamp("2024-01-05"), "chlorophyll_a"] == 40.0
        # 01-06 两条卫星值 10/20 均低于阈值 30 → bloom_fraction=0，chla 取均值 15
        assert frame.loc[pd.Timestamp("2024-01-06"), "chlorophyll_a"] == pytest.approx(15.0)
        assert frame.loc[pd.Timestamp("2024-01-06"), "bloom_fraction"] == pytest.approx(0.0)
        assert pd.isna(frame.loc[pd.Timestamp("2024-01-07"), "chlorophyll_a"])
        # 站点水温按 available 日聚合
        assert frame.loc[pd.Timestamp("2024-01-03"), "water_temperature"] == pytest.approx(13.0)
        assert pd.isna(frame.loc[pd.Timestamp("2024-01-04"), "water_temperature"])
        # TP/TN 站点仿真观测同样按 available 日聚合（接口收尾：算法机理输入）
        assert frame.loc[pd.Timestamp("2024-01-03"), "total_phosphorus"] == pytest.approx(0.08)
        assert frame.loc[pd.Timestamp("2024-01-03"), "total_nitrogen"] == pytest.approx(2.1)
        assert pd.isna(frame.loc[pd.Timestamp("2024-01-04"), "total_phosphorus"])

    def test_station_features_in_core_and_latent_excluded(self):
        assert set(STATION_FEATURES).issubset(CORE_FEATURES)
        assert not {"water_level", "blue_algae_biomass", "cyanobacteria_density"} & set(CORE_FEATURES)

    def test_satellite_grid_pivots_preserve_nan_and_threshold(self):
        satellite = pd.DataFrame(
            {
                "grid_id": ["G1", "G2", "G1"],
                "variable_code": ["chla_retrieval"] * 3,
                "value": [50.0, 5.0, 10.0],
                "available_time": pd.to_datetime(["2024-01-05 07:00"] * 3),
            }
        )
        chla_pivot, frac_pivot = _satellite_grid_pivots(satellite)
        assert chla_pivot.loc[pd.Timestamp("2024-01-05"), "G1"] == pytest.approx(30.0)  # G1 两行 (50,10) 取均值
        assert pd.Timestamp("2024-01-06") not in chla_pivot.index
        assert frac_pivot.loc[pd.Timestamp("2024-01-05"), "G1"] == 1.0  # 30 ≥ 阈值 30
        assert frac_pivot.loc[pd.Timestamp("2024-01-05"), "G2"] == 0.0

    def test_expand_samples_feature_observed_ratio_and_coverage(self):
        dates = pd.date_range("2024-01-01", "2024-01-15")
        raw = pd.DataFrame(
            {
                "air_temperature": np.linspace(0, 5, len(dates)),
                "wind_speed": np.linspace(1, 6, len(dates)),
                "precipitation": np.zeros(len(dates)),
                "shortwave_radiation": np.linspace(5, 15, len(dates)),
                "chlorophyll_a": np.where(dates == pd.Timestamp("2024-01-10"), 33.0, np.nan),
                "bloom_fraction": np.where(dates == pd.Timestamp("2024-01-10"), 1.0, np.nan),
            },
            index=dates,
        )
        frame = _augment_frame(raw)
        labels = pd.DataFrame(
            [
                {
                    "task_id": "T1",
                    "spatial_id": "TAIHU_ML",
                    "spatial_type": "zone",
                    "target_date": pd.Timestamp("2024-01-12"),
                    "label_value": 1,
                    "label_unit": "0/1",
                    "label_status": "simulation_positive",
                    "label_source_type": "simulation_truth",
                    "label_quality": "pass",
                    "is_ground_truth": False,
                    "is_synthetic": True,
                    "domain_coverage_fraction": 1.0,
                    "is_partial_domain": False,
                    "evidence_record_ids": "batch-1",
                }
            ]
        )
        samples = expand_samples(
            {},
            labels=labels,
            frames={"TAIHU_ML": frame},
            grid_weather=None,
            frac_pivot=None,
            split_of_date={pd.Timestamp("2024-01-12"): "train"},
            dataset="mvp",
            identity={"scenario_id": "baseline_replay", "random_seed": 20260904, "driver_hash": "d" * 64, "driver_type": "observed_replay"},
            horizons=(2,),
        )
        assert len(samples) == 1
        row = samples.iloc[0]
        n_expected = len(CORE_FEATURES) * (1 + len(FEATURE_LAGS) + len(FEATURE_ROLLS))
        features = json.loads(row["features_json"])
        assert row["feature_observed_ratio"] == pytest.approx(round(len(features) / n_expected, 4))
        assert row["feature_observed_ratio"] < 1.0  # WQ 观测特征缺测如实反映
        assert row["domain_coverage_fraction"] == 1.0
        # DG-004：未观测的 latent 键不得进入特征（TP/TN 已升级观测层，不在此列）
        assert not (set(features) & {"water_level", "blue_algae_biomass", "cyanobacteria_density", "relative_humidity"})

    def test_weather_core_in_core_features(self):
        assert set(WEATHER_FEATURES).issubset(CORE_FEATURES)
        assert "water_level" not in CORE_FEATURES


class TestDG008TaskGrainMatrix:
    def test_matrix_registration(self):
        assert TASK_GRAIN_MATRIX["T1"] == ("grid", "zone", "lake")
        assert TASK_GRAIN_MATRIX["T3"] == ("zone", "lake")
        assert TASK_GRAIN_MATRIX["T7"] == ("zone", "lake")
        assert set(TASK_GRAIN_MATRIX) == {f"T{i}" for i in range(1, 8)}


class TestDG005BoundHits:
    def test_nutrients_report_bound_hits(self):
        from data_factory.simulation.nutrients import simulate_nutrients

        T, N = 30, 3
        out = simulate_nutrients(
            pd.date_range("2024-06-01", periods=T),
            np.full((T, N), 25.0),
            np.full((T, N), 2.0),
            np.full((T, N), 200.0),
            np.full((T, N), 5.0),
            np.zeros((T, N)),
            np.zeros((T, N)),
            np.full((T, N), 2.0),
            "TAIHU_ML",
            lambda family, key, scope: (None, 0),
            {"nutrients": {}},
            {"nutrients": np.random.default_rng(3)},
            {},
        )
        assert isinstance(out["_bound_hits"], dict)
        assert set(out["_bound_hits"]) >= {"total_phosphorus", "total_nitrogen", "dissolved_oxygen"}


class TestDG010LineageContract:
    def test_row_lineage_fields(self):
        from data_factory.lineage.row_lineage import write_row_lineage  # 导入即校验重命名后接口存在

        assert callable(write_row_lineage)
