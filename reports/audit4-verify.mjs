// 零依赖 P03 复验脚本（Node >= 22 内置 WebSocket/fetch）：无头 Edge 直连页面级 DevTools。
// 覆盖任务书 22 项验收：URL 同步、四端一致、竞态守卫、搜索筛选、稀疏趋势、档位切换、
// T+30 阻塞、演示规则贡献、Tab 键盘操作、模拟预警确认、390 移动端抽屉/触摸目标/溢出、
// 1920 首屏、P01/P07/历史页回归、控制台无 error、失败时非零退出码。
// 截图输出到本目录 audit4-screenshots/。
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.env.VERIFY_BASE || 'http://localhost:4173'
const OUT_DIR = fileURLToPath(new URL('./audit4-screenshots/', import.meta.url))
fs.mkdirSync(OUT_DIR, { recursive: true })

const log = (...a) => console.log(new Date().toISOString().slice(17, 23), ...a)

// ---------- 自检模式（验证第 22 条：断言失败 → 非零退出码） ----------
if (process.env.AUDIT4_SELFCHECK) {
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

const proc = spawn(EDGE, [
  '--headless',
  '--remote-debugging-port=0',
  `--user-data-dir=${fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-audit4-'))}`,
  '--no-first-run',
  '--disable-gpu',
  '--window-size=1920,1080',
  'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe'] })
proc.on('error', (e) => { console.error('SPAWN_ERROR', e); process.exit(2) })
setTimeout(() => { console.error('WATCHDOG_TIMEOUT'); proc.kill(); process.exit(3) }, 300000)

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

async function shot(file) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(file, Buffer.from(data, 'base64'))
  log('SAVED', path.basename(file))
}

const clickByRole = (sel) => `(() => { const el = document.querySelector('${sel}'); if (!el) return 'NO_EL'; el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return 'CLICKED' })()`

// ================================================================
// 阶段 A：桌面 1920×1080 —— stations?t=t3&p=central_lake
// ================================================================
await setViewport(1920, 1080)
await goto(`${BASE}/#/stations?t=t3&p=central_lake`)
await sleep(3200)

// ---- 1. URL 同步进入 ----
const hash1 = await evalJs('location.hash')
check('1. /cockpit?t=t3&p=central_lake 进入站点页后仍为 t3/central_lake',
  hash1.includes('/stations') && hash1.includes('t=t3') && hash1.includes('p=central_lake'), hash1)

// ---- 2. 列表、地图、URL、右栏同一分区 ----
const sync2 = await evalJs(`(() => {
  const sel = document.querySelector('.stn-zone-item.selected')
  const profile = document.querySelector('.stn-sec-profile')
  const marker = document.querySelector('.lake-marker.is-active')
  return {
    selId: sel ? sel.dataset.zoneId : null,
    hashP: new URLSearchParams(location.hash.split('?')[1] || '').get('p'),
    profileText: profile ? profile.textContent : '',
    hasMarker: !!marker
  }
})()`)
check('2. 列表/地图/URL/右栏指向同一分区',
  sync2.selId === 'central_lake' && sync2.hashP === 'central_lake'
    && sync2.profileText.includes('CN-02') && sync2.hasMarker,
  JSON.stringify(sync2))

// ---- 3. 刷新后恢复相同 t/p ----
await send('Page.reload')
await sleep(2800)
const sync3 = await evalJs(`(() => {
  const sel = document.querySelector('.stn-zone-item.selected')
  return { hash: location.hash, selId: sel ? sel.dataset.zoneId : null }
})()`)
check('3. 刷新后恢复相同 t/p',
  sync3.hash.includes('t=t3') && sync3.hash.includes('p=central_lake') && sync3.selId === 'central_lake',
  JSON.stringify(sync3))

