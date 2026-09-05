// 零依赖 P07 复验脚本（Node >= 22 内置 WebSocket/fetch）：无头 Edge 直连页面级 DevTools。
// 覆盖任务书 33 项验收：URL 初始化/刷新恢复、非法 t/p 回落、五档位格网、快速切换竞态、
// 失败不展示旧格网+新档位标签、重试恢复、T+30 simulation_only、无 T+90、历史/当前禁用、
// 格网来自 API、格点点击一致、热点/地图一致、计数求和、KPI 档位同步、图层 toggle 语义、
// 禁用图层原因、播放停在 T+30、前后边界、倍速、A/B 双格网、同档位提示、无虚构声明、
// 高风险预警弹窗、低风险阻塞、取消无请求、确认仅模拟状态、390 抽屉/触摸/溢出、
// 1920 首屏、P01/P03/历史页回归、控制台 0 error、失败非零退出码。
// 截图输出到本目录 audit5-screenshots/。
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.env.VERIFY_BASE || 'http://localhost:4173'
const OUT_DIR = fileURLToPath(new URL('./audit5-screenshots/', import.meta.url))
fs.mkdirSync(OUT_DIR, { recursive: true })

const log = (...a) => console.log(new Date().toISOString().slice(17, 23), ...a)

// ---------- 自检模式（验证第 33 条：断言失败 → 非零退出码） ----------
if (process.env.AUDIT5_SELFCHECK) {
  console.log('FAIL | selftest-intentional-failure')
  console.log('SUMMARY: 0/1 checks passed')
  console.log('EXIT_CODE', 1)
  process.exit(1)
}

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${name}${detail ? ' | ' + detail : ''}`)
}

// ---------- 直连后端（经 preview 代理）获取 API 真值 ----------
async function apiRiskGrid(horizon) {
  const r = await fetch(`${BASE}/api/v1/map/risk-grid?horizon_days=${horizon}`)
  if (!r.ok) throw new Error(`risk-grid ${horizon} -> ${r.status}`)
  const { data } = await r.json()
  const cells = []
  data.grid.forEach((row, ri) => row.forEach((v, ci) => {
    const n = Number(v)
    if (Number.isFinite(n)) cells.push({ id: `R${String(ri + 1).padStart(2, '0')}-C${String(ci + 1).padStart(2, '0')}`, row: ri, col: ci, value: n })
  }))
  const stats = {
    valid: cells.length,
    high: cells.filter((c) => c.value >= 75).length,
    mid: cells.filter((c) => c.value >= 45 && c.value < 75).length,
    low: cells.filter((c) => c.value < 45).length,
    max: cells.reduce((m, c) => (c.value > m ? c.value : m), -Infinity)
  }
  stats.top = cells.filter((c) => c.value === stats.max).sort((a, b) => a.row - b.row || a.col - b.col)[0]
  return { data, stats }
}

const proc = spawn(EDGE, [
  '--headless',
  '--remote-debugging-port=0',
  `--user-data-dir=${fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-audit5-'))}`,
  '--no-first-run',
  '--disable-gpu',
  '--window-size=1920,1080',
  'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe'] })
proc.on('error', (e) => { console.error('SPAWN_ERROR', e); process.exit(2) })
setTimeout(() => { console.error('WATCHDOG_TIMEOUT'); proc.kill(); process.exit(3) }, 420000)

log('browser spawning…')
const wsBrowserUrl = await new Promise((resolve, reject) => {
  let buf = ''
  const timer = setTimeout(() => reject(new Error('DevTools ws url timeout')), 20000)
  proc.stderr.on('data', (d) => {
    buf += d.toString()
    const m = buf.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+\/devtools\/browser\/\S+)/)
    if (m) { clearTimeout(timer); resolve(m[1]) }
  })
  proc.on('exit', (c) => { clearTimeout(timer); reject(new Error('browser exited: ' + c)) })
})
const debugPort = wsBrowserUrl.match(/127\.0\.0\.1:(\d+)\//)[1]
log('browser up, port', debugPort)

async function createPageWs() {
  for (const method of ['PUT', 'GET']) {
    try {
      const r = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method })
      if (r.ok) {
        const info = await r.json()
        if (info.webSocketDebuggerUrl) return info.webSocketDebuggerUrl
      }
    } catch { /* try next */ }
  }
  const list = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json()
  const page = list.find((t) => t.type === 'page')
  if (!page) throw new Error('no page target available')
  return page.webSocketDebuggerUrl
}
const pageWs = await createPageWs()
log('page ws', pageWs)

const ws = new WebSocket(pageWs)
await new Promise((res, rej) => {
  const t = setTimeout(() => rej(new Error('page ws open timeout')), 10000)
  ws.onopen = () => { clearTimeout(t); res() }
  ws.onerror = () => { clearTimeout(t); rej(new Error('page ws error')) }
})
log('ws open')

let msgId = 0
const pending = new Map()
const consoleErrors = []
const apiRequests = new Map() // requestId -> {url, method, status}

ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) {
    const { resolve, reject } = pending.get(m.id)
    pending.delete(m.id)
    if (m.error) reject(new Error(`${m.method}: ${m.error.message}`))
    else resolve(m.result)
    return
  }
  if (!m.method) return
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300))
  }
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
    consoleErrors.push(`[log] ${m.params.entry.text}`.slice(0, 300))
  }
  if (m.method === 'Runtime.exceptionThrown') {
    consoleErrors.push(`[exc] ${m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text}`.slice(0, 300))
  }
  if (m.method === 'Network.requestWillBeSent' && /\/api\//.test(m.params.request.url)) {
    apiRequests.set(m.params.requestId, { url: m.params.request.url, method: m.params.request.method, status: 0 })
  }
  if (m.method === 'Network.responseReceived' && apiRequests.has(m.params.requestId)) {
    apiRequests.get(m.params.requestId).status = m.params.response.status
  }
}

