<template>
  <main class="page-stations">
    <div class="stn-body">
      <!-- ===== 标题区 ===== -->
      <header class="stn-title" aria-label="监测站点研判标题与数据身份">
        <div class="stn-title-left">
          <BackLink :to="cockpitLink" label="返回驾驶舱" class="stn-back" />
          <div class="stn-title-text">
            <p class="stn-kicker">P03 · STATION ASSESSMENT</p>
            <h1>监测站点研判</h1>
            <p class="stn-sub">当前对象为太湖演示分区，用于前后端联调和功能演示，不代表真实监测站。</p>
          </div>
        </div>
        <div class="stn-title-right">
          <div class="stn-chips">
            <span v-if="selectedEntity" class="stn-chip stn-chip--zone">
              {{ selectedEntity.short }} · {{ selectedEntity.display_name }}
            </span>
            <span class="stn-chip stn-chip--notice">SIMULATED</span>
            <span class="stn-chip">{{ obsVersion }}</span>
            <span class="stn-chip stn-chip--notice">非决策用途</span>
            <span class="stn-chip">档位 <b>{{ stageShortLabel }}</b></span>
            <span class="stn-chip">基准 <b>{{ dataIdentity.asOfFull }}</b></span>
          </div>
          <div class="stn-stage-row" role="group" aria-label="预测档位切换">
            <button
              v-for="key in stageKeys"
              :key="key"
              type="button"
              class="stn-stage-btn"
              :class="{ active: store.stageKey === key, blocked: key === 't30' }"
              :aria-pressed="String(store.stageKey === key)"
              @click="store.stageKey = key"
            >
              {{ stageShort(key) }}
              <small v-if="key === 't30'">模拟预演</small>
            </button>
          </div>
        </div>
      </header>

      <!-- ===== 左栏：搜索 / 筛选 / 列表 ===== -->
      <div class="stn-col stn-col-left">
        <ZoneListPanel
          class="stn-area-list"
          :rows="filteredRows"
          :selected-id="store.selectedPoint"
          :state="listState"
          :filter="zoneFilter"
          @update:search="zoneSearch = $event"
          @update:filter="zoneFilter = $event"
          @select="store.selectedPoint = $event"
          @retry="fetchEntities"
          @reset-filters="resetFilters"
        />
      </div>

      <!-- ===== 中栏：地图 + 趋势 ===== -->
      <div class="stn-col stn-col-mid">
        <section class="stn-block stn-map-block" aria-label="太湖演示分区地图">
        <div class="stn-map-tools">
          <div class="stn-layer-toggles" role="group" aria-label="地图图层开关">
            <button type="button" :aria-pressed="String(showPoints)" @click="showPoints = !showPoints">分区点</button>
            <button type="button" :aria-pressed="String(showHeat)" @click="showHeat = !showHeat">风险面</button>
          </div>
          <span class="stn-map-flag">风险面 · 演示数据</span>
          <span v-if="heatError" class="stn-map-flag stn-map-flag--warn" role="status">
            风险面数据加载失败
            <button type="button" class="stn-inline-btn" @click="fetchHeat">重试</button>
          </span>
          <span v-if="tileError" class="stn-map-flag stn-map-flag--warn" role="status">
            地图瓦片加载失败
            <button type="button" class="stn-inline-btn" @click="retryTiles">重试图层</button>
          </span>
        </div>
        <div class="stn-map-wrap">
          <LakeMap
            ref="mapRef"
            :model-value="store.selectedPoint"
            :point-list="mapPoints"
            :heat-field="heatField"
            :heat-stage-key="store.stageKey"
            :stage-label="`当前档位 ${stageShortLabel} · 演示数据`"
            title="太湖演示分区 · 风险研判"
            :show-tabs="false"
            :points-visible="showPoints"
            :heat-visible="showHeat"
            heat-all-layers
            :reset-token="resetToken"
            @update:model-value="store.selectedPoint = $event"
            @tile-error="onTileError"
          />
        </div>
      </section>

      <!-- ===== 中栏下部：趋势 ===== -->
        <ZoneTrendPanel
          class="stn-area-trend"
          :observations="observations"
          :state="obsState"
          :refreshing="refreshing"
          @retry="fetchObs"
        />
      </div>

      <!-- ===== 右栏：档案 / 指标 / 质量 / 预测 / 事件 ===== -->
      <div class="stn-col stn-col-right">
        <ZoneBriefPanel
          class="stn-area-brief"
          :entity="selectedEntity"
          :entity-state="entitiesState"
          :observations="observations"
          :obs-state="obsState"
          :quality="quality"
          :quality-state="qualityState"
          :forecast="selectedForecast"
          :forecast-state="selectedForecast || stageKey === 't30' ? 'ok' : rankStateForBrief"
          :stage-key="stageKey"
          :stage-short-label="stageShortLabel"
          :obs-version="obsVersion"
          :pred-version="predVersion"
          :brief-refreshing="refreshing"
          @retry-entity="fetchEntities"
          @retry-obs="fetchObs"
          @retry-quality="fetchQuality"
          @retry-forecast="fetchRanking"
        />

        <ZoneEventsPanel
          class="stn-area-events"
          :events="selectedEvents"
          :events-state="eventsState"
          :warning-busy="warnBusy"
          :warning-result="warnResult"
          :warning-error="warnError"
          @retry-events="fetchEvents"
          @warn="openWarning"
        />
      </div>

      <!-- ===== 底部三 Tab ===== -->
      <StationTabs
        class="stn-area-tabs"
        :observations="observations"
        :forecast="selectedForecast"
        :stage-key="stageKey"
        :stage-short-label="stageShortLabel"
        :quality="quality"
        :explanation="explanation"
        :explain-state="explainState"
        :explain-error="explainError"
        :obs-version="obsVersion"
        :pred-version="predVersion"
        :as-of="dataIdentity.asOfFull"
        @retry-explain="fetchExplain"
      />
    </div>

    <!-- ===== 移动端底部操作栏 ===== -->
    <Teleport to="body" :disabled="!isMobileViewport">
      <nav class="stn-mobile-bar" aria-label="移动端操作栏">
        <RouterLink class="stn-mb-btn" :to="cockpitLink">返回驾驶舱</RouterLink>
        <button ref="drawerTriggerRef" type="button" class="stn-mb-btn" data-role="drawer-trigger" @click="openDrawer">切换分区</button>
        <button type="button" class="stn-mb-btn stn-mb-btn--warn" data-role="warn-trigger" :disabled="warnBusy" @click="openWarning">模拟预警</button>
      </nav>
    </Teleport>

    <WarningDialog
      :open="warnOpen"
      :zone-name="selectedEntity ? `${selectedEntity.short} ${selectedEntity.display_name}` : ''"
      :busy="warnBusy"
      :error="warnError"
      @cancel="closeWarning"
      @confirm="confirmWarning"
    />

    <ZoneDrawer
      :open="drawerOpen"
      :rows="filteredRows"
      :selected-id="store.selectedPoint"
      @close="closeDrawer"
      @select="store.selectedPoint = $event"
    />
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cockpitState, useCockpitStore } from '../stores/cockpit.js'
import {
  getEntityObservations,
  getEntityQuality,
  getEventsEnvelope,
  getExplanationEnvelope,
  getForecastsEnvelope,
  getHeatField,
  getSpatialEntities,
  handleWarning
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import ZoneListPanel from '../components/stations/ZoneListPanel.vue'
import ZoneTrendPanel from '../components/stations/ZoneTrendPanel.vue'
import ZoneBriefPanel from '../components/stations/ZoneBriefPanel.vue'
import ZoneEventsPanel from '../components/stations/ZoneEventsPanel.vue'
import StationTabs from '../components/stations/StationTabs.vue'
import WarningDialog from '../components/stations/WarningDialog.vue'
import ZoneDrawer from '../components/stations/ZoneDrawer.vue'
import { dataIdentity } from '../data/dataIdentity.js'
import {
  RISK_ORDER,
  RISK_TEXT,
  STAGE_KEYS,
  positionToCoord,
  stageDays,
  stageShort
} from '../components/stations/stationDisplay.js'

const router = useRouter()
const route = useRoute()
useCockpitStore() // 绑定 URL 双向同步
const store = cockpitState() // 可写视图（t / p 已在 URL 中规范化）

const stageKeys = STAGE_KEYS

// ---------- 数据状态 ----------
const entities = ref([])
const entitiesState = ref('loading') // loading | error | ok
const rankForecasts = ref({}) // id -> forecast（当前档位）
const rankState = ref('loading')
const observations = ref([])
const obsState = ref('loading')
const obsMeta = ref({})
const quality = ref(null)
const qualityState = ref('loading')
const explanation = ref(null)
const explainState = ref('loading')
const explainError = ref('')
const eventsAll = ref([])
const eventsState = ref('loading')
const heatField = ref({})
const heatError = ref(false)
const refreshing = ref(false)

const predVersion = ref(dataIdentity.predictionRunId)

let rankToken = 0
// 观测与质量各自独立令牌：两者并发发起，不能共用一个自增计数器
let obsToken = 0
let qualityToken = 0
let explainToken = 0

// ---------- 档位 ----------
const stageKey = computed(() => store.stageKey)
const stageShortLabel = computed(() => stageShort(stageKey.value))

// ---------- 实体加载与 URL 规范化 ----------
async function fetchEntities() {
  entitiesState.value = 'loading'
  try {
    const { data } = await getSpatialEntities()
    entities.value = Array.isArray(data) ? data : []
    entitiesState.value = 'ok'
    resolveSelection()
    fetchRanking()
    fetchObs()
    fetchQuality()
  } catch {
    entitiesState.value = 'error'
  }
}

// 非法 p 回落到风险最高的有效分区；非法 t 由 store 校验，这里兜底强制规范，并显式回写 URL
function resolveSelection() {
  if (!entities.value.length) return
  if (!entities.value.some((e) => e.id === store.selectedPoint)) {
    const byRisk = entities.value
      .slice()
      .sort((a, b) => (RISK_ORDER[a.risk_hint] ?? 9) - (RISK_ORDER[b.risk_hint] ?? 9))
    store.selectedPoint = byRisk[0].id
  }
  if (!STAGE_KEYS.includes(store.stageKey)) store.stageKey = 't7'
  router.replace({ query: { ...route.query, t: store.stageKey, p: store.selectedPoint } }).catch(() => {})
}

// ---------- 当前档位排行（6 分区并行预测） ----------
async function fetchRanking() {
  const token = ++rankToken
  const stage = store.stageKey
  const ids = entities.value.map((e) => e.id)
  if (!ids.length) return
  if (stage === 't30') {
    // T+30 不调用正式预测接口：无分数、无解释，页面显示能力阻塞
    rankForecasts.value = {}
    rankState.value = 'ok'
    return
  }
  rankState.value = 'loading'
  try {
    const results = await Promise.all(ids.map((id) => getForecastsEnvelope(id, stageDays(stage))))
    if (token !== rankToken) return
    const map = {}
    results.forEach(({ data, meta }) => {
      const fc = Array.isArray(data) ? data[0] : null
      if (fc && fc.spatial_entity_id) map[fc.spatial_entity_id] = fc
      if (meta && meta.dataset_version) predVersion.value = meta.dataset_version
    })
    rankForecasts.value = map
    rankState.value = 'ok'
  } catch {
    if (token !== rankToken) return
    // 失败时清空残值：不允许旧档位/旧结果在错误态下继续展示
    rankForecasts.value = {}
    rankState.value = 'error'
  }
}

// ---------- 选中分区数据 ----------
async function fetchObs() {
  const token = ++obsToken
  const id = store.selectedPoint
  if (!id) return
  observations.value = []
  obsMeta.value = {}
  obsState.value = 'loading'
  refreshing.value = true
  try {
    const { data, meta } = await getEntityObservations(id)
    if (token !== obsToken) return
    observations.value = Array.isArray(data) ? data : []
    obsMeta.value = meta || {}
    obsState.value = 'ok'
  } catch {
    if (token !== obsToken) return
    obsState.value = 'error'
  } finally {
    if (token === obsToken) refreshing.value = false
  }
}

async function fetchQuality() {
  const token = ++qualityToken
  const id = store.selectedPoint
  if (!id) return
  quality.value = null
  qualityState.value = 'loading'
  try {
    const { data } = await getEntityQuality(id)
    if (token !== qualityToken) return
    quality.value = data || null
    qualityState.value = 'ok'
  } catch {
    if (token !== qualityToken) return
    qualityState.value = 'error'
  }
}

const selectedForecast = computed(() => rankForecasts.value[store.selectedPoint] || null)

async function fetchExplain() {
  const token = ++explainToken
  const fc = selectedForecast.value
  if (!fc || !fc.id || store.stageKey === 't30') {
    explanation.value = null
    explainState.value = 'ok'
    explainError.value = ''
    return
  }
  explainState.value = explanation.value ? 'loading' : 'loading'
  try {
    const { data } = await getExplanationEnvelope(fc.id)
    if (token !== explainToken) return
    explanation.value = data || null
    explainState.value = 'ok'
    explainError.value = ''
  } catch (err) {
    if (token !== explainToken) return
    explanation.value = null
    explainState.value = 'error'
    explainError.value = err && err.message ? err.message : '解释接口请求失败'
  }
}

// ---------- 事件 ----------
async function fetchEvents() {
  eventsState.value = 'loading'
  try {
    const { data } = await getEventsEnvelope()
    eventsAll.value = Array.isArray(data) ? data : []
    eventsState.value = 'ok'
  } catch {
    eventsState.value = 'error'
  }
}

// ---------- 风险面 ----------
async function fetchHeat() {
  heatError.value = false
  try {
    heatField.value = await getHeatField()
  } catch {
    heatField.value = {}
    heatError.value = true
  }
}

// ---------- 联动与筛选 ----------
const rankRows = computed(() => {
  const fcs = rankForecasts.value
  const rows = entities.value.map((e) => {
    const fc = fcs[e.id] || null
    const riskClass = fc ? fc.risk_level : (e.risk_hint || 'low')
    return {
      id: e.id,
      short: e.short,
      name: e.display_name,
      riskClass,
      score: fc ? fc.risk_score : null,
      riskText: RISK_TEXT[riskClass] || riskClass
    }
  })
  rows.sort((a, b) => {
    if (a.score != null && b.score != null) return b.score - a.score
    if (a.score != null) return -1
    if (b.score != null) return 1
    return (RISK_ORDER[a.riskClass] ?? 9) - (RISK_ORDER[b.riskClass] ?? 9)
  })
  rows.forEach((r, i) => { r.rank = i + 1 })
  return rows
})

const zoneSearch = ref('')
const zoneFilter = ref('all')

const filteredRows = computed(() => {
  const kw = zoneSearch.value.trim().toLowerCase()
  return rankRows.value.filter((row) => {
    if (zoneFilter.value !== 'all' && row.riskClass !== zoneFilter.value) return false
    if (kw && !(row.short.toLowerCase().includes(kw) || String(row.name).toLowerCase().includes(kw))) return false
    return true
  })
})

function resetFilters() {
  zoneSearch.value = ''
  zoneFilter.value = 'all'
}

const listState = computed(() => {
  if (entitiesState.value === 'loading' && !entities.value.length) return 'loading'
  if (entitiesState.value === 'error') return 'error'
  return 'ok'
})

const selectedEntity = computed(() => entities.value.find((e) => e.id === store.selectedPoint) || null)
const selectedEvents = computed(() => eventsAll.value.filter((ev) => ev.spatial_entity_id === store.selectedPoint))

const mapPoints = computed(() => entities.value.map((e) => {
  const row = rankRows.value.find((r) => r.id === e.id)
  return {
    id: e.id,
    short: e.short,
    name: e.display_name,
    riskClass: row ? row.riskClass : (e.risk_hint || 'low'),
    coord: positionToCoord(e.position)
  }
}).filter((p) => p.coord))

const obsVersion = computed(() => (obsMeta.value && obsMeta.value.dataset_version) || dataIdentity.datasetVersionId)
const rankStateForBrief = computed(() => (rankState.value === 'error' ? 'error' : 'loading'))

const cockpitLink = computed(() => ({
  path: '/cockpit',
  query: { t: store.stageKey, p: store.selectedPoint }
}))

// ---------- 地图交互 ----------
const mapRef = ref(null)
const showPoints = ref(true)
const showHeat = ref(true)
const tileError = ref(false)
const resetToken = ref(0)

function onTileError(v) {
  tileError.value = v
}
function retryTiles() {
  mapRef.value && mapRef.value.retryTiles && mapRef.value.retryTiles()
}

// 列表选中滚入可见区域（地图/抽屉驱动选择时）
watch(() => store.selectedPoint, async (id, old) => {
  if (id === old) return
  await nextTick()
  const el = document.querySelector('.stn-zone-item.selected')
  if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
})

// ---------- 数据刷新联动 ----------
watch(() => store.stageKey, (key, old) => {
  if (key === old) return
  warnResult.value = null
  // 档位切换立即隔离旧档位数据：预测/解释在新档位响应到达前不得沿用，
  // 请求失败也不得被旧档位残值掩盖（否则 brief 会因存在旧 forecast 而误判 ok）
  rankForecasts.value = {}
  rankState.value = 'loading'
  explanation.value = null
  fetchRanking()
})
watch(() => store.selectedPoint, (id, old) => {
  if (id === old) return
  warnResult.value = null
  fetchObs()
  fetchQuality()
})
watch(selectedForecast, () => {
  fetchExplain()
})

// ---------- 模拟预警流程 ----------
const warnOpen = ref(false)
const warnBusy = ref(false)
const warnResult = ref(null)
const warnError = ref('')
let warnReturnFocus = null

function openWarning() {
  warnReturnFocus = document.activeElement
  warnError.value = ''
  warnOpen.value = true
}
function closeWarning() {
  warnOpen.value = false
  if (warnReturnFocus && warnReturnFocus.focus) warnReturnFocus.focus()
  warnReturnFocus = null
}
async function confirmWarning() {
  warnBusy.value = true
  warnError.value = ''
  try {
    const eventId = (selectedEvents.value[0] && selectedEvents.value[0].id) || store.selectedPoint
    const data = await handleWarning(eventId)
    warnResult.value = data
    warnOpen.value = false
    if (warnReturnFocus && warnReturnFocus.focus) warnReturnFocus.focus()
    warnReturnFocus = null
  } catch (err) {
    warnError.value = err && err.message ? err.message : '调用失败'
  } finally {
    warnBusy.value = false
  }
}

// ---------- 移动端分区抽屉 ----------
const drawerOpen = ref(false)
const drawerTriggerRef = ref(null)
let drawerReturnFocus = null

function openDrawer() {
  // .click() 或触摸不保证触发按钮获得焦点，显式引用触发按钮
  drawerReturnFocus = drawerTriggerRef.value || document.activeElement
  drawerOpen.value = true
}
function closeDrawer() {
  drawerOpen.value = false
  if (drawerReturnFocus && drawerReturnFocus.focus) drawerReturnFocus.focus()
  drawerReturnFocus = null
}

watch([warnOpen, drawerOpen], ([w, d]) => {
  document.body.style.overflow = w || d ? 'hidden' : ''
})

// ≤960px 时底部操作栏 Teleport 到 body，避开 route-stage 入场动画对 fixed 定位的捕获
const mobileMq = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 960px)')
  : null
