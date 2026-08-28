<template>
  <section class="panel map-panel">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">LAKE TWIN MAP &middot; {{ activeLayer === 'heat' ? 'RISK FIELD' : activeLayer === 'topo' ? 'TOPOGRAPHY' : 'SATELLITE' }}</p>
        <h2>{{ title }}</h2>
      </div>
      <div class="map-controls">
        <div class="layer-switcher" role="group" aria-label="地图图层">
          <button v-if="hasHeatField" type="button" :class="{ active: activeLayer === 'heat' }" @click="switchLayer('heat')">风险热力</button>
          <button type="button" :class="{ active: activeLayer === 'satellite' }" @click="switchLayer('satellite')">卫星影像</button>
          <button type="button" :class="{ active: activeLayer === 'topo' }" @click="switchLayer('topo')">地形地图</button>
        </div>
      </div>
    </header>

    <div ref="mapContainerRef" class="leaflet-map-container"></div>

    <footer class="map-footer">
      <div class="legend-row">
        <span><span class="legend-dot high"></span>红色预警</span>
        <span><span class="legend-dot mid"></span>橙色关注</span>
        <span><span class="legend-dot low"></span>绿色稳定</span>
        <span v-if="hasHeatField" class="heat-ramp" aria-label="风险值由低到高"><i></i><b>低</b><b>高</b></span>
      </div>
      <span class="legend-row">点击点位查看详情 &middot; 当前档位 {{ stageLabel }}</span>
    </footer>
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { palette } from './echartsTheme.js'
import taihuBoundary from '../../data/taihuBoundary.js'

const props = defineProps({
  modelValue: { type: String, required: true },
  pointList: { type: Array, required: true },
  positions: { type: Object, default: () => ({}) },
  heatField: { type: Object, default: () => ({}) },
  heatStageKey: { type: String, default: '' },
  stageLabel: { type: String, default: '' },
  title: { type: String, default: '监测点位全景' },
  defaultLayer: { type: String, default: 'satellite' }
})

const emit = defineEmits(['update:modelValue'])

const mapContainerRef = ref(null)
let map = null
let markers = []
let satelliteLayer = null
let topoLayer = null
let labelsLayer = null
let heatLayer = null
let riskCanvasLayer = null
let lakeBoundaryLayer = null
let resizeObserver = null
const activeLayer = ref(props.defaultLayer)

// 太湖流域中心（点位几何中心，默认视野对准点位+水域）
const LAKE_CENTER = [31.19, 120.15]
// 默认缩放 11（太湖大小刚好），最小可缩到 9 级看更广的全景
const DEFAULT_ZOOM = 11
const MIN_ZOOM = 9
const MAX_ZOOM = 14
// 风险场包络覆盖真实 HydroLAKES 太湖边界，避免东侧/北侧出现未着色空白。
const HEAT_FIELD_BOUNDS = { south: 30.90, north: 31.56, west: 119.88, east: 120.60 }
// 地图边界（拖拽/瓦片加载的硬边界）
// 覆盖长三角范围：保证缩小到 9 级、宽屏全宽时满屏都有地图（太湖+周边城市），不露白
// [南西角, 北东角]  [lat, lon]
const LAKE_BOUNDS = [
  [29.30, 118.00],
  [33.10, 122.30]
]

function riskColors() {
  const p = palette()
  return {
    high: p.alert,
    mid: p.watch,
    low: p.stable
  }
}

function createMarkerIcon(point, isActive) {
  const riskClass = point.riskClass || 'low'
  const colors = riskColors()
  const color = colors[riskClass] || colors.low
  const dotSize = isActive ? 20 : 14
  const ringSize = isActive ? 36 : 26

  return L.divIcon({
    className: 'lake-marker-wrapper',
    html: `
      <div class="lake-marker ${isActive ? 'is-active' : ''} level-${riskClass}"
           style="--mc: ${color}; --dot: ${dotSize}px; --ring: ${ringSize}px;">
        <div class="lake-marker-ring"></div>
        <div class="lake-marker-dot"></div>
        ${isActive ? '<div class="lake-marker-pulse"></div>' : ''}
        <div class="lake-marker-label">
          <strong>${point.short || ''}</strong>
          <span>${point.name || ''}</span>
        </div>
      </div>
    `,
    iconSize: [0, 0],
    iconAnchor: [0, 0]
  })
}

