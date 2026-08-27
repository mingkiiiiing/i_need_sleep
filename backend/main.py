"""FastAPI 服务：驾驶舱接口与后续数据接入的稳定边界。"""
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="蓝藻水华监测预警系统 API", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def ok(data: Any) -> dict[str, Any]:
    return {"code": 200, "message": "success", "data": data}


class IngestRequest(BaseModel):
    """未来 JSON/向量数据库统一接入格式。"""
    source_type: Literal["water_quality", "weather", "hydrology", "remote_sensing", "vector"]
    records: list[dict[str, Any]] = Field(min_length=1)
    source_name: str = "manual-import"


class PredictRequest(BaseModel):
    station_id: str
    horizon_days: Literal[1, 3, 7, 15, 30] = 3
    features: dict[str, float] | None = None


class AlertActionRequest(BaseModel):
    action: Literal["confirm", "assign", "start", "push", "resolve", "close"]
    actor: str = "当前用户"
    owner: str | None = None


class DataRepository:
    """演示数据仓库；真实数据到位后替换为 JSON/数据库实现，路由无需变更。"""
    stages = [
        {"key": "t1", "label": "未来 1 天", "short": "1 天", "days": 1, "index": 0},
        {"key": "t3", "label": "未来 3 天", "short": "3 天", "days": 3, "index": 1},
        {"key": "t7", "label": "未来 7 天", "short": "7 天", "days": 7, "index": 2},
        {"key": "t15", "label": "未来 15 天", "short": "15 天", "days": 15, "index": 3},
        {"key": "t30", "label": "未来 30 天", "short": "30 天", "days": 30, "index": 4},
    ]
    specs = [
        ("northwest_hotspot", "西北热点区", "NW-01", "红色预警", "high", [88, 76, 72, 64], ["1.25e6 cells/L", "42.8 ug/L", "0.091 mg/L", "29.6 ℃"]),
        ("central_lake", "湖心浮标", "CN-02", "橙色关注", "mid", [72, 68, 54, 46], ["8.5e5 cells/L", "18.9 ug/L", "0.063 mg/L", "28.4 ℃"]),
        ("river_inlet", "入湖河口", "RI-03", "橙色关注", "mid", [84, 71, 58, 49], ["9.4e5 cells/L", "24.6 ug/L", "0.082 mg/L", "27.8 ℃"]),
        ("southeast_station", "东南监测站", "SE-04", "绿色稳定", "low", [48, 42, 36, 32], ["4.7e5 cells/L", "11.4 ug/L", "0.041 mg/L", "26.9 ℃"]),
        ("water_intake", "取水口", "WI-05", "绿色稳定", "low", [66, 59, 35, 33], ["5.0e5 cells/L", "14.2 ug/L", "0.048 mg/L", "27.1 ℃"]),
        ("south_channel", "南部通道", "SC-06", "橙色关注", "mid", [77, 63, 42, 37], ["7.4e5 cells/L", "17.3 ug/L", "0.058 mg/L", "27.6 ℃"]),
    ]
    positions = {"northwest_hotspot": {"top": "24%", "left": "22%"}, "river_inlet": {"top": "62%", "left": "12%"}, "southeast_station": {"top": "72%", "left": "78%"}, "central_lake": {"top": "45%", "left": "52%"}, "water_intake": {"top": "30%", "left": "84%"}, "south_channel": {"top": "82%", "left": "40%"}}

    def points(self) -> dict[str, dict[str, Any]]:
        names = ["水温", "风速", "营养盐", "历史聚集惯性"]
        data = {}
        for index, (sid, name, short, risk, risk_class, values, metrics) in enumerate(self.specs):
            data[sid] = {
                "id": sid, "name": name, "short": short, "risk": risk, "riskClass": risk_class,
                "summary": f"{name}是湖区重要监测点位，当前由水质、气象和水动力因子共同驱动，建议按预警档位滚动复核。",
                "metrics": dict(zip(["density", "chla", "phosphorus", "temp"], metrics)),
                "forecast": {"window": ["未来 1 天", "未来 3 天", "未来 7 天", "未来 15 天", "未来 30 天"], "title": ["紧急研判", "短期预警", "中期趋势", "长期推演", "综合复盘"], "text": [f"{name}未来 {day} 天预测已生成，请结合现场监测数据滚动校准。" for day in [1, 3, 7, 15, 30]]},
                "factors": [{"name": names[i], "value": value, "unit": "%"} for i, value in enumerate(values)],
                "trend": [max(8, values[0] - 42 + ((day * 7 + index * 5) % 28)) for day in range(24)],
                "timeline": [["08-21 09:00", "数据入库", "完成质量校验并进入融合模型。"], ["08-21 10:00", "风险研判", "机理模型与 AI 模型输出已对齐。"]],
                "explainability": [{"driver": names[i], "contribution": round(value / 300, 2), "direction": "负" if i == 1 else "正"} for i, value in enumerate(values)],
            }
        return data

    def heat_fields(self) -> dict[str, list[list[int]]]:
        output = {}
        for stage in self.stages:
            x, y = [(4, 2), (5, 3), (7, 4), (9, 5), (10, 5)][stage["index"]]
            output[stage["key"]] = [[max(8, min(96, round(92 - (abs(col - x) + abs(row - y) * 1.4) * 10 - stage["index"] * 3))) for col in range(19)] for row in range(11)]
        return output

    def events(self) -> list[dict[str, str]]:
        station_ids = list(self.points())
        return [{"id": f"e{i + 1}", "time": f"08-{16 + i:02d} 09:00", "stageKey": self.stages[i % 5]["key"], "point": station_ids[i % len(station_ids)], "title": "风险研判事件", "summary": "多源观测数据完成质控，系统已更新预警结果。", "severity": ["low", "mid", "high"][i % 3]} for i in range(15)]

    def alerts(self) -> list[dict[str, Any]]:
        base = [
            ("AL202505200015", "贡湖湾叶绿素 a 高风险", "太湖 / 贡湖湾 / 西北热点区", "northwest_hotspot", "high", "new", "10:15", 58.7, 40.0, 82, "未指派"),
            ("AL202505200014", "梅梁湖叶绿素 a 关注", "太湖 / 梅梁湖 / 湖心浮标", "central_lake", "mid", "processing", "09:52", 44.2, 40.0, 68, "处置组"),
            ("AL202505200013", "蠡湖入湖总磷超标", "太湖 / 蠡湖 / 入湖河口", "river_inlet", "high", "processing", "09:41", 0.112, 0.08, 76, "处置组"),
            ("AL202505200012", "长广溪叶绿素 a 早期聚集", "太湖 / 长广溪 / 南部通道", "south_channel", "mid", "assigned", "09:28", 36.8, 40.0, 54, "巡查组"),
            ("AL202505200011", "东太湖叶绿素 a 稳定", "太湖 / 东太湖 / 东南监测站", "southeast_station", "low", "resolved", "08:55", 22.4, 40.0, 31, "监测组"),
        ]
        status_index = {"new": 0, "confirmed": 1, "assigned": 1, "processing": 2, "resolved": 3, "closed": 4}
        factors = [[("水温偏高", 38), ("总磷浓度偏高", 28), ("风速降低", 18)], [("水温偏高", 32), ("水动力减弱", 24), ("营养盐累积", 16)], [("上游来水增加", 36), ("降雨冲刷", 27), ("交换流减弱", 15)], [("水温偏高", 28), ("风速降低", 19), ("交换流减弱", 13)], [("水温偏高", 18), ("历史聚集惯性", 12), ("风场稳定", 8)]]
        output = []
        for index, (alert_id, title, area, point, severity, status, alert_time, value, threshold, probability, owner) in enumerate(base):
            metric = "总磷" if alert_id.endswith("13") else "叶绿素 a"
            unit = "mg/L" if metric == "总磷" else "μg/L"
            trend = {
                "AL202505200015": [39.8, 41.2, 43.6, 46.1, 49.8, 54.3, 58.7],
                "AL202505200014": [35.1, 36.4, 37.8, 39.2, 40.8, 42.5, 44.2],
                "AL202505200013": [0.071, 0.075, 0.079, 0.084, 0.091, 0.101, 0.112],
                "AL202505200012": [29.3, 30.1, 31.4, 32.6, 33.8, 35.2, 36.8],
                "AL202505200011": [27.6, 26.8, 25.9, 24.8, 24.1, 23.2, 22.4],
            }[alert_id]
            lake = area.split(" / ")[1]
            task_defs = [
                ("monitor", f"{lake}加密监测（每3小时）", "监测组", "05-20 13:00", True),
                ("inspect", f"复核{lake}藻情与现场样品", "巡查组", "05-20 12:00", index < 3),
                ("control", f"评估{lake}生态控藻措施（按规范）", "处置组", "05-20 16:00", index == 0),
                ("device", f"核查{lake}应急设备状态", "运维组", "05-20 14:00", False),
                ("public", f"发布{lake}风险提示", "宣传组", "05-20 15:00", False),
            ]
            flow_labels = ["新预警", "已确认", "处理中", "已解决", "已关闭"]
            current = status_index[status]
            flow = [{"label": label, "time": alert_time if step == 0 else "—", "done": step <= current} for step, label in enumerate(flow_labels)]
            output.append({
                "id": alert_id, "title": title, "area": area, "point": point, "severity": severity, "status": status,
                "time": alert_time, "date": "2025-05-20", "metric": metric, "value": value, "unit": unit,
                "threshold": threshold, "exceedance": round(value / threshold, 2), "probability": probability, "trend": trend,
                "source": f"{area.split(' / ')[1]}监测站 + 湖面风场", "model": "太湖蓝藻风险预测模型 v2.3", "updatedAt": "2025-05-20 09:50",
                "confidence": "较高" if probability >= 70 else "中等", "owner": owner, "responseTime": "18分钟" if index else "—",
                "factors": [{"name": name, "value": contribution} for name, contribution in factors[index]], "flow": flow,
                "plan": {"name": f"{area.split(' / ')[1]}蓝藻监测应急预案（{'III' if severity == 'high' else 'II' if severity == 'mid' else 'I'}级）", "match": 92 - index * 6, "target": "蓝藻水华风险、叶绿素 a / 总磷异常与局地聚集", "tasks": [{"id": task_id, "label": label, "owner": task_owner, "due": due, "checked": checked} for task_id, label, task_owner, due, checked in task_defs], "updatedAt": "2025-04-18"},
                "records": [{"time": f"2025-05-20 {alert_time}", "node": "新预警", "content": "系统自动生成预警", "actor": "系统", "note": f"预测值{value} {unit}，概率{probability}%"}],
                "audit": [{"time": f"2025-05-20 {alert_time}:32", "actor": "系统", "content": f"生成预警（{alert_id}）", "result": "成功", "ip": "10.0.1.10"}],
            })
        return output

    def summary(self) -> dict[str, Any]:
        points = self.points()
        return {"totalStations": len(points), "riskCounts": {"high": 1, "mid": 3, "low": 2}, "intensity": {sid: {stage["key"]: min(98, point["factors"][0]["value"] - stage["index"] * 5) for stage in self.stages} for sid, point in points.items()}}


