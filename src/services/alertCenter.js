// 预警与应急预案中心服务：/realtime/alerts/center* 接口的统一前端入口。
// 事件工作流、预案匹配、短信/邮件模拟推送、站内通知（已读状态独立于预警确认）。
// 口径与后端一致：chla ≥25 红色告警（moderate）/ ≥10 黄色预警（light）；
// 站点退出快照记"数据待核实"，不视为指标恢复。
import { requestEnvelope } from './api.js'

const CACHE_TTL_MS = 30_000
let overviewCache = null
let notificationsCache = null
let recordsCache = null

function invalidate() {
  overviewCache = null
  notificationsCache = null
  recordsCache = null
}

export async function fetchCenterOverview({ force = false, type = 'all', status = 'all', search = '' } = {}) {
  if (!force && overviewCache && Date.now() - overviewCache.at < CACHE_TTL_MS) return overviewCache.value
  const query = new URLSearchParams({ type, status, search })
  const { data } = await requestEnvelope(`/realtime/alerts/center?${query.toString()}`)
  overviewCache = { at: Date.now(), value: data }
  return data
}

export async function fetchCenterEvent(eventId, { force = false } = {}) {
  const { data } = await requestEnvelope(`/realtime/alerts/center/events/${eventId}`)
  if (force) invalidate()
  return data
}

export async function postCenterAction(eventId, action, payload = {}) {
  const { data } = await requestEnvelope(`/realtime/alerts/center/events/${eventId}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action, ...payload })
  })
  invalidate()
  return data
}

export async function postCenterPush(eventId, payload) {
  const { data } = await requestEnvelope(`/realtime/alerts/center/events/${eventId}/push`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
  invalidate()
  return data
}

export async function postCenterAdoptPlan(eventId, planId) {
  const { data } = await requestEnvelope(`/realtime/alerts/center/events/${eventId}/plan`, {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId })
  })
  invalidate()
  return data
}

export async function postCenterTaskUpdate(eventId, taskId, payload) {
  const { data } = await requestEnvelope(`/realtime/alerts/center/events/${eventId}/tasks/${taskId}`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
  invalidate()
  return data
}

export async function fetchCenterRecords({ force = false } = {}) {
  if (!force && recordsCache && Date.now() - recordsCache.at < CACHE_TTL_MS) return recordsCache.value
  const { data } = await requestEnvelope('/realtime/alerts/center/records')
  recordsCache = { at: Date.now(), value: data }
  return data
}

export async function fetchCenterNotifications({ force = false, unreadOnly = false } = {}) {
  if (!force && notificationsCache && Date.now() - notificationsCache.at < CACHE_TTL_MS) return notificationsCache.value
  const { data } = await requestEnvelope(`/realtime/alerts/center/notifications?unread_only=${unreadOnly ? 'true' : 'false'}`)
  notificationsCache = { at: Date.now(), value: data }
  return data
}

export async function markNotificationsRead({ ids = null, all = false } = {}) {
  const { data } = await requestEnvelope('/realtime/alerts/center/notifications/read', {
    method: 'POST',
    body: JSON.stringify({ ids, all })
  })
  notificationsCache = null
  return data
}

export async function postCenterRules(payload) {
  const { data } = await requestEnvelope('/realtime/alerts/center/rules', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
  invalidate()
  return data
}

export const EVENT_STATUS_TEXT = {
  pending: '待确认',
  acknowledged: '已确认',
  processing: '处理中',
  review: '待复核',
  closed: '已关闭',
  revoked: '已撤销'
}

export const EVENT_TYPE_TEXT = {
  realtime: '实时',
  predicted: '预测'
}

export const EVIDENCE_STATE_TEXT = {
  valid: '有效',
  recovered: '已恢复',
  unverified: '待核实'
}

export const NOTIFY_TYPE_TEXT = {
  new_event: '新预警',
  escalation: '风险升级',
  recovery: '恢复待复核',
  unverified: '数据待核实',
  process: '处理动态',
  push_failure: '模拟推送失败'
}

export const TASK_STATUS_TEXT = {
  todo: '待开始',
  doing: '进行中',
  done: '已完成'
}

export const PUSH_GROUP_TEXT = {
  monitor: '监测组',
  patrol: '巡查组',
  disposal: '处置组',
  admin: '管理员'
}

export const PUSH_STATUS_TEXT = {
  simulated_success: '模拟成功',
  simulated_failed: '模拟失败'
}

export const RECORD_ACTION_TEXT = {
  confirm: '确认预警',
  assign: '指派',
  start: '开始处置',
  submit_review: '提交复核',
  close: '关闭事件',
  reopen: '重新打开',
  revoke: '撤销事件',
  adopt_plan: '采用预案',
  task: '任务进展',
  simulate_push: '模拟推送',
  escalate: '风险升级',
  recovered: '指标恢复',
  unverified: '数据待核实',
  to_review: '转入待复核',
  evidence: '证据更新',
  import: '历史导入',
  update_rules: '规则更新'
}

// 状态 → 可用动作（与后端 ACTION_TRANSITIONS 对应，前端据此渲染按钮）
export const STATUS_ACTIONS = {
  pending: [
    { action: 'confirm', label: '确认预警', kind: 'primary' },
    { action: 'revoke', label: '撤销', kind: 'ghost', needReason: true }
  ],
  acknowledged: [
    { action: 'assign', label: '指派负责人', kind: 'primary' },
    { action: 'start', label: '开始处置', kind: 'primary' },
    { action: 'revoke', label: '撤销', kind: 'ghost', needReason: true }
  ],
  processing: [
    { action: 'assign', label: '指派负责人', kind: 'ghost' },
    { action: 'submit_review', label: '提交复核', kind: 'primary' },
    { action: 'revoke', label: '撤销', kind: 'ghost', needReason: true }
  ],
  review: [
    { action: 'close', label: '复核通过并关闭', kind: 'primary' },
    { action: 'revoke', label: '退回/撤销', kind: 'ghost', needReason: true }
  ],
  closed: [
    { action: 'reopen', label: '重新打开', kind: 'ghost', needReason: true }
  ],
  revoked: [
    { action: 'reopen', label: '重新打开', kind: 'ghost', needReason: true }
  ]
}

// 处置流程步骤（待确认 → 已确认 → 处理中 → 待复核 → 已关闭）
export const FLOW_STEPS = ['pending', 'acknowledged', 'processing', 'review', 'closed']

export { formatAlertTime } from './alerts.js'
