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
//
// T2 动画层（借鉴 earth.nullschool / Windy / kepler.gl 的平滑感）：
//  · 场点：fieldPoints 变化时按索引对账，已存在 circle 用 rAF 在 ~450ms 内
//    从旧半径/旧颜色补间到新值（setRadius + setStyle），索引级联错峰；
//    新增点 scale-in 淡入（半径 0 → 目标）；移除点直接移除。
//  · 高值（high:true）场点叠加呼吸光晕（SVG circle + CSS 动画，辉光用
//    --c-alert/--c-watch 语义令牌）；prefers-reduced-motion 时静态显示。
//  · 站点 divIcon：同 id 颜色变化用 rAF 插值 --mc（最可靠的跨浏览器双帧过渡），
//    强调/选中态缩放走 CSS transform transition。
//  · 影像：A/B 年份切换做 400ms opacity 交叉淡化，旧层淡出后移除；
//    props.opacity 调节仍即时生效。
// 补间只在同一目标的新旧真实渲染值之间插值，不造数据；工具见 composables/mapTween.js。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  colorToRgb,
  createTweenGroup,
  prefersReducedMotion,
  rgbToCss,
  staggerDelay
} from '../../composables/mapTween'

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
  // 预测空间样点：仅用于模型推演场，不与 observed 点位混为一条数据轨
  fieldPoints: { type: Array, default: () => [] },
  fieldVisible: { type: Boolean, default: false },
  fieldBoundary: { type: Array, default: () => [] },
  boundaryVisible: { type: Boolean, default: false },
  // 预警范围凸包（[[lat,lon],...]，首尾不闭合；空数组不渲染）
  hull: { type: Array, default: () => [] },
  basemap: { type: String, default: 'satellite' },
  opacity: { type: Number, default: 0.85 },
  // 当前选中站点（预测推演站点视图高亮）；空串表示全湖视图
  activeId: { type: String, default: '' },
  resetToken: { type: Number, default: 0 }
})

const emit = defineEmits(['tile-error', 'point-click'])

const mapContainerRef = ref(null)
const divider = ref(50)
let map = null
let hullLayer = null
let fieldLayer = null
let fieldGlowLayer = null
let fieldBoundaryLayer = null
let satelliteLayer = null
let topoLayer = null
let labelsLayer = null
let resizeObserver = null

// —— 对账式图层注册表（index/key → 条目，含当前显示值供补间断点续接）——
const fieldEntries = new Map() // 索引 → { circle, rgb, radius, tooltip, handle }
const glowEntries = new Map() // 索引 → { circle, radius, variant, handle }
const boundaryEntries = new Map() // 索引 → { circle, radius, tooltip, handle }
const markerEntries = new Map() // 站点 key → { marker, root, point, rgb, color, tooltip, handle }
// —— rAF 取消令牌分组：新一轮动画前 cancelAll，卸载时 destroy 全清 ——
const fieldTweens = createTweenGroup()
const markerTweens = createTweenGroup()
const overlaySlotA = createOverlaySlot(350)
const overlaySlotB = createOverlaySlot(360)

const LAKE_CENTER = [31.19, 120.15]
// 默认视野：全湖 + 宜兴/苏州周边一览（对标监测研判参考稿），站点点位初始即可见
const DEFAULT_ZOOM = 10
const MIN_ZOOM = 9
const MAX_ZOOM = 14
const LAKE_BOUNDS = [
  [29.3, 118.0],
  [33.1, 122.3]
]

// —— 动画参数 ——
const FIELD_TWEEN_MS = 450 // 场点半径/颜色补间时长
const FIELD_STAGGER_MS = 32 // 按索引级联错峰步长（30-40ms 档）
const OVERLAY_FADE_MS = 400 // 影像年份交叉淡化时长
const MARKER_COLOR_MS = 380 // 站点 chla 颜色过渡时长
const GLOW_RADIUS = 5800 // 高值呼吸光晕半径（介于场点 4200 与虚线圈 7200 之间）

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
  updateField()
  rebuildOverlays()
  rebuildHull()
  setTimeout(() => map && map.invalidateSize(), 200)
  resizeObserver = new ResizeObserver(() => map && map.invalidateSize())
  resizeObserver.observe(mapContainerRef.value)
}

/* ============================================================
   影像图层：A/B 槽位 + 400ms 交叉淡化
   ============================================================ */