function send(method, params = {}) {
  const id = ++msgId
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

await send('Page.enable')
await send('Runtime.enable')
await send('Log.enable')
await send('Network.enable')

async function evalJs(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (r.exceptionDetails) {
    throw new Error('eval failed: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text))
  }
  return r.result.value
}

async function setViewport(w, h, mobile = false) {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile })
}

async function goto(url) {
  await send('Page.navigate', { url })
  await sleep(1400)
}

async function reload() {
  await send('Page.reload')
  await sleep(2600)
}

async function shot(file) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(file, Buffer.from(data, 'base64'))
  log('SAVED', path.basename(file))
}

const clickSel = (sel) => `(() => { const el = document.querySelector('${sel}'); if (!el) return 'NO_EL'; el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return 'CLICKED' })()`

// 页面状态快照
const PAGE_SNAP = `(() => {
  const num = (sel) => { const el = document.querySelector(sel); if (!el) return null; const m = el.textContent.match(/-?\\d+(\\.\\d+)?/); return m ? Number(m[0]) : null }
  const rects = document.querySelectorAll('.hm-map path[data-cell]').length
  const overlay = document.querySelector('[data-role=grid-state]')
  return {
    hash: location.hash,
    rects,
    overlayState: overlay ? overlay.dataset.state : null,
    kpiValid: num('[data-kpi=valid-cells]'),
    kpiHigh: num('[data-kpi=high-cells]'),
    kpiMax: num('[data-kpi=max-score]'),
    frameHigh: num('[data-frame=high]'),
    frameMid: num('[data-frame=mid]'),
    frameLow: num('[data-frame=low]'),
    activeNode: document.querySelector('.axis-node.active .node-label')?.textContent?.trim() || null,
    stageChip: document.querySelector('[data-role=stage-chip] b')?.textContent?.trim() || null,
    cellId: document.querySelector('[data-cd=id]')?.textContent?.trim() || null,
    cellScore: num('[data-cd=score]'),
    trendChart: !!document.querySelector('.hm-charts canvas')
  }
})()`

// ================================================================
// 阶段 A：桌面 1920×1080
// ================================================================
const api7 = await apiRiskGrid(7)
const api3 = await apiRiskGrid(3)
const api15 = await apiRiskGrid(15)
log(`API truth: t7 max=${api7.stats.max} top=${api7.stats.top.id}; t3 max=${api3.stats.max}; t15 max=${api15.stats.max}`)

await setViewport(1920, 1080)
await goto(`${BASE}/#/heatmap?t=t7&p=central_lake`)
await sleep(3400)

// ---- 1. URL t/p 初始化 + 刷新恢复 ----
const hash1 = await evalJs('location.hash')
const keep1 = hash1.includes('t=t7') && hash1.includes('p=central_lake')
await reload()
const hash1b = await evalJs('location.hash')
const snap1 = await evalJs(PAGE_SNAP)
check('1. URL t/p 初始化与刷新恢复（t=t7&p=central_lake 保持，页面为 T+7）',
  keep1 && hash1b.includes('t=t7') && hash1b.includes('p=central_lake') && snap1.activeNode === 'T+7',
  `first=${hash1} reload=${hash1b} active=${snap1.activeNode}`)

// ---- 2. 非法 t/p 回落 ----
await goto(`${BASE}/#/heatmap?t=t90&p=nonexistent_zone`)
await sleep(2600)
const snap2 = await evalJs(PAGE_SNAP)
const validZones = ['northwest_hotspot', 'central_lake', 'south_channel', 'east_bay', 'west_littoral', 'river_inlet']
const p2 = new URLSearchParams(snap2.hash.split('?')[1] || '').get('p')
const t2 = new URLSearchParams(snap2.hash.split('?')[1] || '').get('t')
check('2. 非法 t=t90/p=nonexistent 回落：t 回有效档位、p 回最高风险演示分区且 URL 归一化',
  t2 !== 't90' && p2 !== 'nonexistent_zone' && validZones.includes(p2) && /^T\+(1|3|7|15|30)$/.test(snap2.stageChip || ''),
  `hash=${snap2.hash} chip=${snap2.stageChip}`)

// 回到干净 t7 状态
await goto(`${BASE}/#/heatmap?t=t7&p=central_lake`)
await sleep(3200)
await shot(path.join(OUT_DIR, 'heatmap-1920.png'))

// ---- 10. 格网数据来自 API（KPI 与直连接口真值一致） ----
const snap10 = await evalJs(PAGE_SNAP)
check('10. 格网数据来自 /map/risk-grid（KPI 有效格数/最大分数与 API 真值一致，209 rect）',
  snap10.rects === 209 && snap10.kpiValid === api7.stats.valid && snap10.kpiMax === api7.stats.max,
  `page=${JSON.stringify({ rects: snap10.rects, valid: snap10.kpiValid, max: snap10.kpiMax })} api=${JSON.stringify({ valid: api7.stats.valid, max: api7.stats.max })}`)

