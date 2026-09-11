"""季节气候态 v3 三段时序回测的去泄漏合同（2026-09-12 复审整改）。

v2 缺陷：残差分位数与经验覆盖率在同一段（末尾 20% 目标月）上核算——分位数由这批
残差构造、覆盖率再在同批记录上回算，~90% 覆盖是分位数构造的必然结果，不是独立验证。
v3 合同：拟合(60%)/区间校准(20%)/独立测试(20%)三段互不重叠；分位数只来自校准段，
覆盖率只来自测试段。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.algorithm_models import SEASONAL_CLIMATOLOGY_VERSION, V3_PACKAGE_DIR

CODE_DIR = Path(__file__).resolve().parents[1] / "model_runtime_v0_3" / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from modeling_real.seasonal_climatology import (  # noqa: E402
    ARTIFACT_VERSION,
    MIN_SEGMENT_MONTHS,
    _three_segment_backtest,
    build_seasonal_climatology,
    split_month_segments,
)
from modeling_real.contracts_real import TASK_SPECS_REAL  # noqa: E402


def _spec(task_id: str, variant: str):
    return next(s for s in TASK_SPECS_REAL if s.task_id == task_id and s.variant == variant)


def test_version_constants_stay_aligned():
    """生成器与运行层的产物版本常量必须一致，否则运行层按"版本不符=不可用"拒读。"""
    assert ARTIFACT_VERSION == SEASONAL_CLIMATOLOGY_VERSION == "seasonal_climatology_v3"


def test_split_month_segments_disjoint_ordered():
    months = [f"2020-{m:02d}" for m in range(1, 13)] + [f"2021-{m:02d}" for m in range(1, 13)]
    months += [f"2022-{m:02d}" for m in range(1, 13)] + [f"2023-{m:02d}" for m in range(1, 13)]
    fit, calib, test = split_month_segments(months)
    assert len(fit) == 28 and len(calib) == 10 and len(test) == 10
    assert not (set(fit) & set(calib)) and not (set(calib) & set(test)) and not (set(fit) & set(test))
    assert sorted(fit + calib + test) == sorted(months)
    assert max(fit) < min(calib) and max(calib) < min(test)


def test_three_segment_backtest_quantiles_and_coverage_use_disjoint_segments():
    """构造性验证去泄漏：校准段残差温和、测试段含大离群点 → 覆盖率必须 < 100%。

    v2 口径下（分位数与覆盖率同段）覆盖率会等于分位数构造的必然值；
    v3 下分位数来自校准段、覆盖率来自含离群点的测试段，两者必须独立。
    """
    spec = _spec("T5", "chla")
    fit_months = [f"2015-{m:02d}" for m in range(1, 13)] + [f"2016-{m:02d}" for m in range(1, 13)]
    calib_months = [f"2017-{m:02d}" for m in range(1, 13)]
    test_months = [f"2018-{m:02d}" for m in range(1, 13)]
    by_month = {str(int(m[5:7])): 10.0 for m in fit_months + calib_months + test_months}
    fallback = 10.0

    def _frame(months, values):
        return pd.DataFrame({
            "target_month": months,
            "actual": values,
            "actual_num": [float(v) for v in values],
        })

    calib_values = [10.0 + (0.1 * (i % 5) - 0.2) for i in range(12)]  # 残差 ∈ [-0.2, 0.2]
    test_values = [10.0, 10.1, 9.9, 10.05, 9.95, 10.0, 10.1, 20.0, 9.9, 10.0, 10.05, 9.95]  # 20.0 为离群点
    frame = pd.concat([
        _frame(calib_months, calib_values),
        _frame(test_months, test_values),
    ], ignore_index=True)

    backtest = _three_segment_backtest(
        frame, spec, "chla", is_ordinal=False,
        fit_months=fit_months, calib_months=calib_months, test_months=test_months,
        by_month=by_month, fallback=fallback,
    )

    # 段披露：校准段/测试段行数与月份互不重叠
    assert backtest["interval_calibration_n"] == 12
    assert backtest["n"] == 12
    assert backtest["interval_calibration_max_month"] < backtest["test_min_month"]
    # 分位数必须等于校准段残差分位数（与测试段无关）
    calib_residual = np.array(calib_values) - 10.0
    assert backtest["residual_quantiles"]["p05"] == float(np.quantile(calib_residual, 0.05))
    assert backtest["residual_quantiles"]["p95"] == float(np.quantile(calib_residual, 0.95))
    # 覆盖率在测试段回算：11/12 个点落在 [p05,p95] 区间内，离群点 20.0 不被覆盖
    p05 = 10.0 + backtest["residual_quantiles"]["p05"]
    p95 = 10.0 + backtest["residual_quantiles"]["p95"]
    expected = float(np.mean([(v >= p05) and (v <= p95) for v in test_values]))
    assert backtest["empirical_coverage"] == expected
    assert backtest["empirical_coverage"] < 1.0, "离群点必须拉低独立覆盖率，否则仍是共段构造"
    assert backtest["coverage_n"] == 12


def test_segments_too_short_fail_the_backtest_gate():
    """月份不足以三段回测时必须过不了回测门槛（产物按"无区间证据"降级，不出覆盖率）。"""
    few = [f"2025-{m:02d}" for m in range(1, 5)]  # 仅 4 个月
    fit, calib, test = split_month_segments(few)
    gate = (
        len(few) >= 6
        and len(calib) >= MIN_SEGMENT_MONTHS
        and len(test) >= MIN_SEGMENT_MONTHS
    )
    assert gate is False
    # 边界：30 个月 → 18/6/6，各段恰好达标，门槛放行
    _, c30, t30 = split_month_segments(
        [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 13)]
        + [f"2026-{m:02d}" for m in range(1, 7)]
    )
    assert (len(c30), len(t30)) == (6, 6)
    gate_ok = len(c30) >= MIN_SEGMENT_MONTHS and len(t30) >= MIN_SEGMENT_MONTHS
    assert gate_ok is True


def test_regenerated_artifact_is_v3_with_disjoint_segments():
    """再生成的产物必须是 v3：分位数段与覆盖率段互不重叠、覆盖率有记录。"""
    artifact = json.loads(
        (V3_PACKAGE_DIR / "evaluation" / "seasonal_climatology.json").read_text(encoding="utf-8")
    )
    assert artifact["artifact_version"] == "seasonal_climatology_v3"
    tasks = {f"{t['task_id']}/{t['variant']}": t for t in artifact["tasks"]}
    assert set(tasks) == {"T1/bloom", "T3/density", "T4/biomass", "T5/chla", "T6/probability"}
    for name, blk in tasks.items():
        bt = blk.get("backtest") or {}
        if not bt.get("residual_quantiles"):
            continue
        assert bt.get("protocol") == "time_block_three_segment_v1", name
        assert bt["interval_calibration_max_month"] < bt["test_min_month"], name
        assert bt["interval_calibration_n"] > 0 and bt["coverage_n"] > 0, name
        assert bt.get("empirical_coverage") is not None, name
