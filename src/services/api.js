// 驾驶舱 API 统一入口。开发服务器将 /api 代理到本地 FastAPI。
// VITE_USE_MOCK=true 才使用本地 mock；默认不在接口失败时切换另一套数据源，
// 以保证页面全部读取同一份、可追溯的 P0 演示数据。
import * as mock from './mock.js'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

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

// ---------- P03 监测站点研判（demo_zone 演示分区） ----------

export function getSpatialEntities(entityType = 'demo_zone') {
  return requestEnvelope(`/spatial-entities?entity_type=${encodeURIComponent(entityType)}&mode=simulated`)
}

export function getSpatialEntity(entityId) {
  return requestEnvelope(`/spatial-entities/${encodeURIComponent(entityId)}`)
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

async function useConfiguredSource(apiCall, mockCall) {
  if (USE_MOCK) return mockCall()
  return apiCall()
}

export function getTimeStages() {
  return useConfiguredSource(() => request('/cockpit/time-stages'), mock.fetchTimeStages)
}

export function getPoints() {
  return useConfiguredSource(() => request('/cockpit/points'), mock.fetchPoints)
}

export function getPointDetail(id) {
  return useConfiguredSource(() => request(`/cockpit/points/${encodeURIComponent(id)}`), () => mock.fetchPointDetail(id))
}

export function getHeatField() {
  return useConfiguredSource(() => request('/cockpit/risk-heatmap'), mock.fetchHeatField)
}

export function getEvents() {
  return useConfiguredSource(() => request('/cockpit/events'), mock.fetchEvents)
}

export function getRegionSummary() {
  return useConfiguredSource(() => request('/cockpit/region-summary'), mock.fetchRegionSummary)
}

export function getPrediction(stationId, targetMetric = 'chlorophyll_a', forecastScale = 'short_term') {
  const horizonDays = { short_term: 3, mid_term: 7, long_term: 30 }[forecastScale] || 3
  return useConfiguredSource(
    () => request(`/forecasts?spatial_entity_id=${encodeURIComponent(stationId)}&horizon_days=${horizonDays}&target_metric=${encodeURIComponent(targetMetric)}`).then((forecasts) => forecasts[0]),
    mock.fetchPrediction
  )
}

export function getExplanation(predictionId) {
  return useConfiguredSource(
    () => request(`/forecasts/${encodeURIComponent(predictionId)}/explanations`),
    mock.fetchExplanation
  )
}

export function handleWarning(eventId) {
  return useConfiguredSource(
    () => request('/cockpit/handle-warning', {
      method: 'POST',
      body: JSON.stringify({ event_id: eventId })
    }),
    () => mock.fetchHandleWarning(eventId)
  )
}

export function getTimeline(startDate, endDate) {
  return useConfiguredSource(
    () => request(`/cockpit/timeline?start=${encodeURIComponent(startDate)}&end=${encodeURIComponent(endDate)}`),
    () => mock.fetchTimeline(startDate, endDate)
  )
}
