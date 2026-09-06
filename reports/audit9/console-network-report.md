# audit9 控制台与网络报告

生成时间：2026-09-06。数据来源：`reports/audit9/audit9-verify.mjs` 正式运行
（**run_id=2026-09-06T06-49-03-068Z，167/167 PASS，status=passed，退出码 0**，进程正常结束），
逐会话原始记录见 `console-network-report.json`（与 verify-results.json 同一 run_id）。

## 〇、运行标识

- `run_id=2026-09-06T06-49-03-068Z`；`started_at=2026-09-06T06:49:03.069Z`、
  `finished_at=2026-09-06T06:50:24.820Z`、`exit_code=0`、`status=passed`；
  running 占位 `finished_at=null`，仅终态记录完成时间；终端汇总行与结果 JSON 同源。
- 运行开始写 `status=running`；断言失败覆盖写 `failed`；FATAL 覆盖写 `fatal` + 启动诊断。
  负向实测（`AUDIT9_EDGE` 指向非浏览器可执行文件）：3 次尝试全部 `ok=false` 记录于
  `browser_diag.attempts`、退出码 2、`status=fatal`、进程正常结束、4191/8629 无残留监听。
- 浏览器：固定版本 `chrome-headless-shell@152.0.7977.82`（`HeadlessChrome/152.0.7977.82`，
  `browser.ok=true`，落盘前有 `chosen.ok===true` 硬断言）。

## 一、采集方法

21 个全新 page 会话（15 个「五页 × 三视口」渲染 + 跨页导航 + URL 状态 + 404 组 +
声明扫描 + 抽屉可访问性），采集六类信号：

1. **JavaScript error / Vue warning / 未处理 Promise**：`console(type=error)` + `pageerror`。
2. **失败静态资源**：`requestfailed`，按第一方（同源）/ 第三方（跨域瓦片）分级。
3. **未解释的 4xx/5xx**：所有 `/api/` 响应状态码断言。
4. **API 数据身份**：浏览器实际收到的每个 `/api/` 信封断言 meta 六键与 OBS/PRED/RUN 归类。
5. **废弃残留**：五页可见文本 + `src/**` + `dist/**` 文件扫描。
6. **超范围声明**：可见文本禁用词（真实预测/正式预警/算法已验证）扫描。

## 二、结果

| 信号 | 结果 |
|---|---|
| 硬控制台错误（未豁免） | **0 条**（21 个会话合计） |
| pageerror / 未处理 Promise | **0 条** |
| 第一方资源失败（同源静态 + /api/） | **0 条** |
| 未解释 4xx/5xx | **0 条**（全部 API 响应 code=200） |
| API 数据身份 | 全部符合（观察类 OBS+run=null；预测类 PRED，成功响应 run=DEMO-RUN-V1；404/422/409 错误信封 run 恒 null） |
| 废弃模块残留（源码/构建产物/可见文本） | **0 命中** |
| 超范围声明 | **0 命中** |

## 三、逐条信号记录（无笼统豁免）

| 会话 | 信号 | 条数 | 定性 |
|---|---|---|---|
| url-state@1440 | ArcGIS 底图瓦片 `net::ERR_ABORTED`（server.arcgisonline.com，跨域第三方） | 5 | **预期内**：D 组连续 goto/reload 导航中止在途第三方瓦片请求，属浏览器标准中止行为，非应用错误；分级后不计入第一方资源失败，B 组单页会话同类请求 0 失败 |

既有警告豁免清单（CONSOLE_ALLOWLIST）：**为空**——五页三种视口正式渲染未产生任何
需要豁免的控制台错误或 Vue warning。

## 四、构建期提示（非运行时）

`npm run build` 存在 ECharts chunk > 500 kB 的体积提示（既有行为）。属构建优化建议，
不影响运行时正确性，本轮不处理。
