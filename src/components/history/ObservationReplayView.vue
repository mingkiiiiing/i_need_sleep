<template>
  <div class="orp">
    <!-- ===== 筛选与播放控制 ===== -->
    <section class="orp-controls" aria-label="回放筛选与播放控制" data-role="replay-controls">
      <label class="orp-field">
        <span>开始日期</span>
        <input v-model="draft.start" type="date" data-role="replay-start" aria-label="开始日期" />
      </label>
      <label class="orp-field">
        <span>结束日期</span>
        <input v-model="draft.end" type="date" data-role="replay-end" aria-label="结束日期" />
      </label>
      <label class="orp-field">
        <span>站点（趋势）</span>
        <select v-model="station" aria-label="选择站点">
          <option value="" disabled>选择站点</option>
          <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.source_station_name }}</option>
        </select>
      </label>
      <label class="orp-field">
        <span>指标</span>
        <select v-model="indicator" aria-label="选择指标">
          <option v-for="v in REALTIME_VARIABLES" :key="v.code" :value="v.code">{{ v.label }}{{ v.unit ? `（${v.unit}）` : '' }}</option>
        </select>
      </label>
      <label class="orp-field">
        <span>快照频率</span>
        <select v-model="playMode" aria-label="快照频率">
          <option value="snapshot">逐快照</option>
          <option value="daily">每日最后一帧</option>
        </select>
      </label>
      <div class="orp-play">
        <button type="button" class="orp-btn" data-role="replay-prev" :disabled="!hasPrev" @click="step(-1)">◀ 上一帧</button>
        <button type="button" class="orp-btn orp-btn--primary" data-role="replay-play" @click="togglePlay">
          {{ playing ? '⏸ 暂停' : '▶ 播放' }}
        </button>
        <button type="button" class="orp-btn" data-role="replay-next" :disabled="!hasNext" @click="step(1)">下一帧 ▶</button>
      </div>
      <button type="button" class="orp-btn" data-role="replay-apply" @click="applyDates">应用日期</button>
      <p v-if="dateError" class="orp-error" role="alert">{{ dateError }}</p>
    </section>

    <!-- ===== 快照时间轴（横向） ===== -->
    <section class="orp-axis-wrap" aria-label="快照时间轴">
      <div v-if="axisState === 'loading'" class="orp-note">正在加载快照时间轴…</div>
      <div v-else-if="axisState === 'error'" class="orp-note orp-note--bad" role="alert">
        {{ axisError || '快照时间轴请求失败' }}
        <button type="button" class="orp-btn" @click="fetchAxis">重试</button>
      </div>
      <p v-else-if="!filteredSnapshots.length" class="orp-note">
        该日期范围内没有快照。系统自 2026-09-04 起随抓取自动积累，不做模拟补齐。
      </p>
      <div v-else class="orp-axis" data-role="replay-axis">
        <div v-for="group in dayGroups" :key="group.day" class="orp-axis-day">
          <span class="orp-axis-daylabel">{{ group.day }}</span>
          <div class="orp-axis-frames">
            <button
              v-for="snap in group.snaps"
              :key="snap.snapshot_id"
              type="button"
              class="orp-frame"
              :class="{ 'orp-frame--on': snap.snapshot_id === snapshotId, 'orp-frame--warn': snap.warning_count > 0 }"
              :data-snapshot="snap.snapshot_id"
              :title="`${snap.station_count} 站 · 预警 ${snap.warning_count}`"
              @click="selectSnapshot(snap.snapshot_id)"
            >{{ frameLabel(snap) }}</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== 地图 + 快照摘要 ===== -->
    <div class="orp-main">
      <section class="orp-map-panel" aria-label="历史站点地图">
        <header class="orp-panel-head">
          <p class="orp-kicker">SNAPSHOT MAP · 历史快照</p>
          <span v-if="summary" class="orp-badge" :class="{ 'orp-badge--old': !summary.is_latest }" data-role="replay-badge">
            {{ summary.is_latest ? '最新快照' : '历史快照回放（非最新）' }}
          </span>
        </header>
        <LakeMap
          v-model="mapStation"
          :point-list="mapPoints"
          :show-header="false"
          :show-tabs="false"
          :show-legend="false"
          :heat-visible="false"
          title="历史站点地图"
        />
        <footer class="orp-map-foot">
          <span><i class="orp-dot" style="background:#5fd6a4"></i>叶绿素a &lt;10</span>
          <span><i class="orp-dot" style="background:#f5b45d"></i>10–25 轻度筛查</span>
          <span><i class="orp-dot" style="background:#ef4444"></i>≥25 中度筛查</span>
          <span><i class="orp-dot" style="background:#7d93a8"></i>缺测</span>
          <span class="orp-map-note" v-if="summary">仅显示有坐标站点（无坐标 {{ noCoordCount }} 站不上图）；点击点位查看趋势</span>
        </footer>
      </section>

      <section class="orp-summary" aria-label="当前快照摘要">
        <header class="orp-panel-head">
          <p class="orp-kicker">SNAPSHOT SUMMARY · 当前快照</p>
          <span v-if="snapshotId" class="orp-mono orp-snap-id">{{ snapshotId }}</span>
        </header>
        <div v-if="sumState === 'loading'" class="orp-note">快照详情加载中…</div>
        <div v-else-if="sumState === 'error'" class="orp-note orp-note--bad" role="alert">
          {{ sumError || '快照详情请求失败' }}
          <button type="button" class="orp-btn" @click="fetchSummary">重试</button>
        </div>
        <template v-else-if="summary">
          <ul class="orp-caps" data-role="replay-summary">
            <li>活跃站点：<b>{{ summary.station_total }}</b></li>
            <li>水质达标率（≤III 类）：<b>{{ summary.class_iii_rate != null ? (summary.class_iii_rate * 100).toFixed(1) + '%' : '—' }}</b></li>
            <li>蓝藻筛查预警：<b :class="{ 'orp-cap-warn': (summary.warnings || []).length }">{{ (summary.warnings || []).length }} 站</b></li>
            <li>叶绿素 a 均值：<b>{{ chlaMeanText }}</b>（{{ summary.chla_report_stations }} 站报数）</li>
            <li>数据覆盖率：<b>{{ coverageText }}</b></li>
            <li>观测时间：<b class="orp-mono">{{ formatBeijing(summary.latest_observed_at) }}</b>（北京时间）</li>
            <li>抓取时间：<b class="orp-mono">{{ formatBeijing(summary.retrieved_at) }}</b>（北京时间）</li>
          </ul>
          <section class="orp-warn-sec" aria-label="蓝藻筛查预警站点">
            <h4>蓝藻筛查预警站点（{{ (summary.warnings || []).length }}）</h4>
            <p v-if="!(summary.warnings || []).length" class="orp-dim">该快照无蓝藻筛查预警站点。</p>
            <ul v-else class="orp-warn-list">
              <li v-for="w in summary.warnings" :key="w.station_id">
                <button type="button" class="orp-warn-item" @click="selectStation(w.station_id)">
                  {{ w.station_name }}<span class="orp-mono">{{ w.chla }} μg/L · {{ w.band === 'moderate' ? '中度' : '轻度' }}</span>
                </button>
              </li>
            </ul>
          </section>
          <details class="orp-fold" data-role="station-table-fold">
            <summary>全站观测明细大表（{{ (summary.markers || []).length }} 站有坐标，默认折叠）</summary>
            <div class="orp-table-wrap">
              <table class="orp-table">
                <thead>
                  <tr><th>站点</th><th>省份</th><th>水质类别</th><th>叶绿素 a</th><th>溶解氧</th><th>总磷</th><th>总氮</th></tr>
                </thead>
                <tbody>
                  <tr v-for="mk in summary.markers" :key="mk.id">
                    <td>{{ mk.name }}</td>
                    <td>{{ mk.province || '—' }}</td>
                    <td>{{ mk.water_level != null ? classText(String(mk.water_level)) : '—' }}</td>
                    <td :class="{ 'orp-miss': mk.chla == null }" class="orp-mono">{{ mk.chla != null ? mk.chla : '缺测' }}</td>
                    <td :class="{ 'orp-miss': mk.metrics?.dissolved_oxygen == null }" class="orp-mono">{{ mk.metrics?.dissolved_oxygen ?? '缺测' }}</td>
                    <td :class="{ 'orp-miss': mk.metrics?.total_phosphorus == null }" class="orp-mono">{{ mk.metrics?.total_phosphorus ?? '缺测' }}</td>
                    <td :class="{ 'orp-miss': mk.metrics?.total_nitrogen == null }" class="orp-mono">{{ mk.metrics?.total_nitrogen ?? '缺测' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>
        </template>
        <p v-else class="orp-note">在上方时间轴选择一次快照查看该时刻的全湖状态。</p>
      </section>
    </div>

    <!-- ===== 选中站点趋势 ===== -->
    <section class="orp-trend" aria-label="选中站点趋势曲线">
      <header class="orp-panel-head">
        <p class="orp-kicker">STATION TREND · 站点趋势</p>
        <span v-if="trendStationName" class="orp-trend-name">{{ trendStationName }} · {{ indicatorLabel }}</span>
      </header>
      <div v-if="!station" class="orp-note">在筛选区选择站点，或点击地图 / 预警站点查看该站历史观测趋势。</div>
      <div v-else-if="trendState === 'loading'" class="orp-note">趋势数据加载中…</div>
      <div v-else-if="trendState === 'error'" class="orp-note orp-note--bad" role="alert">趋势数据加载失败 <button type="button" class="orp-btn" @click="fetchTrend">重试</button></div>
      <p v-else-if="trendPoints.length < 2" class="orp-note">
        该站点在此日期范围内仅有 {{ trendPoints.length }} 次有效观测，暂不可绘制趋势；缺测不插值，不做模拟补齐。
      </p>
      <EChart v-else :option="trendOption" :height="240" data-role="replay-trend" />
    </section>
  </div>
</template>

<script setup>
// 观测回放视图（第二视图）：快照列表改为横向时间轴，地图成为主回放区域，
// 点击站点联动趋势曲线；全站大表默认折叠；历史快照状态显式标注且不跳回最新。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EChart from '../cockpit/EChart.vue'
import LakeMap from '../cockpit/LakeMap.vue'
import { palette } from '../cockpit/echartsTheme.js'
import {
  REALTIME_VARIABLES,
  chlaColor,
  fetchRealtimeStations,
  fetchRealtimeSummary,
  fetchRealtimeTimeline,
  fetchStationObservations
} from '../../services/realtime.js'
import { formatBeijing } from '../../services/historyReview.js'

const route = useRoute()
const router = useRouter()

const draft = reactive({ start: '', end: '' })
const applied = reactive({ start: '', end: '' })
const dateError = ref('')

const axisState = ref('loading')
const axisError = ref('')
const snapshots = ref([])

const snapshotId = ref('')
const sumState = ref('idle')
const sumError = ref('')
const summary = ref(null)

const stations = ref([])
const station = ref('')
const mapStation = ref('')
const indicator = ref('chlorophyll_a')
const playMode = ref('snapshot')
const playing = ref(false)
let playTimer = null

const trendState = ref('idle')
const trendRows = ref([])

// ---------- URL 契约：start/end/snapshot/station/indicator 写入 query ----------
function normalizeQuery(query = {}) {
  const date = (v) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '')
  return {
    start: date(query.start),
    end: date(query.end),
    snapshot: typeof query.snapshot === 'string' ? query.snapshot : '',
    station: typeof query.station === 'string' ? query.station : '',
    indicator: typeof query.indicator === 'string' && query.indicator ? query.indicator : 'chlorophyll_a'
  }
}

function syncUrl() {
  const query = { ...(route.query.view ? { view: route.query.view } : { view: 'replay' }) }
  if (applied.start) query.start = applied.start
  if (applied.end) query.end = applied.end
  if (snapshotId.value) query.snapshot = snapshotId.value
  if (station.value) query.station = station.value
  if (indicator.value && indicator.value !== 'chlorophyll_a') query.indicator = indicator.value
  router.replace({ query }).catch(() => {})
}

// ---------- 快照时间轴 ----------
async function fetchAxis() {
  axisState.value = 'loading'
  axisError.value = ''
  try {
    const data = await fetchRealtimeTimeline({ force: true })
    snapshots.value = Array.isArray(data?.snapshots) ? data.snapshots : []
    axisState.value = 'ok'
    normalizeSnapshot()
  } catch (err) {
    snapshots.value = []
    axisState.value = 'error'
    axisError.value = err?.message || '快照时间轴请求失败'
  }
}

const filteredSnapshots = computed(() =>
  snapshots.value.filter((snap) => {
    const day = String(snap.latest_observed_at || '').slice(0, 10)
    if (!day) return false
    if (applied.start && day < applied.start) return false
    if (applied.end && day > applied.end) return false
    return true
  })
)

const dayGroups = computed(() => {
  const groups = []
  filteredSnapshots.value.forEach((snap) => {
    const day = String(snap.latest_observed_at || '').slice(0, 10)
    const last = groups[groups.length - 1]
    if (last && last.day === day) last.snaps.push(snap)
    else groups.push({ day, snaps: [snap] })
  })
  return groups
})

function normalizeSnapshot() {
  if (axisState.value !== 'ok') return
  const exists = filteredSnapshots.value.some((s) => s.snapshot_id === snapshotId.value)
  if (snapshotId.value && !exists) {
    snapshotId.value = ''
    syncUrl()
  }
  // 仅在无有效选中时默认选最新；URL 指定的历史快照不跳回最新值
  if (!snapshotId.value && filteredSnapshots.value.length) {
    snapshotId.value = filteredSnapshots.value[filteredSnapshots.value.length - 1].snapshot_id
    syncUrl()
  }
}

function selectSnapshot(id) {
  if (!id || id === snapshotId.value) return
  snapshotId.value = id
  syncUrl()
}

function frameLabel(snap) {
  const iso = String(snap.latest_observed_at || '')
  return iso.slice(11, 16)
}

// ---------- 播放（逐快照 / 每日最后一帧） ----------
const playFrames = computed(() => {
  if (playMode.value === 'snapshot') return filteredSnapshots.value
  const lastByDay = new Map()
  filteredSnapshots.value.forEach((snap) => {
    const day = String(snap.latest_observed_at || '').slice(0, 10)
    lastByDay.set(day, snap)
  })
  return Array.from(lastByDay.values())
})

const frameIndex = computed(() => playFrames.value.findIndex((s) => s.snapshot_id === snapshotId.value))
const hasPrev = computed(() => frameIndex.value > 0)
const hasNext = computed(() => frameIndex.value >= 0 && frameIndex.value < playFrames.value.length - 1)

function step(delta) {
  const next = playFrames.value[frameIndex.value + delta]
  if (next) selectSnapshot(next.snapshot_id)
}

function togglePlay() {
  playing.value = !playing.value
}

watch(playing, (on) => {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  if (!on) return
  playTimer = setInterval(() => {
    if (!hasNext.value) {
      playing.value = false
      return
    }
    step(1)
  }, 1200)
})

watch(playMode, () => {
  playing.value = false
})

// ---------- 快照摘要 ----------
async function fetchSummary() {
  if (!snapshotId.value) {
    summary.value = null
    sumState.value = 'idle'
    return
  }
  sumState.value = 'loading'
  sumError.value = ''
  try {
    summary.value = await fetchRealtimeSummary({ snapshotId: snapshotId.value })
    sumState.value = 'ok'
  } catch (err) {
    summary.value = null
    sumState.value = 'error'
    sumError.value = err?.message || '快照详情请求失败'
  }
}

watch(snapshotId, fetchSummary)

const noCoordCount = computed(() =>
  summary.value ? Math.max(0, (summary.value.station_total || 0) - (summary.value.markers || []).length) : 0
)

const chlaMeanText = computed(() => {
  // /realtime/summary 的均值在 means.chlorophyll_a（chla_mean 只存在于 timeline 快照）
  const v = summary.value?.means?.chlorophyll_a?.value
  return v != null ? `${v} μg/L` : '—'
})

const coverageText = computed(() => {
  const rate = summary.value?.health?.subscores?.completeness?.rate
  return rate != null ? `${(rate * 100).toFixed(1)}%` : '—'
})

const mapPoints = computed(() =>
  (summary.value?.markers || []).map((mk) => ({
    id: mk.id,
    short: mk.name || '',
    name: mk.name || '',
    color: chlaColor(mk.chla),
    coord: { lat: mk.lat, lon: mk.lon }
  }))
)

watch(mapStation, (id) => {
  if (id) selectStation(id)
})

function selectStation(id) {
  if (!id) return
  station.value = id
  syncUrl()
}

// ---------- 站点趋势 ----------
function todayLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function fetchTrend() {
  if (!station.value) {
    trendRows.value = []
    trendState.value = 'idle'
    return
  }
  trendState.value = 'loading'
  try {
    const rows = await fetchStationObservations(station.value, {
      window: 'range',
      start: applied.start || '2026-09-01',
      end: applied.end || todayLocal(),
      variables: [indicator.value]
    })
    // 同一快照按观测时间取最新一行
    const bySnapshot = new Map()
    rows.forEach((row) => {
      const prev = bySnapshot.get(row.snapshot_id)
      if (!prev || String(row.observed_at) > String(prev.observed_at)) bySnapshot.set(row.snapshot_id, row)
    })
    trendRows.value = Array.from(bySnapshot.values()).sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
    trendState.value = 'ok'
  } catch {
    trendRows.value = []
    trendState.value = 'error'
  }
}

watch([station, indicator, () => applied.start, () => applied.end], fetchTrend)

const trendPoints = computed(() =>
  trendRows.value
    .map((row) => ({
      t: row.observed_at,
      v: row.observation_status === 'ok' ? row.value : null
    }))
    .filter((p) => p.t)
)

const indicatorLabel = computed(() => {
  const found = REALTIME_VARIABLES.find((v) => v.code === indicator.value)
  return found ? `${found.label}${found.unit ? `（${found.unit}）` : ''}` : indicator.value
})

const trendStationName = computed(() => {
  const found = stations.value.find((s) => s.id === station.value)
  return found?.source_station_name || ''
})

const trendOption = computed(() => {
  const p = palette()
  const isChla = indicator.value === 'chlorophyll_a'
  const markerTime = summary.value?.latest_observed_at
  return {
    grid: { left: 52, right: 18, top: 26, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text, fontSize: 11 },
      valueFormatter: (v) => (v == null ? '缺测' : String(v))
    },
    xAxis: {
      type: 'category',
      data: trendPoints.value.map((point) => formatBeijing(point.t)),
      axisLabel: { color: p.muted, fontSize: 9.5, interval: Math.max(0, Math.floor(trendPoints.value.length / 8)) },
      axisLine: { lineStyle: { color: p.lineStrong } }
    },
    yAxis: {
      type: 'value',
      name: indicatorLabel.value,
      nameTextStyle: { color: p.muted, fontSize: 10 },
      axisLabel: { color: p.muted, fontSize: 10 },
      splitLine: { lineStyle: { color: p.line } }
    },
    series: [
      {
        name: indicatorLabel.value,
        type: 'line',
        data: trendPoints.value.map((point) => point.v),
        connectNulls: false,
        showSymbol: trendPoints.value.length <= 40,
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            ...(isChla
              ? [
                  { yAxis: 10, lineStyle: { color: '#f5b45d', type: 'dashed', width: 1 }, label: { formatter: '轻度 10', fontSize: 9, color: '#f5b45d' } },
                  { yAxis: 25, lineStyle: { color: '#ef4444', type: 'dashed', width: 1 }, label: { formatter: '中度 25', fontSize: 9, color: '#ef4444' } }
                ]
              : []),
            ...(markerTime
              ? [{
                  xAxis: formatBeijing(markerTime),
                  lineStyle: { color: p.accent, type: 'dotted', width: 1 },
                  label: { formatter: '当前快照', fontSize: 9, color: p.textSoft }
                }]
              : [])
          ]
        }
      }
    ]
  }
})

