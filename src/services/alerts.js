// 预警通知服务：/realtime/alerts* 三接口的统一前端入口（右上角组件 + /alerts 页 + 大屏着色共用）。
// 口径与后端一致：chla ≥25 红色告警（moderate）/ ≥10 黄色预警（light）。
// 推送通道未配置时投递记 skipped —— 页面必须如实展示"未发送/未启用"，不得伪装已发送。
import { requestEnvelope } from './api.js'

const CACHE_TTL_MS = 60_000
let overviewCache = null
const historyCaches = new Map()

export async function fetchAlertOverview({ force = false } = {}) {
  if (!force && overviewCache && Date.now() - overviewCache.at < CACHE_TTL_MS) return overviewCache.value
  const { data } = await requestEnvelope('/realtime/alerts/overview')
  overviewCache = { at: Date.now(), value: data }
  return data
}

export async function fetchAlertHistory({ force = false, status = 'all', level } = {}) {
  const key = `${status}|${level || ''}`
  const cached = historyCaches.get(key)
  if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.value
  const query = new URLSearchParams({ status, limit: '500' })
  if (level) query.set('level', level)
  const { data } = await requestEnvelope(`/realtime/alerts?${query.toString()}`)
  const list = Array.isArray(data) ? data : []
  historyCaches.set(key, { at: Date.now(), value: list })
  return list
}

export async function evaluateAlerts() {
  const { data } = await requestEnvelope('/realtime/alerts/evaluate', { method: 'POST' })
  overviewCache = null
  historyCaches.clear()
  return data
}

export function clearAlertCache() {
  overviewCache = null
  historyCaches.clear()
}

export const ALERT_LEVEL_TEXT = {
  light: '黄色预警',
  moderate: '红色告警'
}

export const ALERT_RESOLVE_REASON_TEXT = {
  escalated_to_moderate: '升级为红色告警',
  downgraded_to_light: '降级为黄色预警',
  below_threshold: '指标恢复至阈值以下',
  station_missing: '站点退出最新快照'
}

export const DELIVERY_STATUS_TEXT = {
  sent: '已发送',
  failed: '发送失败',
  skipped: '未发送'
}

export const CHANNEL_TEXT = {
  email: '邮箱',
  sms: '短信',
  none: '推送'
}

export function levelColor(level) {
  return level === 'moderate' ? 'var(--risk-critical, #ff6b6b)' : 'var(--risk-medium, #f5b45d)'
}

export function formatAlertTime(iso) {
  if (!iso) return '—'
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[1]}-${m[2]} ${m[3]} ${m[4]}:${m[5]}` : String(iso)
}
