# A23 前后端联调说明

> 当前阶段：P0 模拟数据联调。接口返回的数值均为 `simulated`，只用于页面联调和答辩情景展示，不能作为实时监测、真实模型精度或监管决策依据。

## 启动

后端：

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
npm run dev
```

Vite 会将 `/api` 代理到 `http://127.0.0.1:8000`。默认前端请求 `/api/v1`；后端异常会由调用层显示错误，绝不会自动切换为本地 mock。

## 数据源切换

仅在项目根目录 `.env.local` 明确配置下启用前端 mock：

```ini
VITE_USE_MOCK=true
```

mock 仍为 `SIMULATED` 演示数据；没有真实模型、模型精度或 SHAP 输出。未设置或设为 `false` 时，所有请求均走后端 API。

## P0 核心接口

统一前缀：`/api/v1`。成功响应的公共结构：

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "meta": {
    "request_id": "req_...",
    "data_mode": "simulated",
    "dataset_version": "DEMO-OBS-V1 或 DEMO-PRED-V1",
    "claim_boundary": "simulation_only"
  },
  "errors": []
}
```

主要读取接口：

| 接口 | 用途 |
| --- | --- |
| `GET /system/capabilities` | 能力边界与阻塞项 |
| `GET /datasets/summary` | 演示数据版本 |
| `GET /spatial-entities?entity_type=demo_zone` | 六个演示分区 |
| `GET /spatial-entities/{id}/observations` | 演示观测与来源 |
| `GET /spatial-entities/{id}/quality` | 演示数据质量说明 |
| `GET /forecasts?spatial_entity_id=...&horizon_days=...` | 1/3/7/15 天样例接口；30 天返回 409 |
| `GET /forecasts/{id}/explanations` | 演示规则贡献，不是真实 SHAP |
| `GET /map/risk-grid` | `simulated_scenario` 风险格网 |
| `GET /events` | 演示事件 |
| `GET /cockpit/*` | 当前驾驶舱兼容视图 |

`/cockpit/time-stages` 中的 T+30 为模拟预演，明确不代表 30—90 天正式预测能力。

## 错误与能力阻塞

错误响应也使用统一结构，`errors[0].code` 可用于 UI 展示。当前重点错误：

| HTTP | code | 含义 |
| --- | --- | --- |
| 404 | `SPATIAL_ENTITY_NOT_FOUND` | 演示分区不存在 |
| 409 | `CAPABILITY_UNAVAILABLE` | 30—90 天预测未就绪 |
| 409 | `DATA_MODE_UNAVAILABLE` | 真实历史数据尚未接入业务 API |
| 422 | `REQUEST_VALIDATION_FAILED` | 参数或请求体不符合契约 |

## 后续数据接入

当前不提供通用 records 上传接口。数据同学交付清洗发布物后，将实现 `POST /api/v1/ingestion/releases`，按 manifest、哈希、schema、质量与路径白名单校验接入。真实数据接入前，页面不得将模拟数据描述为真实或实时数据。
