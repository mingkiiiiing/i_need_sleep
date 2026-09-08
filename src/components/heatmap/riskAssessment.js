// 多时间尺度水华风险研判 —— 临时规则实现（占位）。
//
// ⚠️ 正式算法尚未由算法组交付：本文件的打分规则是透明的临时口径，
// 输入全部来自 observed 真实接口（/realtime/summary、/rs/manifest、站点观测），
// 不产生任何虚构预测数值；正式算法到位后只需整体替换本文件。
//
// 输出统一为 { score, code, text, caliber, reasons, factors, neutral }：
// - factors：对研判分有正贡献（推高风险）的因子，含原始输入值与得分点数；
//   仅供“规则贡献度排序”展示，不是 SHAP / 注意力 / 敏感性等模型解释。
// - neutral：参与了评估但未推高得分（抑制/中性）的因子，文本呈现。
//
// 输入字段（均来自后端，不做前端二次加工）：
// - summary.means.{chlorophyll_a,total_phosphorus,total_nitrogen,water_temperature} → { value, count }
// - summary.trends.chlorophyll_a → { delta_pct, direction: 'up'|'down'|'flat', prev_value }
// - summary.warnings[] → { chla, band: 'light'|'moderate' }
// - summary.warning_thresholds → { light, moderate }
// - rsManifest.layers[chla].years[].stats.mean → 年度反演均值（历史背景）

