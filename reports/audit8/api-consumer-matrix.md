# audit8 五页 API 消费矩阵

生成时间：2026-09-06。核对基准：`backend/app/api.py`（第七任务后契约，HEAD = 7f21d32）、
`src/services/api.js`、`reports/audit8/audit8-verify.mjs` 实测（148/148）。

## 一、唯一事实源与 fallback 链

`src/data/dataIdentity.js` 为全站数据身份唯一事实源，字段命名与后端 meta 一致：

| 事实源字段 | 值 | 对应后端 meta 字段 |
|---|---|---|
| dataMode | SIMULATED | data_mode（接口值为 simulated，界面展示大写品牌态） |
| datasetVersionId | DEMO-OBS-V1 | dataset_version（观察类） |
| predVersionId | DEMO-PRED-V1 | dataset_version（预测类） |
| predictionRunId | DEMO-RUN-V1 | prediction_run_id |
| claimBoundary / claimBoundaryCode | 非决策用途 / simulation_only | claim_boundary |
| asOfFull | 2026-08-24 08:00 | as_of（2026-08-24T08:00:00+08:00） |

优先级：**页面展示一律优先取接口返回 meta / 业务数据，事实源仅作为请求失败或首帧前的明确 fallback**。

> 语义修正：任务前 `predictionRunId` 被误用作预测数据集版本（DEMO-PRED-V1）。
> 本轮起 `predictionRunId` 恢复后端语义 = 预测运行 ID（DEMO-RUN-V1），新增
> `predVersionId` 表示预测数据集版本。

## 二、逐页消费矩阵

### 首页 `/`（Home.vue）
| 接口 | 方法 | 身份 | meta 使用 |
|---|---|---|---|
| /system/capabilities | GET | OBS | 能力卡数据 + 首页身份口径统一取该响应 meta（data_mode/dataset_version/as_of/claim_boundary 全部 meta 优先，事实源仅兜底）。按 CapabilitiesData 结构消费：`data.capabilities`（能力键→状态，如 short_term_forecast_1_3d=dataset_ready_model_pending、long_term_forecast_30_90d=blocked_auth）与 `data.blockers`（长期能力说明来源）。实测能力卡：预测能力=1—15 天演示档位、长期能力=仅模拟预演，无 `—` 占位 |
| /datasets/summary | GET | OBS | 数据集摘要（DEMO-OBS-V1 6 条 / DEMO-PRED-V1 30 条） |
| /spatial-entities?entity_type=demo_zone&mode=simulated | GET | OBS | 湖面分区位置/名称/风险（risk_hint）、分区风险统计；回退静态常量并如实标注 |
| 状态机 | loading（StatePanel）/ error（StatePanel + 重试按钮）/ empty（StatePanel + 重试）/ ok（能力卡四张，全部由接口数据推导） |
| 身份展示 | 页脚完整身份行（meta 优先）；四张入口卡按目标页面域标注 OBS/PRED/RUN；首屏边界行含 claim_boundary 代码 |
| 实测 | 三接口信封逐响应断言（audit8 B 组）；网络失败注入 → 错误态 → 重试恢复（E 组 home-error / home-error-recovered 截图） |

### P01 驾驶舱 `/cockpit`（Cockpit.vue）
> 注：原"打开综合展示大屏"入口已按 P2-3 移除，驾驶舱子页入口仅指向三个正式业务页。
| 接口 | 方法 | 身份 | meta 使用 |
|---|---|---|---|
| /cockpit/time-stages | GET | PRED | 档位轴 |
| /cockpit/points | GET | PRED+RUN | 点位卡 datasetVersion（serialization_alias=datasetVersion）优先，回退事实源 predVersionId |
| /cockpit/points/{id} | GET | PRED | 点位详情 |
| /cockpit/risk-heatmap | GET | PRED | 热力场 |
| /cockpit/events | GET | PRED+RUN | 事件流 |
| /cockpit/region-summary | GET | PRED+RUN | 分区汇总 |
| /forecasts?…&target_metric | GET | PRED | 预测卡 |
| /forecasts/{id}/explanations | GET | PRED | 因子解释 |
| /cockpit/handle-warning | POST | PRED+RUN | 模拟处置（persisted:false） |
| /map/layers、/map/risk-grid | GET | PRED+RUN | 底图/格网 |
| 身份展示 | 顶栏芯片 `数据版本 DEMO-OBS-V1 / <PRED>`；摘要区 `数据模式 SIMULATED · 非决策用途（simulation_only）`；公共身份栏（全局） |
| URL 状态 | `?t=<stage>&p=<point>`（store 双向同步；非法 t 拒绝应用、非法 p 清理） |

