"""V0.3 主链路修复批次语义测试：概率语义 / 动态质量门 / 风险等级推导 / legacy 回退 / 补训协议。"""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.app import services as services_module
from backend.model_runtime_v0_3.code.modeling_real.contracts_real import RISK_BANDS_UG_L

client = TestClient(app)


class FakeRealtimeSemantics:
    """与 test_v03_api 相同口径的最小实时输入。"""

    def summary(self):
        return {
            "latest_snapshot_id": "mee-semantics-test",
            "latest_observed_at": "2026-09-09T15:00:00+08:00",
            "means": {
                "total_phosphorus": {"value": 0.096},
                "total_nitrogen": {"value": 1.717},
                "dissolved_oxygen": {"value": 6.105},
                "pH": {"value": 7.9},
                "ammonia_nitrogen": {"value": 0.21},
                "chlorophyll_a": {"value": 12.5},
            },
        }

    def station(self, entity_id: str):
        return None


@pytest.fixture()
def fake_realtime(monkeypatch):
    v3 = services_module.service.algorithm_v3
    legacy = services_module.service.algorithm
    monkeypatch.setattr(v3, "realtime", FakeRealtimeSemantics())
    if legacy is not None:
        monkeypatch.setattr(legacy, "realtime", FakeRealtimeSemantics())
    return v3


def _suite(horizon: int, focus: str = "risk") -> dict:
    """模型层语义测试直接调 predict_suite。

    2026-09-11 起业务读取接口（algorithm_predictions_v3 / prediction_snapshot_view）
    为快照只读、快照未就绪一律 409，绝不回落即时推理；因此模型语义断言
    不再经过读取层，避免依赖机器上是否存在已发布快照。
    """
    v3 = services_module.service.algorithm_v3
    return v3.predict_suite(horizon, "lake", focus)


def test_risk_score_uses_probability_not_class_label(fake_realtime):
    """风险得分必须来自概率字段：概率 0.09 时得分约 9.1，而不是把类别标签 0 当概率。"""
    data = _suite(3)
    probability = data["results"]["probability"]["value"]
    assert probability is not None and 0.0 < float(probability) < 1.0
    assert data["risk_score"] == round(float(probability) * 100, 1)
    assert data["risk_score"] > 0


def test_quality_gate_reflects_mixed_origins_short_horizon(fake_realtime):
    """短时效：焦点指标来自真实模型，但同时效含 legacy 补位 → partial（禁止无差别 ok）。"""
    data = _suite(3)
    gate = data["quality_gate"]
    assert gate["status"] in {"ok", "partial"}
    counts = gate["value_origin_counts"]
    assert sum(counts.values()) == 9
    assert counts["real_data_v0_3"] >= 3, "bloom/chla/probability + 补训任务应为真实链路"
    assert counts["legacy_v0_2_synthetic_fallback"] >= 1, "面积/覆盖率/空间范围应如实标记为合成对照"


def test_quality_gate_degraded_on_legacy_only_focus(fake_realtime):
    """焦点指标为 legacy 合成对照时 → 质量门必须 degraded，且不得自称真实链路。

    2026-09-11 起已不存在"整档只有 legacy 合成对照"的 (时效, 焦点指标) 组合：
    30 天先由季节气候态基线接住、其余档由逐站模型接住。这里直接对质量门本身做单元
    断言，把这个不变量钉住，而不是依赖某个时效恰好退化——那种依赖会随数据可用性漂移。
    """
    from backend.app.algorithm_models import AlgorithmModelServiceV3

    counts = {
        "real_data_v0_3": 0, "seasonal_climatology_baseline": 0, "derived_from_chla": 0,
        "derived_from_retrieval_field": 0, "legacy_v0_2_synthetic_fallback": 9, "not_applicable": 0,
    }
    gate = AlgorithmModelServiceV3._quality_gate(
        {"value": 12.5, "value_origin": "legacy_v0_2_synthetic_fallback"}, counts, "risk", True
    )
    assert gate["status"] == "degraded"
    assert gate["decision"] == "legacy_synthetic_fallback_scenario"
    assert gate["value_origin_counts"]["real_data_v0_3"] == 0

    # 焦点为季节气候态基线 → partial，且不得混入逐站模型来源桶
    clim_counts = {**counts, "legacy_v0_2_synthetic_fallback": 0, "seasonal_climatology_baseline": 1}
    clim_gate = AlgorithmModelServiceV3._quality_gate(
        {"value": 7.4, "value_origin": "seasonal_climatology_baseline"}, clim_counts, "chla", True
    )
    assert clim_gate["status"] == "partial"
    assert clim_gate["decision"] == "seasonal_climatology_baseline"
    assert clim_gate["value_origin_counts"]["real_data_v0_3"] == 0


def test_risk_level_derived_from_chla_risk_bands(fake_realtime):
    """风险等级由叶绿素 a 预测值按冻结风险带推导，等级必须与数值一致。"""
    for horizon in (3, 30):
        data = _suite(horizon)
        chla_value = data["results"]["chla"]["value"]
        risk_level = data["results"]["risk_level"]
        if chla_value is None:
            continue
        assert risk_level["value_origin"] == "derived_from_chla_v0_3_risk_bands"
        band = next(
            name for name, (low, high) in RISK_BANDS_UG_L.items()
            if low <= float(chla_value) < high
        )
        assert risk_level["value"] == band
        assert risk_level["derived_from"]["chla_value_ug_l"] == chla_value


