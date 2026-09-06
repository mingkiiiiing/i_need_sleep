# audit9 交付报告：废弃页面清理与最终交付冻结

生成时间：2026-09-06。结论：**第九任务全部完成条件满足**，等待独立审计。
正式运行 **run_id=2026-09-06T06-49-03-068Z：167/167 PASS、status=passed、退出码 0**；
`npm run build` 通过；`git diff --check` 通过。

## 一、前置动作确认

1. **第八任务报告陈旧文字**：已修正，全目录无旧 `started_at`（04:12:30.103Z）与
   "第四轮"表述，材料与正式 JSON 的 run_id/started_at/finished_at 完全一致。
2. **第八任务 Git 检查点**（复审 PASS 后建立）：**`72a7b7b`**，提交后工作区全净，
   第九任务在该基线上进行。

## 二、系统最终形态：仅保留五个正式页面

| 路由 | 页面 | 状态 |
|---|---|---|
| `/` | Home.vue | ✓ 保留 |
| `/cockpit` | Cockpit.vue | ✓ 保留 |
| `/stations` | Stations.vue | ✓ 保留 |
| `/heatmap` | Heatmap.vue | ✓ 保留 |
| `/history` | History.vue | ✓ 保留 |
| `/:pathMatch(.*)*` | NotFound.vue | ✓ 404 兜底 |
| ~~`/wallboard`~~ | ~~Wallboard.vue~~ | **已删除**（路由 + 页面 + App.vue fullscreen 唯一消费分支） |
| P02 / P08 | （从未有对应实现） | 全仓扫描 0 残留；`/#/p02`、`/#/p08`、`/#/p02/detail` 实测 404 |

## 三、清理清单（详见 removed-assets.md）

- **删除文件 15 个**：
  - 废弃页面与死组件/服务（8 个）：Wallboard.vue、HeroShell.vue、CockpitSubTabs.vue、
    PageHeader.vue、adapters.js、_mapping.js、mock.js（15 个导出；mock 配置从未启用）；
  - 根目录一次性维护脚本（8 个 .cjs，返工轮补充）：inject-ai.cjs、patch-stations.cjs
    （引用已删除 API，审计点名）及 fix4.cjs、regression2.cjs、repro-back.cjs、
    repro-back2.cjs、test-back.cjs、test-heatmap.cjs（一次性 playwright 调试脚本，
    依赖未安装的 playwright，不可运行，职责已由 audit9-verify.mjs 取代）。
- **死代码重构**：main.js 路由/导入、App.vue fullscreen 分支、api.js 的
  USE_MOCK/useConfiguredSource 包装（11 个函数改直连后端）与 4 个零引用导出
  （getSpatialEntity、getRiskPolygonsEnvelope、getPointDetail、getPrediction）。
- **活动文档同步（返工轮）**：README.md（删除 mock 切换说明与已删组件目录项，目录树
  按真实结构重写）、INTEGRATION.md、backend/README.md（删除 mock 配置指引，改为
  "前端只连接后端"）；src/data/points.js 头注释由"mock 数据源"改为"静态回退"说明。
- **保留边界**：后端契约接口（含 /map/risk-polygons）不因前端暂不调用而删除；
  `data-cleaning/**`、`backend/**` 零改动；npm 依赖核查无未使用项。
- **删除量**：src 净变化 +15/−56 行（api.js 重构）+ 15 个整文件删除；构建产物同步重建。

## 四、导航与路由行为（全部由 audit9-verify.mjs 实测）

- 侧栏恰好五个正式入口；首页四张业务卡逐卡点击导航正确（C 组）。
- 跨页状态：P01 排行选点 → URL `?p=` 同步 → 站点页选中同一分区；返回/前进保持；
  cockpit 参数冷启动/刷新/非法参数清理；冷启动与同文档跳转签名一致（D 组）。
- **旧地址 404**：`/#/wallboard`、`/#/p02`、`/#/p08`、`/#/p02/detail` 均渲染 404 页、
  URL 不改写、不自动跳转，提供回首页/驾驶舱入口（E 组）。
- **残留扫描**：`src/**`、`dist/**`、6 份活动交付文档、`scripts/**`、五页可见文本对
  `wallboard|综合展示大屏|P02|P08` 0 命中；禁用声明词（真实预测/正式预警/算法已验证）
  0 命中；15 个已删除路径确认不存在、根目录无维护脚本、活动文档无 mock 配置与已删
  API 引用（F 组，历史报告/交接文档白名单不扫描）。
- **全站无冻结链接**：五页 DOM 断言 10 项（B 组）。

## 五、视觉一致性与可访问性（B/G 组实测）

