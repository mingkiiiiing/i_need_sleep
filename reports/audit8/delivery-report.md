# audit8 交付报告：五页面全系统联调与最终体验验收

生成时间：2026-09-06（第五轮重新生成）。结论：**第八任务全部验收项通过**，等待独立复审。
正式运行 **run_id=2026-09-06T04-45-39-397Z：161/161 PASS、status=passed、退出码 0**；
后端 92/92；audit7 实机 64/64；`git diff --check` 通过；失败路径实测退出码 2、无残留监听、
结果文件即时落盘 `status=fatal`（不残留陈旧通过结果）；
终端汇总行与结果 JSON 使用同一计算状态（failed 时不再谎报 passed）。

## 一、任务前置

- **第七任务检查点**：按指示先提交审计确认的 5 个文件，提交哈希 **`7f21d32`**，
  提交后工作区全净，随后开始第八任务。
- **基线**（任务开始时实测）：`npm run build` 通过；`python -m pytest backend/tests -q`
  → 92 passed；`live_verify.py`（uvicorn 8617）→ 64/64、0 失败。基线运行刷新的
  `reports/audit7/live-api-verification.json` 已恢复至检查点版本，audit7 材料保持冻结。
- **并行现场保护**：5173/4173 端口旧 Vite 进程（PID 77588/16944）记录在案、未杀未占；
  自建服务用 4180（dist 静态 + /api 反代）与 8617/8618/8619/8621（临时 uvicorn，均已停止）。
  `data-cleaning/**` 全程零改动。

## 二、本任务代码改动（均在允许范围内，未新增功能、未重新设计）

| 文件 | 改动 | 对应要求 |
|---|---|---|
| src/data/dataIdentity.js | 事实源修正：`predictionRunId` 恢复后端语义 = DEMO-RUN-V1；新增 `predVersionId`=DEMO-PRED-V1、`claimBoundaryCode`=simulation_only；provenance 增加"预测运行"行 | 四·不能再用 predictionRunId 表示预测数据集版本；唯一事实源 |
| **src/pages/Home.vue** | **接入后端契约**：`/system/capabilities` + `/datasets/summary` + `/spatial-entities` 三接口并行加载；**按 CapabilitiesData 结构解析 `data.capabilities` 与 `data.blockers`**；能力卡四张全部由接口数据推导（实测：预测能力=1—15 天演示档位、长期能力=仅模拟预演，无 `—` 占位）；湖面分区位置/名称/风险、分区风险统计接口优先；身份行 meta 优先、事实源兜底；**loading / error（重试）/ empty（重试）/ ok 四态**，empty 判定按 `Object.keys(capabilities).length===0`；分区悬浮提示防溢出 | **P1**（结构解析+empty 可达）；四·meta 优先；五·四态 |
| **src/services/api.js** | 新增 `getSystemCapabilitiesEnvelope` / `getDatasetsSummaryEnvelope` | P1-1 |
| src/pages/Cockpit.vue | 预测版本回退修正、身份芯片接事实源；**移除"打开综合展示大屏"入口**；移动端缩放钮/署名链接 44px | P2-3；四；七 |
| src/pages/Stations.vue | predVersion 初始值修正、芯片接事实源；署名链接 44px | 四；七 |
| src/pages/Heatmap.vue | PRED/RUN 回退与芯片接事实源；缩放钮/署名链接 44px | 四；七 |
| src/pages/History.vue | 身份芯片与页脚由硬编码改为事实源引用 | 四 |
| src/components/common/DataContextBar.vue | 公共身份栏展示 OBS/PRED/RUN 三元组 + simulation_only；移动端"查看来源"≥44px | 四；七 |
| src/layouts/AppShell.vue | skip-link 最小高度 44px（视觉隐藏元素，无外观变化） | 七·触摸目标 |
| package.json | devDependencies 增加 puppeteer-core（复验脚本驱动本机 Edge，无运行时影响） | 九 |

