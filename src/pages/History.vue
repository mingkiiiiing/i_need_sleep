<template>
  <main class="page-history">
    <div class="his-body" :class="mobileBodyClass">
      <!-- ===== 标题区 ===== -->
      <header class="his-title" aria-label="实时观测历史复盘标题">
        <div class="his-title-left">
          <BackLink :to="cockpitLink" label="返回驾驶舱" />
          <div class="his-title-text">
            <h1>实时观测历史复盘</h1>
          </div>
        </div>
        <div class="his-title-right">
          <div class="his-chips">
            <span class="his-chip">observed · 真实观测</span>
            <span class="his-chip">{{ tlMeta.dataset_version || 'MEE-RT-V1' }}</span>
            <span class="his-chip his-chip--notice">官方观测未经跨源验证</span>
          </div>
        </div>
      </header>

      <!-- ===== 移动端筛选摘要（仅移动列表视图显示） ===== -->
      <div class="his-filter-summary" data-role="filter-summary">
        <span data-role="filter-summary-text">{{ filterSummaryText }}</span>
      </div>

      <!-- ===== 桌面筛选区 ===== -->
      <section class="his-panel his-filterbar" aria-label="快照时间筛选">
        <div class="his-date-filter" data-role="date-filter">
          <label class="his-date-field">
            <span>开始日期</span>
            <input v-model="draft.start" type="date" data-role="filter-start" aria-label="开始日期" />
          </label>
          <label class="his-date-field">
            <span>结束日期</span>
            <input v-model="draft.end" type="date" data-role="filter-end" aria-label="结束日期" />
          </label>
          <button type="button" class="his-btn his-btn--primary" data-role="filter-apply" @click="onApplyFilters">应用</button>
          <button type="button" class="his-btn" data-role="filter-reset" @click="onResetFilters">重置</button>
          <p v-if="filterError" class="his-filter-error" role="alert">{{ filterError }}</p>
        </div>
      </section>

      <!-- ===== 主体 38% / 62% ===== -->
      <div class="his-main">
        <aside class="his-panel his-list" aria-label="实时快照列表">
          <header class="his-panel-head">
            <div>
              <p class="his-panel-kicker">SNAPSHOT LIST · 实时快照</p>
              <h2>快照列表</h2>
            </div>
            <span class="his-count">共 <b data-role="snapshot-count">{{ filteredSnapshots.length }}</b> 个</span>
          </header>
          <div v-if="tlState === 'loading'" class="his-list-note">正在加载快照时间轴…</div>
          <div v-else-if="tlState === 'error'" class="his-list-note his-list-note--bad" role="alert">
            {{ tlError || '快照时间轴请求失败' }}
            <button type="button" class="his-btn" @click="fetchTimeline">重试</button>
          </div>
          <div v-else-if="!filteredSnapshots.length" class="his-list-note">
            该日期范围内没有快照。系统自 2026-09-04 起随抓取自动积累，不做模拟补齐。
            <button type="button" class="his-btn" @click="onResetFilters">清除日期筛选</button>
          </div>
          <ul v-else class="his-snap-list" data-role="snapshot-list">
            <li v-for="snap in filteredSnapshots" :key="snap.snapshot_id">
              <button
                type="button"
                class="his-snap-item"
                :class="{ active: snap.snapshot_id === selectedSnapshotId }"
                :data-snapshot="snap.snapshot_id"
                @click="selectSnapshot(snap.snapshot_id)"
              >
                <span class="his-snap-time">{{ formatStamp(snap.latest_observed_at) }}</span>
                <span class="his-snap-meta">
                  <b>{{ snap.station_count }}</b> 站 ·
                  达标 <b>{{ complianceText(snap) }}</b> ·
                  预警 <b :class="{ 'his-snap-warn': snap.warning_count > 0 }">{{ snap.warning_count }}</b>
                </span>
                <span class="his-snap-sub">叶绿素均值 {{ snap.chla_mean != null ? snap.chla_mean + ' μg/L' : '—' }} · {{ snap.chla_report_stations }} 站报数</span>
              </button>
            </li>
          </ul>
        </aside>

        <section class="his-panel his-detail" aria-label="快照详情">
          <div v-if="!selectedSnapshotId" class="his-detail-empty">
            <StatePanel
              state="empty"
              title="未选择快照"
              description="从快照列表选择一次真实抓取快照后，这里展示该时刻的全站观测状态、达标构成与蓝藻筛查预警。所有内容均为官方观测（observed），无情景数据。"
            />
          </div>
          <div v-else-if="sumState === 'loading'" class="his-detail-empty">
            <StatePanel state="loading" title="快照详情加载中…" />
          </div>
          <div v-else-if="sumState === 'error'" class="his-detail-empty">
            <StatePanel state="error" title="快照详情加载失败" :description="sumError">
              <button type="button" class="his-btn" @click="fetchSnapshotSummary">重试</button>
            </StatePanel>
          </div>
          <div v-else-if="summary" class="his-detail-body" data-role="snapshot-detail">
            <header class="his-detail-head">
              <h3>快照详情 <span>{{ formatStamp(summary.latest_observed_at) }}</span></h3>
              <span class="his-detail-flag" :class="{ 'his-detail-flag--old': !summary.is_latest }">
                {{ summary.is_latest ? '最新快照' : '历史快照回放（非最新）' }}
              </span>
            </header>

            <ul class="his-caps" data-role="snapshot-caps">
              <li>活跃站点：<b>{{ summary.station_total }}</b></li>
              <li>水质达标率（≤III 类）：<b>{{ summary.class_iii_rate != null ? (summary.class_iii_rate * 100).toFixed(1) + '%' : '—' }}</b></li>
              <li>蓝藻筛查预警：<b :class="{ 'his-cap-warn': (summary.warnings || []).length }">{{ (summary.warnings || []).length }} 站</b></li>
              <li>叶绿素 a 均值：<b>{{ chlaMeanText }}</b>（{{ summary.chla_report_stations }} 站报数）</li>
              <li>数据新鲜度：<b>{{ freshnessText }}</b>（滞后 {{ formatLag(summary.observed_lag_h) }}）</li>
              <li>抓取时间：<b>{{ formatStamp(summary.retrieved_at) }} UTC</b></li>
            </ul>

            <div class="his-class-row" data-role="class-counts">
              <span class="his-class-label">水质类别构成：</span>
              <span v-for="(count, cls) in summary.class_counts" :key="cls" class="his-class-chip">{{ classText(cls) }}：{{ count }}</span>
            </div>

            <section class="his-sec" aria-label="蓝藻筛查预警站点">
              <h4>蓝藻筛查预警站点<span class="his-sec-hint">chla ≥{{ summary.warning_thresholds?.light ?? 10 }} 轻度 / ≥{{ summary.warning_thresholds?.moderate ?? 25 }} 中度</span></h4>
              <table v-if="(summary.warnings || []).length" class="his-table">
                <thead>
                  <tr><th>站点</th><th>叶绿素 a（μg/L）</th><th>筛查档位</th><th>坐标状态</th></tr>
                </thead>
                <tbody>
                  <tr v-for="w in summary.warnings" :key="w.station_id" data-role="warning-row">
                    <td>{{ w.station_name }}</td>
                    <td class="his-mono">{{ w.chla != null ? w.chla : '—' }}</td>
                    <td>{{ bandText(w.band) }}</td>
                    <td class="his-miss">{{ locationText(w.location_status) }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else class="his-sec-empty">该快照无蓝藻筛查预警站点。</p>
            </section>

            <section class="his-sec" aria-label="站点观测明细">
              <h4>站点观测明细<span class="his-sec-hint">{{ (summary.markers || []).length }} 站（仅有坐标站点）· 其余 {{ Math.max(0, summary.station_total - (summary.markers || []).length) }} 站无坐标，见「监测站点」页 · 缺测显式标注</span></h4>
              <div class="his-table-wrap">
                <table class="his-table">
                  <thead>
                    <tr>
                      <th>站点</th><th>省份</th><th>水质类别</th><th>叶绿素 a</th><th>溶解氧</th><th>总磷</th><th>总氮</th><th>坐标状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in summary.markers" :key="m.id" data-role="marker-row">
                      <td>{{ m.name }}</td>
                      <td>{{ m.province || '—' }}</td>
                      <td>{{ m.water_level != null ? classText(String(m.water_level)) : '—' }}</td>
                      <td :class="{ 'his-miss': m.chla == null }" class="his-mono">{{ m.chla != null ? m.chla : '缺测' }}</td>
                      <td :class="{ 'his-miss': m.metrics?.dissolved_oxygen == null }" class="his-mono">{{ m.metrics?.dissolved_oxygen ?? '缺测' }}</td>
                      <td :class="{ 'his-miss': m.metrics?.total_phosphorus == null }" class="his-mono">{{ m.metrics?.total_phosphorus ?? '缺测' }}</td>
                      <td :class="{ 'his-miss': m.metrics?.total_nitrogen == null }" class="his-mono">{{ m.metrics?.total_nitrogen ?? '缺测' }}</td>
                      <td class="his-miss">{{ locationText(m.location_status) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </section>
      </div>

      <!-- ===== 推荐预案区 ===== -->
      <HistoryPlanPanel
        class="his-plan"
        :capabilities="capabilities"
        :caps-state="capsState"
        @retry-caps="fetchCaps"
      />

      <!-- ===== 单站观测回放（observed 轨） ===== -->
      <StationReplayPanel class="his-rt-replay" />

      <footer class="his-foot">
        <span>数据模式 observed · {{ tlMeta.dataset_version || 'MEE-RT-V1' }} / {{ tlMeta.claim_boundary || 'official_observation_not_cross_validated' }} · 官方实时观测未经跨源验证；阈值为筛查口径非监管判定</span>
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
            :disabled="!selectedSnapshotId"
            :aria-disabled="String(!selectedSnapshotId)"
            title="查看当前选中快照的详情"
            @click="goCurrentSnapshot"
          >当前快照</button>
        </template>
        <template v-else>
          <button type="button" class="his-mb-btn" data-role="mb-back-list" @click="mobileView = 'list'">返回列表</button>
          <button
            type="button"
            class="his-mb-btn"
            data-role="mb-prev"
            :disabled="!hasPrevSnapshot"
            :aria-disabled="String(!hasPrevSnapshot)"
            @click="stepSnapshot(-1)"
          >上一快照</button>
          <button
            type="button"
            class="his-mb-btn"
            data-role="mb-next"
            :disabled="!hasNextSnapshot"
            :aria-disabled="String(!hasNextSnapshot)"
            @click="stepSnapshot(1)"
          >下一快照</button>
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
          aria-label="快照时间筛选"
          @keydown="onDrawerKeydown"
        >
          <header class="his-drawer-head">
            <h3>筛选快照时间</h3>
            <button ref="drawerCloseRef" type="button" class="his-drawer-close" data-role="drawer-close" aria-label="关闭筛选抽屉" @click="closeDrawer">关闭</button>
          </header>
          <div class="his-drawer-body">
            <div class="his-date-filter">
              <label class="his-date-field">
                <span>开始日期</span>
                <input v-model="draft.start" type="date" aria-label="开始日期" />
              </label>
              <label class="his-date-field">
                <span>结束日期</span>
                <input v-model="draft.end" type="date" aria-label="结束日期" />
              </label>
              <button type="button" class="his-btn his-btn--primary" @click="onDrawerApply">应用</button>
              <button type="button" class="his-btn" @click="onResetFilters">重置</button>
              <p v-if="filterError" class="his-filter-error" role="alert">{{ filterError }}</p>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getForecastCapabilitiesEnvelope, getRealtimeTimelineEnvelope } from '../services/api.js'
import { fetchRealtimeSummary, formatStamp, formatLag, LOCATION_STATUS_TEXT } from '../services/realtime.js'
import BackLink from '../components/common/BackLink.vue'
import StatePanel from '../components/common/StatePanel.vue'
import HistoryPlanPanel from '../components/history/HistoryPlanPanel.vue'
import StationReplayPanel from '../components/stations/StationReplayPanel.vue'

const route = useRoute()
const router = useRouter()

const cockpitLink = '/cockpit'

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

// ---------- 快照时间轴（observed，唯一数据源 /realtime/timeline） ----------
const tlState = ref('loading')
const tlError = ref('')
const snapshots = ref([])
const tlMeta = ref({})
let timelineToken = 0

async function fetchTimeline() {
  const token = ++timelineToken
  tlState.value = 'loading'
  tlError.value = ''
  try {
    const { data, meta } = await getRealtimeTimelineEnvelope()
    if (token !== timelineToken) return
    snapshots.value = Array.isArray(data?.snapshots) ? data.snapshots : []
    tlMeta.value = meta || {}
    tlState.value = 'ok'
    normalizeSnapshotAgainstData()
  } catch (err) {
    if (token !== timelineToken) return
    snapshots.value = []
    tlMeta.value = {}
    tlState.value = 'error'
    tlError.value = err && err.message ? err.message : '快照时间轴请求失败'
  }
}

// ---------- 筛选（applied 生效值 / draft 编辑值，URL 为事实来源） ----------
const applied = reactive(normalizeQuery(route.query))
const draft = reactive({ start: applied.start, end: applied.end })
const filterError = ref('')
const selectedSnapshotId = ref(applied.snapshot || '')

function normalizeQuery(query = {}) {
  const start = typeof query.start === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(query.start) ? query.start : ''
  const end = typeof query.end === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(query.end) ? query.end : ''
  const snapshot = typeof query.snapshot === 'string' ? query.snapshot : ''
  return { start, end, snapshot }
}

function rangeError(start, end) {
  if (start && end && start > end) return '开始日期不能晚于结束日期'
  return ''
}

// 按观测日期过滤快照（两端闭区间；空值表示不限）
const filteredSnapshots = computed(() => {
  const { start, end } = applied
  return snapshots.value.filter((snap) => {
    const day = String(snap.latest_observed_at || '').slice(0, 10)
    if (!day) return false
    if (start && day < start) return false
    if (end && day > end) return false
    return true
  })
})

function normalizeSnapshotAgainstData() {
  if (tlState.value !== 'ok') return
  const exists = snapshots.value.some((s) => s.snapshot_id === selectedSnapshotId.value)
  if (selectedSnapshotId.value && !exists) {
    selectedSnapshotId.value = ''
    syncUrl()
  }
  // 无有效选中时默认选中最新快照（时间轴已按时间升序，末位即最新）
  if (!selectedSnapshotId.value && snapshots.value.length) {
    selectedSnapshotId.value = snapshots.value[snapshots.value.length - 1].snapshot_id
    syncUrl()
  }
}

function onApplyFilters() {
  const err = rangeError(draft.start, draft.end)
  filterError.value = err
  if (err) return
  applied.start = draft.start
  applied.end = draft.end
  syncUrl()
}

function onResetFilters() {
  filterError.value = ''
  draft.start = ''
  draft.end = ''
  applied.start = ''
  applied.end = ''
  syncUrl()
}

function syncUrl() {
  router.replace({ query: serializeFilters(applied, selectedSnapshotId.value) }).catch(() => {})
}

function serializeFilters(state, snapshotId) {
  const query = {}
  if (state.start) query.start = state.start
  if (state.end) query.end = state.end
  if (snapshotId) query.snapshot = snapshotId
  return query
}

// 外部 URL 变化（前进/后退、手改地址）→ 归一化并应用；自身 replace 因幂等不触发循环。
watch(() => route.query, (q) => {
  const n = normalizeQuery(q)
  const cur = serializeFilters(applied, selectedSnapshotId.value)
  const next = serializeFilters(n, n.snapshot)
  if (JSON.stringify(next) === JSON.stringify(cur)) return
  applied.start = n.start
  applied.end = n.end
  draft.start = n.start
  draft.end = n.end
  selectedSnapshotId.value = n.snapshot
  syncUrl()
})

const filterSummaryText = computed(() => {
  const range = applied.start || applied.end ? `${applied.start || '…'} ~ ${applied.end || '…'}` : '全部日期'
  return `${range} · ${filteredSnapshots.value.length} 个快照`
})

// ---------- 快照选择与详情 ----------
const selectedSnapshot = computed(() =>
  snapshots.value.find((s) => s.snapshot_id === selectedSnapshotId.value) || null
)

function selectSnapshot(id) {
  if (!id || id === selectedSnapshotId.value) return
  selectedSnapshotId.value = id
  syncUrl()
  if (isMobileViewport.value) mobileView.value = 'detail'
}

function goCurrentSnapshot() {
  if (selectedSnapshotId.value && isMobileViewport.value) mobileView.value = 'detail'
}

const sumState = ref('idle')
const sumError = ref('')
const summary = ref(null)
let summaryToken = 0

async function fetchSnapshotSummary() {
  const id = selectedSnapshotId.value
  if (!id) {
    sumState.value = 'idle'
    summary.value = null
    return
  }
  const token = ++summaryToken
  sumState.value = 'loading'
  sumError.value = ''
  try {
    summary.value = await fetchRealtimeSummary({ snapshotId: id })
    if (token !== summaryToken) return
    sumState.value = 'ok'
  } catch (err) {
    if (token !== summaryToken) return
    summary.value = null
    sumState.value = 'error'
    sumError.value = err && err.message ? err.message : '快照详情请求失败'
  }
}

// 监听选中 ID：URL 冷启动恢复、列表点击、上一/下一快照都汇聚到这一处请求。
watch(selectedSnapshotId, (id) => {
  if (id) fetchSnapshotSummary()
  else {
    summary.value = null
    sumState.value = 'idle'
  }
})

// 快照到达后若 URL 携带的 snapshot 已失效，归一化并默认选中最新
watch(tlState, (s) => {
  if (s === 'ok') normalizeSnapshotAgainstData()
})

// ---------- 上一 / 下一快照（在筛选后的列表内步进，时间升序） ----------
const snapshotIndex = computed(() =>
  filteredSnapshots.value.findIndex((s) => s.snapshot_id === selectedSnapshotId.value)
)
const hasPrevSnapshot = computed(() => snapshotIndex.value > 0)
const hasNextSnapshot = computed(() => snapshotIndex.value >= 0 && snapshotIndex.value < filteredSnapshots.value.length - 1)

function stepSnapshot(delta) {
  const next = filteredSnapshots.value[snapshotIndex.value + delta]
  if (next) selectSnapshot(next.snapshot_id)
}

// ---------- 展示口径 ----------
function complianceText(snap) {
  const { num, den } = snap.class_compliance || {}
  if (!den) return '—'
  return `${Math.round((num / den) * 100)}%`
}

function classText(cls) {
  return { 1: 'I 类', 2: 'II 类', 3: 'III 类', 4: 'IV 类', 5: 'V 类', 6: '劣 V 类' }[String(cls)] || `类别 ${cls}`
}

function bandText(band) {
  return { light: '轻度筛查', moderate: '中度筛查' }[band] || band || '—'
}

function locationText(status) {
  return LOCATION_STATUS_TEXT[status] || status || '—'
}

const freshnessText = computed(() =>
  ({ normal: '正常', delayed: '数据延迟', severely_overdue: '严重过期', unavailable: '不可用' })[summary.value?.freshness_status] || summary.value?.freshness_status || '—'
)

// /realtime/summary 不返回 chla_mean（仅时间轴有），回退到所选快照的时间轴统计
const chlaMeanText = computed(() => {
  const v = summary.value?.chla_mean ?? selectedSnapshot.value?.chla_mean
  return v != null ? `${v} μg/L` : '—'
})

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

watch([drawerOpen], ([d]) => {
  document.body.style.overflow = d ? 'hidden' : ''
})

// ---------- 初始化 ----------
onMounted(() => {
  const n = normalizeQuery(route.query)
  applied.start = n.start
  applied.end = n.end
  draft.start = n.start
  draft.end = n.end
  selectedSnapshotId.value = n.snapshot
  syncUrl()
  fetchCaps()
  fetchTimeline()
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  mobileMq?.removeEventListener('change', onMobileMqChange)
})
</script>

<style scoped>
.his-rt-replay {
  margin-top: 14px;
}
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
.his-title h1 {
  margin: 1px 0 0;
  font-family: var(--font-display);
  font-size: clamp(18px, 1.8vw, 24px);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
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

/* ---------- 筛选区 ---------- */
.his-date-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
}
.his-date-field {
  display: grid;
  gap: 3px;
}
.his-date-field span {
  font-size: 10.5px;
  color: var(--text-muted);
}
.his-date-field input {
  min-height: 38px;
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-family: var(--font-mono);
}
.his-date-field input:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.his-btn {
  appearance: none;
  min-height: 38px;
  padding: 4px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.his-btn--primary {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}
.his-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.his-filter-error {
  margin: 0;
  font-size: 11.5px;
  color: var(--risk-critical, #ff6b6b);
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

/* ---------- 快照列表 ---------- */
.his-list {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 620px;
  overflow-y: auto;
}
.his-list-note {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  display: grid;
  gap: 8px;
  justify-items: start;
}
.his-list-note--bad {
  color: var(--risk-critical, #ff6b6b);
}
.his-snap-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.his-snap-item {
  appearance: none;
  width: 100%;
  display: grid;
  gap: 3px;
  text-align: left;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  cursor: pointer;
}
.his-snap-item:hover {
  border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
}
.his-snap-item.active {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.his-snap-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.his-snap-time {
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.his-snap-meta {
  font-size: 11px;
  color: var(--text-secondary);
}
.his-snap-meta b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.his-snap-warn {
  color: var(--risk-critical, #ff6b6b);
}
.his-snap-sub {
  font-size: 10.5px;
  color: var(--text-muted);
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
.his-detail {
  padding: 12px 14px;
  min-height: 320px;
}
.his-detail-empty {
  display: grid;
  min-height: 280px;
  align-items: center;
}
.his-detail-body {
  display: grid;
  gap: 12px;
}
.his-detail-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.his-detail-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.his-detail-head h3 span {
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.his-detail-flag {
  font-size: 10.5px;
  font-family: var(--font-mono);
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, #5fd6a4 50%, transparent);
  color: #5fd6a4;
}
.his-detail-flag--old {
  border-color: color-mix(in srgb, #f5b45d 50%, transparent);
  color: #f5b45d;
}
.his-caps {
  list-style: none;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 6px 14px;
}
.his-caps li {
  font-size: 11.5px;
  color: var(--text-secondary);
}
.his-caps b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.his-cap-warn {
  color: var(--risk-critical, #ff6b6b);
}
.his-class-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.his-class-label {
  font-size: 11.5px;
  color: var(--text-secondary);
}
.his-class-chip {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.his-sec {
  display: grid;
  gap: 8px;
}
.his-sec h4 {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.his-sec-hint {
  margin-left: 8px;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--text-muted);
}
.his-sec-empty {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.his-table-wrap {
  overflow: auto;
  max-height: 340px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}
.his-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}
.his-table th,
.his-table td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
  white-space: nowrap;
}
.his-table th {
  position: sticky;
  top: 0;
  background: var(--surface-panel);
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10.5px;
}
.his-mono {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.his-miss {
  color: var(--text-muted);
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
  .his-chip {
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
  .his-body--m-list .his-rt-replay,
  .his-body--m-list .his-filterbar {
    display: none;
  }

  .his-body--m-detail {
    grid-template-areas:
      'title'
      'mdetail'
      'mplan'
      'foot';
  }
  .his-body--m-detail .his-detail {
    grid-area: mdetail;
  }
  .his-body--m-detail .his-plan {
    grid-area: mplan;
  }
  .his-body--m-detail .his-list,
  .his-body--m-detail .his-filterbar,
  .his-body--m-detail .his-filter-summary,
  .his-body--m-detail .his-rt-replay {
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
  .his-mb-btn:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
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
