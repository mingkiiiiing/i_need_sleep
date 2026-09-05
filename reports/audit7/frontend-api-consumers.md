# 前端接口消费清单（第七任务 · 只读扫描）

- 基线：`977c357 feat(frontend): rebuild historical event review`（扫描时工作树含并行未提交修改，本文档只读扫描，未修改任何前端文件）。
- 扫描对象：`src/services/api.js`、五个保留页面（`src/pages/Home.vue`、`Cockpit.vue`、`Stations.vue`、`Heatmap.vue`、`History.vue`）及其直接子组件（`components/cockpit/LakeMap.vue`、`components/stations/*`、`components/heatmap/*`、`components/history/*`）。
- 方法：逐文件通读 `<script>` 与模板中的数据绑定，记录**实际读取的字段**，不以设计文档为准。
- 并行现场声明：`Wallboard.vue`（并行大屏任务）消费 `getTimeStages / getPoints / getHeatField / getEvents / getRegionSummary`（与 P01 相同），收口时一并保持兼容，但不对其做任何修改。

## 1. 前端请求层机制（兼容硬约束）

`src/services/api.js` 有两条请求路径，决定了后端信封必须同时满足两者：

| 路径 | 使用页面 | 成功判定 | 返回 | 错误处理 |
|---|---|---|---|---|
| `request()` | P01（time-stages/points/risk-heatmap/events/region-summary）、遗留导出 | `body.code === 200` | `body.data`（丢弃 meta） | `throw Error(body.message)`；页面落 StatePanel error |
| `requestEnvelope()` | P03、P07、历史复盘 | `body.code === 200` | `{ data: body.data, meta: body.meta }` | `body.detail.code/detail.message` 或 `body.errors[0].code`、`body.message` → `ApiError(message, status, code)` |

推论：

1. 所有响应必须有 `code: 200` 与 `data`；错误必须是非 2xx HTTP 状态 + `message` + `errors[0].code`（`requestEnvelope` 读 `body.errors[0].code`，无 `detail` 时走此分支）。
2. `meta` 是 P03/P07/P06 的显式消费字段：`meta.dataset_version`（P03 观测/预测版本 chip、P07 版本 chip）、`meta.claim_boundary`（P06 事件详情）、P03 还把整个 `meta` 传给 `obsMeta`。meta 键名不可变。
3. P01 页面不读 meta（除 `getPoints` 里的 `data.pointPositions`）。

## 2. 首页 Home.vue

**当前不调用任何 HTTP 接口。** 数据全部来自前端静态常量：

| 前端函数 | HTTP | URL | 请求参数 | 实际读取字段 |
|---|---|---|---|---|
| 无（`import { pointData, regionSummary } from '../data/points.js'`） | — | — | — | `dataMode/dataModeLabel/datasetVersionId/predictionRunId/asOfLabel/asOfFull/claimBoundary/claimNote`（`data/dataIdentity.js`，静态） |
| 无（`regionSummary.riskCounts.high/mid/low`） | — | — | — | 静态常量 |

因此首页的三个接口 `GET /system/capabilities`、`GET /datasets/summary`、`GET /pipeline/runs/latest` 目前无前端消费方，本任务按任务书第六节**规范其语义**（能力状态不得虚报、模型 pending、30—90 天 `blocked_auth`、实时预警 `not_enabled`、演示发送 `available`），信封并入统一体系，为首页后续接入留稳定接口。

## 3. P01 综合驾驶舱 Cockpit.vue（全部走 `request()`）

| # | 前端函数 | HTTP | URL | 请求参数 | 实际读取字段 |
|---|---|---|---|---|---|
| 1 | `getTimeStages()` | GET | `/cockpit/time-stages` | — | 数组每项：`key`、`days`、`index`、`short`、`label`（KPI 档位名）、`capability_status`（映射 `sample_interface_only`→“演示预测接口”、`simulation_only`→“模拟预演”） |
| 2 | `getPoints()` | GET | `/cockpit/points` | — | `data.pointData`（对象，键=分区 id）每点：`id`、`short`、`name`、`risk`、`riskClass`、`metrics.density/chla/phosphorus/temp`、`factors[].name/value(/unit)`、`forecast.window[]/title[]/text[]`（按下标取档位）、`datasetVersion`；`data.pointPositions[id].top/left`（映射经纬度） |
| 3 | `getHeatField()` | GET | `/cockpit/risk-heatmap` | — | 顶层键 `t1/t3/t7/t15/t30` → 11×19 数值格网（`LakeMap` 按 `heatField[stageKey]` 取帧）；`Object.keys(heatField).length>0` 判定有无格网 |
| 4 | `getEvents()` | GET | `/cockpit/events` | — | 数组每项：`id`、`point`（按选中分区过滤）、`time`、`title`、`severity`（`high/mid/low`） |
| 5 | `getRegionSummary()` | GET | `/cockpit/region-summary` | — | `totalStations`、`riskCounts.high/mid/low`、`intensity[分区id][t1..t30]`（排行+趋势图数值） |

