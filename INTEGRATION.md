# 后端对接说明（INTEGRATION）

> 最后更新：2026-07-30
> 适用范围：A23 · 蓝藻水华监测预警 · 前端 ↔ 后端联调

---

## 1. 启动方式

### 后端（FastAPI mock）

```bash
cd backend
# 推荐 Python 3.12+，依赖已在 requirements.txt 锁定
pip install -r requirements.txt

# 启动 mock 服务（默认端口 8000）
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- 接口根：`http://127.0.0.1:8000`
- 接口文档：`/docs`（Swagger）、`/redoc`
- 已配 CORS `*`

### 前端（Vue 3 + Vite）

```bash
npm install
npm run dev
```

- 前端开发服：`http://127.0.0.1:5173`
- `vite.config.js` 已配代理：`/api/*` → `http://127.0.0.1:8000`，前端代码统一用 `/api` 相对路径

> 演示前请先启动后端；后端未起时，`USE_MOCK=false` 下前端会按接口降级到 mock。

### 总开关

`src/services/api.js`：

```js
const USE_MOCK = false   // true = 全 mock；false = 接后端（带降级）
```

---

## 2. 后端接口清单（9 个）

| # | 接口 | 方法 | 说明 |
|---|---|---|---|
| 1 | `/api/health` | GET | 健康检查 |
| 2 | `/api/sites` | GET | 监测站点列表（8 个） |
| 3 | `/api/dashboard/overview` | GET | 驾驶舱总览（summary + trend + recent_warnings） |
| 4 | `/api/predict` | POST | 模型预测（多模型对比 + 评估指标） |
| 5 | `/api/explain` | POST | 可解释性（SHAP + 置信区间 + 敏感度曲线） |
| 6 | `/api/map/risk` | GET | 风险地图热力点（返回 42 个点位，非网格） |
| 7 | `/api/warnings` | GET | 预警列表（query 参数：`limit`、`status`） |
| 8 | `/api/warnings/{id}/handle` | POST | 处置预警（模拟短信/邮件推送） |
| 9 | `/api/timeline` | GET | 历史回溯（query 参数：`start_date`、`end_date`） |

返回统一格式：

```json
{ "code": 200, "msg": "success", "data": { ... } }
```

---

## 3. 接入映射（前端 service ↔ 后端接口）

| 前端 service | 后端接口 | 适配器 | 兜底 |
|---|---|---|---|
| `getTimeStages()` | ❌ 无 | — | mock（前端硬编码 未来 1/3/7/15/30 天） |
| `getPoints()` | `/api/sites` | `adaptSites()` | mock（forecast/factors/trend/timeline 等仍走 mock） |
| `getPointDetail(id)` | `/api/sites` | 复用 `getPoints()` | mock |
| `getHeatField()` | `/api/map/risk` | `adaptHeatField()` | mock |
| `getEvents()` | `/api/warnings?limit=15` | `adaptWarnings()` | mock |
| `getRegionSummary()` | `/api/dashboard/overview` | `adaptRegionSummary()` | mock（intensity 来自 mock） |
| `getPrediction(stationId)` | `/api/predict` | 直接透传 | 无（前端必填后端站点 ID） |
| `getExplanation(predictionId)` | `/api/explain` | 直接透传 | 无 |
| `handleWarning(id)` | `/api/warnings/{id}/handle` | 直接透传 | 无 |
| `getTimeline(start, end)` | `/api/timeline` | 直接透传 | 无 |

**链式调用**：`getPoints()` 之后会拿到 `_backendId`（如 `S001`）；页面渲染时用 `_backendId` 调 `getPrediction()` → 拿到预测，再生成临时 `predictionId` 调 `getExplanation()`。

---

## 4. 站点 ID 映射表

后端 8 个站点保留，前端展示 6 个太湖点位：

| 后端 ID | 前端 key | short | name（前端） |
|---|---|---|---|
| S001 | `northwest_hotspot` | NW-01 | 西北热点区 |
| S002 | `central_lake` | CN-02 | 湖心浮标 |
| S003 | `river_inlet` | RI-03 | 入湖河口 |
| S004 | `southeast_station` | SE-04 | 东南监测站 |
| S005 | `water_intake` | WI-05 | 取水口 |
| S006 | `south_channel` | SC-06 | 南部通道 |
| S007 | — | — | 不在前端使用（白洋淀-烧车淀） |
| S008 | — | — | 不在前端使用（洱海-北部） |

定义位置：`src/services/_mapping.js` 的 `SITE_ID_MAP`。

---

## 5. 字段命名差异

