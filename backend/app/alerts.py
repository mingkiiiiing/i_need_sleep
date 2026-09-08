"""站点级蓝藻预警引擎：评估 → 状态机去重 → 多通道推送 → 全程落盘。

风险分级与后端 /realtime/summary 的蓝藻筛查完全同口径（阈值 10/25 μg/L）：
  chla ≥ 25 μg/L → moderate（红色告警）；≥ 10 μg/L → light（黄色预警）。

状态机（对"同一站持续越限"不重复轰炸）：
  无状态→light/moderate  触发并推送；light→moderate            升级并重新推送；
  同级持续                不重发；moderate→light                红色记 resolved(降级)，黄色按新触发推送；
  任何状态→低于阈值/站点退出快照                                  记 resolved。

推送通道：email（stdlib smtplib）与 sms（通用 webhook POST，适配短信网关中转）。
通道未配置/未启用 → 投递如实记 skipped 及原因，绝不伪造"已发送"；评估本身不受影响
（未配置时也能在页面看到"本应告警的站点"）。全部事件与投递回执 JSON 落盘 alerts-data/。

后台巡检线程在 main.py lifespan 启停；POST /realtime/alerts/evaluate 可手动触发。
"""

from __future__ import annotations

import http.client
import json
import smtplib
import ssl
import threading
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

ALERT_DATA_DIR = Path(__file__).resolve().parents[1] / "alerts-data"
ALERT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alerts-config.json"
CONFIG_EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "alerts-config.example.json"

ALERT_VERSION = "alerts-v1"
DEFAULT_EVALUATE_INTERVAL_S = 300.0
MAX_HISTORY = 1000

# 分级文案与判定说明（阈值与 providers.CHLA_LIGHT/CHLA_MODERATE 保持一致，勿单改此处）
LEVEL_META = {
    "light": {"label": "黄色预警", "color": "yellow", "rule": "叶绿素a ≥ 10 μg/L"},
    "moderate": {"label": "红色告警", "color": "red", "rule": "叶绿素a ≥ 25 μg/L"},
}
THRESHOLD_NOTE = "chla ≥ 25 μg/L 红色告警；≥ 10 μg/L 黄色预警（与实时汇总蓝藻筛查同口径）"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config() -> dict[str, Any]:
    """只读 alerts-config.json（真实配置）；不存在 = 未启用态。

    绝不回退读取 alerts-config.example.json——示例文件里的占位 host/url 会让
    通道被误判为"已配置"。配置未创建时评估照常、投递一律 skipped。
    """
    if ALERT_CONFIG_PATH.exists():
        try:
            return json.loads(ALERT_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"enabled": False, "evaluate_interval_s": DEFAULT_EVALUATE_INTERVAL_S, "channels": {}, "recipients": {}}