// ---------- 展示口径 ----------
function classText(cls) {
  return { 1: 'I 类', 2: 'II 类', 3: 'III 类', 4: 'IV 类', 5: 'V 类', 6: '劣 V 类' }[String(cls)] || `类别 ${cls}`
}

// ---------- 日期应用 ----------
function applyDates() {
  if (draft.start && draft.end && draft.start > draft.end) {
    dateError.value = '开始日期不能晚于结束日期'
    return
  }
  dateError.value = ''
  applied.start = draft.start
  applied.end = draft.end
  syncUrl()
  normalizeSnapshot()
}

// ---------- 外部 URL 变化（事件复盘跳转 / 前进后退） ----------
watch(() => route.query, (q) => {
  const n = normalizeQuery(q)
  if (n.start !== applied.start) {
    applied.start = n.start
    draft.start = n.start
  }
  if (n.end !== applied.end) {
    applied.end = n.end
    draft.end = n.end
  }
  if (n.station !== station.value) station.value = n.station
  if (n.indicator !== indicator.value) indicator.value = n.indicator
  if (n.snapshot !== snapshotId.value) {
    snapshotId.value = n.snapshot
    if (n.snapshot) fetchSummary()
  }
})

// ---------- 初始化 ----------
onMounted(async () => {
  const n = normalizeQuery(route.query)
  applied.start = n.start
  applied.end = n.end
  draft.start = n.start
  draft.end = n.end
  snapshotId.value = n.snapshot
  station.value = n.station
  indicator.value = n.indicator
  fetchAxis()
  fetchTrend()
  try {
    stations.value = await fetchRealtimeStations()
  } catch {
    stations.value = []
  }
})

