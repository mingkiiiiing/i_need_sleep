# audit7 API 契约矩阵

基线：HEAD = 977c357 · 生成：2026-09-05 · 服务：`uvicorn backend.main:app`（v2.1.0）
本文所有 data 字段均来自真实服务响应实测（见 live-api-verification.json），非设计文档转抄。

## 1. 统一响应信封

所有保留接口（含 /api/health 与根路径）返回：

```json
{
  "code": 200, "message": "ok", "data": {…},
  "meta": {
    "data_mode": "simulated", "dataset_version": "…", "prediction_run_id": null|“DEMO-RUN-V1”,
    "as_of": "2026-08-24T08:00:00+08:00", "claim_boundary": "simulation_only", "request_id": "req_<uuid4>"
  },
  "errors": []
}
```

- `request_id`：每请求唯一（中间件生成，X-Response 头 `X-Request-Id` 同值），错误响应保留。
- `as_of`：固定演示基准 2026-08-24T08:00:00+08:00（带时区 ISO-8601），与前端 dataIdentity 一致。
- meta 恒为 6 键；同一信息不会时而在 data 时而在 meta。

### 版本划分

| 域 | dataset_version | prediction_run_id | 覆盖端点 |
|---|---|---|---|
| 观测/数据集/能力（OBS） | `DEMO-OBS-V1` | `null` | system/capabilities、datasets/summary、pipeline/runs/latest、spatial-entities*（含 observations/quality）、/、/api/health |
| 预测/格网/事件（PRED） | `DEMO-PRED-V1` | `DEMO-RUN-V1` | dashboard/overview、forecast*、map/*、events、cockpit/* 全部 |

## 2. 端点矩阵（data 实测字段）

### 首页

| 端点 | data 字段（实测） | 备注 |
|---|---|---|
| GET /system/capabilities | `data_as_of`；`capabilities{historical_observation=dataset_available_backend_pending, short_term_forecast_1_3d=dataset_ready_model_pending, medium_term_forecast_7_15d=dataset_ready_model_pending, long_term_forecast_30_90d=blocked_auth, satellite_chlorophyll=experimental_not_operational, real_time_warning_dispatch=not_enabled, demo_warning_dispatch=available}`；`blockers[{code:MISSING_C3S_SEASONAL_HINDCAST,…}]`；`provider_status{observation_provider, prediction_provider}` | 能力状态诚实：pending / blocked_auth / not_enabled / available 四态齐备 |
| GET /datasets/summary | `datasets[2]`（含 record_count 由实际样本行计算）、`claim_boundary` | |
| GET /pipeline/runs/latest | `run_id, status, dataset_versions[2]` | |

### P01 驾驶舱

| 端点 | data 字段（实测） | 备注 |
|---|---|---|
| GET /cockpit/time-stages | `[{key,label,short,days,index,data_mode,capability_status}]×5` | t30 带能力说明 |
| GET /cockpit/points | `pointData{6 分区→{id,name,short,risk,riskClass,summary,metrics,factors,forecast,dataMode,datasetVersion}}`、`pointPositions{6→{top,left}}` | 保留前端 camelCase 兼容键；收口删除 trend/timeline/explainability 冗余 |
| GET /cockpit/points/{id} | 同上单点 | |
| GET /cockpit/risk-heatmap | `t1…t30 各 11×19 整数矩阵`、`_scenario{layer_type,operational_use,long_term_notice}` | `_scenario` 为前端兼容键 |
| GET /cockpit/events | `[{id,time,stageKey,point,title,summary,severity,data_mode,dataset_version,prediction_run_id}]` | stageKey 驼峰兼容 |
| GET /cockpit/region-summary | `totalStations=6`、`riskCounts{high,mid,low}`、`intensity{6 分区→T+1…T+30 分}` | intensity 为 T+30 演示预览，claim=simulation_only |
| GET /cockpit/timeline?start&end | `start_date,end_date,total_days,data[{date,risk_score,risk_level,data_mode,dataset_version}]` | 无叶绿素字段；非法日期 4xx |
| POST /cockpit/handle-warning | `event_id,status=simulated_dispatched,channels=[platform_simulation],persisted=false,data_mode,dataset_version,claim_boundary` | 接受事件/分区/格网三类演示引用 |

### P03 监测站点研判

| 端点 | data 字段（实测） | 备注 |
|---|---|---|
| GET /spatial-entities | `[{id,entity_type=demo_zone,display_name,short,geometry_status=simulated,data_mode,position{top,left},risk_hint}]×6` | 六对象统一 demo_zone |
| GET /spatial-entities/{id} | 同上单条 | |
| GET …/observations | `[{spatial_entity_id,observed_at,variable_code,clean_value,unit,value_origin=simulated,quality_status,is_imputed,proxy_flag,data_mode,dataset_version}]` | 气温行 proxy_flag=true，逐行披露 |
| GET …/quality | `spatial_entity_id,status,freshness,observed_count,source_count,is_imputed,value_origin,proxy_flag,limitations[]` | |
| GET /forecasts?spatial_entity_id&horizon_days | `[{id,spatial_entity_id,prediction_run_id,horizon_days,target_metric,risk_score,risk_level,provider_type,model_version,claim_boundary,uncertainty{lower,upper,method},quality_gate{status,decision,reason}}]` | 仅 T+1/3/7/15；T+30 → 409 |
| GET /forecasts/{id} | 同上单条 | ID 可解析校验 |
| GET /forecasts/{id}/explanations | `forecast_id,prediction_run_id,dataset_version,method,claim_boundary,features[{name,label,contribution,direction}]` | 严格绑定已存在 forecast ID |
| GET /events | `[{id,event_type,occurred_at,spatial_entity_id,title,summary,severity,data_mode,dataset_version,prediction_run_id}]` | 规范事件源 |

### P07 风险地图

| 端点 | data 字段（实测） | 备注 |
|---|---|---|
| GET /map/layers | `[{id,layer_type=simulated_scenario,data_mode,operational_use=false,description}]` | |
| GET /map/risk-grid?horizon_days | `prediction_run_id,horizon_days,data_mode,dataset_version,grid[11][19],rows=11,columns=19,resolution{rows,columns,unit=risk_score},thresholds{low:[0,44],mid:[45,74],high:[75,100]},claim_boundary,layer_type,operational_use=false,capability_status` | 五档位齐全；值 0-100 整数；T+30 带 capability_status=long_term_forecast_blocked_simulation_only；本任务新增顶层 rows/columns（加法兼容） |
| GET /map/risk-polygons?horizon_days | `type=FeatureCollection,features=[],horizon_days,source=simulated_grid,empty_reason,data_mode,dataset_version,prediction_run_id,claim_boundary` | 诚实空结果+原因；无面积/分辨率/置信度/迁移速度 |
| GET /forecast-capabilities | capabilities 七键同首页 | P07 档位开关数据源 |

### 历史复盘

| 端点 | 说明 |
|---|---|
| GET /events | 规范源；事件 ID 稳定 |
| GET /cockpit/events | 兼容视图；与 /events 共享同一事件 ID（契约测试验证同 ID 合并）；保留前端消费的 `time/stageKey/point` 旧字段名 |
| GET /cockpit/timeline | 演示风险序列（risk_score/risk_level），无叶绿素伪装；`>90 天→422`、`start>end→422`、`=90 天放行`（与 historyCore MAX_RANGE_DAYS 对齐） |
| POST /cockpit/handle-warning | `simulated_dispatched`、`persisted:false`、`channels=[platform_simulation]`；无 dispatch history、无负责人、无短信/邮件渠道 |

## 3. 错误契约

统一错误信封：`{code:<http>, message, data:null, meta(同6键), errors:[{code,field,detail}]}`。

错误响应数据身份（audit7 返工收口）：`meta.dataset_version` 由集中式解析器 `contracts.dataset_version_for_path(path)` 按接口类别决定——观察类（`/`、`/api/health`、`/api/v1/{system,datasets,pipeline,spatial-entities}`）= `DEMO-OBS-V1`，其余 `/api/v1` 路由 = `DEMO-PRED-V1`。`RequestValidationError` 与兜底 500 同样经该解析器选择版本，不得固定为预测版本；`ApiError` 工厂在路由类别明确处显式携带 `dataset_version`。错误响应 `prediction_run_id` 恒为 null。实机断言（pytest + live_verify）已覆盖：观察类业务/校验错误保持 OBS，预测类业务/校验错误保持 PRED，兜底 500 两类路径均按类别选择。

| 错误码 | HTTP | 触发场景（实测） |
|---|---|---|
| INVALID_DATE_RANGE | 422 | timeline start>end（field=start） |
| QUERY_RANGE_TOO_LARGE | 422 | timeline 跨度 >90 天 |
| INVALID_HORIZON | 422 | horizon_days ∉ {1,3,7,15,30}（field=horizon_days） |
| ENTITY_NOT_FOUND | 404 | 未注册分区、不可解析的 forecast ID、T+30 解释记录 |
| FORECAST_NOT_AVAILABLE | 409 | Provider 在场但无法提供该预测（预留） |
| CAPABILITY_UNAVAILABLE | 409 | T+30 分区预测（列表与记录两条路径） |
| INVALID_EVENT_ID | 422 | handle-warning 引用不是事件/分区/格网编号（field=event_id） |
| SIMULATION_ONLY | 409 | mode=historical / mode=observed 请求真实数据 |
| REQUEST_VALIDATION_FAILED | 422 | 参数类型/缺失兜底（如缺 event_id、日期格式错） |
| INTERNAL_ERROR | 500 | 未预期异常兜底 |

禁止模式已消除：非法日期不再 200+空数组；未知对象不再 200+null；后端异常不切换第二套 Mock（main.py 统一异常处理器渲染同一信封）。

## 4. 兼容策略

前端五个页面与 Wallboard 不改一行代码即可运行。保留的硬兼容项（来自 frontend-api-consumers.md 扫描）：

1. 信封双读法兼容：`request()` 只读 code==200，`requestEnvelope()` 读 data+meta+errors[0].code —— code/message 键名不变。
2. P01 cockpit points：`pointData`/`pointPositions` 复合键、`riskClass`/`dataMode`/`datasetVersion` 驼峰别名（Pydantic serialization_alias）。
3. P01 time-stages：`key/label/short/days/index/capability_status` 结构与 t30 阻塞语义不变。
4. P01 events：`severity/risk_hint` 等字段与 t1–t30 档位键不变。
5. P01 region-summary：`totalStations`/`riskCounts` 驼峰别名保留；删除的是前端未读的 data.data_mode 冗余。
6. P07 heatmap：`t1…t30` 裸矩阵键 + `_scenario` 元信息键不变。
7. History cockpit events：`time`/`stageKey` 旧字段名保留；事件 ID 与 /events 共享稳定值。
8. Timeline：90 天边界语义与前端 MAX_RANGE_DAYS=90 精确对齐（diff=90 放行）。
9. P03 forecasts：`target_metric` 遗留查询参数保留可传。

本任务新增字段（纯加法，不破坏旧前端）：risk-grid 顶层 `rows`/`columns`；观测行 `proxy_flag`（原接口无此披露）；timeline 行 `dataset_version`；删除字段仅限扫描确认前端未消费的项（cockpit points 内嵌 trend/timeline/explainability、P01 overview `avg_chlorophyll` 假名、demo_provider 旧路由、遗留孤立模块 backend/app/core.py——旧响应格式无任何引用，返工轮删除）。

## 5. Provider 边界

```text
ObservationProvider: name/dataset_version/zones/zone/observations/quality
PredictionProvider:  name/dataset_version/prediction_run_id/forecast/explanation/risk_grid
```

- 环境变量 `OBSERVATION_PROVIDER` / `PREDICTION_PROVIDER`，默认 `simulated`。
- 启动日志（uvicorn.error）明确输出：`Provider 配置: OBSERVATION_PROVIDER=simulated PREDICTION_PROVIDER=simulated（未配置时默认 simulated）`。
- 配置 `cleaned`/`member_c`/未知值且实现不存在 → `ProviderConfigError`，应用导入期即启动失败，绝不静默回退（测试 7 例覆盖，含显式恢复 simulated 后可用）。
- simulated 实现只读 `backend/sample-data/` 固定样本；不访问 data-cleaning 现场。
- 未宣称接入真实清洗产物或成员 C 正式模型；capabilities/provider_status 如实反映。

## 6. 尚未实现的能力（诚实清单）

| 能力 | 状态 | 表现 |
|---|---|---|
| 历史真实观测业务 API | dataset_available_backend_pending | 请求真实模式返回 409 SIMULATION_ONLY |
| T+1/3/7/15 正式模型 | dataset_ready_model_pending | 返回演示规则推演值，quality_gate 标注 demo |
| T+30—90 天预测 | blocked_auth（缺 C3S 季节预测回报数据） | 分区预测 409；仅风险地图提供 T+30 演示格网（capability_status 披露） |
| 实时正式预警分发 | not_enabled | 仅 platform_simulation 演示通道，persisted=false |
| 卫星叶绿素业务化 | experimental_not_operational | 不作为演示数值来源 |
| 风险矢量面 | 不提供 | 空 FeatureCollection + empty_reason |
| 处置记录持久化 | 未实现 | persisted:false，无 dispatch history |

## 7. 验证摘要

| 验证 | 命令/方式 | 结果 |
|---|---|---|
| 全套测试 | `python -m pytest backend/tests -q` | **90 passed**，0 failed，0 warnings（filterwarnings=error）；返工轮新增 7 例（错误数据身份五类实测 + 兜底 500 观察类/预测类各一） |
| 实机验证 | 真实 uvicorn（127.0.0.1:8617）+ live_verify.py | **64/64 通过**：31 成功路径 + 18 错误路径（expect_error 逐例断言 dataset_version/prediction_run_id/六键 meta，新增观察类参数校验 err-mode-bogus）+ 5 并发格网 + 10 专项（代理观测/三类预警引用/五档格网多面校验等）；request_id 全局唯一 |
| OpenAPI | `app.openapi()` | 26 paths 全部生成，响应模型带 Pydantic 校验，见 openapi.json |
| 测试清单覆盖 | 任务规格 22 项 | 全覆盖：信封/版本分配/格网尺寸/跨接口风险一致/demo_zone/404/422/T+30 阻塞/timeline 三态/无叶绿素声称/explanation 绑定/空面披露/simulated_dispatched/persisted:false/非法事件拒绝/无真实渠道/Provider 不回退/旧前端兼容/OpenAPI/零警告 |
| 真实浏览器联调 | vite dev(5173) → 代理 8000 真实 uvicorn，逐页操作 | 五页全过：首页能力卡诚实四态；P01 T+7 排行 77/54/54/21/21 与公式一致+驱动因素 34/24/20+时间轴；P03 六分区/观测(总磷+气温代理)/质量 proxy_flag=true/T+7=77/T+30 阻塞文案/模拟预警 simulated_dispatched(platform_simulation)；P07 11×19+209 格+阈值文案+热点排行 R04-C07=87+格详情绑定 DEMO-RUN-V1+历史/当前/导出按钮诚实禁用；History 6 事件双源同 ID 合并+证据边界"接口未提供"+4 帧回放+模拟发送"未形成持久化处置记录" |
