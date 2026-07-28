// 后端接口适配层（统一入口）


// 阶段一：把能跑通的接口（sites / warnings / overview / map-risk）接到后端，


// 其余字段（forecast/factors/trend/timeline/explainability/intensity 等）由 mock 兜底。


// 网络或后端异常时自动降级到 mock，保证页面不崩溃。


import * as mock from './mock.js'


import { adaptSites, adaptWarnings, adaptHeatField, adaptRegionSummary } from './adapters.js'




// 总开关：true = 全 mock；false = 接后端（带降级）


const USE_MOCK = false




// 后端基础地址（通过 vite proxy 时使用相对路径）


const API_BASE = '/api'




// fetch 封装：自动解包 {code, msg, data}


async function request(path, options = {}) {


  const url = path.startsWith('http') ? path : API_BASE + path


  const res = await fetch(url, {


    headers: { 'Content-Type': 'application/json' },


    ...options


  })


  if (!res.ok) throw new Error('HTTP ' + res.status + ' ' + res.statusText)


  const json = await res.json()


  if (json && typeof json.code === 'number' && json.code !== 200) {


    throw new Error('API error ' + json.code + ': ' + (json.msg || 'unknown'))


  }


  return json && Object.prototype.hasOwnProperty.call(json, 'data') ? json.data : json


}




async function withFallback(primary, fallback) {


  if (USE_MOCK) return fallback()


  try {


    const data = await primary()


    return data


  } catch (err) {


    console.warn('[api] fallback to mock:', err && err.message ? err.message : err)


    return fallback()


  }


}




// -------------- 对外接口 --------------




// 时间档：后端暂无对应接口，前端硬编码（保持原样）


export async function getTimeStages() {


  return mock.fetchTimeStages()


}




// 站点 + 位置：后端 /api/sites 提供基础信息；forecast/factors/trend 等由 mock 兜底


export async function getPoints() {


  return withFallback(


    async () => adaptSites(await request('/sites')),


    mock.fetchPoints


  )


}




// 单站点详情：复用 getPoints 的处理结果


export async function getPointDetail(id) {


  const { pointData } = await getPoints()


  return pointData[id] || (await mock.fetchPointDetail(id))


}




// 风险热力网格：后端 /api/map/risk 经纬度点位 -> 前端 11x19 网格


export async function getHeatField() {


  return withFallback(


    async () => adaptHeatField((await request('/map/risk')).grid_points),


    mock.fetchHeatField


  )


}




// 事件流：后端 /api/warnings -> 前端事件流


export async function getEvents() {


  return withFallback(


    async () => adaptWarnings((await request('/warnings?limit=15')).list),


    mock.fetchEvents


  )


}




// 区域总览：后端 /api/dashboard/overview summary 部分；intensity 等用 mock


export async function getRegionSummary() {


  return withFallback(


    async () => adaptRegionSummary(await request('/dashboard/overview')),


    mock.fetchRegionSummary


  )


}


// 模型预测：后端 /api/predict (POST) — 多模型对比 + 评估指标
export async function getPrediction(stationId, targetMetric = 'chlorophyll_a', forecastScale = 'short_term') {
  return request('/predict', {
    method: 'POST',
    body: JSON.stringify({ station_id: stationId, target_metric: targetMetric, forecast_scale: forecastScale })
  })
}

// 可解释性：后端 /api/explain (POST)
export async function getExplanation(predictionId) {
  return request('/explain', {
    method: 'POST',
    body: JSON.stringify({ prediction_id: predictionId })
  })
}

// 预警处置：后端 /api/warnings/{id}/handle (POST)
export async function handleWarning(warningId) {
  return request(`/warnings/${encodeURIComponent(warningId)}/handle`, { method: 'POST' })
}

// 历史时间轴：后端 /api/timeline?start_date=&end_date=
export async function getTimeline(startDate, endDate) {
  return request(`/timeline?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`)
}