function buildHeatPoints(pointList) {
  const points = []
  pointList.forEach(p => {
    if (!p.coord) return
    const intensity = p.riskClass === 'high' ? 1.0 : p.riskClass === 'mid' ? 0.6 : 0.25
    points.push([p.coord.lat, p.coord.lon, intensity])
  })
  return points
}

function buildGridHeatPoints(field, stageKey) {
  const grid = field && stageKey ? field[stageKey] : null
  if (!Array.isArray(grid) || !grid.length) return []

  // Grid maps to Taihu Lake region (normalized 0-100 → lat/lon).
  const bounds = HEAT_FIELD_BOUNDS
  const rows = grid.length
  const cols = Math.max(...grid.map((row) => row.length), 0)
  if (!cols) return []

  const points = []
  grid.forEach((row, r) => row.forEach((value, c) => {
    const v = Number(value)
    if (!Number.isFinite(v) || v < 3) return
    const intensity = Math.min(1, v / 100)
    const lat = bounds.north - ((r + 0.5) / rows) * (bounds.north - bounds.south)
    const lon = bounds.west + ((c + 0.5) / cols) * (bounds.east - bounds.west)
    points.push([lat, lon, intensity])
  }))
  return points
}

const hasHeatField = computed(() => Object.keys(props.heatField || {}).length > 0 && Boolean(props.heatStageKey))

function heatColor(value) {
  const v = Math.max(0, Math.min(100, Number(value) || 0))
  const stops = [[0, [34, 211, 238]], [35, [110, 231, 183]], [55, [251, 191, 36]], [75, [249, 115, 22]], [100, [220, 38, 38]]]
  for (let i = 1; i < stops.length; i += 1) {
    if (v <= stops[i][0]) {
      const [a, b] = [stops[i - 1], stops[i]]
      const t = (v - a[0]) / (b[0] - a[0])
      const rgb = a[1].map((channel, index) => Math.round(channel + (b[1][index] - channel) * t))
      return `rgb(${rgb.join(',')})`
    }
  }
  return 'rgb(220,38,38)'
}

// Taihu shoreline data (WGS84). HydroLAKES supplies the detailed shoreline;
// the fallback keeps the map usable if the bundled asset is unavailable.
const FALLBACK_LAKE_MASK = [
  [31.49, 119.97], [31.47, 120.04], [31.43, 120.10], [31.45, 120.16],
  [31.43, 120.23], [31.40, 120.28], [31.42, 120.34], [31.37, 120.38],
  [31.31, 120.40], [31.25, 120.38], [31.20, 120.35], [31.16, 120.37],
  [31.11, 120.34], [31.07, 120.29], [31.03, 120.24], [31.00, 120.18],
  [30.96, 120.12], [30.99, 120.07], [30.97, 120.02], [31.01, 119.98],
  [31.05, 119.94], [31.08, 119.90], [31.14, 119.88], [31.18, 119.84],
  [31.24, 119.86], [31.29, 119.84], [31.34, 119.87], [31.39, 119.86],
  [31.43, 119.90], [31.47, 119.93]
]

const LAKE_GEOMETRY = (() => {
  const feature = taihuBoundary?.features?.[0]
  const geometry = feature?.geometry
  if (!geometry) return { polygons: [[FALLBACK_LAKE_MASK.map(([lat, lon]) => [lon, lat])]], main: FALLBACK_LAKE_MASK }
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : (geometry.coordinates || [])
  const rings = polygons.flatMap((polygon) => polygon)
  const main = (rings || []).slice().sort((a, b) => b.length - a.length)[0]
  return {
    polygons,
    main: main?.map(([lon, lat]) => [lat, lon]) || FALLBACK_LAKE_MASK
  }
})()

