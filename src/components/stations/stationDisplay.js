// P03 监测站点研判：演示分区展示口径统一入口。
// 只做“展示格式化”，不制造任何接口未返回的数值或状态。

export const GRID_BOUNDS = { south: 30.9, north: 31.48, west: 119.88, east: 120.38 }

// 后端 fixture 只提供 {top,left} 百分比位置（模拟几何），没有经纬度。
// 与 P01 驾驶舱同一套边界映射，保证两页点位一致；经纬度仅用于地图定位，不在页面展示。
export function positionToCoord(position) {
  if (!position) return null
  const top = parseFloat(position.top)
  const left = parseFloat(position.left)
  if (!Number.isFinite(top) || !Number.isFinite(left)) return null
  return {
    lat: GRID_BOUNDS.north - (top / 100) * (GRID_BOUNDS.north - GRID_BOUNDS.south),
    lon: GRID_BOUNDS.west + (left / 100) * (GRID_BOUNDS.east - GRID_BOUNDS.west)
  }
}

export const VARIABLE_LABELS = {
  total_phosphorus: '总磷',
  total_nitrogen: '总氮',
  air_temperature: '气温（代理）',
  water_temperature: '水温',
  chlorophyll_a: '叶绿素 a',
  algae_density: '藻密度',
  wind_speed: '风速',
  precipitation: '降水'
}

export function variableLabel(code) {
  return VARIABLE_LABELS[code] || code
}

export const RISK_TEXT = { high: '高风险', mid: '中风险', low: '低风险' }
export const RISK_ORDER = { high: 0, mid: 1, low: 2 }

export const QUALITY_TEXT = {
  pass: '通过',
  good: '正常',
  warning: '警告',
  suspect: '存疑',
  fail: '异常',
  blocked: '阻塞',
  missing: '缺测'
}

export function qualityText(status) {
  if (status == null || status === '') return '—'
  return QUALITY_TEXT[status] ? `${QUALITY_TEXT[status]}（${status}）` : String(status)
}

export function formatStamp(iso) {
  if (!iso) return '—'
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return String(iso)
  return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`
}

export const STAGE_DAYS = { t1: 1, t3: 3, t7: 7, t15: 15, t30: 30 }
export const STAGE_KEYS = ['t1', 't3', 't7', 't15', 't30']

export function stageDays(key) {
  return STAGE_DAYS[key] || 7
}

export function stageShort(key) {
  const d = STAGE_DAYS[key]
  return d ? `T+${d}` : '—'
}

// 观测值展示：保留接口原始精度，不做单位换算或插值
export function formatValue(value) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return String(n)
}

// 时间窗口（相对数据自身最新观测时间，而非墙钟时间）：
// 演示观测样本基准为 2026-08-21，相对“现在”开窗会全部落空，因此以数据基准为锚。
export function filterByWindow(rows, windowKey) {
  if (!rows.length) return []
  const latest = rows.reduce((acc, r) => {
    const t = Date.parse(r.observed_at)
    return Number.isFinite(t) && t > acc ? t : acc
  }, -Infinity)
  if (!Number.isFinite(latest)) return []
  const span = { '24h': 24 * 3600e3, '7d': 7 * 24 * 3600e3, '30d': 30 * 24 * 3600e3 }[windowKey]
  if (!span) return rows
  return rows.filter((r) => {
    const t = Date.parse(r.observed_at)
    return Number.isFinite(t) && t >= latest - span && t <= latest
  })
}