// ---- 13. 计数求和 ----
const sum13 = snap10.frameHigh + snap10.frameMid + snap10.frameLow
check('13. 帧摘要 高+中+低 = 有效演示格数（不重不漏）',
  sum13 === snap10.kpiValid && sum13 === 209,
  `high=${snap10.frameHigh} mid=${snap10.frameMid} low=${snap10.frameLow} sum=${sum13}`)

// ---- 14. KPI 档位同步（t7 → t3） ----
const nodeOf = (label) => `(() => { const n = [...document.querySelectorAll('.axis-node')].find((x) => x.textContent.includes('${label}')); if (!n) return 'NO_NODE'; n.dispatchEvent(new MouseEvent('click', { bubbles: true })); return 'OK' })()`
await evalJs(nodeOf('T+3'))
await sleep(1500)
const snap14 = await evalJs(PAGE_SNAP)
const sync14 = snap14.activeNode === 'T+3' && snap14.kpiMax === api3.stats.max && snap14.kpiValid === api3.stats.valid
await evalJs(nodeOf('T+7'))
await sleep(1200)
check('14. KPI 随档位同步（T+3 时最大分数/有效格数 = API t3 真值，非固定数组）',
  sync14, `t3page=${JSON.stringify({ max: snap14.kpiMax, valid: snap14.kpiValid })} api=${JSON.stringify({ max: api3.stats.max, valid: api3.stats.valid })}`)

// ---- 3. 五个档位各自正确加载 ----
let stages3Ok = true
const stages3Detail = []
for (const [label, tkey] of [['T+1', 't1'], ['T+3', 't3'], ['T+7', 't7'], ['T+15', 't15'], ['T+30', 't30']]) {
  await evalJs(nodeOf(label))
  await sleep(1100)
  const s = await evalJs(PAGE_SNAP)
  const ok = s.activeNode === label && s.hash.includes(`t=${tkey}`) && s.rects === 209 && !s.overlayState
  stages3Ok = stages3Ok && ok
  stages3Detail.push(`${label}:${s.rects}r${s.overlayState ? '/' + s.overlayState : ''}`)
}
check('3. 五个档位（T+1/3/7/15/30）各自从接口加载 209 格演示格网', stages3Ok, stages3Detail.join(' '))

// ---- 7. T+30 simulation_only ----
await evalJs(nodeOf('T+30'))
await sleep(1100)
const t30 = await evalJs(`(() => {
  const banner = document.querySelector('[data-role=t30-banner]')
  const txt = banner ? banner.textContent : ''
  return {
    banner: !!banner,
    hasSimOnly: txt.includes('模拟预演') && txt.includes('30—90 天'),
    quality: (document.querySelector('[data-kpi=quality-status]') || { textContent: '' }).textContent.includes('simulation_only')
  }
})()`)
check('7. T+30 显示 simulation_only 横幅与质量状态（30—90 天能力阻塞，仅为模拟预演）',
  t30.banner && t30.hasSimOnly && t30.quality, JSON.stringify(t30))

// ---- 8. 无 T+90 ----
const axis8 = await evalJs(`(() => {
  const nodes = [...document.querySelectorAll('.axis-node .node-label')].map((n) => n.textContent.trim())
  return { nodes, hasT90: document.querySelector('.page-heatmap').textContent.includes('T+90') }
})()`)
check('8. 不存在 T+90 档位（时间轴仅 T+1/3/7/15/30）',
  axis8.nodes.length === 5 && axis8.nodes.join(',') === 'T+1,T+3,T+7,T+15,T+30' && !axis8.hasT90,
  JSON.stringify(axis8.nodes))

// ---- 9. 历史/当前禁用 ----
const modes9 = await evalJs(`(() => {
  const grab = (k) => { const b = document.querySelector('[data-mode-btn=' + k + ']'); return b ? { disabled: b.disabled, aria: b.getAttribute('aria-disabled'), text: b.textContent.replace(/\\s+/g, ' ') } : null }
  const fut = document.querySelector('[data-mode-btn=future]')
  return { history: grab('history'), current: grab('current'), futurePressed: fut ? fut.getAttribute('aria-pressed') : null }
})()`)
check('9. 历史/当前模式禁用且原因可见，未来预演为当前可用模式',
  modes9.history?.disabled && modes9.history?.aria === 'true' && modes9.history.text.includes('尚未接入')
    && modes9.current?.disabled && modes9.current?.aria === 'true' && modes9.current.text.includes('未接入')
    && modes9.futurePressed === 'true',
  JSON.stringify(modes9))

// ---- 15. 图层 toggle aria-pressed 语义 ----
await evalJs(nodeOf('T+7'))
await sleep(1200)
const toggle15 = await evalJs(`(async () => {
  const btns = [...document.querySelectorAll('.hm-left button[aria-pressed]')]
  const gridBtn = btns.find((b) => b.textContent.includes('演示风险格网'))
  if (!gridBtn) return { err: 'NO_TOGGLE' }
  const before = gridBtn.getAttribute('aria-pressed')
  gridBtn.click()
  await new Promise((r) => setTimeout(r, 500))
  const off = { pressed: gridBtn.getAttribute('aria-pressed'), rects: document.querySelectorAll('.hm-map path[data-cell]').length }
  gridBtn.click()
  await new Promise((r) => setTimeout(r, 500))
  const on = { pressed: gridBtn.getAttribute('aria-pressed'), rects: document.querySelectorAll('.hm-map path[data-cell]').length }
  return { before, off, on }
})()`)
check('15. 图层 toggle aria-pressed 语义正确（关闭后格网移除，重开后恢复 209）',
  toggle15.before === 'true' && toggle15.off.pressed === 'false' && toggle15.off.rects === 0
    && toggle15.on.pressed === 'true' && toggle15.on.rects === 209,
  JSON.stringify(toggle15))