const LAKE_MASK = LAKE_GEOMETRY.main

function rebuildLakeBoundary() {
  if (!map) return
  if (lakeBoundaryLayer) map.removeLayer(lakeBoundaryLayer)
  const feature = taihuBoundary?.features?.[0]
  lakeBoundaryLayer = feature
    ? L.geoJSON(feature, {
        style: { color: '#b9ffff', weight: 2.5, opacity: 0.96, fill: false },
        interactive: false,
        className: 'taihu-boundary'
      }).addTo(map)
    : L.polygon(LAKE_MASK, {
        color: '#b9ffff', weight: 2.5, opacity: 0.96, fill: false,
        interactive: false, className: 'taihu-boundary'
      }).addTo(map)
}

function drawRiskCanvas(canvas, mapInstance) {
  const grid = props.heatField[props.heatStageKey]
  if (!Array.isArray(grid) || !grid.length) return
  const rows = grid.length
  const cols = Math.max(...grid.map((row) => row.length), 0)
  const size = mapInstance.getSize()
  canvas.width = size.x
  canvas.height = size.y
  canvas.style.width = `${size.x}px`
  canvas.style.height = `${size.y}px`
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, size.x, size.y)

  // Canvas 直接挂在地图容器，使用 container point，避免 Leaflet pane 平移被重复计算。
  const lakePoints = LAKE_MASK.map((coord) => mapInstance.latLngToContainerPoint(coord))
  ctx.save()
  ctx.beginPath()
  lakePoints.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y))
  ctx.closePath()
  ctx.clip()

  const northWest = mapInstance.latLngToContainerPoint([HEAT_FIELD_BOUNDS.north, HEAT_FIELD_BOUNDS.west])
  const southEast = mapInstance.latLngToContainerPoint([HEAT_FIELD_BOUNDS.south, HEAT_FIELD_BOUNDS.east])
  const left = Math.min(northWest.x, southEast.x)
  const top = Math.min(northWest.y, southEast.y)
  const width = Math.abs(southEast.x - northWest.x)
  const height = Math.abs(southEast.y - northWest.y)
  const field = document.createElement('canvas')
  field.width = cols
  field.height = rows
  const fieldCtx = field.getContext('2d')
  grid.forEach((row, r) => row.forEach((value, c) => {
    fieldCtx.fillStyle = heatColor(value)
    fieldCtx.fillRect(c, r, 1, 1)
  }))
  ctx.globalAlpha = 0.9
  ctx.imageSmoothingEnabled = true
  ctx.drawImage(field, left, top, width, height)

  const drawContour = (threshold, color) => {
    ctx.beginPath()
    ctx.strokeStyle = color
    ctx.lineWidth = 1.2
    ctx.globalAlpha = 0.58
    const px = (c) => left + (c / cols) * width
    const py = (r) => top + (r / rows) * height
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const value = Number(grid[r][c]) || 0
        if (c + 1 < cols && (value - threshold) * ((Number(grid[r][c + 1]) || 0) - threshold) < 0) {
          ctx.moveTo(px(c + 1), py(r)); ctx.lineTo(px(c + 1), py(r + 1))
        }
        if (r + 1 < rows && (value - threshold) * ((Number(grid[r + 1][c]) || 0) - threshold) < 0) {
          ctx.moveTo(px(c), py(r + 1)); ctx.lineTo(px(c + 1), py(r + 1))
        }
      }
    }
    ctx.stroke()
  }
  drawContour(45, 'rgba(255, 221, 94, 0.9)')
  drawContour(75, 'rgba(255, 112, 92, 0.95)')
  ctx.restore()

  ctx.beginPath()
  lakePoints.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y))
  ctx.closePath()
  ctx.strokeStyle = 'rgba(255,255,255,0.68)'
  ctx.lineWidth = 1.5
  ctx.globalAlpha = 1
  ctx.stroke()
}

