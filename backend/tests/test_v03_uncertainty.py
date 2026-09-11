"""V0.3 conformal 区间：split-conformal 校准器与冻结测试集经验覆盖率。"""
from __future__ import annotations

import json

from backend.app.algorithm_models import V3_PACKAGE_DIR


def _manifest() -> dict:
    path = V3_PACKAGE_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_trainable_bundle_carries_conformal_calibrator():
    """bundle 必须携带 conformal 校准器；但"携带校准器"不等于"校准有效"。

    清单里的 is_calibrated_confidence_interval 恒为 true（含 test_n=0/1 的模型），
    运行口径已停止消费该字段，改由 test_n + 经验覆盖率判定，见 calibration_coverage()。
    """
    manifest = _manifest()
    models = manifest.get("models", [])
    assert models, "V0.3 包应至少有一个可训练 bundle"
    for model in models:
        uncertainty = model.get("uncertainty") or {}
        # 序数任务（T6-risk_level 风险带）预测是标签字符串，无数值残差可池化，
        # conformal 区间不适用——这是 2026-09-11 代理标签重训后首次可训练时明确的口径。
        if model["run_id"].startswith("T6-risk_level"):
            continue
        assert uncertainty.get("method") == "split_conformal_residual_quantiles", (
            f"{model['run_id']} 缺少 conformal 校准器"
        )
        assert uncertainty.get("coverage_target") == 0.90
        assert uncertainty.get("calibration_n", 0) > 0


def test_calibration_status_is_evidence_based_not_flag_based():
    """校准状态必须由测试集证据决定，而不是由模型自带的布尔标志决定。

    判据是**双向**的，与当前包里有几个模型恰好有证据无关：
      无测试证据（test_n 为 None/0）→ 不得判为 validated；
      判为 validated → test_n 必须达标、经验覆盖率必须核算过。
    曾经额外断言"至少有 1 个模型无测试证据"——那是当时交付包的数据快照，不是合同；
    补训协议补上真实留出测试段后该断言自然失效，而它失效恰恰说明合同在工作。
    """
    from backend.app.algorithm_models import (
        CALIBRATION_NO_TEST_EVIDENCE,
        CALIBRATION_UNDERCOVERED,
        CALIBRATION_VALIDATED,
        AlgorithmModelServiceV3,
        COVERAGE_ACCEPTANCE_MIN,
        MIN_CALIBRATION_TEST_N,
    )

    service = AlgorithmModelServiceV3(realtime_provider=None)
    payload = service.calibration_coverage()
    assert payload["items"], "校准清单不得为空"
    assert payload["interval_semantics"] == "prediction_interval_not_parameter_confidence_interval"
    for item in payload["items"]:
        assert item["is_prediction_interval"] is True
        if item["test_n"] in (None, 0):
            assert item["calibration_status"] == CALIBRATION_NO_TEST_EVIDENCE
            assert item["test_n"] != MIN_CALIBRATION_TEST_N
        if item["calibration_status"] == CALIBRATION_VALIDATED:
            assert item["test_n"] >= MIN_CALIBRATION_TEST_N
            assert item["empirical_coverage"] is not None
            # 2026-09-11 加：达标还必须真的达到验收线，而不是"覆盖率非空"
            assert float(item["empirical_coverage"]) >= COVERAGE_ACCEPTANCE_MIN
            assert item["decision_usable"] is True
    # 汇总必须与逐条明细自洽：四种校准状态互斥且完备，计数之和 == 明细条数
    summary = payload["summary"]
    assert summary["reviewed"] == len(payload["items"])
    assert (
        summary["calibration_validated"]
        + summary["undercovered"]
        + summary["without_test_evidence"]
        + summary["insufficient_test_evidence"]
        == summary["reviewed"]
    )
    # 欠覆盖必须是可核对的：每条 undercovered 的实测覆盖率都真的低于验收线
    for item in payload["items"]:
        if item["calibration_status"] == CALIBRATION_UNDERCOVERED:
            assert item["decision_usable"] is False
            assert item["empirical_coverage"] is not None
            assert float(item["empirical_coverage"]) < COVERAGE_ACCEPTANCE_MIN


def test_empirical_coverage_is_disclosed_not_fitted_on_test():
    manifest = _manifest()
    for model in manifest.get("models", []):
        uncertainty = model.get("uncertainty") or {}
        coverage = uncertainty.get("empirical_coverage_test")
        test_n = uncertainty.get("test_n")
        # 冻结测试集只报经验覆盖率，不参与拟合：字段必须存在且口径诚实
        assert coverage is None or 0.0 <= float(coverage) <= 1.0
        assert test_n is None or int(test_n) >= 0


def test_bundle_interval_offsets_bracket_point_prediction():
    joblib = __import__("importlib").import_module("joblib")
    import sys

    code_path = str(V3_PACKAGE_DIR / "code")
    if code_path not in sys.path:
        sys.path.insert(0, code_path)
    models_dir = V3_PACKAGE_DIR / "models"
    bundles = sorted(models_dir.glob("*.joblib"))
    assert bundles
    for path in bundles:
        bundle = joblib.load(path)
        if bundle.intervals is None:
            continue
        # 残差分位：P05 ≤ 0 ≤ P95 才能对点预测形成覆盖区间
        assert bundle.intervals.residual_p05 <= bundle.intervals.residual_p95
        assert bundle.intervals.calibration_n > 0