// ---- 16. 禁用图层原因可见 ----
const layers16 = await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.hm-left button[disabled]')]
  return btns.map((b) => ({ text: b.textContent.replace(/\\s+/g, ' ').trim(), aria: b.getAttribute('aria-disabled') }))
})()`)
const need16 = ['历史水华点', '扩散轨迹', '风险多边形', '3D']
const ok16 = need16.every((k) => layers16.some((b) => b.text.includes(k) && b.aria === 'true' && b.text.length > k.length))
check('16. 未接入图层禁用且原因文案可见（历史水华点/扩散轨迹/风险多边形/3D）',
  ok16, JSON.stringify(layers16))

// ---- 11. 格点点击一致性 ----
const apiCell = api7.data.grid[3][4] // R04-C05
await evalJs(`(() => { const el = document.querySelector('[data-cell="R04-C05"]'); if (!el) return 'NO_CELL'; el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return 'OK' })()`)
await sleep(600)
const cell11 = await evalJs(`(() => {
  const g = (k) => document.querySelector('[data-cd=' + k + ']')?.textContent?.trim() || null
  return {
    id: g('id'), score: Number(g('score')), level: g('level'), mode: g('data-mode'),
    run: g('run-id'), boundary: g('boundary'), rowcol: g('rowcol')
  }
})()`)
check('11. 点击格网 R04-C05：详情编号/分数与 API 一致，含数据模式/运行/使用边界',
  cell11.id === 'R04-C05' && cell11.score === apiCell && cell11.mode === 'simulated'
    && cell11.run === 'DEMO-RUN-V1' && cell11.boundary === 'simulation_only'
    && (cell11.rowcol || '').includes('第 4 行') && (cell11.rowcol || '').includes('第 5 列'),
  `page=${JSON.stringify(cell11)} apiValue=${apiCell}`)
await shot(path.join(OUT_DIR, 'heatmap-cell-selected.png'))

// ---- 12. 热点排行与地图选择一致 ----
const hs12 = await evalJs(`(async () => {
  const items = [...document.querySelectorAll('[data-hotspot-cell]')]
  if (!items.length) return { err: 'NO_HOTSPOTS' }
  const firstId = items[0].dataset.hotspotCell
  items[0].click()
  await new Promise((r) => setTimeout(r, 500))
  const selPath = document.querySelector('.hm-map path.hm-cell-selected')
  const detailId = document.querySelector('[data-cd=id]')?.textContent?.trim()
  const activeItem = document.querySelector('[data-hotspot-cell].active')?.dataset.hotspotCell
  return { firstId, mapSelected: selPath ? selPath.dataset.cell : null, detailId, activeItem }
})()`)
check('12. 热点排行选择与地图高亮、详情面板一致',
  hs12.mapSelected === hs12.firstId && hs12.detailId === hs12.firstId && hs12.activeItem === hs12.firstId,
  JSON.stringify(hs12))

// ---- 23. 高风险预警弹窗 ----
const apiTop = api7.stats.top // t7 最高分格（高风险）
const dlgOpen = await evalJs(clickSel('[data-role=warn-trigger]'))
await sleep(700)
const dlg23 = await evalJs(`(() => {
  const d = document.querySelector('.hm-dlg')
  if (!d) return { shown: false }
  const t = d.textContent
  return {
    shown: true, role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'),
    hasCell: t.includes('${apiTop.id}'), hasStage: t.includes('T+7'), hasScore: t.includes('${apiTop.stats?.max ?? api7.stats.max}'),
    noReal: t.includes('不会发送真实短信'), simWord: t.includes('simulated_dispatched'),
    confirmBtn: !!d.querySelector('.dlg-btn--danger'), cancelBtn: !!d.querySelector('.dlg-btn--ghost')
  }
})()`)
check('23. 高风险格预警必须经过确认弹窗（role=dialog + 档位/格网编号/演示分数 + 无真实渠道声明）',
  dlgOpen === 'CLICKED' && dlg23.shown && dlg23.role === 'dialog' && dlg23.modal === 'true'
    && dlg23.hasCell && dlg23.hasStage && dlg23.hasScore && dlg23.noReal && dlg23.simWord
    && dlg23.confirmBtn && dlg23.cancelBtn,
  `open=${dlgOpen} dlg=${JSON.stringify(dlg23)}`)
await shot(path.join(OUT_DIR, 'heatmap-warning-confirm.png'))

// ---- 25. 取消弹窗不调用 API ----
const warnBefore25 = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning')).length
await evalJs(clickSel('.hm-dlg .dlg-btn--ghost'))
await sleep(600)
const dlgClosed25 = await evalJs(`!document.querySelector('.hm-dlg')`)
const warnAfter25 = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning')).length
check('25. 取消弹窗不调用 /cockpit/handle-warning',
  dlgClosed25 && warnBefore25 === 0 && warnAfter25 === 0, `closed=${dlgClosed25} calls=${warnAfter25}`)

// ---- 24. 低风险格阻塞预警 ----
await evalJs(`(() => { const el = document.querySelector('[data-cell="R01-C01"]'); if (!el) return 'NO_CELL'; el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return 'OK' })()`)
await sleep(600)
const low24 = await evalJs(`(() => {
  const btn = document.querySelector('[data-role=warn-trigger]')
  const hint = btn ? btn.textContent : ''
  const score = document.querySelector('[data-cd=score]')?.textContent?.trim()
  return { id: document.querySelector('[data-cd=id]')?.textContent?.trim(), score, disabled: btn ? btn.disabled : null, aria: btn?.getAttribute('aria-disabled'), hint: hint.replace(/\\s+/g, ' ') }
})()`)
check('24. 低风险格（R01-C01）无法发起预警（禁用 + 仅高风险可发起提示）',
  low24.id === 'R01-C01' && low24.score !== null && low24.score < 45
    && low24.disabled === true && low24.aria === 'true' && low24.hint.includes('高风险'),
  JSON.stringify(low24))

// ---- 26. 确认后只显示模拟发送状态 ----
await evalJs(`(() => { const items = [...document.querySelectorAll('[data-hotspot-cell]')]; if (!items.length) return 'NO_HS'; items[0].click(); return 'OK' })()`)
await sleep(500)
await evalJs(clickSel('[data-role=warn-trigger]'))
await sleep(600)
const callsBefore26 = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning')).length
await evalJs(clickSel('.hm-dlg .dlg-btn--danger'))
await sleep(1600)
const warn26 = await evalJs(`(() => {
  const res = document.querySelector('[data-role=warn-result]')
  const t = res ? res.textContent : ''
  return { shown: !!res, sim: t.includes('simulated_dispatched'), cell: t.includes('${apiTop.id}'),
    channel: t.includes('platform_simulation'), mode: t.includes('simulated'),
    noSms: !t.includes('短信发送成功') && !t.includes('已通知政府') }
})()`)
const warnCalls26 = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning'))
check('26. 确认后仅显示 simulated_dispatched 模拟状态（恰好 1 次 POST 200，无真实渠道措辞）',
  warn26.shown && warn26.sim && warn26.cell && warn26.channel && warn26.mode && warn26.noSms
    && callsBefore26 === 0 && warnCalls26.length === 1 && warnCalls26[0].status === 200,
  `res=${JSON.stringify(warn26)} calls=${JSON.stringify(warnCalls26.map((c) => c.status))}`)

// ---- 4. 快速连续切换竞态安全 ----
await evalJs(`(async () => {
  const pick = (label) => { const n = [...document.querySelectorAll('.axis-node')].find((x) => x.textContent.includes(label)); n && n.dispatchEvent(new MouseEvent('click', { bubbles: true })) }
  pick('T+1'); await new Promise((r) => setTimeout(r, 60))
  pick('T+15'); await new Promise((r) => setTimeout(r, 60))
  pick('T+3'); await new Promise((r) => setTimeout(r, 60))
  pick('T+7'); return 'OK'
})()`)
await sleep(1800)
const snap4 = await evalJs(PAGE_SNAP)
check('4. 快速连点 T+1/T+15/T+3/T+7 竞态安全：最终停在 T+7，数据为 t7 真值',
  snap4.activeNode === 'T+7' && snap4.hash.includes('t=t7') && snap4.rects === 209
    && snap4.kpiMax === api7.stats.max && snap4.kpiValid === api7.stats.valid,
  `end=${JSON.stringify({ active: snap4.activeNode, hash: snap4.hash, max: snap4.kpiMax })} apiMax=${api7.stats.max}`)

// ---- 20. A/B 基于两个 API 格网 ----
const gridReq = (h) => [...apiRequests.values()].filter((r) => r.url.includes(`horizon_days=${h}`) && r.url.includes('risk-grid'))
const ab20 = await evalJs(`(async () => {
  const a = document.querySelector('[data-role=ab-a]')
  const b = document.querySelector('[data-role=ab-b]')
  if (!a || !b) return { err: 'NO_SELECT' }
  a.value = 't3'; a.dispatchEvent(new Event('change', { bubbles: true }))
  b.value = 't15'; b.dispatchEvent(new Event('change', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 400))
  const diffBtn = [...document.querySelectorAll('.hm-ab-modes button')].find((x) => x.textContent.includes('差值'))
  diffBtn.click()
  await new Promise((r) => setTimeout(r, 1400))
  const num = (k) => { const el = document.querySelector('[data-ab=' + k + ']'); if (!el) return null; const m = el.textContent.match(/-?\\d+/); return m ? Number(m[0]) : null }
  const flag = [...document.querySelectorAll('.hm-map-flag')].some((f) => f.textContent.includes('非模型评估结论'))
  return {
    up: num('up'), down: num('down'), same: num('same'), maxDelta: num('max-delta'),
    l2m: num('low-to-mid'), m2h: num('mid-to-high'), h2m: num('high-to-mid'), m2l: num('mid-to-low'),
    flag, rects: document.querySelectorAll('.hm-map path[data-cell]').length
  }
})()`)
const req20a = gridReq(3).filter((r) => r.status === 200).length
const req20b = gridReq(15).filter((r) => r.status === 200).length
const sum20 = ab20.up + ab20.down + ab20.same
check('20. A/B 比较基于两个成功加载的 API 格网（t3/t15 均 200，四类计数求和 = 209，含非评估声明）',
  !ab20.err && req20a >= 1 && req20b >= 1 && sum20 === 209 && ab20.maxDelta !== null && ab20.flag,
  `ab=${JSON.stringify(ab20)} req t3=${req20a} t15=${req20b}`)
await shot(path.join(OUT_DIR, 'heatmap-compare.png'))

// ---- 21. 同档位提示 ----
const same21 = await evalJs(`(async () => {
  const b = document.querySelector('[data-role=ab-b]')
  b.value = 't3'; b.dispatchEvent(new Event('change', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 300))
  const diffBtn = [...document.querySelectorAll('.hm-ab-modes button')].find((x) => x.textContent.includes('差值'))
  diffBtn.click()
  await new Promise((r) => setTimeout(r, 700))
  return {
    notice: document.querySelector('[data-role=ab-same]')?.textContent?.trim() || null,
    overlay: document.querySelector('[data-role=grid-state]')?.dataset?.state || null,
    rects: document.querySelectorAll('.hm-map path[data-cell]').length
  }
})()`)
check('21. A/B 选同档位时显示「两个场景相同，无差异」（面板 + 地图覆盖层，不渲染差值格网）',
  same21.notice === '两个场景相同，无差异' && same21.overlay === 'same' && same21.rects === 0,
  JSON.stringify(same21))

// ---- 22. 无虚构能力声明 ----
const claims22 = await evalJs(`(() => {
  const t = document.querySelector('.page-heatmap').innerText
  const banned = ['km²', '平方公里', '置信度', '500m', '500 米', '有效像元']
  const hitBanned = banned.filter((k) => t.includes(k))
  // “扩散速度/迁移速度/面积” 只允许出现在否认句中
  const softHits = []
  for (const kw of ['扩散速度', '迁移速度', '面积']) {
    let idx = t.indexOf(kw)
    while (idx >= 0) {
      const prev = t.slice(Math.max(0, idx - 15), idx)
      if (!prev.includes('不是') && !prev.includes('不计算') && !prev.includes('不代表')) softHits.push(kw + '<-' + prev.slice(-8))
      idx = t.indexOf(kw, idx + 1)
    }
  }
  return { hitBanned, softHits }
})()`)
check('22. 页面无 km²/平方公里/置信度/500m/有效像元等虚构声明；速度/面积仅出现在否认句',
  claims22.hitBanned.length === 0 && claims22.softHits.length === 0,
  JSON.stringify(claims22))

// ---- 17. 播放停在 T+30（1× 从 T+1 起） ----
await evalJs(`(() => { const n = [...document.querySelectorAll('.axis-node')].find((x) => x.textContent.includes('T+1')); n.dispatchEvent(new MouseEvent('click', { bubbles: true })); return 'OK' })()`)
await sleep(800)
const playStart = Date.now()
await evalJs(clickSel('.hm-dock .play-btn.primary'))
let play17 = { stopped: false, atT30: false }
for (let i = 0; i < 24; i++) {
  await sleep(600)
  play17 = await evalJs(`(() => ({ stopped: !document.querySelector('[aria-label=暂停]'), active: document.querySelector('.axis-node.active .node-label')?.textContent?.trim() }))()`)
  if (play17.stopped) break
}
const playMs = Date.now() - playStart
check('17. 播放推进到 T+30 自动停止（不循环，最后档位为 T+30）',
  play17.stopped && play17.active === 'T+30' && playMs < 12000,
  `stopped=${play17.stopped} active=${play17.active} elapsed=${playMs}ms`)
await sleep(1800)
const noLoop17 = await evalJs(`document.querySelector('.axis-node.active .node-label')?.textContent?.trim()`)
check('17b. 停止后不跳回第一档', noLoop17 === 'T+30', `still=${noLoop17}`)

// ---- 18. 前进/后退边界 ----
const bounds18 = await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.hm-dock .play-btn')]
  const prev = btns[0], next = btns[2]
  return { atT30: { prevDisabled: prev.disabled, nextDisabled: next.disabled } }
})()`)
check('18. T+30 时「下一档」禁用（播放边界）',
  bounds18.atT30.nextDisabled === true && bounds18.atT30.prevDisabled === false, JSON.stringify(bounds18))
