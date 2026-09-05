# 第四任务交付报告：P03 监测站点研判重构

- 日期：2026-09-05
- 前端基线：`072a82c feat(frontend): build P01 lake situation cockpit`（P03 改动全部未提交）
- 复验结论：`node reports/audit4-verify.mjs` **27/27 项全部 PASS，退出码 0**（证据：`reports/audit4-run6.log`；经 R1、R2 两轮返工补强，见文末返工记录）

## 1. 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/pages/Stations.vue` | 重写（+1135/−572，含样式与共享展示类） |
| `src/services/api.js` | +64 行：新增 `requestEnvelope()` 与 `ApiError`（P03 需要 meta；不改动旧 `request()` 返回结构，P01 不受影响） |
| `src/components/stations/`（新增 8 文件） | `ZoneListPanel` / `ZoneTrendPanel` / `ZoneBriefPanel` / `ZoneEventsPanel` / `StationTabs` / `ZoneDrawer` / `WarningDialog` / `stationDisplay.js` |
| `reports/audit4-verify.mjs`、`reports/audit4-run6.log`、`reports/audit4-screenshots/`（5 张） | 复验脚本与证据 |
| `dist/**` | 重新构建产物 |
| 允许区微调 | 无（`cockpit.js`、`LakeMap.vue`、`EChart.vue`、`styles.css` 均未改动） |

临时探针脚本（`_probe-map.mjs`、`_probe-filter.mjs`）与中间日志已清理。

## 2. 页面区块实现说明

- **三栏布局**（1920 一屏）：左 22% 搜索+风险筛选+分区列表；中 53% 地图（LakeMap 复用）+趋势面板；右 25% 分区档案+当前指标+数据质量+预测能力+分区事件。每栏独立 flex 容器解耦行高，消除共享 grid 行的幽灵空洞。
- **底部 3-Tab 行**：`stationSearch`（预测能力状态）/`drivers`（演示规则贡献）/`stations`（观测记录），原生 tablist 键盘语义（←→/Home/End），全宽横贯三栏。
- **单一 `<main>`**；390px 时底部操作栏经 `<Teleport to="body">` 移出路由动画容器（避免 `route-enter` 动画劫持 `position:fixed`），分区抽屉含焦点圈闭、Esc 关闭（元素级+window 级双通道）、焦点返回触发按钮。
- **并发防护**：obs/quality/explain 各自独立 token，快速连点分区时旧响应作废，最终数据属于最后选中的分区。

## 3. 实际调用的接口与返回状态

全程仅以下请求，业务请求**全部 200**（完整清单见 run6 日志 API_CALLS；唯一例外是 9b 用例中**故意**经 CDP 阻断的一次 `horizon_days=1` 请求，status=0，用于验证失败路径）：

- `GET /api/v1/spatial-entities?entity_type=demo_zone&mode=simulated`
- `GET /api/v1/spatial-entities/{id}/observations`、`/quality`
- `GET /api/v1/forecasts?spatial_entity_id={id}&horizon_days={1,3,7,15}`（仅这 4 档）
- `GET /api/v1/forecasts/{id}/explanations`
- `POST /api/v1/cockpit/handle-warning`（全程恰好 1 次，确认弹窗后）
- 回归加载：`/cockpit/time-stages`、`/points`、`/risk-heatmap`、`/region-summary`、`/events`、`/timeline`

## 4. 模拟数据边界的显示方式

- 每个数据区块右上角固定 `SIMULATED` 徽标；档案区明确 `数据模式: simulated`。
- 预测分数旁 `SIMULATED · 仅模拟` 虚线徽标；模型标注 `（演示规则）`。
- 驱动因素 Tab 头部 `simulation_only · 非真实 SHAP 解释`，正文注明"仅用于展示解释结构，不代表真实算法归因"。
- 趋势稀疏提示："当前数据不足以形成连续趋势……仅显示点标记"（单点不画假曲线）。
- 插补值打 `插补值` 橙色标签；缺失不填 0（验收 8 证实 0 个零填充单元格）。
- T+30 显示能力阻塞块："30—90 天预测能力未就绪，仅允许模拟预演"，且**不调用**预测接口（h30Calls=0）。
- 预警确认弹窗声明"不会发送真实短信/邮件/政府预警"，结果仅显示 `simulated_dispatched（platform_simulation）`。

