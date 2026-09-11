<template>
  <section class="rl" aria-label="V0.3 月度叶绿素 a 栅格场">
    <header class="rl-head">
      <div class="rl-head-text">
        <h3>V0.3 月度叶绿素 a 栅格场</h3>
        <p>
          月度反演重建基底：年度反演产品（固定色标反解）× 地面 / CLMS 月度锚点残差 IDW 修正，
          不随预测时效生成未来空间场；边界为 {{ field?.boundary?.threshold_ug_l ?? 20 }} μg/L 阈值分割。
        </p>
      </div>
      <label class="rl-month">
        <span>月份</span>
        <select v-model="selectedMonth" :disabled="months.length === 0" aria-label="选择栅格月份">
          <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <button v-if="closable" type="button" class="rl-close" aria-label="关闭栅格面板" @click="$emit('close')">✕</button>
    </header>

    <div class="rl-map-wrap">
      <div ref="mapRef" class="rl-map"></div>
      <span v-if="state === 'loading'" class="rl-flag">栅格图层加载中…</span>
      <span v-else-if="state === 'error'" class="rl-flag rl-flag--warn">
        {{ error || '栅格产物不可用' }}
        <button type="button" class="rl-retry" @click="load">重试</button>
      </span>
    </div>

    <div v-if="field" class="rl-legend" aria-label="栅格色带图例">
      <span class="rl-legend-min">{{ field.vmin }} {{ field.unit }}</span>
      <span class="rl-legend-bar"></span>
      <span class="rl-legend-max">≥ {{ field.vmax }} {{ field.unit }}</span>
      <span class="rl-legend-meta">
        产物月份 {{ field.issued_month }} · 年度基底 {{ field.year_base }} ·
        边界面积 {{ formatArea(field.boundary?.area_km2) }} km²
      </span>
    </div>
    <p v-if="field?.calibration" class="rl-calibration" data-role="raster-calibration">
      月度锚点校准：{{ field.calibration.status }}
      <template v-if="field.calibration.pair_count != null">（配对 {{ field.calibration.pair_count }} 对）</template>
      · 校准/反演值均为派生口径，不作为观测真值。
    </p>
  </section>
</template>

<script setup>
// V0.3 连续栅格空间场（P0-4 证据）：Leaflet ImageOverlay + 20 μg/L 边界 GeoJSON。
// 数据链：/model/spatial-field?layer=raster → /rs/monthly_v3/*.png + boundaries/*.geojson。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { getRasterFieldEnvelope, rsImageUrl } from '../../services/api.js'

const props = defineProps({
  horizonDays: { type: Number, default: 3 },
  // 与结果面板同一次预测运行的 prediction_run_id（仅作运行追踪串联）
  runId: { type: String, default: '' },
  closable: { type: Boolean, default: false }
})

defineEmits(['close'])

const state = ref('loading')
const error = ref('')
const field = ref(null)
const boundaryGeojson = ref(null)
const selectedMonth = ref('')

const months = computed(() => (field.value?.available_months || []).slice())
const activeMonth = computed(() => selectedMonth.value || field.value?.issued_month || '')

const mapRef = ref(null)
let map = null
let overlayLayer = null
let boundaryLayer = null
let resizeObserver = null

const LAKE_CENTER = [31.19, 120.15]
const DEFAULT_ZOOM = 10

function formatArea(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 1 })
}

function ensureMap() {
  if (map || !mapRef.value) return
  map = L.map(mapRef.value, {
    center: LAKE_CENTER,
    zoom: DEFAULT_ZOOM,
    minZoom: 9,
    maxZoom: 14,
    attributionControl: false
  })
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 14
  }).addTo(map)
  resizeObserver = new ResizeObserver(() => map && map.invalidateSize())
  resizeObserver.observe(mapRef.value)
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const { data } = await getRasterFieldEnvelope(props.horizonDays, 'chla', props.runId)
    field.value = { ...data, available_months: data.available_months || [] }
    // 后端只返回当前月份图层；可选月份清单由 availability 揭示（缺省仅当前月）
    if (!months.value.length && data.issued_month) {
      field.value.available_months = [data.issued_month]
    }
    selectedMonth.value = data.issued_month || ''
    state.value = 'ok'
    await render()
  } catch (err) {
    state.value = 'error'
    error.value = err?.message || '栅格产物不可用'
  }
}

async function loadBoundary(month) {
  if (!month) return
  // 边界 GeoJSON 直接走静态 /rs 路径（与 png 同目录）
  const base = rsImageUrl(`monthly_v3/boundaries/chla_${month}.geojson`)
  try {
    const response = await fetch(base)
    if (!response.ok) throw new Error(`边界请求失败：${response.status}`)
    boundaryGeojson.value = await response.json()
  } catch {
    boundaryGeojson.value = null
  }
}

async function render() {
  ensureMap()
  if (!map || !field.value) return
  if (overlayLayer) {
    map.removeLayer(overlayLayer)
    overlayLayer = null
  }
  if (boundaryLayer) {
    map.removeLayer(boundaryLayer)
    boundaryLayer = null
  }
  const month = activeMonth.value
  if (!month) return
  const pngUrl = rsImageUrl(`monthly_v3/chla_${month}.png`)
  try {
    overlayLayer = L.imageOverlay(pngUrl, field.value.bounds, { opacity: 0.82 }).addTo(map)
  } catch {
    /* PNG 缺失时保留底图，由边界层兜底 */
  }
  await loadBoundary(month)
  if (boundaryGeojson.value) {
    boundaryLayer = L.geoJSON(boundaryGeojson.value, {
      style: () => ({ color: '#38bdf8', weight: 1.2, fillOpacity: 0.08 })
    }).addTo(map)
  }
  if (field.value.bounds) map.fitBounds(field.value.bounds, { padding: [12, 12] })
}

