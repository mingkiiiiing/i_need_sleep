# audit9 废弃资产清理清单（removed-assets）

生成时间：2026-09-06。清理基线：第八任务检查点 `72a7b7b`。
逐项删除均有依据：无引用（全仓 grep 0 命中）或仅服务于已废弃页面/配置路径。

## 一、废弃页面与路由

| 文件/位置 | 处置 | 依据 |
|---|---|---|
| `src/pages/Wallboard.vue`（1070 行） | **删除** | `/wallboard` 为第九任务明令废弃页面；删除后 `/#/wallboard` 由路由兜底进入 404（audit9 E 组实测） |
| `src/main.js` 中 `/wallboard` 路由项与 `Wallboard` 懒加载导入 | **删除** | 同上；正式路由收敛为 5 页 + 404 兜底 |
| `src/App.vue` 的 `route.meta.fullscreen` 分支 | **删除** | 该分支仅服务于 Wallboard 全屏渲染（全仓唯一 `fullscreen` meta 使用者），删除后 App 恒走 AppShell |

## 二、无引用组件

| 文件 | 处置 | 依据 |
|---|---|---|
| `src/components/HeroShell.vue` | **删除** | 全仓 grep 无任何 import/引用 |
| `src/components/cockpit/CockpitSubTabs.vue` | **删除** | 同上 |
| `src/components/common/PageHeader.vue` | **删除** | 同上 |

## 三、无引用服务层与 mock 数据源

| 文件 | 处置 | 依据 |
|---|---|---|
| `src/services/adapters.js` | **删除** | 全仓无引用（仅被同样无引用的 `_mapping.js` 依赖） |
| `src/services/_mapping.js` | **删除** | 唯一引用方 adapters.js 已删除 |
| `src/services/mock.js`（15 个导出） | **删除** | 仅被 `api.js` 的 `USE_MOCK` 配置路径引用；仓库无任何 `.env` 设置 `VITE_USE_MOCK`，属废弃开发期数据源；api.js 文件头注释本身即声明"默认不在接口失败时切换另一套数据源" |
| `src/services/api.js` 的 `USE_MOCK`/`useConfiguredSource`/`import * as mock` | **删除** | mock.js 删除后的连带重构；11 个原 mock 包装函数改为直连后端，行为与默认配置完全一致 |

## 四、无引用 API 导出（api.js）

| 导出 | 处置 | 依据 |
|---|---|---|
| `getSpatialEntity` | **删除** | 五页 0 引用（列表接口 `getSpatialEntities` 保留，首页/站点页在用） |
| `getRiskPolygonsEnvelope` | **删除** | 0 引用（风险矢量面为后端"不提供"能力，空面披露在 Heatmap 内由 risk-grid 承担；后端接口本身保留，未来算法接入不受影响） |
| `getPointDetail` | **删除** | 0 引用（驾驶舱点位数据经 `/cockpit/points` 列表获取） |
| `getPrediction` | **删除** | 0 引用（预测经 `getForecastsEnvelope` 获取） |

保留说明：`getExplanation`（Cockpit 在用）、`handleWarning`/`getTimeline`（History/模拟预警在用）等全部保留；后端契约接口一律不在前端删除（`/map/risk-polygons` 后端路由不动）。

## 五、数据文件与静态资源

| 文件 | 处置 | 依据 |
|---|---|---|
| `src/data/points.js` | **保留**（头注释已修正） | 活代码：驾驶舱 store 档位、首页湖面分区静态回退（接口失败时如实降级并展示错误态）。原"mock 数据源"陈旧注释已于返工轮改为"前端静态演示数据：接口优先、静态回退（不静默切换）" |
| `src/data/taihuOutline.js`、`dataIdentity.js` | **保留** | 五页在用 |
| `public/` 静态资源目录 | 不存在 | 无可清理项 |

## 六、npm 依赖核查

| 依赖 | 结论 |
|---|---|
| `echarts` | 在用（EChart.vue / Heatmap / Stations / History 图表） |
| `leaflet` / `leaflet.heat` | 在用（LakeMap 动态 import，热力图层） |
| `vue` / `vue-router` / `vite` / `@vitejs/plugin-vue` | 在用 |
| 新增 devDependencies（第八任务）：`puppeteer-core`、`@puppeteer/browsers` | 复验脚本专用，非运行时依赖 |

结论：**无未使用 npm 依赖需要删除**。

## 七、活动文档与根目录维护脚本（返工轮补充）

首轮清理后审计指出：活动文档仍在指导使用已删除功能，根目录 Git 跟踪的一次性维护脚本
仍引用已删除 API——"无引用"的结论此前只覆盖了 `src/**`，不成立。返工轮处置：

### 7.1 根目录维护脚本（8 个，全部删除）

| 文件 | 处置 | 依据 |
|---|---|---|
| `inject-ai.cjs` | **删除** | 引用已删除的 `getPrediction` 等接口（审计点名）；一次性源码注入脚本 |
| `patch-stations.cjs` | **删除** | 同上（审计点名，2 处已删 API 引用） |
| `fix4.cjs` | **删除** | 一次性源码行级修补脚本（对 src/pages/Stations.vue 打补丁），修补目标早已合入，无运行价值 |
| `regression2.cjs` / `repro-back.cjs` / `repro-back2.cjs` / `test-back.cjs` / `test-heatmap.cjs` | **删除** | 一次性 playwright 调试/回归脚本；依赖 `playwright`（package.json 从未安装），不可运行；职责已由 `reports/audit9/audit9-verify.mjs`（167 项、可复跑、run_id 化）取代 |

### 7.2 活动文档修正

| 文档 | 修正 |
|---|---|
| `README.md` | 删除"3.3 切换数据源"整节（VITE_USE_MOCK 配置说明）；目录树移除 HeroShell/CockpitSubTabs/PageHeader/mock.js，改为按子目录描述真实组件结构；数据源说明改为"前端只连接后端" |
| `INTEGRATION.md` | 删除"数据源切换"节的 mock 配置说明，改为"数据源说明：前端只连接后端" |
| `backend/README.md` | 删除 VITE_USE_MOCK 指引，改为"前端只连接后端，无 mock 数据源" |
| `src/data/points.js` 头注释 | 删除"mock 数据源"陈旧说明，改为"前端静态演示数据：接口优先、静态回退（不静默切换）" |

### 7.3 白名单（历史记录，不扫描、不篡改）

`reports/audit1-8/**`（历史审计报告）、`history/**`（git bundle 历史包）、
`design-export/**`、`codex-handoff-summary-2026-07-25.md`（历史交接文档）、
`里程碑7_成员C机理AI融合建模/**`、`shenji-pan/**`、`private/**`、`data-cleaning/**`（禁改现场）。

## 八、删除后验证

- `npm run build` 通过；`dist/**` 重建后 grep `wallboard|综合展示大屏|P02|P08` 0 命中。
- `src/**`、6 份活动文档、`scripts/**` 同规则扫描 0 命中；五页可见文本同规则 0 命中（audit9 F 组）。
- 15 个已删除路径确认不存在；根目录无 `.cjs` 维护脚本；活动文档无 `VITE_USE_MOCK` 与已删 API 引用。
- `/#/wallboard`、`/#/p02`、`/#/p08`、`/#/p02/detail` 全部进入 404 页且 URL 不改写（audit9 E 组）。
- 五页 167 项自动化全过（run_id=2026-09-06T06-49-03-068Z），构建与页面行为无回归。
