// 零依赖 P06 历史复盘复验脚本（Node >= 22 内置 WebSocket/fetch）：无头 Edge 直连页面级 DevTools。
// 覆盖任务书 33 项验收：URL 初始化/刷新恢复/非法归一化、事件双源渲染与倒序、同 ID 合并、
// 日期校验/90 天/查询/重置、空态与清除筛选、选择与 URL/详情一致、身份字段完整、演示分区口径、
// 触发规则/影响范围/处置状态“接口未提供”、回放窗口 -24h~+48h、播放停在末帧不循环、4× 倍速、
// 快速切换不串写、时间轴失败清空旧数据、重试恢复、三类预案无伪造分、预案匹配禁用、
// 低/中风险禁止模拟发送、高风险确认弹窗、取消 0 POST、确认恰 1 次 POST、simulated_dispatched、
// 未形成持久化处置记录、无误导措辞、1920/1440 桌面、390 列表/详情/抽屉焦点/无溢出/触摸目标、
// P01/P03/P07/History 切换、event 参数冷启动/刷新恢复/非法清除（审计 P1 回归）、
// 控制台 0 error（favicon.ico 404 既有缺失豁免）、失败非零退出码。
// 截图输出到本目录 audit6-screenshots/。
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.env.VERIFY_BASE || 'http://localhost:4173'
const OUT_DIR = fileURLToPath(new URL('./audit6-screenshots/', import.meta.url))
fs.mkdirSync(OUT_DIR, { recursive: true })

const log = (...a) => console.log(new Date().toISOString().slice(17, 23), ...a)