const isMobileViewport = ref(Boolean(mobileMq && mobileMq.matches))
function onMobileMqChange(e) {
  isMobileViewport.value = e.matches
}

onMounted(() => {
  fetchEntities()
  fetchEvents()
  fetchHeat()
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  mobileMq?.removeEventListener('change', onMobileMqChange)
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
  grid-template-columns: minmax(264px, 22fr) minmax(0, 53fr) minmax(296px, 25fr);
  grid-template-areas:
    'stitle stitle stitle'
    'sleft  smid   sright'
    'stabs  stabs  stabs';
  align-items: start;
  min-width: 0;
}

/* 三栏各自独立堆叠，行高不互相牵制 */
.stn-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.stn-col-left { grid-area: sleft; }
.stn-col-mid { grid-area: smid; }
.stn-col-right { grid-area: sright; }

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
.stn-title-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}
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
.stn-sub {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.stn-title-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  min-width: 0;
}
.stn-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.stn-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  font-size: 11px;
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.stn-chip b { color: var(--text-primary); font-weight: 600; }
.stn-chip--zone { color: var(--text-primary); }
.stn-chip--notice {
  border-color: color-mix(in srgb, var(--data-simulated, #f5b45d) 45%, transparent);
  color: var(--data-simulated, #f5b45d);
}
.stn-stage-row {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
}
.stn-stage-btn {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  min-height: 32px;
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.stn-stage-btn small { font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.05em; }
.stn-stage-btn:hover { color: var(--text-primary); }
.stn-stage-btn.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.stn-stage-btn.blocked.active {
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 12%, transparent);
  border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 45%, transparent);
}
.stn-stage-btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }

/* ---------- 区块区域分配 ---------- */
.stn-area-list { grid-area: slist; }
.stn-map-block { grid-area: smap; }
.stn-area-trend { grid-area: strend; }
.stn-area-brief { display: contents; }
.stn-area-events { grid-area: sevents; }
.stn-area-tabs { grid-area: stabs; }

/* ---------- 地图 ---------- */
.stn-map-block {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.stn-map-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.stn-layer-toggles {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
}
.stn-layer-toggles button {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}
.stn-layer-toggles button[aria-pressed='true'] {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.stn-layer-toggles button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
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
.stn-map-flag--warn {
  color: var(--risk-medium, #f5b45d);
  border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent);
}
.stn-map-wrap {
  min-width: 0;
}
.stn-map-wrap :deep(.map-panel) {
  min-height: 0;
  border: none;
  background: transparent;
  padding: 0;
}
.stn-map-wrap :deep(.leaflet-map-container) {
  /* flex:none 压过 LakeMap 自带的 flex:1（flex-basis 0 会吞掉显式高度） */
  flex: none;
  min-height: 0;
  height: clamp(260px, 26vh, 340px);
}
.stn-map-wrap :deep(.panel-head) { padding: 0 2px 8px; }

/* ---------- 移动端底部操作栏 ---------- */
.stn-mobile-bar {
  display: none;
}

/* ---------- 响应式 ---------- */
@media (max-width: 1280px) {
  .stn-body {
    grid-template-columns: minmax(232px, 24fr) minmax(0, 76fr);
    grid-template-areas:
      'stitle stitle'
      'sleft  smid'
      'sright sright'
      'stabs  stabs';
  }
}
@media (max-width: 960px) {
  .page-stations { padding: 12px 12px calc(84px + env(safe-area-inset-bottom, 0px)); }
  .stn-body {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'stitle'
      'sprofile'
      'smap'
      'smetrics'
      'strend'
      'stabs'
      'sevents'
      'squality'
      'sforecast';
  }
  /* 列容器打散，让各区块成为 body 的直接网格项参与排序 */
  .stn-col { display: contents; }
  .stn-area-brief { display: contents; }
  .stn-map-block { grid-area: smap; }
  .stn-area-trend { grid-area: strend; }
  .stn-area-tabs { grid-area: stabs; }
  .stn-sec-profile { grid-area: sprofile; }
  .stn-sec-metrics { grid-area: smetrics; }
  .stn-sec-quality { grid-area: squality; }
  .stn-sec-forecast { grid-area: sforecast; }
  .stn-area-events { grid-area: sevents; }
  .stn-area-list { display: none; }
  .stn-title-right { align-items: flex-start; }
  .stn-chips { justify-content: flex-start; }

  /* 触摸目标 ≥44×44 */
  .stn-stage-btn,
  .stn-chip,
  .stn-tab,
  .stn-layer-toggles button,
  .stn-filter button,
  .stn-inline-btn,
  .stn-search input {
    min-height: 44px;
  }

  .stn-mobile-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1500;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
    background: var(--surface-panel-strong, rgba(10, 20, 34, 0.96));
    border-top: 1px solid var(--border-subtle);
    backdrop-filter: blur(10px);
  }
  .stn-mb-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 8px 10px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-item, 10px);
    background: var(--surface-panel-soft);
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .stn-mb-btn--warn {
    border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 55%, transparent);
    color: var(--risk-critical, #ff6b6b);
    background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 10%, transparent);
  }
  .stn-mb-btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
}
@media (max-width: 640px) {
  .stn-map-wrap :deep(.leaflet-map-container) { height: 300px; }
  /* Leaflet 缩放按钮默认 30×30，不满足主要触摸目标 ≥44×44（R2 审计 finding） */
  .stn-map-wrap :deep(.leaflet-control-zoom a) {
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
.page-stations .stn-sec-head h2 {
  margin: 0;
  font-size: 13px;
  font-weight: 650;
  color: var(--text-primary);
}
.page-stations .stn-sec-tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.page-stations .stn-kv {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 3px 12px;
  margin: 0;
}
.page-stations .stn-kv dt {
  font-size: 11.5px;
  line-height: 1.4;
  color: var(--text-muted);
  white-space: nowrap;
}
.page-stations .stn-kv dd {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}
.page-stations .stn-mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.02em;
}
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
.page-stations .stn-none {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
  padding: 4px 0;
  margin: 0;
}
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

/* ZoneListPanel */
.page-stations .stn-search { position: relative; display: flex; }
.page-stations .stn-search input {
  width: 100%;
  min-height: 40px;
  padding: 8px 36px 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
}
.page-stations .stn-search input::placeholder { color: var(--text-muted); }
.page-stations .stn-search input:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
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
.page-stations .stn-search-row { margin-bottom: 8px; }
.page-stations .stn-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
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

.page-stations .stn-zone-list { display: grid; gap: 6px; }
.page-stations .stn-zone-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
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
.page-stations .zi-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.page-stations .zi-side { display: grid; gap: 2px; justify-items: end; }
.page-stations .zi-risk { font-size: 10.5px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-subtle); }
.page-stations .zi-risk.lv-high { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-risk.lv-mid { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-risk.lv-low { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.page-stations .zi-score { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-primary); }
.page-stations .stn-list-skeleton { display: grid; gap: 8px; }
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

/* ZoneTrendPanel 芯片 */
.page-stations .stn-chip-rows { display: grid; gap: 5px; margin-bottom: 6px; }
.page-stations .stn-chip-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
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
.page-stations .stn-chip small { font-size: 10px; color: var(--text-muted); font-weight: 500; }
.page-stations .stn-chip.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 48%, transparent);
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
}
.page-stations .stn-chip[aria-disabled='true'] { opacity: 0.45; cursor: not-allowed; }
.page-stations .stn-chip:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.page-stations .stn-chip--win { min-width: 52px; justify-content: center; }
/* 移动端触摸目标：需在同级特异性下后置声明才能覆盖上面的 30px */
@media (max-width: 960px) {
  .page-stations .stn-chip { min-height: 44px; }
}
.page-stations .stn-trend-note {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.6;
}
.page-stations .stn-trend-note--sparse {
  color: var(--risk-medium, #f5b45d);
}

/* StationTabs 表格 */
.page-stations .stn-table-wrap { overflow-x: auto; }
.page-stations .stn-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}
.page-stations .stn-table th,
.page-stations .stn-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
}
.page-stations .stn-table th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10.5px;
  letter-spacing: 0.05em;
}
.page-stations .stn-table td { color: var(--text-primary); }
.page-stations .stn-table tbody tr:hover { background: var(--surface-panel-soft); }
</style>
