<template>
  <main class="page-stations">
    <div class="stn-body">
      <!-- ===== 左栏：站点列表 ===== -->
      <div class="stn-col stn-col-left">
        <StationListPanel
          :stations="stations"
          :selected-id="selectedId"
          :state="stationsState"
          v-model:search="search"
          v-model:filter="statusFilter"
          v-model:location-filter="locationFilter"
          @select="selectStation"
          @retry="loadStations(true)"
          @reset-filters="resetFilters"
        />
      </div>

      <!-- ===== 中栏：地图 + 趋势 ===== -->
      <div class="stn-col stn-col-mid">
        <section class="stn-block stn-map-block" aria-label="实时站点地图">
          <div class="stn-map-tools">
            <span v-if="tileError" class="stn-map-flag stn-map-flag--warn" role="status">
              地图瓦片加载失败
              <button type="button" class="stn-inline-btn" @click="retryTiles">重试图层</button>
            </span>
          </div>
          <div class="stn-map-wrap">
      <LakeMap
        ref="mapRef"
        :model-value="selectedId"
        :point-list="mapPoints"
        title="太湖流域 · MEE 国控实时站点"
        :show-tabs="false"
        :show-legend="false"
        points-visible
        :reset-token="resetToken"
        @update:model-value="selectStation"
        @tile-error="onTileError"
      />
          </div>
        </section>

        <StationTrendPanel :station-id="selectedId" />
      </div>

      <!-- ===== 右栏：最新观测 + 数据质量 ===== -->
      <div class="stn-col stn-col-right">
        <StationObsCard
          :station-name="selectedStation ? selectedStation.source_station_name : ''"
          :observed-at="latestObservedAt"
          :rows="obsRows"
          :state="obsState"
          @retry="fetchObs"
        />
        <StationQualityCard :quality="quality" :state="qualityState" @retry="fetchQuality" />
      </div>

      <!-- ===== 底部：指标明细 / 情景推演（独立标签） ===== -->
      <StationDetailTabs class="stn-area-tabs" :rows="obsRows" />
    </div>
  </main>
</template>

<script setup>
// P03 监测站点研判（observed 轨改造版，大任务 2）：
// - 站点集合完全由最新成功快照决定，不再使用 demo_zone 情景分区；
// - 真实站点不再并行请求 6/79 次情景推演；情景推演收进独立标签页惰性加载；
// - 无可靠坐标（suspicious/missing）的站点只在列表出现，不生成假地图点位。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LakeMap from '../components/cockpit/LakeMap.vue'
import StationListPanel from '../components/stations/StationListPanel.vue'
import StationObsCard from '../components/stations/StationObsCard.vue'
import StationQualityCard from '../components/stations/StationQualityCard.vue'
import StationTrendPanel from '../components/stations/StationTrendPanel.vue'
import StationDetailTabs from '../components/stations/StationDetailTabs.vue'
import {
  fetchRealtimeStations,
  fetchStationObservations,
  fetchStationQuality,
  sortStationsByDataStatus,
  stationMapPoints
} from '../services/realtime.js'

const route = useRoute()
const router = useRouter()

// ---------- 数据状态 ----------
const stations = ref([])
const stationsState = ref('loading')
const obsRows = ref([])
const obsState = ref('loading')
const quality = ref(null)
const qualityState = ref('loading')

const search = ref('')
const statusFilter = ref('all')
const locationFilter = ref('all')

let obsToken = 0
let qualityToken = 0
let refreshTimer = null

// ---------- 站点目录 ----------
async function loadStations(force = false, silent = false) {
  if (!silent) stationsState.value = 'loading'
  try {
    stations.value = sortStationsByDataStatus(await fetchRealtimeStations({ force }))
    stationsState.value = 'ok'
    resolveSelection()
    // URL 恢复选中时 watch(selectedId) 不触发，初始必须显式拉取详情
    fetchObs(silent)
    fetchQuality(force, silent)
  } catch {
    stationsState.value = 'error'
  }
}

function resolveSelection() {
  const valid = stations.value.some((s) => s.id === selectedId.value)
  if (!valid && stations.value.length) {
    selectedId.value = stations.value[0].id
  }
  if (selectedId.value !== route.query.p) {
    router.replace({ query: { ...route.query, p: selectedId.value || undefined } }).catch(() => {})
  }
}

const selectedId = ref(typeof route.query.p === 'string' ? route.query.p : '')

function selectStation(id) {
  if (id && id !== selectedId.value) selectedId.value = id
}

