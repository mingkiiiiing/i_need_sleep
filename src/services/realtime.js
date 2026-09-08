// 实时观测轨（observed）统一数据服务 —— 大任务 2/3 全站唯一站点数据源。
//
// 原则（对应实时站点改造验收门槛）：
// - 只访问 observed 轨接口；情景推演内容走 api.js 的 simulated 接口，两轨不得合并。
// - 站点集合完全由最新成功快照决定（79→81 自动变化），页面不得写死站点清单。
// - 60s 内存缓存供多页共用（首页/驾驶舱/站点页/大屏/历史页），避免重复请求；
//   失败不静默回退情景数据，原样抛错进入页面错误态。
// - 展示助手只做格式化/状态映射，不制造接口未返回的数值。

import {
  getRealtimeStatusEnvelope,
  getRealtimeSummaryEnvelope,
  getRealtimeTimelineEnvelope,
  getRealtimeStationsEnvelope,
  getStationObservationsEnvelope,
  getStationQualityEnvelope
} from './api.js'

const CACHE_TTL_MS = 60_000
let statusCache = null
let stationsCache = null
const summaryCaches = new Map()
let timelineCache = null
const qualityCache = new Map()

export async function fetchRealtimeSummary({ force = false, snapshotId } = {}) {
  const key = snapshotId || '__latest__'
  const cached = summaryCaches.get(key)
  if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.value
  const { data } = await getRealtimeSummaryEnvelope(snapshotId)
  summaryCaches.set(key, { at: Date.now(), value: data })
  return data
}

export async function fetchRealtimeTimeline({ force = false } = {}) {
  if (!force && timelineCache && Date.now() - timelineCache.at < CACHE_TTL_MS) return timelineCache.value
  const { data } = await getRealtimeTimelineEnvelope()
  timelineCache = { at: Date.now(), value: data }
  return data
}

export async function fetchRealtimeStatus({ force = false } = {}) {
  if (!force && statusCache && Date.now() - statusCache.at < CACHE_TTL_MS) return statusCache.value
  const { data } = await getRealtimeStatusEnvelope()
  statusCache = { at: Date.now(), value: data }
  return data
}

export async function fetchRealtimeStations({ force = false, province, locationStatus } = {}) {
  const filtered = Boolean(province || locationStatus)
  if (!filtered && !force && stationsCache && Date.now() - stationsCache.at < CACHE_TTL_MS) {
    return stationsCache.value
  }
  const { data } = await getRealtimeStationsEnvelope({ province, locationStatus })
  const stations = Array.isArray(data) ? data : []
  if (!filtered) stationsCache = { at: Date.now(), value: stations }
  return stations
}

export async function fetchStationObservations(stationId, options = {}) {
  const { data } = await getStationObservationsEnvelope(stationId, options)
  return Array.isArray(data) ? data : []
}

export async function fetchStationQuality(stationId, { force = false } = {}) {
  const cached = qualityCache.get(stationId)
  if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.value
  const { data } = await getStationQualityEnvelope(stationId)
  qualityCache.set(stationId, { at: Date.now(), value: data })
  return data
}

export function clearRealtimeCache() {
  statusCache = null
  stationsCache = null
  summaryCaches.clear()
  timelineCache = null
  qualityCache.clear()
}

// 蓝藻筛查着色：与后端阈值及 tokens.css 风险色一致（≥25 --risk-critical #ef4444 /
// ≥10 --risk-medium 口径 / 正常绿；未报数显示中性灰）。JS 侧（canvas/SVG/echarts）读不到
// CSS 变量，故此处直接写 token 色值；改 tokens.css 风险色时必须同步此处。
export function chlaColor(chla) {
  if (chla == null) return '#7d93a8'
  if (chla >= 25) return '#ef4444'
  if (chla >= 10) return '#f5b45d'
  return '#5fd6a4'
}

export function trendChip(trend) {
  if (!trend || trend.delta_pct == null) return { text: '→ 持平', tone: 'flat' }
  if (trend.direction === 'up') return { text: `↑ ${trend.delta_pct}%`, tone: 'up' }
  if (trend.direction === 'down') return { text: `↓ ${Math.abs(trend.delta_pct)}%`, tone: 'down' }
  return { text: '→ 持平', tone: 'flat' }
}

export function healthGradeText(grade) {
  return { excellent: '优 · Excellent', good: '良 · Good', fair: '中 · Fair', poor: '差 · Poor' }[grade] || grade || '—'
}

// ---------- 展示口径（与后端契约一一对应，不新增语义） ----------

export const LOCATION_STATUS_TEXT = {
  verified: '已核验',
  suspicious: '坐标可疑',
  missing: '无坐标'
}

