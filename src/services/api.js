// 驾驶舱 API 统一入口。开发服务器将 /api 代理到本地 FastAPI。
// 页面全部读取同一份、可追溯的 P0 情景数据：不做接口失败时的数据源切换，
// 失败一律进入各页面的错误态与重试流程。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  if (!response.ok) throw new Error(`API 请求失败：${response.status}`)
  const body = await response.json()
  if (body.code !== 200) throw new Error(body.message || body.msg || 'API 返回异常')
  return body.data
}

// P03 站点研判需要 meta（data_mode / dataset_version / claim_boundary），
// 不能改变旧 request() 的返回结构（P01 依赖），因此新增独立 envelope 方法。
export class ApiError extends Error {
  constructor(message, status, code) {
    super(message)
    this.status = status
    this.code = code || ''
  }
}

export async function requestEnvelope(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  let body = null
  try {
    body = await response.json()
  } catch {
    if (!response.ok) throw new ApiError(`API 请求失败：${response.status}`, response.status)
    throw new ApiError('API 返回了无法解析的内容', response.status)
  }
  if (!response.ok) {
    const detail = body && body.detail
    const code = (detail && detail.code) || (body.errors && body.errors[0] && body.errors[0].code) || ''
    const message = (detail && detail.message) || body.message || `API 请求失败：${response.status}`
    throw new ApiError(message, response.status, code)
  }
  if (!body || body.code !== 200) {
    throw new ApiError((body && body.message) || 'API 返回异常', response.status)
  }
  return { data: body.data, meta: body.meta || {} }
}

// ---------- 首页：系统能力 / 数据集摘要（观察类契约，meta 驱动身份展示） ----------

export function getSystemCapabilitiesEnvelope() {
  return requestEnvelope('/system/capabilities')
}

export function getDatasetsSummaryEnvelope() {
  return requestEnvelope('/datasets/summary')
}

// ---------- P03 监测站点研判（demo_zone 情景分区） ----------

export function getSpatialEntities(entityType = 'demo_zone') {
  return requestEnvelope(`/spatial-entities?entity_type=${encodeURIComponent(entityType)}&mode=simulated`)
}

// ---------- 实时观测轨（observed；MEE 国控站点，2026-09-06 大任务1/2） ----------
// 双轨隔离：本组函数只访问 observed 轨；页面展示层禁止把两轨数据合并成“真实实时预测”。

export function getRealtimeStatusEnvelope() {
  return requestEnvelope('/realtime/status')
}

export function getRealtimeSummaryEnvelope(snapshotId) {
  const query = snapshotId ? `?snapshot=${encodeURIComponent(snapshotId)}` : ''
  return requestEnvelope(`/realtime/summary${query}`)
}

export function getRealtimeTimelineEnvelope() {
  return requestEnvelope('/realtime/timeline')
}

export function getRealtimeStationsEnvelope({ province, locationStatus } = {}) {
  const query = new URLSearchParams({ mode: 'observed', active: 'latest' })
  if (province) query.set('province', province)
  if (locationStatus) query.set('location_status', locationStatus)
  return requestEnvelope(`/spatial-entities?${query.toString()}`)
}

export function getStationObservationsEnvelope(entityId, { window = 'latest', start, end, variables } = {}) {
  const query = new URLSearchParams({ window })
  if (start) query.set('start', start)
  if (end) query.set('end', end)
  if (variables && variables.length) query.set('variables', variables.join(','))
  return requestEnvelope(`/spatial-entities/${encodeURIComponent(entityId)}/observations?${query.toString()}`)
}

export function getStationQualityEnvelope(entityId) {
  return requestEnvelope(`/spatial-entities/${encodeURIComponent(entityId)}/quality`)
}

export function getEntityObservations(entityId) {
  return requestEnvelope(`/spatial-entities/${encodeURIComponent(entityId)}/observations`)
}

export function getEntityQuality(entityId) {
  return requestEnvelope(`/spatial-entities/${encodeURIComponent(entityId)}/quality`)
}

export function getForecastsEnvelope(entityId, horizonDays) {
  return requestEnvelope(`/forecasts?spatial_entity_id=${encodeURIComponent(entityId)}&horizon_days=${horizonDays}`)
}

export function getExplanationEnvelope(forecastId) {
  return requestEnvelope(`/forecasts/${encodeURIComponent(forecastId)}/explanations`)
}

// ---------- P07 卫星遥感与时空推演（map / capabilities） ----------

export function getMapLayersEnvelope() {
  return requestEnvelope('/map/layers')
}

// 卫星遥感年度图层（THQBCA-V2 反演 PNG + manifest）。
// 静态 PNG 挂在后端根路径 /rs（不经 /api/v1）；API_BASE_URL 为绝对地址时跟随其源。
const API_ROOT = API_BASE_URL.startsWith('http') ? new URL(API_BASE_URL).origin : ''

export function getRsManifestEnvelope() {
  return requestEnvelope('/rs/manifest')
}

export function rsImageUrl(relativePath) {
  return `${API_ROOT}/rs/${relativePath}`
}

export function getForecastCapabilitiesEnvelope() {
  return requestEnvelope('/forecast-capabilities')
}

// ---------- P01 驾驶舱（cockpit 视图接口，旧 request 结构） ----------

export function getTimeStages() {
  return request('/cockpit/time-stages')
}

export function getPoints() {
  return request('/cockpit/points')
}

export function getHeatField() {
  return request('/cockpit/risk-heatmap')
}

export function getEvents() {
  return request('/cockpit/events')
}

export function getRegionSummary() {
  return request('/cockpit/region-summary')
}

export function getExplanation(predictionId) {
  return request(`/forecasts/${encodeURIComponent(predictionId)}/explanations`)
}

export function handleWarning(eventId) {
  return request('/cockpit/handle-warning', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId })
  })
}

export function getTimeline(startDate, endDate) {
  return request(`/cockpit/timeline?start=${encodeURIComponent(startDate)}&end=${encodeURIComponent(endDate)}`)
}