function boundsKeyOf(bounds) {
  return Array.isArray(bounds) ? bounds.map((pair) => `${pair[0]},${pair[1]}`).join('|') : ''
}

// 影像槽位封装：管理「当前层 + 淡出中的旧层」，url 变化时交叉淡化
function createOverlaySlot(zIndex) {
  let current = null // 当前展示的 imageOverlay
  let fading = null // 正在淡出的旧 imageOverlay
  const group = createTweenGroup()

  // 淘汰正在淡出的旧层：取消其补间并立即移除（被新一轮覆盖）
  function dropFading() {
    group.cancelAll()
    if (fading) {
      if (map && map.hasLayer(fading)) map.removeLayer(fading)
      fading = null
    }
  }

  function fadeOut(layer) {
    const start = typeof layer._rsOpacity === 'number' ? layer._rsOpacity : props.opacity
    group.run({
      duration: OVERLAY_FADE_MS,
      from: [start],
      to: [0],
      update: (vals) => {
        layer._rsOpacity = Math.max(0, vals[0])
        layer.setOpacity(layer._rsOpacity)
      },
      done: () => {
        if (map && map.hasLayer(layer)) map.removeLayer(layer)
        if (fading === layer) fading = null
      }
    })
  }

  // 新层淡入（0 → 目标透明度）；影像未加载完时等 load/error 再启动，
  // 避免对着空白图做交叉淡化。旧层与新层同帧启动，形成 cross-fade。
  function enter(layer, prev) {
    const begin = () => {
      if (layer !== current) return // 已被新一轮切换淘汰
      group.run({
        duration: OVERLAY_FADE_MS,
        from: [0],
        to: [1],
        // 目标透明度实时读取 props.opacity：淡化中途调节透明度也能跟随
        update: (vals) => {
          if (layer !== current) return
          const o = vals[0] * props.opacity
          layer._rsOpacity = o
          layer.setOpacity(o)
        }
      })
      if (prev) fadeOut(prev)
    }
    const el = layer.getElement()
    if (el && el.complete === false) {
      layer.once('load', begin)
      layer.once('error', begin)
    } else {
      begin()
    }
  }

  function rebuild(image, visible, instantHidden) {
    if (!map) return
    const usable = visible && image && image.url && image.bounds
    const url = usable ? image.url : null
    // url 与 bounds 均未变化：只同步透明度，不做无意义的重建
    if (current && url && current._rsUrl === url && current._rsBoundsKey === boundsKeyOf(image.bounds)) {
      current.setOpacity(props.opacity)
      current._rsOpacity = props.opacity
      return
    }
    dropFading()
    let prev = current
    current = null

    if (!url) {
      if (prev) {
        if (instantHidden || prefersReducedMotion()) map.removeLayer(prev)
        else {
          fading = prev
          fadeOut(prev)
        }
      }
      return
    }

    current = L.imageOverlay(url, L.latLngBounds(image.bounds), { opacity: 0 })
    current._rsUrl = url
    current._rsBoundsKey = boundsKeyOf(image.bounds)
    current._rsOpacity = 0
    current.addTo(map)
    const el = current.getElement()
    if (el) el.style.zIndex = String(zIndex)

    const animate = !prefersReducedMotion()
    if (prev && !animate) {
      // reduced-motion：直接换层，无动画
      map.removeLayer(prev)
      prev = null
    }
    if (!prev) {
      enter(current, null)
    } else {
      // 年份切换（单年/对比同理）：新层 0→目标，旧层同步→0 后移除
      fading = prev
      enter(current, prev)
    }
  }

  function setOpacity(v) {
    if (current) {
      current._rsOpacity = v
      current.setOpacity(v)
    }
  }

  function eachElement(cb) {
    let el = current && current.getElement()
    if (el) cb(el)
    el = fading && fading.getElement()
    if (el) cb(el)
  }

  function destroy() {
    group.destroy()
    current = null
    fading = null
  }

  return { rebuild, setOpacity, eachElement, destroy }
}

function rebuildOverlays() {
  overlaySlotA.rebuild(props.imageA, true, false)
  // B：对比关闭时随原行为立即移除；开启/切年时交叉淡化
  overlaySlotB.rebuild(props.imageB, props.compare, !props.compare)
  applyClip()
}