watch(selectedMonth, () => {
  if (state.value === 'ok') render()
})

// 时效变化 → 以对应时效重取图层元数据（栅格本身仍是月度反演基底，由后端披露）
watch(() => props.horizonDays, () => {
  load()
})

onMounted(load)
onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (map) {
    map.remove()
    map = null
  }
})
</script>

<style scoped>
/* 间距节奏统一为 8 / 12 / 16 阶；圆角对齐 --radius-md。 */
.rl {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* —— 头部：负边距出血 + 毛玻璃强化 + 底部虚线 —— */
.rl-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: -14px -14px 0;
  padding: 12px 14px;
  background: var(--glass-bg-strong, rgba(20, 36, 56, 0.52));
  -webkit-backdrop-filter: blur(var(--glass-blur, 22px)) saturate(var(--glass-saturate, 150%));
  backdrop-filter: blur(var(--glass-blur, 22px)) saturate(var(--glass-saturate, 150%));
  border-bottom: 1px dashed var(--border-subtle, rgba(34, 211, 238, 0.18));
  border-radius: calc(var(--radius-md, 14px) - 1px) calc(var(--radius-md, 14px) - 1px) 0 0;
}
.rl-head-text {
  flex: 1;
  min-width: 0;
}
.rl-head h3 {
  position: relative;
  margin: 0;
  padding-left: 11px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.rl-head h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 2px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-primary, #22d3ee);
}
.rl-head p {
  margin: 5px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.55;
}
.rl-month {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.rl-month select {
  min-height: 30px;
  background: var(--surface-panel-soft, rgba(122, 172, 205, 0.08));
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 8px);
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}
.rl-month select:focus {
  outline: none;
  border-color: var(--color-primary, #22d3ee);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary, #22d3ee) 32%, transparent);
}

/* —— 关闭钮：44px 触摸目标，hover 主色描边 —— */
.rl-close {
  flex: none;
  width: 44px;
  height: 44px;
  margin: -7px -7px -7px 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  border-radius: var(--radius-item, 8px);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}
.rl-close:focus-visible {
  outline: 2px solid var(--color-primary, #22d3ee);
  outline-offset: 1px;
}

.rl-map-wrap {
  position: relative;
  height: 300px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 10px);
  overflow: hidden;
}
.rl-map {
  position: absolute;
  inset: 0;
}
.rl-flag {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 500;
  max-width: calc(100% - 20px);
  padding: 6px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 8px);
  background: color-mix(in srgb, var(--surface-panel-raised, rgba(9, 28, 48, 0.94)) 90%, transparent);
  -webkit-backdrop-filter: blur(var(--glass-blur, 22px));
  backdrop-filter: blur(var(--glass-blur, 22px));
  color: var(--text-primary);
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.rl-flag--warn {
  color: var(--c-watch, #f5b45d);
}
.rl-retry {
  border: 1px solid color-mix(in srgb, var(--color-primary, #22d3ee) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary, #22d3ee) 10%, transparent);
  color: var(--color-primary, #22d3ee);
  border-radius: var(--radius-item, 8px);
  padding: 3px 10px;
  min-height: 26px;
  cursor: pointer;
  font-size: 11px;
}
.rl-retry:focus-visible {
  outline: 2px solid var(--color-primary, #22d3ee);
  outline-offset: 1px;
}

.rl-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.rl-legend-min,
.rl-legend-max,
.rl-legend-meta {
  font-family: var(--font-mono);
}
.rl-legend-bar {
  width: 120px;
  height: 8px;
  border-radius: 4px;
  /* 固定色标与栅格产物色带对应；--data-observed / --risk-* 均为主题无关令牌，三主题下不漂移 */
  background: linear-gradient(90deg,
    var(--data-observed, #3b82f6),
    var(--risk-low, #22c55e),
    var(--risk-medium, #facc15),
    var(--risk-high, #f97316),
    var(--risk-critical, #ef4444));
  border: 1px solid color-mix(in srgb, var(--text-primary) 18%, transparent);
}
.rl-legend-meta {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 10.5px;
}
.rl-calibration {
  margin: 0;
  padding-top: 10px;
  border-top: 1px dashed var(--border-subtle, rgba(34, 211, 238, 0.18));
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.55;
}

/* hover / 过渡：仅 reduced-motion: no-preference 下启用 */
@media (prefers-reduced-motion: no-preference) {
  .rl-month select,
  .rl-retry {
    transition: background-color 180ms var(--ease-out, ease-out),
      border-color 180ms var(--ease-out, ease-out),
      color 180ms var(--ease-out, ease-out),
      box-shadow 180ms var(--ease-out, ease-out);
  }
  .rl-close {
    transition: background-color 180ms var(--ease-out, ease-out),
      border-color 180ms var(--ease-out, ease-out),
      color 180ms var(--ease-out, ease-out);
  }
  .rl-close:hover {
    border-color: color-mix(in srgb, var(--color-primary, #22d3ee) 58%, transparent);
    background: color-mix(in srgb, var(--color-primary, #22d3ee) 10%, transparent);
    color: var(--color-primary, #22d3ee);
  }
  .rl-retry:hover {
    background: color-mix(in srgb, var(--color-primary, #22d3ee) 18%, transparent);
  }
  .rl-month select:hover:not(:disabled):not(:focus) {
    border-color: color-mix(in srgb, var(--color-primary, #22d3ee) 40%, transparent);
  }
}

@media (max-width: 759px) {
  .rl-month select,
  .rl-retry {
    min-height: 44px;
  }
  .rl-head {
    flex-wrap: wrap;
  }
}
</style>