| 后端字段 | 前端字段 | 说明 |
|---|---|---|
| `id`（如 `S001`） | `id`（如 `northwest_hotspot`） | 映射表转换 |
| `lat` / `lng` | `coord.lat` / `coord.lon` | 字段重组 |
| `risk_level: "medium"` | `riskClass: "mid"` | `medium` → `mid` |
| `warning_id` | `id` | 预警 ID 重命名 |
| `station_id` | `point` | 站点引用重命名 |
| `risk_level` | `severity` | 事件等级字段名不同 |
| `risk_level_name` | 显示在 `title` | "高风险"、"中风险" 等 |
| `trigger_factor` | 拼接进 `title` 和 `summary` | |
| `high_risk_count` / `medium_risk_count` / `low_risk_count` | `riskCounts.high` / `riskCounts.mid` / `riskCounts.low` | `medium → mid` |
| `grid_points[]`（点位） | `t1/t3/t7/t15/t30` 五张 11×19 网格 | **几何分桶转换**（见 6） |
| `model_comparison.mechanism_model` 等 | 直接透传 | Tab 1 用 |
| `feature_importance[].contribution` | 直接透传 | Tab 2 用 |

---

## 6. 热力图点位 → 网格分桶

后端 `/api/map/risk` 返回 42 个 `{lat, lng, risk_value, chlorophyll}` 点位，预期范围：

```
lat: [31.33, 31.62]
lng: [120.08, 120.42]
```

前端需要 11×19 网格（按 stage 分，5 个 stage）。前端适配：

```js
// src/services/adapters.js → adaptHeatField()
// 经纬度 → 网格坐标
col = floor((lng - 120.08) / 0.34 × 19)
row = floor((31.62 - lat) / 0.29 × 11)
// 同一格子内 risk_value 取均值 → 0-100 显示值
```

**注意**：后端当前只返回太湖点位，不分 stage。前端目前**5 个 stage 共用同一张网格**，切档不改变热力图分布（见缺口 #1）。

---

## 7. 适配器与降级策略

### 适配器（src/services/adapters.js）

- `adaptSites(backendSites)` → `{pointData, pointPositions}`
  - 用后端 ID 映射覆盖的 6 个站点填基础字段（`id/name/short/risk/riskClass/coord/summary`），缺失字段从 mock 兜底
  - 给每个映射点位补 `_backendId` 字段（链式调用需要）
  - 未被后端覆盖的 4 个前端点位，整段从 mock 取
- `adaptWarnings(backendWarnings)` → 事件流数组
- `adaptHeatField(gridPoints)` → `{t1, t3, t7, t15, t30}` 5 张网格
- `adaptRegionSummary(backendOverview)` → `{totalStations, riskCounts, intensity, summary, trend, recentWarnings}`
  - `riskCounts` 优先从前端实际显示的 `pointData` 重新计算（保证和 `totalStations` 一致）

### 降级（src/services/api.js）

```js
async function withFallback(primary, fallback) {
  if (USE_MOCK) return fallback()
  try {
    return await primary()
  } catch (err) {
    console.warn('[api] fallback to mock:', err.message)
    return fallback()
  }
}
```

任意接口报错都会自动回退到 mock，**演示不会因后端挂掉而翻车**。

---

## 8. 页面与接口的关系

| 页面 | 用到的接口 | 备注 |
|---|---|---|
| `/` Home | — | 纯静态 |
| `/stations` | `/api/sites` + `/api/predict` + `/api/explain` | 双 Tab（模型对比 / SHAP 解释）+ 链式调用 |
| `/heatmap` | `/api/sites` + `/api/dashboard/overview` + `/api/map/risk` | KPI / 网格 / 强度排行 |
| `/history` | `/api/warnings` + `/api/warnings/{id}/handle` + `/api/timeline` | 事件流 + 推送 + 日期筛选 |

---

## 9. 修复的 pre-existing bug（顺手处理）

| 文件 | 问题 | 修复 |
|---|---|---|
| `src/pages/Stations.vue` | `selectedPoint.*` 无空值守卫，初次渲染崩溃 | 给 `selectedPoint` 加 `\|\| {}` 兜底，模板用 `(x.y \|\| dash)` 守卫 |
| `src/pages/Stations.vue` / `History.vue` | `useCockpitStore()` 返回 readonly，写入点变更无效 | 引入 `cockpitState()`（writable）并用于所有写入点 |
| `src/main.js` | hash 路由 + 直接 deep link 时，浏览器后退掉到 `about:blank` 整页空白 | 路由 `afterEach` 压 `{sentinel:true,from:path}` 占位 history 项；`popstate` 监听 sentinel 被 pop 时再 `pushState` 回去，使返回永远在站内 |
| `src/pages/Stations.vue` / `Heatmap.vue` / `History.vue` | 这三个子页面没有返回入口 | `<main>` 末尾加 `<footer class="cockpit-foot">` 返回驾驶舱按钮，风格与 Cockpit 统一 |

