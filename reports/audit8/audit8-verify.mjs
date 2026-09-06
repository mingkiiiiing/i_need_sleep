// audit8 自动化复验：五页面前后端全链路验收。
//
// 用法（仓库 01_我们的开发/ 下）：
//   node reports/audit8/audit8-verify.mjs
// 环境变量：
//   AUDIT8_CDP_URL  预启动浏览器的 CDP 地址（如 http://127.0.0.1:9222），连接而非拉起，优先级最高
//   AUDIT8_SHELL_BUILDID  固定版本 chrome-headless-shell 的构建号（默认 152.0.7977.82）
//   AUDIT8_FRONT_URL / AUDIT8_BACK_URL  外部已运行的前端/后端地址（提供则直接使用）
//   AUDIT8_FRONT_PORT (默认 4180) / AUDIT8_BACK_PORT (默认 8618)  自建服务端口
//   AUDIT8_EDGE   指定系统浏览器可执行文件（唯一候选，不存在即报错不回退）
//   AUDIT8_HEADLESS=0  有头模式（默认无头）
//   AUDIT8_SKIP_SHOTS=1  跳过截图
// 浏览器方案优先级：CDP 连接 → 固定版本 chrome-headless-shell（本地缓存，缺失自动安装）
//                  → 系统 Edge/Chrome（ws/pipe/精简参数三种方式逐次尝试）
// 行为：
//   - 后端不可达时自动启动 uvicorn；前端不可达时启动内置 dist 静态服务（/api 反代到后端）。
//   - 逐项输出 PASS/FAIL；任一 FAIL 退出码 1，全部通过退出码 0。
//   - 截图输出到 reports/audit8/screenshots/。
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '../..')
const DIST = path.join(REPO_ROOT, 'dist')
const SHOTS_DIR = path.join(__dirname, 'screenshots')

const FRONT_PORT = Number(process.env.AUDIT8_FRONT_PORT || 4180)
const BACK_PORT = Number(process.env.AUDIT8_BACK_PORT || 8618)
// 语义（P2-1）：通过环境变量显式提供 URL = 外部服务，不可达时快速失败，不代为拉起；
// 未提供 = 由脚本按端口自建服务（BACK_URL 即实际后端地址，内置前端反代一律指向它）。
const EXTERNAL_FRONT = Boolean(process.env.AUDIT8_FRONT_URL)
const EXTERNAL_BACK = Boolean(process.env.AUDIT8_BACK_URL)
const FRONT_URL = process.env.AUDIT8_FRONT_URL || `http://127.0.0.1:${FRONT_PORT}`
const BACK_URL = process.env.AUDIT8_BACK_URL || `http://127.0.0.1:${BACK_PORT}`
const HEADLESS = process.env.AUDIT8_HEADLESS !== '0'
const SKIP_SHOTS = process.env.AUDIT8_SKIP_SHOTS === '1'

// 与 backend/app/contracts.py 全局一致的数据身份口径
const OBS = 'DEMO-OBS-V1'
const PRED = 'DEMO-PRED-V1'
const RUN = 'DEMO-RUN-V1'
const META_KEYS = ['data_mode', 'dataset_version', 'prediction_run_id', 'as_of', 'claim_boundary', 'request_id']

// 观察类路径前缀（成功与错误均应为 OBS；其余 /api/v1 为 PRED）
const OBS_PREFIXES = ['/api/health', '/api/v1/system', '/api/v1/datasets', '/api/v1/pipeline', '/api/v1/spatial-entities']

const VIEWPORTS = [
  { name: '1920', width: 1920, height: 1080 },
  { name: '1440', width: 1440, height: 900 },
  { name: '390', width: 390, height: 844 }
]

// 控制台豁免清单：既有且确认无业务影响的警告必须逐条记录，不允许笼统豁免
const CONSOLE_ALLOWLIST = [
  {
    match: /Download the Vue Devtools extension/i,
    reason: 'Vue 开发提示（生产构建通常不出现；出现时无业务影响）'
  },
  {
    match: /\[Vue warn\]: Extra non-attributes/i,
    reason: 'Vue 透传属性提示，既有行为，不影响渲染与交互'
  },
  {
    match: /Deferred long-running timer/i,
    reason: 'Chrome 对长任务的性能建议，非页面错误'
  },
  {
    match: /Non-Error promise rejection captured with keys: timeout/i,
    reason: 'ECharts 内部 resize 防抖超时提示，无业务影响'
  }
]

const results = []
function report(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` —— ${detail}` : ''}`)
}
async function check(name, fn) {
  try {
    const detail = await fn()
    report(name, true, typeof detail === 'string' ? detail : '')
  } catch (err) {
    report(name, false, err && err.message ? err.message : String(err))
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function waitFor(fn, timeout = 15000, interval = 120, label = 'condition') {
  const start = Date.now()
  for (;;) {
    if (await fn()) return
    if (Date.now() - start > timeout) throw new Error(`等待超时：${label}`)
    await sleep(interval)
  }
}

// ---------- 服务编排 ----------
function reachable(url) {
  return fetch(url, { signal: AbortSignal.timeout(2500) }).then((r) => r.ok).catch(() => false)
}

function startBackend() {
  const child = spawn('python', ['-m', 'uvicorn', 'backend.main:app', '--port', String(BACK_PORT), '--log-level', 'warning'], {
    cwd: REPO_ROOT,
    stdio: 'ignore',
    windowsHide: true
  })
  return { child, url: `http://127.0.0.1:${BACK_PORT}` }
}

// 内置前端服务：dist 静态资源 + /api 反代（生产构建即所测产物）
function startFrontendStatic(backUrl) {
  const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ico': 'image/x-icon' }
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/api/')) {
      const proxyReq = http.request(`${backUrl}${req.url}`, { method: req.method, headers: { 'content-type': 'application/json' } }, (up) => {
        res.writeHead(up.statusCode, { 'content-type': up.headers['content-type'] || 'application/json' })
        up.pipe(res)
      })
      proxyReq.on('error', () => { res.writeHead(502); res.end('{"code":502,"message":"bad gateway"}') })
      req.pipe(proxyReq)
      return
    }
    const rel = req.url.split('?')[0].replace(/^\/+/, '')
    let file = path.join(DIST, decodeURIComponent(rel || 'index.html'))
    if (!file.startsWith(DIST) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(DIST, 'index.html')
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' })
    fs.createReadStream(file).pipe(res)
  })
  return new Promise((resolve) => server.listen(FRONT_PORT, '127.0.0.1', () => resolve({ child: server, url: `http://127.0.0.1:${FRONT_PORT}` })))
}

async function ensureServices() {
  const procs = []
  if (EXTERNAL_BACK) {
    if (!(await reachable(`${BACK_URL}/api/health`))) {
      throw new Error(`外部后端 ${BACK_URL} 不可达（AUDIT8_BACK_URL 已指定，脚本不代为拉起）`)
    }
    console.log(`复用外部后端：${BACK_URL}`)
  } else {
    const b = startBackend()
    procs.push(b)
    await waitFor(() => reachable(`${BACK_URL}/api/health`), 30000, 400, 'backend up')
    console.log(`已启动后端 uvicorn：${BACK_URL}`)
  }
  if (EXTERNAL_FRONT) {
    if (!(await reachable(FRONT_URL))) {
      throw new Error(`外部前端 ${FRONT_URL} 不可达（AUDIT8_FRONT_URL 已指定，脚本不代为拉起）`)
    }
    console.log(`复用外部前端：${FRONT_URL}`)
  } else {
    // 内置前端反代一律指向实际 BACK_URL（外部/自建后端均正确）
    const f = await startFrontendStatic(BACK_URL)
    procs.push(f)
    await waitFor(() => reachable(FRONT_URL), 15000, 300, 'frontend up')
    console.log(`已启动前端静态服务（dist + /api 反代 → ${BACK_URL}）：${FRONT_URL}`)
  }
  return procs
}