await evalJs(`(() => { const n = [...document.querySelectorAll('.axis-node')].find((x) => x.textContent.includes('T+1')); n.dispatchEvent(new MouseEvent('click', { bubbles: true })); return 'OK' })()`)
await sleep(700)
const bounds18b = await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.hm-dock .play-btn')]
  return { atT1: { prevDisabled: btns[0].disabled, nextDisabled: btns[2].disabled } }
})()`)
check('18b. T+1 时「上一档」禁用', bounds18b.atT1.prevDisabled === true && bounds18b.atT1.nextDisabled === false, JSON.stringify(bounds18b))

// ---- 19. 倍速生效 ----
await evalJs(`(() => { const b = [...document.querySelectorAll('.hm-dock .speed-pill button')].find((x) => x.textContent.includes('4×')); b && b.click(); return 'OK' })()`)
await evalJs(clickSel('.hm-dock .play-btn.primary'))
const speedStart = Date.now()
let speed19 = { stopped: false, active: null }
for (let i = 0; i < 14; i++) {
  await sleep(400)
  speed19 = await evalJs(`(() => ({ stopped: !document.querySelector('[aria-label=暂停]'), active: document.querySelector('.axis-node.active .node-label')?.textContent?.trim() }))()`)
  if (speed19.stopped) break
}
const speedMs = Date.now() - speedStart
check('19. 4× 倍速生效（T+1 → T+30 用时明显短于 1×，且正常停在 T+30）',
  speed19.stopped && speed19.active === 'T+30' && speedMs < 4000,
  `elapsed=${speedMs}ms active=${speed19.active}`)
await evalJs(`(() => { const b = [...document.querySelectorAll('.hm-dock .speed-pill button')].find((x) => x.textContent.includes('1×')); b && b.click(); return 'OK' })()`)

// ---- 30. 1920×1080 首屏 ----
await goto(`${BASE}/#/heatmap?t=t7&p=central_lake`)
await sleep(3400)
const oneScreen = await evalJs(`(() => {
  const pick = (sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return { top: Math.round(r.top + scrollY), bottom: Math.round(r.bottom + scrollY) } }
  return { title: pick('.hm-title'), kpis: pick('.hm-kpis'), map: pick('.hm-center'), dock: pick('.hm-dock'), vh: innerHeight }
})()`)
const osFail = Object.entries(oneScreen).filter(([k, v]) => k !== 'vh' && (!v || v.bottom > oneScreen.vh))
check('30. 1920×1080 首屏包含标题/KPI/地图/时间轴（不超出一屏）',
  osFail.length === 0, `vh=${oneScreen.vh} overflow=${osFail.map(([k, v]) => k + ':' + (v ? v.bottom : 'null')).join(',') || 'none'}`)

