from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import random

# ============================================================
# 1. 创建应用实例
# ============================================================
app = FastAPI(
    title="蓝藻水华监测预警系统 API",
    description="Mock 版本 - 用于前后端联调",
    version="1.0.0"
)

# ============================================================
# 2. 跨域配置（让前端能够调用）
# ============================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 3. 统一返回格式封装
# ============================================================
def success_response(data):
    return {
        "code": 200,
        "msg": "success",
        "data": data
    }

def error_response(msg: str, code: int = 400):
    return {
        "code": code,
        "msg": msg,
        "data": None
    }

# ============================================================
# 4. 请求模型定义（Pydantic）
# ============================================================
class PredictRequest(BaseModel):
    station_id: str
    target_metric: str = "chlorophyll_a"  # chlorophyll_a / algae_density / bloom_area / risk_level
    forecast_scale: str = "short_term"    # short_term / mid_term / long_term

class ExplainRequest(BaseModel):
    prediction_id: str  # 预测记录ID，用于查询对应的解释数据

# ============================================================
# 5. 模拟数据生成器（辅助函数）
# ============================================================
def generate_sites():
    """生成模拟站点数据"""
    sites = [
        {"id": "S001", "name": "太湖-贡湖湾", "lat": 31.42, "lng": 120.31, "risk_level": "high"},
        {"id": "S002", "name": "太湖-梅梁湖", "lat": 31.48, "lng": 120.18, "risk_level": "medium"},
        {"id": "S003", "name": "巢湖-湖心区", "lat": 31.60, "lng": 117.38, "risk_level": "low"},
        {"id": "S004", "name": "巢湖-西半湖", "lat": 31.55, "lng": 117.28, "risk_level": "medium"},
        {"id": "S005", "name": "滇池-草海", "lat": 24.98, "lng": 102.68, "risk_level": "high"},
        {"id": "S006", "name": "滇池-外海北", "lat": 24.92, "lng": 102.72, "risk_level": "low"},
        {"id": "S007", "name": "白洋淀-烧车淀", "lat": 38.92, "lng": 115.98, "risk_level": "medium"},
        {"id": "S008", "name": "洱海-北部", "lat": 25.85, "lng": 100.25, "risk_level": "low"},
    ]
    return sites

def generate_trend_data(days=7, base_value=30):
    """生成近N天的趋势数据"""
    result = []
    today = datetime.now().date()
    for i in range(days, 0, -1):
        date = today - timedelta(days=i)
        # 随机波动
        value = base_value + random.uniform(-10, 15)
        result.append({
            "date": date.strftime("%Y-%m-%d"),
            "value": round(value, 2)
        })
    return result

def generate_predict_metrics():
    """生成多指标预测数据"""
    return [
        {"metric_code": "chlorophyll_a", "metric_name": "叶绿素a", "value": round(random.uniform(25, 55), 2), "unit": "μg/L"},
        {"metric_code": "algae_density", "metric_name": "藻密度", "value": int(random.uniform(5000000, 12000000)), "unit": "cells/L"},
        {"metric_code": "bloom_area", "metric_name": "水华面积", "value": round(random.uniform(1.5, 5.5), 2), "unit": "km²"},
    ]

def generate_warnings(count=5):
    """生成预警列表"""
    levels = ["high", "medium", "low"]
    level_names = {"high": "高风险", "medium": "中风险", "low": "低风险"}
    sites = generate_sites()
    result = []
    for i in range(count):
        site = random.choice(sites)
        level = random.choice(levels)
        now = datetime.now()
        result.append({
            "warning_id": f"W{now.strftime('%Y%m%d%H%M%S')}{i:03d}",
            "time": (now - timedelta(hours=random.randint(1, 48))).strftime("%Y-%m-%d %H:%M"),
            "station_id": site["id"],
            "station_name": site["name"],
            "risk_level": level,
            "risk_level_name": level_names[level],
            "trigger_factor": random.choice(["水温异常升高", "总磷超标", "连续高温", "风速偏低", "光照充足"]),
            "status": random.choice(["待处理", "处理中", "已处置"])
        })
    return result

# ============================================================
# 6. 核心接口实现
# ============================================================

# ---------- 6.1 健康检查 ----------
@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return success_response({"status": "ok", "timestamp": datetime.now().isoformat()})

# ---------- 6.2 获取站点列表 ----------
@app.get("/api/sites")
async def get_sites():
    """获取所有监测站点列表"""
    sites = generate_sites()
    return success_response(sites)

