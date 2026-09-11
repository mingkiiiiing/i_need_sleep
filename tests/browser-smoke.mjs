// 预测页浏览器端到端冒烟验证（五任务重构后的新页面合同）。
//
// 页面合同（2026-09-11 五任务改造后）：
//   - 业务页不出现审计卡/指纹矩阵/门禁明细；技术状态只有一行 prediction-status-tag；
//   - 全湖模式主结果 = 79 站聚合（lake-aggregate-cards），站点模式 = 本站 9 任务输出；
//   - 短期预测（T+1..15）与情景推演（T+30..90）在趋势图上实线/虚线分口；
//   - 覆盖披露三行：预测覆盖 79/79 · 地图覆盖 48/79 · 未上图站给出原因；
//   - 快速切换/前进后退不串站；页面读取零推理（同源校验走快照 ID）。
//
// 运行：npm run test:browser （puppeteer-core + 本机 Edge，需 5173/8000 在线）
import puppeteer from 'puppeteer-core'
import fs from 'node:fs'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const BASE = 'http://127.0.0.1:5173'
const API = 'http://127.0.0.1:8000/api/v1'

const ST_A = 'mee-0145cdb7' // 临江
const ST_B = 'mee-077b367a' // 池家浜水文站
const ST_C = 'mee-0e770fb5' // 朱厍港口

const results = []
const consoleLog = []
const failures = []

function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail })
  if (!ok) failures.push(`${name} :: ${detail}`)
}

async function expected(entityId, metric, horizon) {
  const url = `${API}/model/v3/prediction-snapshot?entity_id=${encodeURIComponent(entityId)}&focus_metric=${metric}`
  const d = (await (await fetch(url)).json()).data
  const h = d.horizons[String(horizon)]
  const key = (h.analysis_focus || {}).result_key
  const box = (h.results || {})[key] || {}
  const u = box.uncertainty || {}
  const agg = h.station_aggregate || {}
  return {
    predictionSnapshotId: d.prediction_snapshot_id,
    value: box.value,
    origin: box.value_origin || '',
    structuralValid: u.structural_valid,
    decisionUsable: Boolean(u.decision_usable),
    comparisonUsable: Boolean((h.entity_diagnostic || {}).comparison_usable),
    lakeChlaMedian: ((agg.metrics || {}).chla || {}).median ?? null,
    lakeProbMedian: ((agg.metrics || {}).probability || {}).median ?? null
  }
}