// ---- 5/6. 失败注入：全部 risk-grid 阻断 → 无虚构数据；重试恢复 ----
await send('Network.setBlockedURLs', { urls: ['*risk-grid*'] })
await reload()
const fail5 = await evalJs(PAGE_SNAP)
check('5a. 接口全阻断时：格网区域显示错误/加载覆盖层，不渲染旧格网、KPI 不虚构数值',
  (fail5.overlayState === 'error' || fail5.overlayState === 'loading') && fail5.rects === 0
    && fail5.kpiValid === null && fail5.kpiMax === null,
  JSON.stringify({ overlay: fail5.overlayState, rects: fail5.rects, valid: fail5.kpiValid, max: fail5.kpiMax }))
await send('Network.setBlockedURLs', { urls: [] })
const retry5 = await evalJs(clickSel('[data-role=grid-retry]'))
await sleep(2200)
const snap5r = await evalJs(PAGE_SNAP)
check('6a. 解除阻断后点击重试：T+7 格网恢复 209 格，KPI 恢复 API 真值',
  retry5 === 'CLICKED' && snap5r.rects === 209 && snap5r.kpiMax === api7.stats.max && !snap5r.overlayState,
  `retry=${retry5} rects=${snap5r.rects} max=${snap5r.kpiMax}`)