# ---------- 6.3 驾驶舱总览 ----------
@app.get("/api/dashboard/overview")
async def get_dashboard_overview():
    """获取驾驶舱总览数据"""
    sites = generate_sites()
    # 统计各风险等级数量
    risk_count = {"high": 0, "medium": 0, "low": 0}
    for site in sites:
        risk_count[site["risk_level"]] += 1
    
    warnings = generate_warnings(5)
    
    return success_response({
        "summary": {
            "total_sites": len(sites),
            "high_risk_count": risk_count["high"],
            "medium_risk_count": risk_count["medium"],
            "low_risk_count": risk_count["low"],
            "total_warnings": len(warnings),
            "avg_chlorophyll": round(random.uniform(30, 45), 2),
            "avg_algae_density": int(random.uniform(6000000, 10000000))
        },
        "trend": generate_trend_data(7, 35),
        "recent_warnings": warnings[:5]
    })

# ---------- 6.4 模型预测（核心接口） ----------
@app.post("/api/predict")
async def get_prediction(request: PredictRequest):
    """获取模型预测结果（支持多模型对比）"""
    
    # 模拟不同模型的结果
    base_mechanism = random.uniform(30, 50)
    base_ai1 = base_mechanism + random.uniform(-3, 8)
    base_ai2 = base_mechanism + random.uniform(-2, 10)
    base_fusion = max(base_mechanism, base_ai1, base_ai2) + random.uniform(3, 10)
    
    # 计算提升比例
    best_single = max(base_mechanism, base_ai1, base_ai2)
    improvement = round(((base_fusion - best_single) / best_single) * 100, 1)
    
    # 风险等级映射
    risk_levels = ["low", "medium", "high"]
    risk_weights = [0.2, 0.4, 0.4]  # 随机权重
    selected_risk = random.choices(risk_levels, weights=risk_weights)[0]
    
    # 生成未来3天的预测结果
    results = []
    today = datetime.now().date()
    for i in range(1, 4):  # 1-3天
        date = today + timedelta(days=i)
        metrics = generate_predict_metrics()
        results.append({
            "date": date.strftime("%Y-%m-%d"),
            "metrics": metrics,
            "risk_level": random.choices(risk_levels, weights=risk_weights)[0],
            "risk_probability": round(random.uniform(0.3, 0.95), 3)
        })
    
    return success_response({
        "station_id": request.station_id,
        "forecast_scale": request.forecast_scale,
        "target_metric": request.target_metric,
        "results": results,
        "model_comparison": {
            "mechanism_model": round(base_mechanism, 2),
            "ai_model_1": round(base_ai1, 2),
            "ai_model_2": round(base_ai2, 2),
            "fusion_model": round(base_fusion, 2),
            "improvement": f"{improvement}%"
        },
        "evaluation": {
            "r2": round(random.uniform(0.75, 0.92), 3),
            "rmse": round(random.uniform(2.5, 6.5), 2),
            "mae": round(random.uniform(1.8, 4.5), 2)
        }
    })

