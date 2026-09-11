// 预测页浏览器端到端冒烟验证（五任务重构后的新页面合同）。
//
// 页面合同（2026-09-11 五任务改造后）：
//   - 业务页不出现审计卡/指纹矩阵/门禁明细；技术状态只有一行 prediction-status-tag；
//   - 全湖模式主结果 = 79 站聚合（lake-aggregate-cards），站点模式 = 本站 9 任务输出；
//   - 短期预测（T+1..15）与中长期月度趋势（T+30..90）在趋势图上实线/虚线分口；
//     中长期按真实来源命名（90 天逐站模型 / 30/60 天季节气候态基线），不再写"情景推演·未验证"；
//   - 月度栅格场开关归左栏控制面板；驱动因素逐项标注"逐站 / 全湖"；
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
  if (process.env.SMOKE_VERBOSE) {
    console.error(`[smoke ${String(results.length).padStart(3)}] ${ok ? 'ok  ' : 'FAIL'} ${name}`)
  }
}

async function expected(entityId, metric, horizon, tries = 6) {
  // 快照后台重建期间站点视图会短暂 409/data 为空：指数退避重试，而不是让整轮冒烟崩死
  const url = `${API}/model/v3/prediction-snapshot?entity_id=${encodeURIComponent(entityId)}&focus_metric=${metric}`
  let d = null
  for (let t = 0; t < tries; t++) {
    try {
      const resp = await fetch(url)
      if (resp.ok) {
        const body = (await resp.json()).data
        if (body && body.horizons && body.horizons[String(horizon)]) { d = body; break }
      }
    } catch { /* 网络抖动继续重试 */ }
    await new Promise((r) => setTimeout(r, 4000))
  }
  if (!d) throw new Error(`expected(${entityId}, ${metric}, ${horizon}): 快照暂不可用（重试 ${tries} 次）`)
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
    // 等级范围的给出与否取决于叶绿素 a 源区间是否可决策（2026-09-11 合同收紧）
    chlaUsable: Boolean((((h.results || {}).chla || {}).uncertainty || {}).decision_usable),
    // 该站实测观测里是否有 MEE 水温（决定驱动面板温度的诚实标注形态）
    chlaHasTemp: (((h.scope || {}).observed_fields || [])).includes('wq_water_temp'),
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
      trendResolutionNote: (q('trend-resolution-note') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      areaNote: (q('lake-area-note') || {}).innerText?.trim() || null,
      predictionCoverage: (q('prediction-coverage') || {}).textContent?.trim() || null,
      mapCoverage: (q('spatial-coverage') || {}).textContent?.trim() || null,
      notPlottable: (q('not-plottable-note') || {}).textContent?.trim() || null,
      lddNotes: (q('ldd-data-notes') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      driverSources: Array.from(document.querySelectorAll('[data-role="mechanism-factors"] [data-role="driver-source"]')).map((e) => e.textContent.trim()),
      driverSourceGroups: (q('driver-source-groups') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      lightSource: (document.querySelector('[data-factor="light"] [data-role="driver-source"]') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      tempSource: (document.querySelector('[data-factor="temperature"] [data-role="driver-source"]') || {}).innerText?.replace(/\s+/g, ' ').trim() || null,
      // 逐站 / 全湖 徽标：结构化的分辨率标注，不靠来源长句推断
      driverResolutions: Array.from(document.querySelectorAll('[data-role="mechanism-factors"] [data-role="driver-source"] em'))
        .map((e) => e.getAttribute('data-resolution')),
      // 栅格开关必须落在左栏控制面板内，不再挂标题栏
      rasterToggleInLeftPanel: Boolean(document.querySelector('.hm-left [data-role="raster-toggle"]')),
      rasterToggleInHeader: Boolean(document.querySelector('.hm-title [data-role="raster-toggle"]')),
      panelText: (document.querySelector('.frp') || {}).innerText?.replace(/\s+/g, ' ').trim() || '',
      pageText: document.body.innerText.replace(/\s+/g, ' ').trim(),
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

  // ---------- T5 长期时效：中长期月度趋势分口 ----------
  // 口径已从"情景推演（未验证）"改为按真实来源命名：90 天为逐站模型、
  // 30/60 天为季节气候态基线。两者都有真实来源与留出回测，不得再笼统写成"未验证"。
  await page.click('[data-role="metric-risk"]')
  await settle(1000)
  await page.click('[data-role="scale-long"]')
  await settle(2600)
  st = await readPage(page)
  check('T5 hero 口径为"中长期"', (st.heroScope || '').includes('中长期'), `heroScope=${st.heroScope}`)
  check('T5 hero 口径不再出现"未验证"', !(st.heroScope || '').includes('未验证'), `heroScope=${st.heroScope}`)
  check('T5 状态标签为 longterm 态', st.statusTagState === 'longterm', `state=${st.statusTagState} 文本=${st.statusTagText}`)
  check('T5 中长期口径标签说明来源', /逐站模型|季节气候态|全湖常量模型/.test(st.statusTagText || ''), st.statusTagText)
  check('T5 趋势图虚线分口仍在', st.trendScenarioLine, `scenarioLine=${st.trendScenarioLine}`)
  check('T5 趋势图短期/中长期双标注', st.trendCaptions.includes('短期') && st.trendCaptions.includes('中长期'),
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
  // 双向：后端 decision_usable 为真才允许显示"区间可用"；为假时必须降级。
  // 曾经这条是单向的（一律不得显示"可用"），因为当时所有模型 test_n=0；现在补训协议
  // 切出真实留出测试段，证据成立就该允许"可用"，否则页面会低报自己已经做到的证据。
  check('T8 区间可用结论与后端 decision_usable 一致',
    eU.decisionUsable ? uTab.statusText === '区间可用' : uTab.statusText !== '区间可用',
    `shortTitle=${uTab.statusText} 后端decision_usable=${eU.decisionUsable}`)
  check('T8 区间刻度尺绘制与后端结构自洽一致', uTab.hasScale === Boolean(eU.structuralValid),
    `尺=${uTab.hasScale} 后端structural_valid=${eU.structuralValid}`)
  // 校准未核算（decision_usable=false）时环必须明示"未核算"，不得表述为已核算/达标
  check('T8 校准未核算时覆盖率环明示"未核算"',
    eU.decisionUsable ? true : (uTab.ringNote.includes('未核算') && !uTab.ringNote.includes('已核算')),
    `覆盖率环=${uTab.ringNote} 后端decision_usable=${eU.decisionUsable}`)

  // ---------- T8b 风险等级范围：源区间可决策才给范围，否则必须阻断并说明原因 ----------
  // 默认焦点指标是风险等级，它没有自己的数值区间，等级范围由叶绿素 a 的区间映射而来。
  // 2026-09-11 合同收紧后：T+1 叶绿素区间留出覆盖率 80.30% < 88% 验收线 → 不给范围，
  // 页面必须渲染 band-range-blocked 并写明原因，不得留空态；T+30 季节基线源区间
  // 覆盖率 92.42% 达标 → 必须给出三档等级范围。
  await page.click('[data-role="result-tab-uncertainty"]')
  await settle(1400)
  const uDerived = await page.evaluate(() => {
    const box = document.querySelector('[data-role="result-uncertainty"]')
    const band = document.querySelector('[data-role="derived-band-range"]')
    const bandHead = document.querySelector('[data-role="risk-band-range-head"] strong')
    const blockedBox = document.querySelector('[data-role="band-range-blocked"]')
    return {
      blocked: Boolean(document.querySelector('[data-role="uncertainty-blocked"]')),
      bandPresent: Boolean(band),
      bandText: band ? band.innerText.replace(/\s+/g, ' ').trim() : '',
      bandStatus: bandHead ? bandHead.innerText.trim() : null,
      bandBlocked: Boolean(blockedBox),
      bandBlockedReason: blockedBox ? blockedBox.innerText.replace(/\s+/g, ' ').trim() : '',
      statusKey: (box?.querySelector('.frp-driver-head strong') || {}).getAttribute?.('data-status') || null
    }
  })
  const eRisk = await expected(ST_A, 'risk', 1)
  check('T8b 焦点区间不是空态', !uDerived.blocked, `blocked=${uDerived.blocked}`)
  check('T8b 等级范围与源区间可决策状态一致（不可决策→阻断并给原因）',
    eRisk.chlaUsable
      ? uDerived.bandPresent
      : (uDerived.bandBlocked && uDerived.bandBlockedReason.length > 0 && !uDerived.bandPresent),
    `chlaUsable=${eRisk.chlaUsable} band=${uDerived.bandPresent} blocked=${uDerived.bandBlocked} ` +
    `reason=${uDerived.bandBlockedReason.slice(0, 70)}`)
  check('T8b 后端 decision_usable 与页面结论一致',
    !eRisk.decisionUsable || uDerived.statusKey === 'usable',
    `后端=${eRisk.decisionUsable} 页面=${uDerived.statusKey}`)
  // T+30（中长期档）：季节基线 v3 三段回测后，独立测试覆盖率低于验收线的时效同样阻断；
  // 断言数据驱动——源区间可决策必须给三档范围，不可决策必须渲染阻断原因，不允许空态。
  await page.goto(deep(`mode=forecast&scale=long&metric=risk&station=${ST_A}&stop=t30`), { waitUntil: 'domcontentloaded' })
  await settle(1800)
  await page.click('[data-role="result-tab-uncertainty"]')
  await settle(1400)
  const uBand30 = await page.evaluate(() => {
    const band = document.querySelector('[data-role="derived-band-range"]')
    const bandHead = document.querySelector('[data-role="risk-band-range-head"] strong')
    const blockedBox = document.querySelector('[data-role="band-range-blocked"]')
    return {
      bandPresent: Boolean(band),
      bandText: band ? band.innerText.replace(/\s+/g, ' ').trim() : '',
      bandStatus: bandHead ? bandHead.innerText.trim() : null,
      bandBlocked: Boolean(blockedBox),
      bandBlockedReason: blockedBox ? blockedBox.innerText.replace(/\s+/g, ' ').trim() : ''
    }
  })
  const eBand30 = await expected(ST_A, 'risk', 30)
  check('T8b T+30 等级范围与源区间可决策状态一致',
    eBand30.chlaUsable
      ? uBand30.bandPresent
      : (uBand30.bandBlocked && uBand30.bandBlockedReason.length > 0 && !uBand30.bandPresent),
    `chlaUsable=${eBand30.chlaUsable} band=${uBand30.bandPresent} blocked=${uBand30.bandBlocked} ` +
    `reason=${uBand30.bandBlockedReason.slice(0, 70)}`)
  if (eBand30.chlaUsable) {
    check('T8b T+30 等级范围给出三档结论', /无风险|低|中|高|严重/.test(uBand30.bandText) && uBand30.bandText.length > 0,
      uBand30.bandText)
    check('T8b T+30 等级范围状态不与"区间无效"混淆', uBand30.bandStatus !== '区间无效', `bandStatus=${uBand30.bandStatus}`)
  }
  // 回到 T+1 短临态，保证下游 T9/T10 的前置状态不变。
  await page.goto(deep(`mode=forecast&scale=short&metric=risk&station=${ST_A}&stop=t1`), { waitUntil: 'domcontentloaded' })
  await settle(1800)

  // ---------- T9 覆盖披露三行 ----------
  await page.click('[data-role="result-tab-overview"]')
  await settle(800)
  st = await readPage(page)
  // 站点分母动态化（审计整改）：目录 79 站、当轮活跃可能只有 78，断言读 API 实际口径
  {
    const statusResp = await (await fetch(`${API}/model/v3/prediction-status`)).json()
    const stb = (statusResp.data || {}).stations || {}
    const expectCoverage = `${stb.done}/${stb.total}`
    check('T9 预测覆盖与 API 实际口径一致（动态分母）',
      (st.predictionCoverage || '').includes(expectCoverage),
      `页面=${st.predictionCoverage} API=${expectCoverage}`)
  }
  check('T9 地图覆盖 48/79', (st.mapCoverage || '').includes('48/79'), st.mapCoverage)
  check('T9 未上图站披露原因（缺可核验坐标）', (st.notPlottable || '').includes('缺少可核验坐标'), st.notPlottable)

  // ---------- T10 驱动因素口径 ----------
  await page.click('[data-role="result-tab-drivers"]')
  await settle(1400)
  st = await readPage(page)
  check('T10 站点驱动每项带来源标注', st.driverSources.length >= 5 && st.driverSources.every((s) => s.trim().length > 0),
    JSON.stringify(st.driverSources.slice(0, 6)))
  // 温度/营养盐来自本站 MEE 实测 → 逐站；光照/气温来自单一气象网格 → 全湖，物理上无站间差异。
  // 这两类必须在界面上可区分，否则用户会把"全湖同值"读成"站点数据没更新"。
  // 温度标注必须与该站真实观测状态一致：MEE 水温在报 → "本站实测·MEE 水温"；
  // 本周期缺测 → 诚实回退 ERA5 网格并披露"全湖同一网格"，绝不允许把网格值标成"本站实测"。
  {
    const eSta = await expected(ST_A, 'risk', 1)
    const src = st.tempSource || ''
    const okTemp = eSta.chlaHasTemp
      ? (src.includes('本站实测') && src.includes('水温'))
      : (/网格|气候态/.test(src) && !src.includes('本站实测'))
    check('T10 温度来源标注与本站观测一致（缺测时诚实回退网格）', okTemp,
      `observed_temp=${eSta.chlaHasTemp} 标注=${src}`)
  }
  // 光照来自单一气象网格：必须标为网格/气候态，且不得被标成本站实测；
  // 其适合度恒为 1.0 是公式上界，界面须写明"已取到上限"而不是让人读成"光照理想"。
  check('T10 光照标注为网格/气候态且非本站实测',
    /网格|气候态/.test(st.lightSource || '') && !(st.lightSource || '').includes('本站实测'),
    st.lightSource)
  check('T10 光照适合度取到上界时明示', (st.lightSource || '').includes('已取到上限'), st.lightSource)
  check('T10 驱动来源分组披露逐站与全湖', (st.driverSourceGroups || '').includes('逐站')
    && (st.driverSourceGroups || '').includes('全湖同值'), st.driverSourceGroups)
  check('T10 逐站/全湖徽标成对出现', st.driverResolutions.includes('station') && st.driverResolutions.includes('lake'),
    JSON.stringify(st.driverResolutions))
  check('T10 流速明示不可用', st.driverSources.some((s) => s.includes('不可用')),
    JSON.stringify(st.driverSources))
  // 全湖驱动的数据口径披露（切回全湖后页签会重置为总览，需再点一次驱动页签）
  await page.click('[data-role="scope-lake"]')
  await settle(1800)
  await page.click('[data-role="result-tab-drivers"]')
  await settle(1600)
  st = await readPage(page)
  // 温度已改为逐站实测水温，不再出现在"无站间差异"清单里；光照/流速仍必须如实披露。
  check('T10 全湖驱动数据口径披露光/流', (st.lddNotes || '').includes('光照')
    && /气象网格/.test(st.lddNotes || '') && (st.lddNotes || '').includes('流速：当前缺少有效数据'),
    st.lddNotes)
  check('T10 全湖驱动不再把温度说成无站间差异', !/温度[^；]*同值/.test(st.lddNotes || ''), st.lddNotes)

  // ---------- T10b 图层控件归属与研发口径文案 ----------
  await page.click('[data-role="scope-lake"]')
  await settle(1600)
  st = await readPage(page)
  check('T10b 月度栅格场开关位于左栏', st.rasterToggleInLeftPanel, `left=${st.rasterToggleInLeftPanel}`)
  check('T10b 月度栅格场开关不在标题栏', !st.rasterToggleInHeader, `header=${st.rasterToggleInHeader}`)
  check('T10b 页面不再出现"仅供研发观察"', !(st.pageText || '').includes('仅供研发观察'), '仍出现研发口径文案')
  check('T10b 页面不再出现"情景推演（未验证）"', !(st.pageText || '').includes('情景推演（未验证）'), '仍出现未验证口径')
  check('T10b 页面不再出现"该任务时效无门禁评估记录"', !(st.pageText || '').includes('无门禁评估记录'), '仍出现门禁缺失文案')

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
  // 门禁只看交付物自身（本机前端/后端）产生的错误；外部第三方资源（如 ArcGIS 底图瓦片
  // server.arcgisonline.com）的可达性不受交付物控制，网络抖动导致的加载失败单列为外部
  // 噪音——不作为门禁失败，但在报告中如实披露数量，便于人工判断当时网络状况。
  const EXTERNAL_HOST = /(^|\.)arcgisonline\.com$|(^|\.)arcgis\.com$/
  const isInternalError = (l) => {
    if (!l.url) return true
    try {
      return !EXTERNAL_HOST.test(new URL(l.url).hostname)
    } catch {
      return true
    }
  }
  const allErrors = consoleLog.filter((l) => ['error', 'pageerror', 'requestfailed', 'http'].includes(l.type))
  const errors = allErrors.filter(isInternalError)
  const externalErrors = allErrors.filter((l) => !isInternalError(l))
  const warnings = consoleLog.filter((l) => l.type === 'warning')
  check('T13 控制台零错误', errors.length === 0, JSON.stringify(errors.slice(0, 6)))
  check('T13 外部第三方资源错误单列披露（不阻塞门禁）', true,
    `external=${externalErrors.length} ${JSON.stringify(externalErrors.slice(0, 2))}`)
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
