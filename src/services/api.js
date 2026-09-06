// 驾驶舱 API 统一入口。开发服务器将 /api 代理到本地 FastAPI。
// 页面全部读取同一份、可追溯的 P0 演示数据：不做接口失败时的数据源切换，
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

// ---------- P03 监测站点研判（demo_zone 演示分区） ----------

export function getSpatialEntities(entityType = 'demo_zone') {
  return requestEnvelope(`/spatial-entities?entity_type=${encodeURIComponent(entityType)}&mode=simulated`)
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

export function getEventsEnvelope() {
  return requestEnvelope('/events')
}

// ---------- 第六任务：历史事件复盘（cockpit 事件兼容源 + 回放时间轴，均需 meta） ----------

export function getCockpitEventsEnvelope() {
  return requestEnvelope('/cockpit/events')
}

export function getTimelineEnvelope(start, end) {
  return requestEnvelope(`/cockpit/timeline?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`)
}

// ---------- P07 风险地图与时空推演（map / capabilities / 模拟预警处理） ----------

export function getMapLayersEnvelope() {
  return requestEnvelope('/map/layers')
}

export function getRiskGridEnvelope(horizonDays) {
  return requestEnvelope(`/map/risk-grid?horizon_days=${encodeURIComponent(horizonDays)}`)
}

export function getForecastCapabilitiesEnvelope() {
  return requestEnvelope('/forecast-capabilities')
}

export function postHandleWarningEnvelope(eventId) {
  return requestEnvelope('/cockpit/handle-warning', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId })
  })
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