function rebuildRiskCanvas() {
  if (!map || !hasHeatField.value) return
  if (!riskCanvasLayer) {
    const RiskCanvasLayer = L.Layer.extend({
      onAdd(mapInstance) {
        this._map = mapInstance
        this._canvas = L.DomUtil.create('canvas', 'leaflet-risk-canvas')
        mapInstance.getContainer().appendChild(this._canvas)
        mapInstance.on('move zoom resize', this._reset, this)
        this._reset()
      },
      onRemove(mapInstance) {
        mapInstance.off('move zoom resize', this._reset, this)
        this._canvas?.remove()
      },
      _reset() {
        if (!this._canvas) return
        this._canvas.style.position = 'absolute'
        this._canvas.style.left = '0'
        this._canvas.style.top = '0'
        drawRiskCanvas(this._canvas, this._map)
      }
    })
    riskCanvasLayer = new RiskCanvasLayer()
  }
  if (!map.hasLayer(riskCanvasLayer)) riskCanvasLayer.addTo(map)
  drawRiskCanvas(riskCanvasLayer._canvas, map)
}

function applyLayerVisibility() {
  if (!map) return
  ;[satelliteLayer, topoLayer, labelsLayer, heatLayer, riskCanvasLayer, lakeBoundaryLayer].forEach((layer) => {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer)
  })
  if (activeLayer.value === 'topo') {
    topoLayer.addTo(map)
  } else if (activeLayer.value === 'heat') {
    satelliteLayer.setOpacity(0.18)
    labelsLayer.setOpacity(0.55)
    satelliteLayer.addTo(map)
    labelsLayer.addTo(map)
    if (riskCanvasLayer) riskCanvasLayer.addTo(map)
  } else {
    satelliteLayer.setOpacity(1)
    labelsLayer.setOpacity(0.85)
    satelliteLayer.addTo(map)
    labelsLayer.addTo(map)
    if (!hasHeatField.value && heatLayer) heatLayer.addTo(map)
  }
  if (activeLayer.value === 'heat') rebuildLakeBoundary()
}

async function initMap() {
  if (!mapContainerRef.value) return

  // leaflet.heat plugin needs L on the global scope
  if (typeof window !== 'undefined') {
    window.L = L
  }
  try {
    await import('leaflet.heat')
  } catch (e) {
    console.warn('[LakeMap] leaflet.heat plugin load failed:', e)
  }

  map = L.map(mapContainerRef.value, {
    center: LAKE_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: true,
    attributionControl: true,
    // 锁定在太湖流域，拖拽不会超出边界 → 区域外瓦片不会加载
    maxBounds: LAKE_BOUNDS,
    maxBoundsViscosity: 1.0,
    // 默认 11 级，最小 9 级（全景），最大 14 级看细节
    scrollWheelZoom: true,
    doubleClickZoom: true,
    boxZoom: false,
    keyboard: false,
    touchZoom: true,
    dragging: true
  })

  map.setView(LAKE_CENTER, DEFAULT_ZOOM, { animate: false })
  map.setMinZoom(MIN_ZOOM)
  map.setMaxZoom(MAX_ZOOM)

  const tileBounds = L.latLngBounds(LAKE_BOUNDS)

  satelliteLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 19,
      bounds: tileBounds,
      attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics'
    }
  ).addTo(map)

  labelsLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 19,
      bounds: tileBounds,
      opacity: 0.85
    }
  ).addTo(map)

  topoLayer = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    {
      maxZoom: 17,
      bounds: tileBounds,
      attribution: '&copy; Esri'
    }
  )

  addMarkers()

  rebuildHeatLayer()
  rebuildRiskCanvas()
  applyLayerVisibility()
  if (activeLayer.value === 'heat') rebuildLakeBoundary()

  fitBounds()

  setTimeout(() => map && map.invalidateSize(), 200)

  resizeObserver = new ResizeObserver(() => {
    if (map) map.invalidateSize()
  })
  resizeObserver.observe(mapContainerRef.value)
}

