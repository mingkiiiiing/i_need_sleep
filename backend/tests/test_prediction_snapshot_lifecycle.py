"""预测快照生命周期合同测试（大任务二：快照与即时加载）。

覆盖审计验收的四条硬口径：
1. 版本键不变 → 绝不重新推理（页面打开/切换零推理的前提）；
2. 管理员主动重算 → 版本键不变也强制重新推理（代码口径修复后的唯一入口）；
3. 生成失败 → 保留上一成功版本继续服务，页面如实披露（using_previous_success）；
4. 页面读取回落即时推理 → 计数器如实记录（live_inference_fallbacks）。
"""
import json
from types import SimpleNamespace

from app.prediction_snapshot import PredictionSnapshotService


class _FakeRealtime:
    def status(self):
        return {"latest_snapshot_id": "mee_surface_water_realtime_test", "means": {}}

    def summary(self):
        return self.status()

    def stations(self, active="latest"):
        return []


class _FakeAlgorithm:
    """最小可生成算法桩：predict_suite 可计数、可注入故障。"""

    def __init__(self):
        self.realtime = _FakeRealtime()
        self.calls = 0
        self.fail = False

    def status(self):
        return {
            "package_version": "0.3.1",
            "model_count": 24,
            "feature_contract": {"version": "v2.0"},
            "data_version": "test",
            "model_artifacts": {
                "manifest_sha256": "a" * 64,
                "bundle_digest": "b" * 64,
                "bundle_hashes": {},
                "training_data_version": "test",
                "preprocessor": "test",
            },
        }

    def predict_suite(self, horizon_days, entity_id="lake", focus_metric="risk", explain=True):
        self.calls += 1
        if self.fail:
            raise RuntimeError("注入的生成故障")
        return {
            "acceptance": {},
            "retrieval_and_calibration": {},
            "model": {},
            "model_quality": {},
            "entity_id": entity_id,
            "horizon_days": horizon_days,
            "prediction_run_id": f"RUN-{horizon_days}",
            "results": {
                "probability": {"value": 0.01 * horizon_days, "value_origin": "v0_3_real_bundle"}
            },
        }


def _service(tmp_path):
    algorithm = _FakeAlgorithm()
    service = PredictionSnapshotService(
        algorithm, _FakeRealtime(), cache_dir=tmp_path, poll_interval_s=3600
    )
    return service, algorithm


def _sync_once(service):
    """直接调用对齐逻辑（不起后台线程）。"""
    service.ensure_fresh()


def test_version_key_unchanged_never_recomputes(tmp_path):
    service, algorithm = _service(tmp_path)
    _sync_once(service)
    assert service._generation_count == 1
    calls_after_generate = algorithm.calls  # 含全湖解释预热
    # 再次对齐：版本键不变 → 零推理、零新生成
    _sync_once(service)
    assert service._generation_count == 1
    assert algorithm.calls == calls_after_generate
    # 页面读取命中快照，结构完整且标注来源
    payload = service.snapshot_payload("lake", "risk")
    assert payload is not None
    assert payload["snapshot_source"]["served_from_snapshot"] is True
    assert payload["horizons"]["1"]["results"]["probability"]["value"] == 0.01


def test_force_rebuild_recomputes_even_when_version_unchanged(tmp_path):
    service, algorithm = _service(tmp_path)
    _sync_once(service)
    assert service._generation_count == 1
    calls_before = algorithm.calls
    # 管理员重算：即使版本键完全相同也必须真实重新推理
    service.request_rebuild()
    with service._lock:
        assert service._force_requested is True
    service.ensure_fresh(force=True)
    assert service._generation_count == 2
    assert algorithm.calls > calls_before
    payload = service.snapshot_payload("lake", "risk")
    assert payload is not None
    assert service.status()["generation_count"] == 2


def test_generation_failure_keeps_previous_success_serving(tmp_path):
    service, algorithm = _service(tmp_path)
    _sync_once(service)
    served_before = service.snapshot_payload("lake", "risk")
    assert served_before is not None
    # 注入故障后强制重算：必须失败但保留上一版
    algorithm.fail = True
    service.ensure_fresh(force=True)
    status = service.status()
    assert status["state"] == "failed"
    assert status["using_previous_success"] is True
    assert "注入的生成故障" in status["last_error"]
    # 页面继续读到上一成功版本的完整结果，数值与此前一致
    served_after = service.snapshot_payload("lake", "risk")
    assert served_after is not None
    assert (
        served_after["horizons"]["1"]["results"]["probability"]["value"]
        == served_before["horizons"]["1"]["results"]["probability"]["value"]
    )
    assert served_after["prediction_snapshot_id"] == served_before["prediction_snapshot_id"]


def test_live_inference_fallback_counter(tmp_path):
    service, _algorithm = _service(tmp_path)
    assert service.status()["live_inference_fallbacks"] == 0
    service.count_live_inference_fallback()
    service.count_live_inference_fallback()
    assert service.status()["live_inference_fallbacks"] == 2


def test_status_file_records_counters(tmp_path):
    service, _algorithm = _service(tmp_path)
    _sync_once(service)
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["generation_count"] == 1
    assert status["live_inference_fallbacks"] == 0


def test_business_reads_never_fall_back_to_live_inference(tmp_path, monkeypatch):
    """GPT 审计指令（2026-09-11）：业务读取接口必须彻底移除 cache miss → live inference。

    快照未就绪时 prediction_snapshot_view / algorithm_predictions_v3 一律 409
    PREDICTION_SNAPSHOT_NOT_READY，绝不允许为读取运行模型。
    """
    from types import SimpleNamespace as NS

    import pytest

    from backend.app import services as services_module
    from backend.app.errors import ApiError

    class _NoCapability:
        """无 status()/stations() 能力：快照无法核实同源关系，不服务。"""

    stub = PredictionSnapshotService(NS(realtime=_NoCapability()), _NoCapability(), cache_dir=tmp_path)
    original = services_module.service.prediction_snapshot
    monkeypatch.setattr(services_module.service, "prediction_snapshot", stub)
    try:
        with pytest.raises(ApiError) as exc_view:
            services_module.service.prediction_snapshot_view("lake", "risk")
        assert exc_view.value.status_code == 409
        assert exc_view.value.detail["code"] == "PREDICTION_SNAPSHOT_NOT_READY"
        with pytest.raises(ApiError) as exc_pred:
            services_module.service.algorithm_predictions_v3(1, "lake", "risk")
        assert exc_pred.value.status_code == 409
        assert exc_pred.value.detail["code"] == "PREDICTION_SNAPSHOT_NOT_READY"
    finally:
        services_module.service.prediction_snapshot = original