function applyClip() {
  // A 显示在分割线左侧，B 显示在右侧；仅左/右半边可见（含淡化中的旧层）
  const left = Math.min(Math.max(divider.value, 0), 100)
  overlaySlotA.eachElement((el) => {
    el.style.clipPath = props.compare ? `inset(0 ${100 - left}% 0 0)` : ''
  })
  overlaySlotB.eachElement((el) => {
    el.style.clipPath = props.compare ? `inset(0 0 0 ${left}%)` : 'inset(0 0 0 100%)'
  })
}

function rebuildHull() {
  if (!map) return
  if (hullLayer) {
    map.removeLayer(hullLayer)
    hullLayer = null
  }
  if (Array.isArray(props.hull) && props.hull.length >= 3) {
    hullLayer = L.layerGroup()
    L.polygon(props.hull, {
      color: '#ef4444',
      weight: 8,
      opacity: 0.12,
      fill: false,
      interactive: false
    }).addTo(hullLayer)
    L.polygon(props.hull, {
      color: '#ef4444',
      weight: 2,
      dashArray: '8 6',
      fill: true,
      fillColor: '#ef4444',
      fillOpacity: 0.12,
      interactive: false
    }).addTo(hullLayer)
    const center = props.hull.reduce((sum, point) => [sum[0] + point[0], sum[1] + point[1]], [0, 0])
      .map((value) => value / props.hull.length)
    L.marker(center, {
      interactive: false,
      icon: L.divIcon({ className: 'rs-hull-label', html: '<span>预警范围</span>', iconSize: [72, 24], iconAnchor: [36, 12] })
    }).addTo(hullLayer)
    hullLayer.addTo(map)
  }
}

function fieldColor(value) {
  const v = Math.max(0, Math.min(1, Number(value) || 0))
  if (v >= 0.75) return '#ef4444'
  if (v >= 0.5) return '#f59e0b'
  if (v >= 0.25) return '#f5d45d'
  return '#22c55e'
}

/* ============================================================
   预测场点：整体重建 → 按「索引」对账 + rAF 补间
   （数值→颜色映射 fieldColor 一字未改，动画只过渡新旧映射结果）
   ============================================================ */
function syncCircleTooltip(layer, entry, tooltip, options) {
  if (entry.tooltip === tooltip) return
  const bound = layer.getTooltip()
  if (tooltip) {
    if (bound) layer.setTooltipContent(tooltip)
    else layer.bindTooltip(tooltip, options)
  } else if (bound) {
    layer.unbindTooltip()
  }
  entry.tooltip = tooltip
}

function syncCircleLatLng(circle, lat, lon) {
  const ll = circle.getLatLng()
  if (ll.lat !== lat || ll.lng !== lon) circle.setLatLng([lat, lon])
}