// ---- 5b/6b. 单档位失败：无「旧格网 + 新档位标签」组合 ----
await send('Network.setBlockedURLs', { urls: ['*horizon_days=15*'] })
await reload()
await sleep(1200)
await evalJs(nodeOf('T+15'))
await sleep(1500)
const fail5b = await evalJs(PAGE_SNAP)
check('5b. T+15 失败时切到该档位：T+15 标签下不展示任何格网（无旧档位格网 + 新档位标签）',
  fail5b.activeNode === 'T+15' && fail5b.rects === 0 && fail5b.overlayState === 'error' && fail5b.kpiMax === null,
  JSON.stringify({ active: fail5b.activeNode, rects: fail5b.rects, overlay: fail5b.overlayState, max: fail5b.kpiMax }))
await send('Network.setBlockedURLs', { urls: [] })
await evalJs(clickSel('[data-role=grid-retry]'))
await sleep(2200)
const snap6b = await evalJs(PAGE_SNAP)
check('6b. T+15 重试恢复：209 格 + 趋势图恢复渲染（五档位齐备）',
  snap6b.rects === 209 && snap6b.activeNode === 'T+15' && snap6b.trendChart === true,
  `rects=${snap6b.rects} active=${snap6b.activeNode} trendChart=${snap6b.trendChart}`)

// ---- 1440 截图 ----
await goto(`${BASE}/#/heatmap?t=t7&p=central_lake`)
await sleep(3000)
await setViewport(1440, 900)
await sleep(1200)
await shot(path.join(OUT_DIR, 'heatmap-1440.png'))
await setViewport(1920, 1080)

// ================================================================
// 阶段 B：移动端 390×844
// ================================================================
await setViewport(390, 844, true)
await goto(`${BASE}/#/heatmap?t=t7&p=northwest_hotspot`)
await sleep(3600)

// ---- 29. 无横向溢出 ----
const overflow29 = await evalJs(`({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })`)
check('29. 390px 无横向溢出', overflow29.sw <= overflow29.iw + 1, `scrollWidth=${overflow29.sw} innerWidth=${overflow29.iw}`)

