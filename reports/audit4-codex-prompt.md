你是本仓库前端任务的独立审计方（第四步审计）。请审计"第四个大任务：重构 P03 监测站点研判"的交付质量，并给出判定。

## 背景

- 仓库（当前工作目录）：D:\Project\fuwai\项目完整汇总_2026-08-31\01_我们的开发
- 前端基线：072a82c（P01 驾驶舱，已过审提交）。P03 的全部改动未提交：`git status --short` 中的 src/**、reports/audit4-* 与 dist/** 即本任务现场。
- 并行任务现场（不属本任务、不得触碰）：data-cleaning/**、reports/data-generation-*、reports/audit2-*（git status 中这些条目来自并行会话，其中有其自己的提交 c05abf6、52c9ec5）。
- 本任务允许修改：src/pages/Stations.vue、src/components/stations/**、src/services/api.js、reports/audit4-*、dist/**；src/stores/cockpit.js、src/components/cockpit/{LakeMap,EChart}.vue、src/styles.css 仅允许有正当理由的小改动（交付方声称完全未改）。禁止修改：Home.vue、Cockpit.vue、Heatmap.vue（P07）、History.vue、layouts/**、AppSidebar/AppTopBar、backend/**、algorithms/**、shenji-pan/**。

## 必读材料

1. reports/audit4-delivery-report.md —— 交付报告（10 项，含 22 项验收的 25 子项映射与证据）
2. reports/audit4-verify.mjs —— 复验脚本（25 断言、失败退出非零）；reports/audit4-run4.log —— 最后一轮 25/25、EXIT_CODE 0
3. git diff HEAD -- src/pages/Stations.vue src/services/api.js；新目录 src/components/stations/ 全部 8 个文件
4. 原任务书要点：1920 三栏（22/53/25）+ 底部 3-Tab；22 项验收清单见报告第 5 节；模拟数据边界必须诚实披露；T+30 只显示能力阻塞不得冒充预测；预警必须经确认弹窗且仅模拟发送

## 审计要求

1. 逐条核对 22 项验收（对照报告第 5 节的证据），必要时**亲自重跑** `node reports/audit4-verify.mjs`（preview 已在 http://localhost:4173 运行、后端经代理可用；脚本需约 1-2 分钟）。
2. 代码质量抽查：并发响应 token 防护是否正确；Teleport 处理 fixed 定位的方案是否稳妥；地图容器 flex 塌缩修复；CSS 级联覆盖（scoped vs unscoped）；键盘可达性与焦点管理；api.js 的 requestEnvelope 是否真的不影响 P01。
3. 确认禁区：git status / git diff 中不应出现 P07、历史页、Home、Cockpit、layouts、backend、algorithms、shenji-pan、data-cleaning 的本任务改动。
4. 模拟数据边界披露是否诚实、完整、无夸大（这是本项目的红线）。
5. 若需返工：给出具体 findings（文件:行号、严重度 blocker/major/minor、修复建议）。
6. 若通过：明确说明"可推进下一个大任务"。

## 输出格式（严格遵守）

第一行：`VERDICT: PASS` 或 `VERDICT: REWORK`
随后：findings 列表（文件:行号、严重度、建议）或 PASS 结论摘要
最后一行：给执行 AI 的一句话下一步指令。

## 硬性约束

你只做审计：禁止修改/删除/暂存任何文件，禁止任何 git 写操作（commit/push/checkout/reset/clean/stash），禁止触碰 data-cleaning/** 与 reports/data-generation-*/reports/audit2-*。只读 + 可运行 reports/audit4-verify.mjs。
