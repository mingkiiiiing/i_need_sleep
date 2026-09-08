// 历史复盘服务：/history/* 聚合接口的统一前端入口。
// 事件复盘以 event_id 为主关联键；复盘意见与系统证据分离（is_manual_review）。
// 口径与后端一致：事件关闭≠风险解除；模拟推送成功≠真实送达；比例显式分子/分母。
import { requestEnvelope } from './api.js'

export async function fetchHistoryReviews(filters = {}) {
  const query = new URLSearchParams()
  const keys = ['start', 'end', 'type', 'level', 'status', 'station', 'plan_adopted', 'tasks_done', 'push_failed']
  keys.forEach((key) => {
    const value = filters[key]
    if (value && value !== 'all') query.set(key, value)
  })
  const qs = query.toString()
  const { data } = await requestEnvelope(`/history/reviews${qs ? `?${qs}` : ''}`)
  return data
}

export async function fetchHistoryReview(eventId, { force = false } = {}) {
  const { data } = await requestEnvelope(`/history/reviews/${encodeURIComponent(eventId)}`)
  return data
}

export async function fetchHistoryMetrics() {
  const { data } = await requestEnvelope('/history/metrics')
  return data
}

export async function fetchPredictionEvaluations() {
  const { data } = await requestEnvelope('/history/prediction-evaluations')
  return data
}

export async function saveReviewNotes(eventId, fields, editor) {
  const { data } = await requestEnvelope(`/history/reviews/${encodeURIComponent(eventId)}/review-notes`, {
    method: 'PUT',
    body: JSON.stringify({ fields, editor })
  })
  return data
}

// ---------- 时间展示口径：界面统一北京时间（抓取时间/观测时间分别标注来源） ----------

const BJ_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false
})

export function formatBeijing(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const parts = BJ_FORMATTER.formatToParts(d)
  const get = (type) => parts.find((p) => p.type === type)?.value || ''
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`
}

// 图表坐标轴用（北京时间，MM-DD HH:mm）
export function formatBeijingShort(iso) {
  return formatBeijing(iso).slice(5)
}

export function formatDuration(minutes) {
  if (minutes == null || !Number.isFinite(Number(minutes))) return '—'
  const total = Math.max(0, Number(minutes))
  if (total < 1) return '不足 1 分钟'
  if (total < 60) return `${Math.round(total)} 分钟`
  const hours = total / 60
  if (hours < 48) return `${Math.floor(hours)} 小时 ${Math.round(total % 60)} 分`
  return `${Math.floor(hours / 24)} 天 ${Math.round(hours % 24)} 小时`
}

// ---------- 标签映射（与预警中心 alertCenter.js 同口径；先建本地绑定再转发，供下方函数引用） ----------

import {
  EVENT_STATUS_TEXT,
  EVENT_TYPE_TEXT,
  EVIDENCE_STATE_TEXT,
  NOTIFY_TYPE_TEXT,
  PUSH_GROUP_TEXT,
  PUSH_STATUS_TEXT,
  RECORD_ACTION_TEXT,
  TASK_STATUS_TEXT
} from './alertCenter.js'

export { EVENT_STATUS_TEXT, EVENT_TYPE_TEXT, EVIDENCE_STATE_TEXT, NOTIFY_TYPE_TEXT, PUSH_GROUP_TEXT, PUSH_STATUS_TEXT, RECORD_ACTION_TEXT, TASK_STATUS_TEXT }

export const LEVEL_TEXT = {
  light: '黄色预警',
  moderate: '红色告警'
}

// 里程碑节点色调（颜色只表示节点性质；与后端 tone 字段一一对应）
export const TONE_META = {
  evidence: { label: '观测/预测证据', color: '#4da3ff' },
  risk: { label: '风险触发及升级', color: '#f5b45d' },
  human: { label: '人员处理', color: '#39c5cf' },
  plan: { label: '预案与任务', color: '#a78bfa' },
  muted: { label: '待核实/撤销/失败', color: '#8296ab' },
  good: { label: '有效恢复与关闭', color: '#5fd6a4' }
}

export function toneColor(tone) {
  return (TONE_META[tone] || TONE_META.human).color
}

export function evidenceStateText(state) {
  return EVIDENCE_STATE_TEXT[state] || state || '—'
}

export function levelText(level) {
  return LEVEL_TEXT[level] || level || '—'
}
