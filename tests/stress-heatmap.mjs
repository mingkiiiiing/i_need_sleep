// 时空推演页（/#/heatmap）压力测试套件：前端交互压测 + 后端并发压测，一键出报告。
//
// 用法：node tests/stress-heatmap.mjs
// 输出：tests/stress-report.json + 控制台两行摘要
//
// 前端（puppeteer-core + 本机 Edge headless，args 带 --no-proxy-server 与 --disable-gpu）：
//   S1 指标轮换   risk→chla→area→biomass 循环 6 轮（24 次切换），每步等主结果
//                 [data-role="model-primary-result"] 或骨架 [data-role="lake-aggregate-pending"]
//                 出现（3s 超时容忍），记录每步耗时；
//   S2 时效快切   时间轴轨道（.ftl-track，role=slider）keyboard：End 落 T+90、ArrowLeft×6
//                 逆行走完 7 个 T+ 刻度（t90→t60→t30→t15→t7→t3→t1），4 轮，每步 250ms；
//   S3 站点快切   从页面站点下拉 [data-role="station-select"] options 读取真实 id 取前 8，
//                 hash 深链 #/heatmap?mode=forecast&scale=short&metric=chla&station=<id>&stop=t1
//                 逐站切换，每站等 back-to-lake / 骨架 / 主结果（4s 容忍）；
//   S4 模式切换   forecast→replay→rs 循环 5 轮（[data-role="mode-*"] 卡），每模式停留 800ms；
//   S5 内存采样   每场景前后 performance.memory.usedJSHeapSize，报告各场景增量与总增量
//                 （总增量 >50MB 标 WARN，>120MB 标 FAIL）。
//   统一收集：console error / pageerror（计数 + 前 5 条原文）、白屏（body 内 .hm-main 缺失）。
//   门禁口径与 browser-smoke 一致：只计交付物自身（本机前端）产生的错误，外部第三方
//   资源（ArcGIS 底图瓦片）的网络抖动单列为 externalNoise 披露，不作门禁失败。
//
// 后端（同脚本内 fetch 并发，不开浏览器）：
//   C1 快照并发   20 并发 × 5 轮打 prediction-snapshot?entity_id=lake&focus_metric=chla；
//   C2 站点快照   从 /realtime/summary markers 取 8 个真实站点 id 各 3 次并发（24 请求）。
//   统计 p50/p95/max，判定：失败率 0 且 p95 < 2000ms → PASS。
//
// 压测定额按任务书执行，不加大并发/轮数，避免把本机 dev server 打挂。
import puppeteer from 'puppeteer-core'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const BASE = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api/v1'
const REPORT_PATH = new URL('./stress-report.json', import.meta.url)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const r1 = (n) => Math.round(Number(n) * 10) / 10
const mb = (bytes) => r1((bytes || 0) / 1048576)

// 最近邻秩百分位（latencies 需已升序），返回毫秒一位小数
function pct(sorted, q) {
  if (!sorted.length) return null
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((q / 100) * sorted.length) - 1))
  return r1(sorted[idx])
}
function latencyStats(arr) {
  const ok = arr.filter((x) => x.ok)
  const lat = ok.map((x) => x.ms).sort((a, b) => a - b)
  const non200 = arr.filter((x) => !x.ok && x.status !== 0).length
  const netFail = arr.filter((x) => x.status === 0).length
  return {
    requests: arr.length,
    non200,
    netFail,
    failureRate: arr.length ? r1((non200 + netFail) / arr.length) : 1,
    p50: pct(lat, 50),
    p95: pct(lat, 95),
    max: lat.length ? r1(lat[lat.length - 1]) : null,
    mean: lat.length ? r1(lat.reduce((s, x) => s + x, 0) / lat.length) : null,
    latencies: arr.map((x) => ({ status: x.status, ms: r1(x.ms), ...(x.error ? { error: x.error } : {}) }))
  }
}

// ---------- 全局收集器 ----------
const consoleRecords = [] // { scenario, type, text }
let currentScenario = 'init'
const EXTERNAL_HOST = /(^|\.)arcgisonline\.com$|(^|\.)arcgis\.com$/ // 与 browser-smoke 同口径：外部底图噪音

