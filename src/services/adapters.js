// 后端 -> 前端数据适配器
import {
  SITE_ID_MAP, SHORT_LABEL_MAP,
  SEVERITY_TO_CLASS, RISK_DISPLAY
} from './_mapping.js'
import * as mock from './mock.js'

export function adaptSites(backendSites) {
  const pointData = {}
  const pointPositions = {}
  backendSites.forEach((site) => {
    const frontendId = SITE_ID_MAP[site.id]
    if (!frontendId) return
    pointData[frontendId] = mergeSiteFromBackend(site, frontendId)
    pointData[frontendId]._backendId = site.id
    pointPositions[frontendId] = computePosition(site.lat, site.lng)
  })
  const mockPoints = mock.fetchPointsSync()
  Object.entries(mockPoints.pointData).forEach(([fid, pdata]) => {
    if (!pointData[fid]) {
      pointData[fid] = { ...pdata }
      pointPositions[fid] = mockPoints.pointPositions[fid]
    }
  })
  return { pointData, pointPositions }
}

function mergeSiteFromBackend(site, frontendId) {
  const mockData = mock.fetchPointsSync().pointData[frontendId] || {}
  const riskClass = SEVERITY_TO_CLASS[site.risk_level] || 'low'
  return {
    ...mockData,
    id: frontendId,
    name: mockData.name || site.name,
    short: SHORT_LABEL_MAP[frontendId] || frontendId.slice(0, 6).toUpperCase(),
    risk: RISK_DISPLAY[site.risk_level] || '绿色稳定',
    riskClass: riskClass,
    coord: { lon: site.lng, lat: site.lat },
    summary: mockData.summary || ('位于 ' + site.name + '，当前等级 ' + (RISK_DISPLAY[site.risk_level] || '稳定') + '。')
  }
}

function computePosition(lat, lng) {
  const LAT_MIN = 31.20, LAT_MAX = 31.65
  const LNG_MIN = 119.10, LNG_MAX = 119.50
  const left = Math.max(5, Math.min(95, ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * 100))
  const top = Math.max(5, Math.min(95, (1 - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 100))
  return { top: top.toFixed(1) + '%', left: left.toFixed(1) + '%' }
}

export function adaptWarnings(backendWarnings) {
  const severityMap = { high: 'high', medium: 'mid', low: 'low' }
  const stages = ['t1', 't3', 't7', 't15', 't30']
  return backendWarnings.map((w, idx) => {
    const frontendId = SITE_ID_MAP[w.station_id]
    const severity = severityMap[w.risk_level] || 'low'
    return {
      id: w.warning_id,
      time: w.time,
      stageKey: stages[idx % stages.length],
      point: frontendId || w.station_id,
      title: w.risk_level_name + '·' + w.trigger_factor,
      summary: w.station_name + '：' + w.trigger_factor + '，状态 ' + w.status + '。',
      severity: severity
    }
  }).filter((ev) => ev.point && Object.values(SITE_ID_MAP).includes(ev.point))
}

export function adaptHeatField(gridPoints) {
  const COLS = 19, ROWS = 11
  const LAT_MIN = 31.33, LAT_MAX = 31.62
  const LNG_MIN = 120.08, LNG_MAX = 120.42
  const sums = Array.from({ length: ROWS }, () => new Array(COLS).fill(0))
  const counts = Array.from({ length: ROWS }, () => new Array(COLS).fill(0))
  gridPoints.forEach((p) => {
    const col = Math.max(0, Math.min(COLS - 1,
      Math.floor((p.lng - LNG_MIN) / (LNG_MAX - LNG_MIN) * COLS)))
    const row = Math.max(0, Math.min(ROWS - 1,
      Math.floor((LAT_MAX - p.lat) / (LAT_MAX - LAT_MIN) * ROWS)))
    sums[row][col] += (p.risk_value || 0)
    counts[row][col] += 1
  })
  const grid = sums.map((rowArr, r) =>
    rowArr.map((sum, c) => {
      if (counts[r][c] === 0) return 0
      return Math.min(100, Math.round((sum / counts[r][c]) * 100))
    })
  )
  return { t1: grid, t3: grid, t7: grid, t15: grid, t30: grid }
}

export function adaptRegionSummary(backendOverview) {
  const s = backendOverview.summary || {}
  const mockSummary = mock.fetchRegionSummarySync()
  // riskCounts ???????? pointData ?????? totalStations ???
  const points = mock.fetchPointsSync().pointData
  const riskCounts = { high: 0, mid: 0, low: 0 }
  Object.values(points).forEach((p) => {
    if (p && p.riskClass && riskCounts[p.riskClass] !== undefined) {
      riskCounts[p.riskClass]++
    }
  })
  return {
    totalStations: mockSummary.totalStations || Object.keys(points).length,
    riskCounts: riskCounts,
    intensity: mockSummary.intensity || {},
    summary: s,
    trend: backendOverview.trend || [],
    recentWarnings: backendOverview.recent_warnings || []
  }
}
