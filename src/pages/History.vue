<template>
  <main class="page-history">
    <div class="his-body" :class="mobileBodyClass">
      <!-- ===== 标题区 ===== -->
      <header class="his-title" aria-label="历史事件与处置复盘标题与数据身份">
        <div class="his-title-left">
          <BackLink :to="cockpitLink" label="返回驾驶舱" />
          <div class="his-title-text">
            <p class="his-kicker">HISTORY · EVENT REVIEW</p>
            <h1>历史事件与处置复盘</h1>
            <p class="his-desc">演示事件链回放，不代表真实历史灾情或正式处置档案</p>
          </div>
        </div>
        <div class="his-title-right">
          <div class="his-chips" aria-label="数据身份">
            <span class="his-chip his-chip--notice">SIMULATED</span>
            <span class="his-chip">DEMO-OBS-V1</span>
            <span class="his-chip">DEMO-PRED-V1</span>
            <span class="his-chip">DEMO-RUN-V1</span>
            <span class="his-chip his-chip--notice">simulation_only</span>
            <span class="his-chip his-chip--notice">非决策用途</span>
          </div>
          <button
            type="button"
            class="his-export-btn"
            data-role="export-btn"
            disabled
            aria-disabled="true"
            title="导出能力规划在 P2 阶段接入，当前未接入"
          >导出演示记录 · P2/未接入</button>
        </div>
      </header>

      <!-- ===== 移动端筛选摘要（仅移动列表视图显示） ===== -->
      <div class="his-filter-summary" data-role="filter-summary">
        <span data-role="filter-summary-text">{{ filterSummaryText }}</span>
      </div>

      <!-- ===== 桌面筛选区 ===== -->
      <section class="his-panel his-filterbar" aria-label="事件筛选">
        <HistoryFilterBar
          :draft="draft"
          :options="filterOptions"
          :error="filterError"
          @apply="onApplyFilters"
          @reset="onResetFilters"
        />
      </section>

      <!-- ===== 主体 38% / 62% ===== -->
      <div class="his-main">
        <aside class="his-panel his-list" aria-label="演示事件列表">
          <header class="his-panel-head">
            <div>
              <p class="his-panel-kicker">EVENT LIST · 演示事件</p>
              <h2>事件列表</h2>
            </div>
            <span class="his-count">共 <b data-role="event-count">{{ filteredEvents.length }}</b> 条</span>
          </header>
          <HistoryEventList
            :state="eventsState"
            :error="eventsError"
            :groups="eventGroups"
            :selected-id="selectedEventId"
            :zone-names="zoneNames"
            @select="selectEvent"
            @retry="fetchEvents"
            @clear-filters="onResetFilters"
          />
        </aside>

        <section class="his-panel his-detail" aria-label="事件详情">
          <div v-if="!selectedEvent" class="his-detail-empty">
            <StatePanel
              state="empty"
              title="未选择演示事件"
              description="从事件列表选择一条演示事件后，这里展示事件身份、证据版本、摘要与能力边界。当前事件均为演示事件，不是真实历史水华事件。"
            />
          </div>
          <HistoryEventDetail
            v-else
            :event="selectedEvent"
            :zone-name="zoneNames[selectedEvent.spatial_entity_id] || ''"
            :meta="{ datasetVersion: eventsMeta.dataset_version, claimBoundary: eventsMeta.claim_boundary }"
            :frame-summary="frameSummary"
            :can-warn="canWarn"
            :dispatch-result="dispatchResult"
            @open-warning="openWarning"
            @back-to-list="mobileView = 'list'"
          />
        </section>
      </div>

      <!-- ===== 推荐预案区 ===== -->
      <HistoryPlanPanel
        class="his-plan"
        :capabilities="capabilities"
        :caps-state="capsState"
        @retry-caps="fetchCaps"
      />

      <!-- ===== 事件回放轴 ===== -->
      <HistoryReplayBar
        class="his-replay"
        :state="replay.state"
        :error="replay.error"
        :frames="replay.frames"
        :index="frameIndex"
        :playing="playing"
        :speed="speed"
        @prev="stepFrame(-1)"
        @next="stepFrame(1)"
        @toggle-play="togglePlay"
        @set-speed="setSpeed"
        @select-frame="jumpFrame"
        @retry="fetchReplay"
      />

      <footer class="his-foot">
        <span>数据模式 simulated · SIMULATED / DEMO-OBS-V1 / DEMO-PRED-V1 / DEMO-RUN-V1 / simulation_only / 非决策用途 · 当前事件为演示事件，非真实历史水华事件</span>
      </footer>
    </div>

    <!-- ===== 移动端底部操作栏 ===== -->
    <Teleport to="body" :disabled="!isMobileViewport">
      <nav class="his-mobile-bar" aria-label="移动端操作栏">
        <template v-if="mobileView === 'list'">
          <RouterLink class="his-mb-btn" :to="cockpitLink">返回驾驶舱</RouterLink>
          <button ref="drawerTriggerRef" type="button" class="his-mb-btn" data-role="drawer-trigger" @click="openDrawer">筛选</button>
          <button
            type="button"
            class="his-mb-btn"
            data-role="mb-current"
            :disabled="!selectedEventId"
            :aria-disabled="String(!selectedEventId)"
            title="查看当前选中事件的详情"
            @click="goCurrentEvent"
          >当前事件</button>
        </template>
        <template v-else>
          <button type="button" class="his-mb-btn" data-role="mb-back-list" @click="mobileView = 'list'">返回列表</button>
          <button
            type="button"
            class="his-mb-btn"
            data-role="mb-plan-match"
            disabled
            aria-disabled="true"
            title="预案匹配接口未实现，无法执行匹配"
          >匹配预案</button>
          <button
            type="button"
            class="his-mb-btn his-mb-btn--warn"
            data-role="mb-warn"
            :disabled="!canWarn"
            :aria-disabled="String(!canWarn)"
            :title="canWarn ? '发起模拟发送预警' : '仅高风险演示事件可发起模拟发送'"
            @click="openWarning"
          >{{ canWarn ? '模拟发送' : '仅高风险可发' }}</button>
        </template>
      </nav>
    </Teleport>

    <!-- ===== 移动端筛选抽屉 ===== -->
    <Teleport to="body">
      <div v-if="drawerOpen" class="his-drawer-mask" @click.self="closeDrawer">
        <div
          ref="drawerRef"
          class="his-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="事件筛选"
          @keydown="onDrawerKeydown"
        >
          <header class="his-drawer-head">
            <h3>筛选事件</h3>
            <button ref="drawerCloseRef" type="button" class="his-drawer-close" data-role="drawer-close" aria-label="关闭筛选抽屉" @click="closeDrawer">关闭</button>
          </header>
          <div class="his-drawer-body">
            <HistoryFilterBar
              compact
              :draft="draft"
              :options="filterOptions"
              :error="filterError"
              @apply="onDrawerApply"
              @reset="onResetFilters"
            />
          </div>
        </div>
      </div>
    </Teleport>

    <HistoryWarningDialog
      :open="warnOpen"
      :event-id="selectedEvent ? selectedEvent.id : ''"
      :zone-label="selectedEvent ? (zoneNames[selectedEvent.spatial_entity_id] || selectedEvent.spatial_entity_id || '—') : ''"
      :level-text="selectedEvent ? severityText(selectedEvent.severity) : ''"
      :busy="warnBusy"
      :error="warnError"
      @cancel="closeWarning"
      @confirm="confirmWarning"
    />
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cockpitState, useCockpitStore } from '../stores/cockpit.js'
import {
  getEventsEnvelope,
  getCockpitEventsEnvelope,
  getSpatialEntities,
  getTimelineEnvelope,
  getForecastCapabilitiesEnvelope,
  postHandleWarningEnvelope
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import StatePanel from '../components/common/StatePanel.vue'
import HistoryFilterBar from '../components/history/HistoryFilterBar.vue'
import HistoryEventList from '../components/history/HistoryEventList.vue'
import HistoryEventDetail from '../components/history/HistoryEventDetail.vue'
import HistoryPlanPanel from '../components/history/HistoryPlanPanel.vue'
import HistoryReplayBar from '../components/history/HistoryReplayBar.vue'
import HistoryWarningDialog from '../components/history/HistoryWarningDialog.vue'
import {
  STATUS_UNAVAILABLE,
  eventTypeText,
  filterEvents,
  groupByDateDesc,
  mergeEvents,
  normalizeQuery,
  rangeError,
  replayWindow,
  buildReplayFrames,
  eventDateOf,
  serializeFilters,
  severityText,
  sortEventsDesc
} from '../components/history/historyCore.js'

const route = useRoute()
const router = useRouter()
useCockpitStore()
const store = cockpitState()

const cockpitLink = computed(() => ({
  path: '/cockpit',
  query: { t: store.stageKey, p: store.selectedPoint }
}))

// ---------- 能力状态 ----------
const capabilities = ref(null)
const capsState = ref('loading')
async function fetchCaps() {
  capsState.value = 'loading'
  try {
    const { data } = await getForecastCapabilitiesEnvelope()
    capabilities.value = data && typeof data === 'object' ? data : {}
    capsState.value = 'ok'
  } catch {
    capabilities.value = null
    capsState.value = 'error'
  }
}

// ---------- 演示分区 ----------
const entities = ref([])
const entitiesState = ref('loading')
const zoneNames = computed(() =>
  Object.fromEntries(entities.value.map((e) => [e.id, e.display_name || e.short || e.id]))
)
async function fetchEntities() {
  entitiesState.value = 'loading'
  try {
    const { data } = await getSpatialEntities()
    entities.value = Array.isArray(data) ? data : []
    entitiesState.value = 'ok'
    normalizeFiltersAgainstData()
  } catch {
    entities.value = []
    entitiesState.value = 'error'
    normalizeFiltersAgainstData()
  }
}

// ---------- 事件双源（/events + /cockpit/events，仅按相同 ID 合并） ----------
const eventsState = ref('loading')
const eventsError = ref('')
const mergedEvents = ref([])
const eventsMeta = ref({})
const runIdChip = ref('—')
let eventsToken = 0

async function fetchEvents() {
  const token = ++eventsToken
  eventsState.value = 'loading'
  eventsError.value = ''
  try {
    const [basic, cockpit] = await Promise.all([getEventsEnvelope(), getCockpitEventsEnvelope()])
    if (token !== eventsToken) return
    eventsMeta.value = basic.meta || {}
    mergedEvents.value = sortEventsDesc(mergeEvents(basic.data, cockpit.data))
    const run = mergedEvents.value.find((e) => e.prediction_run_id)
    runIdChip.value = run ? run.prediction_run_id : '—'
    eventsState.value = 'ok'
    normalizeFiltersAgainstData()
  } catch (err) {
    if (token !== eventsToken) return
    mergedEvents.value = []
    eventsMeta.value = {}
    runIdChip.value = '—'
    eventsState.value = 'error'
    eventsError.value = err && err.message ? err.message : '事件接口请求失败'
  }
}

// ---------- 筛选（applied 生效值 / draft 编辑值，URL 为事实来源） ----------
const applied = reactive(normalizeQuery(route.query))
const draft = reactive({ ...normalizeQuery(route.query) })
const filterError = ref('')
const selectedEventId = ref('')

const filterOptions = computed(() => ({
  types: [...new Set(mergedEvents.value.map((e) => e.event_type).filter(Boolean))],
  zones: entities.value.map((e) => ({ id: e.id, label: `${e.display_name || e.id}（${e.short || '—'}）` })),
  modes: [...new Set(mergedEvents.value.map((e) => e.data_mode).filter(Boolean))]
}))

// 数据到位后剔除无效筛选值（非法分区/类型/模式不参与过滤，也不留在 URL）。
// 每类校验以其数据源就绪为前提：fetchEntities 与 fetchEvents 都会调用本函数，
// 先返回的一方不能把尚未加载的数据当作“非法”清掉（否则冷启动恢复的 event 会被误删）。
function normalizeFiltersAgainstData() {
  const patch = {}
  if (entitiesState.value === 'ok' && applied.p && !entities.value.some((e) => e.id === applied.p)) patch.p = ''
  const types = filterOptions.value.types
  if (eventsState.value === 'ok' && applied.type && !types.includes(applied.type)) patch.type = ''
  const modes = filterOptions.value.modes
  if (eventsState.value === 'ok' && applied.mode && !modes.includes(applied.mode)) patch.mode = ''
  if (Object.keys(patch).length) {
    Object.assign(applied, patch)
    Object.assign(draft, patch)
    syncUrl()
  }
  if (eventsState.value === 'ok' && selectedEventId.value && !mergedEvents.value.some((e) => e.id === selectedEventId.value)) {
    selectedEventId.value = ''
    syncUrl()
  }
}

const filteredEvents = computed(() => filterEvents(mergedEvents.value, applied))
const eventGroups = computed(() => groupByDateDesc(filteredEvents.value))

watch(filteredEvents, (list) => {
  if (selectedEventId.value && !list.some((e) => e.id === selectedEventId.value)) {
    selectedEventId.value = ''
    syncUrl()
  }
})

function onApplyFilters() {
  const err = rangeError(draft.start, draft.end)
  filterError.value = err
  if (err) return
  Object.assign(applied, {
    start: draft.start,
    end: draft.end,
    type: draft.type,
    p: draft.p,
    mode: draft.mode,
    status: STATUS_UNAVAILABLE
  })
  syncUrl()
}

function onResetFilters() {
  filterError.value = ''
  Object.assign(draft, { start: '', end: '', type: '', p: '', mode: '' })
  Object.assign(applied, { start: '', end: '', type: '', p: '', mode: '', status: STATUS_UNAVAILABLE })
  syncUrl()
}

function syncUrl() {
  router.replace({ query: serializeFilters(applied, selectedEventId.value) }).catch(() => {})
}

// 外部 URL 变化（前进/后退、手改地址）→ 归一化并应用；自身 replace 因幂等不触发循环。
// 非法 event 在此被清空后必须回写 URL，否则非法参数会一直留在地址栏。
watch(() => route.query, (q) => {
  const n = normalizeQuery(q)
  const cur = serializeFilters(applied, selectedEventId.value)
  const next = serializeFilters(n, n.event)
  if (JSON.stringify(next) === JSON.stringify(cur)) return
  Object.assign(applied, { start: n.start, end: n.end, type: n.type, p: n.p, mode: n.mode, status: STATUS_UNAVAILABLE })
  Object.assign(draft, { start: n.start, end: n.end, type: n.type, p: n.p, mode: n.mode })
  selectedEventId.value =
    n.event && (eventsState.value !== 'ok' || mergedEvents.value.some((e) => e.id === n.event))
      ? n.event
      : ''
  syncUrl()
})

const filterSummaryText = computed(() => {
  const parts = [
    applied.start && applied.end ? `${applied.start} ~ ${applied.end}` : '全部日期',
    applied.type ? eventTypeText(applied.type) : '全部类型',
    applied.p ? (zoneNames.value[applied.p] || applied.p) : '全部分区',
    applied.mode || '全部模式'
  ]
  return parts.join(' · ')
})

// ---------- 事件选择 ----------
const selectedEvent = computed(() =>
  mergedEvents.value.find((e) => e.id === selectedEventId.value) || null
)

function selectEvent(id) {
  if (!id) return
  if (id !== selectedEventId.value) {
    selectedEventId.value = id
    syncUrl()
  }
  if (isMobileViewport.value) mobileView.value = 'detail'
}

function goCurrentEvent() {
  if (selectedEventId.value && isMobileViewport.value) mobileView.value = 'detail'
}

// ---------- 回放（-24h → +48h，仅接口 risk_level） ----------
const replay = reactive({ state: 'idle', frames: [], error: '' })
const frameIndex = ref(0)
const playing = ref(false)
const speed = ref(1)
const replayToken = { n: 0 }

async function fetchReplay() {
  const ev = selectedEvent.value
  if (!ev) {
    replay.state = 'idle'
    replay.frames = []
    replay.error = ''
    stopPlay()
    return
  }
  const date = eventDateOf(ev)
  const win = replayWindow(date)
  if (!win) {
    replay.state = 'blocked'
    replay.frames = []
    replay.error = ''
    stopPlay()
    return
  }
  const token = ++replayToken.n
  replay.state = 'loading'
  replay.frames = []
  replay.error = ''
  frameIndex.value = 0
  stopPlay()
  try {
    const { data } = await getTimelineEnvelope(win.start, win.end)
    if (token !== replayToken.n) return
    replay.frames = buildReplayFrames(data, date)
    replay.state = 'ok'
    frameIndex.value = 0
  } catch (err) {
    if (token !== replayToken.n) return
    replay.frames = []
    replay.state = 'error'
    replay.error = err && err.message ? err.message : '回放时间轴请求失败'
  }
}

// 监听选中的事件对象而非 ID：冷启动/刷新时 URL 的 event 先于事件列表恢复，
// 列表到达后 selectedEvent 才从 null 变为有效事件，此时必须补发回放请求。
// 事件列表重挂载（同 ID 新对象）也只触发这一次请求，token 保证不串写。
watch(selectedEvent, () => {
  dispatchResult.value = null
  fetchReplay()
})

function stepFrame(delta) {
  const next = frameIndex.value + delta
  if (next < 0 || next > replay.frames.length - 1) return
  frameIndex.value = next
}

function jumpFrame(i) {
  if (i < 0 || i > replay.frames.length - 1) return
  frameIndex.value = i
  playing.value = false
}

let playTimer = null
function stopPlay() {
  playing.value = false
}
function syncPlayTimer() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  if (!playing.value) return
  playTimer = setInterval(() => {
    if (frameIndex.value < replay.frames.length - 1) {
      frameIndex.value++
    } else {
      // 播放到事件后 48h 自动停止，不循环
      playing.value = false
    }
  }, 1200 / speed.value)
}
watch(playing, syncPlayTimer)
watch(speed, syncPlayTimer)

