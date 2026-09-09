"""V0.3 特征契约 v2 与监督表时间冻结划分。"""
from __future__ import annotations

import pandas as pd

from backend.app.algorithm_models import V3_PACKAGE_DIR
from backend.model_runtime_v0_3.code.modeling_real.contracts_real import (  # noqa: I001
    BLOOM_THRESHOLD_UG_L,
    FEATURE_COLUMNS_V2,
    FeatureContractV2,
    HORIZON_MAP_V3,
    HORIZON_MONTH_MAP_V3,
    SCENARIO_HORIZONS_V3,
    SPLIT_BOUNDS,
    TASK_SPECS_REAL,
    feature_contract_sha256,
    split_of_month,
)


def test_feature_contract_v2_has_78_fields_and_p0_1_columns():
    assert len(FEATURE_COLUMNS_V2) == 78
    assert len(set(FEATURE_COLUMNS_V2)) == 78
    # P0-1 达标点：氨氮与光照入契约
    assert "wq_nh4_n" in FEATURE_COLUMNS_V2
    assert "met_shortwave_radiation_wm2" in FEATURE_COLUMNS_V2


def test_feature_contract_sha256_is_stable():
    contract = FeatureContractV2()
    assert contract.version == "v2.0"
    assert contract.n_features == 78
    assert contract.sha256 == feature_contract_sha256()


def test_horizon_month_map_and_scenario_lock():
    assert HORIZON_MONTH_MAP_V3 == {1: 0, 3: 0, 7: 0, 15: 0, 30: 1, 60: 2, 90: 3}
    for horizon in (1, 3, 7, 15):
        assert HORIZON_MAP_V3.month_offset(horizon) == 0
    for horizon in (30, 60, 90):
        assert HORIZON_MAP_V3.month_offset(horizon) == horizon // 30
    assert SCENARIO_HORIZONS_V3 == (30, 60, 90)
    # 时效→月偏移粒度与 manifest 一致性在 API 测试中复核
    assert set(HORIZON_MAP_V3.month_map) == set(HORIZON_MONTH_MAP_V3)


def test_split_of_month_time_frozen_bounds():
    assert split_of_month("2005-02") == "train"
    assert split_of_month(SPLIT_BOUNDS["train_max"]) == "train"
    assert split_of_month("2022-01") == "validation"
    assert split_of_month(SPLIT_BOUNDS["validation_max"]) == "validation"
    assert split_of_month("2024-01") == "test"
    assert split_of_month("2026-08") == "test"


def test_supervised_base_split_frozen_matches_month_bounds():
    frame = pd.read_parquet(V3_PACKAGE_DIR / "supervised" / "features_base.parquet")
    assert len(frame) > 0
    for month, group in frame.groupby("month"):
        expected = split_of_month(str(month))
        assert (group["dataset_split_frozen"] == expected).all(), f"{month} 划分泄漏"


def test_proxy_labels_never_claim_ground_truth():
    provenance = {(spec.task_id, spec.variant): spec.label_provenance for spec in TASK_SPECS_REAL}
    assert provenance[("T1", "bloom")] == "proxy_derived"
    assert provenance[("T6", "probability")] == "proxy_derived"
    assert provenance[("T5", "chla")] == "ground_truth"
    # 第二轮：T4 直接以 wq_phyto_biomass 作目标（ground_truth）；T2/T3 代理目标
    assert provenance[("T4", "biomass")] == "ground_truth"
    assert provenance[("T3", "density")] == "proxy_derived"
    assert provenance[("T2", "coverage")] == "proxy_derived"
    assert BLOOM_THRESHOLD_UG_L == 20.0


def test_task_level_feature_exclusions_prevent_same_month_leakage():
    from backend.model_runtime_v0_3.code.modeling_real.contracts_real import (  # noqa: I001
        FCB_BLOOM_PROB_THRESHOLD,
        FCB_PROB_SCALE_FACTOR,
        feature_columns_for_task,
    )
    # 目标同源特征必须从当月特征中剔除（滞后/滚动列保留）
    assert "wq_phyto_biomass" not in feature_columns_for_task("biomass")
    assert "wq_phyto_biomass" not in feature_columns_for_task("density")
    assert "rs_clms_lwq_300m_10daily_fcb_prob" not in feature_columns_for_task("coverage")
    assert "wq_phyto_biomass" in feature_columns_for_task("chla")
    assert len(feature_columns_for_task("chla")) == 78
    assert FCB_BLOOM_PROB_THRESHOLD == 0.5
    assert FCB_PROB_SCALE_FACTOR == 10000.0
