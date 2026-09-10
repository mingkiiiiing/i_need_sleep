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
.rl {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rl-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.rl-head-text {
  flex: 1;
  min-width: 0;
}
.rl-head h3 {
  margin: 0;
  font-size: 14px;
}
.rl-head p {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.5;
}
.rl-month {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}
.rl-month select {
  background: var(--surface-panel-soft, rgba(255, 255, 255, 0.06));
  color: var(--text-primary);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
}
.rl-close {
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  width: 26px;
  height: 26px;
  cursor: pointer;
}
.rl-map-wrap {
  position: relative;
  height: 300px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
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
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(8, 16, 28, 0.82);
  color: var(--text-primary);
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.rl-flag--warn { color: #fbbf24; }
.rl-retry {
  border: none;
  background: transparent;
  color: #38bdf8;
  cursor: pointer;
  font-size: 11px;
}
.rl-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.rl-legend-bar {
  width: 120px;
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(90deg, #1d4ed8, #10b981, #fde047, #f97316, #dc2626);
}
.rl-legend-meta { margin-left: auto; }
.rl-calibration {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
</style>
