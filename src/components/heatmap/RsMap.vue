<template>
  <section class="hm-map rs-map" aria-label="太湖卫星遥感图层地图">
    <div ref="mapContainerRef" class="rs-map-container"></div>

    <span v-if="badgeA" class="rs-badge rs-badge--a">{{ badgeA }}</span>
    <span v-if="compare && badgeB" class="rs-badge rs-badge--b">{{ badgeB }}</span>

    <div
      v-if="compare"
      class="rs-divider"
      :style="{ left: divider + '%' }"
      role="separator"
      aria-label="对比分割线（左右拖动）"
      @pointerdown="onDividerDown"
    >
      <span class="rs-divider-handle"></span>
    </div>
  </section>
</template>

<script setup>
// 卫星遥感图层地图：ArcGIS 底图 + THQBCA-V2 年度反演 PNG 叠加 + A/B swipe 对比。
// 年度产品为真实历史观测；无坐标不造点，站点点位由父级传入（observed 轨）。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps({
  // 影像 A（主视图）：{ url, bounds: [[s,w],[n,e]] }，url 为空表示未就绪
  imageA: { type: Object, default: null },
  // 影像 B（对比右侧）：仅 compare 时渲染
  imageB: { type: Object, default: null },
  compare: { type: Boolean, default: false },
  badgeA: { type: String, default: '' },
  badgeB: { type: String, default: '' },
  // 实时观测点位（observed）：形状与 LakeMap pointList 一致
  points: { type: Array, default: () => [] },
  pointsVisible: { type: Boolean, default: true },
  // 预警范围凸包（[[lat,lon],...]，首尾不闭合；空数组不渲染）
  hull: { type: Array, default: () => [] },
  basemap: { type: String, default: 'satellite' },
  opacity: { type: Number, default: 0.85 },
  resetToken: { type: Number, default: 0 }
})

const emit = defineEmits(['tile-error'])

const mapContainerRef = ref(null)
const divider = ref(50)
let map = null
let markers = []
let hullLayer = null
let satelliteLayer = null
let topoLayer = null
let labelsLayer = null
let overlayA = null
let overlayB = null
let resizeObserver = null

const LAKE_CENTER = [31.19, 120.15]
const DEFAULT_ZOOM = 11
const MIN_ZOOM = 9
const MAX_ZOOM = 14
const LAKE_BOUNDS = [
  [29.3, 118.0],
  [33.1, 122.3]
]

let tileErrorCount = 0

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

