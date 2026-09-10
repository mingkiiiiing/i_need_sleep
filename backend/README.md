# 后端联调说明

当前后端同时提供三条明确隔离的链路：`observed` MEE 实时观测、`simulated` 旧演示接口，以及 `hybrid` 算法交付包 V0.2 情景推演。算法链已能执行 63 个 bundle，但训练边界仍为 `synthetic_development_only`，不得用于真实监管、正式预警发布或真实精度宣传。

## 本地启动

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`。

前端默认请求 `/api/v1`，经 Vite 代理到本服务。前端只连接后端，无 mock 数据源（历史 mock 配置与 mock 服务文件已于第九任务删除）；后端失败时前端会显示错误态并提供重试。

## P0 边界

- 六个驾驶舱对象均为 `demo_zone`，不是已核验真实站点；
- `DEMO-OBS-V1` 和 `DEMO-PRED-V1` 仅为固定演示样本；
- 1/3/7/15 天仅提供 `sample_interface_only` 演示接口；
- 30—90 天正式预测返回 `CAPABILITY_UNAVAILABLE`；T+30 地图仅是 `simulated_scenario` 预演；
- 解释接口仅返回 `demo_rule_contribution`，不是 SHAP；
- 模拟预警处理仅写演示响应，不发送短信、邮件或其他真实通知。

## 算法交付包 V0.2

- 运行目录：`backend/model_runtime_v0_2`；
- 模型：9 个任务变体 × 7 个时效，共 63 个；
- 状态接口：`GET /api/v1/model/status`；
- 推演接口：`GET /api/v1/model/predictions?horizon_days=3&entity_id=lake&focus_metric=risk`；
- 空间样点：`GET /api/v1/model/spatial-field?horizon_days=3&metric=risk`；
- 10% 门禁：`GET /api/v1/model/acceptance`（当前冻结结果为 `FAIL`，0/189 通过）；
- 反演状态：`GET /api/v1/model/retrieval/status`；同期地面配对校准：`POST /api/v1/model/retrieval/calibrate`；
- 当前查看指标随响应返回局部单因素敏感性排序和 64 次输入扰动情景分布；该分布不是经真实残差校准的置信区间。
- `entity_id` 可为 `lake` 或一个 `mee-*` 站点 ID；
- 平台只将语义一致的 MEE 水温、总磷、总氮、溶解氧、pH 写入模型，时间特征由观测时间派生；缺失的气象、遥感、机理与空间字段由 bundle 冻结预处理器按训练期中位数插补并保留缺失标记；
- 每次响应包含 `snapshot_id`、`prediction_run_id`、实测/派生/插补字段清单和 `scenario_assessment_only` 质量门禁。

## 数据接入

当前不提供任意 JSON records 上传。后续可通过清洗发布物契约实现 `POST /api/v1/ingestion/releases`，并校验 manifest、哈希、schema、质量、版本与允许路径。
