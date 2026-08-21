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


class DataRepository:
    """演示数据仓库；真实数据到位后替换为 JSON/数据库实现，路由无需变更。"""
    stages = [
        {"key": "t1", "label": "T+1 天", "short": "T+1d", "days": 1, "index": 0},
        {"key": "t3", "label": "T+3 天", "short": "T+3d", "days": 3, "index": 1},
        {"key": "t7", "label": "T+7 天", "short": "T+7d", "days": 7, "index": 2},
        {"key": "t15", "label": "T+15 天", "short": "T+15d", "days": 15, "index": 3},
        {"key": "t30", "label": "T+30 天", "short": "T+30d", "days": 30, "index": 4},
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

    def summary(self) -> dict[str, Any]:
        points = self.points()
        return {"totalStations": len(points), "riskCounts": {"high": 1, "mid": 3, "low": 2}, "intensity": {sid: {stage["key"]: min(98, point["factors"][0]["value"] - stage["index"] * 5) for stage in self.stages} for sid, point in points.items()}}


repository = DataRepository()
ingested_batches: list[dict[str, Any]] = []

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