**注意**：
- `useCockpitStore()` 仍保留用于读取，绑定 URL hash 同步；写入统一走 `cockpitState()`。
- 返回入口的 `<footer>` 必须放在 `<main>` 内部，否则组件多根节点会触发 `<Transition>` 警告。

---

## 10. 给后端同学的缺口清单（建议补）

按"演示效果 / 改动量"排序：

### P1 · 影响大，建议尽快补

1. **`/api/map/risk` 加 stage 维度**
   - 现在只返回太湖点位 + 一个时间快照，热力图切档不变
   - 建议：query 参数加 `stage` (t1/t3/t7/t15/t30)，按 stage 返回不同 `grid_points`，或直接返回 5 张网格

2. **`/api/sites` 补完整字段**
   - 现在只有 `{id, name, lat, lng, risk_level}` 4 字段
   - 前端需要 `forecast/factors/trend/timeline/metrics/explainability` 等，目前用 mock 兜底显得"半真半假"
   - 建议：新增 `GET /api/sites/{id}` 返回该站点的完整详情（含预报、因子、历史等）

3. **`/api/predict` 返回 `prediction_id`**
   - 现在不返回，前端只能自造 `PRED-{station_id}-{ts}` 给 explain 用
   - 建议：predict 成功时返回 `{...results, prediction_id: "uuid"}`，前端真正链式调用

### P2 · 演示更完整

4. **`/api/timeline` 增加按 stage 聚合**
   - 现在按天聚合，给的指标是当天的 `avg_chlorophyll` 等
   - 建议：可选按 `forecast_stage` 返回预报表的逐日序列

5. **前端站点名映射**
   - 后端返回的 `name` 是 `"太湖-贡湖湾"` / `"巢湖-湖心区"` 等
   - 前端映射到 6 个"太湖点位"时会出现名实不符（`S003` 是巢湖，但前端叫"入湖河口"）
   - 建议：要么后端全部用太湖点位，要么前端显示用前端名字、tooltip 显示真实名字

### P3 · 可选

6. **`/api/explain` 接收站点 ID**
   - 目前要求 `prediction_id`，但 ID 是后端生成的
   - 建议：要么接受 `station_id` 自动内部生成 prediction_id，要么前端继续自造 ID（当前实现）

7. **`/api/warnings` 加 stage 字段**
   - 现在返回时间、站点、等级、状态等，但没有"对应哪个 forecast 档位"
   - 建议：生成预警时根据当时的 forecast 状态打 stageKey 标签

---

## 11. 快速排错

### 接口走通但页面没数据

- 打开 DevTools → Console，看 `[api] fallback` 警告
- 看 Network → `/api/sites` 等接口的响应是否 `{code:200, data:...}`
- 看 Application → Session Storage 是否有登录态

### 后端启动失败

- 检查端口：`netstat -ano | findstr 8000`
- 看 uvicorn 输出，常见是依赖版本（`pydantic` 等）

### 前端代理失败

- `vite.config.js` 改了之后需要重启 `npm run dev`
- 直接请求 `http://127.0.0.1:5173/api/health` 看是否走通

### 切换点位不响应 / 切换不生效

- 之前是 readonly 问题，已修。如仍出现，请检查 `cockpitState()` 是否正确导入

---

## 12. 文件索引

```
src/
├── services/
│   ├── api.js           # 统一 service 入口（fetch + 解包 + 降级）
│   ├── adapters.js      # 5 个后端→前端数据适配器
│   ├── _mapping.js      # 站点 ID 映射表 + 字段字典
│   └── mock.js          # 兜底数据（带 sync 版本供适配器使用）
├── pages/
│   ├── Stations.vue     # 双 Tab（模型对比 / SHAP 解释），链式调用
│   ├── Heatmap.vue      # 网格 + KPI + 强度榜
│   └── History.vue      # 事件流 + 推送 + 日期范围 timeline
├── stores/
│   └── cockpit.js       # 全局状态（stageKey/selectedPoint/currentEventId/playing/speed）
└── components/
    └── cockpit/
        ├── LakeMap.vue  # 地图点位
        └── EChart.vue   # ECharts 容器

vite.config.js           # 加了 /api → :8000 代理
backend/main.py          # 9 个 mock 接口
```
