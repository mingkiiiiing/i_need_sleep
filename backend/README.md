# 后端联调说明

## 启动

在项目根目录执行：

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

启动后访问 `http://127.0.0.1:8000/docs` 查看和调试接口。前端无需改地址：默认请求 `http://127.0.0.1:8000/api/v1`；后端未启动时自动回退本地 mock。若要始终只用 mock，在前端 `.env.local` 中设置 `VITE_USE_MOCK=true`。

## 驾驶舱接口

所有接口响应均为：

```json
{ "code": 200, "message": "success", "data": {} }
```

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/cockpit/time-stages` | T+1、T+3、T+7、T+15、T+30 档位 |
| `GET /api/v1/cockpit/points` | 站点详情及地图相对坐标 |
| `GET /api/v1/cockpit/points/{station_id}` | 单站详情 |
| `GET /api/v1/cockpit/risk-heatmap` | 5 个档位的 11×19 风险网格 |
| `GET /api/v1/cockpit/events` | 历史回放事件流 |
| `GET /api/v1/cockpit/region-summary` | 站点汇总及分档风险强度 |

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