function updateField() {
  if (!map) return
  const points = props.fieldPoints
  const fieldOn = !!props.fieldVisible && points.length > 0

  if (!fieldOn) {
    fieldTweens.cancelAll()
    if (fieldLayer) {
      map.removeLayer(fieldLayer)
      fieldLayer = null
    }
    fieldEntries.clear()
  } else {
    if (!fieldLayer) fieldLayer = L.layerGroup().addTo(map)
    // 移除已消失/失效的场点（先取消其补间令牌）
    for (const [i, entry] of Array.from(fieldEntries)) {
      const p = points[i]
      if (!p || p.lat == null || p.lon == null) {
        if (entry.handle) entry.handle.cancel()
        fieldLayer.removeLayer(entry.circle)
        fieldEntries.delete(i)
      }
    }
    points.forEach((point, i) => {
      if (point.lat == null || point.lon == null) return
      const targetCss = fieldColor(point.normalized)
      const targetRgb = colorToRgb(targetCss)
      const tooltip = point.tooltip || ''
      let entry = fieldEntries.get(i)
      if (!entry) {
        // 新增点：scale-in 淡入（初始半径 0 → 目标），reduced-motion 时直落终态
        const circle = L.circle([point.lat, point.lon], {
          radius: 0,
          stroke: true,
          color: targetCss,
          weight: 1,
          opacity: 0,
          fillColor: targetCss,
          fillOpacity: 0,
          interactive: true
        })
        if (tooltip) circle.bindTooltip(tooltip, { direction: 'top' })
        circle.addTo(fieldLayer)
        entry = { circle, rgb: targetRgb, radius: 0, tooltip, handle: null }
        fieldEntries.set(i, entry)
        entry.handle = fieldTweens.run({
          duration: FIELD_TWEEN_MS,
          delay: staggerDelay(i, FIELD_STAGGER_MS),
          from: [0, 0, 0],
          to: [4200, 0.75, 0.24],
          update: (vals) => {
            entry.radius = vals[0]
            entry.circle.setRadius(vals[0])
            entry.circle.setStyle({ opacity: vals[1], fillOpacity: vals[2] })
          }
        })
      } else {
        // 已存在点：从旧半径/旧颜色（当前显示值）平滑过渡到新真实值；
        // 上一轮补间若在进行中，先取消其令牌，再以当前显示值为起点续接
        syncCircleTooltip(entry.circle, entry, tooltip, { direction: 'top' })
        syncCircleLatLng(entry.circle, point.lat, point.lon)
        const radiusChanged = Math.abs(entry.radius - 4200) > 0.5
        const colorChanged = !entry.rgb || !targetRgb || entry.rgb.some((v, c) => Math.abs(v - targetRgb[c]) > 0.5)
        if (radiusChanged || colorChanged) {
          if (entry.handle) entry.handle.cancel()
          const fromRgb = entry.rgb ? entry.rgb.slice() : targetRgb
          const toRgb = targetRgb || fromRgb
          entry.handle = fieldTweens.run({
            duration: FIELD_TWEEN_MS,
            delay: staggerDelay(i, FIELD_STAGGER_MS),
            from: [...fromRgb, entry.radius],
            to: [...toRgb, 4200],
            update: (vals) => {
              entry.rgb = [vals[0], vals[1], vals[2]]
              entry.radius = vals[3]
              const css = rgbToCss(entry.rgb)
              entry.circle.setRadius(vals[3])
              entry.circle.setStyle({ color: css, fillColor: css })
            }
          })
        }
      }
    })
  }
  updateFieldGlow(fieldOn, points)
  updateFieldBoundary(points)
}

// 高值呼吸光晕：high:true 场点叠加柔光圈（辉光色用 --c-alert/--c-watch 语义
// 令牌，随主题联动；呼吸由 CSS 动画驱动，reduced-motion 下静态显示）
function updateFieldGlow(fieldOn, points) {
  if (!fieldOn) {
    for (const entry of glowEntries.values()) {
      if (entry.handle) entry.handle.cancel()
    }
    if (fieldGlowLayer) {
      map.removeLayer(fieldGlowLayer)
      fieldGlowLayer = null
    }
    glowEntries.clear()
    return
  }
  if (!fieldGlowLayer) fieldGlowLayer = L.layerGroup().addTo(map)
  for (const [i, entry] of Array.from(glowEntries)) {
    const p = points[i]
    if (!p || !p.high || p.lat == null || p.lon == null) {
      if (entry.handle) entry.handle.cancel()
      fieldGlowLayer.removeLayer(entry.circle)
      glowEntries.delete(i)
    }
  }
  points.forEach((point, i) => {
    if (!point.high || point.lat == null || point.lon == null) return
    // 关注档（琥珀）与预警档（珊瑚红）按 fieldColor 同口径分档
    const isWatch = point.normalized >= 0.5 && point.normalized < 0.75
    const variant = isWatch ? 'rs-field-halo--watch' : ''
    let entry = glowEntries.get(i)
    if (!entry) {
      const circle = L.circle([point.lat, point.lon], {
        radius: 0,
        stroke: false,
        fill: true,
        fillOpacity: 0.16,
        fillColor: '#ef4444',
        interactive: false,
        className: `rs-field-halo${variant ? ` ${variant}` : ''}`
      })
      circle.addTo(fieldGlowLayer)
      entry = { circle, radius: 0, variant, handle: null }
      glowEntries.set(i, entry)
      entry.handle = fieldTweens.run({
        duration: FIELD_TWEEN_MS,
        delay: staggerDelay(i, FIELD_STAGGER_MS),
        from: [0],
        to: [GLOW_RADIUS],
        update: (vals) => {
          entry.radius = vals[0]
          entry.circle.setRadius(vals[0])
        }
      })
    } else {
      syncCircleLatLng(entry.circle, point.lat, point.lon)
      if (entry.variant !== variant) {
        entry.variant = variant
        const el = entry.circle.getElement()
        if (el) el.classList.toggle('rs-field-halo--watch', isWatch)
      }
      // scale-in 补间若仍在进行中（被新一轮对账取消），从当前半径续接到目标
      if (Math.abs(entry.radius - GLOW_RADIUS) > 0.5) {
        if (entry.handle) entry.handle.cancel()
        entry.handle = fieldTweens.run({
          duration: FIELD_TWEEN_MS,
          delay: staggerDelay(i, FIELD_STAGGER_MS),
          from: [entry.radius],
          to: [GLOW_RADIUS],
          update: (vals) => {
            entry.radius = vals[0]
            entry.circle.setRadius(vals[0])
          }
        })
      }
    }
  })
}

