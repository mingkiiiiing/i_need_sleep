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
    """任务配置只能声明"允许的来源"；任何含代理行的任务都不得声明为 ground_truth。

    2026-09-11 修正：T5-chla 此前声明 ground_truth，而 T+90 监督表 567 行的标签
    全部来自 chla_station_proxy_v1——声明与事实不符，还会一路传到风险等级与季节基线。
    """
    provenance = {(spec.task_id, spec.variant): spec.label_provenance for spec in TASK_SPECS_REAL}
    assert provenance[("T1", "bloom")] == "proxy_derived"
    assert provenance[("T6", "probability")] == "proxy_derived"
    # T5 的 chla 标签来自「4 个航次月实测 + chla_station_proxy_v1 代理」两个来源
    assert provenance[("T5", "chla")] == "ground_truth_or_proxy"
    assert provenance[("T5", "chla")] != "ground_truth"
    # 风险等级由叶绿素值经冻结风险带推导，来源必须继承 T5，不得单独声称实测
    assert provenance[("T6", "risk_level")] == "ground_truth_or_proxy"
    # 第二轮：T4 直接以 wq_phyto_biomass 作目标（ground_truth）；T2/T3 代理目标
    assert provenance[("T4", "biomass")] == "ground_truth"
    assert provenance[("T3", "density")] == "proxy_derived"
    assert provenance[("T2", "coverage")] == "proxy_derived"
    assert BLOOM_THRESHOLD_UG_L == 20.0


def test_manifest_provenance_is_rowwise_not_task_declaration():
    """落盘口径必须是逐行 actual_provenance 汇总，且声明与观测的对账无 mismatch。"""
    import json

    from backend.app.algorithm_models import V3_PACKAGE_DIR

    manifest = json.loads((V3_PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    by_key = {
        (entry["task_id"], entry["variant"], entry["horizon_days"]): entry
        for entry in manifest["availability_matrix"]
    }
    # 审阅结论 P0-1 的具体事实：T+90 的 567 行标签全部来自代理
    t5_90 = by_key[("T5", "chla", 90)]
    assert t5_90["label_provenance"] == "chla_station_proxy_v1"
    assert t5_90["label_provenance_breakdown"] == {"chla_station_proxy_v1": 567}
    assert t5_90["label_provenance_declared"] == "ground_truth_or_proxy"
    # 短时效两来源并存，必须如实标成 mixed，而不是塌缩成 ground_truth
    t5_1 = by_key[("T5", "chla", 1)]
    assert t5_1["label_provenance"].startswith("mixed(")
    assert t5_1["label_provenance_breakdown"]["ground_truth"] == 42
    audit = manifest.get("label_provenance_audit") or {}
    assert audit, "清单必须携带标签来源对账段"
    assert audit["mismatch_count"] == 0, audit.get("mismatches")


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
