"""P0.5 结果可信合同：响应性三态 / 不确定性三层 / 双指纹 / 快照版本键与服役闸门。

这些测试只校验"结果是否被正确表述"，不涉及模型精度，也不依赖真实 MEE 目录。
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.app.algorithm_models import (
    CALIBRATION_INSUFFICIENT_TEST_EVIDENCE,
    CALIBRATION_NO_TEST_EVIDENCE,
    CALIBRATION_VALIDATED,
    FINGERPRINT_SCHEMA,
    MIN_CALIBRATION_TEST_N,
    AlgorithmModelServiceV3,
)
from backend.app.prediction_snapshot import (
    CACHE_SCHEMA_VERSION,
    PredictionSnapshotService,
    build_version_key,
    prediction_snapshot_id,
)


# ------------------------------------------------------------------ 版本键


def _status(bundle_digest: str = "aaa", manifest_sha: str = "mmm") -> dict:
    return {
        "package_version": "0.3",
        "model_count": 20,
        "feature_contract": {"version": "v2.0", "sha256": "fc"},
        "data_version": "TAIWU/model_dataset.parquet",
        "model_artifacts": {
            "manifest_sha256": manifest_sha,
            "bundle_digest": bundle_digest,
            "bundle_hashes": {"a.joblib": "1", "b.joblib": "2"},
            "training_data_version": "TAIWU/model_dataset.parquet",
            "preprocessor": {"source_sha256": "pp", "feature_contract_version": "v2.0"},
        },
    }


def test_version_key_changes_when_model_artifact_changes():
    """同版本号下替换模型文件，快照必须换代（本轮修补的核心缺口）。"""
    base = predict_id = prediction_snapshot_id(build_version_key(_status(), "snap-1"))
    changed_bundle = prediction_snapshot_id(build_version_key(_status(bundle_digest="bbb"), "snap-1"))
    changed_manifest = prediction_snapshot_id(build_version_key(_status(manifest_sha="nnn"), "snap-1"))
    assert base != changed_bundle
    assert base != changed_manifest


def test_version_key_changes_when_preprocessor_changes():
    status = _status()
    status["model_artifacts"]["preprocessor"] = {"source_sha256": "OTHER", "feature_contract_version": "v2.0"}
    assert prediction_snapshot_id(build_version_key(status, "snap-1")) != prediction_snapshot_id(
        build_version_key(_status(), "snap-1")
    )


def test_version_key_carries_bundle_hash_set_and_schema():
    key = build_version_key(_status(), "snap-1")
    assert key["schema"] == CACHE_SCHEMA_VERSION
    assert key["bundle_hashes"] == {"a.joblib": "1", "b.joblib": "2"}
    assert key["bundle_digest"] == "aaa"
    assert key["training_data_version"] == "TAIWU/model_dataset.parquet"


# ------------------------------------------------------ 响应性三态（可比较性）


def _usability(
    value_origin,
    model_family,
    model_run_id,
    numeric_variation,
    quality,
    gate_row=None,
    gate_available=True,
):
    return PredictionSnapshotService._comparison_usability(
        value_origin, model_family, model_run_id, numeric_variation, quality,
        gate_row, gate_available,
    )


def test_synthetic_fallback_is_never_comparable_even_with_variation():
    """合成情景回退有数值差异，但只能说明情景设定不同，不得判为可用于站点比较。"""
    usable, reason, _ = _usability(
        "legacy_v0_2_synthetic_fallback", "residual", "T2-area", True, {}
    )
    assert usable is False
    assert reason == "synthetic_scenario_fallback_not_comparable"


def test_gate_fail_blocks_comparison_even_with_holdout_evidence():
    """10% 提升门禁 FAIL（未达标）时，留出证据形式达标也不得放行站点比较。"""
    quality = {"T5-chla": {"test_metrics": {"n": 40, "r2": 0.42}}}
    gate_row = {"task_id": "T5", "variant": "chla", "horizon_days": 1, "status": "FAIL", "na_reason": None}
    usable, reason, evidence = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, quality, gate_row
    )
    assert (usable, reason) == (False, "gate_10pct_uplift_fail")
    assert evidence["gate_status"] == "FAIL"


def test_gate_na_blocks_comparison():
    """门禁未可评估（N.A.）的任务/时效不得宣称可用于站点比较。"""
    gate_row = {
        "task_id": "T5", "variant": "chla", "horizon_days": 1,
        "status": "NA", "na_reason": "test_n_below_minimum_15",
    }
    usable, reason, evidence = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, {}, gate_row
    )
    assert (usable, reason) == (False, "gate_10pct_uplift_not_evaluable")
    assert evidence["gate_na_reason"] == "test_n_below_minimum_15"


def test_missing_gate_row_blocks_comparison():
    """门禁表没有该 (任务, 时效) 的评估记录时不得放行（如 T+30/60/90）。"""
    usable, reason, evidence = _usability("v0_3_real_bundle", "xgboost", "T5-chla", True, {})
    assert (usable, reason) == (False, "gate_row_missing_for_task_horizon")
    assert evidence["gate_status"] is None


def test_gate_evidence_unavailable_blocks_comparison():
    """门禁表整体缺失时收敛为"不可比较"，不得退回旧口径。"""
    usable, reason, _ = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, {}, None, gate_available=False
    )
    assert (usable, reason) == (False, "gate_evidence_unavailable")


def test_gate_pass_falls_through_to_holdout_evidence():
    """门禁 PASS 只是必要条件：仍须通过留出证据检查才可判可用。"""
    quality = {"T5-chla": {"test_metrics": {"n": 40, "r2": 0.42}}}
    gate_row = {"task_id": "T5", "variant": "chla", "horizon_days": 1, "status": "PASS", "na_reason": None}
    usable, reason, _ = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, quality, gate_row
    )
    assert usable is True
    assert reason is None
    # 门禁 PASS 但留出证据不足时仍须拦截
    usable, reason, _ = _usability("v0_3_real_bundle", "xgboost", "T5-chla", True, {}, gate_row)
    assert (usable, reason) == (False, "insufficient_holdout_evidence_for_entity_comparison")


def test_numeric_variation_alone_is_not_comparison_usable():
    """数值不同只是统计事实；门禁与留出证据都不满足时不得据此宣称可用于比较。"""
    usable, reason, evidence = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, {}, None, gate_available=False
    )
    assert usable is False
    assert reason == "gate_evidence_unavailable"
    # 门禁 PASS 但留出证据不足时，证据里必须带最小样本量口径
    gate_pass = {"task_id": "T5", "variant": "chla", "horizon_days": 1, "status": "PASS", "na_reason": None}
    _, _, evidence = _usability("v0_3_real_bundle", "xgboost", "T5-chla", True, {}, gate_pass)
    assert evidence["min_test_rows"] == MIN_CALIBRATION_TEST_N


def test_constant_output_and_static_baseline_block_comparison():
    usable, reason, _ = _usability("v0_3_real_bundle", "xgboost", "T5-chla", False, {})
    assert (usable, reason) == (False, "constant_output_across_entities")
    usable, reason, _ = _usability("v0_3_real_bundle", "simple_baseline", "T1-bloom", True, {})
    assert (usable, reason) == (False, "static_baseline_model_does_not_use_entity_inputs")


def test_discrimination_not_better_than_chance_blocks_comparison():
    quality = {"T1-bloom": {"test_metrics": {"n": 40, "roc_auc": 0.5}}}
    gate_pass = {"task_id": "T1", "variant": "bloom", "horizon_days": 1, "status": "PASS", "na_reason": None}
    usable, reason, _ = _usability(
        "v0_3_real_bundle", "xgboost", "T1-bloom", True, quality, gate_pass
    )
    assert (usable, reason) == (False, "holdout_discrimination_not_better_than_chance")


def test_comparison_usable_requires_real_evidence():
    gate_pass = {"task_id": "T5", "variant": "chla", "horizon_days": 1, "status": "PASS", "na_reason": None}
    quality = {"T5-chla": {"test_metrics": {"n": 40, "r2": 0.42}}}
    usable, reason, _ = _usability(
        "v0_3_real_bundle", "xgboost", "T5-chla", True, quality, gate_pass
    )
    assert usable is True
    assert reason is None


def test_derived_indicator_inherits_source_model_limits():
    usable, reason, _ = _usability(
        "derived_from_chla_v0_3_risk_bands", "xgboost", "T5-chla", True,
        {"T5-chla": {"test_metrics": {"n": 40, "r2": 0.9}}},
    )
    assert usable is False
    assert reason == "derived_indicator_inherits_source_model_limits"


# ------------------------------------------------------- 不确定性三层合同


def _bundle(*, residual_p05: float, residual_p95: float, calibration_n: int, test_n, coverage):
    return SimpleNamespace(
        intervals=SimpleNamespace(
            residual_p05=residual_p05, residual_p95=residual_p95, calibration_n=calibration_n
        ),
        uncertainty_meta={"test_n": test_n, "empirical_coverage_test": coverage},
    )


def test_structural_valid_alone_is_not_calibration_evidence():
    """结构自洽（点预测落在非零宽区间内）不等于校准有效。"""
    service = AlgorithmModelServiceV3(realtime_provider=None)
    # 有充分测试样本 → 校准状态 validated；区间非退化 → 结构自洽 → 决策可用
    rich = service._build_uncertainty(
        _bundle(residual_p05=-1.0, residual_p95=1.0, calibration_n=100, test_n=40, coverage=0.93),
        0.5, "chla", "frozen_split",
    )
    assert rich["is_prediction_interval"] is True
    assert rich["structural_valid"] is True
    assert rich["calibration_status"] == CALIBRATION_VALIDATED
    assert rich["decision_usable"] is True


def test_zero_width_interval_is_structurally_invalid_but_calibration_still_reported():
    """零宽退化区间必须标为结构无效，同时校准证据层照实给出，不得混为一谈。"""
    service = AlgorithmModelServiceV3(realtime_provider=None)
    degenerate = service._build_uncertainty(
        _bundle(residual_p05=0.0, residual_p95=0.0, calibration_n=31, test_n=40, coverage=0.975),
        0.0909, "probability", "frozen_split",
    )
    assert degenerate["structural_valid"] is False
    assert degenerate["interval_degenerate"] is True
    assert degenerate["invalid_reason"]
    # 校准证据层独立成立 → 但决策不可用
    assert degenerate["calibration_status"] == CALIBRATION_VALIDATED
    assert degenerate["decision_usable"] is False


def test_single_test_sample_never_counts_as_calibrated():
    """test_n=1（叶绿素 a）时经验覆盖率非 0 即 1，不得判为校准有效。"""
    service = AlgorithmModelServiceV3(realtime_provider=None)
    payload = service._build_uncertainty(
        _bundle(residual_p05=-1.0, residual_p95=1.0, calibration_n=31, test_n=1, coverage=0.0),
        3.06, "chla", "frozen_split",
    )
    assert payload["structural_valid"] is True
    assert payload["calibration_status"] == CALIBRATION_INSUFFICIENT_TEST_EVIDENCE
    assert payload["decision_usable"] is False
    assert payload["coverage"]["test_n"] == 1


def test_zero_test_sample_is_reported_as_no_evidence():
    """T3/T4 在冻结测试期无标签（test_n=0）→ 无校准证据，且不得判为可用。"""
    service = AlgorithmModelServiceV3(realtime_provider=None)
    payload = service._build_uncertainty(
        _bundle(residual_p05=-1.0, residual_p95=1.0, calibration_n=297, test_n=0, coverage=None),
        0.4, "density", "train_internal_time_block_cv_v1",
    )
    assert payload["calibration_status"] == CALIBRATION_NO_TEST_EVIDENCE
    assert payload["decision_usable"] is False
    assert "is_calibrated_confidence_interval" not in payload


def test_dual_fingerprint_contract_is_declared():
    """双指纹 schema 必须显式声明：observed 与 transformed 证明的事情不同。"""
    assert FINGERPRINT_SCHEMA == "dual_fingerprint_v1"


# ------------------------------------------------------------- 服役闸门


class _NoCapabilityRealtime:
    """没有 status()/catalog_signature() 的实时源：无法核实快照同源关系。"""

    def summary(self):
        return {"latest_snapshot_id": "x", "means": {}}

    def station(self, entity_id):
        return None


def test_snapshot_is_not_served_when_source_capability_missing():
    algorithm = SimpleNamespace(realtime=_NoCapabilityRealtime())
    service = PredictionSnapshotService(algorithm, _NoCapabilityRealtime(), cache_dir="__nonexistent__")
    service._published = {"id": "PRED_x", "key": {}, "manifest": {}, "common": {}, "lake": {}, "stations": {}}
    assert service._source_capability() is False
    assert service._serving_is_current() is False
    assert service.assemble("lake", 3) is None
    assert service.snapshot_payload("lake", "risk") is None


def test_snapshot_is_not_served_when_no_published_snapshot():
    algorithm = SimpleNamespace(realtime=_NoCapabilityRealtime())
    service = PredictionSnapshotService(algorithm, _NoCapabilityRealtime(), cache_dir="__nonexistent__")
    assert service._serving_is_current() is False
    assert service.assemble("lake", 1) is None


# ------------------------------------------- 单条推理 vs 批量推理一致性


def _compare(a, b, path="", diffs=None, tol=1e-9):
    """结构必须完全一致；数值允许批量推理固有的浮点末位差异（相对 1e-9）。"""
    if diffs is None:
        diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in set(a) | set(b):
            if key not in a or key not in b:
                diffs.append(f"{path}.{key} 键缺失")
                continue
            _compare(a[key], b[key], f"{path}.{key}", diffs, tol)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path} 长度不同 {len(a)}!={len(b)}")
            return diffs
        for index, (x, y) in enumerate(zip(a, b)):
            _compare(x, y, f"{path}[{index}]", diffs, tol)
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        if a != b:
            diffs.append(f"{path} {a!r}!={b!r}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        scale = max(abs(float(a)), abs(float(b)), 1.0)
        if abs(float(a) - float(b)) > tol * scale:
            diffs.append(f"{path} {a}!={b}")
    elif a != b:
        diffs.append(f"{path} {a!r}!={b!r}")
    return diffs


def test_single_and_batch_inference_agree():
    """批量预生成与逐实体推理必须同口径：结构完全一致，数值仅允许浮点末位差异。

    站点快照全部由批量路径生成、而接口回退走单条路径，两者若口径不同就会出现
    「同一站点两次读到不同数值」的问题。
    """
    from backend.app.services import service as backend_service

    algorithm = backend_service.algorithm_v3
    if algorithm is None:
        return
    entities = ["lake", "mee-0145cdb7"]
    skip = {"scope", "input_provenance", "acceptance", "retrieval_and_calibration"}
    problems = []
    for horizon in (3, 30):
        batch = algorithm.predict_suite_batch(horizon, entities)
        for entity in entities:
            single = algorithm.predict_suite(horizon, entity, "risk", explain=False)
            left = {k: v for k, v in single.items() if k not in skip}
            right = {k: v for k, v in batch[entity].items() if k not in skip}
            diffs = _compare(left, right, f"h{horizon}/{entity}")
            problems.extend(diffs[:5])
    assert not problems, "单条与批量推理口径不一致:\n" + "\n".join(problems)