function addMarkers() {
  markers.forEach(m => map.removeLayer(m))
  markers = []

  props.pointList.forEach(point => {
    if (!point.coord) return
    const isActive = point.id === props.modelValue
    const marker = L.marker([point.coord.lat, point.coord.lon], {
      icon: createMarkerIcon(point, isActive),
      zIndexOffset: isActive ? 1000 : 0
    })

    marker.on('click', () => {
      emit('update:modelValue', point.id)
    })

    marker.addTo(map)
    markers.push({ id: point.id, marker })
  })
}

function updateMarkerStates() {
  markers.forEach(({ id, marker }) => {
    const point = props.pointList.find(p => p.id === id)
    if (!point) return
    const isActive = id === props.modelValue
    marker.setIcon(createMarkerIcon(point, isActive))
    marker.setZIndexOffset(isActive ? 1000 : 0)
  })
}

function rebuildHeatLayer() {
  if (!map) return
  if (typeof L.heatLayer !== 'function') return

  // Remove old layer
  if (heatLayer) {
    map.removeLayer(heatLayer)
    heatLayer = null
  }

  // Pick data source: grid (geographic heatmap) > point list (sparse monitoring points)
  const hasGrid = Object.keys(props.heatField).length > 0 && props.heatStageKey
  const heatData = hasGrid
    ? buildGridHeatPoints(props.heatField, props.heatStageKey)
    : buildHeatPoints(props.pointList)

  if (!heatData.length) return

  heatLayer = L.heatLayer(heatData, {
    radius: hasGrid ? 35 : 50,
    blur: hasGrid ? 25 : 35,
    maxZoom: 15,
    minOpacity: 0.05,
    max: 1.0,
    gradient: {
      0.0: '#22d3ee',
      0.2: '#6ee7b7',
      0.4: '#fbbf24',
      0.6: '#f97316',
      0.8: '#ef4444',
      1.0: '#dc2626'
    }
  })

  if (!hasHeatField.value) heatLayer.addTo(map)

  // Ensure heat canvas renders above tile layers
  setTimeout(() => {
    const canvas = mapContainerRef.value?.querySelector('canvas.leaflet-heatmap-layer')
    if (canvas) {
      canvas.style.zIndex = '1000'
      canvas.style.pointerEvents = 'none'
    }
    const overlayPane = mapContainerRef.value?.querySelector('.leaflet-overlay-pane')
    if (overlayPane) {
      overlayPane.style.zIndex = '450'
    }
  }, 0)
}

// 回到默认视野（11 级，太湖全景）
function fitBounds() {
  if (!map) return
  map.setView(LAKE_CENTER, DEFAULT_ZOOM)
}

function switchLayer(layer) {
  activeLayer.value = layer
  if (!map) return
  applyLayerVisibility()
}

watch(() => props.modelValue, () => {
  updateMarkerStates()
})

watch(() => props.pointList, () => {
  if (map) {
    addMarkers()
    rebuildHeatLayer()
    fitBounds()
  }
}, { deep: true })

watch(() => [props.heatField, props.heatStageKey], () => {
  rebuildHeatLayer()
  rebuildRiskCanvas()
  applyLayerVisibility()
  if (activeLayer.value === 'heat') rebuildLakeBoundary()
}, { deep: true })

onMounted(() => {
  nextTick(() => {
    initMap()
  })
})

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
</script>

<style scoped>
.map-panel {
  min-height: 720px;
  display: flex;
  flex-direction: column;
}