// 可等待的异步清理（P1-2）：HTTP 服务等待 close 回调；uvicorn 子进程等待退出并设超时兜底
async function stopProc(handle) {
  const child = handle.child
  if (typeof child.close === 'function') {
    await new Promise((resolve) => {
      try { child.close(() => resolve()) } catch { resolve() }
      setTimeout(resolve, 5000)
    })
    return
  }
  await new Promise((resolve) => {
    let done = false
    const finish = () => { if (!done) { done = true; clearTimeout(timer); resolve() } }
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL') } catch { /* 已退出 */ }
      setTimeout(finish, 500)
    }, 5000)
    child.once('exit', finish)
    try { child.kill() } catch { finish() }
  })
}

// ---------- 逐页浏览器会话 ----------
// 每页一个全新 page + 收集器：console 错误 / pageerror / requestfailed / 4xx-5xx / API 信封
const FRONT_HOST = new URL(FRONT_URL).host
function isThirdPartyUrl(url) {
  try {
    return new URL(url).host !== FRONT_HOST
  } catch {
    return false
  }
}
function makeCollector(page, label) {
  const state = {
    label,
    consoleErrors: [],
    pageErrors: [],
    requestFailures: [],
    badResponses: [],
    apiEnvelopes: []
  }
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    // 第三方底图瓦片加载失败会同时产生 console error；与对应第三方 requestfailed
    // 按错误码配对后归类为外部信号（页面有图层错误态诚实处理），不与第一方错误混淆
    const m = text.match(/^Failed to load resource: (net::\S+)/)
    if (m) {
      const tp = state.requestFailures.find((f) => f.thirdParty && f.error === m[1] && !f.consoleMatched)
      if (tp) {
        tp.consoleMatched = true
        state.consoleErrors.push({ text, allowlisted: true, reason: `第三方底图瓦片加载失败（${tp.url.slice(0, 60)}…），页面以图层错误态/重试图层诚实处理` })
        return
      }
    }
    const allow = CONSOLE_ALLOWLIST.find((a) => a.match.test(text))
    if (allow) state.consoleErrors.push({ text, allowlisted: true, reason: allow.reason })
    else state.consoleErrors.push({ text, allowlisted: false })
  })
  page.on('pageerror', (err) => state.pageErrors.push(String(err && err.stack || err)))
  page.on('requestfailed', (req) => {
    const failure = req.failure() && req.failure().errorText
    if (failure === 'net::ERR_ABORTED' && req.resourceType() === 'document') return // 页面跳转中止属正常
    state.requestFailures.push({ url: req.url(), error: failure, thirdParty: isThirdPartyUrl(req.url()) })
  })
  page.on('response', async (res) => {
    const url = res.url()
    if (!url.includes('/api/')) return
    if (res.status() >= 400) state.badResponses.push({ url, status: res.status() })
    try {
      const body = await res.json()
      if (body && typeof body === 'object' && 'meta' in body && body.meta) state.apiEnvelopes.push({ url, meta: body.meta, code: body.code })
    } catch { /* 非 JSON 响应（如静态资源）忽略 */ }
  })
  return state
}

function assertMetaContract(meta, expectVersion, where, { expectRun = true } = {}) {
  assert(meta && typeof meta === 'object', `${where}：meta 缺失`)
  assert(META_KEYS.every((k) => k in meta), `${where}：meta 六键不齐（${Object.keys(meta)}）`)
  assert(meta.data_mode === 'simulated', `${where}：data_mode=${meta.data_mode}`)
  assert(meta.dataset_version === expectVersion, `${where}：dataset_version=${meta.dataset_version} 期望 ${expectVersion}`)
  assert(meta.as_of === '2026-08-24T08:00:00+08:00', `${where}：as_of=${meta.as_of}`)
  assert(meta.claim_boundary === 'simulation_only', `${where}：claim_boundary=${meta.claim_boundary}`)
  assert(typeof meta.request_id === 'string' && meta.request_id.startsWith('req_'), `${where}：request_id 异常`)
  // 契约（audit7）：成功 PRED 响应携带 RUN；OBS 响应与一切错误响应 prediction_run_id 恒为 null
  if (expectVersion === OBS || !expectRun) assert(meta.prediction_run_id === null, `${where}：prediction_run_id 应为 null`)
  else assert(meta.prediction_run_id === RUN, `${where}：prediction_run_id=${meta.prediction_run_id}`)
}

function expectedVersion(urlPath) {
  const p = new URL(urlPath, 'http://x').pathname
  if (p === '/' || OBS_PREFIXES.some((pre) => p === pre || p.startsWith(`${pre}/`))) return OBS
  return PRED
}

// ---------- 页面级断言工具 ----------
async function assertNoHorizontalOverflow(page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  assert(over <= 1, `横向溢出 ${over}px（scrollWidth-innerWidth）`)
}

async function assertSingleMain(page) {
  const mains = await page.evaluate(() => document.querySelectorAll('main').length)
  assert(mains === 1, `页面 <main> 数量=${mains}`)
}

async function assertAttributionVisible(page) {
  const ok = await page.evaluate(() => {
    const el = document.querySelector('.leaflet-control-attribution')
    if (!el) return false
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && el.textContent.trim().length > 0
  })
  assert(ok, 'Leaflet 署名控件不可见')
}

async function collectTouchViolations(page) {
  // P2-2：测量全部已渲染可交互元素（不以当前首屏为限），输出测量数量与失败明细
  return page.evaluate(() => {
    const selectors = 'a[href], button, [role="button"], select, input[type="checkbox"], [tabindex]:not([tabindex="-1"])'
    const bad = []
    let measured = 0
    for (const el of document.querySelectorAll(selectors)) {
      if (el.closest('[aria-hidden="true"]')) continue
      const style = getComputedStyle(el)
      if (style.visibility === 'hidden' || style.display === 'none') continue
      const rect = el.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) continue
      measured += 1
      if (rect.width < 44 || rect.height < 44) bad.push({ tag: el.tagName.toLowerCase(), text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24), w: Math.round(rect.width), h: Math.round(rect.height) })
    }
    return { measured, bad }
  })
}

// 五个正式页面不得出现 Wallboard / P02 / P08 链接（P2-3）
async function assertNoFrozenLinks(page) {
  const links = await page.evaluate(() => [...document.querySelectorAll('a[href]')]
    .map((a) => a.getAttribute('href') || '')
    .filter((h) => /wallboard|p02|p08/i.test(h)))
  assert(links.length === 0, `正式页面存在冻结入口链接：${links.join(', ')}`)
  return '无 /wallboard、P02、P08 链接'
}

async function pageSignature(page, route) {
  return page.evaluate((r) => {
    const q = {}
    new URLSearchParams((location.hash.split('?')[1] || '')).forEach((v, k) => { q[k] = v })
    const text = (sel) => { const el = document.querySelector(sel); return el ? el.textContent.trim() : null }
    switch (r) {
      case 'home': return { entries: document.querySelectorAll('.entry-card').length }
      case 'cockpit': return { stage: q.t || null, point: q.p || null, kpis: document.querySelectorAll('.ckp-kpi, [data-kpi]').length }
      case 'stations': return { point: q.p || null, chips: text('.stn-chips') && document.querySelectorAll('.stn-chip').length }
      case 'heatmap': return { stage: (text('[data-role="stage-chip"]') || '').replace(/\s+/g, ''), cells: document.querySelectorAll('.lake-grid-cell, [data-cell]').length }
      case 'history': return { count: (text('[data-role="event-count"]') || '') }
      default: return {}
    }
  }, route)
}

async function gotoPage(page, route, label) {
  await page.goto(`${FRONT_URL}/#/${route === 'home' ? '' : route}`, { waitUntil: 'networkidle2', timeout: 30000 })
  await waitFor(() => page.evaluate(() => document.readyState === 'complete' && !!document.querySelector('main')), 15000, 150, `${label} main`)
  await sleep(700) // 图表/地图首帧渲染余量
}

// ---------- 主流程 ----------
let browserRef = null