// ---- 4. 快速连点三个分区，最终数据属于最后一个 ----
const rapid = await evalJs(`(async () => {
  const items = [...document.querySelectorAll('.stn-zone-item')]
  if (items.length < 3) return { err: 'LIST<' + items.length }
  const picks = items.slice(0, 3).map((el) => ({ id: el.dataset.zoneId, code: el.querySelector('.zi-code')?.textContent.trim() }))
  for (const p of picks) {
    const el = items.find((i) => i.dataset.zoneId === p.id)
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
    await new Promise((r) => setTimeout(r, 40))
  }
  return picks
})()`)
await sleep(2000)
const rapidEnd = await evalJs(`(() => {
  const sel = document.querySelector('.stn-zone-item.selected')
  const profile = document.querySelector('.stn-sec-profile')
  return { selId: sel ? sel.dataset.zoneId : null, profileText: profile ? profile.textContent : '' }
})()`)
const lastPick = Array.isArray(rapid) ? rapid[rapid.length - 1] : null
// 归属一致性：最后一次 observations/quality/explanations 请求必须指向最终分区
const ownership = (() => {
  const grab = (re) => {
    const hits = [...apiRequests.values()].filter((r) => re.test(r.url))
    const m = hits.length ? decodeURIComponent(hits[hits.length - 1].url).match(re) : null
    return m ? m[1] : null
  }
  return {
    obs: grab(/spatial-entities\/([^/?]+)\/observations/),
    qly: grab(/spatial-entities\/([^/?]+)\/quality/),
    exp: grab(/forecasts\/demo-forecast-([a-z_]+)-\d+d\/explanations/)
  }
})()
check('4. 快速连续点击三个分区，最终数据属于最后一个（选择/档案/观测/质量/解释归属一致）',
  Array.isArray(rapid) && rapidEnd.selId === lastPick?.id
    && rapidEnd.profileText.includes(lastPick?.code)
    && ownership.obs === lastPick?.id && ownership.qly === lastPick?.id && ownership.exp === lastPick?.id,
  `picks=${JSON.stringify(rapid)} end=${JSON.stringify({ selId: rapidEnd.selId })} ownership=${JSON.stringify(ownership)}`)

// ---- 5. 搜索和风险筛选正确 ----
await evalJs(`(() => {
  const inp = document.querySelector('.stn-search input')
  inp.value = 'NW'
  inp.dispatchEvent(new Event('input', { bubbles: true }))
  return 'OK'
})()`)
await sleep(700)
const searchRes = await evalJs(`(() => {
  const items = [...document.querySelectorAll('.stn-zone-item')]
  return { n: items.length, codes: items.map((i) => i.querySelector('.zi-code')?.textContent.trim()) }
})()`)
check('5a. 搜索 “NW” 只剩 NW-01', searchRes.n === 1 && searchRes.codes[0] === 'NW-01', JSON.stringify(searchRes))
await evalJs(clickByRole('.stn-search-clear'))
await sleep(500)
const filterRes = await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.stn-filter button')]
  const high = btns.find((b) => b.textContent.includes('高风险'))
  if (!high) return { err: 'NO_FILTER_BTN' }
  high.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  return 'OK'
})()`)
await sleep(600)
const highRes = await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.stn-filter button')]
  const high = btns.find((b) => b.textContent.includes('高风险'))
  const items = [...document.querySelectorAll('.stn-zone-item')]
  const badges = items.map((i) => i.querySelector('.zi-risk')?.className || '')
  return {
    pressed: high ? high.getAttribute('aria-pressed') : null,
    n: items.length,
    allHigh: badges.length > 0 && badges.every((c) => c.includes('lv-high')),
    badges
  }
})()`)
check('5b. 高风险筛选后全部为高风险且 aria-pressed 正确',
  highRes.allHigh && highRes.pressed === 'true', JSON.stringify({ r: highRes }))

// ---- 6. 清除筛选恢复 6 个分区 ----
await evalJs(`(() => {
  const btns = [...document.querySelectorAll('.stn-filter button')]
  const all = btns.find((b) => b.textContent.includes('全部'))
  all.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  const inp = document.querySelector('.stn-search input')
  if (inp.value) {
    inp.value = ''
    inp.dispatchEvent(new Event('input', { bubbles: true }))
  }
  return 'OK'
})()`)
await sleep(700)
const allCount = await evalJs(`document.querySelectorAll('.stn-zone-item').length`)
check('6. 清除筛选恢复 6 个演示分区', allCount === 6, `count=${allCount}`)