function togglePlay() {
  if (!replay.frames.length) return
  if (!playing.value && frameIndex.value >= replay.frames.length - 1) {
    frameIndex.value = 0
  }
  playing.value = !playing.value
}

function setSpeed(s) {
  speed.value = s
}

const frameSummary = computed(() => {
  if (replay.state !== 'ok' || !replay.frames.length) return ''
  const f = replay.frames[frameIndex.value]
  if (!f) return ''
  return `${f.label} · ${f.date} · ${f.riskLevel ? severityText(f.riskLevel) + '（演示）' : '接口未提供'}`
})

// ---------- 模拟发送预警（仅高风险演示事件） ----------
const canWarn = computed(() => Boolean(selectedEvent.value && selectedEvent.value.severity === 'high'))
const warnOpen = ref(false)
const warnBusy = ref(false)
const warnError = ref('')
const dispatchResult = ref(null)
let warnReturnFocus = null

function openWarning() {
  if (!canWarn.value || warnBusy.value) return
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
  // 请求期间禁止重复提交：一次确认仅产生一次 POST
  if (warnBusy.value || !selectedEvent.value) return
  warnBusy.value = true
  warnError.value = ''
  try {
    const { data } = await postHandleWarningEnvelope(selectedEvent.value.id)
    dispatchResult.value = data
    warnOpen.value = false
    if (warnReturnFocus && warnReturnFocus.focus) warnReturnFocus.focus()
    warnReturnFocus = null
  } catch (err) {
    warnError.value = err && err.message ? err.message : '调用失败'
  } finally {
    warnBusy.value = false
  }
}