// 预警范围虚线圈（样式沿用原实现）：显隐/数据变化以 scale-in + 半径补间代替整体重建
function updateFieldBoundary(points) {
  if (!props.boundaryVisible || !points.length) {
    // 注意：此处只按条目取消令牌，不能整组 cancelAll——
    // 本函数在同一次 updateField 中运行于场点/光晕补间之后，整组取消会误杀本轮新动画
    for (const entry of boundaryEntries.values()) {
      if (entry.handle) entry.handle.cancel()
    }
    if (fieldBoundaryLayer) {
      map.removeLayer(fieldBoundaryLayer)
      fieldBoundaryLayer = null
    }
    boundaryEntries.clear()
    return
  }
  if (!fieldBoundaryLayer) fieldBoundaryLayer = L.layerGroup().addTo(map)
  for (const [i, entry] of Array.from(boundaryEntries)) {
    const p = points[i]
    if (!p || !p.high || p.lat == null || p.lon == null) {
      if (entry.handle) entry.handle.cancel()
      fieldBoundaryLayer.removeLayer(entry.circle)
      boundaryEntries.delete(i)
    }
  }
  points.forEach((point, i) => {
    if (!point.high || point.lat == null || point.lon == null) return
    const tooltip = `相对高值 · ${point.tooltip || point.name}`
    let entry = boundaryEntries.get(i)
    if (!entry) {
      const halo = L.circle([point.lat, point.lon], {
        radius: 0,
        color: '#fb7185',
        weight: 2,
        dashArray: '7 5',
        opacity: 0.95,
        fill: true,
        fillColor: '#ef4444',
        fillOpacity: 0.08,
        interactive: true
      })
      halo.bindTooltip(tooltip, { direction: 'top' })
      halo.addTo(fieldBoundaryLayer)
      entry = { circle: halo, radius: 0, tooltip, handle: null }
      boundaryEntries.set(i, entry)
      entry.handle = fieldTweens.run({
        duration: FIELD_TWEEN_MS,
        delay: staggerDelay(i, FIELD_STAGGER_MS),
        from: [0],
        to: [7200],
        update: (vals) => {
          entry.radius = vals[0]
          entry.circle.setRadius(vals[0])
        }
      })
    } else {
      syncCircleTooltip(entry.circle, entry, tooltip, { direction: 'top' })
      syncCircleLatLng(entry.circle, point.lat, point.lon)
      // scale-in 补间若仍在进行中，从当前半径续接到目标
      if (Math.abs(entry.radius - 7200) > 0.5) {
        if (entry.handle) entry.handle.cancel()
        entry.handle = fieldTweens.run({
          duration: FIELD_TWEEN_MS,
          delay: staggerDelay(i, FIELD_STAGGER_MS),
          from: [entry.radius],
          to: [7200],
          update: (vals) => {
            entry.radius = vals[0]
            entry.circle.setRadius(vals[0])
          }
        })
      }
    }
  })
}

/* ============================================================
   观测站点：innerHTML 整体重建 → 按「站点 id」对账 + 局部过渡
   （同 id 保留同一 DOM：颜色 rAF 插值 --mc，强调/选中态走 CSS
   transform transition；跨浏览器最可靠的方案）
   ============================================================ */
