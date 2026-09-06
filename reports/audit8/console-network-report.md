# audit8 控制台与网络报告

生成时间：2026-09-06（第五轮重新生成）。数据来源：`reports/audit8/audit8-verify.mjs` 正式运行
（**run_id=2026-09-06T04-45-39-397Z，161/161 PASS，status=passed，退出码 0**，进程正常结束），
逐会话原始记录见 `console-network-report.json`（与 verify-results.json 同一 run_id）。

## 〇、运行标识与可复现性（P1 / P2 复验记录）

- 全部产物（verify.log 头部、verify-results.json、console-network-report.json）携带同一
  `run_id=2026-09-06T04-45-39-397Z`；`started_at=2026-09-06T04:45:39.399Z`、
  `finished_at=2026-09-06T04:47:24.085Z`、`exit_code=0`、`status=passed`；
  running 占位的 `finished_at=null`，仅终态记录完成时间；终端汇总行与结果 JSON
  使用同一计算状态变量。
- 运行开始即写入 `status=running` 占位，断言失败覆盖写 `status=failed`，FATAL 覆盖写
  `status=fatal` + 完整错误与启动诊断——失败运行不会残留上一轮的全绿结果（负向实测验证）。
- 浏览器方案（三级）：① `AUDIT8_CDP_URL` 连接预启动浏览器（CDP，不拉起进程）；
  ② **固定版本 `chrome-headless-shell@152.0.7977.82`**（本轮正式 run 实际采用，
  `HeadlessChrome/152.0.7977.82`，可执行文件位于 `reports/audit8/.browser-cache/` 本地
  缓存，缺失时经 `@puppeteer/browsers` 一次性自动安装，与系统 Edge 状态/策略完全解耦）；
  ③ 系统 Edge/Chrome 兜底（ws / pipe / 精简参数三种方式逐次尝试，独立临时 profile，
  失败逐次记录完整 stderr 于 `browser_diag.attempts`；`AUDIT8_EDGE` 显式指定不存在时
  报错不回退）。

## 一、采集方法

对每个「页面 × 视口」组合创建全新 page 会话（共 26 个），采集五类信号：

1. **JavaScript error / Vue warning / 未处理 Promise**：`page.on('console', type=error)` + `page.on('pageerror')`（pageerror 覆盖未处理异常与未捕获 Promise 拒绝）。
2. **失败静态资源**：`page.on('requestfailed')`。
3. **未解释的 4xx/5xx**：`page.on('response')` 对所有 `/api/` 响应做状态码断言。
4. **重复请求 / 请求竞态**：F 组专项（T+1 响应延迟 2s 后快速切档、驾驶舱快速连点四档）。
5. **API 返回的数据身份**：对浏览器实际收到的每个 `/api/` JSON 响应断言 meta 六键与 OBS/PRED/RUN 归类（含首页三接口）。

## 二、五页正式渲染会话（15 个：5 页 × 3 视口）

| 信号 | 结果 |
|---|---|
| 硬控制台错误（未豁免） | **0 条**（15 个会话全部为 0） |
| pageerror / 未处理 Promise | **0 条** |
| 失败静态资源（第一方：同源静态 + /api/） | **0 条** |
| 未解释 4xx/5xx | **0 条**（浏览器收到的全部 API 响应 code=200） |
| API 数据身份 | 全部符合：观察类（首页能力/数据集/分区、P03 观测等）meta.dataset_version=DEMO-OBS-V1 且 prediction_run_id=null；预测类 =DEMO-PRED-V1 且成功响应 prediction_run_id=DEMO-RUN-V1 |

跨页导航（C）、URL 冷启动/刷新/非法参数（D）、请求竞态（F）、可访问性（G）共 5 个会话
同样硬错误为 0（竞态会话额外断言竞态期间无 JS 错误）。

**第三方底图瓦片分级**：跨域瓦片请求（如 ArcGIS World_Imagery）受外部网络可用性影响，
其失败按条记录（URL + 错误码，并与同码 console error 配对归类），不算第一方资源失败；
但脚本同时断言页面在瓦片失败时以图层错误态/"重试图层"诚实处理。本轮正式 run 中
第三方瓦片 **0 失败**；分级逻辑已在 ArcGIS 瞬断的独立运行中实测（第一方全过、
第三方失败逐条记录、页面诚实披露、status=failed 如实落盘与终端一致）。

## 三、逐条豁免与已知信号（无笼统豁免）

E 组错误注入现已各自独立 page 会话，注入信号仅存在于注入会话内：

| 会话 | 信号 | 条数 | 定性 |
|---|---|---|---|
| home-empty@1440 / home-error@1440 | 注入响应或 `ERR_FAILED` 控制台错误 | — | **预期内**：首页三接口分别注入"200+空载荷"与"网络失败"，验证 empty/错误态与重试恢复 |
| home-error@1440 | `Failed to load resource: net::ERR_FAILED` + requestFailed | 3 | 同上（三接口 abort 注入） |
| stations-error@1440 | 同上（spatial-entities abort） | 1 | **预期内**：验证错误态→重试恢复 |
| heatmap-grid-error@1440 | 同上（risk-grid 各档 abort） | 5 | **预期内**：验证格网错误态→grid-retry 恢复 |

既有警告豁免清单（CONSOLE_ALLOWLIST）：**为空**——五页三种视口正式渲染未产生任何
需要豁免的控制台错误或 Vue warning；上表信号均为测试自身注入，正式用户路径不可复现。

## 四、重复请求与竞态结论

- heatmap 迟到请求注入（T+1 延迟 2s）：迟到响应落地后展示仍稳定在 T+3→回点 T+1 正常，无覆盖、无 JS 错误。
- cockpit 快速连点 T+1→T+3→T+7→T+15（间隔 60ms）：最终稳定 T+15 且 URL 同步 `t=t15`。
- 正式渲染会话中未发现对同一接口的重复冗余请求（各业务页捕获的 API 响应数量与页面设计一致）。

## 五、失败路径行为（本轮实测）

- 正常完成：161/161，`status=passed`、`exit_code=0`，输出"服务清理完成"，进程实际结束，
  4180/8618 无残留监听。
- 浏览器启动失败（AUDIT8_EDGE 指向非浏览器可执行文件）：3 次尝试逐次记录完整错误
  （`Timed out after 30000 ms while waiting for the WS endpoint URL…`），输出 `FATAL` +
  启动诊断 JSON，退出码 **2**，结果文件即时写入 `status=fatal`（不残留旧通过结果），
  进程正常结束，4180/8618 无残留监听。
- 外部后端不可达（`AUDIT8_BACK_URL` 指向死端口）：快速失败，退出码 **2**，无残留监听。

## 六、构建期提示（非运行时）

`npm run build` 存在 ECharts chunk > 500 kB 的体积提示（既有行为，来自按页懒加载的
EChart chunk）。属构建优化建议，不影响运行时正确性，本轮不处理。