// ---------- 移动端视图与抽屉 ----------
const mobileMq = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 960px)')
  : null
const isMobileViewport = ref(Boolean(mobileMq && mobileMq.matches))
function onMobileMqChange(e) {
  isMobileViewport.value = e.matches
}
const mobileView = ref('list')
const mobileBodyClass = computed(() =>
  isMobileViewport.value ? `his-body--m-${mobileView.value}` : ''
)

const drawerOpen = ref(false)
const drawerTriggerRef = ref(null)
const drawerRef = ref(null)
const drawerCloseRef = ref(null)
let drawerReturnFocus = null

function openDrawer() {
  drawerReturnFocus = drawerTriggerRef.value || document.activeElement
  drawerOpen.value = true
  nextTick(() => drawerCloseRef.value && drawerCloseRef.value.focus())
}
function closeDrawer() {
  drawerOpen.value = false
  if (drawerReturnFocus && drawerReturnFocus.focus) drawerReturnFocus.focus()
  drawerReturnFocus = null
}
function onDrawerApply() {
  onApplyFilters()
  if (!filterError.value) closeDrawer()
}
function onDrawerKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    closeDrawer()
    return
  }
  if (e.key !== 'Tab') return
  const focusables = Array.from(
    drawerRef.value.querySelectorAll('button, select, [href], input')
  ).filter((el) => !el.disabled && el.offsetParent !== null)
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const activeEl = document.activeElement
  if (e.shiftKey && (activeEl === first || activeEl === drawerRef.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && activeEl === last) {
    e.preventDefault()
    first.focus()
  }
}