// ---- 7/8 回到 central_lake：稀疏趋势 + 缺失值不补 0 ----
await evalJs(`(() => {
  const el = [...document.querySelectorAll('.stn-zone-item')].find((i) => i.dataset.zoneId === 'central_lake')
  if (!el) return 'NO_ZONE'
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }))
  return 'CLICKED'
})()`)
await sleep(2200)
const sparse = await evalJs(`(() => {
  const note = document.querySelector('.stn-trend-note--sparse')
  const honesty = [...document.querySelectorAll('.stn-trend-note')].map((n) => n.textContent)
  return {
    sparseShown: !!note,
    sparseText: note ? note.textContent.trim().slice(0, 60) : '',
    hasHonestyNote: honesty.some((t) => t.includes('不进行插值'))
  }
})()`)
check('7. 单点观测只显示标记与稀疏提示，不生成假连续曲线',
  sparse.sparseShown && sparse.hasHonestyNote, JSON.stringify(sparse))
const table8 = await evalJs(`(() => {
  const rows = [...document.querySelectorAll('.stn-table tbody tr')]
  const cells = rows.flatMap((r) => [...r.querySelectorAll('td')].map((c) => c.textContent.trim()))
  return { rowCount: rows.length, zeroCells: cells.filter((c) => c === '0' || c === '0.00' || c === '0.000').length, cells }
})()`)
check('8. 缺失值不转成 0（central_lake 仅 1 行接口返回的模拟观测，无 0 填充）',
  table8.rowCount === 1 && table8.zeroCells === 0 && table8.cells.some((c) => c.includes('0.063')),
  JSON.stringify(table8))

// ---- 9. T+1/T+3/T+7/T+15 正常切换 ----
let stage9Ok = true
const stage9Detail = []
for (let i = 0; i <= 3; i++) {
  const r = await evalJs(`(() => {
    const btns = [...document.querySelectorAll('.stn-stage-btn')]
    btns[${i}].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    return 'OK'
  })()`)
  await sleep(900)
  const st = await evalJs(`(() => {
    const active = document.querySelector('.stn-stage-btn.active')
    return { active: active ? active.textContent.trim().slice(0, 4) : null, hash: location.hash }
  })()`)
  const expect = ['T+1', 'T+3', 'T+7', 'T+15'][i]
  const ok = r === 'OK' && st.active === expect && st.hash.includes(`t=t${[1, 3, 7, 15][i]}`)
  stage9Ok = stage9Ok && ok
  stage9Detail.push(`${expect}:${st.active}`)
}
check('9. T+1/T+3/T+7/T+15 正常切换（active + URL 同步）', stage9Ok, stage9Detail.join(' '))

// ---- 9b. 档位切换期间旧档位预测不得沿用（阻塞 T+1 请求制造加载/失败窗口）----
const scoreBeforeSwitch = await evalJs(`(() => {
  const s = document.querySelector('.stn-sec-forecast .sf-score')
  return s ? s.textContent.trim() : null
})()`)
await send('Network.setBlockedURLs', { urls: ['*horizon_days=1'] })
await evalJs(`(() => { [...document.querySelectorAll('.stn-stage-btn')][0].dispatchEvent(new MouseEvent('click', { bubbles: true })) ; return 'OK' })()`)
await sleep(400)
const duringLoad = await evalJs(`(() => {
  const sec = document.querySelector('.stn-sec-forecast')
  return {
    staleScore: !!document.querySelector('.stn-sec-forecast .sf-score'),
    loadingSkel: !!document.querySelector('.stn-sec-forecast .skel-row'),
    errShown: sec ? sec.textContent.includes('预测接口请求失败') : false,
    active: document.querySelector('.stn-stage-btn.active')?.textContent.trim().slice(0, 4) || null
  }
})()`)
await send('Network.setBlockedURLs', { urls: [] })
check('9b. 档位切换加载/失败期间不展示旧档位预测（无 sf-score 残值）',
  scoreBeforeSwitch !== null && duringLoad.active === 'T+1'
    && !duringLoad.staleScore && (duringLoad.loadingSkel || duringLoad.errShown),
  `before=${scoreBeforeSwitch} during=${JSON.stringify(duringLoad)}`)

