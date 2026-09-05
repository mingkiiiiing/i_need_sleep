<template>
  <div ref="mapContainerRef" class="hm-map" role="application" aria-label="太湖演示风险格网地图"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { cellBounds, cellId, gridDims, GRID_BOUNDS } from './gridCore.js'

const props = defineProps({
  // 当前显示的二维数组：普通档位格网或差值格网（B−A）；null 表示不渲染格网
  grid: { type: Array, default: null },
  // stage | diff：diff 使用差值配色（上升红 / 下降青 / 持平透明）
  renderMode: { type: String, default: 'stage' },
  points: { type: Array, default: () => [] },
  selectedCell: { type: String, default: '' },
  selectedPoint: { type: String, default: '' },
  gridVisible: { type: Boolean, default: true },
  pointsVisible: { type: Boolean, default: true },
  labelsVisible: { type: Boolean, default: true },
  basemap: { type: String, default: 'satellite' }
})

const emit = defineEmits(['select-cell', 'select-point', 'tile-error'])

const mapContainerRef = ref(null)
let map = null
let satelliteLayer = null
let topoLayer = null
let labelsLayer = null
let gridLayer = null
let markers = []
let resizeObserver = null
let tileErrorCount = 0

// 拖拽/瓦片硬边界与 P01/P03 一致（长三角范围，不露白）
const MAP_BOUNDS = [
  [29.3, 118.0],
  [33.1, 122.3]
]
const MAP_CENTER = [(GRID_BOUNDS.south + GRID_BOUNDS.north) / 2, (GRID_BOUNDS.west + GRID_BOUNDS.east) / 2]
const DEFAULT_ZOOM = 11

// 填充配色：低绿 / 中黄 / 高红，边线轻量
const LEVEL_FILL = {
  low: 'rgba(47, 158, 99, 0.40)',
  mid: 'rgba(234, 179, 8, 0.48)',
  high: 'rgba(239, 68, 68, 0.58)'
}
const LEVEL_STROKE = {
  low: 'rgba(47, 158, 99, 0.85)',
  mid: 'rgba(234, 179, 8, 0.9)',
  high: 'rgba(239, 68, 68, 0.95)'
}
// 差值配色（B−A）
const DIFF_ZERO_FILL = 'rgba(148, 163, 184, 0.10)'
const DIFF_ZERO_STROKE = 'rgba(148, 163, 184, 0.35)'

function levelOf(value) {
  return value >= 75 ? 'high' : value >= 45 ? 'mid' : 'low'
}

function diffFill(delta) {
  if (!Number.isFinite(delta) || delta === 0) return DIFF_ZERO_FILL
  const strength = Math.min(0.72, 0.16 + Math.abs(delta) * 0.045)
  return delta > 0 ? `rgba(239, 68, 68, ${strength.toFixed(3)})` : `rgba(56, 189, 248, ${strength.toFixed(3)})`
}

function diffStroke(delta) {
  if (!Number.isFinite(delta) || delta === 0) return DIFF_ZERO_STROKE
  return delta > 0 ? 'rgba(239, 68, 68, 0.85)' : 'rgba(56, 189, 248, 0.85)'
}

function baseStyle(rect) {
  const value = Number.isFinite(rect.hmValue) ? rect.hmValue : 0
  if (props.renderMode === 'diff') {
    return { fillColor: diffFill(value), color: diffStroke(value), fillOpacity: 1, weight: 0.6, opacity: 0.8 }
  }
  return { fillColor: LEVEL_FILL[levelOf(value)], color: LEVEL_STROKE[levelOf(value)], fillOpacity: 1, weight: 0.6, opacity: 0.8 }
}

function createZoneIcon(point, isActive) {
  const root = document.createElement('div')
  root.className = `hm-zone-marker${isActive ? ' is-active' : ''} lv-${point.level || 'low'}`
  const dot = document.createElement('span')
  dot.className = 'hm-zone-dot'
  const label = document.createElement('span')
  label.className = 'hm-zone-label'
  const code = document.createElement('strong')
  code.textContent = point.short || ''
  const name = document.createElement('span')
  name.textContent = point.name || ''
  label.append(code, name)
  root.append(dot, label)
  return L.divIcon({ className: 'hm-zone-wrapper', html: root, iconSize: [0, 0], iconAnchor: [0, 0] })
}