watch([warnOpen, drawerOpen], ([w, d]) => {
  document.body.style.overflow = w || d ? 'hidden' : ''
})

// ---------- 初始化 ----------
onMounted(() => {
  const n = normalizeQuery(route.query)
  Object.assign(applied, n)
  Object.assign(draft, { start: n.start, end: n.end, type: n.type, p: n.p, mode: n.mode })
  selectedEventId.value = n.event
  // 立即回写归一化后的参数：非法值不残留在地址栏
  syncUrl()
  fetchCaps()
  fetchEntities()
  fetchEvents()
  mobileMq?.addEventListener('change', onMobileMqChange)
})

// 事件加载完成后：URL 中携带合法 event 时，移动端直接进入详情视图
watch(eventsState, (s) => {
  if (s === 'ok' && selectedEventId.value && mergedEvents.value.some((e) => e.id === selectedEventId.value)) {
    if (isMobileViewport.value) mobileView.value = 'detail'
  }
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  mobileMq?.removeEventListener('change', onMobileMqChange)
  if (playTimer) clearInterval(playTimer)
})
</script>

<style scoped>
.page-history {
  max-width: 1760px;
  margin: 0 auto;
  padding: 8px 20px 12px;
  min-height: 100vh;
}
.his-body {
  display: grid;
  gap: 6px;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'title'
    'filters'
    'main'
    'plan'
    'replay'
    'foot';
  align-items: start;
  min-width: 0;
}

