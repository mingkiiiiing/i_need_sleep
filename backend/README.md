# 后端联调说明

当前为 **P0 演示数据联调阶段**：所有 API 响应都显式携带 `data_mode=simulated`、数据版本和 `simulation_only` 声明，不得用于真实监管或预警决策。

## 启动

在项目根目录执行：

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

启动后访问 `http://127.0.0.1:8000/docs` 查看和调试接口。前端默认请求 `/api/v1`（由 Vite 代理到后端）；后端异常会直接暴露错误，避免静默切换到另一份 mock。仅在 `.env.local` 显式设置 `VITE_USE_MOCK=true` 时才使用本地 mock。

## 驾驶舱接口

所有接口响应均为：

```json
{ "code": 200, "message": "success", "data": {} }
```

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/cockpit/time-stages` | 未来 1 / 3 / 7 / 15 / 30 天档位 |
| `GET /api/v1/cockpit/points` | 站点详情及地图相对坐标 |
| `GET /api/v1/cockpit/points/{station_id}` | 单站详情 |
| `GET /api/v1/cockpit/risk-heatmap` | 5 个档位的 11×19 风险网格 |
| `GET /api/v1/cockpit/events` | 历史回放事件流 |
| `GET /api/v1/cockpit/region-summary` | 站点汇总及分档风险强度 |

核心业务契约还包括：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/system/capabilities` | 能力边界与外部阻塞项 |
| `GET /api/v1/datasets/summary` | 演示数据版本与范围 |
| `GET /api/v1/spatial-entities` | 区分真实站点与 `demo_zone` |
| `GET /api/v1/spatial-entities/{id}/observations` | 带质量和来源的观测记录 |
| `GET /api/v1/forecasts` | 1—15 天演示预测；30—90 天返回能力阻塞 |
| `GET /api/v1/map/risk-grid` | 演示风险格网与空间分辨率 |

## 数据接入约定

数据同学交付 JSON 时，先调用 `POST /api/v1/data/ingest`。每条记录的业务字段不受限，但建议统一包含 `station_id`、`observed_at`、`latitude`、`longitude` 和测量值；向量数据可用 `source_type: "vector"`。

```json
{
  "source_type": "water_quality",
  "source_name": "太湖自动监测站",
  "records": [
    {
      "station_id": "northwest_hotspot",
      "observed_at": "2026-08-21T08:00:00+08:00",
      "chlorophyll_a": 42.8,
      "total_phosphorus": 0.091,
      "water_temperature": 29.6
    }
  ]
}
```

`POST /api/v1/model/predict` 已定义预测调用契约，当前为可复现的演示模型输出；后续将由训练模型替换实现，接口字段保持不变。
