这是 P03 监测站点研判交付的 R1 复审（只读）。你上一轮审计（reports/audit4-codex-review.md）判定 REWORK，给出 1 major + 3 minor。执行 AI 已按 findings 返工，请复核并给出最终判定。

## 上轮 findings 与执行 AI 声称的修复（逐条核实）

1. (major) `src/pages/Stations.vue` 档位互切未立即失效 `rankForecasts`，旧预测跨档位展示、失败被掩盖。
   声称修复：stageKey watcher 切换瞬间 `rankForecasts={}` + `rankState='loading'` + 清空 `explanation`；`fetchRanking` 无条件 loading、catch 时清空 `rankForecasts` 再置 error。
   核实点：读当前 `git diff HEAD -- src/pages/Stations.vue` 中 stageKey watcher 与 fetchRanking；确认错误态下 brief 的 forecast-state 判定不会再被旧值判成 ok；确认 explanation 生命周期同样隔离。

2. (minor) 验收 9 未核对档位数据归属/失败状态。
   声称修复：reports/audit4-verify.mjs 新增 9b/9c——CDP `Network.setBlockedURLs` 阻断 `*horizon_days=1` 注入失败；9b 断言切换期间旧 sf-score 不展示（加载或失败二态）；9c 断言错误文案可见、重试后展示 T+1 档位分数与"档位 T+1"。
   核实点：读脚本对应代码段；确认断言逻辑真实有效（非恒真）；run5 日志中 9b before=48、during.staleScore=false、9c after.score=61、stageVal=T+1。

3. (minor) 验收 4 竞态断言不足。
   声称修复：check 4 增加 ownership 断言（最后一次 observations/quality/explanations 请求实体=最终分区）。
   核实点：脚本与 run5 日志 ownership={"obs":"river_inlet","qly":"river_inlet","exp":"river_inlet"}。

4. (minor) 报告"真实观测"措辞违反数据红线。
   声称修复：reports/audit4-delivery-report.md 与脚本 check 8 统一改为"接口返回的模拟观测"。
   核实点：grep 两文件确认不再出现"真实观测"这类口径（注意：正文别处若出现指的是"非模拟"含义的上下文请具体判断）。

## 复审要求

1. 可亲自重跑 `node reports/audit4-verify.mjs`（preview 在 http://localhost:4173，已重新构建；约 1-2 分钟，预期 27/27、EXIT_CODE 0）。
2. 抽查修复是否引入新问题：档位切换 loading 骨架、错误面板、重试交互、explanation 状态机、以及 P01（cockpit 页）不受影响。
3. 仍为只读：禁止修改/删除/暂存任何文件，禁止 git 写操作，禁止触碰 data-cleaning/** 与 reports/data-generation-*/reports/audit2-*。

## 输出格式（严格遵守）

第一行：`VERDICT: PASS` 或 `VERDICT: REWORK`
随后：逐条 findings 复核结论；若仍有问题给出文件:行号、严重度、建议
最后一行：给执行 AI 的一句话下一步指令。