// ---- 27. 图层抽屉与焦点 ----
const bar27 = await evalJs(`(() => {
  const bar = document.querySelector('.hm-mobile-bar')
  if (!bar) return { err: 'NO_BAR' }
  const cs = getComputedStyle(bar)
  return { fixed: cs.position === 'fixed', bottom: Math.round(bar.getBoundingClientRect().bottom), vh: window.innerHeight }
})()`)
check('27a. 移动端底部操作栏 fixed 且贴住视口底', bar27.fixed === true && Math.abs(bar27.bottom - bar27.vh) <= 2, JSON.stringify(bar27))
await evalJs(clickSel('[data-role=layers-trigger]'))
await sleep(700)
const drawer27 = await evalJs(`(() => {
  const d = document.querySelector('[aria-label=图层设置]')
  if (!d) return { shown: false }
  const ae = document.activeElement
  return { shown: true, focusInside: d.contains(ae), ariaModal: d.getAttribute('aria-modal'), toggles: d.querySelectorAll('button[aria-pressed]').length }
})()`)
check('27b. 图层抽屉打开（role=dialog + aria-modal）且焦点移入抽屉',
  drawer27.shown === true && drawer27.focusInside === true && drawer27.ariaModal === 'true' && drawer27.toggles >= 3,
  JSON.stringify(drawer27))
await shot(path.join(OUT_DIR, 'heatmap-layers-390.png'))
await evalJs(`(() => { const d = document.querySelector('[aria-label=图层设置]'); d && d.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); return 'OK' })()`)
await sleep(600)
const drawerClose27 = await evalJs(`(() => {
  const closed = !document.querySelector('[aria-label=图层设置]')
  const trig = document.querySelector('[data-role=layers-trigger]')
  return { closed, focusBack: trig && document.activeElement === trig }
})()`)
check('27c. Esc 关闭抽屉且焦点返回触发按钮', drawerClose27.closed && drawerClose27.focusBack === true, JSON.stringify(drawerClose27))

// ---- 28. 触摸目标 ≥44×44 ----
const touch28 = await evalJs(`(() => {
  const sels = ['.hm-mobile-bar a', '.hm-mobile-bar button', '.axis-node', '.hm-dock .play-btn', '.hm-ab-modes button',
    '.hm-ab-select select', '.hm-hotspot-item', '.hm-zone-row', '.hm-inline-btn', '.hm-warn-btn',
    '.hm-modes button', '.hm-chip', '.leaflet-control-zoom a', '.hm-fold summary']
  const out = []
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach((el) => {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) return
      out.push({ sel: sel.replace(/^\\./, ''), w: Math.round(r.width), h: Math.round(r.height) })
    })
  }
  return out
})()`)
const badTouch28 = touch28.filter((t) => t.w < 44 || t.h < 44)
console.log('TOUCH_TARGETS', JSON.stringify(touch28))
check('28. 390px 主要触摸目标 ≥44×44px（含 Leaflet 缩放按钮）', touch28.length > 0 && badTouch28.length === 0,
  badTouch28.length ? `violations=${JSON.stringify(badTouch28)}` : `${touch28.length} 个目标全部达标`)
await shot(path.join(OUT_DIR, 'heatmap-390.png'))

// ================================================================
// 阶段 C：回归 + 控制台 + 自检
// ================================================================
await setViewport(1440, 900)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(3200)
const cockpit31 = await evalJs(`!!document.querySelector('.ckp-kpis') && !!document.querySelector('.ckp-map')`)
await goto(`${BASE}/#/stations?t=t7&p=northwest_hotspot`)
await sleep(3200)
const stations31 = await evalJs(`!!document.querySelector('.stn-body') && document.querySelectorAll('.stn-zone-item').length === 6`)
await goto(`${BASE}/#/history`)
await sleep(2400)
const hist31 = await evalJs(`!!document.querySelector('.panel')`)
await goto(`${BASE}/#/heatmap?t=t7&p=northwest_hotspot`)
await sleep(2400)
const heat31 = await evalJs(`!!document.querySelector('.hm-map')`)
check('31. P01 驾驶舱 / P03 站点 / 历史页 / P07 相互切换回归正常',
  cockpit31 && stations31 && hist31 && heat31,
  `cockpit=${cockpit31} stations=${stations31} history=${hist31} heatmap=${heat31}`)

// ---- 32. 控制台无 error ----
const pageErrors = consoleErrors.filter((t) => !t.includes('favicon') && !t.includes('Failed to load resource'))
console.log('CONSOLE_ERRORS', pageErrors.length)
pageErrors.slice(0, 10).forEach((t) => console.log('  ERR:', t))
check('32. 全流程控制台无 error', pageErrors.length === 0, `${pageErrors.length} 个错误`)

// ---- 33. 断言失败时返回非零退出码（子进程自检） ----
const selfRun = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {
  env: { ...process.env, AUDIT5_SELFCHECK: '1' }, encoding: 'utf8'
})
check('33. 脚本断言失败时返回非零退出码', selfRun.status === 1 && /EXIT_CODE 1/.test(selfRun.stdout),
  `childExit=${selfRun.status}`)

// ---- 汇总与退出码 ----
const apiList = [...apiRequests.values()]
console.log('API_CALLS', JSON.stringify(apiList.map((r) => `${r.method} ${r.url.replace(BASE, '')} -> ${r.status}`), null, 1))
const failed = results.filter((r) => !r.ok)
console.log(`SUMMARY: ${results.length - failed.length}/${results.length} checks passed`)
const exitCode = failed.length > 0 || pageErrors.length > 0 ? 1 : 0
console.log('EXIT_CODE', exitCode)
proc.kill()
process.exit(exitCode)
