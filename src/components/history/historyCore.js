// P06 历史事件复盘：纯展示逻辑。只做接口已有字段的组织与格式化，
// 不制造任何接口未返回的数值、状态或因果结论。
import { RISK_TEXT } from '../stations/stationDisplay.js'

export const MAX_RANGE_DAYS = 90
// 处置状态能力当前未提供：唯一合法取值，仅用于 URL 契约与禁用控件展示
export const STATUS_UNAVAILABLE = 'unavailable'

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export function isoDateOrNull(value) {
  if (typeof value !== 'string' || !ISO_DATE_RE.test(value)) return null
  const t = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(t) ? value : null
}

export function addDaysIso(iso, days) {
  const t = Date.parse(`${iso}T00:00:00Z`)
  if (!Number.isFinite(t)) return null
  const d = new Date(t + days * 86400000)
  return d.toISOString().slice(0, 10)
}

export function diffDaysIso(a, b) {
  const ta = Date.parse(`${a}T00:00:00Z`)
  const tb = Date.parse(`${b}T00:00:00Z`)
  if (!Number.isFinite(ta) || !Number.isFinite(tb)) return NaN
  return Math.round((tb - ta) / 86400000)
}

// URL 查询参数归一化：非法日期丢弃；start 晚于 end 自动对调；跨度 >90 天整对丢弃。
// status 能力未提供，任何取值都归一化为 unavailable 常量。
export function normalizeQuery(query = {}) {
  let start = isoDateOrNull(query.start)
  let end = isoDateOrNull(query.end)
  if (start && end) {
    if (start > end) [start, end] = [end, start]
    if (diffDaysIso(start, end) > MAX_RANGE_DAYS) [start, end] = [null, null]
  }
  return {
    start: start || '',
    end: end || '',
    type: typeof query.type === 'string' ? query.type : '',
    p: typeof query.p === 'string' ? query.p : '',
    mode: typeof query.mode === 'string' ? query.mode : '',
    status: STATUS_UNAVAILABLE,
    event: typeof query.event === 'string' ? query.event : ''
  }
}

export function rangeError(start, end) {
  if (start && end && start > end) return '开始日期不能晚于结束日期'
  if (start && end && diffDaysIso(start, end) > MAX_RANGE_DAYS) return `查询范围最大 ${MAX_RANGE_DAYS} 天`
  return ''
}

// 事件日期取 occurred_at 的日部分（接口不提供日期字段的事件无法参与日期筛选）
export function eventDateOf(ev) {
  const m = ev && typeof ev.occurred_at === 'string' ? ev.occurred_at.slice(0, 10) : ''
  return isoDateOrNull(m) || ''
}

// 只按相同事件 ID 合并两个事件源；单源独有的记录保留，缺失字段由展示层标“未提供”
export function mergeEvents(basicList, cockpitList) {
  const byId = new Map()
  const pick = (list, key) => {
    ;(Array.isArray(list) ? list : []).forEach((item) => {
      if (!item || typeof item.id !== 'string' || !item.id) return
      const merged = byId.get(item.id) || { id: item.id, sources: [] }
      if (!merged.sources.includes(key)) merged.sources.push(key)
      byId.set(item.id, Object.assign(merged, item))
    })
  }
  pick(basicList, 'events')
  pick(cockpitList, 'cockpit_events')
  return [...byId.values()]
}

export function sortEventsDesc(list) {
  return list.slice().sort((a, b) => {
    const da = eventDateOf(a)
    const db = eventDateOf(b)
    if (da && db && da !== db) return da < db ? 1 : -1
    if (da !== db) return da ? -1 : 1
    const ta = typeof a.time === 'string' ? a.time : ''
    const tb = typeof b.time === 'string' ? b.time : ''
    if (ta !== tb) return ta < tb ? 1 : -1
    return a.id < b.id ? 1 : -1
  })
}

export function filterEvents(list, f) {
  return list.filter((ev) => {
    if (f.type && ev.event_type !== f.type) return false
    if (f.p && ev.spatial_entity_id !== f.p) return false
    if (f.mode && ev.data_mode !== f.mode) return false
    if (f.start || f.end) {
      const d = eventDateOf(ev)
      if (!d) return false
      if (f.start && d < f.start) return false
      if (f.end && d > f.end) return false
    }
    return true
  })
}

