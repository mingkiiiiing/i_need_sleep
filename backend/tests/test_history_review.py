"""历史复盘聚合接口测试：列表统计口径、详情聚合、复盘意见版本化与诚实空态。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.alert_center import AlertCenter, CenterStore
from backend.app.history_review import HistoryReviewService
from backend.main import app

client = TestClient(app)


def _stub_engine(alerts: list[dict]):
    class _Store:
        def __init__(self, rows):
            self._rows = rows

        def list_alerts(self):
            return list(self._rows)

        def load_state(self):
            return {}

    class _Engine:
        def __init__(self, rows):
            self.store = _Store(rows)
            self.config = {}
            self.enabled = False
            self.last_evaluated_at = None
            self.last_error = None
            self.interval_s = 600

            class _Channel:
                configured = False

            self.email = _Channel()
            self.sms = _Channel()

    return _Engine(alerts)


def _sample_alert(**overrides):
    alert = {
        "id": "alr-test-1",
        "station_id": "mee-test01",
        "station_name": "测试站",
        "province": "江苏省",
        "level": "light",
        "chla": 11.2,
        "snapshot_id": "snap-test-1",
        "observed_at": "2026-09-08T23:00:00+08:00",
        "kind": "trigger",
        "status": "active",
        "triggered_at": "2026-09-08T15:00:00+00:00",
        "resolved_at": None,
    }
    alert.update(overrides)
    return alert


@pytest.fixture()
def review_service(tmp_path):
    """独立数据目录的复盘服务：一个已确认事件 + 一条同站重复事件。"""
    alerts = [
        _sample_alert(),
        _sample_alert(id="alr-test-2", triggered_at="2026-09-09T15:00:00+00:00"),
    ]
    center = AlertCenter(engine=_stub_engine(alerts), store=CenterStore(tmp_path))
    center.bootstrap()
    events = center.store.list_events()
    events[0]["records"].append({"at": "2026-09-08T15:20:00+00:00", "actor": "值班员",
                                 "action": "confirm", "detail": "已核实"})
    events[0]["records"].append({"at": "2026-09-08T15:40:00+00:00", "actor": "值班员",
                                 "action": "escalate", "detail": "风险等级由 黄色预警 升级为 红色告警"})
    events[0]["level"] = "moderate"
    center.store.save_events(events)
    return HistoryReviewService(center=center, realtime=None, data_dir=tmp_path)


def test_list_reviews_stats_show_numerator_denominator(review_service):
    data = review_service.list_reviews()
    stats = data["stats"]
    assert stats["total"] == 2
    assert stats["closed"]["num"] == 0 and stats["closed"]["den"] == 2
    resp = stats["avg_response_min"]
    assert resp["samples"] == 1 and resp["value"] == 20.0  # 仅已确认事件进入响应样本


def test_list_reviews_filters(review_service):
    data = review_service.list_reviews(level="moderate")
    assert data["total"] == 1
    assert data["events"][0]["escalated"] is True
    data = review_service.list_reviews(plan_adopted="yes")
    assert data["total"] == 0
    data = review_service.list_reviews()
    assert data["events"][0]["recurrence_count"] == 1  # 同站 7 天内重复事件


def test_detail_aggregates_evidence_and_metrics(review_service):
    events = review_service.center.store.list_events()
    detail = review_service.review_detail(events[0]["id"])
    assert detail["event"]["no"] == detail["event"]["no"]
    assert detail["forecast_evidence"] is None
    assert "无可验证的正式预测" in detail["forecast_evidence_note"]
    kinds = [m["kind"] for m in detail["milestones"]]
    assert "trigger" in kinds and "confirm" in kinds and "escalate" in kinds
    tones = {m["tone"] for m in detail["milestones"]}
    assert "risk" in tones and "human" in tones
    resp = detail["response_metrics"]
    assert resp["trigger_to_confirm"]["minutes"] == 20.0  # 15:00 触发 → 15:20 确认
    assert resp["total_handling"]["ongoing"] is True
    assert resp["escalated"] is True
    assert resp["plan_tasks"]["total"] == 0
    # 观测轨未注入：证据必须显式不可用，不得伪造曲线
    assert detail["observed_evidence"]["available"] is False


def test_review_notes_save_with_version(review_service):
    events = review_service.center.store.list_events()
    event_id = events[0]["id"]
    first = review_service.save_review_notes(event_id, {"cause": "上游污水团", "improvements": [
        {"item": "加密巡查", "owner": "巡查组", "due": "2026-09-15"}
    ]}, editor="张三")
    assert first["exists"] is True and first["version"] == 1 and first["editor"] == "张三"
    assert first["fields"]["improvements"][0]["item"] == "加密巡查"
    second = review_service.save_review_notes(event_id, {"cause": "改口：面源污染"}, editor="李四")
    assert second["version"] == 2
    assert second["history"][0]["editor"] == "张三" and second["history"][-1]["editor"] == "李四"
    detail = review_service.review_detail(event_id)
    assert detail["review_notes"]["version"] == 2
    assert detail["review_notes"]["is_manual_review"] is True


def test_milestone_ids_unique_even_same_timestamp(review_service):
    """同一次模拟推送的短信+邮件回执共用时间戳：节点 ID 不得重复（重复会破坏前端 diff）。"""
    events = review_service.center.store.list_events()
    event_id = events[0]["id"]
    same_at = "2026-09-08T16:30:00+00:00"
    events[0]["pushes"] = [
        {"id": "push-a", "at": same_at, "channel": "sms", "status": "simulated_failed",
         "receipt_no": "SIM-1", "reason": "x", "groups": ["监测组"], "recipients_masked": [], "actor": "值班员"},
        {"id": "push-b", "at": same_at, "channel": "email", "status": "simulated_failed",
         "receipt_no": "SIM-2", "reason": "x", "groups": ["监测组"], "recipients_masked": [], "actor": "值班员"},
    ]
    review_service.center.store.save_events(events)
    detail = review_service.review_detail(event_id)
    ids = [m["id"] for m in detail["milestones"]]
    assert len(ids) == len(set(ids))
    # 内部辅助键不得泄露进响应
    assert "_trigger_at" not in detail["response_metrics"]


def test_event_lookup_bootstraps_fresh_store(tmp_path):
    """冷启动（store 为空、引擎有告警）时事件查询应先引导导入，而不是在空库上直接判 404。"""
    import pytest

    from backend.app.alert_center import CenterNotFound

    alerts = [_sample_alert()]
    center = AlertCenter(engine=_stub_engine(alerts), store=CenterStore(tmp_path / "fresh"))
    service = HistoryReviewService(center=center, realtime=None, data_dir=tmp_path / "fresh")
    assert center.store.list_events() == []
    with pytest.raises(CenterNotFound):
        service.review_timeline("evt-anything")
    # 查询过程完成了 bootstrap：引擎告警已导入为事件
    assert len(center.store.list_events()) == 1


def test_prediction_evaluations_honest_empty(review_service):
    data = review_service.prediction_evaluations()
    assert data["available"] is False
    assert data["verifiable"]["samples"] == 0
    assert data["metrics"]["hit_rate"] is None
    assert data["metric_definitions"]


def test_api_history_envelopes_and_404():
    r = client.get("/api/v1/history/reviews")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200 and "stats" in body["data"] and "events" in body["data"]
    events = body["data"]["events"]
    if events:
        eid = events[0]["id"]
        r = client.get(f"/api/v1/history/reviews/{eid}")
        assert r.status_code == 200
        detail = r.json()["data"]
        for key in ("event", "milestones", "observed_evidence", "plan_execution",
                    "notifications", "pushes", "response_metrics", "review_notes"):
            assert key in detail
        # 时间线节点 ID 必须全局唯一（前端以 id 为 v-for key）
        all_ids = []
        for ev in events:
            d = client.get(f"/api/v1/history/reviews/{ev['id']}").json()["data"]
            all_ids.append([m["id"] for m in d["milestones"]])
        for ids in all_ids:
            assert len(ids) == len(set(ids)), f"duplicate milestone ids: {ids}"
        r = client.get(f"/api/v1/history/reviews/{eid}/timeline")
        assert r.status_code == 200 and r.json()["data"]["milestones"]
        r = client.get(f"/api/v1/history/reviews/{eid}/evidence")
        assert r.status_code == 200
    r = client.get("/api/v1/history/reviews/evt-not-exist")
    assert r.status_code == 404
    r = client.get("/api/v1/history/reviews", params={"start": "2026/09/01"})
    assert r.status_code == 422
    r = client.put("/api/v1/history/reviews/evt-not-exist/review-notes",
                   json={"fields": {"cause": "x"}})
    assert r.status_code == 404
    r = client.get("/api/v1/history/prediction-evaluations")
    assert r.status_code == 200 and r.json()["data"]["available"] is False
    r = client.get("/api/v1/history/metrics")
    assert r.status_code == 200