// ---------- 单个并发请求 ----------
async function hit(url) {
  const t0 = performance.now()
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 10000)
    const resp = await fetch(url, { signal: ctrl.signal })
    await resp.arrayBuffer() // 读净响应体（连接复用与真实负载更接近）
    clearTimeout(timer)
    return { ok: resp.ok, status: resp.status, ms: performance.now() - t0 }
  } catch (e) {
    return { ok: false, status: 0, ms: performance.now() - t0, error: String(e && e.message ? e.message : e).slice(0, 120) }
  }
}

// ---------- 后端压测 ----------
async function backendStress() {
  const out = {}

  // T2 性能守卫（2026-09-12）：后端启动后的解释预热/站点重生成窗口（~40-120s）
  // 会与压测竞争单 worker 的 GIL，首波延迟被放大 3-6 倍（见 backend/performance/
  // T2_性能定位报告_20260912.md）。连续两次单请求 <300ms 才认为已度过预热窗口，
  // 避免压测数字被环境因素污染。
  for (let i = 0; i < 30; i++) {
    const p1 = await hit(`${API}/model/v3/prediction-snapshot?entity_id=lake&focus_metric=risk`)
    if (p1.ok && p1.ms < 300) {
      await sleep(1000)
      const p2 = await hit(`${API}/model/v3/prediction-snapshot?entity_id=lake&focus_metric=risk`)
      if (p2.ok && p2.ms < 300) break
    }
    await sleep(4000)
  }

  // C1 全湖快照：20 并发 × 5 轮
  {
    const url = `${API}/model/v3/prediction-snapshot?entity_id=lake&focus_metric=chla`
    const all = []
    for (let round = 1; round <= 5; round++) {
      const batch = await Promise.all(Array.from({ length: 20 }, () => hit(url)))
      all.push(...batch)
      await sleep(300)
    }
    const stats = latencyStats(all)
    out.c1 = {
      name: '全湖快照并发 20×5',
      url: '/api/v1/model/v3/prediction-snapshot?entity_id=lake&focus_metric=chla',
      rounds: 5,
      concurrency: 20,
      ...stats,
      verdict: stats.failureRate === 0 && stats.p95 != null && stats.p95 < 2000 ? 'PASS' : 'FAIL'
    }
  }

  // C2 站点快照：/realtime/summary markers 前 8 站各 3 次并发
  {
    let ids = []
    try {
      const resp = await fetch(`${API}/realtime/summary`)
      const body = await resp.json()
      ids = ((body.data || {}).markers || []).map((m) => m.id).filter(Boolean).slice(0, 8)
    } catch { /* 下面兜底 */ }
    if (ids.length < 8) {
      // 兜底：browser-smoke 已核验过的真实站点 id（下拉列表前几位）
      ids = ['mee-0145cdb7', 'mee-077b367a', 'mee-0e770fb5', 'mee-1c5c6f47', 'mee-1d96cbf3', 'mee-1eeede89', 'mee-1fb5ae3c', 'mee-200076ad']
    }
    const urls = ids.flatMap((id) => Array.from({ length: 3 }, () =>
      `${API}/model/v3/prediction-snapshot?entity_id=${encodeURIComponent(id)}&focus_metric=chla`))
    const results = await Promise.all(urls.map((u) => hit(u)))
    const stats = latencyStats(results)
    out.c2 = {
      name: '8 站点快照并发 ×3',
      stationIds: ids,
      requests: stats.requests,
      non200: stats.non200,
      netFail: stats.netFail,
      failureRate: stats.failureRate,
      p50: stats.p50,
      p95: stats.p95,
      max: stats.max,
      mean: stats.mean,
      latencies: stats.latencies,
      verdict: stats.failureRate === 0 && stats.p95 != null && stats.p95 < 2000 ? 'PASS' : 'FAIL'
    }
  }

  out.verdict = out.c1.verdict === 'PASS' && out.c2.verdict === 'PASS' ? 'PASS' : 'FAIL'
  return out
}

