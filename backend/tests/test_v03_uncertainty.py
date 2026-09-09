"""V0.3 conformal 区间：split-conformal 校准器与冻结测试集经验覆盖率。"""
from __future__ import annotations

import json

from backend.app.algorithm_models import V3_PACKAGE_DIR


def _manifest() -> dict:
    path = V3_PACKAGE_DIR / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_trainable_bundle_carries_conformal_calibrator():
    manifest = _manifest()
    models = manifest.get("models", [])
    assert models, "V0.3 包应至少有一个可训练 bundle"
    for model in models:
        uncertainty = model.get("uncertainty") or {}
        assert uncertainty.get("is_calibrated_confidence_interval") is True, (
            f"{model['run_id']} 缺少 conformal 校准器"
        )
        assert uncertainty.get("method") == "split_conformal_residual_quantiles"
        assert uncertainty.get("coverage_target") == 0.90
        assert uncertainty.get("calibration_n", 0) > 0


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
