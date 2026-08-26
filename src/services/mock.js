import {
  pointData,
  pointPositions,
  timeStages,
  eventStream,
  heatGrid,
  regionSummary
} from '../data/points.js'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function simulatedPoint(point) {
  return {
    ...point,
    risk: point.risk?.startsWith('SIMULATED') ? point.risk : `SIMULATED / ${point.risk || '演示风险'}`,
    summary: 'SIMULATED / 演示分区，非真实站点、非实时监测、非决策用途。',
    dataMode: 'simulated',
    datasetVersion: 'FRONTEND-MOCK-V1'
  }
}

function simulatedPointsPayload() {
  return {
    pointData: Object.fromEntries(Object.entries(pointData).map(([id, point]) => [id, simulatedPoint(point)])),
    pointPositions
  }
}

export async function fetchTimeStages() {
  await delay(40)
  return timeStages.map((stage) => ({
    ...stage,
    label: stage.key === 't30' ? '30 天模拟预演' : `${stage.label} 演示`,
    data_mode: 'simulated',
    capability_status: stage.key === 't30' ? 'simulation_only' : 'sample_interface_only'
  }))
}

export async function fetchPoints() {
  await delay(60)
  return simulatedPointsPayload()
}

export async function fetchPointDetail(id) {
  await delay(60)
  return pointData[id] ? simulatedPoint(pointData[id]) : undefined
}

export async function fetchHeatField() {
  await delay(60)
  return heatGrid
}

export async function fetchEvents() {
  await delay(60)
  return eventStream.map((event) => ({
    ...event,
    title: `SIMULATED / ${event.title}`,
    summary: `SIMULATED / ${event.summary}`,
    data_mode: 'simulated'
  }))
}

export async function fetchRegionSummary() {
  await delay(40)
  return regionSummary
}

export function fetchPointsSync() {
  return simulatedPointsPayload()
}

export function fetchEventsSync() {
  return eventStream.map((event) => ({ ...event, data_mode: 'simulated' }))
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

export async function fetchPrediction() {
  await delay(80)
  // P0 has no trained model or real SHAP output. Do not manufacture either in mock mode.
  return null
}

export async function fetchExplanation() {
  await delay(40)
  return null
}

export async function fetchHandleWarning(eventId) {
  await delay(120)
  return {
    event_id: eventId,
    channels: ['platform_simulation'],
    status: 'simulated_dispatched',
    data_mode: 'simulated',
    claim_boundary: 'simulation_only'
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
    const chl = 34 + (i * 7) % 38
    data.push({
      date: d.toISOString().slice(0, 10),
      avg_chlorophyll: chl,
      risk_level: chl >= 65 ? 'high' : chl >= 45 ? 'mid' : 'low',
      data_mode: 'simulated'
    })
  }
  return { start_date: startDate, end_date: endDate, total_days: days, data }
}