// 按日期（倒序）分组；缺日期字段的事件归入“日期未提供”组并排在最前
export function groupByDateDesc(sorted) {
  const groups = []
  const index = new Map()
  sorted.forEach((ev) => {
    const d = eventDateOf(ev)
    const key = d || '未提供日期'
    if (!index.has(key)) {
      const group = { key, label: d || '日期未提供', events: [] }
      index.set(key, group)
      groups.push(group)
    }
    index.get(key).events.push(ev)
  })
  return groups
}

export function severityText(sev) {
  return RISK_TEXT[sev] || ''
}

export function eventTimeLabel(ev) {
  if (typeof ev.occurred_at === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(ev.occurred_at)) {
    return ev.occurred_at.slice(5, 16).replace('T', ' ')
  }
  if (typeof ev.time === 'string' && ev.time) return ev.time
  return ''
}

const EVENT_TYPE_TEXT = { model: '预测运行（演示）' }
export function eventTypeText(type) {
  if (!type) return ''
  return EVENT_TYPE_TEXT[type] || type
}

const STAGE_TEXT = { t1: 'T+1d', t3: 'T+3d', t7: 'T+7d', t15: 'T+15d', t30: 'T+30d' }
export function stageLabelOf(key) {
  if (!key) return ''
  const base = STAGE_TEXT[key] || key
  return key === 't30' ? `${base} · 模拟预演` : `${base} · 演示预测`
}

export function serializeFilters(f, eventId = '') {
  const q = {}
  if (f.start) q.start = f.start
  if (f.end) q.end = f.end
  if (f.type) q.type = f.type
  if (f.p) q.p = f.p
  if (f.mode) q.mode = f.mode
  q.status = STATUS_UNAVAILABLE
  if (eventId) q.event = eventId
  return q
}

// 回放窗口：事件日 -1 天（事件前 24h）至事件日 +2 天（事件后 48h）
export function replayWindow(eventDateIso) {
  if (!eventDateIso) return null
  return { start: addDaysIso(eventDateIso, -1), end: addDaysIso(eventDateIso, 2) }
}

export const REPLAY_FRAME_DEFS = [
  { key: 'before24', label: '事件前24h', offset: -1 },
  { key: 'at', label: '事件时刻', offset: 0 },
  { key: 'after24', label: '事件后24h', offset: 1 },
  { key: 'after48', label: '事件后48h', offset: 2 }
]

// 仅使用接口返回的 risk_level 组装演示回放帧；接口缺某日数据则该帧标记 null
export function buildReplayFrames(timelineData, eventDateIso) {
  const win = replayWindow(eventDateIso)
  if (!win) return []
  const byDate = new Map()
  ;(Array.isArray(timelineData && timelineData.data) ? timelineData.data : []).forEach((row) => {
    if (row && typeof row.date === 'string') byDate.set(row.date, row)
  })
  return REPLAY_FRAME_DEFS.map((def) => {
    const date = addDaysIso(eventDateIso, def.offset)
    const row = byDate.get(date)
    return {
      key: def.key,
      label: def.label,
      date,
      riskLevel: row && typeof row.risk_level === 'string' ? row.risk_level : null
    }
  })
}

// 规划中的三套预案模板：仅静态名称与用途说明，无适配分 / 负责人 / 措施状态
export const PLAN_TEMPLATES = Object.freeze([
  { id: 'intake_protection', name: '取水口保护', note: '面向取水口周边演示分区的巡查与防护模板' },
  { id: 'bay_patrol', name: '重点湖湾加密巡查', note: '面向重点湖湾的加密巡查模板' },
  { id: 'river_mouth_monitor', name: '强降雨后入湖河口加密监测', note: '面向强降雨后入湖河口的加密监测模板' }
])

export const PLAN_CAPABILITY_NOTE = '预案模板待后端接入 · 当前未执行自动匹配 · 无适配分、无负责人、无真实措施状态'
