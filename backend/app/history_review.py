"""历史复盘聚合层：以预警事件 event_id 为主关联键，把观测证据、处理记录、
预案执行、站内通知与模拟推送组合成复盘视图。

职责边界（与 alert_center / providers 严格分层，对应历史复盘升级设计稿）：
  - 只读聚合：组合 alert_center 已落盘的事件/通知/预案快照与实时观测轨证据，
    不复制、不重构观测或推送数据。
  - 历史事实：里程碑/证据保留事件发生当时的内容（触发值优先取引擎告警留痕），
    不用事件当前状态覆盖过去发生过的事实。
  - 口径约束：事件关闭≠风险解除；任务完成≠措施有效；铃铛已读≠预警已确认；
    模拟推送成功≠真实送达；站点退出快照记"待核实"不视为恢复。
  - 预测复盘为预留结构：无 forecast_id / prediction_run_id 关联时诚实返回空态。
  - 复盘意见（人工）单独保存 review-notes.json，记录编辑人/保存时间/版本，
    与系统自动证据分离展示。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .alert_center import EVENT_STATUS_META, CenterNotFound
from .alerts import LEVEL_META, THRESHOLD_NOTE

REVIEW_VERSION = "history-review-v1"
MAX_NOTE_VERSIONS = 20
RECURRENCE_WINDOW_DAYS = 7
EVIDENCE_BEFORE_HOURS = 24

# 证据曲线指标（与设计稿观测证据标签一致；叶绿素a 为主指标）
EVIDENCE_VARIABLES: tuple[tuple[str, str, str], ...] = (
    ("chlorophyll_a", "叶绿素a", "μg/L"),
    ("water_temperature", "水温", "℃"),
    ("total_phosphorus", "总磷", "mg/L"),
    ("total_nitrogen", "总氮", "mg/L"),
    ("dissolved_oxygen", "溶解氧", "mg/L"),
)
EVIDENCE_CODES = [code for code, _, _ in EVIDENCE_VARIABLES]

# 人工复盘意见字段（与系统统计严格分离，前端必须标注"复盘意见"）
NOTE_TEXT_FIELDS = ("cause", "effective_measures", "problems", "threshold_adjustment", "plan_adjustment")

# 里程碑配色语义（设计稿第二节）：evidence=蓝 / risk=黄红 / human=青 / plan=紫 / muted=灰 / good=绿
RECORD_TONE: dict[str, str] = {
    "import": "evidence",
    "evidence": "evidence",
    "confirm": "human",
    "assign": "human",
    "start": "human",
    "submit_review": "human",
    "reopen": "human",
    "adopt_plan": "plan",
    "task": "plan",
    "escalate": "risk",
    "recovered": "good",
    "to_review": "good",
    "close": "good",
    "unverified": "muted",
    "revoke": "muted",
}
RECORD_TITLE: dict[str, str] = {
    "import": "历史告警导入预警中心",
    "evidence": "证据更新",
    "confirm": "人工确认预警",
    "assign": "指派负责人",
    "start": "开始处置",
    "submit_review": "提交复核",
    "reopen": "事件重新打开",
    "adopt_plan": "采用应急预案",
    "task": "措施任务进展",
    "escalate": "风险升级",
    "recovered": "指标恢复（转入待复核）",
    "to_review": "转入待复核",
    "close": "复核通过，事件关闭",
    "unverified": "站点退出快照，数据待核实",
    "revoke": "事件撤销",
}
# 记录动作中已由 pushes 单独成节点的（避免时间线重复）
RECORD_KIND_PUSH = "simulate_push"
NOTIFY_TONE = {
    "new_event": "risk",
    "escalation": "risk",
    "recovery": "good",
    "unverified": "muted",
    "process": "human",
    "push_failure": "muted",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _minutes_between(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round(max(0.0, (b - a).total_seconds() / 60.0), 1)


class HistoryReviewService:
    """事件复盘聚合：读预警中心 + 实时观测轨 + 复盘意见存储。"""

    def __init__(self, center, realtime, data_dir: Path | None = None) -> None:
        self.center = center
        self.realtime = realtime
        self._dir = Path(data_dir) if data_dir else center.store._dir
        self._lock = threading.RLock()

    # ---- 复盘意见存储（与事件数据分离落盘；编辑人/保存时间/版本） ----

    def _read_notes(self) -> dict[str, Any]:
        path = self._dir / "review-notes.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        notes = payload.get("notes")
        return notes if isinstance(notes, dict) else {}

    def _write_notes(self, notes: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / "review-notes.json"
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(
            json.dumps({"version": REVIEW_VERSION, "updated_at": _now_iso(), "notes": notes},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)

    def review_notes_for(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._read_notes().get(event_id)
            if not entry:
                return {"exists": False, "is_manual_review": True, "version": 0,
                        "saved_at": None, "editor": None, "fields": {}, "history": []}
            versions = entry.get("versions") or []
            latest = versions[-1] if versions else None
            return {
                "exists": bool(latest),
                "is_manual_review": True,
                "version": latest.get("version", 0) if latest else 0,
                "saved_at": latest.get("saved_at") if latest else None,
                "editor": latest.get("editor") if latest else None,
                "fields": (latest or {}).get("fields", {}),
                "history": [
                    {"version": v.get("version"), "saved_at": v.get("saved_at"), "editor": v.get("editor")}
                    for v in versions[-5:]
                ],
            }

    def save_review_notes(self, event_id: str, fields: dict[str, Any], editor: str | None = None) -> dict[str, Any]:
        with self._lock:
            self._event_or_404(event_id)
            clean: dict[str, Any] = {}
            for key in NOTE_TEXT_FIELDS:
                if key in fields:
                    value = fields.get(key)
                    clean[key] = str(value).strip() if value is not None else ""
            improvements = fields.get("improvements")
            if isinstance(improvements, list):
                clean["improvements"] = [
                    {
                        "item": str(row.get("item") or "").strip(),
                        "owner": str(row.get("owner") or "").strip(),
                        "due": str(row.get("due") or "").strip(),
                    }
                    for row in improvements
                    if isinstance(row, dict) and str(row.get("item") or "").strip()
                ]
            notes = self._read_notes()
            entry = notes.setdefault(event_id, {"versions": []})
            versions: list = entry.setdefault("versions", [])
            record = {
                "version": (versions[-1]["version"] + 1) if versions else 1,
                "saved_at": _now_iso(),
                "editor": (editor or "值班员").strip() or "值班员",
                "fields": clean,
            }
            versions.append(record)
            entry["versions"] = versions[-MAX_NOTE_VERSIONS:]
            self._write_notes(notes)
            return self.review_notes_for(event_id)

    # ---- 事件列表 ----

    def list_reviews(self, *, start: str = "", end: str = "", type: str = "all", level: str = "all",
                     status: str = "all", station: str = "", plan_adopted: str = "all",
                     tasks_done: str = "all", push_failed: str = "all") -> dict[str, Any]:
        self.center.bootstrap()
        events = self.center.store.list_events()
        briefs = [self._brief(event, events) for event in events]
        briefs.sort(key=lambda r: r.get("triggered_at") or r.get("created_at") or "", reverse=True)
        filtered = [row for row in briefs if self._match(row, start, end, type, level, status,
                                                         station, plan_adopted, tasks_done, push_failed)]
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "stats": self._reviews_stats(events),
            "total": len(filtered),
            "total_unfiltered": len(briefs),
            "events": filtered[:200],
            "filters": {
                "start": start, "end": end, "type": type, "level": level, "status": status,
                "station": station, "plan_adopted": plan_adopted,
                "tasks_done": tasks_done, "push_failed": push_failed,
            },
            "criteria": {
                "closed_rate": "关闭率 = 已关闭 / 全部事件（含撤销与处理中），分子分母显式展示",
                "durations": "时长按触发→确认/关闭计算；进行中事件不进入处置时长统计",
                "note": "事件关闭≠指标恢复；预案任务完成≠措施被证明有效",
            },
        }

    def _match(self, row: dict[str, Any], start: str, end: str, type: str, level: str, status: str,
               station: str, plan_adopted: str, tasks_done: str, push_failed: str) -> bool:
        day = (row.get("triggered_at") or row.get("created_at") or "")[:10]
        if start and (not day or day < start):
            return False
        if end and (not day or day > end):
            return False
        if type != "all" and row.get("type") != type:
            return False
        if level != "all" and row.get("level") != level:
            return False
        if status != "all" and row.get("status") != status:
            return False
        if station:
            key = station.strip().lower()
            hay = f"{row.get('station_name') or ''} {row.get('station_id') or ''}".lower()
            if key not in hay:
                return False
        if plan_adopted == "yes" and not row.get("plan_adopted"):
            return False
        if plan_adopted == "no" and row.get("plan_adopted"):
            return False
        if tasks_done == "yes" and not (row.get("tasks_total") and row["tasks_done"] == row["tasks_total"]):
            return False
        if tasks_done == "no" and (row.get("tasks_total") and row["tasks_done"] == row["tasks_total"]):
            return False
        if push_failed == "yes" and not row.get("push_failed"):
            return False
        if push_failed == "no" and row.get("push_failed"):
            return False
        return True

    def _brief(self, event: dict[str, Any], all_events: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = self._response_metrics(event, [e for e in all_events if e.get("id") != event.get("id")])
        plan = event.get("plan") or {}
        tasks = plan.get("tasks") or []
        pushes = event.get("pushes") or []
        evidence = event.get("evidence") or {}
        return {
            "id": event.get("id"),
            "no": event.get("no"),
            "type": event.get("type"),
            "level": event.get("level"),
            "title": event.get("title"),
            "station_id": event.get("station_id"),
            "station_name": event.get("station_name"),
            "province": event.get("province"),
            "status": event.get("status"),
            "status_label": EVENT_STATUS_META.get(event.get("status"), {}).get("label", event.get("status")),
            "assignee": event.get("assignee"),
            "evidence_state": evidence.get("state"),
            "value": evidence.get("value"),
            "unit": evidence.get("unit"),
            "threshold": evidence.get("threshold"),
            "triggered_at": evidence.get("triggered_at") or event.get("created_at"),
            "created_at": event.get("created_at"),
            "closed_at": event.get("closed_at"),
            "updated_at": event.get("updated_at"),
            "response_min": metrics["trigger_to_confirm"]["minutes"],
            "handling_min": metrics["total_handling"]["minutes"],
            "handling_ongoing": metrics["total_handling"]["ongoing"],
            "plan_adopted": bool(plan),
            "plan_name": plan.get("name"),
            "tasks_done": sum(1 for t in tasks if t.get("status") == "done"),
            "tasks_total": len(tasks),
            "push_success": sum(1 for p in pushes if p.get("status") == "simulated_success"),
            "push_failed": sum(1 for p in pushes if p.get("status") not in (None, "simulated_success")),
            "escalated": metrics["escalated"],
            "valid_recovery": metrics["valid_recovery"],
            "unverified_period": metrics["unverified_period"],
            "recurrence_count": metrics["recurrence"]["count"],
        }

    # ---- 全局统计（分子/分母显式，比例不做隐式取舍） ----

    def _reviews_stats(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(events)
        closed = [e for e in events if e.get("status") == "closed"]
        revoked = [e for e in events if e.get("status") == "revoked"]
        response_samples: list[float] = []
        handling_samples: list[float] = []
        for event in events:
            triggered = _parse_iso((event.get("evidence") or {}).get("triggered_at") or event.get("created_at"))
            confirmed = next(
                (_parse_iso(r.get("at")) for r in event.get("records") or [] if r.get("action") == "confirm"),
                None,
            )
            minutes = _minutes_between(triggered, confirmed)
            if minutes is not None:
                response_samples.append(minutes)
            if event.get("status") in ("closed", "revoked"):
                minutes = _minutes_between(triggered, _parse_iso(event.get("closed_at")))
                if minutes is not None:
                    handling_samples.append(minutes)
        return {
            "total": total,
            "by_type": {
                "realtime": sum(1 for e in events if e.get("type") == "realtime"),
                "predicted": sum(1 for e in events if e.get("type") == "predicted"),
            },
            "by_status": {
                status: sum(1 for e in events if e.get("status") == status) for status in EVENT_STATUS_META
            },
            "by_level": {
                level: sum(1 for e in events if e.get("level") == level) for level in ("light", "moderate")
            },
            "closed": {
                "num": len(closed),
                "den": total,
                "rate": round(len(closed) / total, 4) if total else None,
                "revoked": len(revoked),
                "open": total - len(closed) - len(revoked),
            },
            "avg_response_min": {
                "value": round(sum(response_samples) / len(response_samples), 1) if response_samples else None,
                "samples": len(response_samples),
                "basis": "首次触发 → 首次人工确认",
            },
            "avg_handling_min": {
                "value": round(sum(handling_samples) / len(handling_samples), 1) if handling_samples else None,
                "samples": len(handling_samples),
                "basis": "首次触发 → 关闭/撤销（仅已结束事件）",
            },
            "plan_adopted_events": sum(1 for e in events if e.get("plan")),
            "tasks_all_done_events": sum(
                1 for e in events
                if e.get("plan") and e["plan"].get("tasks")
                and all(t.get("status") == "done" for t in e["plan"]["tasks"])
            ),
            "push_failed_events": sum(
                1 for e in events
                if any(p.get("status") not in (None, "simulated_success") for p in e.get("pushes") or [])
            ),
            "escalated_events": sum(
                1 for e in events if any(r.get("action") == "escalate" for r in e.get("records") or [])
            ),
            "unverified_events": sum(
                1 for e in events if any(r.get("action") == "unverified" for r in e.get("records") or [])
            ),
            "recovered_events": sum(
                1 for e in events if any(r.get("action") == "recovered" for r in e.get("records") or [])
            ),
        }

    def history_metrics(self) -> dict[str, Any]:
        self.center.bootstrap()
        events = self.center.store.list_events()
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "stats": self._reviews_stats(events),
            "criteria": [
                "事件状态与证据状态分开统计：已关闭只表示处置流程结束，不等于指标已恢复",
                "比例均显示分子/分母；缺测、进行中事件不进入对应分母",
                "模拟推送成功不等于短信/邮件真实送达",
            ],
        }

    # ---- 事件复盘详情（聚合） ----

    def review_detail(self, event_id: str) -> dict[str, Any]:
        self.center.bootstrap()
        event = self._event_or_404(event_id)
        events = self.center.store.list_events()
        others = [e for e in events if e.get("id") != event_id]
        read_state = self.center.store.load_read_state()
        notifications = [
            self._notification_view(n, read_state)
            for n in self.center.store.list_notifications()
            if n.get("event_id") == event_id
        ]
        engine_alerts = self._engine_alert_map()
        has_forecast_link = bool(event.get("forecast_id") or event.get("prediction_run_id"))
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "event": {
                "id": event.get("id"),
                "no": event.get("no"),
                "type": event.get("type"),
                "level": event.get("level"),
                "level_label": LEVEL_META.get(event.get("level"), {}).get("label", event.get("level")),
                "title": event.get("title"),
                "station_id": event.get("station_id"),
                "station_name": event.get("station_name"),
                "province": event.get("province"),
                "status": event.get("status"),
                "status_label": EVENT_STATUS_META.get(event.get("status"), {}).get("label", event.get("status")),
                "assignee": event.get("assignee"),
                "evidence": event.get("evidence"),
                "rule_name": event.get("rule_name"),
                "engine_alert_id": event.get("engine_alert_id"),
                "engine_alert_ids": event.get("engine_alert_ids"),
                "created_at": event.get("created_at"),
                "updated_at": event.get("updated_at"),
                "closed_at": event.get("closed_at"),
                "acknowledged_at": event.get("acknowledged_at"),
                "recovered_at": event.get("recovered_at"),
            },
            "milestones": self._milestones(event, notifications, engine_alerts),
            "observed_evidence": self._observed_evidence(event),
            "forecast_evidence": None if not has_forecast_link else {"forecast_id": event.get("forecast_id")},
            "forecast_evidence_note": (
                None if has_forecast_link
                else "本事件无可验证的正式预测：预测规则未启用且无 forecast_id / prediction_run_id 关联，"
                     "不能用当前规则研判补充历史预测结果。"
            ),
            "plan_execution": self._plan_execution(event),
            "notifications": notifications,
            "pushes": list(event.get("pushes") or []),
            "response_metrics": self._response_metrics(event, others),
            "review_notes": self.review_notes_for(event_id),
            "records": self._records_view(event),
            "links": {
                "alert_center_event": f"/api/v1/realtime/alerts/center/events/{event_id}",
                "station_observations": (
                    f"/api/v1/spatial-entities/{event.get('station_id')}/observations?window=range"
                    if event.get("station_id") else None
                ),
                "station_quality": (
                    f"/api/v1/spatial-entities/{event.get('station_id')}/quality"
                    if event.get("station_id") else None
                ),
            },
        }

    def review_timeline(self, event_id: str) -> dict[str, Any]:
        detail_event = self._event_or_404(event_id)
        read_state = self.center.store.load_read_state()
        notifications = [
            self._notification_view(n, read_state)
            for n in self.center.store.list_notifications()
            if n.get("event_id") == event_id
        ]
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "event_id": event_id,
            "event_no": detail_event.get("no"),
            "milestones": self._milestones(detail_event, notifications, self._engine_alert_map()),
        }

    def review_evidence(self, event_id: str) -> dict[str, Any]:
        self.center.bootstrap()
        event = self._event_or_404(event_id)
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "event_id": event_id,
            "event_no": event.get("no"),
            "observed_evidence": self._observed_evidence(event),
        }

    def _event_or_404(self, event_id: str) -> dict[str, Any]:
        self.center.bootstrap()
        for event in self.center.store.list_events():
            if event.get("id") == event_id:
                return event
        raise CenterNotFound(event_id)

    def _engine_alert_map(self) -> dict[str, dict[str, Any]]:
        try:
            alerts = self.center.engine.store.list_alerts()
        except Exception:  # noqa: BLE001 — 引擎留痕缺失时退化用事件当前证据
            return {}
        return {a.get("id"): a for a in alerts if a.get("id")}

    def _notification_view(self, n: dict[str, Any], read_state: dict[str, str]) -> dict[str, Any]:
        return {
            "id": n.get("id"),
            "at": n.get("at"),
            "type": n.get("type"),
            "title": n.get("title"),
            "lines": list(n.get("lines") or []),
            "event_no": n.get("event_no"),
            "read": n.get("id") in read_state,
            "read_at": read_state.get(n.get("id")),
        }

    # ---- 里程碑（保留当时内容；颜色只表示节点性质） ----

    def _milestones(self, event: dict[str, Any], notifications: list[dict[str, Any]],
                    engine_alerts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        evidence = event.get("evidence") or {}

        if event.get("type") == "predicted":
            # 预测事件为预留类型：正式预测接入后在此补 预测发布/预测通知 节点
            nodes.append(self._node(
                event.get("created_at"), "forecast_publish", "evidence",
                "预测发布（正式预测批次）", event.get("title"), None,
                snapshot_id=None,
            ))

        # 触发节点：优先用引擎告警留痕的当时触发值，不用当前证据值覆盖历史。
        # 预测事件（预留类型）不走"实时观测达到阈值"口径，由预测发布节点表达。
        trigger_at = evidence.get("triggered_at") or event.get("created_at")
        engine_alert = engine_alerts.get(event.get("engine_alert_id")) or {}
        trigger_value = engine_alert.get("chla", evidence.get("value"))
        if event.get("type") != "predicted":
            nodes.append(self._node(
                trigger_at, "trigger", "risk",
                f"实时观测达到阈值：{evidence.get('indicator', '叶绿素a')} {trigger_value if trigger_value is not None else '缺测'}"
                f" {evidence.get('unit') or ''}（≥ {evidence.get('threshold')}）".replace("  ", " "),
                f"触发规则：{evidence.get('rule_name') or event.get('rule_name') or '—'}",
                trigger_value,
                snapshot_id=engine_alert.get("snapshot_id") or evidence.get("snapshot_id"),
            ))

        for n in notifications:
            nodes.append(self._node(
                n.get("at"), "notification", NOTIFY_TONE.get(n.get("type"), "human"),
                f"站内通知：{n.get('title')}",
                "；".join(n.get("lines") or []) + f"（铃铛通知{'已读' if n.get('read') else '未读'}；已读≠已确认事件）",
                None,
                snapshot_id=None,
                refs={"notification_id": n.get("id"), "notify_type": n.get("type")},
            ))

        for record in event.get("records") or []:
            action = record.get("action")
            if action == RECORD_KIND_PUSH:
                continue  # 由 pushes 生成更完整的节点
            tone = RECORD_TONE.get(action, "human")
            title = RECORD_TITLE.get(action, action or "处理记录")
            level_hint = ""
            if action == "escalate":
                new_level = (event.get("level") or "")
                level_hint = LEVEL_META.get(new_level, {}).get("label", new_level)
                title = f"风险升级（当前 {level_hint}）" if level_hint else title
            nodes.append(self._node(
                record.get("at"), action or "record", tone, title, record.get("detail"),
                None,
                snapshot_id=None,
                actor=record.get("actor"),
            ))

        for push in event.get("pushes") or []:
            failed = push.get("status") not in (None, "simulated_success")
            nodes.append(self._node(
                push.get("at"), "push", "muted" if failed else "human",
                f"模拟推送（{'短信' if push.get('channel') == 'sms' else '邮件'}）"
                f"{'失败' if failed else '成功'}",
                f"回执 {push.get('receipt_no') or '—'} · {push.get('reason') or ''}"
                "（模拟发送≠真实送达）",
                None,
                snapshot_id=None,
                actor=push.get("actor"),
                refs={"push_id": push.get("id"), "receipt_no": push.get("receipt_no")},
            ))

        # 同一动作/同一时间可能产生多个节点（如同一次模拟推送的短信+邮件回执共用时间戳），
        # 追加序号保证节点 ID 唯一：前端 v-for 以 id 为 key，重复会触发 diff 崩溃
        seen: dict[str, int] = {}
        for node in nodes:
            count = seen.get(node["id"], 0)
            seen[node["id"]] = count + 1
            if count:
                node["id"] = f"{node['id']}-{count + 1}"

        nodes.sort(key=lambda n: (_parse_iso(n["at"]) or datetime.max.replace(tzinfo=timezone.utc), n["id"]))
        return nodes

    @staticmethod
    def _node(at: str | None, kind: str, tone: str, title: str, detail: str | None,
              value: Any = None, *, snapshot_id: str | None = None,
              actor: str | None = None, refs: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "id": f"ms-{kind}-{str(at or 'na').replace(':', '').replace('.', '')}",
            "at": at,
            "kind": kind,
            "tone": tone,
            "title": title,
            "detail": detail,
            "value": value,
            "snapshot_id": snapshot_id,
            "actor": actor,
            "refs": refs or {},
        }

    # ---- 响应/处置指标（缺输入显式置空，不估算） ----

    def _response_metrics(self, event: dict[str, Any], others: list[dict[str, Any]]) -> dict[str, Any]:
        records = event.get("records") or []
        evidence = event.get("evidence") or {}
        triggered = _parse_iso(evidence.get("triggered_at") or event.get("created_at"))
        confirmed = next((_parse_iso(r.get("at")) for r in records if r.get("action") == "confirm"), None)
        started = next((_parse_iso(r.get("at")) for r in records if r.get("action") == "start"), None)
        closed_t = _parse_iso(event.get("closed_at"))
        now = datetime.now(timezone.utc)
        ongoing = event.get("status") not in ("closed", "revoked")

        plan = event.get("plan") or {}
        tasks = plan.get("tasks") or []
        done = sum(1 for t in tasks if t.get("status") == "done")
        pushes = event.get("pushes") or []
        station_id = event.get("station_id")
        similar = []
        if station_id and triggered:
            for other in others:
                if other.get("station_id") != station_id:
                    continue
                other_at = _parse_iso((other.get("evidence") or {}).get("triggered_at") or other.get("created_at"))
                if other_at and abs((other_at - triggered).total_seconds()) <= RECURRENCE_WINDOW_DAYS * 86400:
                    similar.append({"id": other.get("id"), "no": other.get("no"),
                                    "triggered_at": (other.get("evidence") or {}).get("triggered_at")})
        return {
            "trigger_to_confirm": {
                "minutes": _minutes_between(triggered, confirmed),
                "basis": "首次触发 → 首次人工确认",
            },
            "confirm_to_start": {
                "minutes": _minutes_between(confirmed, started),
                "basis": "首次确认 → 开始处置",
            },
            "total_handling": {
                "minutes": _minutes_between(triggered, closed_t) if not ongoing else None,
                "ongoing": ongoing,
                "basis": "首次触发 → 关闭/撤销" + ("；事件仍在处理中，暂不计总处置时长" if ongoing else ""),
            },
            "plan_tasks": {
                "done": done,
                "total": len(tasks),
                "completion_rate": round(done / len(tasks), 4) if tasks else None,
                "note": "任务完成≠预案措施被证明有效" if tasks else "本事件未采用预案",
            },
            "pushes": {
                "simulated_total": len(pushes),
                "success": sum(1 for p in pushes if p.get("status") == "simulated_success"),
                "failed": sum(1 for p in pushes if p.get("status") not in (None, "simulated_success")),
                "note": "模拟推送成功不等于短信/邮件真实送达",
            },
            "escalated": any(r.get("action") == "escalate" for r in records),
            "valid_recovery": bool(event.get("recovered_at")) or any(r.get("action") == "recovered" for r in records),
            "unverified_period": any(r.get("action") == "unverified" for r in records),
            "recurrence": {
                "window_days": RECURRENCE_WINDOW_DAYS,
                "count": len(similar),
                "events": similar,
                "basis": f"同站 {RECURRENCE_WINDOW_DAYS} 天内其他事件",
            },
        }

    # ---- 观测证据（事件前/中/后曲线 + 节点） ----

    def _observed_evidence(self, event: dict[str, Any]) -> dict[str, Any]:
        evidence = event.get("evidence") or {}
        station_id = event.get("station_id")
        if not station_id:
            return {"available": False, "reason": "事件无关联站点，无法拉取观测证据"}
        if self.realtime is None:
            return {"available": False, "reason": "实时观测轨未配置，无法拉取观测证据"}
        triggered = _parse_iso(evidence.get("triggered_at") or event.get("created_at"))
        if triggered is None:
            return {"available": False, "reason": "事件缺少触发时间，无法确定证据窗口"}
        end_dt = _parse_iso(event.get("closed_at")) or _parse_iso(event.get("updated_at")) or datetime.now(timezone.utc)
        start_dt = triggered - timedelta(hours=EVIDENCE_BEFORE_HOURS)
        end_dt = end_dt + timedelta(hours=2)
        try:
            rows = self.realtime.observations(
                station_id,
                window="range",
                start=start_dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
                end=end_dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
                variables=list(EVIDENCE_CODES),
            ) or []
        except Exception as exc:  # noqa: BLE001 — 证据缺失必须显式说明，不让复盘详情失败
            return {"available": False, "reason": f"观测证据读取失败：{exc}"}

        # 同一 (变量, 快照) 保留观测时间最新一行（与站点回放口径一致）
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row.get("variable_code"), row.get("snapshot_id"))
            prev = latest.get(key)
            if prev is None or str(row.get("observed_at")) > str(prev.get("observed_at")):
                latest[key] = row

        stamps: dict[tuple[str, str], dict[str, Any]] = {}
        for row in latest.values():
            key = (row.get("snapshot_id"), row.get("observed_at"))
            stamps.setdefault(key, {"snapshot_id": row.get("snapshot_id"), "observed_at": row.get("observed_at"),
                                    "retrieved_at": row.get("retrieved_at"), "values": {}, "missing": {}})
        series = sorted(stamps.values(), key=lambda p: str(p["observed_at"]))
        for point in series:
            for code, _, _ in EVIDENCE_VARIABLES:
                row = latest.get((code, point["snapshot_id"]))
                if row is None:
                    point["values"][code] = None
                    continue
                if row.get("observation_status") == "ok" and row.get("value") is not None:
                    point["values"][code] = row.get("value")
                else:
                    point["values"][code] = None
                    point["missing"][code] = row.get("missing_reason") or row.get("observation_status") or "缺测"

        chla_points = [p for p in series if p["snapshot_id"] and "chlorophyll_a" in p["values"]]
        missing_chla = sum(1 for p in series if p["missing"].get("chlorophyll_a"))
        return {
            "available": True,
            "station_id": station_id,
            "station_name": event.get("station_name"),
            "province": event.get("province"),
            "window": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "basis": f"首次触发前 {EVIDENCE_BEFORE_HOURS} 小时 → 事件结束（或当前）后 2 小时",
            },
            "indicators": [
                {"code": code, "label": label, "unit": unit} for code, label, unit in EVIDENCE_VARIABLES
            ],
            "series": series,
            "nodes": self._evidence_nodes(event),
            "thresholds": {
                "light": 10.0,
                "moderate": 25.0,
                "unit": "μg/L",
                "note": THRESHOLD_NOTE,
            },
            "coverage": {
                "total_points": len(series),
                "missing_chla_points": missing_chla,
                "note": "缺测位置曲线断开并标记原因，不插值；站点退出快照记待核实，不视为恢复",
            },
        }

    def _evidence_nodes(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        evidence = event.get("evidence") or {}
        nodes = [{
            "at": evidence.get("triggered_at") or event.get("created_at"),
            "type": "trigger",
            "label": "首次触发",
            "value": evidence.get("value"),
            "snapshot_id": evidence.get("snapshot_id"),
        }]
        for record in event.get("records") or []:
            if record.get("action") in ("escalate", "recovered", "unverified"):
                nodes.append({
                    "at": record.get("at"),
                    "type": record.get("action"),
                    "label": RECORD_TITLE.get(record.get("action"), record.get("action")),
                    "value": None,
                    "detail": record.get("detail"),
                    "snapshot_id": None,
                })
        return nodes

    # ---- 预案执行（读取采用时快照，不读预案库现值） ----

    def _plan_execution(self, event: dict[str, Any]) -> dict[str, Any]:
        plan = event.get("plan")
        if not plan:
            return {
                "adopted": False,
                "note": "本事件未采用应急预案（复盘不做事后推测）",
                "tasks": [], "tasks_done": 0, "tasks_total": 0, "completion_rate": None, "unfinished": [],
            }
        tasks = list(plan.get("tasks") or [])
        done = sum(1 for t in tasks if t.get("status") == "done")
        current = next(
            (p for p in self.center.store.list_plans() if p.get("id") == plan.get("plan_id")), None,
        )
        snapshot_texts = [t.get("text") for t in tasks]
        current_texts = [m.get("text") for m in (current or {}).get("measures") or []]
        changed = bool(current) and (
            current.get("version") != plan.get("version") or current_texts != snapshot_texts
        )
        return {
            "adopted": True,
            "plan_id": plan.get("plan_id"),
            "name": plan.get("name"),
            "version": plan.get("version"),
            "adopted_at": plan.get("adopted_at"),
            "tasks": tasks,
            "tasks_done": done,
            "tasks_total": len(tasks),
            "completion_rate": round(done / len(tasks), 4) if tasks else None,
            "unfinished": [t for t in tasks if t.get("status") != "done"],
            "plan_library_changed_after_adoption": {
                "changed": changed,
                "current_version": (current or {}).get("version"),
                "note": "复盘读取事件采用时保存的预案快照；预案库后续修改不覆盖本快照"
                        + ("；该预案在采用后已被修改" if changed else ""),
            },
        }

    # ---- 完整操作记录（可读内容 + 展开的技术编号） ----

    def _records_view(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for record in event.get("records") or []:
            rows.append({
                "at": record.get("at"),
                "actor": record.get("actor"),
                "action": record.get("action"),
                "detail": record.get("detail"),
                "event_no": event.get("no"),
            })
        rows.sort(key=lambda r: _parse_iso(r.get("at")) or datetime.max.replace(tzinfo=timezone.utc))
        return rows

    # ---- 预测评估（正式预测接入前的诚实空态） ----

    def prediction_evaluations(self) -> dict[str, Any]:
        self.center.bootstrap()
        rules = self.center.store.load_rules()
        predicted_enabled = bool((rules.get("predicted") or {}).get("enabled"))
        events = self.center.store.list_events()
        predicted_events = [e for e in events if e.get("type") == "predicted"]
        return {
            "version": REVIEW_VERSION,
            "generated_at": _now_iso(),
            "available": False,
            "capability_state": "awaiting_official_forecast",
            "message": (
                "正式预测尚未接入：预测规则" + ("已配置但尚无带 forecast_id 的预测事件" if predicted_enabled
                 else "未启用") + "，系统当前无法产生可验证的预测样本，因此不提供准确率统计。"
            ),
            "predicted_rule_enabled": predicted_enabled,
            "predicted_events": len(predicted_events),
            "verifiable": {
                "samples": 0,
                "excluded_missing_observation": 0,
                "excluded_failed_run": 0,
                "excluded_no_target_observation": 0,
                "note": "站点缺测、预测运行失败或目标时间无对应观测的数据不进入准确率分母，单独统计为不可验证",
            },
            "metrics": {
                "hit_rate": None, "miss_count": None, "false_alarm_count": None,
                "avg_lead_time_hours": None, "chla_mae": None, "chla_rmse": None,
                "chla_interval_coverage": None, "area_error": None,
                "brier_score": None, "reliability_curve": None,
            },
            "metric_definitions": [
                {"target": "叶绿素a / 蓝藻生物量", "metrics": "MAE、RMSE、预测区间覆盖率"},
                {"target": "水华面积", "metrics": "面积误差、空间重叠率"},
                {"target": "风险等级", "metrics": "命中率、漏报率、误报率"},
                {"target": "风险概率", "metrics": "Brier 分数、可靠性曲线"},
                {"target": "时间尺度", "metrics": "分别评价 1—3 天、7—15 天、30—90 天"},
            ],
            "criteria": [
                "预测评估只能使用预测发布之后取得的实测数据，防止把未来信息带入历史预测",
                "所有统计必须显示样本数与可验证条件",
                "接入条件：正式预测稳定提供 forecast_id 与 prediction_run_id 后启用",
            ],
        }


# 模块级单例：与 services.service / alert_center 共用同一份数据与引擎。
from .alert_center import alert_center as _center  # noqa: E402
from .services import service as _service  # noqa: E402

history_review = HistoryReviewService(center=_center, realtime=_service.realtime)