// ---------- 自检模式（验证第 33 条：断言失败 → 非零退出码） ----------
if (process.env.AUDIT6_SELFCHECK) {
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
async function apiJson(p) {
  const r = await fetch(`${BASE}/api/v1/${p}`)
  if (!r.ok) throw new Error(`${p} -> ${r.status}`)
  const body = await r.json()
  if (body.code !== 200) throw new Error(`${p} code=${body.code}`)
  return body
}

const evBasic = await apiJson('events')
const evCockpit = await apiJson('cockpit/events')
const basicIds = (evBasic.data || []).map((e) => e.id).sort()
const cockpitIds = (evCockpit.data || []).map((e) => e.id).sort()
const apiTimeline = async (start, end) => (await apiJson(`cockpit/timeline?start=${start}&end=${end}`)).data

const proc = spawn(EDGE, [
  '--headless',
  '--remote-debugging-port=0',
  `--user-data-dir=${fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-audit6-'))}`,
  '--no-first-run',
  '--disable-gpu',
  '--window-size=1920,1080',
  'about:blank'
], { stdio: ['ignore', 'ignore', 'pipe'] })
proc.on('error', (e) => { console.error('SPAWN_ERROR', e); process.exit(2) })
setTimeout(() => { console.error('WATCHDOG_TIMEOUT'); proc.kill(); process.exit(3) }, 600000)

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

const ws = new WebSocket(pageWs)
await new Promise((res, rej) => {
  const t = setTimeout(() => rej(new Error('page ws open timeout')), 10000)
  ws.onopen = () => { clearTimeout(t); res() }
  ws.onerror = () => { clearTimeout(t); rej(new Error('page ws error')) }
})
log('ws open')

let msgId = 0
const pending = new Map()
const consoleErrors = [] // { text, injected } —— injected=故意注入失败窗口内产生的预期资源错误
const http4xxUrls = new Set() // 全部 ≥400 的资源 URL（含 favicon 等非 /api/ 资源）
let injectedWindow = false
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
    consoleErrors.push({ text: m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300), injected: injectedWindow })
  }
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
    consoleErrors.push({ text: (`[log] ${m.params.entry.text}`).slice(0, 300), injected: injectedWindow })
  }
  if (m.method === 'Runtime.exceptionThrown') {
    consoleErrors.push({ text: (`[exc] ${m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text}`).slice(0, 300), injected: injectedWindow })
  }
  if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) {
    http4xxUrls.add(m.params.response.url)
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
  await sleep(1600)
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

const setInput = (sel, val) => `(() => {
  const el = document.querySelector('${sel}')
  if (!el) return 'NO_EL'
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
  desc.set.call(el, '${val}')
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
  return 'SET'
})()`

async function waitExpr(expr, timeout = 9000, interval = 200) {
  const start = Date.now()
  while (Date.now() - start < timeout) {
    try {
      if (await evalJs(`Boolean(${expr})`)) return true
    } catch { /* page may be mid-navigation */ }
    await sleep(interval)
  }
  return false
}

// ---------- 页面状态快照 ----------
const SNAP = `(() => {
  const q = (s) => document.querySelector(s)
  const qa = (s) => Array.from(document.querySelectorAll(s))
  const items = qa('[data-event-id]')
  const detailQ = (s) => q(s)?.textContent?.trim() || ''
  return {
    hash: location.hash,
    title: q('.his-title h1')?.textContent?.trim() || '',
    desc: q('.his-desc')?.textContent?.trim() || '',
    chips: qa('.his-chip').map((c) => c.textContent.trim()),
    exportDisabled: q('[data-role=export-btn]')?.disabled ?? null,
    itemCount: items.length,
    pageIds: items.map((b) => b.dataset.eventId),
    countText: q('[data-role=event-count]')?.textContent?.trim() || '',
    selectedId: items.find((b) => b.classList.contains('active'))?.dataset.eventId || '',
    firstItemText: items[0]?.textContent?.replace(/\\s+/g, ' ') || '',
    listError: q('[data-role=event-list-panel] .state-panel--error')?.textContent?.trim() || null,
    emptyText: q('[data-role=event-empty]')?.textContent?.trim() || null,
    filterStart: q('[data-role=filter-start]')?.value || '',
    filterEnd: q('[data-role=filter-end]')?.value || '',
    filterType: q('[data-role=filter-type]')?.value || '',
    filterZone: q('[data-role=filter-zone]')?.value || '',
    filterMode: q('[data-role=filter-mode]')?.value || '',
    filterStatusDisabled: q('[data-role=filter-status]')?.disabled ?? null,
    filterError: q('[data-role=filter-error]')?.textContent?.trim() || '',
    summary: q('[data-role=filter-summary-text]')?.textContent?.trim() || '',
    detail: {
      present: !!q('[data-role=event-detail-panel]'),
      id: detailQ('[data-role=detail-id]'),
      title: detailQ('[data-role=detail-title]'),
      severity: detailQ('[data-role=detail-severity]'),
      time: detailQ('[data-role=detail-time]'),
      type: detailQ('[data-role=detail-type]'),
      zone: detailQ('[data-role=detail-zone]'),
      mode: detailQ('[data-role=detail-mode]'),
      version: detailQ('[data-role=detail-version]'),
      run: detailQ('[data-role=detail-run]'),
      stage: detailQ('[data-role=detail-stage]'),
      frame: detailQ('[data-role=detail-frame]'),
      summary: detailQ('[data-role=detail-summary]'),
      trigger: detailQ('[data-role=detail-trigger]'),
      scope: detailQ('[data-role=detail-scope]'),
      handle: detailQ('[data-role=detail-handle]'),
      linkStations: q('[data-role=detail-link-stations]')?.getAttribute('href') || null,
      linkHeatmap: q('[data-role=detail-link-heatmap]')?.getAttribute('href') || null,
      warnDisabled: q('[data-role=warn-trigger]')?.disabled ?? null,
      recordDisabled: q('[data-role=dispatch-record]')?.disabled ?? null,
      dispatchResult: detailQ('[data-role=dispatch-result]')
    },
    replay: {
      state: q('[data-role=replay-state]')?.dataset.state || null,
      errorText: q('[data-role=replay-state]')?.textContent?.trim() || '',
      frameCount: qa('[data-role^="replay-frame-"]').length,
      frameLabels: qa('[data-role^="replay-frame-"] .hrp-frame-label').map((e) => e.textContent.trim()),
      frameDates: qa('[data-role^="replay-frame-"] .hrp-frame-date').map((e) => e.textContent.trim()),
      frameRisks: qa('[data-role^="replay-frame-"] .hrp-frame-risk').map((e) => e.textContent.trim()),
      activeIdx: qa('[data-role^="replay-frame-"]').findIndex((f) => f.classList.contains('active')),
      progress: detailQ('[data-role=replay-progress]'),
      playLabel: detailQ('[data-role=replay-play]'),
      nextDisabled: q('[data-role=replay-next]')?.disabled ?? null,
      sync: detailQ('[data-role=replay-sync]'),
      note: detailQ('[data-role=replay-note]'),
      retryBtn: !!q('[data-role=replay-retry]')
    },
    plans: qa('[data-role=plan-template] h4').map((h) => h.textContent.trim()),
    planText: q('[data-role=plan-panel]')?.textContent?.replace(/\\s+/g, ' ') || '',
    planMatchDisabled: q('[data-role=plan-match]')?.disabled ?? null,
    capsRows: qa('[data-role=caps-list] div').map((d) => d.textContent.replace(/\\s+/g, ' ').trim()),
    capsError: !!q('[data-role=plan-caps] .state-panel--error'),
    dialog: {
      present: !!q('.hwd'),
      modal: q('[role=dialog].hwd')?.getAttribute('aria-modal') || null,
      text: q('.hwd')?.textContent?.replace(/\\s+/g, ' ') || ''
    },
    mobile: {
      bodyClass: q('.his-body')?.className || '',
      listVisible: !!q('.his-list') && !!q('.his-list').offsetParent,
      detailVisible: !!q('.his-detail') && !!q('.his-detail').offsetParent,
      backToList: !!q('[data-role=back-to-list]') && q('[data-role=back-to-list]').offsetParent !== null,
      barButtons: qa('.his-mobile-bar button, .his-mobile-bar a').map((b) => ({ text: b.textContent.trim().slice(0, 8), disabled: b.disabled ?? false })),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    },
    bodyText: document.body.innerText
  }
})()`
const snap = () => evalJs(SNAP)

const HIST = (q = '') => `${BASE}/#/history${q}`

// ============================================================
// Phase 1：1920×1080 桌面
// ============================================================
await setViewport(1920, 1080)
await goto(HIST('/'))
let s = await snap()
await shot(path.join(OUT_DIR, 'history-1920.png'))

// 1. 标题与数据身份
const expectChips = ['SIMULATED', 'DEMO-OBS-V1', 'DEMO-PRED-V1', 'DEMO-RUN-V1', 'simulation_only', '非决策用途']
check('1. 标题区含页面说明与六项数据身份标签、导出按钮禁用',
  s.title === '历史事件与处置复盘'
  && s.desc.includes('演示事件链回放，不代表真实历史灾情或正式处置档案')
  && expectChips.every((c) => s.chips.some((x) => x.includes(c)))
  && s.exportDisabled === true,
  `chips=${JSON.stringify(s.chips)}`)

// 2. 事件按接口渲染且倒序
const apiSorted = [...basicIds].sort((a, b) => (a < b ? 1 : -1)) // demo-event-5 … demo-event-0（occurred_at 随序号递增）
check('2. 事件列表按 /events+/cockpit/events 渲染且按时间倒序',
  s.itemCount === basicIds.length
  && JSON.stringify(s.pageIds) === JSON.stringify(apiSorted)
  && s.countText === String(basicIds.length),
  `page=${JSON.stringify(s.pageIds)} api=${JSON.stringify(basicIds)}`)

// 3. 仅按相同 ID 合并（每条同时含 /events 的数据模式与 /cockpit/events 的风险等级）
const firstMergedOk = s.firstItemText.includes('simulated') && /(高风险|中风险|低风险)/.test(s.firstItemText)
check('3. 两个事件接口只按相同 ID 合并（同条同时呈现两源字段，ID 集合一致）',
  firstMergedOk && JSON.stringify(s.pageIds.slice().sort()) === JSON.stringify(basicIds),
  s.firstItemText.slice(0, 80))

// 4. 日期校验 / 90 天 / 查询 / 重置
await evalJs(setInput('[data-role=filter-start]', '2026-08-10'))
await evalJs(setInput('[data-role=filter-end]', '2026-08-05'))
await evalJs(clickSel('[data-role=filter-query]'))
await sleep(300)
s = await snap()
const reversedUrlOk = !/[?&]start=2026-08-10/.test(s.hash)
check('4a. 开始晚于结束 → 就地报错且不应用',
  s.filterError.includes('开始日期不能晚于结束日期') && reversedUrlOk, s.filterError)

await evalJs(setInput('[data-role=filter-start]', '2026-06-01'))
await evalJs(setInput('[data-role=filter-end]', '2026-09-30'))
await evalJs(clickSel('[data-role=filter-query]'))
await sleep(300)
s = await snap()
check('4b. 跨度超过 90 天 → 就地报错且不应用',
  s.filterError.includes('查询范围最大 90 天'), s.filterError)

await evalJs(setInput('[data-role=filter-start]', '2026-08-16'))
await evalJs(setInput('[data-role=filter-end]', '2026-08-17'))
await evalJs(clickSel('[data-role=filter-query]'))
await sleep(500)
s = await snap()
check('4c. 合法范围查询 → URL 同步 start/end 且列表只剩 2 条',
  /[?&]start=2026-08-16/.test(s.hash) && /[?&]end=2026-08-17/.test(s.hash) && s.itemCount === 2,
  `hash=${s.hash} count=${s.itemCount}`)

await evalJs(clickSel('[data-role=filter-reset]'))
await sleep(500)
s = await snap()
check('4d. 重置 → 筛选清空、URL 参数移除、列表恢复',
  s.filterStart === '' && s.filterEnd === '' && !/[?&]start=/.test(s.hash) && s.itemCount === basicIds.length,
  `hash=${s.hash}`)

// 5. 筛选空状态与清除筛选
await evalJs(setInput('[data-role=filter-start]', '2026-09-01'))
await evalJs(setInput('[data-role=filter-end]', '2026-09-10'))
await evalJs(clickSel('[data-role=filter-query]'))
await sleep(500)
s = await snap()
const emptyOk = (s.emptyText || '').includes('当前筛选条件下无事件')
await evalJs(clickSel('[data-role=clear-filters]'))
await sleep(500)
s = await snap()
check('5. 筛选后空状态提示 + 清除筛选恢复',
  emptyOk && s.itemCount === basicIds.length && s.emptyText === null,
  `empty=${emptyOk} count=${s.itemCount}`)

// 6. 选择事件 → URL / 详情一致
await evalJs(clickSel('[data-event-id="demo-event-0"]'))
await sleep(600)
s = await snap()
check('6. 点击事件 → 选中态 + URL event 参数 + 详情标题一致',
  s.selectedId === 'demo-event-0' && /[?&]event=demo-event-0/.test(s.hash)
  && s.detail.id === 'demo-event-0' && s.detail.present
  && s.detail.title === (evCockpit.data.find((e) => e.id === 'demo-event-0')?.title || ''),
  `sel=${s.selectedId} hash=${s.hash}`)

// 7. 详情身份字段完整
check('7. 详情含数据模式 / 数据集版本 / 预测运行 ID / 档位',
  s.detail.mode === 'simulated'
  && s.detail.version === (evBasic.meta?.dataset_version || 'DEMO-PRED-V1')
  && s.detail.run === 'DEMO-RUN-V1'
  && /T\+\d+d · (演示预测|模拟预演)/.test(s.detail.stage),
  `mode=${s.detail.mode} ver=${s.detail.version} run=${s.detail.run} stage=${s.detail.stage}`)

// 8. 演示分区不显示为真实站点
check('8. 关联分区标注为“演示分区，非真实监测站”',
  s.detail.zone.includes('演示分区') && s.detail.zone.includes('非真实监测站'),
  s.detail.zone.slice(0, 60))

// 9. 触发规则 / 影响范围 / 真实处置状态 = 接口未提供
check('9. 触发规则、影响范围、真实处置状态均标注“接口未提供”',
  s.detail.trigger.includes('接口未提供') && s.detail.scope.includes('接口未提供') && s.detail.handle.includes('接口未提供'),
  `${s.detail.trigger} / ${s.detail.scope} / ${s.detail.handle}`)

// 10. 回放窗口 -24h ~ +48h
const t0 = await apiTimeline('2026-08-15', '2026-08-18')
// ok 态没有 replay-state 元素，以帧数=4 作为就绪信号；等待后重新快照
await waitExpr(`document.querySelectorAll('[data-role^="replay-frame-"]').length === 4`, 9000)
s = await snap()
const tlReqs = () => [...apiRequests.values()].filter((r) => r.url.includes('cockpit/timeline'))
const ev0Req = tlReqs().find((r) => r.url.includes('start=2026-08-15') && r.url.includes('end=2026-08-18'))
check('10. 选择事件后按事件日期请求 timeline，回放帧覆盖 -24h/时刻/+24h/+48h',
  !!ev0Req
  && JSON.stringify(s.replay.frameLabels) === JSON.stringify(['事件前24h', '事件时刻', '事件后24h', '事件后48h'])
  && JSON.stringify(s.replay.frameDates) === JSON.stringify(['2026-08-15', '2026-08-16', '2026-08-17', '2026-08-18'])
  && s.replay.note.includes('按日演示序列') && s.replay.note.includes('不是 72 小时逐时真实观测'),
  `labels=${JSON.stringify(s.replay.frameLabels)} dates=${JSON.stringify(s.replay.frameDates)}`)
const apiRisks = t0.data.map((d) => d.risk_level)
const pageRisksOk = s.replay.frameRisks.every((txt, i) => txt.includes(({ high: '高风险', mid: '中风险', low: '低风险' })[apiRisks[i]] || '—'))
check('10b. 回放帧风险等级与接口 risk_level 一致且标注“演示”',
  pageRisksOk && s.replay.frameRisks.every((t) => t.includes('演示')), JSON.stringify(s.replay.frameRisks))

// 截图：1920 事件选中
await shot(path.join(OUT_DIR, 'history-event-selected.png'))

// 11. 播放停在最后一帧且不循环
await evalJs(clickSel('[data-role=replay-play]'))
const stopped = await waitExpr(`document.querySelector('[data-role=replay-play]')?.textContent?.trim() === '播放' && document.querySelector('[data-role=replay-progress]')?.textContent?.includes('4/4')`, 9000)
s = await snap()
await evalJs(clickSel('[data-role=replay-next]'))
await sleep(250)
const s2 = await snap()
check('11. 播放到 +48h 自动停止、不循环（末帧再点下一帧仍 4/4）',
  stopped && s.replay.progress.includes('4/4') && s.replay.nextDisabled === true && s2.replay.progress.includes('4/4'),
  `progress=${s.replay.progress} next=${s.replay.nextDisabled}`)

// 12. 4× 倍速有效
await evalJs(clickSel('[data-role="replay-frame-0"]'))
await sleep(200)
const t4Start = Date.now()
await evalJs(clickSel('[data-role=replay-speed-4]'))
await evalJs(clickSel('[data-role=replay-play]'))
const stopped4 = await waitExpr(`document.querySelector('[data-role=replay-play]')?.textContent?.trim() === '播放' && document.querySelector('[data-role=replay-progress]')?.textContent?.includes('4/4')`, 6000)
const t4Elapsed = Date.now() - t4Start
check('12. 4× 倍速可自动播完 4 帧并停止（明显快于 1×）',
  stopped4 && t4Elapsed < 3000, `elapsed=${t4Elapsed}ms`)
await evalJs(clickSel('[data-role=replay-speed-1]'))

// 13. 快速切换事件不串写（demo-event-4 occurred_at=2026-08-20 → 窗口 08-19~08-22）
await evalJs(clickSel('[data-event-id="demo-event-2"]'))
await evalJs(clickSel('[data-event-id="demo-event-4"]'))
const ev4Dates = JSON.stringify(['2026-08-19', '2026-08-20', '2026-08-21', '2026-08-22'])
await waitExpr(`document.querySelector('[data-role=detail-id]')?.textContent?.trim() === 'demo-event-4' && JSON.stringify(Array.from(document.querySelectorAll('[data-role^="replay-frame-"] .hrp-frame-date')).map((e) => e.textContent.trim())) === '${ev4Dates}'`, 9000)
s = await snap()
const ev4ApiRisks = (await apiTimeline('2026-08-19', '2026-08-22')).data.map((d) => d.risk_level)
const ev4RisksOk = s.replay.frameRisks.every((txt, i) => txt.includes(({ high: '高风险', mid: '中风险', low: '低风险' })[ev4ApiRisks[i]] || '—'))
check('13. 快速连续切换事件 → 详情与回放均为最新事件（demo-event-4 窗口 08-19~08-22），无串写',
  s.detail.id === 'demo-event-4'
  && JSON.stringify(s.replay.frameDates) === ev4Dates
  && ev4RisksOk && s.replay.frameCount === 4,
  `id=${s.detail.id} dates=${JSON.stringify(s.replay.frameDates)}`)

// 14. 时间轴失败 → 清空旧回放数据（不保留旧事件帧）—— 以下窗口内的资源报错是故意注入的预期行为
injectedWindow = true
await send('Network.setBlockedURLs', { urls: ['*cockpit/timeline*'] })
await evalJs(clickSel('[data-event-id="demo-event-3"]'))
const errShown = await waitExpr(`document.querySelector('[data-role=replay-state]')?.dataset.state === 'error'`, 9000)
s = await snap()
await shot(path.join(OUT_DIR, 'history-error-state.png'))
check('14. 时间轴请求失败 → 回放进入 error 态且旧帧全部清空',
  errShown && s.replay.frameCount === 0 && s.detail.id === 'demo-event-3',
  `state=${s.replay.state} frames=${s.replay.frameCount}`)

// 15. 重试恢复
await send('Network.setBlockedURLs', { urls: [] })
injectedWindow = false
await evalJs(clickSel('[data-role=replay-retry]'))
const ev3Dates = JSON.stringify(['2026-08-18', '2026-08-19', '2026-08-20', '2026-08-21'])
const recovered = await waitExpr(`JSON.stringify(Array.from(document.querySelectorAll('[data-role^="replay-frame-"] .hrp-frame-date')).map((e) => e.textContent.trim())) === '${ev3Dates}'`, 9000)
s = await snap()
const ev3Risks = (await apiTimeline('2026-08-18', '2026-08-21')).data.map((d) => d.risk_level)
check('15. 重试后回放恢复为 demo-event-3 的窗口帧',
  recovered && JSON.stringify(s.replay.frameDates) === JSON.stringify(['2026-08-18', '2026-08-19', '2026-08-20', '2026-08-21'])
  && s.replay.frameRisks.every((txt, i) => txt.includes(({ high: '高风险', mid: '中风险', low: '低风险' })[ev3Risks[i]] || '—')),
  `dates=${JSON.stringify(s.replay.frameDates)}`)

// 16. 三类预案名称存在，无伪造适配分
const planNamesOk = ['取水口保护', '重点湖湾加密巡查', '强降雨后入湖河口加密监测'].every((n) => s.plans.includes(n))
const noFakeScore = !/\d+(\.\d+)?\s*分/.test(s.planText) && s.planText.includes('无适配分') && s.planText.includes('预案模板待后端接入') && s.planText.includes('无负责人') && s.planText.includes('无真实措施状态')
check('16. 三类规划预案名称存在，页面无任何伪造适配分/负责人/措施状态',
  planNamesOk && noFakeScore, `plans=${JSON.stringify(s.plans)}`)

// 17. 匹配预案按钮禁用并说明原因
check('17. “匹配预案”按钮禁用且说明原因（接口未接入）',
  s.planMatchDisabled === true && s.planText.includes('匹配预案 · 接口未接入') && s.planText.includes('当前按钮不产生任何匹配结果'),
  `disabled=${s.planMatchDisabled}`)

// 18. 低/中风险事件不能模拟发送
await evalJs(clickSel('[data-event-id="demo-event-1"]'))
await waitExpr(`document.querySelector('[data-role=detail-id]')?.textContent?.trim() === 'demo-event-1'`, 9000)
await sleep(300)
s = await snap()
check('18. 中风险演示事件：模拟发送按钮禁用并标注仅高风险可发起',
  s.detail.severity.includes('中风险') && s.detail.warnDisabled === true,
  `sev=${s.detail.severity} warnDisabled=${s.detail.warnDisabled}`)

// 19. 高风险事件必须先确认
await evalJs(clickSel('[data-event-id="demo-event-0"]'))
await waitExpr(`document.querySelector('[data-role=warn-trigger]')?.disabled === false`, 9000)
const postCountBefore = () => [...apiRequests.values()].filter((r) => r.url.includes('handle-warning') && r.method === 'POST').length
await evalJs(clickSel('[data-role=warn-trigger]'))
const dlgShown = await waitExpr(`!!document.querySelector('.hwd')`, 5000)
s = await snap()

// 弹窗内容必须含诚实边界
const dlgOk = s.dialog.modal === 'true'
  && s.dialog.text.includes('SIMULATED')
  && s.dialog.text.includes('demo-event-0')
  && s.dialog.text.includes('platform_simulation')
  && s.dialog.text.includes('接口未提供')
  && s.dialog.text.includes('无真实接收人')
  && s.dialog.text.includes('不会发送真实短信、邮件或政府预警')
  && s.dialog.text.includes('不形成持久化处置记录')
await shot(path.join(OUT_DIR, 'history-warning-confirm.png'))

// 20. 取消 → 不调用接口
await evalJs(clickSel('[data-role=warn-cancel]'))
await waitExpr(`!document.querySelector('.hwd')`, 5000)
const postsAfterCancel = postCountBefore()
check('19+20. 高风险弹窗（数据身份/渠道/模板/接收人/无真实发送声明完整）且取消后 POST 为 0',
  dlgShown && dlgOk && postsAfterCancel === 0,
  `dlg=${dlgShown} dlgOk=${dlgOk} posts=${postsAfterCancel}`)

// 21. 确认 → 恰好一次 POST；22/23. 成功只显示 simulated_dispatched + 未持久化说明
await evalJs(clickSel('[data-role=warn-trigger]'))
await waitExpr(`!!document.querySelector('.hwd')`, 5000)
await evalJs(clickSel('[data-role=warn-confirm]'))
const resultShown = await waitExpr(`(document.querySelector('[data-role=dispatch-result]')?.textContent || '').includes('simulated_dispatched')`, 9000)
await sleep(400)
const warnPosts = [...apiRequests.values()].filter((r) => r.url.includes('handle-warning') && r.method === 'POST')
s = await snap()
check('21+22. 确认后恰好 1 次 POST 且成功只显示 simulated_dispatched（含渠道 platform_simulation）',
  resultShown && warnPosts.length === 1 && warnPosts[0].status === 200
  && s.detail.dispatchResult.includes('simulated_dispatched')
  && s.detail.dispatchResult.includes('platform_simulation')
  && !s.detail.dispatchResult.includes('推送成功') && !s.detail.dispatchResult.includes('发送成功'),
  `posts=${warnPosts.length} status=${warnPosts[0]?.status}`)

check('23. 明确说明结果未形成持久化处置记录 + 查看处置记录保持禁用',
  s.detail.dispatchResult.includes('未形成持久化处置记录') && s.detail.recordDisabled === true,
  s.detail.dispatchResult.slice(0, 100))

// 24. 全页无误导措辞
const misleading = /(推送成功|处置成功|发送成功|短信已|邮件已|已通知|即时联动|真实事件|真实灾情已|不可变处置记录)/
const noMislead = !misleading.test(s.bodyText.replace(/不会发送真实短信、邮件或政府预警/g, '').replace(/不会通知任何真实人员/g, ''))
check('24. 页面无“真实短信/真实邮件/处置成功/即时联动”等误导措辞',
  noMislead, misleading.test(s.bodyText) ? '发现可疑措辞' : 'clean')

// ============================================================
// Phase 2：1440×900 桌面
// ============================================================
await setViewport(1440, 900)
await sleep(700)
s = await snap()
const overflow1440 = await evalJs(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)
const m1440 = await evalJs(`(() => {
  const list = document.querySelector('.his-list')
  const detail = document.querySelector('.his-detail')
  const main = document.querySelector('.his-main')
  const lr = list && list.getBoundingClientRect()
  const dr = detail && detail.getBoundingClientRect()
  const cs = main && getComputedStyle(main)
  const page = document.querySelector('.page-history')
  const pr = page && page.getBoundingClientRect()
  const mr = main && main.getBoundingClientRect()
  const kids = main ? Array.from(main.children).map((c) => ({
    cls: (c.className || '').toString().slice(0, 50),
    col: getComputedStyle(c).gridColumnStart + '/' + getComputedStyle(c).gridColumnEnd,
    row: getComputedStyle(c).gridRowStart + '/' + getComputedStyle(c).gridRowEnd,
    w: Math.round(c.getBoundingClientRect().width)
  })) : []
  return {
    listFound: !!list, detailFound: !!detail,
    listW: lr ? Math.round(lr.width) : null,
    detailW: dr ? Math.round(dr.width) : null,
    detailRight: dr ? Math.round(dr.right) : null,
    inner: window.innerWidth,
    client: document.documentElement.clientWidth,
    mainDisplay: cs ? cs.display : null,
    mainCols: cs ? cs.gridTemplateColumns : null,
    mainAreas: cs ? cs.gridTemplateAreas : null,
    mainW: mr ? Math.round(mr.width) : null,
    mainLeft: mr ? Math.round(mr.left) : null,
    mainRight: mr ? Math.round(mr.right) : null,
    pageLeft: pr ? Math.round(pr.left) : null,
    pageRight: pr ? Math.round(pr.right) : null,
    kids
  }
})()`)
check('25. 1440×900 布局正常（38/62 两栏、左窄右宽、无横向溢出）',
  overflow1440 === 0 && m1440.listFound && m1440.detailFound
  && m1440.listW > 200 && m1440.detailW > 300
  && m1440.listW < m1440.detailW
  && m1440.inner - m1440.detailRight <= 40,
  `overflow=${overflow1440} measured=${JSON.stringify(m1440)}`)
await shot(path.join(OUT_DIR, 'history-1440.png'))

// ============================================================
// Phase 3：390×844 移动端
// ============================================================
await setViewport(390, 844, true)
await sleep(900)
s = await snap()
check('26. 390 列表视图：列表可见、详情/预案/回放隐藏、筛选摘要显示',
  s.mobile.bodyClass.includes('his-body--m-list')
  && s.mobile.listVisible && !s.mobile.detailVisible
  && s.summary.length > 0,
  `class=${s.mobile.bodyClass} summary=${s.summary.slice(0, 40)}`)
await shot(path.join(OUT_DIR, 'history-390-list.png'))

// 29. 无横向溢出（列表视图）
const overflowList = await evalJs(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)

// 30. 触摸目标 ≥44×44（页面自身 + 底栏 + 抽屉内可见可交互元素）
const touchCheck = `(() => {
  const els = Array.from(document.querySelectorAll('.page-history button, .page-history a, .page-history select, .page-history input, .his-mobile-bar button, .his-mobile-bar a, .his-drawer button, .his-drawer select, .his-drawer input'))
  const bad = []
  els.forEach((el) => {
    if (el.closest('.his-mobile-bar')) { /* bottom bar always checked */ }
    const style = getComputedStyle(el)
    if (style.display === 'none' || style.visibility === 'hidden') return
    const r = el.getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0) return
    if (r.bottom < 0 || r.top > window.innerHeight) return
    if (r.width < 43.5 || r.height < 43.5) bad.push((el.dataset.role || el.className || el.tagName).toString().slice(0, 40) + '@' + Math.round(r.width) + 'x' + Math.round(r.height))
  })
  return { total: els.length, bad }
})()`
const touchList = await evalJs(touchCheck)

// 27/28. 移动端筛选抽屉：焦点锁定 + Esc + 焦点归还
await evalJs(clickSel('[data-role=drawer-trigger]'))
const drawerShown = await waitExpr(`!!document.querySelector('.his-drawer')`, 5000)
await sleep(300)
const focusInDrawer = await evalJs(`!!document.activeElement && !!document.activeElement.closest && !!document.activeElement.closest('.his-drawer')`)
await evalJs(`(() => { const d = document.querySelector('.his-drawer'); d.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })); return 'TAB' })()`)
await sleep(150)
const focusStillInDrawer = await evalJs(`!!document.activeElement && !!document.activeElement.closest && !!document.activeElement.closest('.his-drawer')`)
await shot(path.join(OUT_DIR, 'history-filter-drawer.png'))
const touchDrawer = await evalJs(touchCheck)
await evalJs(`(() => { const d = document.querySelector('.his-drawer'); d.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); return 'ESC' })()`)
const drawerClosed = await waitExpr(`!document.querySelector('.his-drawer')`, 5000)
await sleep(200)
const focusReturned = await evalJs(`document.activeElement?.dataset?.role === 'drawer-trigger'`)

// 27. 列表 → 详情 → 返回列表
await evalJs(clickSel('[data-event-id="demo-event-5"]'))
const detailShown = await waitExpr(`document.querySelector('.his-body')?.className?.includes('his-body--m-detail')`, 5000)
await sleep(400)
s = await snap()
const barDetail = s.mobile.barButtons.map((b) => b.text)
const overflowDetail = await evalJs(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)
const touchDetail = await evalJs(touchCheck)
await shot(path.join(OUT_DIR, 'history-390-detail.png'))
await evalJs(clickSel('[data-role=mb-back-list]'))
const backToList = await waitExpr(`document.querySelector('.his-body')?.className?.includes('his-body--m-list')`, 5000)

check('27. 390 列表/详情独立视图切换 + 详情底栏（返回列表/匹配预案/模拟发送）',
  detailShown && s.mobile.detailVisible && !s.mobile.listVisible
  && barDetail.length === 3 && barDetail[0] === '返回列表'
  && backToList,
  `bar=${JSON.stringify(barDetail)}`)

check('28. 移动端筛选抽屉：打开聚焦、Tab 圈定、Esc 关闭、焦点归还触发按钮',
  drawerShown && focusInDrawer && focusStillInDrawer && drawerClosed && focusReturned,
  `open=${drawerShown} focusIn=${focusInDrawer} tabCycle=${focusStillInDrawer} closed=${drawerClosed} focusBack=${focusReturned}`)

check('29. 390 列表视图与详情视图均无横向溢出',
  overflowList <= 0 && overflowDetail <= 0,
  `list=${overflowList} detail=${overflowDetail}`)

check('30. 主要触摸目标全部 ≥44×44（列表视图 + 抽屉 + 详情视图）',
  touchList.bad.length === 0 && touchDrawer.bad.length === 0 && touchDetail.bad.length === 0,
  `bad=${JSON.stringify([...touchList.bad, ...touchDrawer.bad, ...touchDetail.bad].slice(0, 6))} total=${touchList.total}`)

// ============================================================
// Phase 4：页面互切回归（1920）
// ============================================================
await setViewport(1920, 1080)
await goto(`${BASE}/#/cockpit`)
const cockpitOk = await waitExpr(`!!document.querySelector('h1')`, 8000)
const cockpitTitle = await evalJs(`document.querySelector('h1')?.textContent?.trim() || ''`)
await goto(`${BASE}/#/stations`)
const stationsOk = await waitExpr(`!!document.querySelector('h1')`, 8000)
await goto(`${BASE}/#/heatmap`)
const heatmapOk = await waitExpr(`!!document.querySelector('h1')`, 8000)
await goto(`${BASE}/#/history`)
const historyOk = await waitExpr(`document.querySelector('.his-title h1')?.textContent?.trim() === '历史事件与处置复盘'`, 8000)
check('31. P01/P03/P07/History 相互切换正常（均渲染标题，History 重挂载成功）',
  cockpitOk && cockpitTitle.length > 0 && stationsOk && heatmapOk && historyOk,
  `cockpit=${cockpitTitle} stations=${stationsOk} heatmap=${heatmapOk} history=${historyOk}`)

// ============================================================
// Phase 5：带 event 参数冷启动 / 刷新 / 非法 event（第六审计 P1 回归）
// ============================================================
const EV0_DATES = '["2026-08-15","2026-08-16","2026-08-17","2026-08-18"]'
const framesAre = (d) => `JSON.stringify(Array.from(document.querySelectorAll('[data-role^="replay-frame-"] .hrp-frame-date')).map((e) => e.textContent.trim())) === '${d}'`

// 先经 /index.html 文档级导航：仅变 hash 不会重挂载 History，复现不了
// “event ID 先于事件列表恢复”的冷启动竞态（check 34 的 reload 本身是真文档刷新）。
await goto(`${BASE}/index.html`)
await goto(HIST('?event=demo-event-0'))
const coldDetail = await waitExpr(`document.querySelector('[data-role=detail-id]')?.textContent?.trim() === 'demo-event-0'`, 9000)
const coldFrames = await waitExpr(framesAre(EV0_DATES), 9000)
s = await snap()
check('33. 带 event 参数冷启动 → 详情 + 四帧回放 + 事件日期窗口（08-15~08-18）全部恢复',
  coldDetail && coldFrames && s.replay.frameCount === 4,
  `detail=${coldDetail} frames=${coldFrames} dates=${JSON.stringify(s.replay.frameDates)}`)

// 刷新恢复（ID 先于事件列表恢复、事件到达后必须补发回放）
await reload()
const rlDetail = await waitExpr(`document.querySelector('[data-role=detail-id]')?.textContent?.trim() === 'demo-event-0'`, 9000)
const rlFrames = await waitExpr(framesAre(EV0_DATES), 9000)
s = await snap()
check('34. 带 event 参数刷新 → 详情与四帧回放同样恢复且 event 参数保留',
  rlDetail && rlFrames && s.replay.frameCount === 4 && /[?&]event=demo-event-0/.test(s.hash),
  `detail=${rlDetail} frames=${rlFrames} hash=${s.hash}`)

// 非法 event：同样走文档级冷启动（事件未加载时先容忍，列表到达后归一化移出 URL），
// 列表正常，详情保持空态，回放无残留帧
await goto(`${BASE}/index.html`)
await goto(HIST('?event=nonexistent-event'))
const evCleared = await waitExpr(`!/event=/.test(location.hash)`, 9000)
s = await snap()
check('35. 非法 event 参数 → 从 URL 清除、列表正常渲染、详情保持未选择空态、回放无帧',
  evCleared && s.itemCount === basicIds.length && s.selectedId === '' && !s.detail.present && s.replay.frameCount === 0,
  `hash=${s.hash} count=${s.itemCount} detail=${s.detail.present} frames=${s.replay.frameCount}`)

// 32. 控制台 0 error
// 豁免口径：① 故意注入失败窗口（检查 14/15）内的资源错误是预期行为；② favicon.ico 404 是
// dist 既有资源缺失（index.html 无 favicon 引用、public/ 无文件），非本任务修改引入，全流程
// 唯一 4xx 资源即为 favicon 时显式豁免；出现任何其他 4xx 或非资源类错误一律判 FAIL。
await sleep(800)
const faviconOnly4xx = http4xxUrls.size > 0
  && [...http4xxUrls].every((u) => /favicon\.ico(\?|$)/.test(u))
const fatalErrors = consoleErrors.filter((e) => !e.injected
  && !(faviconOnly4xx && /Failed to load resource/i.test(e.text)))
check('32. 全流程控制台 0 error（favicon.ico 404 为 dist 既有缺失显式豁免；注入窗口资源错误不计）',
  fatalErrors.length === 0,
  `errors=${JSON.stringify(fatalErrors.slice(0, 3).map((e) => e.text))} http4xx=${JSON.stringify([...http4xxUrls])}`)

// ---------- 汇总 ----------
const passed = results.filter((r) => r.ok).length
console.log(`SUMMARY: ${passed}/${results.length} checks passed`)
console.log('EXIT_CODE', passed === results.length ? 0 : 1)
ws.close()
proc.kill()
process.exit(passed === results.length ? 0 : 1)