# ---------- 6.5 可解释性分析 ----------
@app.post("/api/explain")
async def get_explanation(request: ExplainRequest):
    """获取可解释性分析数据（SHAP/特征贡献度）"""
    
    factors = [
        {"name": "水温", "contribution": round(random.uniform(-20, 40), 2), "impact": "positive" if random.random() > 0.5 else "negative"},
        {"name": "总磷", "contribution": round(random.uniform(-15, 35), 2), "impact": "positive" if random.random() > 0.5 else "negative"},
        {"name": "氨氮", "contribution": round(random.uniform(-10, 25), 2), "impact": "positive" if random.random() > 0.5 else "negative"},
        {"name": "风速", "contribution": round(random.uniform(-25, 10), 2), "impact": "negative" if random.random() > 0.5 else "positive"},
        {"name": "光照", "contribution": round(random.uniform(-10, 30), 2), "impact": "positive" if random.random() > 0.5 else "negative"},
        {"name": "流速", "contribution": round(random.uniform(-30, 5), 2), "impact": "negative" if random.random() > 0.5 else "positive"},
    ]
    
    # 按贡献度绝对值排序
    factors.sort(key=lambda x: abs(x["contribution"]), reverse=True)
    
    # 生成置信区间
    predicted_value = random.uniform(30, 55)
    confidence_interval = {
        "lower": round(predicted_value - random.uniform(3, 10), 2),
        "upper": round(predicted_value + random.uniform(3, 10), 2),
        "confidence_level": 0.95
    }
    
    # 生成风险概率分布
    risk_distribution = {
        "low": round(random.uniform(0.05, 0.25), 2),
        "medium": round(random.uniform(0.20, 0.45), 2),
        "high": round(random.uniform(0.30, 0.70), 2)
    }
    
    # 自动生成原因说明
    top_positive = [f for f in factors if f["impact"] == "positive"][:2]
    top_negative = [f for f in factors if f["impact"] == "negative"][:2]
    reason = f"本次预测风险主要由 {top_positive[0]['name']}（贡献 {top_positive[0]['contribution']}%）"
    if len(top_positive) > 1:
        reason += f" 和 {top_positive[1]['name']}（贡献 {top_positive[1]['contribution']}%）"
    reason += " 升高导致"
    if top_negative:
        reason += f"，同时 {top_negative[0]['name']} 的降低进一步加剧了风险"
    
    return success_response({
        "prediction_id": request.prediction_id,
        "feature_importance": factors,
        "confidence_interval": confidence_interval,
        "risk_probability_distribution": risk_distribution,
        "interpretation": reason,
        "sensitivity_curve": [
            {"factor": "水温", "values": [20, 22, 24, 26, 28, 30], "response": [15, 22, 30, 42, 55, 68]},
            {"factor": "总磷", "values": [0.1, 0.15, 0.2, 0.25, 0.3], "response": [20, 28, 38, 52, 65]}
        ]
    })

# ---------- 6.6 风险地图数据 ----------
@app.get("/api/map/risk")
async def get_map_risk():
    """获取风险地图热力图数据"""
    # 生成网格点数据（模拟湖库区域）
    grid_points = []
    # 太湖区域大致经纬度范围
    for lat in [31.35, 31.40, 31.45, 31.50, 31.55, 31.60]:
        for lng in [120.10, 120.15, 120.20, 120.25, 120.30, 120.35, 120.40]:
            grid_points.append({
                "lat": round(lat + random.uniform(-0.02, 0.02), 4),
                "lng": round(lng + random.uniform(-0.02, 0.02), 4),
                "risk_value": round(random.uniform(0.1, 0.95), 3),
                "chlorophyll": round(random.uniform(10, 70), 2)
            })
    
    return success_response({
        "region": "太湖",
        "grid_points": grid_points,
        "timestamp": datetime.now().isoformat()
    })

# ---------- 6.7 预警列表 ----------
@app.get("/api/warnings")
async def get_warnings(limit: int = 20, status: Optional[str] = None):
    """获取预警列表"""
    warnings = generate_warnings(limit)
    
    # 如果指定了状态，进行过滤
    if status:
        warnings = [w for w in warnings if w["status"] == status]
    
    return success_response({
        "total": len(warnings),
        "list": warnings
    })

# ---------- 6.8 预警处置（模拟推送） ----------
@app.post("/api/warnings/{warning_id}/handle")
async def handle_warning(warning_id: str):
    """处理预警（模拟短信/邮件推送）"""
    return success_response({
        "warning_id": warning_id,
        "action": "模拟推送",
        "result": "推送成功",
        "pushed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "channels": ["短信", "邮件"]
    })

# ---------- 6.9 历史回溯/时间轴数据 ----------
@app.get("/api/timeline")
async def get_timeline_data(start_date: str, end_date: str):
    """获取时间轴数据（用于历史回溯和未来预演）"""
    # 解析日期
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
    
    days = (end - start).days + 1
    if days > 90:
        days = 90
    
    result = []
    for i in range(days):
        current_date = start + timedelta(days=i)
        result.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "avg_chlorophyll": round(random.uniform(20, 60), 2),
            "risk_level": random.choice(["low", "medium", "high"]),
            "bloom_area": round(random.uniform(0.5, 6.0), 2)
        })
    
    return success_response({
        "start_date": start_date,
        "end_date": end_date,
        "total_days": len(result),
        "data": result
    })

# ============================================================
# 7. 根路径
# ============================================================
@app.get("/")
async def root():
    return {
        "message": "蓝藻水华监测预警系统 API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


# ============================================================
# 8. 启动命令（注释保留）
# ============================================================
# 终端执行：
# uvicorn main:app --reload