## 5. 22 项验收结果（27/27 PASS）

| # | 结果 | 关键证据 |
|---|---|---|
| 1/2/3 | PASS | `#/stations?t=t3&p=central_lake` 刷新恢复一致；列表/地图/URL/右栏同为 CN-02 |
| 4 | PASS | 连点 NW-01→CN-02→RI-03，最终数据=river_inlet；最后一次 observations/quality/explanations 请求归属均为 river_inlet |
| 5/6 | PASS | 搜索"NW"剩 1 项且 aria-pressed 正确；清除后恢复 6 分区 |
| 7/8 | PASS | 单点仅标记+稀疏提示；1 行接口返回的模拟观测，0 个 0 填充 |
| 9 | PASS | T+1/3/7/15 切换正常；9b 阻断注入下切换 T+1 期间旧档位分数不展示（T+15 残值清零）；9c 失败可见且重试后展示 T+1 档位数据 |
| 10 | PASS | T+30 阻塞文案且 horizon_days=30 接口调用=0 |
| 11 | PASS | 驱动因素含演示规则声明、无 SHAP 字样 |
| 12/13/14/15 | PASS | 键盘←→切换 Tab；弹窗 role=dialog；取消 warnCalls=0；确认后 POST 200 仅模拟状态 |
| 16 | PASS | 16a 底栏 fixed 贴底(bottom=vh=844)；16b 抽屉焦点移入(6 项)；16c Esc 关闭且焦点返回触发按钮 |
| 17 | PASS | 27 个触摸目标全部 ≥44×44（chips/tabs/stage-btns/layer-toggles/底栏 + R2 补入的 Leaflet 缩放按钮 ×2，实测 44×44） |
| 18 | PASS | 390px scrollWidth=390 无横向溢出 |
| 19 | PASS | vh=1080 全部核心区块 ≤1013，Tab 行底 1069，**overflow=none**；Tab 明细面板允许下探（已注明） |
| 20 | PASS | P01 驾驶舱 / P07 热力图 / 历史页回归正常 |
| 21 | PASS | 控制台 0 error |
| 22 | PASS | 自检子进程断言失败退出码 1 |

## 6. 构建结果与包体积

`npm run build` 成功（8.8s，仅既有的 EChart>500kB 警告）。dist 总计 **1.2MB**：`Stations` 页面 chunk **45.78kB (gzip 14.91)** + CSS 30.89kB (gzip 5.21)；共享 chunk 未变：EChart 607.99kB (gzip 201.65)、LakeMap 157.36kB (gzip 46.66)。

## 7. 控制台与网络错误

控制台 error **0**（修复了地图容器 `flex:1` 塌缩导致的 20 次 leaflet-heat `IndexSizeError`；9b 故意阻断产生的 `net::ERR_FAILED` 资源日志属预期注入，脚本已按模式剔除）。业务网络请求全部 200；唯一失败请求为 9b 用例中经 CDP `Network.setBlockedURLs` 故意阻断的 `horizon_days=1`（status=0），用于验证错误态展示与重试。

## 8. 截图路径（reports/audit4-screenshots/）

`stations-1920.png`、`stations-1440.png`、`stations-390.png`、`stations-drawer-390.png`、`stations-warning-confirm.png`

## 9. git status --short（本任务相关部分）

```
 M dist/index.html                + dist/assets 哈希更替（重建产物）
 M src/pages/Stations.vue
 M src/services/api.js
?? src/components/stations/       （8 个新文件）
?? reports/audit4-verify.mjs
?? reports/audit4-run6.log
?? reports/audit4-screenshots/    （5 张）
?? reports/audit4-delivery-report.md / audit4-codex-prompt*.md / audit4-codex-review*.md
```

