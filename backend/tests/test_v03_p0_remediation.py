"""2026-09-11 复审整改的可核对契约：标签来源 / 区间验收 / 中长期路由 / 模型身份。

这四条对应当前复审列出的三个新问题与两个 P0：
  * T5 叶绿素标签被错误标成 ground_truth；
  * 不确定性"已验证"判定不成立（覆盖率未记录 / 未达标却仍 decision_usable）；
  * 中长期 T+30/60 用了只有 5 条测试样本的持久性模型；
  * run_id 不含时效，接口按 run_id 拼出的文件名在磁盘上不存在。
测试只读交付包与运行层输出，不做任何拟合。
"""
from __future__ import annotations

import json

import pytest

from backend.app import services as services_module
from backend.app.algorithm_models import (
    CALIBRATION_UNDERCOVERED,
    COVERAGE_ACCEPTANCE_MIN,
    MIN_CALIBRATION_TEST_N,
    V3_PACKAGE_DIR,
    AlgorithmModelServiceV3,
)


class FakeRealtime:
    """最小实时输入：全湖均值来自 MEE 快照口径，站点查询返回 None（只测全湖实体）。"""

    def summary(self):
        return {
            "latest_snapshot_id": "p0-remediation-test",
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
def v3(monkeypatch):
    service = services_module.service.algorithm_v3
    monkeypatch.setattr(service, "realtime", FakeRealtime())
    return service


# ---------------------------------------------------------------- 标签来源（P0-1）


def test_t5_provenance_is_rowwise_not_declared():
    """T5 的 T+90 标签全部来自代理，落盘来源必须是代理名而不是 ground_truth。"""
    manifest = json.loads((V3_PACKAGE_DIR / "manifest.json").read_text(encoding="utf-8"))
    entries = {
        (entry["task_id"], entry["variant"], entry["horizon_days"]): entry
        for entry in manifest["availability_matrix"]
    }
    t90 = entries[("T5", "chla", 90)]
    assert t90["label_provenance"] == "chla_station_proxy_v1"
    assert t90["label_provenance"] != "ground_truth"
    assert t90["label_provenance_breakdown"] == {"chla_station_proxy_v1": 567}


def test_risk_level_inherits_chla_provenance(v3):
    """风险等级由叶绿素推导，必须继承叶绿素的代理来源，不得标成实测。"""
    suite = v3.predict_suite(30, "lake", "risk", explain=False)
    risk_level = suite["results"]["risk_level"]
    chla = suite["results"]["chla"]
    assert risk_level.get("label_provenance") == chla.get("label_provenance")
    assert "proxy" in str(risk_level.get("label_provenance"))
    assert risk_level.get("derived_is_proxy") is True


# ------------------------------------------------- 不确定性验收线（P0-2）


def test_undercovered_intervals_are_never_decision_usable():
    """实测覆盖率低于验收线的区间一律不得标为"决策可用"。"""
    service = AlgorithmModelServiceV3(realtime_provider=None)
    payload = service.calibration_coverage()
    undercovered = [
        item for item in payload["items"]
        if item["calibration_status"] == CALIBRATION_UNDERCOVERED
    ]
    assert undercovered, "当前交付包应存在欠覆盖区间（T5 T+1=80.30%、T+90=85.47%）"
    for item in undercovered:
        assert item["decision_usable"] is False
        assert float(item["empirical_coverage"]) < COVERAGE_ACCEPTANCE_MIN
        assert item["coverage_gap"] < 0
    assert payload["summary"]["undercovered"] == len(undercovered)
    # 交付包里的 T5 短时效（80.30%）与 T+90（85.47%）必须落在欠覆盖集合内
    t5_short = [
        item for item in undercovered
        if item["task_id"] == "T5" and item["horizon_days"] == 1
    ]
    t5_90 = [
        item for item in undercovered
        if item["task_id"] == "T5" and item["horizon_days"] == 90
    ]
    assert t5_short and t5_90


def test_seasonal_climatology_interval_reports_real_coverage(v3):
    """季节基线的区间必须带留出段真实核算的覆盖率，且验收结论与覆盖率一致。"""
    suite = v3.predict_suite(30, "lake", "chla", explain=False)
    chla = suite["results"]["chla"]
    assert chla["value_origin"] == "seasonal_climatology_baseline"
    uncertainty = chla["uncertainty"]
    assert uncertainty["empirical_coverage"] is not None
    assert uncertainty["coverage_n"] and uncertainty["coverage_n"] > 0
    assert uncertainty["coverage_acceptance_min"] == COVERAGE_ACCEPTANCE_MIN
    if uncertainty["calibration_status"] == CALIBRATION_UNDERCOVERED:
        assert uncertainty["decision_usable"] is False
        assert uncertainty["decision_reason"]


def test_climatology_artifact_carries_coverage_fields():
    payload = json.loads(
        (V3_PACKAGE_DIR / "evaluation" / "seasonal_climatology.json").read_text(encoding="utf-8")
    )
    assert payload["artifact_version"] == "seasonal_climatology_v2"
    assert payload["coverage_acceptance_min"] == COVERAGE_ACCEPTANCE_MIN
    for task in payload["tasks"]:
        backtest = task["backtest"]
        assert "empirical_coverage" in backtest
        assert "coverage_n" in backtest
        if task["problem_type"] != "ordinal" and backtest.get("n"):
            assert backtest["empirical_coverage"] is not None


# ------------------------------------------------- 中长期路由（P1）


def test_t30_t60_reject_under_evidenced_persistence_model(v3):
    """T+30/T+60 的持久性模型只有 5 条留出样本，不得作为交付口径。"""
    for horizon in (30, 60):
        suite = v3.predict_suite(horizon, "lake", "risk", explain=False)
        probability = suite["results"]["probability"]
        route = probability.get("long_term_route") or {}
        assert route.get("model_rejected") is True, (horizon, route)
        assert "insufficient" in str(route.get("reason"))
        assert probability["value_origin"] == "seasonal_climatology_baseline"
        assert probability["selected_family"] == "seasonal_climatology"
        assert probability["station_resolution"] is False
        # 被否决的模型不得再对外声称是这一档的来源
        assert probability.get("model_file") is None
        assert probability.get("artifact_id") is None


def test_t90_keeps_per_station_model_with_holdout_evidence(v3):
    """T+90 有评估充分的逐站模型，路由必须保留它，并如实给出留出指标。"""
    suite = v3.predict_suite(90, "lake", "risk", explain=False)
    probability = suite["results"]["probability"]
    assert probability["value_origin"] == "v0_3_real_bundle"
    assert probability["artifact_id"]
    assert probability["model_file"]
    assert probability["model_sha256"]
    quality = (suite.get("model_quality") or {}).get(probability["model_run_id"]) or {}
    metrics = quality.get("test_metrics") or {}
    assert (metrics.get("n") or 0) >= MIN_CALIBRATION_TEST_N


def test_route_policy_is_disclosed(v3):
    suite = v3.predict_suite(30, "lake", "risk", explain=False)
    route = suite["results"]["probability"]["long_term_route"]
    assert "评估充分" in route["policy"]
    assert "季节气候态基线" in route["policy"]
    assert route["evidence"]["test_n"] < MIN_CALIBRATION_TEST_N


# ------------------------------------------------- 模型身份（P1）


def test_model_artifact_audit_is_pass():
    service = AlgorithmModelServiceV3(realtime_provider=None)
    audit = service.model_artifact_audit()
    assert audit["checked"] > 0
    assert audit["artifact_id_unique"] is True, audit["duplicated_artifact_ids"]
    assert audit["missing_files"] == []
    assert audit["sha256_mismatch"] == []
    assert audit["status"] == "PASS"


def test_api_results_return_manifest_file_and_sha_not_constructed_name(v3):
    """接口返回的模型文件必须真实存在且 SHA256 一致；不得再按 run_id 拼名字。

    复审中的具体复现：接口曾返回 "T5-chla-0m-s20260907-cv-1d.joblib"，
    而磁盘上只有 "T5-chla-0m-s20260907-1d.joblib"（补训协议标记进了 run_id 却不进文件名）。
    """
    import hashlib

    suite = v3.predict_suite(1, "lake", "chla", explain=False)
    chla = suite["results"]["chla"]
    run_id = chla["model_run_id"]
    assert run_id.endswith("-cv"), "该断言针对补训协议 run_id（含协议标记但不进文件名）"
    relative = chla["model_file_path"]
    assert relative, "结果必须带清单里的真实相对路径"
    path = (V3_PACKAGE_DIR / relative).resolve()
    assert path.is_file(), f"接口声明的模型文件不存在: {relative}"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == chla["model_sha256"]
    # 旧缺陷路径：run_id 拼出来的名字在磁盘上必须不存在
    constructed = f"{run_id}-{1}d.joblib"
    assert not (V3_PACKAGE_DIR / "models" / constructed).is_file()
    assert chla["model_file"] != constructed


def test_artifact_id_encodes_task_protocol_offset_horizon_seed():
    service = AlgorithmModelServiceV3(realtime_provider=None)
    manifest = service._manifest()
    for entry in manifest["models"]:
        artifact_id = entry["artifact_id"]
        assert entry["task_id"] in artifact_id
        assert entry["variant"] in artifact_id
        assert entry["protocol"] in artifact_id
        assert f"off{entry['month_offset']}" in artifact_id
        assert f"h{entry['horizon_days']}" in artifact_id
        assert f"s{entry['seed']}" in artifact_id