class AlertStore:
    """告警事件与站点状态机的 JSON 落盘（原子写 + 线程锁）。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = Path(data_dir) if data_dir else ALERT_DATA_DIR
        self._lock = threading.RLock()

    @property
    def alerts_path(self) -> Path:
        return self._dir / "alerts.json"

    @property
    def state_path(self) -> Path:
        return self._dir / "state.json"

    def _read(self, path: Path, root_key: str) -> dict[str, Any]:
        with self._lock:
            empty: dict[str, Any] = [] if root_key != "state" else {}
            if not path.exists():
                return {"version": ALERT_VERSION, root_key: empty}
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            payload.setdefault("version", ALERT_VERSION)
            payload.setdefault(root_key, empty)
            return payload

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(path)

    # ---- 告警事件 ----

    def list_alerts(self) -> list[dict[str, Any]]:
        return list(self._read(self.alerts_path, "alerts")["alerts"])

    def append_alert(self, event: dict[str, Any]) -> None:
        payload = self._read(self.alerts_path, "alerts")
        payload["alerts"].insert(0, event)
        payload["alerts"] = payload["alerts"][:MAX_HISTORY]
        payload["updated_at"] = _now_iso()
        self._write(self.alerts_path, payload)

    def update_alert(self, alert_id: str, **fields: Any) -> None:
        payload = self._read(self.alerts_path, "alerts")
        for event in payload["alerts"]:
            if event["id"] == alert_id:
                event.update(fields)
                break
        payload["updated_at"] = _now_iso()
        self._write(self.alerts_path, payload)

    # ---- 站点状态机 ----

    def load_state(self) -> dict[str, dict[str, Any]]:
        return dict(self._read(self.state_path, "state")["state"])

    def save_state(self, state: dict[str, dict[str, Any]]) -> None:
        payload = {"version": ALERT_VERSION, "updated_at": _now_iso(), "state": state}
        self._write(self.state_path, payload)


def _alert_id(station_id: str, level: str, at_iso: str) -> str:
    stamp = at_iso.strftime("%Y%m%dT%H%M%SZ") if hasattr(at_iso, "strftime") else str(at_iso)
    return f"alr-{stamp}-{station_id.removeprefix('mee-')[:8]}-{level[0]}"


def alert_message_text(level: str, station_name: str, province: str, chla: float | None) -> str:
    chla_text = f"{chla:.1f} μg/L" if chla is not None else "缺测"
    meta = LEVEL_META[level]
    return (
        f"【蓝藻水华预警】{meta['label']}（{meta['rule']}）\n"
        f"站点：{station_name}（{province}）\n"
        f"叶绿素a：{chla_text}\n"
        f"判定口径：{THRESHOLD_NOTE}\n"
        f"本消息由蓝藻水华监测预警系统自动发送（官方观测未经跨源验证，不用于监管决策）。"
    )


class EmailChannel:
    """SMTP 邮件通道（stdlib smtplib，SSL 或 STARTTLS）。未配置 → 一律 skipped。"""

    name = "email"

    def __init__(self, config: dict[str, Any] | None) -> None:
        self._config = config or {}

    @property
    def configured(self) -> bool:
        return bool(
            self._config.get("host") and self._config.get("username")
            and self._config.get("password") and self._config.get("from")
        )

    def send(self, subject: str, body: str, recipients: list[str]) -> dict[str, Any]:
        record: dict[str, Any] = {"channel": self.name, "recipients": recipients, "at": _now_iso()}
        if not self.configured:
            record.update({"status": "skipped", "detail": "channel_not_configured: alerts-config.json 未配置 SMTP"})
            return record
        if not recipients:
            record.update({"status": "skipped", "detail": "no_recipient: 该站点未配置收件邮箱"})
            return record
        try:
            message = MIMEText(body, "plain", "utf-8")
            message["Subject"] = subject
            message["From"] = self._config["from"]
            message["To"] = ", ".join(recipients)
            port = int(self._config.get("port", 465))
            if self._config.get("use_ssl", True):
                server: smtplib.SMTP = smtplib.SMTP_SSL(self._config["host"], port, timeout=float(self._config.get("timeout_s", 20)))
            else:
                server = smtplib.SMTP(self._config["host"], port, timeout=float(self._config.get("timeout_s", 20)))
                if self._config.get("use_starttls", True):
                    server.starttls(context=ssl.create_default_context())
            try:
                server.login(self._config["username"], self._config["password"])
                failures = server.sendmail(self._config["from"], recipients, message.as_string())
            finally:
                server.quit()
            if failures:
                record.update({"status": "failed", "detail": f"sendmail failures: {sorted(failures)}"})
            else:
                record.update({"status": "sent", "detail": f"SMTP {self._config['host']}:{port} 已接受"})
        except Exception as exc:  # noqa: BLE001 — 投递失败必须留痕但不阻断巡检
            record.update({"status": "failed", "detail": f"{type(exc).__name__}: {exc}"})
        return record


class SmsWebhookChannel:
    """短信通道：通用 webhook POST（stdlib http.client，适配短信网关中转服务）。

    请求体：{phones: [...], message: "...", **extra_payload}；网关 2xx 视为已发送，
    响应体前 200 字符作为回执落盘（页面"收到信息"）。模板占位符：
    {station} {province} {level} {chla} {time} {message}。
    """

    name = "sms"

    def __init__(self, config: dict[str, Any] | None) -> None:
        self._config = config or {}

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url"))

    def send(self, message: str, station: str, province: str, level: str, chla: float | None, recipients: list[str]) -> dict[str, Any]:
        record: dict[str, Any] = {"channel": self.name, "recipients": recipients, "at": _now_iso()}
        if not self.configured:
            record.update({"status": "skipped", "detail": "channel_not_configured: alerts-config.json 未配置短信网关"})
            return record
        if not recipients:
            record.update({"status": "skipped", "detail": "no_recipient: 该站点未配置手机号"})
            return record
        text = str(self._config.get("template", "{message}")).format(
            message=message, station=station, province=province, level=LEVEL_META[level]["label"],
            chla="" if chla is None else f"{chla:.1f}", time=_now_iso(),
        )
        parsed = urlsplit(self._config["url"])
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        headers = {"Content-Type": "application/json", **(self._config.get("headers") or {})}
        body = json.dumps({"phones": recipients, "message": text, **(self._config.get("extra_payload") or {})}, ensure_ascii=False)
        try:
            if parsed.scheme == "https":
                conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                    parsed.hostname, parsed.port or 443, timeout=float(self._config.get("timeout_s", 20))
                )
            else:
                conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=float(self._config.get("timeout_s", 20)))
            try:
                conn.request("POST", target, body=body.encode("utf-8"), headers=headers)
                resp = conn.getresponse()
                receipt = resp.read(2048).decode("utf-8", errors="replace")[:200]
            finally:
                conn.close()
            if 200 <= resp.status < 300:
                record.update({"status": "sent", "detail": f"HTTP {resp.status}", "receipt": receipt})
            else:
                record.update({"status": "failed", "detail": f"HTTP {resp.status}", "receipt": receipt})
        except Exception as exc:  # noqa: BLE001 — 投递失败必须留痕但不阻断巡检
            record.update({"status": "failed", "detail": f"{type(exc).__name__}: {exc}"})
        return record


class AlertEngine:
    """评估 + 去重 + 推送。快照与站点目录以 callable 注入（service 层），便于测试。"""

    def __init__(
        self,
        snapshot_fetch: Callable[[], dict[str, Any]],
        stations_fetch: Callable[[], list[dict[str, Any]]],
        *,
        store: AlertStore | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._snapshot_fetch = snapshot_fetch
        self._stations_fetch = stations_fetch
        self.store = store or AlertStore()
        self.config = config if config is not None else load_config()
        self.email = EmailChannel((self.config.get("channels") or {}).get("email"))
        self.sms = SmsWebhookChannel((self.config.get("channels") or {}).get("sms"))
        self.last_evaluated_at: str | None = None
        self.last_error: str | None = None
        self._lock = threading.RLock()

    @property
    def interval_s(self) -> float:
        return float(self.config.get("evaluate_interval_s", DEFAULT_EVALUATE_INTERVAL_S))

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    def recipients_for(self, station_id: str) -> dict[str, list[str]]:
        recipients = self.config.get("recipients") or {}
        per_station = (recipients.get("stations") or {}).get(station_id) or {}
        return {
            "emails": list(per_station.get("emails") or recipients.get("default_emails") or []),
            "phones": list(per_station.get("phones") or recipients.get("default_phones") or []),
        }

    def _deliver(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        recipients = self.recipients_for(event["station_id"])
        body = alert_message_text(event["level"], event["station_name"], event.get("province") or "—", event.get("chla"))
        subject = f"【蓝藻预警】{event['station_name']} {LEVEL_META[event['level']]['label']}"
        return [
            self.email.send(subject, body, recipients["emails"]),
            self.sms.send(body, event["station_name"], event.get("province") or "—", event["level"], event.get("chla"), recipients["phones"]),
        ]

    def evaluate(self) -> dict[str, Any]:
        """单次巡检：评估最新快照 → 差分状态机 → 推送 → 落盘。返回评估摘要。"""
        with self._lock:
            summary = self._snapshot_fetch()
            warnings = {w["station_id"]: w for w in summary.get("warnings") or []}
            stations = {s["id"]: s for s in self._stations_fetch()}
            state = self.store.load_state()
            now = _now_iso()
            triggered: list[str] = []
            escalated: list[str] = []
            resolved: list[dict[str, Any]] = []
            delivery_rows: list[dict[str, Any]] = []

            for station_id, w in warnings.items():
                level = w["band"]
                previous = state.get(station_id)
                if previous and previous["level"] == level:
                    continue  # 同级持续：不重发
                info = stations.get(station_id) or {}
                event = {
                    "id": _alert_id(station_id, level, now),
                    "station_id": station_id,
                    "station_name": w.get("station_name") or info.get("display_name") or station_id,
                    "province": info.get("province"),
                    "level": level,
                    "chla": w.get("chla"),
                    "snapshot_id": summary.get("selected_snapshot_id") or summary.get("latest_snapshot_id"),
                    "observed_at": summary.get("latest_observed_at"),
                    "kind": "escalation" if previous else "trigger",
                    "status": "active",
                    "triggered_at": now,
                    "resolved_at": None,
                    "deliveries": [],
                }
                if not self.enabled:
                    event["deliveries"] = [{
                        "channel": "none", "status": "skipped", "at": now, "recipients": [],
                        "detail": "push_disabled: alerts-config.json enabled=false（评估照常，推送未启用）",
                    }]
                else:
                    event["deliveries"] = self._deliver(event)
                if previous:
                    # 升级关闭旧级别事件（黄色事件随升级红色转为 resolved）
                    self.store.update_alert(previous["alert_id"], status="resolved", resolved_at=now, resolve_reason="escalated_to_moderate")
                self.store.append_alert(event)
                delivery_rows.extend(event["deliveries"])
                (escalated if previous else triggered).append(event["id"])
                state[station_id] = {"level": level, "alert_id": event["id"], "triggered_at": now}

            for station_id, previous in list(state.items()):
                w = warnings.get(station_id)
                band = w["band"] if w else None
                if previous["level"] == band:
                    continue  # 持续同级（含红色持续）
                if previous["level"] == "moderate" and band == "light":
                    reason = "downgraded_to_light"
                elif band is None:
                    reason = "station_missing" if station_id not in stations else "below_threshold"
                else:
                    reason = "below_threshold"
                self.store.update_alert(previous["alert_id"], status="resolved", resolved_at=now, resolve_reason=reason)
                resolved.append({"alert_id": previous["alert_id"], "station_id": station_id, "reason": reason})
                state.pop(station_id, None)

            self.store.save_state(state)
            self.last_evaluated_at = now
            self.last_error = None
            return {
                "evaluated_at": now,
                "enabled": self.enabled,
                "snapshot_id": summary.get("selected_snapshot_id") or summary.get("latest_snapshot_id"),
                "stations_scanned": len(stations),
                "warnings_seen": len(warnings),
                "triggered": triggered,
                "escalated": escalated,
                "resolved": resolved,
                "deliveries": delivery_rows,
            }

    # ---- 查询（右上角组件 / 预警页） ----

    def overview(self) -> dict[str, Any]:
        alerts = self.store.list_alerts()
        state = self.store.load_state()
        by_id = {a["id"]: a for a in alerts}
        active_alerts = [by_id[s["alert_id"]] for s in state.values() if s["alert_id"] in by_id]
        active_alerts.sort(key=lambda a: (-(a.get("chla") or 0.0), a["triggered_at"]))
        return {
            "version": ALERT_VERSION,
            "enabled": self.enabled,
            "channels": {"email": {"configured": self.email.configured}, "sms": {"configured": self.sms.configured}},
            "active_counts": {
                "light": sum(1 for a in active_alerts if a["level"] == "light"),
                "moderate": sum(1 for a in active_alerts if a["level"] == "moderate"),
            },
            "active_total": len(active_alerts),
            "active_alerts": active_alerts,
            "recent_alerts": alerts[:50],
            "last_evaluated_at": self.last_evaluated_at,
            "last_error": self.last_error,
            "thresholds": {"light": 10.0, "moderate": 25.0},
            "threshold_note": THRESHOLD_NOTE,
        }

    def run_forever(self, stop_event: threading.Event, interval_s: float | None = None) -> None:
        """后台巡检循环（lifespan 启停；异常不退出，留痕 last_error）。"""
        interval = interval_s or self.interval_s
        while not stop_event.wait(timeout=interval):
            try:
                self.evaluate()
            except Exception as exc:  # noqa: BLE001 — 巡检失败留痕，下轮重试
                self.last_error = f"{type(exc).__name__}: {exc}"