.map-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.layer-switcher {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  border: 1px solid var(--panel-line);
  background: var(--c-surface-soft);
}
.heat-ramp { display: inline-flex; align-items: center; gap: 5px; margin-left: 4px; color: var(--c-muted); font-size: 10px; }
.heat-ramp i { width: 64px; height: 8px; border-radius: 99px; background: linear-gradient(90deg, #22d3ee, #6ee7b7 30%, #fbbf24 55%, #f97316 75%, #dc2626); border: 1px solid rgba(255,255,255,.25); }
.heat-ramp b { font-weight: 600; }

.layer-switcher button {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.layer-switcher button:hover {
  color: var(--text);
  background: var(--c-surface-soft);
}

.layer-switcher button.active {
  background: var(--c-accent-soft);
  color: var(--teal);
  border-color: var(--c-accent-border);
}

.leaflet-map-container {
  flex: 1;
  min-height: 620px;
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid var(--panel-line);
  background: var(--c-bg-base);
  position: relative;
  z-index: 0;
}
.leaflet-risk-canvas {
  z-index: 420;
  pointer-events: none;
  mix-blend-mode: multiply;
}

@media (max-width: 820px) {
  .leaflet-map-container {
    min-height: 460px;
  }
}
</style>

<style>
/* ===== Leaflet global overrides (not scoped) ===== */

/* Dark-themed zoom controls — 跟随主题 token */
.leaflet-bar {
  border: 1px solid var(--c-line-strong) !important;
  background: var(--c-surface) !important;
  backdrop-filter: blur(8px);
  border-radius: 10px !important;
  overflow: hidden;
  box-shadow: var(--shadow-sm) !important;
}
.leaflet-bar a {
  background: transparent !important;
  color: var(--c-text-soft) !important;
  border-bottom: 1px solid var(--c-line) !important;
  transition: background 0.18s ease, color 0.18s ease;
}
.leaflet-bar a:hover {
  background: var(--c-accent-soft) !important;
  color: var(--c-accent) !important;
}
.leaflet-bar a:last-child {
  border-bottom: none !important;
}

/* Attribution bar */
.leaflet-control-attribution {
  background: var(--c-surface) !important;
  color: var(--c-muted) !important;
  font-size: 11px !important;
  border-radius: 6px 0 0 0 !important;
  padding: 3px 8px !important;
}
.leaflet-control-attribution a {
  color: var(--c-text-soft) !important;
}

/* ===== Custom marker styles ===== */
.lake-marker-wrapper {
  background: none !important;
  border: none !important;
}

.lake-marker {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: var(--ring);
  height: var(--ring);
  cursor: pointer;
}

.lake-marker-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid var(--mc);
  opacity: 0.5;
  box-shadow: 0 0 12px var(--mc);
}

.lake-marker-dot {
  position: relative;
  width: var(--dot);
  height: var(--dot);
  border-radius: 50%;
  background: var(--mc);
  border: 2px solid #ffffff;
  box-shadow: 0 0 14px var(--mc), 0 2px 6px rgba(0, 0, 0, 0.5);
  z-index: 2;
}

.lake-marker-pulse {
  position: absolute;
  width: var(--dot);
  height: var(--dot);
  border-radius: 50%;
  border: 2px solid var(--mc);
  animation: lake-marker-ping 1.8s ease-out infinite;
  z-index: 1;
}

@keyframes lake-marker-ping {
  0% {
    transform: scale(1);
    opacity: 0.7;
  }
  100% {
    transform: scale(3.2);
    opacity: 0;
  }
}

.lake-marker-label {
  position: absolute;
  top: 50%;
  left: calc(100% + 6px);
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--c-surface-strong);
  backdrop-filter: blur(8px);
  border: 1px solid var(--c-line);
  white-space: nowrap;
  pointer-events: none;
  z-index: 3;
}

.lake-marker-label strong {
  color: var(--mc);
  font-size: 11px;
  font-family: var(--font-display);
  letter-spacing: 0.5px;
  line-height: 1.2;
}

.lake-marker-label span {
  color: var(--c-text-soft);
  font-size: 11px;
  line-height: 1.2;
}

.lake-marker:hover .lake-marker-ring {
  opacity: 0.8;
  box-shadow: 0 0 18px var(--mc);
}

.lake-marker:hover .lake-marker-dot {
  transform: scale(1.15);
  transition: transform 0.15s ease;
}

/* Hide default leaflet marker shadow */
.leaflet-marker-shadow {
  display: none !important;
}
</style>