function initMap() {
  if (!mapContainerRef.value || map) return
  map = L.map(mapContainerRef.value, {
    center: MAP_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: true,
    attributionControl: true,
    maxBounds: MAP_BOUNDS,
    maxBoundsViscosity: 1.0,
    scrollWheelZoom: true,
    doubleClickZoom: true,
    boxZoom: false,
    keyboard: false,
    touchZoom: true,
    dragging: true
  })
  map.setView(MAP_CENTER, DEFAULT_ZOOM, { animate: false })

  const tileBounds = L.latLngBounds(MAP_BOUNDS)
  satelliteLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 19, bounds: tileBounds, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' }
  ).addTo(map)
  labelsLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 19, bounds: tileBounds, opacity: 0.85 }
  ).addTo(map)
  topoLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 17, bounds: tileBounds, attribution: '&copy; Esri' }
  )
  attachTileGuards(satelliteLayer)
  attachTileGuards(topoLayer)
  applyBasemap(props.basemap)
  applyLabels(props.labelsVisible)

  addMarkers()
  renderGrid()

  setTimeout(() => map && map.invalidateSize(), 200)
  resizeObserver = new ResizeObserver(() => map && map.invalidateSize())
  resizeObserver.observe(mapContainerRef.value)
}

function attachTileGuards(layer) {
  if (!layer) return
  layer.on('tileload', () => {
    if (tileErrorCount > 0) {
      tileErrorCount = 0
      emit('tile-error', false)
    }
  })
  layer.on('tileerror', () => {
    tileErrorCount += 1
    if (tileErrorCount >= 5) emit('tile-error', true)
  })
}

function retryTiles() {
  if (!map) return
  tileErrorCount = 0
  emit('tile-error', false)
  ;[satelliteLayer, labelsLayer, topoLayer].forEach((layer) => {
    if (layer && map.hasLayer(layer)) {
      map.removeLayer(layer)
      layer.addTo(map)
    }
  })
  map.setView(MAP_CENTER, DEFAULT_ZOOM)
}

function applyBasemap(mode) {
  if (!map) return
  if (mode === 'topo') {
    if (map.hasLayer(satelliteLayer)) map.removeLayer(satelliteLayer)
    if (!map.hasLayer(topoLayer)) map.addLayer(topoLayer)
  } else {
    if (map.hasLayer(topoLayer)) map.removeLayer(topoLayer)
    if (!map.hasLayer(satelliteLayer)) map.addLayer(satelliteLayer)
  }
}

function applyLabels(visible) {
  if (!map || !labelsLayer) return
  if (visible && !map.hasLayer(labelsLayer)) map.addLayer(labelsLayer)
  if (!visible && map.hasLayer(labelsLayer)) map.removeLayer(labelsLayer)
}

function addMarkers() {
  if (!map) return
  markers.forEach(({ marker }) => map.removeLayer(marker))
  markers = []
  props.points.forEach((point) => {
    if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon)) return
    const marker = L.marker([point.lat, point.lon], {
      icon: createZoneIcon(point, point.id === props.selectedPoint),
      zIndexOffset: point.id === props.selectedPoint ? 1000 : 0
    })
    marker.on('click', () => emit('select-point', point.id))
    marker.addTo(map)
    markers.push({ id: point.id, marker })
  })
}

function updateMarkerStates() {
  markers.forEach(({ id, marker }) => {
    const point = props.points.find((p) => p.id === id)
    if (!point) return
    const isActive = id === props.selectedPoint
    marker.setIcon(createZoneIcon(point, isActive))
    marker.setZIndexOffset(isActive ? 1000 : 0)
  })
}