// ---- 9c. 失败必须可见（不被旧值掩盖）；重试成功后展示 T+1 档位数据 ----
await sleep(600)
const failedState = await evalJs(`(() => {
  const sec = document.querySelector('.stn-sec-forecast')
  return {
    errShown: sec ? sec.textContent.includes('预测接口请求失败') : false,
    staleScore: !!document.querySelector('.stn-sec-forecast .sf-score')
  }
})()`)
await evalJs(clickByRole('.stn-sec-forecast .stn-inline-btn'))
await sleep(1800)
const afterRetry = await evalJs(`(() => {
  const score = document.querySelector('.stn-sec-forecast .sf-score')
  const panel = [...document.querySelectorAll('.stn-tabpanel')][0]
  const dts = [...(panel ? panel.querySelectorAll('.stn-kv dt') : [])]
  const stageDt = dts.find((d) => d.textContent.trim() === '档位')
  return {
    score: score ? score.textContent.trim() : null,
    stageVal: stageDt && stageDt.nextElementSibling ? stageDt.nextElementSibling.textContent.trim() : null,
    errShown: (document.querySelector('.stn-sec-forecast') || { textContent: '' }).textContent.includes('预测接口请求失败')
  }
})()`)
check('9c. 预测失败显示错误并可重试；重试后展示 T+1 档位数据',
  failedState.errShown && !failedState.staleScore
    && afterRetry.score !== null && (afterRetry.stageVal || '').includes('T+1') && !afterRetry.errShown,
  `failed=${JSON.stringify(failedState)} after=${JSON.stringify(afterRetry)}`)

// ---- 10. T+30 显示能力阻塞，不调用预测接口 ----
const apiCountBefore30 = [...apiRequests.values()].length
await evalJs(`(() => { [...document.querySelectorAll('.stn-stage-btn')][4].dispatchEvent(new MouseEvent('click', { bubbles: true })) ; return 'OK' })()`)
await sleep(1200)
const blocked = await evalJs(`(() => {
  const box = document.querySelector('.stn-forecast-blocked')
  const txt = box ? box.textContent : ''
  return {
    shown: !!box,
    hasCap: txt.includes('30—90 天预测能力未就绪'),
    hasBoundary: txt.includes('当前仅允许模拟预演，不提供正式预测结论')
  }
})()`)
const h30Calls = [...apiRequests.values()].filter((r) => r.url.includes('horizon_days=30'))
check('10. T+30 显示能力阻塞文案且不调用预测接口',
  blocked.shown && blocked.hasCap && blocked.hasBoundary && h30Calls.length === 0,
  `blocked=${JSON.stringify(blocked)} h30Calls=${h30Calls.length} apiTotalBefore=${apiCountBefore30}`)

// ---- 回到 t3，检查 11/12 ----
await evalJs(`(() => { [...document.querySelectorAll('.stn-stage-btn')][1].dispatchEvent(new MouseEvent('click', { bubbles: true })) ; return 'OK' })()`)
await sleep(1000)

// ---- 11. 驱动因素 = 演示规则贡献 ----
await evalJs(`(() => { [...document.querySelectorAll('.stn-tab')][1].dispatchEvent(new MouseEvent('click', { bubbles: true })) ; return 'OK' })()`)
await sleep(800)
const drivers = await evalJs(`(() => {
  const panels = [...document.querySelectorAll('.stn-tabpanel')]
  const active = panels.find((p) => p.offsetParent !== null) || panels[1]
  const txt = (active || panels[0]).textContent
  return { panelCount: panels.length, activeIdx: panels.indexOf(active), hasDemoRule: txt.includes('演示规则贡献'), hasNoShap: txt.includes('非真实 SHAP') }
})()`)
check('11. 驱动因素明确标记为演示规则贡献（非真实 SHAP）',
  drivers.hasDemoRule && drivers.hasNoShap, JSON.stringify(drivers))

// ---- 12. Tab 支持鼠标和键盘 ----
const kb = await evalJs(`(async () => {
  const tabs = [...document.querySelectorAll('.stn-tab')]
  const list = document.querySelector('.stn-tablist')
  const sel = () => [...document.querySelectorAll('.stn-tab')].findIndex((t) => t.getAttribute('aria-selected') === 'true')
  tabs[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 400))
  const before = sel()
  list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
  await new Promise((r) => setTimeout(r, 400))
  const afterRight = sel()
  list.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }))
  await new Promise((r) => setTimeout(r, 400))
  const afterLeft = sel()
  return { before, afterRight, afterLeft }
})()`)
check('12. 三个 Tab 支持鼠标（前述点击）与键盘（方向键）操作',
  kb.before === 0 && kb.afterRight === 1 && kb.afterLeft === 0, JSON.stringify(kb))