// 页面读取层：新页面合同的全部可观察事实。
// 注意：不做模块注入读 store——puppeteer 页面上下文里动态 import 拿到的是另一份
// 模块实例，值恒为空；页面↔接口同源性改用 hero 展示数值与接口的展示精度比对。
async function readPage(page) {
  return page.evaluate(() => {
    const q = (r) => document.querySelector(`[data-role="${r}"]`)
    const trend = q('horizon-trend')
    const heroFirstLine = (q('model-primary-result') || {}).innerText?.split('\n')[0]?.trim() || null
    const pctMatch = heroFirstLine ? heroFirstLine.match(/([\d.]+)\s*%/) : null
    return {
      hash: window.location.hash,
      objectName: (document.querySelector('.frp-object-name') || {}).textContent?.trim() || null,
      heroScope: (q('hero-scope-label') || {}).textContent?.trim() || null,
      heroFirstLine,
      heroPct: pctMatch ? Number(pctMatch[1]) : null,
      heroPresent: !!q('model-primary-result'),
      statusTagState: q('prediction-status-tag')?.querySelector('span')?.getAttribute('data-state') || null,
      statusTagText: q('prediction-status-tag')?.innerText?.trim() || null,
      aggCardCount: document.querySelectorAll('[data-role="lake-aggregate-cards"] .frp-card').length,
      stationCardCount: document.querySelectorAll('[data-role="model-results"] .frp-card').length,
      stationVsLake: (q('station-vs-lake') || {}).innerText?.trim() || null,
      prevBanner: !!q('previous-version-banner'),
      retryBtn: !!q('model-retry'),
      trendPresent: !!trend,
      trendCaptions: trend ? Array.from(trend.querySelectorAll('.frp-trend-caption')).map((e) => e.textContent.trim()) : [],
      trendScenarioLine: !!document.querySelector('.frp-trend-line--scenario'),
      trendShortLine: !!document.querySelector('.frp-trend-line:not(.frp-trend-line--scenario)'),
      areaNote: (q('lake-area-note') || {}).innerText?.trim() || null,
      predictionCoverage: (q('prediction-coverage') || {}).textContent?.trim() || null,
      mapCoverage: (q('spatial-coverage') || {}).textContent?.trim() || null,
      notPlottable: (q('not-plottable-note') || {}).textContent?.trim() || null,
      lddNotes: (q('ldd-data-notes') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      driverSources: Array.from(document.querySelectorAll('[data-role="mechanism-factors"] [data-role="driver-source"]')).map((e) => e.textContent.trim()),
      panelText: (document.querySelector('.frp') || {}).innerText?.replace(/\s+/g, ' ').trim() || '',
      overflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth
    }
  })
}

const POSITIVE_COMPARE = /(?<!不)可用于站点(间)?比较/

async function main() {
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--window-size=1600,1000']
  })
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000 })

  page.on('console', (m) => {
    const t = m.type()
    if (t === 'error' || t === 'warning') {
      const loc = m.location() || {}
      consoleLog.push({ type: t, text: m.text().slice(0, 400), url: loc.url || '', line: loc.lineNumber })
    }
  })
  page.on('pageerror', (e) => consoleLog.push({ type: 'pageerror', text: String(e).slice(0, 400) }))
  page.on('response', (r) => {
    if (r.status() >= 500) consoleLog.push({ type: 'http', text: `${r.status()} ${r.url()}` })
  })

  const deep = (q) => `${BASE}/#/heatmap?${q}`
  const settle = (ms = 2600) => new Promise((r) => setTimeout(r, ms))

  // ---------- T1 深链：全湖 risk short（T+1） ----------
  const eLake1 = await expected('lake', 'risk', 1)
  await page.goto(deep('mode=forecast&scale=short&metric=risk'), { waitUntil: 'domcontentloaded' })
  await settle(3200)
  let st = await readPage(page)
  check('T1 深链(全湖/risk) 主结果渲染', st.heroPresent && st.aggCardCount >= 6,
    `hero=${st.heroPresent} 聚合卡=${st.aggCardCount}`)
  check('T1 hero 口径为全湖 79 站聚合', (st.heroScope || '').includes('全湖 · 79 站聚合中位数'), `heroScope=${st.heroScope}`)
  check('T1 全湖模式不显示站点 9 任务卡', st.stationCardCount === 0, `站点卡=${st.stationCardCount}`)
  check('T1 快照就绪时无"上一成功版本"横幅', !st.prevBanner, `prevBanner=${st.prevBanner}`)
  check('T1 时间轴构建后 hash 自动补 stop', /stop=t\d+/.test(st.hash), `hash=${st.hash}`)
  check('T1 一行技术状态标签存在且非"可用于比较"', st.statusTagState && st.statusTagState !== 'usable',
    `state=${st.statusTagState} 文本=${st.statusTagText}`)
  check('T1 门禁 0 PASS 下页面绝不出现正面"可用于站点比较"',
    !POSITIVE_COMPARE.test(st.panelText), st.panelText.slice(0, 160))
  // 页面↔接口同源：hero 展示精度（1 位小数）与接口聚合中位数比对
  check('T1 全湖 hero 数值与接口聚合中位同源',
    st.heroPct != null && Math.abs(st.heroPct - eLake1.lakeProbMedian * 100) < 0.05,
    `页面=${st.heroPct}% 接口=${eLake1.lakeProbMedian * 100}%`)

  // ---------- T1b 四区域同快照绑定（GPT 审计 #9 直接证据） ----------
  // 右侧结果/趋势=快照载荷，地图=站点场端点，驱动=驱动分布端点：
  // 四者的 prediction_snapshot_id 必须完全一致（纯接口级直接证据）。
  const binding = await page.evaluate(async () => {
    const base = '/api/v1'
    const j = async (u) => (await (await fetch(base + u)).json()).data
    const [payload, spatial, driver] = await Promise.all([
      j('/model/v3/prediction-snapshot?focus_metric=risk'),
      j('/model/v3/prediction-spatial-field?horizon_days=1&metric=risk'),
      j('/model/v3/driver-distribution?horizon_days=1')
    ])
    const trendPointIds = Object.values(payload.horizons)
      .map((h) => h.snapshot_source?.prediction_snapshot_id || payload.prediction_snapshot_id)
    return {
      payload: payload.prediction_snapshot_id,
      spatial: spatial.prediction_snapshot_id,
      driver: driver.prediction_snapshot_id,
      trendAllBound: trendPointIds.every((id) => id === payload.prediction_snapshot_id)
    }
  })
  check('T1b 四区域（载荷/趋势/地图/驱动）绑定同一 prediction_snapshot_id',
    binding.payload && binding.payload === binding.spatial && binding.payload === binding.driver && binding.trendAllBound,
    JSON.stringify(binding))

  // ---------- T2 深链：站点 A ----------
  const eA = await expected(ST_A, 'risk', 1)
  await page.goto(deep(`mode=forecast&scale=short&metric=risk&station=${ST_A}&stop=t1`), { waitUntil: 'domcontentloaded' })
  await settle(3200)
  st = await readPage(page)
  check('T2 深链站点 A：URL 带 station', st.hash.includes(`station=${ST_A}`), `hash=${st.hash}`)
  check('T2 深链站点 A：对象名为临江', st.objectName === '临江', `对象=${st.objectName}`)
  check('T2 深链站点 A：显示本站 9 任务卡', st.stationCardCount >= 8, `站点卡=${st.stationCardCount}`)
  check('T2 深链站点 A：本站 vs 全湖中位可见', (st.stationVsLake || '').includes('全湖中位'), st.stationVsLake)
  check('T2 深链站点 A：hero 口径为本站预测', st.heroScope === '本站模型预测', `heroScope=${st.heroScope}`)
  check('T2 深链站点 A：T+1 概率与接口同值（展示精度）',
    st.heroPct != null && Math.abs(st.heroPct - eA.value * 100) < 0.05,
    `页面=${st.heroPct}% 接口=${eA.value * 100}%`)

  // ---------- T3 快速切换站点不串站 B→C→A ----------
  const eC = await expected(ST_C, 'risk', 1)
  await page.evaluate((a, b, c) => {
    window.location.hash = `#/heatmap?mode=forecast&scale=short&metric=risk&station=${b}&stop=t1`
    setTimeout(() => { window.location.hash = `#/heatmap?mode=forecast&scale=short&metric=risk&station=${c}&stop=t1` }, 25)
    setTimeout(() => { window.location.hash = `#/heatmap?mode=forecast&scale=short&metric=risk&station=${a}&stop=t1` }, 50)
  }, ST_A, ST_B, ST_C)
  await settle(2800)
  st = await readPage(page)
  check('T3 快速切换后落在最后目标 A', st.hash.includes(`station=${ST_A}`) && st.objectName === '临江',
    `hash=${st.hash} 对象=${st.objectName}`)
  check('T3 落点 A 的 T+1 值与接口一致（未串站）',
    st.heroPct != null && Math.abs(st.heroPct - eA.value * 100) < 0.05,
    `页面=${st.heroPct}% A=${eA.value * 100}% C=${eC.value * 100}%`)

  // ---------- T4 换指标（chla） ----------
  const eA_chla = await expected(ST_A, 'chla', 1)
  await page.click('[data-role="metric-chla"]')
  await settle(2400)
  st = await readPage(page)
  check('T4 换指标后 hash metric=chla', st.hash.includes('metric=chla'), `hash=${st.hash}`)
  check('T4 hero 显示 μg/L 口径', (st.heroFirstLine || '').includes('μg/L'), `hero=${st.heroFirstLine}`)

  // ---------- T5 长期时效：情景推演分口 ----------
  await page.click('[data-role="metric-risk"]')
  await settle(1000)
  await page.click('[data-role="scale-long"]')
  await settle(2600)
  st = await readPage(page)
  check('T5 hero 口径带"情景推演（未验证）"', (st.heroScope || '').includes('情景推演（未验证）'), `heroScope=${st.heroScope}`)
  check('T5 状态标签为 scenario 态', st.statusTagState === 'scenario', `state=${st.statusTagState} 文本=${st.statusTagText}`)
  check('T5 趋势图短期/情景推演双标注', st.trendCaptions.includes('短期') && st.trendCaptions.includes('情景推演'),
    JSON.stringify(st.trendCaptions))
  check('T5 情景段以独立线型绘制', st.trendScenarioLine, `scenarioLine=${st.trendScenarioLine}`)

  // ---------- T6 返回全湖 ----------
  await page.click('[data-role="scale-short"]')
  await settle(1400)
  st = await readPage(page)
  const backBtn = await page.$('[data-role="back-to-lake"]')
  if (backBtn) {
    await page.click('[data-role="back-to-lake"]')
    await settle(2400)
    st = await readPage(page)
  }
  const eLake = await expected('lake', 'risk', 1)
  check('T6 返回全湖后 URL 不带 station', !/station=mee-/.test(st.hash), `hash=${st.hash}`)
  check('T6 返回全湖后对象名为"全湖"', st.objectName === '全湖', `对象=${st.objectName}`)
  check('T6 返回全湖后聚合卡恢复', st.aggCardCount >= 6 && st.stationCardCount === 0,
    `聚合卡=${st.aggCardCount} 站点卡=${st.stationCardCount}`)
  check('T6 返回全湖后无站点残留行', !st.stationVsLake, st.stationVsLake)
  check('T6 返回全湖后 hero 数值回到聚合中位',
    st.heroPct != null && Math.abs(st.heroPct - eLake.lakeProbMedian * 100) < 0.05,
    `页面=${st.heroPct}% 接口=${eLake.lakeProbMedian * 100}%`)

  // ---------- T6b 下拉选站 B ----------
  await page.click('[data-role="scope-station"]')
  await settle(1000)
  const hasSelect = await page.$('[data-role="station-select"]')
  if (hasSelect) {
    await page.select('[data-role="station-select"]', ST_B)
    await settle(2400)
    st = await readPage(page)
    const eB = await expected(ST_B, 'risk', 1)
    check('T6b 下拉选站后 URL 写入 station', st.hash.includes(`station=${ST_B}`), `hash=${st.hash}`)
    check('T6b 下拉选站后 hero 数值与 B 接口同值',
      st.heroPct != null && Math.abs(st.heroPct - eB.value * 100) < 0.05,
      `页面=${st.heroPct}% 接口=${eB.value * 100}%`)
  } else {
    check('T6b 站点下拉控件存在', false, '未找到 [data-role="station-select"]')
  }

  // ---------- T7 浏览器前进/后退 ----------
  await page.goto(deep(`mode=forecast&scale=short&metric=risk&station=${ST_A}&stop=t1`), { waitUntil: 'domcontentloaded' })
  await settle(2800)
  await page.evaluate((b) => {
    window.location.hash = `#/heatmap?mode=forecast&scale=short&metric=risk&station=${b}&stop=t1`
  }, ST_B)
  await settle(2400)
  await page.goBack()
  await settle(2200)
  st = await readPage(page)
  check('T7 后退：hash 回到 A 且对象名为 A', st.hash.includes(`station=${ST_A}`) && st.objectName === '临江',
    `hash=${st.hash} 对象=${st.objectName}`)
  await page.goForward()
  await settle(2200)
  st = await readPage(page)
  check('T7 前进：hash 回到 B 且对象名为 B', st.hash.includes(`station=${ST_B}`) && st.objectName === '池家浜水文站',
    `hash=${st.hash} 对象=${st.objectName}`)

  // ---------- T8 不确定性标签页：三层合同（期望由后端数据驱动） ----------
  await page.goto(deep(`mode=forecast&scale=short&metric=risk&station=${ST_A}&stop=t1`), { waitUntil: 'domcontentloaded' })
  await settle(2800)
  await page.click('[data-role="result-tab-uncertainty"]')
  await settle(1200)
  const uTab = await page.evaluate(() => {
    const box = document.querySelector('[data-role="result-uncertainty"]')
    const head = box ? box.querySelector('.frp-driver-head strong') : null
    const ring = box ? box.querySelector('[data-role="coverage-ring"]') : null
    return {
      tabPresent: Boolean(box),
      blocked: Boolean(document.querySelector('[data-role="uncertainty-blocked"]')),
      statusKey: head ? head.getAttribute('data-status') : null,
      statusText: head ? head.innerText.trim() : '',
      hasScale: Boolean(document.querySelector('[data-role="interval-scale"]')),
      ringNote: ring ? ring.innerText.replace(/\s+/g, ' ').trim() : '',
      text: box ? box.innerText.replace(/\s+/g, ' ').trim() : ''
    }
  })
  const eU = await expected(ST_A, 'risk', 1)
  check('T8 不确定性标签页已挂载', uTab.tabPresent, '未找到 result-uncertainty')
  check('T8 后端有区间时不得显示"未提供预测区间"', !uTab.blocked, `blocked=${uTab.blocked}`)
  check('T8 结构自洽时不显示"区间可用"字样', uTab.statusText !== '区间可用', `shortTitle=${uTab.statusText}`)
  check('T8 区间刻度尺绘制与后端结构自洽一致', uTab.hasScale === Boolean(eU.structuralValid),
    `尺=${uTab.hasScale} 后端structural_valid=${eU.structuralValid}`)
  // 校准未核算（decision_usable=false）时环必须明示"未核算"，不得表述为已核算/达标
  check('T8 校准未核算时覆盖率环明示"未核算"',
    eU.decisionUsable ? true : (uTab.ringNote.includes('未核算') && !uTab.ringNote.includes('已核算')),
    `覆盖率环=${uTab.ringNote} 后端decision_usable=${eU.decisionUsable}`)

  // ---------- T9 覆盖披露三行 ----------
  await page.click('[data-role="result-tab-overview"]')
  await settle(800)
  st = await readPage(page)
  check('T9 预测覆盖 79/79', (st.predictionCoverage || '').includes('79/79'), st.predictionCoverage)
  check('T9 地图覆盖 48/79', (st.mapCoverage || '').includes('48/79'), st.mapCoverage)
  check('T9 未上图站披露原因（缺可核验坐标）', (st.notPlottable || '').includes('缺少可核验坐标'), st.notPlottable)

  // ---------- T10 驱动因素口径 ----------
  await page.click('[data-role="result-tab-drivers"]')
  await settle(1400)
  st = await readPage(page)
  check('T10 站点驱动每项带来源标注', st.driverSources.length >= 5 && st.driverSources.every((s) => s.trim().length > 0),
    JSON.stringify(st.driverSources.slice(0, 6)))
  check('T10 站点驱动标注含"统一气象代理"', st.driverSources.some((s) => s.includes('统一气象代理')),
    JSON.stringify(st.driverSources))
  check('T10 流速明示缺少有效数据', st.driverSources.some((s) => s.includes('缺少有效数据')),
    JSON.stringify(st.driverSources))
  // 全湖驱动的数据口径披露（切回全湖后页签会重置为总览，需再点一次驱动页签）
  await page.click('[data-role="scope-lake"]')
  await settle(1800)
  await page.click('[data-role="result-tab-drivers"]')
  await settle(1600)
  st = await readPage(page)
  check('T10 全湖驱动数据口径披露温/光/流', (st.lddNotes || '').includes('统一气象代理')
    && (st.lddNotes || '').includes('光照') && (st.lddNotes || '').includes('流速：当前缺少有效数据'),
    st.lddNotes)

  // ---------- T11 面积口径（遥感反演，不入未来趋势） ----------
  await page.click('[data-role="result-tab-overview"]')
  await page.click('[data-role="metric-area"]')
  await settle(2200)
  st = await readPage(page)
  check('T11 面积 hero 口径为遥感反演', (st.heroScope || '').includes('遥感反演'), `heroScope=${st.heroScope}`)
  check('T11 面积不绘制未来趋势线并给出说明', !st.trendPresent && (st.areaNote || '').includes('不随时效外推'),
    `trend=${st.trendPresent} note=${st.areaNote}`)
  await page.click('[data-role="metric-risk"]')
  await settle(1200)

  // ---------- T12 三视口无水平溢出 ----------
  for (const [w, h] of [[1600, 1000], [768, 1024], [390, 844]]) {
    await page.setViewport({ width: w, height: h })
    await settle(900)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    check(`T12 视口 ${w}x${h} 无水平溢出`, overflow <= 1, `overflow=${overflow}px`)
  }
  await page.setViewport({ width: 1600, height: 1000 })

  // ---------- T13 控制台 ----------
  const errors = consoleLog.filter((l) => ['error', 'pageerror', 'requestfailed', 'http'].includes(l.type))
  const warnings = consoleLog.filter((l) => l.type === 'warning')
  check('T13 控制台零错误', errors.length === 0, JSON.stringify(errors.slice(0, 6)))
  check('T13 控制台零警告', warnings.length === 0, JSON.stringify(warnings.slice(0, 6)))

  await browser.close()

  const report = {
    passed: results.filter((r) => r.ok).length,
    total: results.length,
    failures,
    results,
    consoleErrors: errors,
    consoleWarnings: warnings
  }
  fs.writeFileSync(new URL('./browser-smoke-report.json', import.meta.url), JSON.stringify(report, null, 2), 'utf8')
  console.log(`预测页浏览器冒烟：${report.passed}/${report.total} 通过`)
  if (failures.length) {
    console.log('未通过项：')
    failures.forEach((f) => console.log('  - ' + f))
  }
  if (errors.length || warnings.length) {
    console.log('控制台：错误 ' + errors.length + ' 条 / 警告 ' + warnings.length + ' 条')
    consoleLog.slice(0, 20).forEach((l) => console.log(`  [${l.type}] ${l.text}`))
  }
  process.exitCode = failures.length ? 1 : 0
}

main().catch((e) => {
  console.error('SMOKE_FATAL', e && e.stack ? e.stack : e)
  process.exitCode = 2
})
