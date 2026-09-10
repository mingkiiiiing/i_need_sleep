# A23 前后端联调说明

> 算法链路口径（2026-09-10 更新）：主链路为 **V0.3 真实数据包**（`/api/v1/model/v3/*`，20 bundle = 12 冻结划分 + 8 补训 CV 协议，含 conformal 区间与动态质量门）；legacy **V0.2 合成包**（63 bundle，`synthetic_development_only`）保留作对照与回退。三轨数据口径：`simulated` 旧演示轨、`observed` MEE 实时观测轨、`hybrid` 算法推演轨。**统一指标口径见 `企业提交材料/算法组提交材料_V0.1/12_命题条款对照与统一指标口径_V0.1.md`。**

## 启动

后端：

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
npm run dev
```

Vite 会将 `/api` 代理到 `http://127.0.0.1:8000`（端口被占用时：后端换端口启动，前端以 `BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev` 覆盖代理目标）。默认前端请求 `/api/v1`；后端异常会由调用层显示错误，绝不会自动切换为本地 mock。

## 数据源说明

前端只连接后端：所有请求统一走 `/api/v1`，不存在 mock 数据源或数据源切换开关（历史 mock 配置与 mock 服务文件已于第九任务清理删除）。后端异常时页面进入各自的错误态并提供重试，绝不静默切换数据。

MEE 观测为 `observed`；时空推演页主链路为 V0.3 真实数据模型（月度标签粒度 + conformal 区间 + 逐任务来源标注），缺失任务逐项回退 legacy 合成对照并如实标注；30/60/90 天为情景推演口径。真实口径 10% 门禁当前 FAIL 如实；尚无逐次 SHAP。

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
| `GET /realtime/status` | **实时链路状态**（observed）：抓取时间、新鲜度、活跃站点数 |
| `GET /spatial-entities?mode=observed&active=latest` | **实时站点列表**（observed）：MEE 国控站全量摘要，支持 province / location_status 筛选 |
| `GET /spatial-entities/{mee-*}/observations?window=latest\|range` | **站点观测**（observed）：每站固定 11 项指标状态，缺测显式（missing_reason=upstream_missing） |
| `GET /spatial-entities/{mee-*}/quality` | **站点质量**（observed）：覆盖率、滞后、缺测清单、坐标可信度、适用性 |
| `GET /model/status` | **legacy 运行状态**（hybrid）：V0.2 合成包 63 模型完整性、依赖、时效与声明边界（当前主链路为 `/model/v3/status`，20 模型） |
| `GET /model/predictions?horizon_days=...&entity_id=...` | **算法情景推演**：1/3/7/15/30/60/90 天，覆盖 9 个任务；输入来源和插补字段逐项披露 |
| `GET /model/spatial-field?horizon_days=...&metric=...` | 太湖附近已核验站点条件化的模型空间样点；不是连续卫星像元反演 |
| `GET /model/acceptance` | 冻结测试口径的融合相对最强单一 AI 提升 10% 门禁；当前如实返回 FAIL |
| `GET /model/retrieval/status` | 叶绿素 a、藻密度、水华面积反演/校准能力状态和证据边界 |
| `POST /model/retrieval/calibrate` | 用至少 3 组 retrieved/reference 同期配对拟合仿射地面校准，并保持 derived 来源标记 |

`/cockpit/time-stages` 中的 T+30 为模拟预演，明确不代表 30—90 天正式预测能力。

## 错误与能力阻塞

错误响应也使用统一结构，`errors[0].code` 可用于 UI 展示。当前重点错误：

| HTTP | code | 含义 |
| --- | --- | --- |
| 404 | `SPATIAL_ENTITY_NOT_FOUND` | 演示分区不存在 |
| 409 | `CAPABILITY_UNAVAILABLE` | 30—90 天预测未就绪 |
| 409 | `DATA_MODE_UNAVAILABLE` | 真实历史数据尚未接入业务 API |
| 422 | `REQUEST_VALIDATION_FAILED` | 参数或请求体不符合契约 |

## 算法输入衔接

模型训练特征多于 MEE 实时接口现有字段。当前适配层只写入语义一致的水温、总磷、总氮、溶解氧和 pH；日历特征由观测时间计算；其他气象、遥感、机理和空间字段保留缺失并由 bundle 内冻结预处理器插补。MEE 叶绿素 a 不会被误填到 `remote_chlorophyll_a`。

## 后续数据接入

当前不提供通用 records 上传接口。数据同学交付清洗发布物后，将实现 `POST /api/v1/ingestion/releases`，按 manifest、哈希、schema、质量与路径白名单校验接入。真实数据接入前，页面不得将模拟数据描述为真实或实时数据。