function createMarkerIcon(point) {
  const color = point.color || '#5fd6a4'
  const active = point.id && point.id === props.activeId
  const root = document.createElement('div')
  root.className = 'rs-dot-marker'
  root.style.setProperty('--mc', color)
  // 环比变化点放大突出；选中站点进一步放大高亮
  if (point.emphasized) root.classList.add('rs-dot-marker--emph')
  if (active) root.classList.add('rs-dot-marker--active')
  // 新标记淡入（CSS 动画；reduced-motion 下禁用）
  root.classList.add('rs-dot-marker--in')
  const ring = document.createElement('div')
  ring.className = 'rs-dot-ring'
  const dot = document.createElement('div')
  dot.className = 'rs-dot-core'
  root.append(ring, dot)
  return L.divIcon({ className: 'rs-dot-wrapper', html: root, iconSize: [0, 0], iconAnchor: [0, 0] })
}

// 稳定站点 key：优先 id；无 id / id 重复时回退到索引
function markerKeyMap(points) {
  const keys = new Map() // key → 索引
  const used = new Set()
  points.forEach((point, i) => {
    if (!point.coord) return
    let key = point.id != null && point.id !== '' ? `id:${point.id}` : `idx:${i}`
    if (used.has(key)) key = `idx:${i}`
    used.add(key)
    keys.set(key, i)
  })
  return keys
}