function initMap() {
  if (!mapContainerRef.value) return
  map = L.map(mapContainerRef.value, {
    center: LAKE_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: true,
    attributionControl: false,
    maxBounds: LAKE_BOUNDS,
    maxBoundsViscosity: 1.0,
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

  addMarkers()
  rebuildOverlays()
  rebuildHull()
  setTimeout(() => map && map.invalidateSize(), 200)
  resizeObserver = new ResizeObserver(() => map && map.invalidateSize())
  resizeObserver.observe(mapContainerRef.value)
}

function rebuildOverlays() {
  if (!map) return
  if (overlayA) {
    map.removeLayer(overlayA)
    overlayA = null
  }
  if (overlayB) {
    map.removeLayer(overlayB)
    overlayB = null
  }
  const a = props.imageA
  if (a && a.url && a.bounds) {
    overlayA = L.imageOverlay(a.url, L.latLngBounds(a.bounds), { opacity: props.opacity })
    overlayA.addTo(map)
    // 影像压在底图/标签之上、点位之下
    const el = overlayA.getElement()
    if (el) el.style.zIndex = '350'
  }
  const b = props.imageB
  if (props.compare && b && b.url && b.bounds) {
    overlayB = L.imageOverlay(b.url, L.latLngBounds(b.bounds), { opacity: props.opacity })
    overlayB.addTo(map)
    const el = overlayB.getElement()
    if (el) el.style.zIndex = '360'
  }
  applyClip()
}

function applyClip() {
  // A 显示在分割线左侧，B 显示在右侧；仅左/右半边可见
  const left = Math.min(Math.max(divider.value, 0), 100)
  const elA = overlayA && overlayA.getElement()
  const elB = overlayB && overlayB.getElement()
  if (elA) elA.style.clipPath = props.compare ? `inset(0 ${100 - left}% 0 0)` : ''
  if (elB) elB.style.clipPath = `inset(0 0 0 ${left}%)`
}

function rebuildHull() {
  if (!map) return
  if (hullLayer) {
    map.removeLayer(hullLayer)
    hullLayer = null
  }
  if (Array.isArray(props.hull) && props.hull.length >= 3) {
    hullLayer = L.polygon(props.hull, {
      color: '#ff6b6b',
      weight: 1.5,
      dashArray: '5 5',
      fill: true,
      fillOpacity: 0.08,
      interactive: false
    })
    hullLayer.addTo(map)
  }
}

function createMarkerIcon(point) {
  const color = point.color || '#5fd6a4'
  const root = document.createElement('div')
  root.className = 'rs-dot-marker'
  root.style.setProperty('--mc', color)
  const ring = document.createElement('div')
  ring.className = 'rs-dot-ring'
  const dot = document.createElement('div')
  dot.className = 'rs-dot-core'
  root.append(ring, dot)
  return L.divIcon({ className: 'rs-dot-wrapper', html: root, iconSize: [0, 0], iconAnchor: [0, 0] })
}

function addMarkers() {
  if (!map) return
  markers.forEach(({ marker }) => map.removeLayer(marker))
  markers = []
  if (!props.pointsVisible) return
  props.points.forEach((point) => {
    if (!point.coord) return
    const marker = L.marker([point.coord.lat, point.coord.lon], { icon: createMarkerIcon(point) })
    if (point.tooltip) {
      marker.bindTooltip(point.tooltip, { direction: 'top', offset: [0, -12] })
    }
    marker.addTo(map)
    markers.push({ id: point.id, marker })
  })
}

function switchBasemap(name) {
  if (!map) return
  if (name === 'satellite') {
    if (map.hasLayer(topoLayer)) map.removeLayer(topoLayer)
    if (!map.hasLayer(satelliteLayer)) map.addLayer(satelliteLayer)
    if (!map.hasLayer(labelsLayer)) map.addLayer(labelsLayer)
  } else {
    if (map.hasLayer(satelliteLayer)) map.removeLayer(satelliteLayer)
    if (map.hasLayer(labelsLayer)) map.removeLayer(labelsLayer)
    if (!map.hasLayer(topoLayer)) map.addLayer(topoLayer)
  }
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
}

function fitBounds() {
  if (!map) return
  map.setView(LAKE_CENTER, DEFAULT_ZOOM)
}

let draggingDivider = false
function onDividerDown(e) {
  draggingDivider = true
  e.preventDefault()
  const move = (ev) => {
    if (!draggingDivider || !mapContainerRef.value) return
    const rect = mapContainerRef.value.getBoundingClientRect()
    const pct = ((ev.clientX - rect.left) / rect.width) * 100
    divider.value = Math.min(100, Math.max(0, Math.round(pct * 10) / 10))
  }
  const up = () => {
    draggingDivider = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

watch(() => props.imageA, rebuildOverlays, { deep: true })
watch(() => props.imageB, rebuildOverlays, { deep: true })
watch(() => props.compare, () => rebuildOverlays())
watch(() => divider.value, applyClip)
watch(() => props.opacity, (value) => {
  if (overlayA) overlayA.setOpacity(value)
  if (overlayB) overlayB.setOpacity(value)
})
watch(() => props.points, addMarkers, { deep: true })
watch(() => props.pointsVisible, () => {
  addMarkers()
})
watch(() => props.hull, rebuildHull, { deep: true })
watch(() => props.basemap, switchBasemap)
watch(() => props.resetToken, fitBounds)

defineExpose({ retryTiles, fitBounds })

onMounted(initMap)

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
.rs-map {
  position: relative;
  overflow: hidden;
}
.rs-map-container {
  height: 100%;
  min-height: inherit;
  background: var(--c-bg-base, #0b1220);
}
.rs-badge {
  position: absolute;
  top: 10px;
  z-index: 500;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono, monospace);
  background: color-mix(in srgb, var(--c-surface, #10192b) 88%, transparent);
  border: 1px solid var(--c-line, rgba(255, 255, 255, 0.14));
  color: var(--c-text, #e8eef7);
  pointer-events: none;
}
.rs-badge--a {
  left: 10px;
  border-color: color-mix(in srgb, #16a34a 55%, transparent);
}
.rs-badge--b {
  right: 10px;
  border-color: color-mix(in srgb, #f97316 55%, transparent);
}
.rs-divider {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  transform: translateX(-1px);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 0 8px rgba(0, 0, 0, 0.55);
  z-index: 600;
  cursor: ew-resize;
  touch-action: none;
}
.rs-divider-handle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
}
.rs-divider-handle::before {
  content: '⇔';
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  color: #0b1220;
  font-weight: 800;
}
</style>

<style>
/* ===== RS 站点点位全局样式（divIcon 内容不经 Vue scoped，需全局块） ===== */
.rs-dot-wrapper {
  background: none !important;
  border: none !important;
}
.rs-dot-marker {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
}
.rs-dot-ring {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid var(--mc);
  opacity: 0.5;
  box-shadow: 0 0 10px var(--mc);
}
.rs-dot-core {
  position: relative;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--mc);
  border: 2px solid #ffffff;
  box-shadow: 0 0 10px var(--mc), 0 2px 5px rgba(0, 0, 0, 0.5);
  z-index: 2;
}
</style>