- data_mode / dataset_version：页面主要展示静态 `dataIdentity`（DEMO-OBS-V1）+ `points[].datasetVersion`（应为 DEMO-PRED-V1）。
- claim_boundary：页面文案固定“非决策用途”，不读接口。
- 错误状态：任一接口异常 → 对应 `load.*='error'` → StatePanel + 重试；无错误码分支。
- 额外约束：`intensity` 的 t30 数值仍会被趋势图展示（页面标注“模拟预演”）；`riskClass` 必须与 `/forecasts`(3d)、`risk_hint`、事件 `severity` 同档一致（阈值 0-44 低 / 45-74 中 / 75-100 高）。

## 4. P03 监测站点研判 Stations.vue（全部走 `requestEnvelope()`，预警走 `request()`）

| # | 前端函数 | HTTP | URL | 请求参数 | 实际读取字段 |
|---|---|---|---|---|---|
| 1 | `getSpatialEntities()` | GET | `/spatial-entities` | `entity_type=demo_zone`、`mode=simulated` | 数组每项：`id`、`short`、`display_name`、`position.top/left`、`risk_hint` |
| 2 | `getForecastsEnvelope(id, days)` | GET | `/forecasts` | `spatial_entity_id`、`horizon_days`（t30 档**前端不发起请求**） | `data[0].id`、`spatial_entity_id`、`risk_level`、`risk_score`、`provider_type`、`model_version`、`uncertainty.lower/upper(/method)`、`quality_gate.status/decision(/reason)`、`claim_boundary`（StationTabs）；`meta.dataset_version` |
| 3 | `getEntityObservations(id)` | GET | `/spatial-entities/{id}/observations` | — | 行：`observed_at`、`variable_code`、`unit`、`clean_value`、`quality_status`、`value_origin`、`is_imputed`、`dataset_version`（行内，趋势 tooltip）；`meta.dataset_version`（页面版本 chip） |
| 4 | `getEntityQuality(id)` | GET | `/spatial-entities/{id}/quality` | — | `status`、`freshness`、`observed_count`、`source_count`、`is_imputed`、`value_origin`、`proxy_flag`、`limitations[]` |
| 5 | `getExplanationEnvelope(fcId)` | GET | `/forecasts/{id}/explanations` | — | `features[].name/label/direction/contribution` |
| 6 | `getEventsEnvelope()` | GET | `/events` | — | `id`、`spatial_entity_id`（过滤）、`occurred_at`、`title` |
| 7 | `getHeatField()` | GET | `/cockpit/risk-heatmap` | — | 同 P01 #3 |
| 8 | `handleWarning(eventId)` | POST | `/cockpit/handle-warning` | body `{event_id}`（事件 id，空则分区 id） | `data.status`、`data.channels[]`（ZoneEventsPanel） |

- data_mode：事件行 `em.simulated` 为页面硬编码文案；观测行的 `value_origin=simulated` 来自接口。
- 错误状态：`explainError` 直接展示 `err.message`（来自 `errors[0]`/`message`）；其余落 StatePanel。
- 硬约束：观测行字段名/精度不得变；`meta.dataset_version` 是观测/预测版本 chip 的数据源；`/forecasts` 对 t30 必须能力阻塞（前端虽不请求，接口语义要求）。

## 5. P07 风险地图 Heatmap.vue（`requestEnvelope()`）

| # | 前端函数 | HTTP | URL | 请求参数 | 实际读取字段 |
|---|---|---|---|---|---|
| 1 | `getForecastCapabilitiesEnvelope()` | GET | `/forecast-capabilities` | — | data 整体（对象）→ `HeatmapLayersPanel` 按 `Object.entries` 渲染 键→状态 |
| 2 | `getMapLayersEnvelope()` | GET | `/map/layers` | — | 数组每项 `l.id`（图层目录文本） |
| 3 | `getSpatialEntities()` | GET | `/spatial-entities` | `entity_type=demo_zone&mode=simulated` | 同 P03 #1 |
| 4 | `getRiskGridEnvelope(days)` | GET | `/map/risk-grid` | `horizon_days`（五档 1/3/7/15/30） | `data.grid`（11×19）、`data.resolution.rows/columns`、`data.data_mode`、`data.prediction_run_id`、`data.claim_boundary`；`meta.dataset_version` |
| 5 | `getForecastsEnvelope(id, days)` | GET | `/forecasts` | 同 P03 | `data[0].spatial_entity_id/risk_level/risk_score`（t30 档前端不发起） |
| 6 | `postHandleWarningEnvelope(cellId)` | POST | `/cockpit/handle-warning` | body `{event_id}`=**格网编号**（`R{01-11}-C{01-19}`） | `data.status`、`data.event_id`、`data.channels[]`、`data.data_mode`（页面直接渲染） |

