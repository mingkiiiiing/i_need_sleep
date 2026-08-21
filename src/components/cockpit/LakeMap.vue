<template>
  <section class="panel map-panel">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">LAKE TWIN MAP &middot; SATELLITE</p>
        <h2>{{ title }}</h2>
      </div>
      <div class="map-controls">
        <div class="layer-switcher" role="group" aria-label="地图图层">
          <button type="button" :class="{ active: activeLayer === 'satellite' }" @click="switchLayer('satellite')">卫星影像</button>
          <button type="button" :class="{ active: activeLayer === 'topo' }" @click="switchLayer('topo')">地形地图</button>
        </div>
        <div v-if="showTabs" class="map-tools">
          <RouterLink class="tool-chip" :class="{ active: activeTab === 'stations' }" to="/stations">监测站</RouterLink>
          <RouterLink class="tool-chip" :class="{ active: activeTab === 'heatmap' }" to="/heatmap">风险分区</RouterLink>
          <RouterLink class="tool-chip" :class="{ active: activeTab === 'history' }" to="/history">历史轨迹</RouterLink>
        </div>
      </div>
    </header>

    <div ref="mapContainerRef" class="leaflet-map-container"></div>

    <footer class="map-footer">
      <div class="legend-row">
        <span><span class="legend-dot high"></span>红色预警</span>
        <span><span class="legend-dot mid"></span>橙色关注</span>
        <span><span class="legend-dot low"></span>绿色稳定</span>
      </div>
      <span class="legend-row">点击点位查看详情 &middot; 当前档位 {{ stageLabel }}</span>
    </footer>
  </section>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { palette } from './echartsTheme.js'

const props = defineProps({
  modelValue: { type: String, required: true },
  pointList: { type: Array, required: true },
  positions: { type: Object, default: () => ({}) },
  stageLabel: { type: String, default: '' },
  title: { type: String, default: '监测点位全景' },
  activeTab: { type: String, default: 'stations' },
  showTabs: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue'])

const mapContainerRef = ref(null)
let map = null
let markers = []
let satelliteLayer = null
let topoLayer = null
let labelsLayer = null
let heatLayer = null
let resizeObserver = null
const activeLayer = ref('satellite')

// 太湖流域中心（点位几何中心，默认视野对准点位+水域）
const LAKE_CENTER = [31.19, 120.15]
// 默认缩放 11（太湖大小刚好），最小可缩到 9 级看更广的全景
const DEFAULT_ZOOM = 11
const MIN_ZOOM = 9
const MAX_ZOOM = 14
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
    preferCanvas: true,
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

  const heatData = buildHeatPoints(props.pointList)
  if (heatData.length && typeof L.heatLayer === 'function') {
    heatLayer = L.heatLayer(heatData, {
      radius: 50,
      blur: 35,
      maxZoom: 14,
      minOpacity: 0.25,
      gradient: { 0.2: '#6ee7b7', 0.4: '#f4c062', 0.6: '#ff8c5a', 0.8: '#ff5757', 1.0: '#ff2d2d' }
    })
    if (activeLayer.value === 'satellite') {
      heatLayer.addTo(map)
    }
  }

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

function updateHeatLayer() {
  if (!map || !heatLayer) return
  const heatData = buildHeatPoints(props.pointList)
  heatLayer.setLatLngs(heatData)
}

// 回到默认视野（11 级，太湖全景）
function fitBounds() {
  if (!map) return
  map.setView(LAKE_CENTER, DEFAULT_ZOOM)
}

function switchLayer(layer) {
  activeLayer.value = layer
  if (!map) return

  if (layer === 'satellite') {
    if (map.hasLayer(topoLayer)) map.removeLayer(topoLayer)
    if (!map.hasLayer(satelliteLayer)) map.addLayer(satelliteLayer)
    if (!map.hasLayer(labelsLayer)) map.addLayer(labelsLayer)
    if (heatLayer && !map.hasLayer(heatLayer)) heatLayer.addTo(map)
  } else {
    if (map.hasLayer(satelliteLayer)) map.removeLayer(satelliteLayer)
    if (map.hasLayer(labelsLayer)) map.removeLayer(labelsLayer)
    if (map.hasLayer(heatLayer)) map.removeLayer(heatLayer)
    if (!map.hasLayer(topoLayer)) map.addLayer(topoLayer)
  }
}

watch(() => props.modelValue, () => {
  updateMarkerStates()
})

watch(() => props.pointList, () => {
  if (map) {
    addMarkers()
    updateHeatLayer()
    fitBounds()
  }
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

.map-tools {
  display: flex;
  gap: 8px;
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
  font-size: 10px !important;
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
  font-size: 10px;
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
