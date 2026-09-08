// 多时间尺度水华风险研判 —— 临时规则实现（占位）。
//
// ⚠️ 正式算法尚未由算法组交付：本文件的打分规则是透明的临时口径，
// 输入全部来自 observed 真实接口（/realtime/summary、/rs/manifest），
// 不产生任何虚构预测数值；正式算法到位后只需整体替换本文件。
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

function trendText(trend) {
  if (!trend || trend.direction == null) return { text: '无趋势数据', tone: 'flat' }
  if (trend.direction === 'up') return { text: `上升 +${round1(trend.delta_pct)}%`, tone: 'up' }
  if (trend.direction === 'down') return { text: `下降 ${round1(trend.delta_pct)}%`, tone: 'down' }
  return { text: `持平（${round1(trend.delta_pct)}%）`, tone: 'flat' }
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

function pack(score, reasons, caliber) {
  return { score: Math.round(score), ...levelOf(score), reasons, caliber }
}

const CALIBER_SHORT = '口径：基于 MEE 实时观测按临时规则推导，非数值模型预报；阈值为筛查口径（10/25 μg/L），非监管判定。正式算法接入后替换。'
const CALIBER_TREND = '口径：基于实测趋势与营养盐基线的临时规则研判，非模型预报；营养盐参照湖库通用富营养化区间，非监管判定。'
const CALIBER_LONG = '口径：季节背景 + 36 年遥感年度统计的情景式研判，非预测数值；正式长期模型接入前仅作背景参考。'

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

  if (chla != null) {
    score += chla >= 25 ? 35 : chla >= 10 ? 20 : 0
    reasons.push(`全湖叶绿素 a 均值 ${round1(chla)} μg/L（${chlaCount ?? '—'} 站报数，${chlaBand(chla, thresholds)}）`)
  }
  if (warnings.length) {
    score += Math.min(lightN * 6 + moderateN * 12, 30)
    reasons.push(`蓝藻筛查预警 ${warnings.length} 站（中度 ${moderateN} 站 / 轻度 ${lightN} 站）`)
  } else {
    reasons.push('本快照无蓝藻筛查预警站点')
  }
  const tr = trendText(trend)
  if (trend?.direction === 'up') score += 12 + Math.min(Math.abs(num(trend.delta_pct) || 0), 8)
  else if (trend?.direction === 'flat') score += 6
  reasons.push(`较上一快照叶绿素趋势：${tr.text}`)
  if (temp != null) {
    if (temp >= 24) {
      score += 10
      reasons.push(`水温 ${round1(temp)} ℃，处于蓝藻适生区间（≥24 ℃）`)
    } else {
      reasons.push(`水温 ${round1(temp)} ℃，低于蓝藻适生区间`)
    }
  }
  return pack(score, reasons, CALIBER_SHORT)
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

  const tr = trendText(trend)
  if (trend?.direction === 'up') score += 20 + Math.min(Math.abs(num(trend.delta_pct) || 0), 6)
  else if (trend?.direction === 'flat') score += 10
  reasons.push(`叶绿素环比趋势：${tr.text}（快照间隔约数小时，代表近期动向）`)

  if (tp != null) {
    score += tp >= 0.2 ? 25 : tp >= 0.1 ? 15 : 5
    reasons.push(`总磷 ${round1(tp)} mg/L、总氮 ${round1(tn)} mg/L（营养盐基线，磷为富营养化限制因子）`)
  }
  if (temp != null) {
    score += temp >= 28 ? 20 : temp >= 24 ? 12 : 4
    reasons.push(`水温 ${round1(temp)} ℃${temp >= 24 ? '，蓝藻增殖适生区间' : ''}`)
  }
  if (chla != null) {
    score += chla >= 25 ? 20 : chla >= 10 ? 10 : 0
    reasons.push(`当前叶绿素水平：${chlaBand(chla, thresholds)}档（均值 ${round1(chla)} μg/L）`)
  }
  return pack(score, reasons, CALIBER_TREND)
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

  if (temp != null) {
    score += temp >= 24 ? 30 : temp >= 18 ? 18 : 8
    reasons.push(
      `季节背景：当前水温 ${round1(temp)} ℃，${temp >= 24 ? '处于蓝藻风险季节（夏初—秋季）' : temp >= 18 ? '接近蓝藻适生温度' : '处于低温期，蓝藻增殖受抑'}`
    )
  }
  const recent = recentRsMean(rsManifest)
  const all = allPeriodRsMean(rsManifest)
  if (recent != null && all != null) {
    const ratio = recent / all
    score += ratio >= 1.1 ? 20 : ratio >= 0.9 ? 12 : 6
    reasons.push(`遥感历史背景：近年（1984—2019 末期 5 年）反演均值 ${round1(recent)} μg/L，全期均值 ${round1(all)} μg/L`)
  }
  if (tp != null) {
    score += tp >= 0.2 ? 20 : tp >= 0.1 ? 12 : 4
    reasons.push(`营养盐现状：总磷 ${round1(tp)} mg/L / 总氮 ${round1(tn)} mg/L`)
  }
  if (warnings.length) {
    score += Math.min(warnings.length * 2, 10)
    reasons.push(`当前筛查预警 ${warnings.length} 站，需关注持续性`)
  }
  return pack(score, reasons, CALIBER_LONG)
}