function addMarkers() {
  if (!map) return
  const points = props.points
  if (!props.pointsVisible || !points.length) {
    markerTweens.cancelAll()
    markerEntries.forEach(({ marker }) => map.removeLayer(marker))
    markerEntries.clear()
    return
  }
  const nextKeys = markerKeyMap(points)
  // 移除消失的站点（先取消其颜色补间令牌）
  for (const [key, entry] of Array.from(markerEntries)) {
    if (!nextKeys.has(key)) {
      if (entry.handle) entry.handle.cancel()
      map.removeLayer(entry.marker)
      markerEntries.delete(key)
    }
  }
  nextKeys.forEach((index, key) => {
    const point = points[index]
    const color = point.color || '#5fd6a4'
    const targetRgb = colorToRgb(color)
    const active = point.id && point.id === props.activeId
    const tooltip = point.tooltip || ''
    let entry = markerEntries.get(key)
    if (!entry) {
      const marker = L.marker([point.coord.lat, point.coord.lon], { icon: createMarkerIcon(point), keyboard: false })
      if (tooltip) {
        marker.bindTooltip(tooltip, { direction: 'top', offset: [0, -12] })
      }
      // 站点可点击：预测推演中点击切换为站点视图（由父级决定行为）
      marker.addTo(map)
      const wrapperEl = marker.getElement()
      const root = wrapperEl ? wrapperEl.querySelector('.rs-dot-marker') : null
      entry = { marker, root, point, rgb: targetRgb, color, tooltip, handle: null }
      markerEntries.set(key, entry)
      marker.on('click', () => emit('point-click', entry.point && entry.point.id))
    } else {
      entry.point = point // 同 key 复用标记时保持点击回传最新数据
      syncCircleLatLng(entry.marker, point.coord.lat, point.coord.lon)
      if (entry.tooltip !== tooltip) {
        const bound = entry.marker.getTooltip()
        if (tooltip) {
          if (bound) entry.marker.setTooltipContent(tooltip)
          else entry.marker.bindTooltip(tooltip, { direction: 'top', offset: [0, -12] })
        } else if (bound) {
          entry.marker.unbindTooltip()
        }
        entry.tooltip = tooltip
      }
      if (entry.root) {
        // 强调/选中态：class 切换 + CSS transform transition 平滑缩放
        entry.root.classList.toggle('rs-dot-marker--emph', !!point.emphasized)
        entry.root.classList.toggle('rs-dot-marker--active', !!active)
      }
      if (entry.color !== color) {
        entry.color = color
        if (!targetRgb || !entry.rgb) {
          // 色值无法解析：跳过插值，直接落新真实色（不猜测）
          if (entry.handle) entry.handle.cancel()
          entry.rgb = targetRgb
          if (entry.root) entry.root.style.setProperty('--mc', color)
        }
      }
      // 以「当前显示色」与目标色的差值判断（含上一轮补间被取消的中间态），
      // 需要过渡时先取消该条目旧令牌，再从当前显示值续接新补间
      const colorNeedsWork = targetRgb && entry.rgb
        ? entry.rgb.some((v, c) => Math.abs(v - targetRgb[c]) > 0.5)
        : entry.rgb !== targetRgb
      if (colorNeedsWork) {
        if (entry.handle) entry.handle.cancel()
        if (!targetRgb || !entry.rgb) {
          entry.rgb = targetRgb
          if (entry.root) entry.root.style.setProperty('--mc', color)
        } else {
          const fromRgb = entry.rgb.slice()
          const rootEl = entry.root
          entry.handle = markerTweens.run({
            duration: MARKER_COLOR_MS,
            from: fromRgb,
            to: targetRgb,
            update: (vals) => {
              entry.rgb = vals
              if (rootEl) rootEl.style.setProperty('--mc', rgbToCss(vals))
            }
          })
        }
      }
    }
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
  // 透明度调节保持即时生效（不参与淡化动画）
  overlaySlotA.setOpacity(value)
  overlaySlotB.setOpacity(value)
})
watch(() => props.points, addMarkers, { deep: true })
watch(() => props.pointsVisible, () => {
  addMarkers()
})
watch(() => props.fieldPoints, updateField, { deep: true })
watch(() => [props.fieldVisible, props.boundaryVisible], updateField)
watch(() => props.fieldBoundary, updateField, { deep: true })
// 选中站点变化：只更新点位图标状态（CSS 过渡高亮），不重建地图
watch(() => props.activeId, addMarkers)
watch(() => props.hull, rebuildHull, { deep: true })
watch(() => props.basemap, switchBasemap)
watch(() => props.resetToken, fitBounds)

defineExpose({ retryTiles, fitBounds })

onMounted(initMap)

onBeforeUnmount(() => {
  // 全清 rAF 动画与影像补间，防串扰/泄漏
  fieldTweens.destroy()
  markerTweens.destroy()
  overlaySlotA.destroy()
  overlaySlotB.destroy()
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
.rs-hull-label {
  background: none !important;
  border: none !important;
}
.rs-hull-label span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  min-height: 24px;
  border: 1px solid rgba(251, 113, 133, 0.8);
  border-radius: 999px;
  background: rgba(69, 10, 22, 0.86);
  color: #fecdd3;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 0 18px rgba(239, 68, 68, 0.28);
}
.rs-dot-marker {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  /* 强调/选中态切换（scale 1 / 1.3 / 1.45）平滑缩放 */
  transition: transform 280ms var(--ease-out, cubic-bezier(0.16, 1, 0.3, 1));
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
/* 环比变化点（红升/绿降）：放大一档，与持平/缺测的灰点拉开层次 */
.rs-dot-marker--emph {
  transform: scale(1.3);
}
.rs-dot-marker--emph .rs-dot-ring {
  opacity: 0.9;
}
/* 选中站点（预测推演站点视图）：放大并加强光圈 */
.rs-dot-marker--active {
  transform: scale(1.45);
}
.rs-dot-marker--active .rs-dot-ring {
  opacity: 1;
  border-width: 3px;
  animation: rs-active-pulse 1.6s ease-out infinite;
}
@keyframes rs-active-pulse {
  0% { box-shadow: 0 0 6px var(--mc); }
  50% { box-shadow: 0 0 16px var(--mc); }
  100% { box-shadow: 0 0 6px var(--mc); }
}
/* ===== T2 过渡动画 ===== */
/* 新站点标记淡入（240ms，一次） */
.rs-dot-marker--in {
  animation: rs-dot-in 240ms ease-out both;
}
@keyframes rs-dot-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
/* 高值场点呼吸光晕：辉光色走语义令牌（--c-alert 珊瑚红 / --c-watch 琥珀），
   随 data-theme 三主题联动；呼吸作用于元素 opacity，与 fillOpacity 独立 */
.rs-field-halo {
  fill: var(--c-alert, #ef4444);
  animation: rs-field-breathe 2.6s ease-in-out infinite;
  transition: fill 400ms;
}
.rs-field-halo--watch {
  fill: var(--c-watch, #f59e0b);
}
@keyframes rs-field-breathe {
  0%, 100% { opacity: 0.35; }
  50% { opacity: 0.9; }
}
/* 无动画偏好：站点缩放/淡入、光晕呼吸全部静态化 */
@media (prefers-reduced-motion: reduce) {
  .rs-dot-marker {
    transition: none;
  }
  .rs-dot-marker--in {
    animation: none;
  }
  .rs-field-halo {
    animation: none;
    opacity: 0.55;
  }
}
</style>