function renderGrid() {
  if (!map) return
  if (gridLayer) {
    map.removeLayer(gridLayer)
    gridLayer = null
  }
  if (!props.gridVisible || !Array.isArray(props.grid) || !props.grid.length) return

  const { rows, cols } = gridDims(props.grid)
  if (!rows || !cols) return
  gridLayer = L.layerGroup()
  for (let r = 0; r < rows; r += 1) {
    const row = props.grid[r]
    if (!Array.isArray(row)) continue
    for (let c = 0; c < cols; c += 1) {
      const value = Number(row[c])
      if (props.renderMode !== 'diff' && !Number.isFinite(value)) continue
      const bounds = cellBounds(r, c, rows, cols)
      const rect = L.rectangle(
        [[bounds.south, bounds.west], [bounds.north, bounds.east]],
        { fillColor: 'rgba(0,0,0,0)', fillOpacity: 1, color: 'rgba(255,255,255,0.4)', weight: 0.6, opacity: 0.8 }
      )
      rect.hmRow = r
      rect.hmCol = c
      rect.hmCellId = cellId(r, c)
      rect.hmValue = value
      rect.setStyle(baseStyle(rect))
      rect.on('click', () => emit('select-cell', { row: r, col: c, id: rect.hmCellId }))
      gridLayer.addLayer(rect)
    }
  }
  gridLayer.addTo(map)
  // 图层入图后元素才存在：补 data-cell 标记并应用选中态
  gridLayer.eachLayer((rect) => {
    const el = rect.getElement && rect.getElement()
    if (el) el.setAttribute('data-cell', rect.hmCellId)
  })
  refreshSelection()
}

function refreshSelection() {
  if (!gridLayer) return
  gridLayer.eachLayer((rect) => {
    const el = rect.getElement && rect.getElement()
    if (!el) return
    const selected = rect.hmCellId === props.selectedCell
    rect.setStyle(selected
      ? { color: '#ffffff', weight: 2.5, opacity: 1 }
      : baseStyle(rect))
    el.classList.toggle('hm-cell-selected', selected)
  })
}

watch(() => props.grid, () => renderGrid())
watch(() => [props.gridVisible, props.renderMode], () => renderGrid())
watch(() => props.selectedCell, () => refreshSelection())
watch(() => props.points, () => addMarkers(), { deep: true })
watch(() => props.selectedPoint, () => updateMarkerStates())
watch(() => props.pointsVisible, (on) => {
  if (!map) return
  if (on) addMarkers()
  else {
    markers.forEach(({ marker }) => map.removeLayer(marker))
    markers = []
  }
})
watch(() => props.labelsVisible, (on) => applyLabels(on))
watch(() => props.basemap, (mode) => applyBasemap(mode))

onMounted(() => initMap())

onBeforeUnmount(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (map) {
    map.remove()
    map = null
  }
})

defineExpose({ retryTiles })
</script>

<style scoped>
.hm-map {
  width: 100%;
  height: 100%;
  min-height: 280px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  position: relative;
  z-index: 0;
}

@media (max-width: 759px) {
  /* Leaflet 缩放按钮默认 30×30，仅在本组件内放大到 ≥44×44，不影响 P01/P03 */
  .hm-map :deep(.leaflet-control-zoom a) {
    box-sizing: border-box;
    width: 44px;
    min-width: 44px;
    height: 44px;
    min-height: 44px;
    line-height: 44px;
  }
}
</style>

<style>
/* ===== P07 地图元素全局样式（hm- 前缀命名空间，不与 P01 lake-marker 冲突） ===== */
.hm-zone-wrapper {
  background: none !important;
  border: none !important;
}
.hm-zone-marker {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  cursor: pointer;
}
.hm-zone-dot {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: var(--risk-low, #22c55e);
  border: 2px solid #fff;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.45);
}
.hm-zone-marker.lv-mid .hm-zone-dot { background: var(--risk-medium, #facc15); }
.hm-zone-marker.lv-high .hm-zone-dot { background: var(--risk-critical, #ef4444); }
.hm-zone-marker.is-active {
  width: 32px;
  height: 32px;
}
.hm-zone-marker.is-active .hm-zone-dot {
  width: 17px;
  height: 17px;
  box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 25%, transparent), 0 2px 8px rgba(0, 0, 0, 0.5);
}
.hm-zone-label {
  position: absolute;
  top: 50%;
  left: calc(100% + 4px);
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 3px 8px;
  border-radius: 7px;
  background: var(--surface-panel-raised, rgba(14, 40, 66, 0.94));
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
  pointer-events: none;
  z-index: 3;
}
.hm-zone-label strong {
  color: var(--text-primary);
  font-size: 10.5px;
  font-family: var(--font-mono);
  letter-spacing: 0.5px;
  line-height: 1.2;
}
.hm-zone-label span {
  color: var(--text-secondary);
  font-size: 9.5px;
  line-height: 1.2;
}
path.hm-cell-selected {
  filter: drop-shadow(0 0 6px rgba(255, 255, 255, 0.75));
}
</style>