function num(v) {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function round1(v) {
  return v == null ? '—' : Number(v).toFixed(1)
}

function chlaBand(chla, thresholds = {}) {
  const light = thresholds.light ?? 10
  const moderate = thresholds.moderate ?? 25
  if (chla == null) return '未报数'
  if (chla >= moderate) return '中度筛查'
  if (chla >= light) return '轻度筛查'
  return '正常'
}

// 趋势间隔披露：后端 trend_baseline.gap_hours 是环比两端的真实观测间隔（小时），
// 快照抓取节奏不规律，文案必须带上间隔，避免被当成固定日趋势。
function gapText(gapHours) {
  const gap = num(gapHours)
  if (gap == null || gap < 0) return ''
  const span = gap >= 24 ? `${(gap / 24).toFixed(1)} 天` : `${gap.toFixed(1)} 小时`
  return `（距上一快照 ${span}）`
}

function trendText(trend, gapHours = null) {
  const gap = gapText(gapHours)
  if (!trend || trend.direction == null) return { text: `无趋势数据${gap}`, tone: 'flat' }
  if (trend.direction === 'up') return { text: `上升 +${round1(trend.delta_pct)}%${gap}`, tone: 'up' }
  if (trend.direction === 'down') return { text: `下降 ${round1(trend.delta_pct)}%${gap}`, tone: 'down' }
  return { text: `持平（${round1(trend.delta_pct)}%）${gap}`, tone: 'flat' }
}

// 近 N 个可用年份的年度反演均值（时间升序取末尾 N 个）
function recentRsMean(rsManifest, n = 5) {
  const years = rsManifest?.layers?.find((l) => l.id === 'chla')?.years || []
  const means = years.slice(-n).map((y) => y.stats?.mean).filter((m) => typeof m === 'number')
  if (!means.length) return null
  return means.reduce((a, b) => a + b, 0) / means.length
}

function allPeriodRsMean(rsManifest) {
  const years = rsManifest?.layers?.find((l) => l.id === 'chla')?.years || []
  const means = years.map((y) => y.stats?.mean).filter((m) => typeof m === 'number')
  if (!means.length) return null
  return means.reduce((a, b) => a + b, 0) / means.length
}

function levelOf(score) {
  if (score >= 70) return { code: 'high', text: '高风险' }
  if (score >= 40) return { code: 'mid', text: '中风险' }
  return { code: 'low', text: '低风险' }
}

function pack(score, reasons, caliber, factors = [], neutral = []) {
  return { score: Math.round(score), ...levelOf(score), caliber, reasons, factors, neutral }
}

const CALIBER_SHORT = '口径：基于 MEE 实时观测按临时规则推导，非数值模型预报；阈值为筛查口径（10/25 μg/L），非监管判定。正式算法接入后替换。'
const CALIBER_TREND = '口径：基于实测趋势与营养盐基线的临时规则研判，非模型预报；营养盐参照湖库通用富营养化区间，非监管判定。'
const CALIBER_LONG = '口径：季节背景 + 36 年遥感年度统计的情景式研判，非预测数值；正式长期模型接入前仅作背景参考。'
const CALIBER_STATION = '口径：站点最新实测值按透明筛查阈值（与全湖规则同源）逐项计分的规则研判；非模型预测。站点级机理+AI 模型预测（v0.1 试点）仅覆盖有叶绿素a 序列的站点，见监测站点页。'

// ---------- 未来 1-3 天（短临）：现状压力 ----------
export function assessShortTerm(summary) {
  if (!summary) return null
  const chla = num(summary.means?.chlorophyll_a?.value)
  const chlaCount = num(summary.means?.chlorophyll_a?.count)
  const warnings = Array.isArray(summary.warnings) ? summary.warnings : []
  const lightN = warnings.filter((w) => w.band === 'light').length
  const moderateN = warnings.filter((w) => w.band === 'moderate').length
  const thresholds = summary.warning_thresholds || {}
  const trend = summary.trends?.chlorophyll_a
  const temp = num(summary.means?.water_temperature?.value)

  let score = 0
  const reasons = []
  const factors = []
  const neutral = []

  if (chla != null) {
    const band = chlaBand(chla, thresholds)
    const points = chla >= 25 ? 35 : chla >= 10 ? 20 : 0
    score += points
    reasons.push(`全湖叶绿素 a 均值 ${round1(chla)} μg/L（${chlaCount ?? '—'} 站报数，${band}）`)
    const item = {
      name: 'chlorophyll_a',
      label: '叶绿素 a',
      value: `${round1(chla)} μg/L`,
      contribution: points,
      note: band
    }
    if (points > 0) factors.push(item)
    else neutral.push({ label: '叶绿素 a', value: `${round1(chla)} μg/L`, note: `${band}档，未推高风险` })
  }
  if (warnings.length) {
    const points = Math.min(lightN * 6 + moderateN * 12, 30)
    score += points
    reasons.push(`蓝藻筛查预警 ${warnings.length} 站（中度 ${moderateN} 站 / 轻度 ${lightN} 站）`)
    factors.push({
      name: 'cyanobacteria_warnings',
      label: '蓝藻筛查预警',
      value: `${warnings.length} 站`,
      contribution: points,
      note: `中度 ${moderateN} / 轻度 ${lightN}`
    })
  } else {
    reasons.push('本快照无蓝藻筛查预警站点')
    neutral.push({ label: '蓝藻筛查预警', value: '0 站', note: '本快照无预警站点' })
  }
  const tr = trendText(trend, summary.trend_baseline?.gap_hours)
  if (trend?.direction === 'up') {
    const points = 12 + Math.min(Math.abs(num(trend.delta_pct) || 0), 8)
    score += points
    factors.push({
      name: 'chla_trend',
      label: '叶绿素趋势',
      value: tr.text,
      contribution: points,
      note: '环比上一快照上升'
    })
  } else if (trend?.direction === 'flat') {
    const points = 6
    score += points
    factors.push({ name: 'chla_trend', label: '叶绿素趋势', value: tr.text, contribution: points, note: '持平延续' })
  } else {
    reasons.push(`叶绿素趋势（环比上一快照）：${tr.text}`)
    neutral.push({ label: '叶绿素趋势', value: tr.text, note: trend?.direction === 'down' ? '下降，未推高风险' : '无趋势数据' })
  }
  if (temp != null) {
    if (temp >= 24) {
      score += 10
      reasons.push(`水温 ${round1(temp)} ℃，处于蓝藻适生区间（≥24 ℃）`)
      factors.push({ name: 'water_temperature', label: '水温', value: `${round1(temp)} ℃`, contribution: 10, note: '蓝藻适生区间（≥24 ℃）' })
    } else {
      reasons.push(`水温 ${round1(temp)} ℃，低于蓝藻适生区间`)
      neutral.push({ label: '水温', value: `${round1(temp)} ℃`, note: '低于蓝藻适生区间（≥24 ℃），未推高' })
    }
  }
  return pack(score, reasons, CALIBER_SHORT, factors, neutral)
}

// ---------- 未来 7-15 天（趋势）：趋势 + 营养盐基线 ----------
export function assessMidTerm(summary) {
  if (!summary) return null
  const chla = num(summary.means?.chlorophyll_a?.value)
  const tp = num(summary.means?.total_phosphorus?.value)
  const tn = num(summary.means?.total_nitrogen?.value)
  const temp = num(summary.means?.water_temperature?.value)
  const trend = summary.trends?.chlorophyll_a
  const thresholds = summary.warning_thresholds || {}

  let score = 0
  const reasons = []
  const factors = []
  const neutral = []

  const tr = trendText(trend, summary.trend_baseline?.gap_hours)
  if (trend?.direction === 'up') {
    const points = 20 + Math.min(Math.abs(num(trend.delta_pct) || 0), 6)
    score += points
    reasons.push(`叶绿素环比趋势：${tr.text}，代表近期动向`)
    factors.push({ name: 'chla_trend', label: '叶绿素趋势', value: tr.text, contribution: points, note: '近期动向向上' })
  } else if (trend?.direction === 'flat') {
    const points = 10
    score += points
    reasons.push(`叶绿素环比趋势：${tr.text}`)
    factors.push({ name: 'chla_trend', label: '叶绿素趋势', value: tr.text, contribution: points, note: '持平延续' })
  } else {
    reasons.push(`叶绿素环比趋势：${tr.text}，代表近期动向`)
    neutral.push({ label: '叶绿素趋势', value: tr.text, note: '未向上，未推高' })
  }

  if (tp != null) {
    const points = tp >= 0.2 ? 25 : tp >= 0.1 ? 15 : 5
    score += points
    reasons.push(`总磷 ${round1(tp)} mg/L、总氮 ${round1(tn)} mg/L（营养盐基线，磷为富营养化限制因子）`)
    factors.push({
      name: 'total_phosphorus',
      label: '总磷',
      value: `${round1(tp)} mg/L`,
      contribution: points,
      note: tp >= 0.2 ? '高位营养盐基线' : tp >= 0.1 ? '中位营养盐基线' : '营养盐基线低'
    })
    neutral.push({
      label: '总氮',
      value: `${round1(tn)} mg/L`,
      note: '与总磷合并计分（磷为限制因子）'
    })
  }
  if (temp != null) {
    const points = temp >= 28 ? 20 : temp >= 24 ? 12 : 4
    score += points
    reasons.push(`水温 ${round1(temp)} ℃${temp >= 24 ? '，蓝藻增殖适生区间' : ''}`)
    const item = { name: 'water_temperature', label: '水温', value: `${round1(temp)} ℃`, contribution: points, note: temp >= 24 ? '蓝藻增殖适生区间' : '低温抑制增殖' }
    if (points >= 12) factors.push(item)
    else neutral.push({ label: '水温', value: item.value, note: '低温期，增殖受抑' })
  }
  if (chla != null) {
    const band = chlaBand(chla, thresholds)
    const points = chla >= 25 ? 20 : chla >= 10 ? 10 : 0
    score += points
    reasons.push(`当前叶绿素水平：${band}档（均值 ${round1(chla)} μg/L）`)
    const item = { name: 'chlorophyll_a', label: '叶绿素 a', value: `${round1(chla)} μg/L`, contribution: points, note: `${band}档` }
    if (points > 0) factors.push(item)
    else neutral.push({ label: '叶绿素 a', value: item.value, note: `${band}档，未推高` })
  }
  return pack(score, reasons, CALIBER_TREND, factors, neutral)
}

// ---------- 未来 30-90 天（长期）：季节背景 + 遥感历史背景 ----------
export function assessLongTerm(summary, rsManifest) {
  if (!summary) return null
  const temp = num(summary.means?.water_temperature?.value)
  const tp = num(summary.means?.total_phosphorus?.value)
  const tn = num(summary.means?.total_nitrogen?.value)
  const warnings = Array.isArray(summary.warnings) ? summary.warnings : []

  let score = 0
  const reasons = []
  const factors = []
  const neutral = []

  if (temp != null) {
    const points = temp >= 24 ? 30 : temp >= 18 ? 18 : 8
    score += points
    const note = temp >= 24 ? '蓝藻风险季节（夏初—秋季）' : temp >= 18 ? '接近蓝藻适生温度' : '低温期，增殖受抑'
    reasons.push(`季节背景：当前水温 ${round1(temp)} ℃，${note}`)
    const item = { name: 'water_temperature', label: '水温（季节）', value: `${round1(temp)} ℃`, contribution: points, note }
    if (points >= 18) factors.push(item)
    else neutral.push({ label: '水温（季节）', value: item.value, note: '低温期，增殖受抑' })
  }
  const recent = recentRsMean(rsManifest)
  const all = allPeriodRsMean(rsManifest)
  if (recent != null && all != null) {
    const ratio = recent / all
    const points = ratio >= 1.1 ? 20 : ratio >= 0.9 ? 12 : 6
    score += points
    reasons.push(`遥感历史背景：近年（1984—2019 末期 5 年）反演均值 ${round1(recent)} μg/L，全期均值 ${round1(all)} μg/L`)
    factors.push({
      name: 'rs_history',
      label: '遥感历史背景',
      value: `近年 ${round1(recent)} / 全期 ${round1(all)} μg/L`,
      contribution: points,
      note: ratio >= 1.1 ? '近年高于全期均值' : '近年与全期持平附近'
    })
  }
  if (tp != null) {
    const points = tp >= 0.2 ? 20 : tp >= 0.1 ? 12 : 4
    score += points
    reasons.push(`营养盐现状：总磷 ${round1(tp)} mg/L / 总氮 ${round1(tn)} mg/L`)
    factors.push({ name: 'total_phosphorus', label: '营养盐现状', value: `TP ${round1(tp)} / TN ${round1(tn)} mg/L`, contribution: points, note: '磷为限制因子' })
  }
  if (warnings.length) {
    const points = Math.min(warnings.length * 2, 10)
    score += points
    reasons.push(`当前筛查预警 ${warnings.length} 站，需关注持续性`)
    factors.push({ name: 'cyanobacteria_warnings', label: '筛查预警', value: `${warnings.length} 站`, contribution: points, note: '关注持续性' })
  } else {
    neutral.push({ label: '筛查预警', value: '0 站', note: '本快照无预警站点' })
  }
  return pack(score, reasons, CALIBER_LONG, factors, neutral)
}

// ---------- 站点级规则研判（站点最新实测逐项计分） ----------
//
// 与全湖规则同源的透明筛查阈值；输入为该站最新快照观测行
// （variable_code / observation_status / value）。流速、光照等 MEE 站点
// 无观测输入，明确列在 missing_inputs，不造假输入。
export function assessStationFactors(rows) {
  const byCode = {}
  ;(rows || []).forEach((row) => {
    const prev = byCode[row.variable_code]
    if (!prev || String(row.observed_at) > String(prev.observed_at)) byCode[row.variable_code] = row
  })
  const val = (code) => {
    const row = byCode[code]
    if (!row || row.observation_status !== 'ok' || row.value == null) return null
    return Number(row.value)
  }

  const chla = val('chlorophyll_a')
  const temp = val('water_temperature')
  const tp = val('total_phosphorus')
  const tn = val('total_nitrogen')
  const nh3 = val('ammonia_nitrogen')
  const doValue = val('dissolved_oxygen')

  let score = 0
  const factors = []
  const neutral = []

  // points>0 → 推高因子（柱状排序）；points=0 → 抑制/中性（文本呈现）；缺测 → 明示未参与
  const addFactor = (name, label, unit, v, points, note) => {
    const text = v != null ? `${round1(v)} ${unit}` : '缺测'
    if (v == null) {
      neutral.push({ label, value: text, note: '缺测，未参与计分' })
      return
    }
    score += points
    const item = { name, label, value: text, contribution: points, note }
    if (points > 0) factors.push(item)
    else neutral.push({ label, value: text, note })
  }
  const chlaNote = chla == null ? '' : chla >= 25 ? '中度筛查（≥25）' : chla >= 10 ? '轻度筛查（10–25）' : '正常（<10），未推高'

  addFactor('chlorophyll_a', '叶绿素 a', 'μg/L', chla,
    chla == null ? 0 : chla >= 25 ? 35 : chla >= 10 ? 20 : 0, chlaNote)
  addFactor('water_temperature', '水温', '℃', temp,
    temp == null ? 0 : temp >= 28 ? 14 : temp >= 24 ? 10 : 0,
    temp != null && temp >= 24 ? '蓝藻适生区间（≥24 ℃）' : '低于适生区间（≥24 ℃），未推高')
  addFactor('total_phosphorus', '总磷', 'mg/L', tp,
    tp == null ? 0 : tp >= 0.2 ? 25 : tp >= 0.1 ? 15 : 0,
    tp != null && tp < 0.1 ? '低于 0.1 mg/L 筛查线，未推高' : '磷为富营养化限制因子')
  addFactor('total_nitrogen', '总氮', 'mg/L', tn,
    tn == null ? 0 : tn >= 1.0 ? 8 : tn >= 0.5 ? 4 : 0,
    tn != null && tn < 0.5 ? '低于 0.5 mg/L 参考线，未推高' : '湖库通用富营养化参考区间')
  addFactor('ammonia_nitrogen', '氨氮', 'mg/L', nh3,
    nh3 == null ? 0 : nh3 >= 1.0 ? 8 : nh3 >= 0.5 ? 4 : 0,
    nh3 != null && nh3 < 0.5 ? '低于 0.5 mg/L 参考线，未推高' : '湖库通用筛查参考区间')
  addFactor('dissolved_oxygen', '溶解氧（低）', 'mg/L', doValue,
    doValue == null ? 0 : doValue <= 3 ? 10 : doValue <= 5 ? 5 : 0,
    doValue != null && doValue > 5 ? '≥5 mg/L，未推高' : '低氧指示有机污染/藻类呼吸压力大')

  const missingInputs = ['流速', '光照', '气象（风速/降雨）'].map((label) => ({ label, note: 'MEE 站点无该观测输入，未参与研判' }))

  return pack(score, [], CALIBER_STATION, factors, [...neutral, ...missingInputs.map((m) => ({ label: m.label, value: '无输入', note: m.note }))])
}