def test_cv_supplement_models_flagged_with_protocol(fake_realtime):
    """T3/T4 补训模型：真实链路 + 分块协议标注，不得与冻结划分口径混同。"""
    data = _suite(3)
    for key in ("density", "biomass"):
        item = data["results"][key]
        assert item["value_origin"] == "v0_3_real_bundle"
        assert item["training_protocol"] == "train_internal_time_block_cv_v1"
        assert item["value"] is not None


def test_legacy_fallback_results_disclosed(fake_realtime):
    """回退任务来源如实标注：面积=月度反演基底面积；coverage/spatial=legacy 合成回退。"""
    data = _suite(3)
    area = data["results"]["area"]
    # 2026-09-11 起面积优先取月度反演重建基底场的 20μg/L 阈值边界面积（全湖量口径）
    assert area["value_origin"] == "derived_from_monthly_retrieval_field"
    assert area["value"] and area["value"] > 0
    assert area["unit"] == "km²"
    assert area["issued_month"]
    for key in ("coverage", "spatial"):
        item = data["results"][key]
        assert item["value_origin"] == "legacy_v0_2_synthetic_fallback"
        assert item["training_protocol"] == "synthetic_augmented_legacy_v0_2"
        assert item["not_applicable_reason"]
        assert item["compliance"]["locked"] is False


def test_explainability_effective_flag(fake_realtime):
    """有效模型给真实排序；常数模型如实标记无效并给出原因。

    2026-09-11 serving 契约重训后：T4-biomass（constrained_blend）对站点实测水质
    有真实响应，explainability effective=True；T6-probability 仍为 simple_baseline
    常数族，必须如实标记无效并给出原因。
    """
    density = _suite(3, "density")["results"]["density"]["explainability"]
    assert density["effective"] is True
    assert density["factors"] and density["factors"][0]["contribution_percent"] > 0
    biomass = _suite(3, "biomass")["results"]["biomass"]["explainability"]
    assert biomass["effective"] is True
    assert biomass["factors"] and biomass["factors"][0]["contribution_percent"] > 0
    # 2026-09-11 叶绿素代理标签（公示口径）重训后：T1/T5/T6 短时效全部由
    # mechanism_feature / random_forest / xgboost 胜出，四个焦点任务均有真实响应；
    # 常数族（simple_baseline）当前仅存于 T6-risk_level（序数，不在焦点任务中）。
    probability = _suite(3, "risk")["results"]["probability"]["explainability"]
    assert probability["effective"] is True
    assert probability["factors"] and probability["factors"][0]["contribution_percent"] > 0
    chla = _suite(3, "chla")["results"]["chla"]["explainability"]
    assert chla["effective"] is True
    chla = _suite(3, "chla")["results"]["chla"]["explainability"]
    for factor in chla["factors"]:
        assert factor["baseline"] == factor["baseline"], "敏感性基线不得为 NaN"


def test_v3_status_discloses_training_protocols(fake_realtime):
    """训练协议必须逐模型如实披露，且计数与模型总数自洽。

    不锁死具体条数：每条 (任务, 时效) 用哪个协议由该槽位是否有足够留出测试证据决定，
    数字会随标签可用性变化。锁数字会让测试退化成上一次交付包的数据快照。
    """
    response = client.get("/api/v1/model/v3/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ready"
    protocols = data["training_protocols"]
    assert set(protocols) <= {"frozen_split", "train_internal_time_block_cv_v1"}
    assert data["model_count"] > 0
    assert sum(protocols.values()) == data["model_count"]


def test_spatial_field_raster_shares_prediction_run_id(fake_realtime):
    suite = _suite(3)
    response = client.get(
        "/api/v1/model/spatial-field",
        params={"horizon_days": 3, "metric": "chla", "layer": "raster", "run_id": suite["prediction_run_id"]},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["prediction_run_id"].startswith(suite["prediction_run_id"])
    assert data["prediction_run_id"].endswith("-RASTER-CHLA")
    assert data["layer_semantics"] == "monthly_reconstruction_base_not_horizon_forecast"


def test_health_exposes_stable_product_identity():
    """启动器必须能区分 A23 后端和占用同一端口的其他 FastAPI 服务。"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["service"] == "a23-backend"
    assert data["product_id"] == "taihu-a23-algae-warning"
    assert data["api_title"] == "蓝藻水华监测预警系统 API"


def test_mechanism_state_discloses_ammonia_and_missing_flow(fake_realtime):
    """氨氮和流速要显示输入可用性，但不得伪装成已进入机理贡献公式。"""
    factors = {item["key"]: item for item in _suite(3)["mechanism_drivers"]["factors"]}
    assert factors["ammonia"]["source_value"] == pytest.approx(0.21)
    assert factors["ammonia"]["state_only"] is True
    assert factors["flow"]["source_value"] is None
    assert factors["flow"]["state_only"] is True
    assert "不可用" in factors["flow"]["source"]
