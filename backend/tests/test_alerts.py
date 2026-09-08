"""预警引擎回归测试：状态机去重、升级/恢复、通道未配置如实记 skipped、落盘持久化。

测试全部使用 tmp_path，禁止写正式 alerts-data/；快照与站点目录以 fake 注入。
"""

from __future__ import annotations

import json

import pytest

from backend.app.alerts import (
    ALERT_VERSION,
    AlertEngine,
    AlertStore,
    EmailChannel,
    SmsWebhookChannel,
)


def _summary(warnings: list[dict]) -> dict:
    return {
        "selected_snapshot_id": "snap-1",
        "latest_snapshot_id": "snap-1",
        "latest_observed_at": "2026-09-08T00:00:00+08:00",
        "warnings": warnings,
    }


def _stations() -> list[dict]:
    return [
        {"id": "mee-aaaa1111", "display_name": "拖山", "province": "江苏省"},
        {"id": "mee-bbbb2222", "display_name": "五里湖心", "province": "江苏省"},
    ]


def _warning(station_id: str, band: str, chla: float) -> dict:
    return {"station_id": station_id, "station_name": "拖山" if station_id.endswith("1111") else "五里湖心", "chla": chla, "band": band}


@pytest.fixture()
def store(tmp_path):
    return AlertStore(tmp_path / "alerts-data")


def _engine(store, warnings, config=None):
    return AlertEngine(
        lambda: _summary(warnings),
        _stations,
        store=store,
        config=config if config is not None else {"enabled": False, "recipients": {}},
    )


class TestStateMachine:
    def test_trigger_then_persist_no_refire(self, store):
        warnings = [_warning("mee-aaaa1111", "light", 12.5)]
        engine = _engine(store, warnings)
        first = engine.evaluate()
        assert first["triggered"] and not first["escalated"] and not first["resolved"]
        event = store.list_alerts()[0]
        assert event["level"] == "light" and event["status"] == "active"
        # 未启用推送：如实记 skipped，绝不伪造 sent
        assert all(d["status"] == "skipped" for d in event["deliveries"])

        second = engine.evaluate()
        assert not second["triggered"] and not second["escalated"], "同级持续不得重发"
        assert len(store.list_alerts()) == 1

    def test_escalation_light_to_moderate(self, store):
        engine = _engine(store, [_warning("mee-aaaa1111", "light", 12.0)])
        engine.evaluate()
        engine = _engine(store, [_warning("mee-aaaa1111", "moderate", 30.0)])
        result = engine.evaluate()
        assert result["escalated"] and not result["triggered"]
        events = store.list_alerts()
        assert events[0]["level"] == "moderate" and events[0]["kind"] == "escalation"
        assert events[1]["status"] == "resolved" and events[1]["resolve_reason"] == "escalated_to_moderate", "升级后旧黄色事件应关闭"

    def test_recovery_when_warning_disappears(self, store):
        engine = _engine(store, [_warning("mee-aaaa1111", "moderate", 28.0)])
        engine.evaluate()
        engine = _engine(store, [])
        result = engine.evaluate()
        assert len(result["resolved"]) == 1
        assert result["resolved"][0]["reason"] == "below_threshold"
        assert store.list_alerts()[0]["status"] == "resolved"
        # 恢复后再次越限 → 新触发而不是复活旧事件
        engine = _engine(store, [_warning("mee-aaaa1111", "light", 11.0)])
        again = engine.evaluate()
        assert again["triggered"] and not again["escalated"]
        assert len(store.list_alerts()) == 2

    def test_station_leaving_registry_resolves(self, store):
        engine = _engine(store, [_warning("mee-bbbb2222", "light", 10.2)])
        engine.evaluate()
        # 站点退出 warnings 且不在站点目录 → station_missing
        engine = AlertEngine(
            lambda: _summary([]),
            lambda: [],
            store=store,
            config={"enabled": False, "recipients": {}},
        )
        result = engine.evaluate()
        assert result["resolved"][0]["reason"] == "station_missing"


class TestOverview:
    def test_counts_and_channels(self, store):
        engine = _engine(store, [
            _warning("mee-aaaa1111", "moderate", 30.0),
            _warning("mee-bbbb2222", "light", 11.0),
        ])
        engine.evaluate()
        overview = engine.overview()
        assert overview["version"] == ALERT_VERSION
        assert overview["enabled"] is False
        assert overview["active_total"] == 2
        assert overview["active_counts"] == {"light": 1, "moderate": 1}
        # 排序：chla 高的在前
        assert overview["active_alerts"][0]["level"] == "moderate"
        assert overview["channels"]["email"] == {"configured": False}
        assert overview["thresholds"] == {"light": 10.0, "moderate": 25.0}


class TestStorePersistence:
    def test_alerts_and_state_survive_reload(self, tmp_path):
        data_dir = tmp_path / "alerts-data"
        engine = _engine(AlertStore(data_dir), [_warning("mee-aaaa1111", "light", 10.5)])
        engine.evaluate()
        # 全新实例（模拟进程重启）读取同一落盘
        engine2 = _engine(AlertStore(data_dir), [_warning("mee-aaaa1111", "light", 10.5)])
        result = engine2.evaluate()
        assert not result["triggered"], "重启后状态机不得失忆重发"
        assert len(engine2.store.list_alerts()) == 1


class TestChannels:
    def test_email_unconfigured_skipped(self):
        record = EmailChannel({}).send("s", "b", ["a@example.com"])
        assert record["status"] == "skipped" and "channel_not_configured" in record["detail"]

    def test_sms_unconfigured_skipped(self):
        record = SmsWebhookChannel({}).send("m", "站", "省", "light", 12.0, ["138"])
        assert record["status"] == "skipped" and "channel_not_configured" in record["detail"]

    def test_no_recipient_skipped_when_configured(self):
        channel = EmailChannel({"host": "smtp.example.com", "username": "u", "password": "p", "from": "f@example.com"})
        record = channel.send("s", "b", [])
        assert record["status"] == "skipped" and "no_recipient" in record["detail"]

    def test_sms_webhook_sent_and_receipt(self, monkeypatch):
        class FakeResp:
            status = 200

            def read(self, n):
                return b'{"code":0,"msg":"ok"}'

        class FakeConn:
            def __init__(self, *args, **kwargs): ...

            def request(self, method, target, body, headers):
                FakeConn.last_body = json.loads(body.decode("utf-8"))

            def getresponse(self):
                return FakeResp()

            def close(self): ...

        monkeypatch.setattr("backend.app.alerts.http.client.HTTPSConnection", FakeConn)
        channel = SmsWebhookChannel({"url": "https://gw.example.com/send", "headers": {"Authorization": "Bearer t"}})
        record = channel.send("正文", "拖山", "江苏省", "moderate", 30.0, ["13800000000"])
        assert record["status"] == "sent"
        assert record["receipt"].startswith('{"code"')
        assert FakeConn.last_body["phones"] == ["13800000000"]


class TestEnabledMode:
    def test_enabled_without_channel_config_still_skips_honestly(self, store):
        engine = _engine(store, [_warning("mee-aaaa1111", "light", 10.1)], config={"enabled": True, "recipients": {}})
        result = engine.evaluate()
        assert result["enabled"] is True
        event = store.list_alerts()[0]
        assert all(d["status"] == "skipped" for d in event["deliveries"])
        assert event["deliveries"][0]["channel"] == "email"
