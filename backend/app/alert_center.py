"""预警与应急预案中心：在 alerts.py 引擎（触发/去重/真实通道推送）之上叠加"事件处置层"。

职责划分（与 alerts.py 严格分层，旧接口与 Wallboard/铃铛旧数据源不受影响）：
  引擎层 alerts.py —— 判定越限、升级去重、真实 SMTP/短信投递（alerts-config.json 启用）。
  中心层 alert_center —— 事件工作流（待确认→已确认→处理中→待复核→已关闭/撤销）、
  应急预案匹配与采用、短信/邮件"模拟推送"（绝不真发）、站内通知与已读状态、规则展示/通知策略、
  处理记录与审计日志。全部 JSON 落盘 alerts-data/。

设计要点（对应预警中心设计稿）：
  - 站点退出快照 ≠ 指标恢复：引擎记 station_missing 时，中心事件证据态记"待核实"，不得视为恢复。
  - 指标恢复：证据态记"已恢复"并把事件转入待复核，不自动关闭、不自动完成任务。
  - 一条变化只产生一条未读通知（新触发/升级/恢复待核实/恢复待复核/模拟推送失败）。
  - 模拟推送回执明确标注"模拟发送"，未配置接收人记模拟失败（可重试），绝不伪造真实送达。
  - 预测预警为预留类型：时空推演预测批次接入前只有入口与空态，不伪造预测事件。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .alerts import LEVEL_META, THRESHOLD_NOTE, AlertEngine

logger = logging.getLogger(__name__)

CENTER_VERSION = "alert-center-v1"
MAX_RECORDS = 500
MAX_NOTIFICATIONS = 300


class CenterNotFound(KeyError):
    """事件/预案/任务不存在（API 层映射为 404）。"""


class CenterInvalidOperation(ValueError):
    """状态机/参数不允许的操作（API 层映射为 422，带可读原因）。"""

EVENT_STATUS_META = {
    "pending": {"label": "待确认"},
    "acknowledged": {"label": "已确认"},
    "processing": {"label": "处理中"},
    "review": {"label": "待复核"},
    "closed": {"label": "已关闭"},
    "revoked": {"label": "已撤销"},
}

# 状态机允许的流转：action → 允许的前置状态
ACTION_TRANSITIONS = {
    "confirm": {"pending"},
    "assign": {"pending", "acknowledged", "processing"},
    "start": {"acknowledged"},
    "submit_review": {"processing"},
    "close": {"review"},
    "reopen": {"closed", "revoked"},
    "revoke": {"pending", "acknowledged", "processing", "review"},
}

PUSH_GROUPS = {
    "monitor": {"label": "监测组", "emails_key": "default_emails", "phones_key": "default_phones"},
    "patrol": {"label": "巡查组", "emails_key": "default_emails", "phones_key": "default_phones"},
    "disposal": {"label": "处置组", "emails_key": "default_emails", "phones_key": "default_phones"},
    "admin": {"label": "管理员", "emails_key": "default_emails", "phones_key": "default_phones"},
}

# 模拟收件人注册表：alerts-config.json 未配置真实收件人时使用（域名 .sim.invalid 为保留假域名）。
# 模拟推送明确标注"不实际发送"，此注册表仅用于让模拟链路完整走通（回执/记录/脱敏展示）。
SIMULATED_RECIPIENTS = {
    "monitor": {"emails": ["monitor@a23-sim.invalid"], "phones": ["13800000001"]},
    "patrol": {"emails": ["patrol@a23-sim.invalid"], "phones": ["13800000002"]},
    "disposal": {"emails": ["disposal@a23-sim.invalid"], "phones": ["13800000003"]},
    "admin": {"emails": ["admin@a23-sim.invalid"], "phones": ["13800000004"]},
}

DEFAULT_RULES: dict[str, Any] = {
    "version": "center-rules-v1",
    "updated_at": None,
    "realtime": {
        "name": "蓝藻筛查（实测口径）",
        "indicator": "chlorophyll_a",
        "unit": "μg/L",
        "thresholds": {"light": 10.0, "moderate": 25.0},
        "note": f"阈值与实时汇总蓝藻筛查同口径（{THRESHOLD_NOTE}），由观测口径统一定义，系统内不单独改值。",
    },
    "predicted": {
        "name": "水华风险预测（预留）",
        "enabled": False,
        "min_horizon_days": 1,
        "max_horizon_days": 90,
        "probability_threshold": 0.6,
        "note": "时空推演预测批次接入后启用；启用前不产生预测预警事件。",
    },
    "notify": {"new_event": True, "escalation": True, "recovery": True, "unverified": False, "process": True, "push_failure": True},
    "auto_simulate_push": {"enabled": False, "channels": ["sms", "email"], "groups": ["monitor"]},
}

# 预案库种子：措施为通用监测/巡查/研判动作，不含未经项目确认的具体处置工艺。
DEFAULT_PLANS: list[dict[str, Any]] = [
    {
        "id": "plan-light-realtime",
        "name": "蓝藻轻度关注应急响应预案",
        "version": "v1.0",
        "active": True,
        "scope": "全部站点",
        "risk_types": ["chlorophyll_a"],
        "stage": "realtime",
        "levels": ["light", "moderate"],
        "department": "监测预警专班",
        "measures": [
            {"text": "复核监测数据与异常指标", "group": "monitor", "due": "确认后设置"},
            {"text": "安排现场巡查与采样观察", "group": "patrol", "due": "按预案设置"},
            {"text": "跟踪后续观测变化并更新记录", "group": "monitor", "due": "按周期设置"},
        ],
    },
    {
        "id": "plan-moderate-realtime",
        "name": "蓝藻中度预警应急处置预案",
        "version": "v1.0",
        "active": True,
        "scope": "全部站点",
        "risk_types": ["chlorophyll_a"],
        "stage": "realtime",
        "levels": ["moderate"],
        "department": "监测预警专班",
        "measures": [
            {"text": "复核监测数据与异常指标", "group": "monitor", "due": "确认后设置"},
            {"text": "加强监测频次（缩短巡检间隔）", "group": "monitor", "due": "按预案设置"},
            {"text": "安排现场巡查与采样送检", "group": "patrol", "due": "按预案设置"},
            {"text": "组织研判会商并形成简报", "group": "monitor", "due": "确认后设置"},
        ],
    },
    {
        "id": "plan-predicted-prepare",
        "name": "水华预测风险提前准备预案",
        "version": "v1.0",
        "active": True,
        "scope": "全部湖区",
        "risk_types": ["chlorophyll_a"],
        "stage": "predicted",
        "levels": ["light", "moderate"],
        "department": "监测预警专班",
        "measures": [
            {"text": "复核预测依据与驱动因素", "group": "monitor", "due": "确认后设置"},
            {"text": "安排风险窗口前加密监测", "group": "monitor", "due": "按预测窗口设置"},
            {"text": "预备巡查排班与采样器材", "group": "patrol", "due": "按预测窗口设置"},
        ],
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    """解析 ISO 时间；无时区的按 UTC 处理（上游观测时间戳可能不带 offset）。"""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _mask(addr: str) -> str:
    """收件地址脱敏：保留首尾，中间打码。"""
    text = str(addr)
    if "@" in text:
        name, _, domain = text.partition("@")
        return f"{name[:2]}***@{domain}" if len(name) > 2 else f"***@{domain}"
    if len(text) >= 7:
        return f"{text[:3]}****{text[-3:]}"
    return "***"


class CenterStore:
    """预警中心 JSON 落盘（原子写 + 线程锁），文件彼此独立。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1] / "alerts-data"
        self._lock = threading.RLock()

    def _path(self, name: str) -> Path:
        return self._dir / name

    def _read(self, name: str, root_key: str, default: Any) -> dict[str, Any]:
        with self._lock:
            path = self._path(name)
            if not path.exists():
                return {"version": CENTER_VERSION, root_key: default}
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            payload.setdefault("version", CENTER_VERSION)
            payload.setdefault(root_key, default)
            return payload

    def _write(self, name: str, root_key: str, value: Any) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._path(name)
            payload = {"version": CENTER_VERSION, "updated_at": _now_iso(), root_key: value}
            temp = path.with_name(f".{path.name}.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(path)

    # ---- 事件 ----
    def list_events(self) -> list[dict[str, Any]]:
        return list(self._read("center-events.json", "events", [])["events"])

    def save_events(self, events: list[dict[str, Any]]) -> None:
        self._write("center-events.json", "events", events[:MAX_RECORDS])

    # ---- 通知 ----
    def list_notifications(self) -> list[dict[str, Any]]:
        return list(self._read("notifications.json", "notifications", [])["notifications"])

    def save_notifications(self, rows: list[dict[str, Any]]) -> None:
        self._write("notifications.json", "notifications", rows[:MAX_NOTIFICATIONS])

    def load_read_state(self, user: str = "local") -> dict[str, str]:
        payload = self._read("read-state.json", "users", {})
        return dict((payload["users"].get(user) or {}))

    def save_read_state(self, user: str, state: dict[str, str]) -> None:
        payload = self._read("read-state.json", "users", {})
        payload["users"][user] = state
        self._write("read-state.json", "users", payload["users"])

    # ---- 预案 / 规则 ----
    def list_plans(self) -> list[dict[str, Any]]:
        return list(self._read("plans.json", "plans", [])["plans"])

    def save_plans(self, plans: list[dict[str, Any]]) -> None:
        self._write("plans.json", "plans", plans)

    def load_rules(self) -> dict[str, Any]:
        payload = self._read("center-rules.json", "rules", {})
        if not payload["rules"]:
            return json.loads(json.dumps(DEFAULT_RULES, ensure_ascii=False))
        return payload["rules"]

    def save_rules(self, rules: dict[str, Any]) -> None:
        self._write("center-rules.json", "rules", rules)


class AlertCenter:
    """事件工作流 + 预案匹配 + 模拟推送 + 通知。引擎以注入方式复用。"""

    def __init__(self, engine: AlertEngine, store: CenterStore | None = None) -> None:
        self.engine = engine
        self.store = store or CenterStore()
        self._lock = threading.RLock()
        self._bootstraped = False

    # ---- 启动引导：把引擎已有告警导入为事件（只执行一次） ----
    def bootstrap(self) -> None:
        with self._lock:
            if self._bootstraped:
                return
            plans = self.store.list_plans()
            if not plans:
                self.store.save_plans(json.loads(json.dumps(DEFAULT_PLANS, ensure_ascii=False)))
            events = self.store.list_events()
            if not events:
                events = self._import_engine_alerts(self.engine.store.list_alerts())
                if events:
                    self.store.save_events(events)
                    for event in events:
                        if event["status"] == "pending":
                            self._notify(event, "new_event", f"新实时预警：{event['station_name']}", [
                                f"{event['title']}",
                                f"实测 {self._fmt_value(event['evidence'])} · 观测 {self._fmt_time(event['evidence'].get('observed_at'))}",
                            ])
                self._bootstraped = True
                return
            self._bootstraped = True

    def _import_engine_alerts(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """历史引擎告警 → 中心事件（active→待确认；恢复→已关闭；站点缺失→待核实待复核）。"""
        events: list[dict[str, Any]] = []
        for alert in alerts[:100]:
            status = "pending" if alert.get("status") == "active" else "closed"
            evidence_state = "valid" if alert.get("status") == "active" else "recovered"
            if alert.get("status") != "active" and alert.get("resolve_reason") == "station_missing":
                evidence_state, status = "unverified", "review"
            event = self._new_event(alert, status=status, evidence_state=evidence_state)
            event["records"].append({
                "at": alert.get("triggered_at") or _now_iso(),
                "actor": "系统",
                "action": "import",
                "detail": "历史告警导入预警中心（引擎已判定）",
            })
            events.append(event)
        return events

    # ---- 事件构造 ----
    def _new_event(
        self,
        alert: dict[str, Any],
        *,
        status: str = "pending",
        evidence_state: str = "valid",
    ) -> dict[str, Any]:
        level = alert.get("level") or "light"
        observed_at = alert.get("observed_at")
        station_name = alert.get("station_name") or alert.get("station_id") or "未知站点"
        return {
            "id": f"evt-{uuid.uuid4().hex[:12]}",
            "no": f"AL{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}",
            "type": "realtime",
            "level": level,
            "title": f"{station_name} · 叶绿素a达到{LEVEL_META[level]['label']}阈值",
            "station_id": alert.get("station_id"),
            "station_name": station_name,
            "province": alert.get("province"),
            "status": status,
            "assignee": None,
            "evidence": {
                "indicator": "叶绿素a",
                "indicator_code": "chlorophyll_a",
                "unit": "μg/L",
                "value": alert.get("chla"),
                "threshold": 10.0 if level == "light" else 25.0,
                "observed_at": observed_at,
                "triggered_at": alert.get("triggered_at"),
                "snapshot_id": alert.get("snapshot_id"),
                "state": evidence_state,
                "continuous": 1,
                "rule_name": f"蓝藻筛查 · {LEVEL_META[level]['label']}（叶绿素a ≥ {'10' if level == 'light' else '25'} μg/L）",
            },
            "rule_name": f"蓝藻筛查 · {LEVEL_META[level]['label']}",
            "engine_alert_id": alert.get("id"),
            "engine_alert_ids": [alert.get("id")],
            "plan": None,
            "records": [],
            "pushes": [],
            "notified": {},
            "created_at": alert.get("triggered_at") or _now_iso(),
            "updated_at": _now_iso(),
            "closed_at": None,
            "acknowledged_at": None,
            "recovered_at": None,
        }

    # ---- 与引擎评估联动 ----
    def sync_from_engine(self) -> dict[str, Any]:
        """每轮引擎评估后调用：把引擎告警差分同步为中心事件（触发/升级/恢复/待核实）。"""
        with self._lock:
            self.bootstrap()
            state = self.engine.store.load_state()
            alerts = {a["id"]: a for a in self.engine.store.list_alerts()}
            events = self.store.list_events()
            by_engine = {}
            for event in events:
                for aid in event.get("engine_alert_ids") or []:
                    by_engine[aid] = event
                if event.get("engine_alert_id"):
                    by_engine[event["engine_alert_id"]] = event
            created = upgraded = recovered = unverified = 0
            auto_push_ids: list[str] = []

            for alert_id, alert in alerts.items():
                event = by_engine.get(alert_id)
                if event is None:
                    # 新引擎告警：优先并入该站未关闭事件（升级复用），否则新建
                    open_event = next(
                        (
                            e for e in events
                            if e.get("station_id") == alert.get("station_id")
                            and e.get("type") == "realtime"
                            and e.get("status") in ("pending", "acknowledged", "processing", "review")
                        ),
                        None,
                    )
                    if open_event is not None:
                        event = open_event
                        old_level = event.get("level")
                        new_level = alert.get("level")
                        event["level"] = new_level
                        event["engine_alert_ids"] = list({
                            *(event.get("engine_alert_ids") or []),
                            alert_id,
                        })
                        event["engine_alert_id"] = alert_id
                        event["evidence"].update({
                            "value": alert.get("chla"),
                            "threshold": 10.0 if new_level == "light" else 25.0,
                            "observed_at": alert.get("observed_at"),
                            "state": "valid",
                        })
                        old_label = LEVEL_META.get(old_level, {}).get("label", old_level)
                        new_label = LEVEL_META.get(new_level, {}).get("label", new_level)
                        if old_level != new_level:
                            # F-2（R4 整改 2026-09-13）：只有等级真正变化才记 escalate/
                            # 发升级通知/计 upgraded——此前同级并入也走这里，产生
                            # "由黄色预警升级为黄色预警"的自相矛盾留痕。
                            event["records"].append({
                                "at": _now_iso(),
                                "actor": "系统",
                                "action": "escalate",
                                "detail": f"风险等级由 {old_label} 升级为 {new_label}",
                            })
                            upgraded += 1
                            self._notify(event, "escalation", f"风险升级：{event['station_name']}", [
                                f"{event['title']} 已升级为 {new_label}",
                            ])
                        else:
                            event["records"].append({
                                "at": _now_iso(),
                                "actor": "系统",
                                "action": "update",
                                "detail": f"风险等级维持 {new_label}（并入新引擎告警，证据已刷新）",
                            })
                    else:
                        event = self._new_event(alert)
                        events.insert(0, event)
                        created += 1
                        self._notify(event, "new_event", f"新实时预警：{event['station_name']}", [
                            f"{event['title']}",
                            f"实测 {self._fmt_value(event['evidence'])} · 观测 {self._fmt_time(event['evidence'].get('observed_at'))}",
                        ])
                    if (self.store.load_rules().get("auto_simulate_push") or {}).get("enabled"):
                        auto_push_ids.append(event["id"])
                else:
                    # 已有事件：刷新证据值
                    event["evidence"].update({
                        "value": alert.get("chla"),
                        "observed_at": alert.get("observed_at"),
                    })

            # 引擎当前活跃站 → 证据有效；被引擎判恢复的站 → 按原因分流
            active_alert_ids = {s["alert_id"] for s in state.values() if s.get("alert_id")}
            for event in events:
                if event.get("type") != "realtime" or event.get("status") in ("closed", "revoked"):
                    continue
                aid = event.get("engine_alert_id")
                if aid in active_alert_ids:
                    if event["evidence"].get("state") != "valid":
                        event["evidence"]["state"] = "valid"
                        event["records"].append({"at": _now_iso(), "actor": "系统", "action": "evidence", "detail": "证据恢复有效（重新报数且越限）"})
                    continue
                engine_alert = alerts.get(aid)
                if not engine_alert or engine_alert.get("status") != "resolved":
                    continue
                reason = engine_alert.get("resolve_reason")
                if reason == "station_missing":
                    if event["evidence"].get("state") != "unverified":
                        event["evidence"]["state"] = "unverified"
                        event["records"].append({"at": _now_iso(), "actor": "系统", "action": "unverified", "detail": "站点退出最新快照，数据待核实（不视为恢复）"})
                        unverified += 1
                        self._notify(event, "unverified", f"数据待核实：{event['station_name']}", [
                            "站点退出最新快照，无法确认指标状态，请安排核实。",
                        ])
                else:
                    if event["evidence"].get("state") in ("valid", "unverified", None):
                        event["evidence"]["state"] = "recovered"
                        event["recovered_at"] = _now_iso()
                        recovered += 1
                        event["records"].append({"at": _now_iso(), "actor": "系统", "action": "recovered", "detail": "指标恢复至阈值以下，转入待复核"})
                        if event["status"] in ("pending", "acknowledged", "processing"):
                            event["status"] = "review"
                            event["records"].append({"at": _now_iso(), "actor": "系统", "action": "to_review", "detail": "证据已恢复，请复核后关闭"})
                        self._notify(event, "recovery", f"指标已恢复待复核：{event['station_name']}", [
                            f"{event['station_name']} 叶绿素a 已恢复至阈值以下，请复核处置结果。",
                        ])
                event["updated_at"] = _now_iso()

            for event in events:
                event["updated_at"] = event.get("updated_at") or _now_iso()
            self.store.save_events(events)
            for eid in auto_push_ids:
                self._auto_simulate_push(eid)
            return {"created": created, "upgraded": upgraded, "recovered": recovered, "unverified": unverified}

    def evaluate_and_sync(self) -> dict[str, Any]:
        """手动/后台巡检入口：引擎评估 + 中心同步。"""
        result = self.engine.evaluate()
        result["center_sync"] = self.sync_from_engine()
        return result

    def run_forever(self, stop_event: threading.Event, interval_s: float | None = None) -> None:
        """后台巡检循环（等价 engine.run_forever，每轮后同步预警中心）。"""
        interval = interval_s or self.engine.interval_s
        while not stop_event.wait(timeout=interval):
            try:
                self.evaluate_and_sync()
            except Exception:  # noqa: BLE001 — 巡检失败留痕，下轮重试
                self.engine.last_error = "center sync failed (see server log)"

    # ---- 查询 ----
    def overview(self, *, event_filter: str = "all", status_filter: str = "all", search: str = "") -> dict[str, Any]:
        self.bootstrap()
        events = self.store.list_events()
        notifications = self.store.list_notifications()
        read_state = self.store.load_read_state()
        rules = self.store.load_rules()
        if event_filter == "realtime":
            events = [e for e in events if e.get("type") == "realtime"]
        elif event_filter == "predicted":
            events = [e for e in events if e.get("type") == "predicted"]
        if status_filter != "all":
            events = [e for e in events if e.get("status") == status_filter]
        if search:
            key = search.strip().lower()
            events = [e for e in events if key in (e.get("station_name") or "").lower() or key in (e.get("no") or "").lower()]

        def _brief(e: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": e["id"],
                "no": e["no"],
                "type": e["type"],
                "level": e["level"],
                "title": e["title"],
                "station_name": e.get("station_name"),
                "province": e.get("province"),
                "status": e.get("status"),
                "assignee": e.get("assignee"),
                "value": e["evidence"].get("value"),
                "unit": e["evidence"].get("unit"),
                "threshold": e["evidence"].get("threshold"),
                "observed_at": e["evidence"].get("observed_at"),
                "evidence_state": e["evidence"].get("state"),
                "created_at": e.get("created_at"),
                "updated_at": e.get("updated_at"),
            }

        return {
            "version": CENTER_VERSION,
            "stats": self._stats(self.store.list_events()),
            "events": [_brief(e) for e in events],
            "predicted_available": bool((rules.get("predicted") or {}).get("enabled")),
            "rules": self._public_rules(rules),
            "plans": self.store.list_plans(),
            "push_groups": self._push_groups_view(),
            "notifications": [self._brief_notification(n, read_state) for n in notifications[:80]],
            "unread_count": sum(1 for n in notifications if not read_state.get(n["id"])),
            "engine": {
                "enabled": self.engine.enabled,
                "last_evaluated_at": self.engine.last_evaluated_at,
                "last_error": self.engine.last_error,
                "channels": {
                    "email": {"configured": self.engine.email.configured},
                    "sms": {"configured": self.engine.sms.configured},
                },
                "threshold_note": THRESHOLD_NOTE,
            },
        }

    def event_detail(self, event_id: str) -> dict[str, Any] | None:
        for event in self.store.list_events():
            if event["id"] == event_id:
                view = dict(event)
                view["matched_plan"] = self.match_plan(event)
                return view
        return None

    def _push_groups_view(self) -> list[dict[str, Any]]:
        """推送接收组视图（含脱敏收件人与来源），供模拟推送弹窗展示。"""
        config = self.engine.config or {}
        default_emails = (config.get("recipients") or {}).get("default_emails") or []
        default_phones = (config.get("recipients") or {}).get("default_phones") or []
        rows = []
        for key, meta in PUSH_GROUPS.items():
            sim = SIMULATED_RECIPIENTS[key]
            emails = default_emails or sim["emails"]
            phones = default_phones or sim["phones"]
            rows.append({
                "value": key,
                "label": meta["label"],
                "recipients_masked": sorted({_mask(r) for r in emails + phones}),
                "source": "config" if (default_emails or default_phones) else "simulated",
            })
        return rows

    def _stats(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        # 「今日」按北京时间日界（全站时间展示口径统一为北京时间）
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()

        def closed_beijing_date(event: dict[str, Any]) -> str:
            closed = _parse_iso(event.get("closed_at") or "")
            return closed.astimezone(timezone(timedelta(hours=8))).date().isoformat() if closed else ""

        pending = [e for e in events if e.get("status") == "pending"]
        samples: list[float] = []
        for event in events:
            if event.get("acknowledged_at") and event.get("created_at"):
                created = _parse_iso(event["created_at"])
                acked = _parse_iso(event["acknowledged_at"])
                if created and acked:
                    samples.append(max(0.0, (acked - created).total_seconds() / 60.0))
        return {
            "pending": {
                "total": len(pending),
                "realtime": sum(1 for e in pending if e.get("type") == "realtime"),
                "predicted": sum(1 for e in pending if e.get("type") == "predicted"),
            },
            "processing": sum(1 for e in events if e.get("status") in ("acknowledged", "processing")),
            "closed_today": sum(1 for e in events if e.get("status") == "closed" and closed_beijing_date(e) == today),
            "avg_response_min": round(sum(samples) / len(samples), 1) if samples else None,
            "response_samples": len(samples),
        }

    # ---- 工作流动作 ----
    def apply_action(self, event_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            events = self.store.list_events()
            event = next((e for e in events if e["id"] == event_id), None)
            if event is None:
                raise KeyError(event_id)
            actor = (payload or {}).get("actor") or "值班员"
            allowed = ACTION_TRANSITIONS.get(action)
            if not allowed:
                raise ValueError(f"unknown action: {action}")
            if event["status"] not in allowed:
                raise ValueError(f"当前状态不允许该操作（{EVENT_STATUS_META[event['status']]['label']}）")

            now = _now_iso()
            detail = ""
            if action == "confirm":
                event["status"] = "acknowledged"
                event["acknowledged_at"] = now
                detail = (payload or {}).get("comment") or "已核实预警信息"
            elif action == "assign":
                assignee = (payload or {}).get("assignee")
                if not assignee:
                    raise ValueError("缺少 assignee")
                event["assignee"] = assignee
                detail = f"指派给 {assignee}"
                self._notify(event, "process", f"处理动态：{event['station_name']}预警已指派", [detail])
            elif action == "start":
                event["status"] = "processing"
                detail = "开始处置（按预案/措施执行）"
            elif action == "submit_review":
                event["status"] = "review"
                detail = (payload or {}).get("comment") or "处置完成，提交复核"
            elif action == "close":
                event["status"] = "closed"
                event["closed_at"] = now
                detail = (payload or {}).get("comment") or "复核通过，事件关闭"
            elif action == "reopen":
                event["status"] = "processing"
                event["closed_at"] = None
                detail = (payload or {}).get("reason") or "事件重新打开"
            elif action == "revoke":
                event["status"] = "revoked"
                event["closed_at"] = now
                detail = (payload or {}).get("reason") or "误报/重复事件，撤销"
            event["records"].append({"at": now, "actor": actor, "action": action, "detail": detail})
            event["updated_at"] = now
            # F-1（R4 整改 2026-09-13）：先落盘业务状态，成功后再记审计。原顺序是
            # 先 _audit 后 save_events，Windows 下 temp.replace 文件占用瞬态失败时
            # 会出现"审计记成功、业务未生效"的不一致窗口（实测 submit_review 500
            # 后 3 分钟才自愈）。现在 save 失败则不写成功审计，并以请求级堆栈入日志
            # （O-1）后原样上抛；audit 写失败不再让请求 500——业务事实已发生，
            # 审计缺口交由日志告警复核，避免"业务已生效却报错"诱发重复操作。
            try:
                self.store.save_events(events)
            except Exception:
                logger.exception(
                    "apply_action 事件落盘失败（未记成功审计）：event=%s action=%s actor=%s",
                    event_id, action, actor,
                )
                raise
            try:
                self._audit(actor, action, f"{event['no']}（{event['station_name']}）", detail)
            except Exception:
                logger.exception(
                    "apply_action 审计写入失败（业务状态已生效）：event=%s action=%s actor=%s",
                    event_id, action, actor,
                )
            return event

    # ---- 预案匹配与采用 ----
    def match_plan(self, event: dict[str, Any]) -> dict[str, Any] | None:
        plans = [p for p in self.store.list_plans() if p.get("active", True)]
        best: tuple[int, dict[str, Any], list[str]] | None = None
        for plan in plans:
            reasons: list[str] = []
            score = 0
            stage = "predicted" if event.get("type") == "predicted" else "realtime"
            if plan.get("stage") == stage:
                score += 2
                reasons.append("处置阶段一致（实时处置/预测准备）")
            if plan.get("stage") != stage:
                continue
            if event.get("level") in (plan.get("levels") or []):
                score += 2
                reasons.append(f"风险等级适用（{LEVEL_META.get(event['level'], {}).get('label', event['level'])}）")
            reasons.append("风险类型一致（叶绿素a / 蓝藻水华）")
            score += 1
            if plan.get("scope") == "全部站点" or plan.get("scope") == (event.get("province") or ""):
                reasons.append("适用范围覆盖事件对象")
                score += 1
            if best is None or score > best[0]:
                best = (score, plan, reasons)
        if best is None:
            return None
        plan = best[1]
        return {
            "plan_id": plan["id"],
            "name": plan["name"],
            "version": plan.get("version"),
            "department": plan.get("department"),
            "scope": plan.get("scope"),
            "match_reasons": best[2],
            "measures": list(plan.get("measures") or []),
        }

    def adopt_plan(self, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            events = self.store.list_events()
            event = next((e for e in events if e["id"] == event_id), None)
            if event is None:
                raise KeyError(event_id)
            if event.get("status") not in ("acknowledged", "processing"):
                raise ValueError("仅在已确认/处理中状态可采用预案")
            plan_id = (payload or {}).get("plan_id")
            plan = next((p for p in self.store.list_plans() if p["id"] == plan_id), None)
            if plan is None:
                raise KeyError(plan_id or "plan")
            tasks = [
                {
                    "id": f"task-{uuid.uuid4().hex[:8]}",
                    "text": m["text"],
                    "group": m.get("group"),
                    "due": m.get("due") or "",
                    "status": "todo",
                    "note": "",
                }
                for m in (plan.get("measures") or [])
            ]
            event["plan"] = {
                "plan_id": plan["id"],
                "name": plan["name"],
                "version": plan.get("version"),
                "adopted_at": _now_iso(),
                "tasks": tasks,
            }
            event["records"].append({
                "at": _now_iso(),
                "actor": (payload or {}).get("actor") or "值班员",
                "action": "adopt_plan",
                "detail": f"采用预案：{plan['name']}（{plan.get('version')}），生成 {len(tasks)} 项措施任务",
            })
            event["updated_at"] = _now_iso()
            self._audit((payload or {}).get("actor") or "值班员", "adopt_plan", event["no"], plan["name"])
            self.store.save_events(events)
            return event

    def update_task(self, event_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            events = self.store.list_events()
            event = next((e for e in events if e["id"] == event_id), None)
            if event is None or not event.get("plan"):
                raise KeyError(event_id)
            task = next((t for t in event["plan"]["tasks"] if t["id"] == task_id), None)
            if task is None:
                raise KeyError(task_id)
            status = (payload or {}).get("status")
            if status not in ("todo", "doing", "done"):
                raise ValueError("任务状态仅支持 todo/doing/done")
            task["status"] = status
            task["note"] = (payload or {}).get("note") or task.get("note") or ""
            done = sum(1 for t in event["plan"]["tasks"] if t["status"] == "done")
            event["records"].append({
                "at": _now_iso(),
                "actor": (payload or {}).get("actor") or "值班员",
                "action": "task",
                "detail": f"任务进展：{task['text']} → {status}（已完成 {done}/{len(event['plan']['tasks'])} 项）",
            })
            event["updated_at"] = _now_iso()
            self.store.save_events(events)
            return event

    # ---- 模拟推送（绝不真发） ----
    def simulate_push(self, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            events = self.store.list_events()
            event = next((e for e in events if e["id"] == event_id), None)
            if event is None:
                raise KeyError(event_id)
            channels = [c for c in ((payload or {}).get("channels") or []) if c in ("sms", "email")]
            groups = [g for g in ((payload or {}).get("groups") or []) if g in PUSH_GROUPS]
            if not channels:
                raise ValueError("请至少选择一个推送渠道（短信/邮件）")
            if not groups:
                raise ValueError("请至少选择一个接收组")
            actor = (payload or {}).get("actor") or "值班员"
            now = _now_iso()
            ev = event["evidence"]
            body = (payload or {}).get("body") or self._default_push_body(event)
            subject = (payload or {}).get("subject") or f"【太湖水华预警·模拟】{event['station_name']} {LEVEL_META.get(event['level'], {}).get('label', '')}"
            config = self.engine.config or {}
            default_emails = (config.get("recipients") or {}).get("default_emails") or []
            default_phones = (config.get("recipients") or {}).get("default_phones") or []
            results: list[dict[str, Any]] = []
            for channel in channels:
                if channel == "email":
                    recipients = default_emails or [r for g in groups for r in SIMULATED_RECIPIENTS[g]["emails"]]
                    source = "config" if default_emails else "simulated"
                else:
                    recipients = default_phones or [r for g in groups for r in SIMULATED_RECIPIENTS[g]["phones"]]
                    source = "config" if default_phones else "simulated"
                record = {
                    "id": f"push-{uuid.uuid4().hex[:10]}",
                    "at": now,
                    "actor": actor,
                    "channel": channel,
                    "groups": [PUSH_GROUPS[g]["label"] for g in groups],
                    "recipients_masked": sorted({_mask(r) for r in recipients}),
                    "recipient_source": source,
                    "subject": subject,
                    "body": body,
                    "receipt_no": f"SIM-{uuid.uuid4().hex[:8].upper()}",
                    "status": "simulated_success",
                    "reason": (
                        f"模拟发送成功（未实际发送{'邮件' if channel == 'email' else '短信'}；"
                        f"收件人来源：{'alerts-config.json' if source == 'config' else '模拟收件人注册表'}）"
                    ),
                }
                results.append(record)
            event["pushes"].extend(results)
            event["records"].append({
                "at": now,
                "actor": actor,
                "action": "simulate_push",
                "detail": "模拟推送：" + "、".join(r["channel"] for r in results) + f"（{len(results)} 条模拟回执）",
            })
            event["updated_at"] = now
            self._audit(actor, "simulate_push", event["no"], f"{len(results)} 条模拟推送")
            self.store.save_events(events)
            return {"event": event, "results": results}

    def _auto_simulate_push(self, event_id: str) -> None:
        try:
            self.simulate_push(event_id, {
                "channels": ["sms", "email"],
                "groups": ["monitor"],
            })
        except (ValueError, KeyError):
            pass

    def _default_push_body(self, event: dict[str, Any]) -> str:
        ev = event["evidence"]
        if event.get("type") == "predicted":
            return (
                f"【太湖水华预警·模拟】预测：{event['station_name']} 未来存在蓝藻水华风险"
                f"（{LEVEL_META.get(event['level'], {}).get('label', '')}）。"
                f"预计发生：{ev.get('window') or '待预测批次提供'}；预测依据：时空推演预测批次。"
                f"请提前安排核查与监测。编号 {event['no']}。（模拟消息，不实际发送）"
            )
        return (
            f"【太湖水华预警·模拟】{event['station_name']} 叶绿素a达到{LEVEL_META.get(event['level'], {}).get('label', '')}阈值，"
            f"观测值 {self._fmt_value(ev)}，观测时间 {self._fmt_time(ev.get('observed_at'))}。"
            f"请核实并查看关联预案。编号 {event['no']}。（模拟消息，不实际发送）"
        )

    # ---- 通知 ----
    def _notify(self, event: dict[str, Any], kind: str, title: str, lines: list[str]) -> None:
        """站内通知：由调用方保证"一次状态变化只调用一次"，这里只做策略开关过滤。"""
        rules = self.store.load_rules()
        if not (rules.get("notify") or {}).get(kind, True):
            return
        rows = self.store.list_notifications()
        rows.insert(0, {
            "id": f"ntf-{uuid.uuid4().hex[:12]}",
            "at": _now_iso(),
            "type": kind,
            "event_id": event["id"],
            "event_no": event.get("no"),
            "event_level": event.get("level"),
            "event_type": event.get("type"),
            "title": title,
            "lines": lines,
        })
        self.store.save_notifications(rows)

    def notifications_view(self, *, unread_only: bool = False) -> dict[str, Any]:
        self.bootstrap()
        rows = self.store.list_notifications()
        read_state = self.store.load_read_state()
        view = [self._brief_notification(n, read_state) for n in rows]
        if unread_only:
            view = [n for n in view if not n["read"]]
        return {
            "notifications": view[:120],
            "unread_count": sum(1 for n in rows if not read_state.get(n["id"])),
        }

    def _brief_notification(self, n: dict[str, Any], read_state: dict[str, str]) -> dict[str, Any]:
        item = dict(n)
        item["read"] = n["id"] in read_state
        item["read_at"] = read_state.get(n["id"])
        return item

    def mark_notifications_read(self, ids: list[str] | None = None, *, all: bool = False) -> dict[str, Any]:
        with self._lock:
            read_state = self.store.load_read_state()
            now = _now_iso()
            if all:
                rows = self.store.list_notifications()
                for n in rows:
                    read_state.setdefault(n["id"], now)
            else:
                for nid in ids or []:
                    if any(n["id"] == nid for n in self.store.list_notifications()):
                        read_state.setdefault(nid, now)
            self.store.save_read_state("local", read_state)
            return {"unread_count": sum(1 for n in self.store.list_notifications() if n["id"] not in read_state)}

    # ---- 规则 ----
    def _public_rules(self, rules: dict[str, Any]) -> dict[str, Any]:
        return {
            "realtime": rules.get("realtime") or DEFAULT_RULES["realtime"],
            "predicted": rules.get("predicted") or DEFAULT_RULES["predicted"],
            "notify": rules.get("notify") or DEFAULT_RULES["notify"],
            "auto_simulate_push": rules.get("auto_simulate_push") or DEFAULT_RULES["auto_simulate_push"],
        }

    def update_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rules = self.store.load_rules()
            allowed_notify = set(DEFAULT_RULES["notify"].keys())
            if "notify" in (payload or {}):
                current = rules.get("notify") or {}
                for key, value in payload["notify"].items():
                    if key in allowed_notify and isinstance(value, bool):
                        current[key] = value
                rules["notify"] = current
            if "auto_simulate_push" in (payload or {}):
                current = rules.get("auto_simulate_push") or DEFAULT_RULES["auto_simulate_push"]
                incoming = payload["auto_simulate_push"]
                if isinstance(incoming.get("enabled"), bool):
                    current["enabled"] = incoming["enabled"]
                if isinstance(incoming.get("channels"), list):
                    current["channels"] = [c for c in incoming["channels"] if c in ("sms", "email")] or ["sms"]
                if isinstance(incoming.get("groups"), list):
                    current["groups"] = [g for g in incoming["groups"] if g in PUSH_GROUPS] or ["monitor"]
                rules["auto_simulate_push"] = current
            if "predicted" in (payload or {}):
                predicted = rules.get("predicted") or DEFAULT_RULES["predicted"]
                incoming = payload["predicted"]
                if isinstance(incoming.get("probability_threshold"), (int, float)):
                    predicted["probability_threshold"] = min(0.99, max(0.01, float(incoming["probability_threshold"])))
                if isinstance(incoming.get("min_horizon_days"), int):
                    predicted["min_horizon_days"] = max(1, incoming["min_horizon_days"])
                if isinstance(incoming.get("max_horizon_days"), int):
                    predicted["max_horizon_days"] = min(365, incoming["max_horizon_days"])
                rules["predicted"] = predicted
            rules["updated_at"] = _now_iso()
            self.store.save_rules(rules)
            self._audit("值班员", "update_rules", "预警规则", "通知策略/模拟推送/预测参数更新")
            return self._public_rules(rules)

    # ---- 记录 ----
    def records_view(self) -> dict[str, Any]:
        self.bootstrap()
        events = self.store.list_events()
        records: list[dict[str, Any]] = []
        pushes: list[dict[str, Any]] = []
        audit: list[dict[str, Any]] = []
        for event in events:
            for r in event.get("records") or []:
                records.append({
                    "at": r.get("at"),
                    "event_no": event.get("no"),
                    "event_id": event.get("id"),
                    "station_name": event.get("station_name"),
                    "action": r.get("action"),
                    "detail": r.get("detail"),
                    "actor": r.get("actor"),
                })
            for p in event.get("pushes") or []:
                pushes.append({
                    "at": p.get("at"),
                    "event_no": event.get("no"),
                    "event_id": event.get("id"),
                    "station_name": event.get("station_name"),
                    "channel": p.get("channel"),
                    "groups": p.get("groups"),
                    "recipients_masked": p.get("recipients_masked"),
                    "status": p.get("status"),
                    "reason": p.get("reason"),
                    "receipt_no": p.get("receipt_no"),
                    "body": p.get("body"),
                    "actor": p.get("actor"),
                })
        audit = self._read_audit()
        records.sort(key=lambda r: r.get("at") or "", reverse=True)
        pushes.sort(key=lambda r: r.get("at") or "", reverse=True)
        return {"records": records[:200], "pushes": pushes[:100], "audit": audit[:200]}

    def _read_audit(self) -> list[dict[str, Any]]:
        return list(self.store._read("audit.json", "audit", [])["audit"])

    def _audit(self, actor: str, action: str, target: str, detail: str) -> None:
        rows = self._read_audit()
        rows.insert(0, {"at": _now_iso(), "actor": actor, "action": action, "target": target, "detail": detail, "result": "成功"})
        self.store._write("audit.json", "audit", rows[:MAX_RECORDS])

    # ---- 工具 ----
    @staticmethod
    def _fmt_value(ev: dict[str, Any]) -> str:
        value = ev.get("value")
        return "缺测" if value is None else f"{value} {ev.get('unit') or ''}".strip()

    @staticmethod
    def _fmt_time(iso: str | None) -> str:
        return (iso or "—").replace("T", " ")[:16]

    # ---- API 包装：CenterNotFound→404，CenterInvalidOperation→422 ----
    def event_detail_or_404(self, event_id: str) -> dict[str, Any]:
        detail = self.event_detail(event_id)
        if detail is None:
            raise CenterNotFound(event_id)
        return detail

    def action_or_404(self, event_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.event_detail_or_404(event_id)
        try:
            return self.apply_action(event_id, action, payload)
        except ValueError as exc:
            raise CenterInvalidOperation(str(exc)) from exc

    def push_or_404(self, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.event_detail_or_404(event_id)
        try:
            return self.simulate_push(event_id, payload)
        except KeyError as exc:
            raise CenterNotFound(event_id) from exc
        except ValueError as exc:
            raise CenterInvalidOperation(f"模拟推送参数无效：{exc}") from exc

    def adopt_plan_or_404(self, event_id: str, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.event_detail_or_404(event_id)
        try:
            return self.adopt_plan(event_id, {"plan_id": plan_id, **payload})
        except KeyError as exc:
            raise CenterNotFound(plan_id or event_id) from exc
        except ValueError as exc:
            raise CenterInvalidOperation(f"无法采用预案：{exc}") from exc

    def task_or_404(self, event_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.event_detail_or_404(event_id)
        try:
            return self.update_task(event_id, task_id, payload)
        except KeyError as exc:
            raise CenterNotFound(task_id) from exc
        except ValueError as exc:
            raise CenterInvalidOperation(f"任务更新无效：{exc}") from exc


# 模块级单例：api.py 与 main.py 共用同一份（与 services.alert_engine 同模式）。
from .services import alert_engine as _engine  # noqa: E402  — 放在模块尾避免循环导入

alert_center = AlertCenter(engine=_engine)