repository = DataRepository()
ingested_batches: list[dict[str, Any]] = []
alerts_state = repository.alerts()

@app.get("/")
async def root(): return ok({"name": "蓝藻水华监测预警系统 API", "docs": "/docs", "version": app.version})

@app.get("/api/health")
async def health(): return ok({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "dataMode": "demo"})

@app.get("/api/v1/cockpit/time-stages")
async def time_stages(): return ok(repository.stages)

@app.get("/api/v1/cockpit/points")
async def points(): return ok({"pointData": repository.points(), "pointPositions": repository.positions})

@app.get("/api/v1/cockpit/points/{station_id}")
async def point(station_id: str):
    result = repository.points().get(station_id)
    if not result: raise HTTPException(status_code=404, detail="station_id 不存在")
    return ok(result)

@app.get("/api/v1/cockpit/risk-heatmap")
async def risk_heatmap(): return ok(repository.heat_fields())

@app.get("/api/v1/cockpit/events")
async def events(): return ok(repository.events())

@app.get("/api/v1/cockpit/alerts")
async def alerts(): return ok(alerts_state)

@app.post("/api/v1/cockpit/alerts/{alert_id}/actions")
async def alert_actions(alert_id: str, payload: AlertActionRequest):
    alert = next((item for item in alerts_state if item["id"] == alert_id), None)
    if not alert: raise HTTPException(status_code=404, detail="alert_id 不存在")
    labels = {"confirm": "确认预警", "assign": "指派处置", "start": "开始处置", "push": "模拟推送", "resolve": "标记已解决", "close": "关闭预警"}
    transitions = {"confirm": "confirmed", "assign": "assigned", "start": "processing", "resolve": "resolved", "close": "closed"}
    if payload.action in transitions: alert["status"] = transitions[payload.action]
    if payload.action in {"assign", "start"}: alert["owner"] = payload.owner or "处置组"
    if payload.action == "push" and alert["status"] == "new": alert["status"] = "confirmed"
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    current = {"new": 0, "confirmed": 1, "assigned": 1, "processing": 2, "resolved": 3, "closed": 4}[alert["status"]]
    for index, step in enumerate(alert["flow"]):
        step["done"] = index <= current
        if step["done"] and step["time"] == "—": step["time"] = now[11:16]
    alert["records"].insert(0, {"time": now, "node": labels[payload.action], "content": labels[payload.action], "actor": payload.actor, "note": "操作已写入处置记录"})
    alert["audit"].insert(0, {"time": now, "actor": payload.actor, "content": labels[payload.action], "result": "成功", "ip": "10.0.1.23"})
    return ok(alert)

@app.get("/api/v1/cockpit/region-summary")
async def region_summary(): return ok(repository.summary())

@app.post("/api/v1/data/ingest", status_code=201)
async def ingest(payload: IngestRequest):
    batch = {"batchId": f"B{len(ingested_batches) + 1:04d}", "sourceType": payload.source_type, "sourceName": payload.source_name, "recordCount": len(payload.records), "receivedAt": datetime.now(timezone.utc).isoformat()}
    ingested_batches.append(batch)
    return ok(batch)

@app.post("/api/v1/model/predict")
async def predict(payload: PredictRequest):
    point_data = repository.points().get(payload.station_id)
    if not point_data: raise HTTPException(status_code=404, detail="station_id 不存在")
    stage = next(stage for stage in repository.stages if stage["days"] == payload.horizon_days)
    score = repository.summary()["intensity"][payload.station_id][stage["key"]]
    return ok({"stationId": payload.station_id, "horizonDays": payload.horizon_days, "riskScore": score, "riskLevel": "high" if score >= 75 else "mid" if score >= 45 else "low", "model": "mechanism-ai-cascade-demo", "confidenceInterval": [max(0, score - 8), min(100, score + 8)], "featureContributions": point_data["explainability"]})
