// 驾驶舱 API 统一入口。开发服务器将 /api 代理到本地 FastAPI。
// VITE_USE_MOCK=true 时强制使用 mock；后端不可用时自动降级，保证演示不中断。
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

async function withFallback(apiCall, mockCall) {
  if (USE_MOCK) return mockCall()
  try {
    return await apiCall()
  } catch (error) {
    console.warn('[API] 后端不可用，已切换至本地 mock：', error.message)
    return mockCall()
  }
}

export function getTimeStages() {
  return withFallback(() => request('/cockpit/time-stages'), mock.fetchTimeStages)
}

export function getPoints() {
  return withFallback(() => request('/cockpit/points'), mock.fetchPoints)
}

export function getPointDetail(id) {
  return withFallback(() => request(`/cockpit/points/${encodeURIComponent(id)}`), () => mock.fetchPointDetail(id))
}

export function getHeatField() {
  return withFallback(() => request('/cockpit/risk-heatmap'), mock.fetchHeatField)
}

export function getEvents() {
  return withFallback(() => request('/cockpit/events'), mock.fetchEvents)
}

export function getAlerts() {
  return withFallback(() => request('/cockpit/alerts'), mock.fetchAlerts)
}

export function alertAction(alertId, action, payload = {}) {
  return withFallback(
    () => request(`/cockpit/alerts/${encodeURIComponent(alertId)}/actions`, { method: 'POST', body: JSON.stringify({ action, ...payload }) }),
    () => mock.fetchAlertAction(alertId, action, payload)
  )
}

export function getRegionSummary() {
  return withFallback(() => request('/cockpit/region-summary'), mock.fetchRegionSummary)
}

export function getPrediction(stationId, targetMetric = 'chlorophyll_a', forecastScale = 'short_term') {
  const horizonDays = { short_term: 3, mid_term: 7, long_term: 30 }[forecastScale] || 3
  return request('/model/predict', {
    method: 'POST',
    body: JSON.stringify({ station_id: stationId, horizon_days: horizonDays, target_metric: targetMetric })
  })
}

export function getExplanation(predictionId) {
  return withFallback(() => request(`/model/explain/${encodeURIComponent(predictionId)}`), () => mock.fetchExplanation(predictionId))
}

export function handleWarning(eventId) {
  return withFallback(() => request('/cockpit/handle-warning', {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId })
  }), () => mock.fetchHandleWarning(eventId))
}

export function getTimeline(startDate, endDate) {
  return withFallback(() => request(`/cockpit/timeline?start=${encodeURIComponent(startDate)}&end=${encodeURIComponent(endDate)}`), () => mock.fetchTimeline(startDate, endDate))
}
