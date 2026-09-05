// P07 风险地图纯计算辅助：只做展示换算，不制造接口未返回的数值。
// 风险等级阈值与后端/驾驶舱一致：0–44 低、45–74 中、75–100 高。

export const STAGE_KEYS = ['t1', 't3', 't7', 't15', 't30']
export const STAGE_DAYS = { t1: 1, t3: 3, t7: 7, t15: 15, t30: 30 }

export function stageDays(key) {
  return STAGE_DAYS[key] || 7
}

export function stageShort(key) {
  const d = STAGE_DAYS[key]
  return d ? `T+${d}` : '—'
}

export const RISK_LEVELS = ['high', 'mid', 'low']
export const RISK_TEXT = { high: '高风险', mid: '中风险', low: '低风险' }

export function riskLevel(score) {
  const n = Number(score)
  if (!Number.isFinite(n)) return null
  if (n >= 75) return 'high'
  if (n >= 45) return 'mid'
  return 'low'
}

// 与 P01/P03 相同的演示格网地理映射边界（仅用于界面联调定位，不代表真实像元边界）
export const GRID_BOUNDS = { south: 30.9, north: 31.48, west: 119.88, east: 120.38 }

export function cellId(row, col) {
  return `R${String(row + 1).padStart(2, '0')}-C${String(col + 1).padStart(2, '0')}`
}

// grid[r][c] → 矩形四角。r=0 为最北行，与 cockpit 风险面映射方向一致。
export function cellBounds(row, col, rows, cols) {
  const latSpan = GRID_BOUNDS.north - GRID_BOUNDS.south
  const lonSpan = GRID_BOUNDS.east - GRID_BOUNDS.west
  const north = GRID_BOUNDS.north - (row / rows) * latSpan
  const south = GRID_BOUNDS.north - ((row + 1) / rows) * latSpan
  const west = GRID_BOUNDS.west + (col / cols) * lonSpan
  const east = GRID_BOUNDS.west + ((col + 1) / cols) * lonSpan
  return { north, south, west, east }
}

export function gridDims(grid) {
  const rows = Array.isArray(grid) ? grid.length : 0
  const cols = rows ? grid[0].length : 0
  return { rows, cols }
}

// 展平为有效数值格；value 非有限数的格视为无效（不计入统计，也不上色）
export function flattenCells(grid) {
  const cells = []
  if (!Array.isArray(grid)) return cells
  grid.forEach((row, r) => {
    if (!Array.isArray(row)) return
    row.forEach((value, c) => {
      const n = Number(value)
      if (!Number.isFinite(n)) return
      cells.push({ row: r, col: c, id: cellId(r, c), value: n, level: riskLevel(n) })
    })
  })
  return cells
}

export function gridStats(grid) {
  const cells = flattenCells(grid)
  if (!cells.length) {
    return { valid: 0, high: 0, mid: 0, low: 0, max: null, min: null, avg: null }
  }
  let high = 0
  let mid = 0
  let low = 0
  let max = -Infinity
  let min = Infinity
  let sum = 0
  cells.forEach((cell) => {
    if (cell.level === 'high') high += 1
    else if (cell.level === 'mid') mid += 1
    else low += 1
    if (cell.value > max) max = cell.value
    if (cell.value < min) min = cell.value
    sum += cell.value
  })
  return {
    valid: cells.length,
    high,
    mid,
    low,
    max,
    min,
    avg: sum / cells.length
  }
}

export function topCells(grid, limit = 5) {
  return flattenCells(grid)
    .sort((a, b) => b.value - a.value || a.row - b.row || a.col - b.col)
    .slice(0, limit)
}

export function sharePct(count, total) {
  if (!total) return 0
  return Math.round((count / total) * 100)
}

// 两个演示场景的客户端比较：只基于两个接口返回的二维数组做差。
// 不计算面积、岸线长度、迁移速度或置信区间。
export function diffGrids(gridA, gridB) {
  const a = flattenCells(gridA)
  const b = flattenCells(gridB)
  if (!a.length || a.length !== b.length) return null
  const bIndex = new Map(b.map((cell) => [`${cell.row}:${cell.col}`, cell]))
  let up = 0
  let down = 0
  let same = 0
  let maxDelta = 0
  let maxDeltaCell = null
  const transitions = { 'low->mid': 0, 'mid->high': 0, 'high->mid': 0, 'mid->low': 0 }
  a.forEach((cellA) => {
    const cellB = bIndex.get(`${cellA.row}:${cellA.col}`)
    if (!cellB) return
    const delta = cellB.value - cellA.value
    if (delta > 0) up += 1
    else if (delta < 0) down += 1
    else same += 1
    if (Math.abs(delta) > Math.abs(maxDelta)) {
      maxDelta = delta
      maxDeltaCell = cellA.id
    }
    const key = `${cellA.level}->${cellB.level}`
    if (transitions[key] != null) transitions[key] += 1
  })
  return { up, down, same, maxDelta, maxDeltaCell, transitions, compared: a.length }
}

// 差值格网（B−A）：仅保留两侧均为有效数值的格。
export function buildDiffGrid(gridA, gridB) {
  if (!Array.isArray(gridA) || !Array.isArray(gridB)) return null
  if (gridA.length !== gridB.length) return null
  return gridA.map((row, r) => {
    if (!Array.isArray(row) || !Array.isArray(gridB[r]) || row.length !== gridB[r].length) {
      return row.map(() => null)
    }
    return row.map((value, c) => {
      const a = Number(value)
      const b = Number(gridB[r][c])
      if (!Number.isFinite(a) || !Number.isFinite(b)) return null
      return b - a
    })
  })
}

// 热点位置变化：每个已加载档位的最高分格网 + 高风险格的演示格网中心索引。
// 只是格网索引变化，不是真实迁移轨迹或扩散速度。
export function hotspotTrack(stageEntries) {
  return stageEntries
    .filter((entry) => entry && entry.state === 'ok' && entry.grid)
    .map((entry) => {
      const cells = flattenCells(entry.grid)
      if (!cells.length) return null
      const top = cells.reduce((acc, cur) => (cur.value > acc.value ? cur : acc), cells[0])
      const highCells = cells.filter((cell) => cell.level === 'high')
      let center = null
      if (highCells.length) {
        center = {
          row: highCells.reduce((s, c) => s + c.row, 0) / highCells.length,
          col: highCells.reduce((s, c) => s + c.col, 0) / highCells.length
        }
      }
      return { key: entry.key, label: stageShort(entry.key), top, max: top.value, highCount: highCells.length, center }
    })
    .filter(Boolean)
}