- KPI/摘要读 `raw.resolution.rows×columns`、`raw.meta.dataset_version`、`raw.prediction_run_id`、`raw.data_mode`、`raw.claim_boundary`。
- 阈值在前端 `gridCore.js` 固化为 0-44 低 / 45-74 中 / 75-100 高（与后端一致）。
- 错误状态：`entry.error = err.message` 展示于 StatePanel。
- 硬约束：`data.data_mode` 是 handle-warning 的**页面渲染字段**，不可删；格网必须 11×19、数值有限；并发五档请求各自独立缓存（前端已有令牌，后端需确定性输出）。

## 6. 历史复盘 History.vue（`requestEnvelope()`）

| # | 前端函数 | HTTP | URL | 请求参数 | 实际读取字段 |
|---|---|---|---|---|---|
| 1 | `getForecastCapabilitiesEnvelope()` | GET | `/forecast-capabilities` | — | data 对象（`HistoryPlanPanel` 按 entries 渲染） |
| 2 | `getSpatialEntities()` | GET | `/spatial-entities` | `entity_type=demo_zone&mode=simulated` | `id`、`display_name`、`short` |
| 3 | `getEventsEnvelope()` + `getCockpitEventsEnvelope()`（Promise.all 双源） | GET | `/events` + `/cockpit/events` | — | 合并（按 `id`）：`id`、`event_type`、`data_mode`（筛选维度）、`spatial_entity_id`（筛选/详情）、`occurred_at`（日期筛选/回放窗口）、`time`（cockpit 源，回退展示）、`title`、`summary`、`severity`（高风险才能模拟发送）、`prediction_run_id`（run chip）、`stageKey`（cockpit 源，跳转档位）；`meta.dataset_version`、`meta.claim_boundary`（事件详情 meta） |
| 4 | `getTimelineEnvelope(start, end)` | GET | `/cockpit/timeline` | `start`、`end`（事件日 -1d ~ +2d，ISO 日期） | `data.data[].date`、`data.data[].risk_level`（`buildReplayFrames` 仅消费这两键） |
| 5 | `postHandleWarningEnvelope(eventId)` | POST | `/cockpit/handle-warning` | body `{event_id}`=事件 id | `data.status`、`data.channels[]`、`data.event_id`、`data.data_mode`（详情页渲染） |

- 硬约束：`/events` 与 `/cockpit/events` 必须共享同一组稳定 `id`（合并依赖 id 相等）；`severity` 当前仅 cockpit 源提供，若 `/events` 也提供则合并一致；`occurred_at` 必须为 ISO（`eventDateOf` 取前 10 位日期）。
- timeline：前端只读 `date` + `risk_level`；后端不得再用“平均叶绿素”类真实观测字段名承载演示风险序列。
- 错误状态：`eventsError` / `replay.error` 展示 `err.message`。

## 7. 汇总：收口必须保留的兼容字段（前端冻结，禁止破坏）

1. `code/message/data/meta` 信封 + `meta.dataset_version`/`meta.claim_boundary` 键名。
2. `/cockpit/points`：`pointData`/`pointPositions` 复合结构及 #3 表全部字段。
3. `/cockpit/risk-heatmap`：顶层 `t1..t30` 键名（`_scenario` 前端不消费，属后端自述字段，可保留可迁移）。
4. `/cockpit/events`：`time`、`point`、`stageKey`、`severity` 字段名。
5. `/map/risk-grid`：`grid`、`resolution.rows/columns`、`data_mode`、`prediction_run_id`、`claim_boundary`。
6. `/cockpit/handle-warning`：data 内 `status`、`event_id`、`channels`、`data_mode`。
7. `/cockpit/timeline`：`data[]` 内 `date`、`risk_level`。
8. 观测行全部列名（`observed_at/variable_code/clean_value/unit/value_origin/quality_status/is_imputed` + 行内 `dataset_version`）。
9. `/forecasts` 支持 `target_metric` 查询参数（遗留 `getPrediction` 导出默认 `bloom_risk`）。

## 8. 允许的收口动作（前端不消费）

- `/cockpit/points` 单点字段 `trend`（24 点重复值）、`timeline`、`explainability` 前端未消费且与 `factors` 重复 → 删除。
- `/cockpit/region-summary` data 内 `data_mode` 前端未消费（meta 已有）→ 删除。
- `/cockpit/timeline` 行内 `avg_chlorophyll` 前端未消费且命名伪装真实观测 → 更名为演示风险序列字段。
- 成功 `message` 从 "success" 统一为 "ok"（前端仅错误分支读 message）。