其余条目（`data-cleaning/**`、`reports/audit2-*`、`reports/data-generation-*`）为并行任务的现场，本任务未触碰；其中 data-cleaning 的状态变化来自并行会话自己的提交（`c05abf6`、`52c9ec5`，当前 HEAD 即 `52c9ec5`）。

## 10. 未修改声明

**没有修改** P07（Heatmap.vue）、History.vue、Home.vue、Cockpit.vue、layouts/**、AppSidebar/AppTopBar、backend/**、algorithms/**、shenji-pan/**、data-cleaning/**；`dist` 仅为整体重建。

## 复验环境备注

- 复验命令：`node reports/audit4-verify.mjs`（可用 `VERIFY_BASE` 覆盖目标地址，默认 `http://localhost:4173`）
- preview 服务器运行在 4173（已构建最新 dist），后端经 vite 代理可用；审计方可直接重跑

## 返工记录 R1（依据 Codex 审计 reports/audit4-codex-review.md，VERDICT: REWORK）

| # | Finding | 修复 |
|---|---|---|
| 1 (major) | 档位互切未立即失效 `rankForecasts`：新档位响应到达前旧预测被新标签沿用；六分区请求之一失败时旧值持续展示且被 brief 的 forecast-state 判定（原 line 117）判为 ok 掩盖错误 | `Stations.vue` stageKey watcher 切换瞬间清空 `rankForecasts` 并置 `rankState='loading'`、清空旧 `explanation`；`fetchRanking` 无条件进入 loading、catch 时清空 `rankForecasts` 再置 error——错误态下不再有任何残值可展示，brief 自动落到错误面板 |
| 2 (minor) | 验收 9 只核对按钮与 URL | 新增 9b/9c：经 CDP `Network.setBlockedURLs` 阻断 `horizon_days=1` 注入失败——9b 断言切换期间旧档位 sf-score 不展示（加载/失败二态）；9c 断言错误文案可见、点重试后展示 T+1 档位分数与档位值 |
| 3 (minor) | 验收 4 竞态断言不足 | check 4 增加 ownership 断言：最后一次 observations/quality/explanations 请求实体必须等于最终选中分区（run5 实测三者均为 river_inlet） |
| 4 (minor) | 报告将 `value_origin=simulated` 记录称为"真实观测"，违反数据红线口径 | 报告与本脚本 check 8 文案统一改为"接口返回的模拟观测" |

修复后复验：`reports/audit4-run5.log` —— **27/27 PASS，EXIT_CODE 0**（新增 9b/9c 两条断言；check 4 断言加严）。

## 返工记录 R2（依据 Codex 复审 finding [P1]，VERDICT: REWORK）

| # | Finding | 修复 |
|---|---|---|
| 1 (P1) | 390px 实测 Leaflet "+/−" 缩放按钮均 30×30px，不满足主要触摸目标 ≥44×44；且 `audit4-verify.mjs` 触摸目标选择器漏检 `.leaflet-control-zoom a`，"25 个目标全部达标"存在覆盖缺口 | `Stations.vue` ≤640px 媒体查询新增 `.stn-map-wrap :deep(.leaflet-control-zoom a) { box-sizing:border-box; width/height/min-44px; line-height:44px }`（页面级 `:deep()` 覆盖，仅影响 P03 地图，不改 P01 的 LakeMap 全局行为）；脚本选择器补入 `.leaflet-control-zoom a` |

R2 修复后复验：`reports/audit4-run6.log` —— **27/27 PASS，EXIT_CODE 0**；触摸目标 25→**27 个全部达标**，其中 `.leaflet-control-zoom a` ×2 实测 **44×44**；18 无横向溢出（scrollWidth=390）；16a 底栏贴底（bottom=vh=844）；控制台 0 error（地图无塌缩/挤压）；`npm run build` 通过；`stations-390.png` 已更新。
