// 零依赖 CDP 复验脚本（Node >= 22 内置 WebSocket/fetch）：无头 Edge 直连页面级 DevTools。
// 覆盖：默认点位首次点击、恢复默认筛选复位底图、跨页返回 URL 同步、390 底部操作栏，
// 并输出 cockpit-1920 / cockpit-1440 / cockpit-390 三张截图到本目录。
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.env.VERIFY_BASE || 'http://localhost:4173'
const OUT_DIR = fileURLToPath(new URL('./audit3-screenshots/', import.meta.url))

const log = (...a) => console.log(new Date().toISOString().slice(17, 23), ...a)

const proc = spawn(EDGE, [
  '--headless',
  '--remote-debugging-port=0',
  `--user-data-dir=${fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-audit-'))}`,
  '--no-first-run',
  '--disable-gpu',
  '--window-size=1920,1080',
  'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe'] })
proc.on('error', (e) => { console.error('SPAWN_ERROR', e); process.exit(2) })
setTimeout(() => { console.error('WATCHDOG_TIMEOUT'); proc.kill(); process.exit(3) }, 240000)

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

// 通过 HTTP 创建页面级目标，直接连它的 WebSocket（无需 flatten 会话）
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
  // 兜底：复用已有页面目标
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
  await sleep(1200)
}

async function shot(file) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(file, Buffer.from(data, 'base64'))
  log('SAVED', path.basename(file))
}

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'} | ${name}${detail ? ' | ' + detail : ''}`)
}

const CLICK_ACTIVE_MARKER = `(() => {
  const el = document.querySelector('.lake-marker.is-active')
  if (!el) return 'NO_MARKER'
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
  return 'CLICKED'
})()`

// ---------- 复验 1：默认 NW-01 首次点击只选中，时间窗内第二次点击才下钻 ----------
await setViewport(1920, 1080)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(3500)
const hash0 = await evalJs('location.hash')
check('1.0 初始 URL 为驾驶舱 t7/NW-01', hash0.includes('/cockpit') && hash0.includes('t=t7') && hash0.includes('p=northwest_hotspot'), hash0)
const c1 = await evalJs(CLICK_ACTIVE_MARKER)
await sleep(800)
const hash1 = await evalJs('location.hash')
check('1.1 默认点位首次点击不跳转', c1 === 'CLICKED' && hash1.includes('/cockpit'), `click=${c1} hash=${hash1}`)
const c2 = await evalJs(CLICK_ACTIVE_MARKER)
await sleep(1000)
const hash2 = await evalJs('location.hash')
check('1.2 时间窗内第二次点击下钻站点页', c2 === 'CLICKED' && hash2.includes('/stations') && hash2.includes('t=t7') && hash2.includes('p=northwest_hotspot'), `click=${c2} hash=${hash2}`)

// ---------- 复验 2：切地形图层后“恢复默认筛选”复位卫星底图 ----------
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(3000)
await evalJs(`(() => { const b = document.querySelectorAll('.layer-switcher button')[1]; if (!b) return 'NO_BTN'; b.click(); return 'OK' })()`)
await sleep(800)
const topoActive = await evalJs(`document.querySelector('.layer-switcher button.active')?.textContent.trim() || 'NONE'`)
check('2.1 已切换到地形地图', topoActive === '地形地图', topoActive)
await evalJs(`(() => { const b = document.querySelector('.ckp-reset'); if (!b) return 'NO_BTN'; b.click(); return 'OK' })()`)
await sleep(1000)
const satActive = await evalJs(`document.querySelector('.layer-switcher button.active')?.textContent.trim() || 'NONE'`)
const hashB = await evalJs('location.hash')
const topoGone = await evalJs(`![...document.querySelectorAll('.leaflet-layer img')].some(i => (i.src || '').includes('World_Topo_Map'))`)
check('2.2 恢复默认筛选复位卫星底图', satActive === '卫星影像' && topoGone, `active=${satActive} topoTilesGone=${topoGone}`)
check('2.3 筛选复位回 t7/NW-01', hashB.includes('t=t7') && hashB.includes('p=northwest_hotspot'), hashB)

// ---------- 复验 3：跨页返回后档位切换 URL 同步 ----------
await evalJs(`[...document.querySelectorAll('.axis-node')].find(n => n.querySelector('.node-label')?.textContent.trim() === 'T+3')?.click()`)
await sleep(800)
const hashC1 = await evalJs('location.hash')
check('3.1 驾驶舱切 T+3 → URL 同步', hashC1.includes('/cockpit') && hashC1.includes('t=t3'), hashC1)
await evalJs(`[...document.querySelectorAll('a')].find(a => a.textContent.includes('查看站点详情'))?.click()`)
await sleep(1000)
const hashC2 = await evalJs('location.hash')
check('3.2 站点页携带 t=t3', hashC2.includes('/stations') && hashC2.includes('t=t3'), hashC2)
await evalJs('history.back()')
await sleep(1400)
const backHash = await evalJs('location.hash')
await evalJs(`[...document.querySelectorAll('.axis-node')].find(n => n.querySelector('.node-label')?.textContent.trim() === 'T+1')?.click()`)
await sleep(800)
const hashC3 = await evalJs('location.hash')
check('3.3 站点页返回驾驶舱后切 T+1 → URL 同步（原缺陷）', backHash.includes('/cockpit') && hashC3.includes('/cockpit') && hashC3.includes('t=t1'), `back=${backHash} now=${hashC3}`)