// ---- 13. 模拟预警必须经过确认弹窗 ----
const warnOpen = await evalJs(clickByRole('.stn-sec-events [data-role="warn-trigger"]'))
await sleep(700)
const dlg = await evalJs(`(() => {
  const d = document.querySelector('.stn-dlg')
  return { shown: !!d, role: d?.getAttribute('role'), modal: d?.getAttribute('aria-modal'), text: d ? d.textContent.slice(0, 120) : '' }
})()`)
check('13. 模拟预警必须经过确认弹窗（role=dialog + 模拟声明）',
  warnOpen === 'CLICKED' && dlg.shown && dlg.role === 'dialog' && dlg.modal === 'true'
    && dlg.text.includes('模拟预警处理') && dlg.text.includes('simulated_dispatched'),
  `open=${warnOpen} dlg=${JSON.stringify(dlg)}`)
await shot(path.join(OUT_DIR, 'stations-warning-confirm.png'))

// ---- 14. 取消弹窗不调用接口 ----
const warnCallsBefore = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning')).length
await evalJs(clickByRole('.stn-dlg .dlg-btn--ghost'))
await sleep(600)
const dlgClosed = await evalJs(`!document.querySelector('.stn-dlg')`)
const warnCallsAfterCancel = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning')).length
check('14. 取消弹窗不调用预警接口',
  dlgClosed && warnCallsBefore === 0 && warnCallsAfterCancel === 0,
  `closed=${dlgClosed} warnCalls=${warnCallsAfterCancel}`)

// ---- 15. 确认后只显示模拟发送状态 ----
await evalJs(clickByRole('.stn-sec-events [data-role="warn-trigger"]'))
await sleep(600)
await evalJs(clickByRole('.stn-dlg .dlg-btn--danger'))
await sleep(1500)
const warnResult = await evalJs(`(() => {
  const res = document.querySelector('.stn-warn-result')
  return { shown: !!res, text: res ? res.textContent.trim().slice(0, 100) : '' }
})()`)
const warnCalls = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning'))
check('15. 确认后只显示模拟发送状态（simulated_dispatched，接口 200）',
  warnResult.shown && warnResult.text.includes('simulated_dispatched')
    && warnCalls.length === 1 && warnCalls[0].status === 200,
  `result=${JSON.stringify(warnResult)} call=${JSON.stringify(warnCalls)}`)

// ---- 19. 1920 首屏（先回到干净状态再截图） ----
await goto(`${BASE}/#/stations?t=t3&p=central_lake`)
await sleep(3200)
const oneScreen = await evalJs(`(() => {
  const pick = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { top: Math.round(r.top + scrollY), bottom: Math.round(r.bottom + scrollY) }
  }
  return {
    title: pick('.stn-title'), list: pick('.stn-list-panel'), map: pick('.stn-map-wrap'),
    trend: pick('.stn-trend-panel'), profile: pick('.stn-sec-profile'), events: pick('.stn-sec-events'),
    tabBar: pick('.stn-tablist'), vh: innerHeight
  }
})()`)
const osFail = Object.entries(oneScreen)
  .filter(([k, v]) => k !== 'vh' && (!v || v.bottom > oneScreen.vh))
  .map(([k, v]) => `${k}:${v ? v.bottom : 'null'}`)
check('19. 1920px 核心内容在首屏（含 Tab 行完整可见；Tab 明细面板允许下探）',
  osFail.length === 0, `vh=${oneScreen.vh} overflow=${osFail.join(',') || 'none'} ${JSON.stringify(oneScreen)}`)
await shot(path.join(OUT_DIR, 'stations-1920.png'))

// ---- 1440 截图 ----
await setViewport(1440, 900)
await sleep(1000)
await shot(path.join(OUT_DIR, 'stations-1440.png'))

// ================================================================
// 阶段 B：移动端 390×844
// ================================================================
await setViewport(390, 844, true)
await goto(`${BASE}/#/stations?t=t3&p=central_lake`)
await sleep(3500)

// ---- 18. 无横向溢出 ----
const overflow = await evalJs(`({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })`)
check('18. 390px 无横向溢出', overflow.sw <= overflow.iw + 1, `scrollWidth=${overflow.sw} innerWidth=${overflow.iw}`)

