# audit9 最终路由矩阵（route-final-matrix）

生成时间：2026-09-06。基线：第八任务检查点 `72a7b7b`；系统收敛为**且仅保留**五个正式页面。

## 一、最终路由表（src/main.js）

| 路由 | 名称 | 页面 | 懒加载 | 状态 |
|---|---|---|---|---|
| `/` | home | Home.vue | ✓ | 正式保留 |
| `/cockpit` | cockpit | Cockpit.vue | ✓ | 正式保留 |
| `/stations` | stations | Stations.vue | ✓ | 正式保留 |
| `/heatmap` | heatmap | Heatmap.vue | ✓ | 正式保留 |
| `/history` | history | History.vue | ✓ | 正式保留 |
| `/:pathMatch(.*)*` | not-found | NotFound.vue | ✓ | 404 兜底（含 `/wallboard`、P02、P08 及任何未知路径） |
| ~~`/wallboard`~~ | — | ~~Wallboard.vue~~ | — | **已删除**（路由 + 页面文件 + 唯一消费者 App.vue fullscreen 分支） |

P02、P08：src 中从未存在对应页面/路由（历史仅存在于需求编号），本轮全仓扫描 0 残留；
`/#/p02`、`/#/p08` 及深链 `/#/p02/detail` 实测进入 404。

## 二、导航体系

| 入口 | 指向 | 校验 |
|---|---|---|
| 侧栏（AppSidebar） | 恰好 5 项：`/`、`/cockpit`、`/stations`、`/heatmap`、`/history` | 源码核对（items 数组）+ 截图 |
| 首页四张业务卡 | `/cockpit`、`/stations`、`/heatmap`、`/history` | audit9 C 组逐卡点击导航实测 |
| P01 → P03 | `/stations?t=<档位>&p=<分区>` | C 组实测：点击排行分区 → URL 同步 → 详情跳转携带同一 p |
| P01 → P07 / 历史 | `/heatmap`、`/history` | C 组实测 |
| P03/P07 返回 | BackLink + 浏览器后退 | C 组实测：goBack 保持 `?p=`，goForward 回站点页 |
| 404 页（NotFound） | 「返回上一业务页面」（仅当存在站内来源）、「回到首页」、「进入驾驶舱」 | E 组实测；无自动跳转 |
| 移动端底栏/抽屉 | history 底部操作栏 fixed 贴底；stations/history 抽屉 | G 组实测 |

全站（五页 DOM）不存在指向 `/wallboard`、P02、P08 的链接——B 组 10 项断言（5 页 × 1920/1440）全部通过。

## 三、URL 状态与冷启动

| 行为 | 实测结果（audit9 D 组） |
|---|---|
| cockpit `?t=t3&p=water_intake` 冷启动 | 参数保持，页面恢复选中态 |
| cockpit 刷新 | `t=t3&p=water_intake` 保持 |
| stations `?p=river_inlet&t=t7` 冷启动 + 刷新 | 选中 river_inlet 保持，签名一致 |
| cockpit `?t=bogus&p=bogus_zone` | 不白屏，非法档位被拒绝应用 |
| stations `?p=no_such_zone` | 不白屏，非法分区被规范化清理 |
| 冷启动 vs 同文档跳转 | cockpit/heatmap 签名一致 |
| 前进/后退 | 站点 ↔ 驾驶舱 p 状态往返保持 |

## 四、废弃路由 404 行为（audit9 E 组）

| 访问 | 结果 |
|---|---|
| `/#/wallboard` | NotFound 渲染（`.nf-code`=404），URL 保持 `#/wallboard`，不自动跳转 |
| `/#/p02` | 同上，URL 保持 `#/p02` |
| `/#/p08` | 同上，URL 保持 `#/p08` |
| `/#/p02/detail`（深链） | 同上，URL 保持 |

## 五、数据身份与声明边界

- 五页可见文本均包含对应域的 OBS/PRED/RUN/simulation_only 身份（B 组逐页断言）。
- 可见文本扫描禁用词 `真实预测 / 正式预警 / 算法已验证 / wallboard / 综合展示大屏`：五页 0 命中（F 组）。
- 公共身份栏（DataContextBar）全页统一展示 `SIMULATED｜OBS / PRED / RUN｜基准 08:00｜simulation_only`。

## 六、视觉一致性（audit9 B 组实测，run_id=2026-09-06T06-49-03-068Z）

| 视口 | 结果 |
|---|---|
| 1920×1080 | 五页渲染完整、`<main>` 唯一、无溢出、地图署名可见 |
| 1440×900 | 无重叠/裁切/横向滚动 |
| 390×844 | 无横向溢出；交互目标全页测量 23/40/36/49/21 个，均 ≥44×44 |
| 深色主题 | 默认 dark（useTheme：localStorage 合法保存值优先，否则固定 dark，不跟随系统） |
| Leaflet | 缩放控件、署名、图层失败提示（重试图层）正常 |