// ---------- 轻量回归：heatmap / history 打开渲染正常 ----------
await goto(`${BASE}/#/heatmap`)
await sleep(1800)
const heatOk = await evalJs(`!!document.querySelector('.panel')`)
await goto(`${BASE}/#/history`)
await sleep(1800)
const histOk = await evalJs(`!!document.querySelector('.panel')`)
check('3.4 heatmap / history 页面渲染正常（回归）', heatOk && histOk, `heatmap=${heatOk} history=${histOk}`)

// ---------- 复验 4 + 截图：390 移动端 ----------
await setViewport(390, 844, true)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(4000)
const mob = await evalJs(`(() => {
  const nav = document.querySelector('.ckp-entries')
  if (!nav) return { err: 'NO_NAV' }
  const r = nav.getBoundingClientRect()
  const mapEl = document.querySelector('.ckp-map')
  const kpiEl = document.querySelector('.ckp-kpis')
  return {
    parentIsBody: nav.parentElement === document.body,
    fixed: getComputedStyle(nav).position === 'fixed',
    top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight,
    mapBeforeKpis: !!mapEl && !!kpiEl && mapEl.getBoundingClientRect().top < kpiEl.getBoundingClientRect().top
  }
})()`)
check('4.1 底部操作栏 Teleport 到 body', mob.parentIsBody === true, JSON.stringify(mob))
check('4.2 底部操作栏 fixed 且贴住视口底（首屏可见）', mob.fixed === true && Math.abs(mob.bottom - mob.vh) <= 2, `bottom=${mob.bottom} vh=${mob.vh}`)
check('4.3 移动端顺序：地图在 KPI 之前', mob.mapBeforeKpis === true)

// ---------- 复验 4.4：移动端触摸目标 ≥44×44px ----------
const touchTargets = await evalJs(`(() => {
  const sels = ['.ckp-reset', '.ckp-layer-toggles button', '.layer-switcher button', '.tool-chip', '.ckp-detail-btn', '.ckp-rank-btn', '.play-btn', '.speed-pill button']
  const out = []
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach((el) => {
      const r = el.getBoundingClientRect()
      out.push({ sel: sel.replace(/^\\./, ''), label: (el.textContent || '').trim().slice(0, 6) || '(icon)', w: Math.round(r.width), h: Math.round(r.height) })
    })
  }
  return out
})()`)
const badTouch = touchTargets.filter((t) => t.w < 44 || t.h < 44)
console.log('TOUCH_TARGETS', JSON.stringify(touchTargets))
check('4.4 移动端触摸目标 ≥44×44px', touchTargets.length > 0 && badTouch.length === 0,
  badTouch.length ? `violations=${JSON.stringify(badTouch)}` : (touchTargets.length ? `${touchTargets.length} 个目标全部达标` : 'NO_TARGETS'))
await shot(path.join(OUT_DIR, 'cockpit-390.png'))

// ---------- 截图：1920 一屏总览 ----------
await setViewport(1920, 1080, false)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(6000)
const oneScreen = await evalJs(`(() => {
  const pick = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { top: Math.round(r.top + scrollY), bottom: Math.round(r.bottom + scrollY) }
  }
  return {
    title: pick('.ckp-title'), kpis: pick('.ckp-kpis'), map: pick('.ckp-map'),
    timeline: pick('.ckp-timeline'), entries: pick('.ckp-entries'), vh: innerHeight
  }
})()`)
check(
  '5.1 1920 一屏：标题/KPI/地图/时间轴/入口全部在 1080 内',
  oneScreen.title && oneScreen.kpis && oneScreen.map && oneScreen.timeline && oneScreen.entries
    && oneScreen.entries.bottom <= 1080 && oneScreen.timeline.bottom <= 1080 && oneScreen.map.top <= 220,
  JSON.stringify(oneScreen)
)
await shot(path.join(OUT_DIR, 'cockpit-1920.png'))

// ---------- 截图：1440 ----------
await setViewport(1440, 900, false)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(5000)
await shot(path.join(OUT_DIR, 'cockpit-1440.png'))

// ---------- 控制台错误汇总 ----------
const pageErrors = consoleErrors.filter((t) => !t.includes('favicon') && !t.includes('Failed to load resource'))
console.log('CONSOLE_ERRORS', pageErrors.length)
pageErrors.slice(0, 10).forEach((t) => console.log('  ERR:', t))

const failed = results.filter((r) => !r.ok)
console.log(`SUMMARY: ${results.length - failed.length}/${results.length} checks passed`)
const exitCode = failed.length > 0 || pageErrors.length > 0 ? 1 : 0
console.log('EXIT_CODE', exitCode)
proc.kill()
process.exit(exitCode)
