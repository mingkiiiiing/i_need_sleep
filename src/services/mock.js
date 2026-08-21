import {
  pointData,
  pointPositions,
  timeStages,
  eventStream,
  heatGrid,
  regionSummary
} from '../data/points.js'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function fetchTimeStages() {
  await delay(40)
  return timeStages
}

export async function fetchPoints() {
  await delay(60)
  return { pointData, pointPositions }
}

export async function fetchPointDetail(id) {
  await delay(60)
  return pointData[id]
}

export async function fetchHeatField() {
  await delay(60)
  return heatGrid
}

export async function fetchEvents() {
  await delay(60)
  return eventStream
}

export async function fetchRegionSummary() {
  await delay(40)
  return regionSummary
}

export function fetchPointsSync() {
  return { pointData, pointPositions }
}

export function fetchEventsSync() {
  return eventStream
}

export function fetchHeatFieldSync() {
  return heatGrid
}

export function fetchRegionSummarySync() {
  return regionSummary
}

export function fetchTimeStagesSync() {
  return timeStages
}

export async function fetchExplanation(predictionId) {
  await delay(80)
  return {
    prediction_id: predictionId,
    interpretation: '融合模型综合叶绿素a、总磷、水温等因子研判，当前站点藻华风险处于中高位区间，主要驱动因子为水温偏高与营养盐浓度上升。',
    confidence_interval: { lower: 58, upper: 82 },
    feature_importance: [
      { name: '叶绿素a', value: 0.38 },
      { name: '总磷', value: 0.26 },
      { name: '水温', value: 0.21 },
      { name: '溶解氧', value: 0.09 },
      { name: 'pH', value: 0.06 }
    ],
    sensitivity_curve: [
      { t: 0, v: 42 }, { t: 1, v: 46 }, { t: 2, v: 51 },
      { t: 3, v: 58 }, { t: 5, v: 67 }, { t: 7, v: 72 },
      { t: 10, v: 68 }, { t: 14, v: 61 }, { t: 21, v: 53 },
      { t: 30, v: 47 }
    ]
  }
}

export async function fetchHandleWarning(eventId) {
  await delay(120)
  return {
    event_id: eventId,
    pushed_at: new Date().toLocaleString('zh-CN'),
    channels: ['短信', '邮件', '平台通知'],
    status: '已推送'
  }
}

export async function fetchTimeline(startDate, endDate) {
  await delay(100)
  const start = new Date(startDate)
  const end = new Date(endDate)
  const days = Math.max(1, Math.round((end - start) / 86400000) + 1)
  const data = []
  for (let i = 0; i < days; i++) {
    const d = new Date(start)
    d.setDate(d.getDate() + i)
    const chl = 30 + Math.round(Math.random() * 60)
    data.push({
      date: d.toISOString().slice(0, 10),
      avg_chlorophyll: chl,
      risk_level: chl >= 70 ? 'high' : chl >= 45 ? 'mid' : 'low'
    })
  }
  return { start_date: startDate, end_date: endDate, total_days: days, data }
}