const selectedStation = computed(() => stations.value.find((s) => s.id === selectedId.value) || null)
const latestObservedAt = computed(() => {
  const times = obsRows.value.map((r) => r.observed_at).filter(Boolean).sort()
  return times.length ? times[times.length - 1] : ''
})

// ---------- 选中站点观测与质量 ----------
async function fetchObs(silent = false) {
  const token = ++obsToken
  const id = selectedId.value
  if (!id) return
  if (!silent) {
    obsRows.value = []
    obsState.value = 'loading'
  }
  try {
    const rows = await fetchStationObservations(id, { window: 'latest' })
    if (token !== obsToken) return
    obsRows.value = rows
    obsState.value = 'ok'
  } catch {
    if (token !== obsToken) return
    obsState.value = 'error'
  }
}

async function fetchQuality(force = false, silent = false) {
  const token = ++qualityToken
  const id = selectedId.value
  if (!id) return
  if (!silent) {
    quality.value = null
    qualityState.value = 'loading'
  }
  try {
    const data = await fetchStationQuality(id, { force })
    if (token !== qualityToken) return
    quality.value = data
    qualityState.value = 'ok'
  } catch {
    if (token !== qualityToken) return
    qualityState.value = 'error'
  }
}

watch(selectedId, () => {
  fetchObs()
  fetchQuality()
  router.replace({ query: { ...route.query, p: selectedId.value || undefined } }).catch(() => {})
})

// ---------- 地图（真实坐标，规则见 realtime.stationMapPoints） ----------
const mapPoints = computed(() => stationMapPoints(stations.value))

const mapRef = ref(null)
const tileError = ref(false)
const resetToken = ref(0)
function onTileError(v) {
  tileError.value = v
}
function retryTiles() {
  mapRef.value && mapRef.value.retryTiles && mapRef.value.retryTiles()
}

function resetFilters() {
  search.value = ''
  statusFilter.value = 'all'
  locationFilter.value = 'all'
}

onMounted(() => loadStations())