### P03 监测站点 `/stations`（Stations.vue）
| 接口 | 方法 | 身份 | meta 使用 |
|---|---|---|---|
| /spatial-entities?entity_type=demo_zone&mode=simulated | GET | OBS | obsVersion = meta.dataset_version 优先，回退事实源 datasetVersionId |
| /spatial-entities/{id}、/{id}/observations、/{id}/quality | GET | OBS | 详情/观测时序/质量 |
| /forecasts?spatial_entity_id&horizon_days | GET | PRED | predVersion = meta.dataset_version 优先（初始值 = 事实源 predVersionId） |
| /forecasts/{id}/explanations | GET | PRED | 因子贡献 |
| /cockpit/heat-field（经 /cockpit/risk-heatmap） | GET | PRED | 底图热力 |
| /cockpit/handle-warning | POST | PRED+RUN | 模拟预警 |
| 身份展示 | 芯片行 `SIMULATED · <OBS> · <PRED> · 非决策用途 · 档位 · 基准 2026-08-24 08:00` |
| URL 状态 | `?p=<分区>&t=<档位>`；非法 p 规范化清理并回默认选中 |

### P07 风险热力 `/heatmap`（Heatmap.vue）
| 接口 | 方法 | 身份 | meta 使用 |
|---|---|---|---|
| /forecast-capabilities | GET | PRED | 能力状态（T+30 阻塞披露） |
| /map/layers | GET | PRED | 底图图层 |
| /map/risk-grid?horizon_days=1/3/7/15/30 | GET | PRED+RUN | predVersion = raw.meta.dataset_version 优先（回退事实源 predVersionId）；runId = raw.prediction_run_id 优先（回退事实源 predictionRunId） |
| /map/risk-polygons | GET | PRED+RUN | 矢量面（当前为空面+empty_reason 诚实披露） |
| /cockpit/handle-warning | POST | PRED+RUN | 格网模拟预警 |
| 身份展示 | 芯片行 `SIMULATED · <PRED> · <RUN> · 档位 · simulation_only · 非决策用途`（全部来自事实源/meta） |
| URL 状态 | `?t=<档位>` 档位即 URL 状态；T+30 有能力阻塞横幅 |

### 历史复盘 `/history`（History.vue）
| 接口 | 方法 | 身份 | meta 使用 |
|---|---|---|---|
| /events | GET | PRED+RUN | eventsMeta = basic.meta（canonical 事件源） |
| /cockpit/events | GET | PRED+RUN | 兼容视图，与 /events 同 ID 合并（契约测试验证） |
| /forecasts/{id}/explanations | GET | PRED | 证据下钻 |
| /cockpit/timeline?start&end | GET | PRED | 回放时间轴（>90 天→422、start>end→422 业务错误如实呈现） |
| /forecast-capabilities | GET | PRED | 能力说明 |
| /cockpit/handle-warning | POST | PRED+RUN | 模拟处置 |
| 身份展示 | 标题区芯片 `SIMULATED · DEMO-OBS-V1 · DEMO-PRED-V1 · DEMO-RUN-V1 · simulation_only · 非决策用途`（本轮起全部引用事实源，不再硬编码）；页脚同口径 |
| URL 状态 | `?e=<事件>` 选中事件；筛选区未来区间查询呈现诚实空态 |

### 公共身份栏（DataContextBar.vue，AppShell 全页挂载）
展示 `太湖｜SIMULATED｜OBS / PRED / RUN 三元组｜基准 08:00｜simulation_only`，
aria-label 含完整口径；「查看来源」抽屉列出观测数据集/预测数据集/预测运行/基准时间/
数据载体/使用限制六项（事实源 provenance）。

## 三、实测信封断言（audit8 A 组，浏览器同源一致）

- 成功信封：`code=200, message=ok`，meta 六键齐全，`data_mode=simulated`、`as_of=2026-08-24T08:00:00+08:00`、`claim_boundary=simulation_only`、`request_id=req_*`。
- 观察类（`/`、`/api/health`、`/api/v1/system/capabilities`、`/api/v1/datasets/summary`、`/api/v1/pipeline/runs/latest`、`/api/v1/spatial-entities*`）：`dataset_version=DEMO-OBS-V1` 且 `prediction_run_id=null`。
- 预测类（cockpit/*、map/*、events、forecast-capabilities、forecasts）：`dataset_version=DEMO-PRED-V1`；成功响应 `prediction_run_id=DEMO-RUN-V1`。
- 错误信封：404/422/409/500 的 `prediction_run_id` 恒为 null（audit7 契约），`errors[0].code` 为稳定错误码；五页在错误路径不伪造字段、不静默兼容，统一 StatePanel 错误态 + 重试。