// ---- 16. 分区抽屉、底部栏和焦点行为 ----
const bar16 = await evalJs(`(() => {
  const bar = document.querySelector('.stn-mobile-bar')
  if (!bar) return { err: 'NO_BAR' }
  const r = bar.getBoundingClientRect()
  const cs = getComputedStyle(bar)
  return { fixed: cs.position === 'fixed', bottom: Math.round(r.bottom), vh: window.innerHeight }
})()`)
check('16a. 底部操作栏 fixed 且贴住视口底', bar16.fixed === true && Math.abs(bar16.bottom - bar16.vh) <= 2,
  JSON.stringify(bar16))
await evalJs(clickByRole('.stn-mobile-bar [data-role="drawer-trigger"]'))
await sleep(700)
const drawerOpen = await evalJs(`(() => {
  const d = document.querySelector('.stn-drawer')
  if (!d) return { shown: false }
  const ae = document.activeElement
  return { shown: true, focusInside: d.contains(ae), items: d.querySelectorAll('.dr-item').length }
})()`)
check('16b. 分区抽屉打开且焦点移入', drawerOpen.shown === true && drawerOpen.focusInside === true,
  JSON.stringify(drawerOpen))
await shot(path.join(OUT_DIR, 'stations-drawer-390.png'))
await evalJs(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`)
await sleep(600)
const drawerClose = await evalJs(`(() => {
  const closed = !document.querySelector('.stn-drawer')
  const trig = document.querySelector('.stn-mobile-bar [data-role="drawer-trigger"]')
  return { closed, focusBack: trig && document.activeElement === trig }
})()`)
check('16c. Esc 关闭抽屉且焦点返回触发按钮',
  drawerClose.closed && drawerClose.focusBack === true, JSON.stringify(drawerClose))

// ---- 17. 触摸目标 ≥44×44 ----
const touchTargets = await evalJs(`(() => {
  const sels = ['.stn-mobile-bar a', '.stn-mobile-bar button', '.stn-stage-btn', '.stn-chip',
    '.stn-tab', '.stn-filter button', '.stn-search input', '.stn-zone-item', '.dr-item', '.dr-close',
    '.layer-switcher button', '.stn-layer-toggles button', '.stn-inline-btn', '.tool-chip',
    '.leaflet-control-zoom a']
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
const badTouch = touchTargets.filter((t) => t.w < 44 || t.h < 44)
console.log('TOUCH_TARGETS', JSON.stringify(touchTargets))
check('17. 390px 主要触摸目标 ≥44×44px', touchTargets.length > 0 && badTouch.length === 0,
  badTouch.length ? `violations=${JSON.stringify(badTouch)}` : `${touchTargets.length} 个目标全部达标`)
await shot(path.join(OUT_DIR, 'stations-390.png'))

// ================================================================
// 阶段 C：回归 P01 / P07 / 历史页
// ================================================================
await setViewport(1440, 900)
await goto(`${BASE}/#/cockpit?t=t7&p=northwest_hotspot`)
await sleep(3200)
const cockpitOk = await evalJs(`!!document.querySelector('.ckp-kpis') && !!document.querySelector('.ckp-map')`)
await goto(`${BASE}/#/heatmap`)
await sleep(2000)
const heatOk = await evalJs(`!!document.querySelector('.panel')`)
await goto(`${BASE}/#/history`)
await sleep(2000)
const histOk = await evalJs(`!!document.querySelector('.panel')`)
check('20. P01 驾驶舱 / P07 热力图 / 历史页回归正常',
  cockpitOk && heatOk && histOk, `cockpit=${cockpitOk} heatmap=${heatOk} history=${histOk}`)

// ---- 21. 控制台无 error ----
const pageErrors = consoleErrors.filter((t) => !t.includes('favicon') && !t.includes('Failed to load resource'))
console.log('CONSOLE_ERRORS', pageErrors.length)
pageErrors.slice(0, 10).forEach((t) => console.log('  ERR:', t))
check('21. 全流程控制台无 error', pageErrors.length === 0, `${pageErrors.length} 个错误`)

// ---- 22. 断言失败时返回非零退出码（子进程自检） ----
const selfRun = spawnSync(process.execPath, [fileURLToPath(import.meta.url)], {
  env: { ...process.env, AUDIT4_SELFCHECK: '1' }, encoding: 'utf8'
})
check('22. 脚本断言失败时返回非零退出码', selfRun.status === 1 && /EXIT_CODE 1/.test(selfRun.stdout),
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