export const FRESHNESS_TEXT = {
  normal: '正常',
  delayed: '数据延迟',
  severely_overdue: '严重过期',
  unavailable: '不可用'
}

export const OBS_STATUS_TEXT = {
  ok: '正常',
  missing: '缺测',
  qc_rejected: '质控不合格',
  parse_failed: '解析失败'
}

// 最新观测卡固定顺序：上游 tbody 11 项指标
export const REALTIME_VARIABLES = [
  { code: 'water_temperature', label: '水温', unit: '℃' },
  { code: 'pH', label: 'pH', unit: '' },
  { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L' },
  { code: 'conductivity', label: '电导率', unit: 'μS/cm' },
  { code: 'turbidity', label: '浊度', unit: 'NTU' },
  { code: 'cod_mn', label: 'CODMn', unit: 'mg/L' },
  { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L' },
  { code: 'total_phosphorus', label: '总磷', unit: 'mg/L' },
  { code: 'total_nitrogen', label: '总氮', unit: 'mg/L' },
  { code: 'chlorophyll_a', label: '叶绿素 a', unit: 'μg/L' },
  { code: 'cyanobacteria_density', label: '藻密度', unit: '万cells/L' }
]

export function variableLabel(code) {
  const found = REALTIME_VARIABLES.find((item) => item.code === code)
  return found ? found.label : code
}

// 站点级数据状态（用于列表排序与状态徽标）：仅由该站真实观测时间推导，
// 不引入任何情景风险分数。阈值与后端新鲜度分带一致（≤6h 正常 / ≤12h 延迟 / >12h 严重过期）。
export function stationDataStatus(station, now = Date.now()) {
  if (!station || !station.latest_observed_at) return 'abnormal'
  if (station.available_variable_count === 0) return 'abnormal'
  const lagH = (now - Date.parse(station.latest_observed_at)) / 3_600_000
  if (!Number.isFinite(lagH)) return 'abnormal'
  if (lagH <= 6) return 'normal'
  if (lagH <= 12) return 'delayed'
  return 'severely_overdue'
}

export const STATION_STATUS_TEXT = {
  normal: '正常',
  delayed: '数据延迟',
  severely_overdue: '严重过期',
  abnormal: '数据异常'
}

export const STATION_STATUS_ORDER = { abnormal: 0, severely_overdue: 1, delayed: 2, normal: 3 }

export function sortStationsByDataStatus(stations) {
  return stations.slice().sort((a, b) => {
    const sa = STATION_STATUS_ORDER[stationDataStatus(a)] ?? 9
    const sb = STATION_STATUS_ORDER[stationDataStatus(b)] ?? 9
    if (sa !== sb) return sa - sb
    return String(a.source_station_name).localeCompare(String(b.source_station_name), 'zh-Hans-CN')
  })
}

// 地图规则：verified 实点；metadata_only 可显示（不附加任何核验标记）；
// suspicious/missing 只出现在列表，绝不生成地图点位（无坐标不造假点）。
export function stationMapPoints(stations, { includeMetadataOnly = true } = {}) {
  return stations
    .filter((s) => {
      const status = s.location && s.location.location_status
      if (status === 'verified') return true
      if (status === 'metadata_only') return includeMetadataOnly
      return false
    })
    .map((s) => {
      const dataStatus = stationDataStatus(s)
      return {
        id: s.id,
        short: s.source_station_name,
        name: s.source_station_name,
        riskClass: dataStatus === 'abnormal' ? 'high' : dataStatus === 'severely_overdue' ? 'high' : dataStatus === 'delayed' ? 'mid' : 'low',
        coord: { lat: s.location.lat, lon: s.location.lon }
      }
    })
}

export function formatStamp(iso) {
  if (!iso) return '—'
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return String(iso)
  return `${m[1]}-${m[2]} ${m[3]} ${m[4]}:${m[5]}`
}

// 观测历史可回看起点（上游抓取自 2026-09-04 起，窗口取 09-01 保证覆盖最早快照）
export const OBS_HISTORY_START = '2026-09-01'

// 本地（北京）当天日期，用于 range 查询 end；toISOString 是 UTC，凌晨会差一天
export function todayLocalDate() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// 指标数值统一展示精度：4 位有效数字并去掉浮点噪声与多余尾零
// （10.030000000000001 → '10.03'，0.0001249558 → '0.000125'，27.9754 → '27.98'）
export function fmtMeasure(v) {
  if (v == null) return null
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return String(Number(n.toPrecision(4)))
}

export function formatLag(h) {
  if (h == null || !Number.isFinite(Number(h))) return '—'
  const hours = Number(h)
  if (hours < 1) return `${Math.round(hours * 60)} 分钟`
  if (hours < 48) return `${hours.toFixed(1)} 小时`
  return `${(hours / 24).toFixed(1)} 天`
}