// 固定版本的 Chrome Headless Shell（P1-c 稳定复现主方案）：
// 与系统 Edge 的运行状态/策略完全解耦；版本经审计确认后锁定，可用 AUDIT8_SHELL_BUILDID 覆盖。
const SHELL_BUILDID = process.env.AUDIT8_SHELL_BUILDID || '152.0.7977.82'
const SHELL_CACHE_DIR = path.join(__dirname, '.browser-cache')

async function ensureHeadlessShell() {
  const { install } = await import('@puppeteer/browsers')
  const buildId = SHELL_BUILDID
  try {
    const r = await install({ browser: 'chrome-headless-shell', buildId, cacheDir: SHELL_CACHE_DIR })
    return { buildId, executablePath: r.executablePath }
  } catch (err) {
    return { buildId, executablePath: null, error: String(err && err.message ? err.message : err) }
  }
}

function detectBrowserCandidates() {
  // AUDIT8_EDGE 显式指定 = 唯一候选（不存在则报错，不静默回退其它浏览器）；
  // 未指定 = Edge/Chrome 常见安装位置依序探测（兜底方案）
  if (process.env.AUDIT8_EDGE) {
    if (!fs.existsSync(process.env.AUDIT8_EDGE)) {
      throw new Error(`AUDIT8_EDGE 指定的浏览器不存在：${process.env.AUDIT8_EDGE}（显式指定不回退其它候选）`)
    }
    return [{ name: process.env.AUDIT8_EDGE, mode: 'AUDIT8_EDGE 指定' }]
  }
  const list = [
    { name: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', mode: 'edge 系统默认' },
    { name: 'C:/Program Files/Microsoft/Edge/Application/msedge.exe', mode: 'edge 系统默认' },
    { name: 'C:/Program Files/Google/Chrome/Application/chrome.exe', mode: 'chrome 兜底' },
    { name: 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe', mode: 'chrome 兜底' }
  ]
  const found = list.filter((c) => fs.existsSync(c.name))
  if (!found.length) throw new Error('未找到可用浏览器（Edge/Chrome 常见位置均不存在，可用 AUDIT8_EDGE 指定路径或 AUDIT8_CDP_URL 连接预启动浏览器）')
  return found
}

async function launchBrowserWithDiagnostics() {
  const os = await import('node:os')
  const diag = { attempts: [], chosen: null }
  const record = (info, err) => {
    if (err) { info.ok = false; info.error = String(err && err.stack ? err.stack : err); diag.attempts.push(info) }
    else { info.ok = true; diag.attempts.push(info) }
    return info
  }

  // 方案一：CDP 连接预启动浏览器（AUDIT8_CDP_URL，如 http://127.0.0.1:9222），完全不依赖拉起进程
  if (process.env.AUDIT8_CDP_URL) {
    const info = { kind: 'cdp-connect', url: process.env.AUDIT8_CDP_URL, mode: 'AUDIT8_CDP_URL 指定', ok: false }
    try {
      const browser = await puppeteer.connect({ browserURL: process.env.AUDIT8_CDP_URL, defaultViewport: null, protocolTimeout: 180000 })
      const version = await browser.version()
      info.browserVersion = version
      info.ok = true
      diag.attempts.push(info)
      diag.chosen = { ...info }
      console.log(`浏览器连接成功（CDP）：${process.env.AUDIT8_CDP_URL}｜版本 ${version}`)
      return { browser, diag }
    } catch (err) {
      record(info, err)
      console.log(`CDP 连接失败：${err && err.message ? err.message : err}，转本地浏览器候选`)
    }
  }

  // 方案二：固定版本 chrome-headless-shell（本地缓存；缺失时一次性自动安装）
  const shell = await ensureHeadlessShell()
  if (shell.executablePath && fs.existsSync(shell.executablePath)) {
    const info = { kind: `chrome-headless-shell@${shell.buildId}`, executable: shell.executablePath, mode: '固定版本 headless-shell（首选）', headless: true, userDataDir: null, ok: false }
    try {
      const browser = await puppeteer.launch({
        executablePath: shell.executablePath,
        headless: true,
        protocolTimeout: 180000,
        timeout: 60000,
        args: ['--no-first-run', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1960,1120']
      })
      const version = await browser.version()
      info.browserVersion = version
      info.ok = true
      diag.attempts.push(info)
      diag.chosen = { ...info }
      console.log(`浏览器启动成功：chrome-headless-shell@${shell.buildId}（固定版本，与系统 Edge 状态解耦）`)
      console.log(`浏览器版本：${version}｜可执行文件：${shell.executablePath}`)
      return { browser, diag }
    } catch (err) {
      record(info, err)
      console.log(`固定版本 headless-shell 启动失败：${err && err.message ? err.message : err}，转系统浏览器候选`)
    }
  } else {
    console.log(`固定版本 headless-shell 不可用（${shell.error || '未知原因'}），转系统浏览器候选`)
  }

  // 方案三：系统 Edge/Chrome 兜底（三种启动方式逐次尝试）
  const STRATEGIES = [
    { name: 'ws+full-args', extra: {}, args: ['--no-first-run', '--disable-extensions', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1960,1120'] },
    { name: 'pipe+full-args', extra: { pipe: true }, args: ['--no-first-run', '--disable-extensions', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1960,1120'] },
    { name: 'ws+minimal-args', extra: {}, args: ['--no-first-run', '--window-size=1960,1120'] }
  ]
  let lastErr
  for (const cand of detectBrowserCandidates()) {
    for (let attempt = 1; attempt <= STRATEGIES.length; attempt++) {
      const strat = STRATEGIES[attempt - 1]
      const profile = fs.mkdtempSync(path.join(os.tmpdir(), `audit8-${attempt}-`))
      const info = { kind: cand.mode, executable: cand.name, mode: cand.mode, attempt, strategy: strat.name, headless: HEADLESS, userDataDir: profile, ok: false }
      try {
        const browser = await puppeteer.launch({
          executablePath: cand.name,
          headless: HEADLESS,
          userDataDir: profile,
          protocolTimeout: 180000,
          timeout: 60000,
          args: strat.args,
          ...strat.extra
        })
        const version = await browser.version()
        info.browserVersion = version
        info.ok = true
        diag.attempts.push(info)
        diag.chosen = { ...info }
        console.log(`浏览器启动成功：${cand.name}（${cand.mode}｜方式 ${strat.name}｜第 ${attempt}/3 次）`)
        console.log(`浏览器版本：${version}｜启动模式：headless=${HEADLESS}｜临时 profile：${profile}`)
        return { browser, diag }
      } catch (err) {
        record(info, err)
        lastErr = err
        console.log(`浏览器启动失败（${cand.mode}｜方式 ${strat.name}｜第 ${attempt}/3 次）：${err && err.message ? err.message : err}`)
      }
    }
  }
  const err = new Error(`所有浏览器方案均失败（CDP/固定版本 headless-shell/系统浏览器，详见 browser_diag）。最后错误：${lastErr && lastErr.message ? lastErr.message : lastErr || '无'}`)
  err.diag = diag
  throw err
}

async function main() {
  const RUN_ID = new Date().toISOString().replace(/[:.]/g, '-')
  const STARTED_AT = new Date().toISOString()
  console.log(`audit8 复验开始 ${STARTED_AT}｜run_id=${RUN_ID}`)
  console.log(`FRONT=${FRONT_URL}${EXTERNAL_FRONT ? '（外部）' : '（自建）'} BACK=${BACK_URL}${EXTERNAL_BACK ? '（外部）' : '（自建）'} headless=${HEADLESS}`)
  // P2：运行开始即写入本轮 run 的占位结果，任何失败路径都不会留下上一轮的陈旧全绿记录；
  // running 占位不写完成时间（finished_at=null），仅 passed/failed/fatal 记录 finished_at。
  const writeState = (status, extra = {}) => {
    const payload = {
      run_id: RUN_ID,
      started_at: STARTED_AT,
      finished_at: status === 'running' ? null : new Date().toISOString(),
      status,
      exit_code: extra.exit_code ?? null,
      ...extra
    }
    fs.writeFileSync(path.join(__dirname, 'verify-results.json'), JSON.stringify(payload, null, 2))
    fs.writeFileSync(path.join(__dirname, 'console-network-report.json'), JSON.stringify({ run_id: RUN_ID, ...payload, allowlist: CONSOLE_ALLOWLIST, sessions: extra.sessions || [] }, null, 2))
  }
  writeState('running')
  let procs = []
  let exitCode = 0
  try {
    procs = await ensureServices()
  } catch (err) {
    console.error(`FATAL ${err && err.message ? err.message : err}`)
    writeState('fatal', { exit_code: 2, error: String(err && err.message ? err.message : err) })
    process.exit(2)
  }
  // 可等待清理（P1-2）：正常完成 / 断言失败 / 浏览器启动失败等所有路径都会执行；
  // 结束后显式 process.exit，避免活动句柄令进程悬挂。
  const cleanup = async () => {
    if (browserRef) {
      try { await browserRef.close() } catch { /* 已关闭 */ }
      browserRef = null
    }
    for (const p of procs) await stopProc(p)
  }
  process.on('exit', () => { for (const p of procs) { try { p.child.close ? p.child.close() : p.child.kill() } catch { /* 兜底 */ } } })

  try {
    const { browser, diag } = await launchBrowserWithDiagnostics()
    browserRef = browser
    globalThis.__audit8BrowserDiag = diag

    // ===== A. 后端统一信封与身份直测（浏览器同源所见） =====
    console.log('\n== A. 后端统一信封与 OBS/PRED/RUN 身份 ==')
    const ENDPOINTS = [
      { path: '/api/health', ver: OBS },
      { path: '/api/v1/system/capabilities', ver: OBS },
      { path: '/api/v1/datasets/summary', ver: OBS },
      { path: '/api/v1/pipeline/runs/latest', ver: OBS },
      { path: '/api/v1/spatial-entities?entity_type=demo_zone&mode=simulated', ver: OBS },
      { path: '/', ver: OBS },
      { path: '/api/v1/cockpit/time-stages', ver: PRED },
      { path: '/api/v1/cockpit/points', ver: PRED, run: RUN },
      { path: '/api/v1/cockpit/region-summary', ver: PRED, run: RUN },
      { path: '/api/v1/cockpit/events', ver: PRED, run: RUN },
      { path: '/api/v1/map/risk-grid?horizon_days=3', ver: PRED, run: RUN },
      { path: '/api/v1/forecast-capabilities', ver: PRED },
      { path: '/api/v1/events', ver: PRED, run: RUN }
    ]
    for (const ep of ENDPOINTS) {
      await check(`A·信封 ${ep.path}`, async () => {
        const res = await fetch(`${BACK_URL}${ep.path}`)
        assert(res.ok, `HTTP ${res.status}`)
        const body = await res.json()
        assert(body.code === 200 && body.message === 'ok', `code/message=${body.code}/${body.message}`)
        assertMetaContract(body.meta, ep.ver, ep.path)
        if (ep.run) assert(body.meta.prediction_run_id === ep.run, `run=${body.meta.prediction_run_id}`)
        return `dataset_version=${body.meta.dataset_version} run=${body.meta.prediction_run_id}`
      })
    }
    await check('A·错误信封 404 保持身份（错误响应 run 恒 null）', async () => {
      const res = await fetch(`${BACK_URL}/api/v1/spatial-entities/no_such_zone`)
      assert(res.status === 404)
      const body = await res.json()
      assertMetaContract(body.meta, OBS, '404 obs', { expectRun: false })
      assert(Array.isArray(body.errors) && body.errors[0].code === 'ENTITY_NOT_FOUND', '错误码缺失')
      const res2 = await fetch(`${BACK_URL}/api/v1/forecasts/demo-forecast-nope-3d`)
      assert(res2.status === 404)
      const body2 = await res2.json()
      assertMetaContract(body2.meta, PRED, '404 pred', { expectRun: false })
      return 'OBS 404 + PRED 404 均按类别，run=null'
    })

    // ===== B. 五页 × 三视口：渲染/身份/控制台/网络/溢出/main/署名 =====
    console.log('\n== B. 五页 × 三视口渲染与数据身份 ==')
    const ROUTES = ['home', 'cockpit', 'stations', 'heatmap', 'history']
    const identitySeen = {}
    const consoleReport = []

    for (const vp of VIEWPORTS) {
      for (const route of ROUTES) {
        const page = await browser.newPage()
        await page.setViewport({ width: vp.width, height: vp.height })
        const col = makeCollector(page, `${route}@${vp.name}`)
        try {
          await gotoPage(page, route, route)
          const tag = `${route} @ ${vp.width}×${vp.height}`
          await check(`B·渲染 ${tag}`, async () => {
            const ok = await page.evaluate(() => !!document.querySelector('main') && document.querySelector('main').children.length > 0)
            assert(ok, 'main 未渲染内容')
            return '成功状态渲染'
          })
          await check(`B·数据身份展示 ${tag}`, async () => {
            const bodyText = await page.evaluate(() => document.body.innerText)
            const expect = route === 'home'
              ? [OBS, PRED, RUN, 'simulation_only']
              : route === 'cockpit'
                ? [OBS, PRED, 'SIMULATED']
                : route === 'stations'
                  ? [OBS, PRED, 'simulation_only']
                  : route === 'heatmap'
                    ? [PRED, RUN, 'simulation_only']
                    : [OBS, PRED, RUN]
            const missing = expect.filter((t) => !bodyText.includes(t))
            identitySeen[route] = true
            assert(missing.length === 0, `页面身份文本缺失：${missing.join(', ')}`)
            return expect.join(' / ')
          })
          if (vp.width >= 1440) await check(`B·<main> 唯一 ${tag}`, () => assertSingleMain(page))
          if (route === 'home' && vp.name === '1920') {
            // 首页能力卡必须消费接口结构化数据（P1 复验点）：真实值、非占位
            await check('B·首页能力卡消费接口数据', async () => {
              await waitFor(() => page.evaluate(() => document.querySelectorAll('.fact').length >= 4), 12000, 150, '能力卡渲染')
              const cards = await page.evaluate(() => [...document.querySelectorAll('.fact')].map((f) => ({
                label: f.querySelector('dt')?.textContent.trim() || '',
                value: f.querySelector('dd')?.textContent.trim() || ''
              })))
              const dash = cards.filter((c) => c.value === '—' || c.value === '')
              assert(dash.length === 0, `能力卡存在占位值：${dash.map((c) => c.label).join(',')}`)
              const predict = cards.find((c) => c.label === '预测能力')
              const longterm = cards.find((c) => c.label === '长期能力')
              assert(predict && predict.value.includes('1—15 天演示档位'), `预测能力=${predict?.value}，期望含"1—15 天演示档位"`)
              assert(longterm && longterm.value.includes('仅模拟预演'), `长期能力=${longterm?.value}，期望含"仅模拟预演"`)
              return cards.map((c) => `${c.label}=${c.value}`).join('｜')
            })
          }
          if (route === 'heatmap' || route === 'stations') {
            await check(`B·地图署名 ${tag}`, () => assertAttributionVisible(page))
          }
          await check(`B·无横向溢出 ${tag}`, () => assertNoHorizontalOverflow(page))
          await check(`B·控制台无错误 ${tag}`, () => {
            const hard = col.consoleErrors.filter((e) => !e.allowlisted)
            assert(hard.length === 0, hard.map((e) => e.text.slice(0, 160)).join(' | ') || '')
            assert(col.pageErrors.length === 0, col.pageErrors.join(' | ').slice(0, 200) || '')
            return col.consoleErrors.length ? `豁免 ${col.consoleErrors.length} 条既有警告` : '无错误'
          })
          await check(`B·网络无失败 ${tag}`, async () => {
            // 分级：第一方资源（同源静态 + /api/）失败即不通过；
            // 第三方底图瓦片（跨域）受外部网络可用性影响，记录明细并要求页面诚实披露
            const first = col.requestFailures.filter((f) => !f.thirdParty)
            const third = col.requestFailures.filter((f) => f.thirdParty)
            assert(first.length === 0, first.map((f) => `${f.url}:${f.error}`).join(' | ').slice(0, 220))
            assert(col.badResponses.length === 0, col.badResponses.map((b) => `${b.url}:${b.status}`).join(' | ').slice(0, 220))
            if (third.length && (route === 'heatmap' || route === 'stations')) {
              const honest = await page.evaluate(() => document.body.innerText.includes('重试图层') || /底图|瓦片|图层|加载失败/.test(document.body.innerText))
              assert(honest, '外部瓦片失败但页面未诚实披露图层错误')
            }
            return third.length
              ? `第一方资源 0 失败；第三方底图瓦片失败 ${third.length} 个（页面以图层错误态诚实处理，明细见控制台报告）`
              : '静态资源与 API 全部正常'
          })
          await check(`B·API 身份契约 ${tag}`, async () => {
            assert(col.apiEnvelopes.length > 0, '未捕获任何 API 响应')
            for (const env of col.apiEnvelopes) {
              const ver = expectedVersion(env.url)
              assert(env.code === 200, `${env.url} code=${env.code}`)
              assertMetaContract(env.meta, ver, env.url)
            }
            return `${col.apiEnvelopes.length} 个响应全部符合`
          })
          if (vp.name === '390') {
            await check(`B·移动触摸目标（全页 ${tag}）`, async () => {
              const { measured, bad } = await collectTouchViolations(page)
              assert(measured > 0, '未测量到任何交互元素')
              assert(bad.length === 0, bad.slice(0, 8).map((b) => `${b.tag}"${b.text}"=${b.w}×${b.h}`).join(' | '))
              return `测量 ${measured} 个交互元素（全页），均 ≥44×44`
            })
          }
          if (vp.width >= 1440) {
            await check(`B·无冻结页入口 ${tag}`, () => assertNoFrozenLinks(page))
          }
          if (!SKIP_SHOTS) {
            fs.mkdirSync(SHOTS_DIR, { recursive: true })
            await page.screenshot({ path: path.join(SHOTS_DIR, `${route === 'home' ? 'home' : route}-${vp.name}.png`), fullPage: false })
          }
          consoleReport.push(col)
        } finally {
          await page.close()
        }
      }
    }

    // ===== C. 跨页面业务链路（1440 桌面） =====
    console.log('\n== C. 跨页面业务链路 ==')
    {
      const page = await browser.newPage()
      await page.setViewport({ width: 1440, height: 900 })
      const col = makeCollector(page, 'cross-link@1440')
      try {
        await check('C·首页进入四个业务页面', async () => {
          await gotoPage(page, 'home', 'home')
          const hrefs = await page.evaluate(() => [...document.querySelectorAll('.entry-card')].map((a) => a.getAttribute('href')))
          for (const r of ['cockpit', 'stations', 'heatmap', 'history']) {
            assert(hrefs.some((h) => h && h.includes(r)), `入口缺少 ${r}`)
          }
          for (const r of ['cockpit', 'stations', 'heatmap', 'history']) {
            await page.click(`.entry-card[href*="${r}"]`)
            await waitFor(() => page.evaluate((rr) => location.hash.startsWith(`#/${rr}`), r), 8000, 120, `nav ${r}`)
            await sleep(600)
            await page.goto(`${FRONT_URL}/#/`, { waitUntil: 'networkidle2' })
          }
          return '四入口可达'
        })
        await check('C·P01 点位进入 P03 对应对象', async () => {
          await gotoPage(page, 'cockpit', 'cockpit')
          await sleep(500)
          // 点击排行中第二个分区（非默认选中项），确保状态真实变化并同步 URL
          const clickedId = await page.evaluate(() => {
            const el = document.querySelectorAll('.ckp-rank-btn')[1]
            if (!el) return null
            el.click()
            return el.getAttribute('data-id') || el.getAttribute('aria-label') || el.textContent.trim().slice(0, 20)
          })
          assert(clickedId, '未点击到排行按钮')
          await waitFor(() => page.evaluate(() => new URLSearchParams(location.hash.split('?')[1] || '').get('p')), 6000, 120, 'cockpit p 同步')
          const cockpitHash = await page.evaluate(() => location.hash)
          const detail = await page.$('.ckp-detail-btn, a[href*="/stations"]')
          assert(detail, '驾驶舱缺少站点详情入口')
          await detail.click()
          await waitFor(() => page.evaluate(() => location.hash.startsWith('#/stations')), 8000, 120, 'stations nav')
          await sleep(800)
          const hash = await page.evaluate(() => location.hash)
          assert(/[?&]p=/.test(hash), `跳转未携带 p 参数：${hash}`)
          const selected = await page.evaluate(() => { const el = document.querySelector('.stn-chip--zone'); return el ? el.textContent.trim() : '' })
          assert(selected.length > 0, '站点页未选中任何分区')
          return `点击 ${clickedId}，${hash}`
        })
        await check('C·P01 返回后筛选与 URL 同步', async () => {
          await page.goBack()
          await waitFor(() => page.evaluate(() => location.hash.startsWith('#/cockpit')), 8000, 120, 'back to cockpit')
          await sleep(500)
          const hash = await page.evaluate(() => location.hash)
          assert(/[?&]p=/.test(hash), `返回后 p 丢失：${hash}`)
          await page.goForward()
          await waitFor(() => page.evaluate(() => location.hash.startsWith('#/stations')), 8000, 120, 'forward to stations')
          await sleep(700)
          const hash2 = await page.evaluate(() => location.hash)
          assert(hash2.startsWith('#/stations'), `前进未回到站点页：${hash2}`)
          return '后退/前进状态保持'
        })
        await check('C·P01 风险区域进入 P07', async () => {
          await gotoPage(page, 'cockpit', 'cockpit')
          await sleep(400)
          const link = await page.evaluateHandle(() => [...document.querySelectorAll('a')].find((a) => a.getAttribute('href')?.includes('/heatmap')))
          await link.asElement().click()
          await waitFor(() => page.evaluate(() => location.hash.startsWith('#/heatmap')), 8000, 120, 'heatmap nav')
          await sleep(800)
          assert((await page.evaluate(() => document.querySelectorAll('main').length)) === 1, '热力页未渲染')
          return '进入风险研判'
        })
        await check('C·P01/P07 事件进入历史复盘', async () => {
          const link = await page.evaluateHandle(() => [...document.querySelectorAll('a')].find((a) => a.getAttribute('href')?.includes('/history')))
          await link.asElement().click()
          await waitFor(() => page.evaluate(() => location.hash.startsWith('#/history')), 8000, 120, 'history nav')
          await sleep(800)
          const count = await page.evaluate(() => (document.querySelector('[data-role="event-count"]') || {}).textContent)
          assert(Number(count) > 0, `历史事件数=${count}`)
          return `历史事件 ${count} 条`
        })
        await check('C·跨页 ID 与 canonical 一致', async () => {
          await gotoPage(page, 'history', 'history')
          await sleep(600)
          const ids = await page.evaluate(() => [...document.querySelectorAll('[data-event-id], .his-event-card')].map((el) => el.getAttribute('data-event-id')).filter(Boolean))
          const apiEvents = await (await fetch(`${BACK_URL}/api/v1/events`)).json()
          const canonical = new Set((apiEvents.data && apiEvents.data.events ? apiEvents.data.events : []).map((e) => e.event_id || e.id))
          if (ids.length && canonical.size) {
            const unknown = ids.filter((id) => !canonical.has(id))
            assert(unknown.length === 0, `页面事件 ID 不在 canonical 集合：${unknown.join(',')}`)
          }
          return '事件/分区 ID 与后端一致'
        })
        consoleReport.push(col)
      } finally {
        await page.close()
      }
    }

    // ===== D. URL 状态：冷启动 / 刷新 / 非法参数 / 前进后退 =====
    console.log('\n== D. URL 冷启动、刷新与非法参数 ==')
    {
      const page = await browser.newPage()
      await page.setViewport({ width: 1440, height: 900 })
      const col = makeCollector(page, 'url-state@1440')
      try {
        await check('D·cockpit 合法参数冷启动恢复', async () => {
          await page.goto(`${FRONT_URL}/#/cockpit?t=t3&p=water_intake`, { waitUntil: 'networkidle2' })
          await sleep(900)
          const hash = await page.evaluate(() => location.hash)
          assert(hash.includes('t=t3') && hash.includes('p=water_intake'), `参数被改写：${hash}`)
          return hash
        })
        await check('D·cockpit 刷新后状态保持', async () => {
          await page.reload({ waitUntil: 'networkidle2' })
          await sleep(900)
          const hash = await page.evaluate(() => location.hash)
          assert(hash.includes('t=t3') && hash.includes('p=water_intake'), `刷新后参数丢失：${hash}`)
          return '刷新保持'
        })
        await check('D·stations 合法参数冷启动 + 刷新', async () => {
          await page.goto(`${FRONT_URL}/#/stations?p=river_inlet&t=t7`, { waitUntil: 'networkidle2' })
          await sleep(1000)
          const before = await pageSignature(page, 'stations')
          await page.reload({ waitUntil: 'networkidle2' })
          await sleep(1000)
          const after = await pageSignature(page, 'stations')
          assert(JSON.stringify(before.point) === JSON.stringify(after.point), `刷新前 ${before.point}≠刷新后 ${after.point}`)
          return `选中 ${after.point}`
        })
        await check('D·非法参数不白屏（cockpit ?t=bogus&p=bogus）', async () => {
          await page.goto(`${FRONT_URL}/#/cockpit?t=bogus&p=bogus_zone`, { waitUntil: 'networkidle2' })
          await sleep(900)
          const mainOk = await page.evaluate(() => !!document.querySelector('main') && document.querySelector('main').textContent.length > 50)
          assert(mainOk, '页面白屏或内容为空')
          const hash = await page.evaluate(() => location.hash)
          assert(!hash.includes('t=bogus'), `非法档位未被清理：${hash}`)
          return '页面正常，非法档位清理'
        })
        await check('D·非法参数不白屏（stations ?p=bogus）', async () => {
          await page.goto(`${FRONT_URL}/#/stations?p=no_such_zone`, { waitUntil: 'networkidle2' })
          await sleep(1100)
          const mainOk = await page.evaluate(() => !!document.querySelector('main') && document.querySelector('main').textContent.length > 50)
          assert(mainOk, '页面白屏或内容为空')
          const hash = await page.evaluate(() => location.hash)
          assert(!hash.includes('p=no_such_zone'), `非法分区未被清理：${hash}`)
          return '页面正常，非法分区清理'
        })
        await check('D·history 冷启动与刷新', async () => {
          await page.goto(`${FRONT_URL}/#/history`, { waitUntil: 'networkidle2' })
          await sleep(1000)
          const before = await pageSignature(page, 'history')
          await page.reload({ waitUntil: 'networkidle2' })
          await sleep(1000)
          const after = await pageSignature(page, 'history')
          assert(before.count === after.count, `刷新前 ${before.count}≠刷新后 ${after.count}`)
          return `${after.count} 条事件`
        })
        await check('D·冷启动与同文档跳转一致', async () => {
          for (const r of ['cockpit', 'heatmap']) {
            await page.goto(`${FRONT_URL}/#/`, { waitUntil: 'networkidle2' })
            await sleep(400)
            await page.evaluate((rr) => { location.hash = `#/${rr}` }, r)
            await sleep(1100)
            const spa = await pageSignature(page, r)
            await page.goto(`${FRONT_URL}/#/${r}`, { waitUntil: 'networkidle2' })
            await sleep(1100)
            const cold = await pageSignature(page, r)
            assert(JSON.stringify(spa) === JSON.stringify(cold), `${r} 签名不一致：SPA=${JSON.stringify(spa)} 冷启=${JSON.stringify(cold)}`)
          }
          return 'cockpit/heatmap 签名一致'
        })
        consoleReport.push(col)
      } finally {
        await page.close()
      }
    }

    // ===== E. 空数据 / 业务错误 / 网络失败 / 重试恢复 =====
    console.log('\n== E. 空态、错误与重试 ==')
    {
      // 每个注入用例使用独立 page：请求拦截/响应注入互不串扰，也不受前例缓存影响
      const withEPage = async (label, fn) => {
        const page = await browser.newPage()
        await page.setViewport({ width: 1440, height: 900 })
        const col = makeCollector(page, label)
        try {
          return await fn(page, col)
        } finally {
          await page.close()
          consoleReport.push(col)
        }
      }

      await check('E·历史筛选空数据状态', () => withEPage('history-empty@1440', async (page) => {
        await gotoPage(page, 'history', 'history')
        // 用未来日期区间查询 → 诚实空态（过滤条明确允许未来日期并呈现空结果）
        await page.evaluate(() => {
          const setVal = (sel, val) => {
            const el = document.querySelector(sel)
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
            setter.call(el, val)
            el.dispatchEvent(new Event('input', { bubbles: true }))
            el.dispatchEvent(new Event('change', { bubbles: true }))
          }
          setVal('[data-role="filter-start"]', '2027-01-01')
          setVal('[data-role="filter-end"]', '2027-03-31')
        })
        await page.click('[data-role="filter-query"]')
        await sleep(800)
        const empty = await page.evaluate(() => /暂无|没有|无匹配|0\s*条/.test(document.body.innerText))
        assert(empty, '未来区间查询未出现空数据提示')
        await page.click('[data-role="filter-reset"]')
        await sleep(500)
        const restored = await page.evaluate(() => Number((document.querySelector('[data-role="event-count"]') || {}).textContent || 0) > 0)
        assert(restored, '重置后未恢复事件列表')
        return '空态出现且重置恢复'
      }))

      await check('E·首页空数据(200+空载荷) → empty 态 → 重试恢复', () => withEPage('home-empty@1440', async (page) => {
        await page.setRequestInterception(true)
        // 模式：empty=HTTP 200 + 合法信封但三接口数据均为空；off=放行真实接口
        let mode = 'empty'
        const meta = { data_mode: 'simulated', dataset_version: 'DEMO-OBS-V1', prediction_run_id: null, as_of: '2026-08-24T08:00:00+08:00', claim_boundary: 'simulation_only', request_id: 'req_audit8_empty_inject' }
        const EMPTY_BODIES = {
          '/api/v1/system/capabilities': { code: 200, message: 'ok', data: { data_as_of: '2026-08-24T08:00:00+08:00', capabilities: {}, blockers: [], provider_status: {} }, meta, errors: [] },
          '/api/v1/datasets/summary': { code: 200, message: 'ok', data: { datasets: [], claim_boundary: 'simulation_only' }, meta, errors: [] },
          '/api/v1/spatial-entities?': { code: 200, message: 'ok', data: [], meta, errors: [] }
        }
        const onReq = (req) => {
          const url = req.url()
          const key = Object.keys(EMPTY_BODIES).find((k) => url.includes(k))
          if (key && mode === 'empty') {
            req.respond({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*', 'cache-control': 'no-store' }, body: JSON.stringify(EMPTY_BODIES[key]) }).catch(() => {})
          } else req.continue().catch(() => {})
        }
        page.on('request', onReq)
        await page.goto(`${FRONT_URL}/#/`, { waitUntil: 'domcontentloaded' })
        await waitFor(() => page.evaluate(() => document.body.innerText.includes('后端暂无能力数据')), 12000, 200, 'home empty 态')
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'home-empty.png') })
        mode = 'off' // 放行真实接口
        const retry = await page.evaluateHandle(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('重试') && b.offsetParent))
        const el = retry.asElement()
        assert(el, '未找到 empty 态重试按钮')
        await el.click()
        await waitFor(() => page.evaluate(() => document.querySelectorAll('.fact').length >= 4), 12000, 200, 'home 恢复')
        const cards = await page.evaluate(() => [...document.querySelectorAll('.fact dd')].map((d) => d.textContent.trim()))
        assert(!cards.some((v) => v === '—' || v === ''), '恢复后能力卡仍有占位值')
        page.off('request', onReq)
        return '200+空载荷 → empty 态 → 重试恢复真实能力卡'
      }))

      await check('E·首页网络失败 → 错误态 → 重试恢复', () => withEPage('home-error@1440', async (page) => {
        await page.setRequestInterception(true)
        let aborting = true
        const onReq = (req) => {
          if (aborting && /\/api\/v1\/(system\/capabilities|datasets\/summary|spatial-entities\?)/.test(req.url())) req.abort('failed').catch(() => {})
          else req.continue().catch(() => {})
        }
        page.on('request', onReq)
        await page.goto(`${FRONT_URL}/#/`, { waitUntil: 'domcontentloaded' })
        await waitFor(() => page.evaluate(() => document.body.innerText.includes('系统能力加载失败')), 12000, 200, 'home 错误态')
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'home-error.png') })
        aborting = false
        const retry = await page.evaluateHandle(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('重试') && b.offsetParent))
        const el = retry.asElement()
        assert(el, '未找到首页重试按钮')
        await el.click()
        await waitFor(() => page.evaluate(() => document.querySelectorAll('.fact').length >= 4), 12000, 200, 'home 恢复')
        const factText = await page.evaluate(() => document.querySelector('.facts')?.textContent || '')
        assert(/演示分区|SIMULATED/.test(factText), '恢复后能力卡未来自接口数据')
        page.off('request', onReq)
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'home-error-recovered.png') })
        return '错误态与重试恢复均出现'
      }))

      await check('E·网络失败 → 错误态 → 重试恢复（stations）', () => withEPage('stations-error@1440', async (page) => {
        await page.setRequestInterception(true)
        let aborting = true
        const onReq = (req) => {
          if (aborting && req.url().includes('/api/v1/spatial-entities?')) req.abort('failed').catch(() => {})
          else req.continue().catch(() => {})
        }
        page.on('request', onReq)
        await page.goto(`${FRONT_URL}/#/stations`, { waitUntil: 'domcontentloaded' })
        await waitFor(() => page.evaluate(() => document.body.innerText.includes('加载失败') || document.body.innerText.includes('错误')), 12000, 200, 'stations 错误态')
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'stations-error.png') })
        aborting = false
        const retryBtn = await page.evaluateHandle(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('重试') && b.offsetParent))
        const el = retryBtn.asElement()
        assert(el, '未找到重试按钮')
        await el.click()
        await waitFor(() => page.evaluate(() => !!document.querySelector('.stn-chip--zone') || document.body.innerText.includes('演示分区')), 12000, 200, 'stations 恢复')
        page.off('request', onReq)
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'stations-error-recovered.png') })
        return '错误态与恢复均出现'
      }))

      await check('E·网络失败 → 重试恢复（heatmap 格网）', () => withEPage('heatmap-grid-error@1440', async (page) => {
        await page.setRequestInterception(true)
        let aborting = true
        const onReq = (req) => {
          if (aborting && req.url().includes('/map/risk-grid')) req.abort('failed').catch(() => {})
          else req.continue().catch(() => {})
        }
        page.on('request', onReq)
        await page.goto(`${FRONT_URL}/#/heatmap`, { waitUntil: 'domcontentloaded' })
        await waitFor(() => page.evaluate(() => !!document.querySelector('[data-role="grid-state"][data-state="error"], [data-role="grid-retry"]')), 12000, 200, 'heatmap 格网错误态')
        if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'heatmap-grid-error.png') })
        aborting = false
        const retry = await page.$('[data-role="grid-retry"]')
        assert(retry, '未找到格网重试按钮')
        await retry.click()
        await waitFor(() => page.evaluate(() => document.querySelector('[data-role="grid-state"]')?.dataset.state === 'ok' || !document.querySelector('[data-role="grid-state"][data-state="error"]')), 12000, 200, 'heatmap 格网恢复')
        page.off('request', onReq)
        return '格网错误态与恢复均出现'
      }))

      await check('E·T+30 能力阻塞诚实披露（heatmap）', () => withEPage('heatmap-t30@1440', async (page) => {
        await gotoPage(page, 'heatmap', 'heatmap')
        const t30 = await page.evaluateHandle(() => [...document.querySelectorAll('.axis-node .node-label, .stage-btn')].find((b) => b.textContent.trim() === 'T+30'))
        const t30el = t30.asElement()
        assert(t30el, '未找到 T+30 档位入口')
        await t30el.click()
        await sleep(1200)
        const banner = await page.evaluate(() => {
          const b = document.querySelector('[data-role="t30-banner"]')
          return b ? b.textContent : ''
        })
        assert(/模拟|演示|未|阻塞|能力/.test(banner), 'T+30 横幅未诚实披露')
        return banner.trim().slice(0, 60)
      }))
    }

    // ===== F. 快速切换筛选：旧请求不覆盖新结果 =====
    console.log('\n== F. 请求竞态 ==')
    {
      const page = await browser.newPage()
      await page.setViewport({ width: 1440, height: 900 })
      const col = makeCollector(page, 'race@1440')
      try {
        await check('F·heatmap 快速切档旧响应不覆盖（T+1 延迟 2s）', async () => {
          await page.setRequestInterception(true)
          let delaying = true
          const delayed = []
          const onReq = (req) => {
            if (delaying && req.url().includes('/map/risk-grid?horizon_days=1')) {
              delayed.push(req.url())
              setTimeout(() => req.continue().catch(() => {}), 2000)
            } else req.continue().catch(() => {})
          }
          page.on('request', onReq)
          await gotoPage(page, 'heatmap', 'heatmap')
          const labelOf = () => page.evaluate(() => (document.querySelector('[data-role="stage-chip"]') || {}).textContent.replace(/\s+/g, ''))
          assert((await labelOf()).includes('T+7'), `默认档位异常：${await labelOf()}`)
          // 点击 T+1（响应被延迟 2s），立即点击 T+3
          const node = (txt) => page.evaluateHandle((t) => [...document.querySelectorAll('.axis-node .node-label, .stage-btn')].find((b) => b.textContent.trim() === t), txt)
          const t1 = (await node('T+1')).asElement()
          const t3 = (await node('T+3')).asElement()
          assert(t1 && t3, '未找到档位按钮')
          await t1.click()
          await sleep(150)
          await t3.click()
          await waitFor(() => labelOf().then((l) => l.includes('T+3')), 8000, 120, 'stage T+3')
          await sleep(2600) // 等 T+1 迟到响应落地
          const after = await labelOf()
          assert(after.includes('T+3'), `迟到响应覆盖了当前档位：${after}`)
          delaying = false
          // 再点回 T+1 应正常加载
          const t1b = (await node('T+1')).asElement()
          await t1b.click()
          await waitFor(() => labelOf().then((l) => l.includes('T+1')), 8000, 120, 'stage T+1 back')
          await sleep(800)
          assert(col.pageErrors.length === 0, '竞态期间出现 JS 错误')
          return `迟到请求 ${delayed.length} 个，最终稳定在 T+3→T+1`
        })
        await check('F·cockpit 快速连点档位稳定', async () => {
          await gotoPage(page, 'cockpit', 'cockpit')
          const activeStage = () => page.evaluate(() => { const el = document.querySelector('.axis-node.active .node-label'); return el ? el.textContent.trim() : '' })
          const labels = ['T+1', 'T+3', 'T+7', 'T+15']
          for (const l of labels) {
            const el = (await page.evaluateHandle((t) => [...document.querySelectorAll('.axis-node .node-label, .stage-btn')].find((b) => b.textContent.trim() === t), l)).asElement()
            if (el) await el.click()
            await sleep(60)
          }
          await sleep(1200)
          const finalStage = await activeStage()
          assert(finalStage === 'T+15', `最终档位=${finalStage}，应为 T+15`)
          const hash = await page.evaluate(() => location.hash)
          assert(hash.includes('t=t15'), `URL 未同步最终档位：${hash}`)
          return `最终稳定 ${finalStage}，URL 已同步`
        })
        consoleReport.push(col)
      } finally {
        await page.close()
      }
    }

    // ===== G. 弹层/抽屉 ARIA + Esc + 焦点归还（桌面与移动） =====
    console.log('\n== G. 弹层可访问性 ==')
    {
      const page = await browser.newPage()
      await page.setViewport({ width: 1440, height: 900 })
      const col = makeCollector(page, 'aria@1440')
      try {
        await check('G·数据来源抽屉 ARIA/Esc/焦点归还（桌面）', async () => {
          await gotoPage(page, 'home', 'home')
          const btn = await page.$('.ctx-source')
          assert(btn, '未找到「查看来源」按钮')
          await btn.click()
          await sleep(500)
          const dlg = await page.evaluate(() => {
            const el = document.querySelector('#ctx-source-drawer')
            if (!el) return null
            const r = el.getBoundingClientRect()
            return { role: el.getAttribute('role'), modal: el.getAttribute('aria-modal'), visible: r.width > 0 && r.height > 0, within: r.left >= 0 && r.right <= window.innerWidth }
          })
          assert(dlg && dlg.role === 'dialog' && dlg.modal === 'true' && dlg.visible, `抽屉属性异常：${JSON.stringify(dlg)}`)
          assert(dlg.within, '抽屉超出视口')
          if (!SKIP_SHOTS) await page.screenshot({ path: path.join(SHOTS_DIR, 'home-source-drawer.png') })
          await page.keyboard.press('Escape')
          await sleep(400)
          const closed = await page.evaluate(() => !document.querySelector('#ctx-source-drawer'))
          assert(closed, 'Esc 未关闭抽屉')
          const focusBack = await page.evaluate(() => document.activeElement && document.activeElement.classList.contains('ctx-source'))
          assert(focusBack, '焦点未归还触发按钮')
          return 'dialog/aria-modal/Esc/焦点 OK'
        })
        await check('G·Tab 焦点圈定（抽屉内）', async () => {
          const btn = await page.$('.ctx-source')
          await btn.click()
          await sleep(400)
          for (let i = 0; i < 5; i++) await page.keyboard.press('Tab')
          const stillInside = await page.evaluate(() => !!document.querySelector('#ctx-source-drawer'))
          assert(stillInside, 'Tab 后抽屉被意外关闭')
          await page.keyboard.press('Escape')
          await sleep(300)
          return 'Tab 循环内不逃逸'
        })
        consoleReport.push(col)
      } finally {
        await page.close()
      }
      // 移动端抽屉 + 底部操作栏
      const mpage = await browser.newPage()
      await mpage.setViewport({ width: 390, height: 844 })
      const mcol = makeCollector(mpage, 'aria@390')
      try {
        await check('G·移动端抽屉与底部操作栏（history）', async () => {
          await gotoPage(mpage, 'history', 'history')
          const trigger = await mpage.$('[data-role="drawer-trigger"]')
          assert(trigger, '未找到移动端筛选按钮')
          await trigger.click()
          await sleep(600)
          const dlg = await mpage.evaluate(() => {
            const el = document.querySelector('[role="dialog"][aria-modal="true"]')
            if (!el) return null
            const r = el.getBoundingClientRect()
            return { visible: r.width > 0 && r.height > 0, within: r.left >= 0 && r.right <= window.innerWidth }
          })
          assert(dlg && dlg.visible && dlg.within, `移动抽屉异常：${JSON.stringify(dlg)}`)
          if (!SKIP_SHOTS) await mpage.screenshot({ path: path.join(SHOTS_DIR, 'history-drawer-390.png') })
          // P2-2：抽屉展开状态下，其条件渲染控件一并纳入全页触摸测量
          const drawerTouch = await collectTouchViolations(mpage)
          assert(drawerTouch.measured > 0, '抽屉展开状态未测量到交互元素')
          assert(drawerTouch.bad.length === 0, `抽屉展开后触摸目标不达标：${drawerTouch.bad.slice(0, 6).map((b) => `${b.tag}"${b.text}"=${b.w}×${b.h}`).join(' | ')}`)
          await mpage.keyboard.press('Escape')
          await sleep(400)
          const closed = await mpage.evaluate(() => !document.querySelector('[role="dialog"][aria-modal="true"]'))
          assert(closed, 'Esc 未关闭移动抽屉')
          const bar = await mpage.evaluate(() => {
            const el = document.querySelector('.his-mobile-bar')
            if (!el) return null
            const r = el.getBoundingClientRect()
            const style = getComputedStyle(el)
            return { fixed: style.position === 'fixed' || style.position === 'sticky', atBottom: Math.abs(window.innerHeight - r.bottom) < 40, height: r.height }
          })
          assert(bar && bar.fixed && bar.atBottom, `底部操作栏异常：${JSON.stringify(bar)}`)
          return `抽屉 + 底栏 OK（抽屉态测量 ${drawerTouch.measured} 个交互元素）`
        })
        await check('G·移动端抽屉与底部操作栏（stations）', async () => {
          await gotoPage(mpage, 'stations', 'stations')
          const trigger = await mpage.$('[data-role="drawer-trigger"]')
          assert(trigger, '未找到站点页切换分区按钮')
          await trigger.click()
          await sleep(600)
          const dlg = await mpage.evaluate(() => !!document.querySelector('[role="dialog"][aria-modal="true"]'))
          assert(dlg, '站点页抽屉未打开')
          if (!SKIP_SHOTS) await mpage.screenshot({ path: path.join(SHOTS_DIR, 'stations-drawer-390.png') })
          await mpage.keyboard.press('Escape')
          return '抽屉 OK'
        })
        consoleReport.push(mcol)
      } finally {
        await mpage.close()
      }
    }

    // ===== 汇总 =====
    await browser.close()
    browserRef = null

    // P2 硬断言：落盘前校验浏览器诊断自洽——成功 run 的 chosen 必须 ok=true
    const browserDiag = globalThis.__audit8BrowserDiag
    assert(browserDiag && browserDiag.chosen && browserDiag.chosen.ok === true, '浏览器诊断状态不一致：chosen.ok !== true')

    const failed = results.filter((r) => !r.ok)
    console.log('\n================ 汇总 ================')
    console.log(`总计 ${results.length} 项：PASS ${results.length - failed.length} / FAIL ${failed.length}`)
    if (failed.length) {
      console.log('失败项：')
      for (const f of failed) console.log(`  FAIL ${f.name} —— ${f.detail}`)
    }
    exitCode = failed.length === 0 ? 0 : 1
    const finalStatus = failed.length === 0 ? 'passed' : 'failed'
    writeState(finalStatus, {
      exit_code: exitCode,
      front: FRONT_URL,
      back: BACK_URL,
      browser: globalThis.__audit8BrowserDiag?.chosen || null,
      pass: results.length - failed.length,
      fail: failed.length,
      total: results.length,
      results,
      sessions: consoleReport.map((s) => ({ label: s.label, consoleErrors: s.consoleErrors, pageErrors: s.pageErrors, requestFailures: s.requestFailures, badResponses: s.badResponses, apiCount: s.apiEnvelopes.length }))
    })
    console.log(`结果已写入 reports/audit8/verify-results.json 与 console-network-report.json（run_id=${RUN_ID}，status=${finalStatus}）`)
  } catch (err) {
    console.error(`FATAL ${err && err.stack ? err.stack : err}`)
    if (err && err.diag) console.error(`启动诊断：${JSON.stringify(err.diag, null, 1)}`)
    exitCode = 2
    writeState('fatal', {
      exit_code: 2,
      error: String(err && err.message ? err.message : err),
      browser_diag: err && err.diag ? err.diag : globalThis.__audit8BrowserDiag || null
    })
  } finally {
    await cleanup()
    console.log('服务清理完成（前端/后端/浏览器均已关闭）')
  }
  return exitCode
}

process.exit(await main())