backend/**、data-cleaning/**、P02、P08 源码：**零改动**。`Wallboard.vue` 文件零改动；
其直达路由 `/wallboard` 按审计意见保留至第九任务清理，但已不在任何正式页面的用户链路中
（五页链接断言见下）。

## 三、五页逐项联调（对应任务五，全部由 audit8-verify.mjs 实测）

| 检查项 | 首页 | P01 | P03 | P07 | 历史 |
|---|---|---|---|---|---|
| 首次加载/成功状态 | ✓（三接口，能力卡为接口真实值） | ✓ | ✓ | ✓ | ✓ |
| 空数据状态 | ✓ 200+空载荷注入 → empty 态+重试恢复 | —（无空态路径） | — | — | ✓ 未来区间查询诚实空态+重置恢复 |
| 业务错误 | ✓ | ✓ T+30 阻塞横幅 | ✓ 404/422 走错误态 | ✓ T+30 格网阻塞披露 | ✓ timeline 业务错误如实呈现 |
| 网络失败→重试恢复 | ✓ 三接口注入失败→错误态→重试恢复 | ✓ 地图数据错误面板 | ✓ spatial-entities 注入失败→重试恢复 | ✓ risk-grid 注入失败→grid-retry 恢复 | ✓ 各区块 retry 面板 |
| 快速切换旧请求不覆盖 | — | ✓ 连点四档稳定 T+15 | — | ✓ T+1 延迟 2s 迟到响应不覆盖 | — |
| 刷新后状态恢复 | ✓ | ✓ ?t&p 保持 | ✓ ?p&t 保持 | ✓ | ✓ 事件数一致 |
| 合法 URL 参数恢复 | ✓ | ✓ t=t3&p=water_intake | ✓ p=river_inlet&t=t7 | ✓ | ✓ |
| 非法 URL 参数清理 | — | ✓ t=bogus/p=bogus 拒绝+清理 | ✓ p=bogus 规范化 | — | — |
| 前进/后退 | ✓ | ✓ 站点↔驾驶舱 p 保持 | ✓ | ✓ | ✓ |
| 冷启动=同文档跳转 | ✓ | ✓ 签名一致 | ✓ | ✓ 签名一致 | ✓ |

## 四、跨页业务链路（任务六）

1. 首页四入口进入四个业务页面 ✓（href 逐一断言 + 实际导航）。
2. P01 排行点选分区 → URL 同步 `?p=` → 「查看站点详情」→ P03 选中同一分区 ✓。
3. P01 →「进入风险研判」→ P07 ✓。
4. P01/P07 →「进入事件复盘」→ 历史 6 条演示事件 ✓。
5. 详情返回后原页筛选与 URL 同步（goBack 保持 p，goForward 回站点页）✓。
6. 非法站点/事件/档位不白屏、不死循环（D 组三例注入）✓。
7. 页面事件 ID 与后端 /events canonical 集合一致，无未知 ID ✓。
8. **五页不存在指向 /wallboard、P02、P08 的链接**（B 组逐页断言，P2-3）✓。

## 五、响应式与可访问性（任务七）

- 三视口 1920×1080 / 1440×900 / 390×844 全部通过：无横向溢出（含首页分区悬浮提示
  小屏防溢出修复）、图表/地图正常、文字按钮无重叠。
- **移动端触摸目标 ≥44×44（P2-2 全页覆盖）**：390px 视口逐页测量全部已渲染交互元素——
  home 23 / cockpit 40 / stations 36 / heatmap 49 / history 21 个，均达标；
  抽屉/弹层等条件渲染控件在展开状态下单独测量（history 抽屉态 28 个）达标；
  结果输出测量数量与失败明细。本轮据此修复三处既有不足：Leaflet 30×30 缩放钮、
  Leaflet 署名/首页 OSM 署名小链接、AppShell skip-link（41px）。
- 历史页移动端底部操作栏 fixed 贴底 ✓；移动端抽屉 ✓。
- 每页仅一个 `<main>` ✓；「查看来源」抽屉 role=dialog + aria-modal=true、不超视口、
  Esc 关闭、Tab 圈定不逃逸、焦点归还触发按钮 ✓。
- 地图署名（Leaflet attribution）在 P03/P07 可见 ✓。

## 六、控制台与网络（任务八）

详见 `console-network-report.md`：15 个正式渲染会话**硬错误 0、pageError 0、
失败静态资源 0、未解释 4xx/5xx 0**（首页三接口纳入逐响应断言）；错误注入会话的
9 条 ERR_FAILED 为脚本主动制造（首页/stations/heatmap），逐条定性；豁免清单为空。

## 七、自动化复验（任务九）

`reports/audit8/audit8-verify.mjs`：puppeteer-core 驱动本机浏览器，覆盖 A 信封身份、
B 五页×三视口（含首页能力卡结构化消费断言）、C 跨页、D URL、E 空态/错误/重试
（含首页 200+空载荷与网络失败两类注入）、F 竞态、G ARIA 七组 **161 项**，逐项输出 PASS/FAIL。
E 组每个注入用例使用独立 page 会话（拦截/缓存互不串扰）。

**浏览器方案（P1 稳定复现）**：按优先级三级——① `AUDIT8_CDP_URL` 连接预启动浏览器
（CDP 连接，不拉起进程）；② **固定版本 chrome-headless-shell@152.0.7977.82**（经
`@puppeteer/browsers` 安装至 `reports/audit8/.browser-cache/` 本地缓存，缺失时一次性
自动安装；与系统 Edge 的运行状态/策略完全解耦，为本轮正式 run 实际采用方案）；
③ 系统 Edge/Chrome 兜底（ws / pipe / 精简参数三种方式逐次尝试）。`AUDIT8_EDGE`
显式指定则唯一且不存在即报错。启动成功后日志与结果 JSON 记录实际可执行文件、
浏览器版本、方案与 profile 路径；失败逐次记录完整错误于 `browser_diag.attempts`。
本轮实测：固定版本 `chrome-headless-shell@152.0.7977.82`（`HeadlessChrome/152.0.7977.82`）
首选成功，见 `verify-results.json` 的 `browser` 字段。

**网络失败分级**：第一方资源（同源静态 + /api/）失败仍为不通过项；第三方底图瓦片
（跨域，如 ArcGIS）受外部网络可用性影响，按条记录明细，并断言页面以图层错误态/
"重试图层"诚实处理——避免外部瓦片服务的瞬时可用性使验收门不确定。

**run 标识与防陈旧（P2）**：每次运行生成 `run_id`，运行开始即写入 `status=running`
占位（`finished_at=null`，仅终态记录完成时间）；正常结束写 `passed/failed` +
`exit_code` + `finished_at`；FATAL 即时写 `fatal` + 错误与启动诊断。终端汇总行与
verify-results.json 使用同一计算状态变量。verify.log 头部、verify-results.json、
console-network-report.json 三者携带同一 run_id，审计引用以同一成功 run 为准。

- 正式运行：**run_id=2026-09-06T04-45-39-397Z，161/161 PASS，status=passed，退出码 0**
  （日志 `verify.log`，明细 `verify-results.json`）。
- 负向实测：浏览器启动失败（AUDIT8_EDGE 指向非浏览器可执行文件）→ 逐次尝试含完整
  stderr → `FATAL` + 启动诊断，退出码 **2**，结果文件即时 `status=fatal`，进程结束，
  4180/8618 无残留监听；外部后端死端口 → 快速失败退出码 2；CDP 地址不可达 →
  自动落回固定版本 headless-shell 继续全量检查。

## 八、截图（reports/audit8/screenshots/，24 张）

五页 × 1920/1440/390 共 15 张；错误态/恢复态：home-empty、home-error、
home-error-recovered、stations-error、stations-error-recovered、heatmap-grid-error；
抽屉/跨页状态：home-source-drawer、history-drawer-390、stations-drawer-390。

## 九、验收标准逐条对照（任务十一）

| 标准 | 结果 |
|---|---|
| 前端构建通过 | ✓ vite build 成功 |
| 后端 ≥92 测试通过 | ✓ 92 passed |
| Audit7 实时接口验证通过 | ✓ 64/64（基线） |
| Audit8 自动化全部通过 | ✓ 161/161，status=passed，退出码 0（run_id=2026-09-06T04-45-39-397Z） |
| Audit8 失败路径返回非零 | ✓ 实测退出码 2（浏览器启动失败/外部后端不可达两类），结果即时 status=fatal |
| 五页无阻断级控制台错误 | ✓ 硬错误 0（逐条记录，无笼统豁免） |
| 无未解释的请求失败 | ✓ 唯一信号为测试注入，已逐条定性 |
| 数据身份没有混用 | ✓ OBS/PRED/RUN 唯一事实源 + meta 优先（含首页），浏览器侧逐响应断言 |
| 三种尺寸通过 | ✓ |
| P02、P08、/wallboard 未进入正式导航或修改范围 | ✓ 源码零改动 + 五页无入口链接（脚本断言） |
| data-cleaning/** 保持原样 | ✓ |
| git diff --check | ✓ 通过 |

## 十、已知事项与边界

1. Wallboard 直达路由 `/wallboard` 与页面文件按审计意见保留至第九任务清理；
   其已不在五页任何用户链路中（脚本逐页断言无入口链接）。事实源 `predictionRunId`
   语义修正对 Wallboard 页脚的被动影响因此仅存在于直达访问，不再是正式用户路径。
2. 首页湖面缩略图组件（太湖轮廓/静态回退）保留：接口正常时分区位置/名称/风险与
   风险统计全部来自 `/spatial-entities`；接口失败时回退静态常量并经错误态如实告知，
   不伪造接口数据。
3. ECharts chunk >500 kB 为既有构建提示，不影响运行时，本轮不优化。

## 十一、交付物清单

```text
reports/audit8/delivery-report.md            # 本文件
reports/audit8/audit8-verify.mjs             # 自动化复验脚本（可复跑、可退出、支持外部地址）
reports/audit8/verify.log                    # 正式运行日志（161/161，run_id=2026-09-06T04-45-39-397Z，退出码 0）
reports/audit8/verify-results.json           # 逐项结果明细
reports/audit8/console-network-report.md     # 控制台与网络报告（含失败路径复验记录）
reports/audit8/console-network-report.json   # 逐会话原始记录
reports/audit8/api-consumer-matrix.md        # 五页 API 消费矩阵
reports/audit8/git-scope.txt                 # Git 范围证明
reports/audit8/screenshots/                  # 23 张验收截图
```

按任务要求在此停止：不提交第八任务、不开始第九任务，等待独立复审。
（复审 REWORK 仅修 findings；复审 PASS 后再建立 Git 检查点。）