/* ---------- 标题区 ---------- */
.his-title {
  grid-area: title;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px 16px;
  padding: 10px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.his-title-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}
.his-kicker {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.22em;
  color: var(--color-primary);
}
.his-title h1 {
  margin: 1px 0 0;
  font-family: var(--font-display);
  font-size: clamp(18px, 1.8vw, 24px);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}
.his-desc {
  margin: 3px 0 0;
  font-size: 11px;
  color: var(--text-muted);
}
.his-title-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  min-width: 0;
}
.his-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}
.his-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  font-size: 10.5px;
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.his-chip--notice {
  border-color: color-mix(in srgb, var(--data-simulated, #7cb8c9) 45%, transparent);
  color: var(--data-simulated, #7cb8c9);
}
.his-export-btn {
  appearance: none;
  min-height: 32px;
  padding: 4px 12px;
  border: 1px dashed var(--border-subtle);
  border-radius: 9px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: not-allowed;
}
.his-export-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 筛选摘要（移动列表视图） ---------- */
.his-filter-summary {
  grid-area: fsummary;
  display: none;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.his-filter-summary span {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-secondary);
  word-break: break-all;
}

/* ---------- 面板通用 ---------- */
.his-panel {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.his-filterbar {
  grid-area: filters;
  padding: 10px 14px;
}
.his-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px 0;
}
.his-panel-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.his-panel-head h2 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.his-count {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.his-count b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}

/* ---------- 主体 38 / 62 ---------- */
.his-main {
  grid-area: main;
  display: grid;
  grid-template-columns: minmax(0, 38fr) minmax(0, 62fr);
  gap: 6px;
  align-items: start;
  min-width: 0;
}
.his-list {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 560px;
  overflow-y: auto;
}
.his-detail {
  /* 桌面端作为 .his-main 第二个网格项自动放入 62% 列；
     grid-area: mdetail 仅限移动端模板（隐式命名线会在桌面造出第三列） */
  padding: 12px 14px;
  min-height: 320px;
}
.his-detail-empty {
  display: grid;
  min-height: 280px;
  align-items: center;
}

.his-plan {
  grid-area: plan;
}
.his-replay {
  grid-area: replay;
}

.his-foot {
  grid-area: foot;
  display: flex;
  justify-content: center;
  padding: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  text-align: center;
}

/* ---------- 移动端底栏与抽屉 ---------- */
.his-mobile-bar {
  display: none;
}
.his-drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 1600;
  display: flex;
  align-items: flex-end;
  background: rgba(2, 8, 18, 0.55);
  backdrop-filter: blur(3px);
}
.his-drawer {
  width: 100%;
  max-height: 76vh;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-subtle);
  border-radius: 16px 16px 0 0;
  background: var(--surface-panel-raised, rgba(14, 40, 66, 0.96));
  padding-bottom: calc(6px + env(safe-area-inset-bottom, 0px));
}
.his-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.his-drawer-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.his-drawer-close {
  appearance: none;
  min-height: 44px;
  min-width: 64px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.his-drawer-close:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.his-drawer-body {
  overflow-y: auto;
  padding: 12px 14px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 960px) {
  .page-history {
    padding: 8px 12px calc(88px + env(safe-area-inset-bottom, 0px));
  }
  .his-body {
    grid-template-areas:
      'title'
      'fsummary'
      'filters'
      'main'
      'plan'
      'replay'
      'foot';
  }
  .his-main {
    display: contents;
  }
  .his-list {
    grid-area: main;
    max-height: none;
    overflow: visible;
  }
  .his-detail {
    grid-area: main;
  }
  .his-filter-summary {
    display: flex;
  }
  .his-export-btn,
  .his-chip,
  .his-count {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
  }

  .his-body--m-list {
    grid-template-areas:
      'title'
      'fsummary'
      'mlist'
      'foot';
  }
  .his-body--m-list .his-list {
    grid-area: mlist;
  }
  .his-body--m-list .his-detail,
  .his-body--m-list .his-plan,
  .his-body--m-list .his-replay,
  .his-body--m-list .his-filterbar {
    display: none;
  }

  .his-body--m-detail {
    grid-template-areas:
      'title'
      'mdetail'
      'mreplay'
      'mplan'
      'foot';
  }
  .his-body--m-detail .his-detail {
    grid-area: mdetail;
  }
  .his-body--m-detail .his-replay {
    grid-area: mreplay;
  }
  .his-body--m-detail .his-plan {
    grid-area: mplan;
  }
  .his-body--m-detail .his-list,
  .his-body--m-detail .his-filterbar,
  .his-body--m-detail .his-filter-summary {
    display: none;
  }

  .his-mobile-bar {
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
  .his-mb-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 8px 10px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-item, 8px);
    background: var(--surface-panel-soft);
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
  }
  .his-mb-btn:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
  .his-mb-btn--warn {
    border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent);
    color: var(--risk-critical, #ef4444);
    background: color-mix(in srgb, var(--risk-critical, #ef4444) 10%, transparent);
  }
  .his-mb-btn:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }

  /* 触摸目标 ≥44×44（页面自身元素；子组件内部由各自 scoped 样式负责） */
  .his-export-btn {
    min-height: 44px;
  }
}
</style>

<style>
/* P06 页面级全局补充：reduced-motion 下关闭入场与装饰动画（不动 styles.css） */
@media (prefers-reduced-motion: reduce) {
  .route-stage > .page-history {
    animation: none !important;
  }
  .page-history *,
  .page-history *::before,
  .page-history *::after {
    transition: none !important;
  }
}
</style>