- 三视口（1920×1080 / 1440×900 / 390×844）：无横向溢出、`<main>` 唯一、地图署名可见。
- 移动端触摸目标：全页测量 home 23 / cockpit 40 / stations 36 / heatmap 49 / history 21
  个交互元素，均 ≥44×44；history 底部操作栏 fixed 贴底。
- 深色主题默认生效（useTheme：合法 localStorage 保存值优先，否则固定 dark）。
- 来源抽屉：role=dialog + aria-modal、不超视口、Esc 关闭、Tab 圈定、焦点归还（G 组）。
- 本任务未对页面做任何视觉重设计——仅删除与死代码重构，五页视觉与第八任务审计通过时一致。

## 六、控制台与网络

详见 `console-network-report.md`：21 个会话**硬控制台错误 0、pageError 0、第一方资源
失败 0、未解释 4xx/5xx 0**；唯一信号为 D 组多跳导航中止的 5 条第三方 ArcGIS 瓦片
ERR_ABORTED（跨域第三方、逐条记录、分级不计入第一方门禁）；豁免清单为空。

## 七、自动化复验（audit9-verify.mjs）

继承第八任务已固化的复验框架（CDP → 固定版本 chrome-headless-shell@152.0.7977.82 →
系统浏览器三级方案；run_id 防陈旧；异步清理；`browser.ok` 硬断言），按第九任务要求
新增：废弃路由 404 组、源码/构建产物/可见文本残留扫描组、超范围声明扫描组；移除
第八任务的错误注入与竞态组（属第八任务验收面）。共 **167 项**，逐项 PASS/FAIL。

返工轮扩展（P2-1）：残留扫描正则实际覆盖 `wallboard / 综合展示大屏 / P02 / P08`；
扫描范围扩展至 6 份活动交付文档与 `scripts/**`（历史审计报告、history bundle、
历史交接文档列入白名单，不扫描、不篡改）；新增断言：15 个已删除路径不存在、
根目录无 `.cjs` 维护脚本、活动文档无 `VITE_USE_MOCK` 与已删 API（getPrediction/
useConfiguredSource/services/mock.js）引用。

返工轮扩展（P2-2）：`ensureServices()` 失败时先回滚自身已启动句柄再抛出；服务初始化
纳入统一 `try/finally`，任何路径都不再于清理前直接 `process.exit`。两类负向实测：
① 自建后端成功 + 外部前端不可达 → 打印"初始化失败，回滚已启动服务"→ FATAL、
退出码 2、status=fatal、8629 无残留监听；② 显式浏览器路径启动失败 → 3 次尝试
全记录（均 `ok=false`）→ FATAL 退出码 2、status=fatal、无残留监听。

- 正式运行：**167/167 PASS，status=passed，退出码 0**（run_id=2026-09-06T06-49-03-068Z）。
- 环境说明：前端默认端口由 4180 改为 4191——4190 被 Node fetch(undici) 列为 bad port。

## 八、截图（reports/audit9/screenshots/，19 张）

五页 × 1920/1440/390 共 15 张；`404-wallboard-1440.png`；`home-source-drawer.png`、
`history-drawer-390.png`、`stations-drawer-390.png`。

## 九、完成条件逐条对照（任务书第六节）

| 条件 | 结果 |
|---|---|
| 第八任务已提交且基线明确 | ✓ `72a7b7b`，提交后工作区全净 |
| 系统只剩五个正式页面 | ✓ 路由表 + 残留扫描实证 |
| `/wallboard`、P02、P08 完全退出正式产品 | ✓ 页面/路由/入口/文案 0 残留，旧地址 404 |
| 自动化全部通过 | ✓ 167/167，status=passed，退出码 0 |
| 构建通过 | ✓ npm run build |
| Git 范围仅前端清理、构建产物、reports/audit9/** | ✓ backend 与 data-cleaning 零改动 |
| 未提交第九任务 | ✓ 全部改动处于未提交状态 |

## 十、交付物清单

```text
reports/audit9/delivery-report.md          # 本文件
reports/audit9/removed-assets.md           # 废弃资产清理清单（逐项依据）
reports/audit9/route-final-matrix.md       # 最终路由矩阵与导航体系
reports/audit9/console-network-report.md   # 控制台与网络报告
reports/audit9/git-scope.txt               # Git 范围证明
reports/audit9/audit9-verify.mjs           # 自动化复验脚本（167 项）
reports/audit9/verify.log                  # 正式运行日志（167/167，退出码 0）
reports/audit9/verify-results.json         # 逐项结果（run_id/status/时间）
reports/audit9/console-network-report.json # 逐会话原始记录
reports/audit9/screenshots/                # 19 张验收截图
```

按任务要求在此停止：**不提交第九任务**，等待独立审计；审计 PASS 后建立最终 Git 检查点，
整个前后端页面重构阶段正式闭环。