onBeforeUnmount(() => {
  if (playTimer) clearInterval(playTimer)
})
</script>

<style scoped>
.orp {
  display: grid;
  gap: 6px;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr);
}
.orp-controls {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.orp-field {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.orp-field span {
  font-size: 10px;
  color: var(--text-muted);
}
.orp-field input,
.orp-field select {
  min-height: 34px;
  padding: 3px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  font-family: var(--font-mono);
}
.orp-field input:focus-visible,
.orp-field select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.orp-play {
  display: flex;
  gap: 4px;
}
.orp-btn {
  appearance: none;
  min-height: 34px;
  padding: 3px 13px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.orp-btn--primary {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}
.orp-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.orp-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.orp-error {
  margin: 0;
  font-size: 11px;
  color: var(--risk-critical, #ef4444);
}
.orp-axis-wrap {
  padding: 8px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.orp-axis {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.orp-axis-day {
  display: grid;
  gap: 3px;
  flex: 0 0 auto;
}
.orp-axis-daylabel {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.orp-axis-frames {
  display: flex;
  gap: 4px;
}
.orp-frame {
  appearance: none;
  min-height: 26px;
  padding: 1px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 10.5px;
  cursor: pointer;
  white-space: nowrap;
}
.orp-frame--warn {
  border-color: color-mix(in srgb, #f5b45d 45%, transparent);
}
.orp-frame--on {
  border-color: color-mix(in srgb, var(--color-primary) 65%, transparent);
  background: color-mix(in srgb, var(--color-primary) 15%, transparent);
  color: var(--text-primary);
}
.orp-frame:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.orp-main {
  display: grid;
  grid-template-columns: minmax(0, 58fr) minmax(0, 42fr);
  gap: 6px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
}
.orp-map-panel,
.orp-summary,
.orp-trend {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 12px 12px;
  display: grid;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  align-content: start;
}
.orp-map-panel :deep(.leaflet-map-container) {
  width: 100%;
  height: 380px;
  border-radius: 10px;
}
.orp-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.orp-kicker {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.orp-badge {
  font-size: 10.5px;
  font-family: var(--font-mono);
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, #5fd6a4 50%, transparent);
  color: #5fd6a4;
}
.orp-badge--old {
  border-color: color-mix(in srgb, #f5b45d 50%, transparent);
  color: #f5b45d;
}
.orp-map-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 10px;
  color: var(--text-muted);
}
.orp-map-foot span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.orp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.orp-map-note {
  margin-left: auto;
}
.orp-snap-id {
  font-size: 10px;
  color: var(--text-muted);
  word-break: break-all;
}
.orp-mono {
  font-family: var(--font-mono);
}
.orp-caps {
  list-style: none;
  margin: 0;
  padding: 9px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  display: grid;
  gap: 4px;
}
.orp-caps li {
  font-size: 11.5px;
  color: var(--text-secondary);
}
.orp-caps b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.orp-cap-warn {
  color: var(--risk-critical, #ef4444);
}
.orp-note {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.orp-note--bad {
  color: var(--risk-critical, #ef4444);
  display: flex;
  gap: 10px;
  align-items: center;
}
.orp-dim {
  font-size: 11px;
  color: var(--text-muted);
}
.orp-warn-sec h4 {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.orp-warn-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.orp-warn-item {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 2px 11px;
  border: 1px solid color-mix(in srgb, #f5b45d 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, #f5b45d 8%, transparent);
  color: var(--text-primary);
  font-size: 11.5px;
  cursor: pointer;
}
.orp-warn-item .orp-mono {
  font-size: 10px;
  color: var(--text-muted);
}
.orp-warn-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.orp-fold summary {
  cursor: pointer;
  font-size: 11.5px;
  color: var(--text-secondary);
  user-select: none;
}
.orp-table-wrap {
  margin-top: 8px;
  overflow: auto;
  max-height: 300px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}
.orp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.orp-table th,
.orp-table td {
  padding: 4px 9px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
  white-space: nowrap;
}
.orp-table th {
  position: sticky;
  top: 0;
  background: var(--surface-panel);
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10px;
}
.orp-miss {
  color: var(--text-muted);
}
.orp-trend-name {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
@media (max-width: 1100px) {
  .orp-main {
    grid-template-columns: minmax(0, 1fr);
  }
  .orp-map-panel :deep(.leaflet-map-container) {
    height: 300px;
  }
}
</style>