// ---------- 前端压测 ----------
async function frontendStress() {
  const out = {
    s1: null, s2: null, s3: null, s4: null,
    consoleErrors: 0,
    consoleErrorSamples: [],
    externalNoise: 0,
    whiteScreens: 0,
    memory: null,
    verdict: 'FAIL'
  }
  let browser = null
  let whiteScreens = 0
  const memory = { scenarios: {} }

  const attach = (page) => {
    page.on('console', (m) => {
      if (m.type() !== 'error') return
      const loc = m.location() || {}
      const url = loc.url || ''
      let external = false
      try { external = Boolean(url) && EXTERNAL_HOST.test(new URL(url).hostname) } catch { /* 保内 */ }
      consoleRecords.push({ scenario: currentScenario, type: 'console', external, text: m.text().slice(0, 400), url })
    })
    page.on('pageerror', (e) => {
      consoleRecords.push({ scenario: currentScenario, type: 'pageerror', external: false, text: String(e).slice(0, 400) })
    })
  }
  const isWhite = (page) => page.evaluate(() => !document.querySelector('body .hm-main'))
  const heap = async (page) => {
    try {
      return await page.evaluate(() => (performance.memory ? performance.memory.usedJSHeapSize : null))
    } catch { return null }
  }
  const countWhite = async (page, where) => {
    try {
      if (await isWhite(page)) {
        whiteScreens += 1
        consoleRecords.push({ scenario: currentScenario, type: 'whiteScreen', external: false, text: `白屏 @ ${where}（body 内 .hm-main 缺失）` })
        return true
      }
    } catch { /* 页面可能正在导航，不判白 */ }
    return false
  }
  const scenarioMem = async (page, key, beforeBytes) => {
    const after = await heap(page)
    memory.scenarios[key] = {
      beforeBytes, afterBytes: after,
      deltaMB: beforeBytes != null && after != null ? mb(after - beforeBytes) : null
    }
    return after
  }

  try {
    browser = await puppeteer.launch({
      executablePath: EDGE,
      headless: true,
      // --enable-precise-memory-info：让 performance.memory 给出精确值而非分桶粗值
      args: ['--no-sandbox', '--disable-gpu', '--no-proxy-server', '--enable-precise-memory-info', '--window-size=1600,1000']
    })
    const page = await browser.newPage()
    await page.setViewport({ width: 1600, height: 1000 })
    attach(page)

    // 初始加载：短临 / risk / T+1 深链，留足构建时间
    currentScenario = 'init'
    await page.goto(`${BASE}/#/heatmap?mode=forecast&scale=short&metric=risk`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await sleep(5000)
    await countWhite(page, 'init')

    // ================= S1 指标轮换 risk→chla→area→biomass × 6 轮 =================
    {
      currentScenario = 's1'
      const before = await heap(page)
      const metrics = ['risk', 'chla', 'area', 'biomass']
      const steps = []
      let timeouts = 0
      for (let round = 1; round <= 6; round++) {
        for (const m of metrics) {
          const t0 = performance.now()
          let timedOut = false
          try {
            await page.click(`[data-role="metric-${m}"]`)
            // 等主结果或骨架出现（hash 已切到该指标），3s 超时容忍
            await page.waitForFunction((metric) => {
              if (!window.location.hash.includes(`metric=${metric}`)) return false
              return Boolean(
                document.querySelector('[data-role="model-primary-result"]') ||
                document.querySelector('[data-role="lake-aggregate-pending"]')
              )
            }, { timeout: 3000, polling: 100 }, m)
          } catch {
            timedOut = true
            timeouts += 1
          }
          const ms = r1(performance.now() - t0)
          steps.push({ round, metric: m, ms, timedOut })
          await countWhite(page, `s1 r${round} ${m}`)
          await sleep(100)
        }
      }
      const msArr = steps.map((s) => s.ms).sort((a, b) => a - b)
      out.s1 = {
        name: '指标轮换 ×6 轮（24 次切换）',
        switches: steps.length,
        timeouts,
        avgMs: r1(msArr.reduce((s, x) => s + x, 0) / msArr.length),
        p95: pct(msArr, 95),
        max: msArr.length ? msArr[msArr.length - 1] : null,
        steps,
        whiteScreens: undefined // 场景级白屏统一计入总数
      }
      await scenarioMem(page, 's1', before)
    }

    // ================= S2 时效快速切换（轨道键盘，7 个 T+ 刻度 × 4 轮） =================
    {
      currentScenario = 's2'
      const before = await heap(page)
      const rounds = []
      let keyPresses = 0
      try {
        await page.focus('.ftl-track')
      } catch { /* 焦点失败在轮内重试 */ }
      for (let round = 1; round <= 4; round++) {
        try { await page.focus('.ftl-track') } catch { /* 忽略 */ }
        // End → T+90（第 7 个 T+ 停靠点），随后 ArrowLeft×6 逆行经过 t60/t30/t15/t7/t3/t1
        await page.keyboard.press('End')
        keyPresses += 1
        await sleep(250)
        for (let i = 0; i < 6; i++) {
          await page.keyboard.press('ArrowLeft')
          keyPresses += 1
          await sleep(250)
          await countWhite(page, `s2 r${round} step${i + 1}`)
        }
        const val = await page.evaluate(() => {
          const t = document.querySelector('.ftl-track')
          return { now: t && t.getAttribute('aria-valuenow'), text: t && t.getAttribute('aria-valuetext') }
        })
        rounds.push({ round, endValue: val })
      }
      out.s2 = {
        name: '时间轴 7 个 T+ 刻度键盘快切 ×4 轮（每步 250ms）',
        rounds: rounds.length,
        keyPresses,
        intervalMs: 250,
        roundEndValues: rounds,
        whiteScreens: undefined
      }
      await scenarioMem(page, 's2', before)
    }

    // ================= S3 站点快速切换（下拉读 8 个真实 id，hash 深链） =================
    {
      currentScenario = 's3'
      const before = await heap(page)
      let ids = []
      try {
        // 打开站点范围让下拉挂载，读取真实 options
        await page.click('[data-role="scope-station"]')
        await page.waitForSelector('[data-role="station-select"]', { timeout: 4000 })
        await sleep(400)
        ids = await page.evaluate(() =>
          Array.from(document.querySelectorAll('[data-role="station-select"] option'))
            .map((o) => o.value)
            .filter((v) => v && v.startsWith('mee-'))
            .slice(0, 8))
      } catch {
        ids = ['mee-0145cdb7', 'mee-077b367a', 'mee-0e770fb5', 'mee-1c5c6f47', 'mee-1d96cbf3', 'mee-1eeede89', 'mee-1fb5ae3c', 'mee-200076ad']
      }
      const stations = []
      for (const id of ids) {
        const t0 = performance.now()
        let waitOk = true
        try {
          await page.evaluate((sid) => {
            window.location.hash = `#/heatmap?mode=forecast&scale=short&metric=chla&station=${sid}&stop=t1`
          }, id)
          await page.waitForFunction(() => Boolean(
            document.querySelector('[data-role="back-to-lake"]') ||
            document.querySelector('[data-role="lake-aggregate-pending"]') ||
            document.querySelector('[data-role="model-primary-result"]')
          ), { timeout: 4000, polling: 150 })
        } catch {
          waitOk = false
        }
        const ms = r1(performance.now() - t0)
        const hash = await page.evaluate(() => window.location.hash).catch(() => '')
        stations.push({ id, ms, waited: waitOk, hashMatched: hash.includes(`station=${id}`) })
        await countWhite(page, `s3 ${id}`)
        await sleep(300)
      }
      // 复位到全湖，给 S4 干净起点
      try {
        await page.evaluate(() => { window.location.hash = '#/heatmap?mode=forecast&scale=short&metric=risk' })
        await sleep(2000)
      } catch { /* 忽略 */ }
      out.s3 = {
        name: '8 站点 hash 深链快切',
        stationIds: ids,
        stations,
        allHashMatched: stations.every((s) => s.hashMatched),
        whiteScreens: undefined
      }
      await scenarioMem(page, 's3', before)
    }

    // ================= S4 模式切换 forecast→replay→rs × 5 轮 =================
    {
      currentScenario = 's4'
      const before = await heap(page)
      const switches = []
      for (let round = 1; round <= 5; round++) {
        for (const mode of ['replay', 'rs', 'forecast']) {
          const t0 = performance.now()
          try {
            await page.click(`[data-role="mode-${mode}"]`)
          } catch (e) {
            switches.push({ round, mode, dwellMs: 0, clickError: String(e).slice(0, 120) })
            continue
          }
          await sleep(800)
          const white = await countWhite(page, `s4 r${round} ${mode}`)
          switches.push({ round, mode, dwellMs: r1(performance.now() - t0), white })
        }
      }
      out.s4 = {
        name: '模式切换 forecast→replay→rs ×5 轮（每模式停留 800ms）',
        cycles: 5,
        switches,
        whiteScreens: undefined
      }
      await scenarioMem(page, 's4', before)
    }

    // ================= 汇总：错误 / 白屏 / 内存 =================
    const internal = consoleRecords.filter((r) => !r.external && (r.type === 'console' || r.type === 'pageerror' || r.type === 'whiteScreen'))
    const external = consoleRecords.filter((r) => r.external)
    out.consoleErrors = internal.filter((r) => r.type === 'console' || r.type === 'pageerror').length
    out.consoleErrorSamples = internal.slice(0, 5).map((r) => `[${r.scenario}/${r.type}] ${r.text}`)
    out.whiteScreens = internal.filter((r) => r.type === 'whiteScreen').length
    out.externalNoise = external.length
    if (external.length) {
      out.externalNoiseSamples = external.slice(0, 3).map((r) => `[${r.scenario}] ${r.text}`)
    }

    const first = memory.scenarios.s1 ? memory.scenarios.s1.beforeBytes : null
    const last = memory.scenarios.s4 ? memory.scenarios.s4.afterBytes : null
    const totalDeltaMB = first != null && last != null ? mb(last - first) : null
    out.memory = {
      metric: 'performance.memory.usedJSHeapSize',
      scenarios: memory.scenarios,
      baselineMB: first != null ? mb(first) : null,
      finalMB: last != null ? mb(last) : null,
      totalDeltaMB,
      thresholds: { warnMB: 50, failMB: 120 }
    }
    out.memory.status = totalDeltaMB == null ? 'UNKNOWN' : totalDeltaMB > 120 ? 'FAIL' : totalDeltaMB > 50 ? 'WARN' : 'OK'

    out.verdict = out.consoleErrors === 0 && out.whiteScreens === 0 && out.memory.status !== 'FAIL' ? 'PASS' : 'FAIL'
    return out
  } catch (e) {
    // 浏览器层异常：记入报告继续后端压测
    out.frontendFatal = String(e && e.stack ? e.stack : e).slice(0, 600)
    const internal = consoleRecords.filter((r) => !r.external)
    out.consoleErrors = internal.length
    out.consoleErrorSamples = internal.slice(0, 5).map((r) => `[${r.scenario}/${r.type}] ${r.text}`)
    out.whiteScreens = whiteScreens
    out.memory = { scenarios: memory.scenarios, status: 'UNKNOWN' }
    out.verdict = 'FAIL'
    return out
  } finally {
    if (browser) {
      try { await browser.close() } catch { /* 忽略关闭异常 */ }
    }
  }
}

// ---------- 主流程 ----------
const startedIso = new Date().toISOString()
const t0 = performance.now()
console.log(`[stress] 开始：前端 S1-S5（Edge headless）+ 后端 C1-C2，目标 ${BASE} / ${API}`)

const frontend = await frontendStress()
console.log('[stress] 前端压测完成，开始后端并发压测…')
const backend = await backendStress()

const report = {
  started_at: startedIso,
  finished_at: new Date().toISOString(),
  duration_ms: Math.round(performance.now() - t0),
  env: { base: BASE, api: API, browser: 'Edge headless (puppeteer-core)' },
  frontend,
  backend,
  overall: frontend.verdict === 'PASS' && backend.verdict === 'PASS' ? 'PASS' : 'FAIL'
}
fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2), 'utf8')

// 控制台摘要（两行 verdict + overall）
const f = report.frontend
const memLine = f.memory && f.memory.totalDeltaMB != null ? `mem +${f.memory.totalDeltaMB}MB(${f.memory.status})` : 'mem n/a'
console.log(`[stress] frontend: ${f.verdict} | consoleErrors=${f.consoleErrors} whiteScreens=${f.whiteScreens} externalNoise=${f.externalNoise} | ${memLine}`)
const c1 = report.backend.c1 || {}
const c2 = report.backend.c2 || {}
console.log(`[stress] backend: ${report.backend.verdict} | C1 p50=${c1.p50}ms p95=${c1.p95}ms max=${c1.max}ms fail=${c1.non200 + c1.netFail} | C2 p50=${c2.p50}ms p95=${c2.p95}ms fail=${c2.non200 + c2.netFail}`)
console.log(`[stress] overall: ${report.overall} → ${fileURLToPath(REPORT_PATH.href)}`)

if (f.consoleErrorSamples && f.consoleErrorSamples.length) {
  console.log('[stress] 错误样本（前 5 条）：')
  f.consoleErrorSamples.forEach((s) => console.log('  - ' + s))
}
process.exitCode = report.overall === 'PASS' ? 0 : 1