onMounted(() => {
  refreshTimer = setInterval(() => loadStations(true, true), 60_000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.page-stations {
  max-width: 1720px;
  margin: 0 auto;
  padding: 12px 24px 32px;
  min-height: 100vh;
}

.stn-body {
  display: grid;
  gap: 10px;
  grid-template-columns: minmax(280px, 23fr) minmax(0, 52fr) minmax(300px, 25fr);
  grid-template-areas:
    'sleft  smid   sright'
    'stabs  stabs  stabs';
  align-items: start;
  min-width: 0;
}

.stn-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}
.stn-col-left { grid-area: sleft; }
.stn-col-mid { grid-area: smid; }
.stn-col-right { grid-area: sright; }
.stn-rtbar { grid-area: srtbar; }
.stn-area-tabs { grid-area: stabs; }

/* ---------- 标题区 ---------- */
.stn-title {
  grid-area: stitle;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px 18px;
  padding: 8px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.stn-title-left { display: flex; align-items: flex-start; gap: 14px; min-width: 0; }
.stn-back { flex: none; }
.stn-kicker {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.22em;
  color: var(--color-primary);
}
.stn-title h1 {
  margin: 2px 0;
  font-family: var(--font-display);
  font-size: clamp(19px, 2vw, 26px);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}
.stn-sub { font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.stn-title-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.stn-chips { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.stn-chip--zone { color: var(--text-primary); }

/* ---------- 地图 ---------- */
.stn-map-block {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.stn-map-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.stn-map-flag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 3px 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.stn-map-flag--warn { color: var(--risk-medium, #f5b45d); }
.stn-map-wrap { min-width: 0; }
.stn-map-wrap :deep(.map-panel) { min-height: 0; border: none; background: transparent; padding: 0; }
.stn-map-wrap :deep(.leaflet-map-container) {
  flex: none;
  min-height: 0;
  /* 主视图地图：中栏主体，保证太湖全湖与站点分布一目了然 */
  height: clamp(430px, 58vh, 700px);
}

/* ---------- 响应式 ---------- */
@media (max-width: 1280px) {
  .stn-body {
    grid-template-columns: minmax(250px, 30fr) minmax(0, 70fr);
    grid-template-areas:
      'sleft  smid'
      'sright sright'
      'stabs  stabs';
  }
}
@media (max-width: 960px) {
  .page-stations { padding: 12px 12px 32px; }
  .stn-body {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'sleft'
      'smap'
      'strend'
      'sright'
      'stabs';
  }
  .stn-col { display: contents; }
  .stn-map-block { grid-area: smap; }
  .stn-map-wrap :deep(.leaflet-map-container) { height: 340px; }
  .stn-title-right { align-items: flex-start; }
  .stn-chips { justify-content: flex-start; }
  /* 触摸目标 */
  .stn-filter button,
  .stn-inline-btn,
  .stn-chip { min-height: 44px; }
  .stn-map-wrap :deep(.leaflet-control-zoom a) {
    box-sizing: border-box;
    width: 44px;
    height: 44px;
    line-height: 44px;
  }
}
</style>

<style>
/* ===== P03 共享展示类（页面 chunk 内全局，stn- 前缀命名空间） ===== */

.page-stations .stn-block {
  padding: 9px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.page-stations .stn-sec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 5px;
}
.page-stations .stn-sec-head h2 { margin: 0; font-size: 13px; font-weight: 650; color: var(--text-primary); }
.page-stations .stn-sec-tag { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); white-space: nowrap; }
.page-stations .stn-kv { display: grid; grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr); gap: 3px 12px; margin: 0; }
.page-stations .stn-kv dt { font-size: 11.5px; line-height: 1.4; color: var(--text-muted); white-space: nowrap; }
.page-stations .stn-kv dd { margin: 0; font-size: 12px; line-height: 1.4; color: var(--text-primary); overflow-wrap: anywhere; }
.page-stations .stn-mono { font-family: var(--font-mono); font-size: 11.5px; letter-spacing: 0.02em; }
.page-stations .stn-inline-btn {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 4px 12px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.page-stations .stn-inline-btn:hover { filter: brightness(1.15); }
.page-stations .stn-inline-btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.page-stations .stn-list-skeleton { display: grid; gap: 8px; }
.page-stations .skel-row {
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--text-muted) 12%, transparent),
    color-mix(in srgb, var(--text-muted) 22%, transparent),
    color-mix(in srgb, var(--text-muted) 12%, transparent));
  background-size: 200% 100%;
  animation: stn-skel 1.4s ease-in-out infinite;
}
.page-stations .skel-row.short { width: 55%; }
@keyframes stn-skel {
  0% { background-position: 0% 0; }
  100% { background-position: -200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .page-stations .skel-row { animation: none; }
}
.page-stations .stn-list-empty {
  display: grid;
  gap: 8px;
  justify-items: start;
  padding: 14px 12px;
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
}
.page-stations .sle-title { font-size: 13px; font-weight: 650; color: var(--text-primary); margin: 0; }
.page-stations .sle-desc { font-size: 11.5px; color: var(--text-secondary); line-height: 1.6; margin: 0; }
.page-stations .stn-search-row { position: relative; display: flex; }
.page-stations .stn-search-clear {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font-size: 17px;
  cursor: pointer;
}
.page-stations .stn-search-clear:hover { color: var(--text-primary); }
.page-stations .stn-filter { display: flex; flex-wrap: wrap; gap: 6px; }
.page-stations .stn-filter button {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 11px;
  min-height: 30px;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.page-stations .stn-filter button.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
}
.page-stations .stn-filter button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.page-stations .stn-zone-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.page-stations .stn-zone-item {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 46px;
  padding: 5px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.page-stations .stn-zone-item:hover { border-color: color-mix(in srgb, var(--color-primary) 40%, transparent); }
.page-stations .stn-zone-item.selected {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-primary) 30%, transparent);
}
.page-stations .stn-zone-item:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.page-stations .zi-rank { font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); }
.page-stations .zi-main { display: grid; gap: 1px; min-width: 0; }
.page-stations .zi-code { font-family: var(--font-mono); font-size: 10.5px; color: var(--color-primary); letter-spacing: 0.06em; }
.page-stations .zi-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page-stations .zi-side { display: grid; gap: 2px; justify-items: end; }
.page-stations .zi-risk { font-size: 10.5px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-subtle); white-space: nowrap; }
.page-stations .zi-risk.lv-high { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-risk.lv-mid { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-risk.lv-low { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-score { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-primary); }
.page-stations .stn-chip {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 30px;
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.page-stations .stn-chip.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 48%, transparent);
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
}
.page-stations .stn-chip:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.page-stations .stn-trend-note { margin: 6px 0 0; font-size: 11px; color: var(--text-muted); line-height: 1.6; }
.page-stations .stn-trend-note--sparse { color: var(--risk-medium, #f5b45d); }
.page-stations .stn-table-wrap { overflow-x: auto; }
.page-stations .stn-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.page-stations .stn-table th,
.page-stations .stn-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
.page-stations .stn-table th { color: var(--text-muted); font-weight: 600; font-size: 10.5px; letter-spacing: 0.05em; }
.page-stations .stn-table td { color: var(--text-primary); }
.page-stations .stn-table tbody tr:hover { background: var(--surface-panel-soft); }
</style>
