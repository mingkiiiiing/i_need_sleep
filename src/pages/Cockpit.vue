<template>
  <main class="page-rc">
    <!-- ===== 全屏地图（observed 轨） ===== -->
    <div class="rc-map" aria-label="太湖流域国控站点实时地图">
      <LakeMap
        :model-value="selectedId"
        :point-list="mapPoints"
        title="太湖流域 · MEE 国控站点实时态势"
        :show-tabs="false"
        :show-legend="false"
        points-visible
        @update:model-value="selectedId = $event"
        @tile-error="onTileError"
      />
    </div>

    <!-- ===== 顶部汇总条 ===== -->
    <div v-if="state === 'error'" class="rc-chip rc-chip--top rc-chip--error" role="alert">
      实时汇总加载失败（不会回退情景数据）
      <button type="button" class="rc-btn" @click="load(true)">重试</button>
    </div>
    <div v-else-if="summary && summary.freshness_status === 'historical'" class="rc-chip rc-chip--top" role="status">
      <strong>历史快照回放</strong>
      <span>观测 {{ formatStamp(summary.latest_observed_at) }} · 点击时间轴最后一个刻度或刷新返回最新</span>
    </div>
    <div v-else-if="summary && summary.freshness_status !== 'normal'" class="rc-chip rc-chip--top rc-chip--error" role="status">
      实时数据{{ FRESHNESS_TEXT[summary.freshness_status] || summary.freshness_status }}：当前展示最后成功抓取数据
      （观测 {{ formatStamp(summary.latest_observed_at) }}，滞后 {{ formatLag(summary.observed_lag_h) }}）
    </div>
    <div v-else-if="summary" class="rc-chip rc-chip--top" role="status">
      <strong>{{ monthDayText }}</strong>
      <span>全湖以 <b>{{ summary.dominant_class }} 类</b>为主（{{ compliancePct }}% 达标 III 类）</span>
      <span class="rc-chip-warn" :class="{ 'rc-chip-warn--on': summary.warnings.length }">
        {{ summary.warnings.length }} 站蓝藻筛查预警{{ warnBrief }}
      </span>
    </div>

    <!-- ===== 更新时间 ===== -->
    <div v-if="summary" class="rc-chip rc-chip--updated">
      <span class="rc-dot" :class="summary.freshness_status === 'normal' ? 'rc-dot--ok' : 'rc-dot--warn'"></span>
      更新 {{ formatStamp(summary.latest_observed_at) }}
    </div>

    <!-- ===== 右侧浮层卡片 ===== -->
    <aside class="rc-cards" aria-label="全湖实时态势卡片">
      <!-- 湖体健康 -->
      <section class="rc-card" aria-label="湖体健康">
        <div class="rc-card-head">
          <h2>湖体健康</h2>
          <span class="rc-grade" :class="`rc-grade--${summary?.health?.grade}`">{{ healthGradeText(summary?.health?.grade) }}</span>
        </div>
        <div class="rc-health">
          <div class="rc-gauge" role="img" :aria-label="`湖体健康分 ${summary?.health?.score ?? '—'}`">
            <svg viewBox="0 0 120 120">
              <circle class="rc-gauge-track" cx="60" cy="60" r="52" />
              <circle
                class="rc-gauge-value"
                cx="60" cy="60" r="52"
                :stroke-dasharray="`${gaugeDash} ${GAUGE_LEN - gaugeDash}`"
              />
            </svg>
            <div class="rc-gauge-center">
              <strong>{{ summary?.health?.score ?? '—' }}</strong>
            </div>
          </div>
          <div class="rc-bars">
            <div v-for="bar in healthBars" :key="bar.label" class="rc-bar-row">
              <span class="rc-bar-label">{{ bar.label }}</span>
              <span class="rc-bar-track"><i :style="{ width: bar.pct + '%' }"></i></span>
              <span class="rc-bar-num">{{ bar.num }}/{{ bar.den }}</span>
            </div>
          </div>
        </div>
        <div class="rc-stats">
          <div class="rc-stat"><strong>{{ summary?.station_total ?? '—' }}</strong><span>监测站</span></div>
          <div class="rc-stat" :class="{ 'rc-stat--bad': (summary?.warnings?.length || 0) > 0 }">
            <strong>{{ summary?.warnings?.length ?? '—' }}</strong><span>预警</span>
          </div>
          <div class="rc-stat"><strong>{{ fmtMean('water_temperature') }}</strong><span>°C 水温</span></div>
          <div class="rc-stat"><strong>{{ fmtMean('chlorophyll_a') }}</strong><span>μg/L Chl-a</span></div>
          <div class="rc-stat"><strong>{{ fmtMean('dissolved_oxygen') }}</strong><span>mg/L DO</span></div>
        </div>
      </section>

      <!-- 蓝藻预警 -->
      <section class="rc-card" aria-label="蓝藻筛查预警">
        <div class="rc-card-head">
          <h2>蓝藻预警</h2>
          <span v-if="summary?.warnings?.length" class="rc-badge">{{ summary.warnings.length }}</span>
        </div>
        <p v-if="!summary?.warnings?.length" class="rc-empty">
          暂无报数站点超过筛查阈值（chla {{ summary?.warning_thresholds?.light ?? 10 }} μg/L）
        </p>
        <ul v-else class="rc-warn-list">
          <li v-for="w in summary.warnings" :key="w.station_id">
            <button type="button" class="rc-warn-item" @click="focusStation(w)">
              <span class="rc-warn-name">
                <strong>{{ w.station_name }}</strong>
                <small>太湖流域 · Chl-a {{ w.chla }} μg/L</small>
              </span>
              <span class="rc-band" :class="w.band === 'moderate' ? 'rc-band--moderate' : 'rc-band--light'">
                {{ w.band === 'moderate' ? '中度' : '轻度' }}
              </span>
            </button>
          </li>
        </ul>
      </section>

      <!-- 关键指标 -->
      <section class="rc-card" aria-label="关键指标（全湖均值与短期趋势）">
        <div class="rc-card-head">
          <h2>关键指标</h2>
          <span class="rc-card-tag">全湖均值 · 环比上一快照</span>
        </div>
        <ul class="rc-kpi-list">
          <li v-for="row in kpiRows" :key="row.code">
            <span class="rc-kpi-dot" :style="{ background: row.dot }"></span>
            <span class="rc-kpi-label">{{ row.label }}</span>
            <small class="rc-kpi-unit">{{ row.unit }}</small>
            <strong class="rc-kpi-value">{{ row.value }}</strong>
            <span class="rc-kpi-trend" :class="`rc-trend--${row.chip.tone}`">{{ row.chip.text }}</span>
          </li>
        </ul>
        <p v-if="summary" class="rc-kpi-note">均值仅统计报数站（chla {{ summary.means?.chlorophyll_a?.count ?? 0 }}/{{ summary.station_total }} 站），缺测不参与。</p>
      </section>
    </aside>

    <!-- ===== 点位图例（chla 筛查口径，替代 LakeMap 情景风险图例） ===== -->
    <div class="rc-legend" aria-label="点位颜色图例">
      <span><i class="rc-lg-dot" style="background: #5fd6a4"></i>正常 &lt;10</span>
      <span><i class="rc-lg-dot" style="background: #f5b45d"></i>轻度 10–25</span>
      <span><i class="rc-lg-dot" style="background: #ff6b6b"></i>中度 ≥25</span>
      <span><i class="rc-lg-dot" style="background: #7d93a8"></i>未报数</span>
      <em>μg/L · 点击点位看详情</em>
    </div>

    <!-- ===== 底部：真实快照回放时间轴 ===== -->
    <div v-if="timeline && timeline.snapshots.length" class="rc-timeline" aria-label="真实快照回放时间轴">
      <button
        type="button"
        class="rc-tl-play"
        :aria-label="playing ? '暂停回放' : '播放回放'"
        @click="togglePlay"
      >
        {{ playing ? '❚❚' : '▶' }}
      </button>
      <div class="rc-tl-track" role="tablist" aria-label="快照刻度">
        <button
          v-for="(snap, i) in timeline.snapshots"
          :key="snap.snapshot_id"
          type="button"
          role="tab"
          class="rc-tl-tick"
          :class="{
            active: activeSnapshotId === snap.snapshot_id,
            latest: snap.snapshot_id === timeline.latest_snapshot_id,
            'has-warn': snap.warning_count > 0
          }"
          :aria-selected="String(activeSnapshotId === snap.snapshot_id)"
          :title="`${stampTick(snap)} · 达标 ${snap.class_compliance.num}/${snap.class_compliance.den} · 预警 ${snap.warning_count}`"
          @click="selectSnapshot(snap.snapshot_id)"
        >
          <span class="rc-tl-line"></span>
          <span class="rc-tl-label">{{ tickLabel(snap) }}</span>
        </button>
      </div>
      <span class="rc-tl-state" :class="{ 'rc-tl-state--replay': !isLatestView }">
        {{ isLatestView ? '● 最新' : '⟲ 历史回放' }}
      </span>
    </div>

    <!-- ===== 站点详情抽屉 / 分析面板 ===== -->
    <CockpitStationDrawer
      v-if="drawerOpen && selectedId"
      :station-id="selectedId"
      :station="drawerStation"
      @close="drawerOpen = false"
      @open-analysis="openAnalysis"
    />
    <CockpitAnalysisPanel
      v-if="analysisOpen"
      :open="analysisOpen"
      :initial-station-id="analysisStationId"
      @close="analysisOpen = false"
    />
  </main>
</template>

<script setup>
// 综合驾驶舱（observed 实时轨改造版）：全屏地图 + 浮层卡片。
// 所有数值来自 /api/v1/realtime/summary 的真实观测计算；健康分/预警均为透明口径的派生指标，
// 与 simulated 情景内容（时空推演页）严格分轨。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import CockpitStationDrawer from '../components/stations/CockpitStationDrawer.vue'
import CockpitAnalysisPanel from '../components/stations/CockpitAnalysisPanel.vue'
import {
  chlaColor,
  fetchRealtimeSummary,
  fetchRealtimeTimeline,
  formatLag,
  formatStamp,
  FRESHNESS_TEXT,
  healthGradeText,
  trendChip
} from '../services/realtime.js'

const summary = ref(null)
const state = ref('loading')
const selectedId = ref('')
// 点击点位 → 详情抽屉；“在分析面板中打开” → 底部大图面板
const drawerOpen = ref(false)
const analysisOpen = ref(false)
const analysisStationId = ref('')
// 真实快照回放：'' = 最新；否则为 timeline 中某个 snapshot_id
const timeline = ref(null)
const activeSnapshotId = ref('')
const playing = ref(false)
let playTimer = null

const GAUGE_LEN = 2 * Math.PI * 52

async function load(force = false) {
  if (force) state.value = 'loading'
  try {
    summary.value = await fetchRealtimeSummary({
      force,
      snapshotId: activeSnapshotId.value || undefined
    })
    state.value = 'ok'
  } catch {
    summary.value = null
    state.value = 'error'
  }
}

async function loadTimeline(force = false) {
  try {
    timeline.value = await fetchRealtimeTimeline({ force })
  } catch {
    // 时间轴失败不打断主视图，仅隐藏回放条
    timeline.value = null
  }
}

const isLatestView = computed(
  () => !activeSnapshotId.value || activeSnapshotId.value === timeline.value?.latest_snapshot_id
)

function selectSnapshot(id) {
  if (!id || id === activeSnapshotId.value) return
  activeSnapshotId.value = id
  stopPlay()
  load()
}

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  playing.value = false
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
    return
  }
  const snaps = timeline.value?.snapshots || []
  if (snaps.length < 2) return
  playing.value = true
  const step = () => {
    const ids = (timeline.value?.snapshots || []).map((s) => s.snapshot_id)
    if (!ids.length) return stopPlay()
    const at = ids.indexOf(activeSnapshotId.value)
    const next = ids[Math.min(at + 1, ids.length - 1)]
    if (next === activeSnapshotId.value || at === ids.length - 1) return stopPlay()
    activeSnapshotId.value = next
    load()
  }
  playTimer = setInterval(step, 2200)
  step()
}

onMounted(() => {
  load()
  loadTimeline()
})



function openAnalysis(stationId) {
  analysisStationId.value = stationId || selectedId.value
  analysisOpen.value = true
}



watch(selectedId, (id) => {
  if (id) drawerOpen.value = true
})





// ---------- 派生展示 ----------
const monthDayText = computed(() => {
  const m = String(summary.value?.latest_observed_at || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${Number(m[2])}月${Number(m[3])}日` : ''
})

function stampTick(snap) {
  return formatStamp(snap.latest_observed_at || snap.retrieved_at_utc)
}

function tickLabel(snap) {
  const m = String(snap.latest_observed_at || snap.retrieved_at_utc || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '—'
}

const compliancePct = computed(() =>
  summary.value?.class_iii_rate != null ? Math.round(summary.value.class_iii_rate * 100) : '—'
)

const warnBrief = computed(() => {
  const list = summary.value?.warnings || []
  if (!list.length) return ''
  const names = list.slice(0, 2).map((w) => w.station_name).join('、')
  return `（${names}${list.length > 2 ? ' 等' : ''}）`
})

const gaugeDash = computed(() => {
  const score = Number(summary.value?.health?.score)
  if (!Number.isFinite(score)) return 0
  return Math.max(0, Math.min(100, score)) / 100 * GAUGE_LEN
})

const healthBars = computed(() => {
  const sub = summary.value?.health?.subscores || {}
  const rows = []
  const rate = (v) => (v == null ? 0 : Math.round(v * 100))
  if (sub.class_compliance) rows.push({ label: '达标率', ...sub.class_compliance, pct: rate(sub.class_compliance.rate) })
  if (sub.algae_normal) rows.push({ label: '蓝藻正常', ...sub.algae_normal, pct: rate(sub.algae_normal.rate) })
  // 短期趋势：5 项关键指标中环比持平（|Δ|<3%）占比
  const trends = Object.values(summary.value?.trends || {})
  const flat = trends.filter((t) => t.direction === 'flat').length
  if (trends.length) rows.push({ label: '环比持平', num: flat, den: trends.length, pct: Math.round((flat / trends.length) * 100) })
  if (sub.completeness) rows.push({ label: '数据完整度', ...sub.completeness, pct: rate(sub.completeness.rate) })
  return rows
})

const kpiRows = computed(() => {
  const defs = [
    { code: 'chlorophyll_a', label: '叶绿素 a', unit: 'μg/L', dot: '#5fd6a4' },
    { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L', dot: '#7ec8ff' },
    { code: 'total_phosphorus', label: '总磷', unit: 'mg/L', dot: '#f5b45d' },
    { code: 'total_nitrogen', label: '总氮', unit: 'mg/L', dot: '#ff8a8a' },
    { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L', dot: '#b28aff' }
  ]
  const means = summary.value?.means || {}
  const trends = summary.value?.trends || {}
  return defs.map(({ code, label, unit, dot }) => ({
    code,
    label,
    unit,
    dot,
    value: means[code]?.value ?? '—',
    chip: trendChip(trends[code])
  }))
})

const fmtMean = (code) => {
  const v = summary.value?.means?.[code]?.value
  return v == null ? '—' : Number(v).toFixed(2)
}

function buildHoverCard(m) {
  // 悬停指标卡（lidantech 同款交互）：全部动态值走 textContent，防注入
  const el = document.createElement('div')
  el.className = 'rc-hover-card'
  const head = document.createElement('div')
  head.className = 'rhc-head'
  const name = document.createElement('strong')
  name.textContent = m.name || '—'
  const level = document.createElement('span')
  level.className = 'rhc-level'
  level.textContent = m.water_level ? `${m.water_level}类` : ''
  head.append(name, level)
  const grid = document.createElement('div')
  grid.className = 'rhc-grid'
  const SHOW = [
    ['chlorophyll_a', '叶绿素a', 'μg/L'],
    ['dissolved_oxygen', '溶解氧', 'mg/L'],
    ['total_phosphorus', '总磷', 'mg/L'],
    ['total_nitrogen', '总氮', 'mg/L'],
    ['ammonia_nitrogen', '氨氮', 'mg/L'],
    ['cod_mn', 'CODMn', 'mg/L']
  ]
  SHOW.forEach(([code, label, unit]) => {
    const row = document.createElement('div')
    row.className = 'rhc-item'
    const k = document.createElement('span')
    k.className = 'rhc-k'
    k.textContent = label
    const v = document.createElement('span')
    v.className = 'rhc-v'
    const metric = m.metrics ? m.metrics[code] : undefined
    const b = document.createElement('b')
    b.textContent = metric != null ? String(metric) : '--'
    const u = document.createElement('small')
    u.textContent = ` ${unit}`
    v.append(b, u)
    row.append(k, v)
    grid.append(row)
  })
  const foot = document.createElement('div')
  foot.className = 'rhc-foot'
  foot.textContent = '蓝藻：' + (m.chla == null ? '无数据' : m.chla >= 25 ? '中度预警' : m.chla >= 10 ? '轻度关注' : '正常') + ' · 点击查看详情'
  el.append(head, grid, foot)
  return el
}

const mapPoints = computed(() =>
  (summary.value?.markers || []).map((m) => ({
    id: m.id,
    short: '',
    name: '',
    hideLabel: true,
    color: chlaColor(m.chla),
    coord: { lat: m.lat, lon: m.lon },
    tooltipNode: buildHoverCard(m)
  }))
)

const drawerStation = computed(
  () => (summary.value?.markers || []).find((m) => m.id === selectedId.value) || null
)

function focusStation(w) {
  selectedId.value = w.station_id
}

let tileErrorFlag = ref(false)
function onTileError(v) {
  tileErrorFlag.value = v
}
</script>

<style scoped>
.page-rc {
  position: relative;
  height: calc(100vh - 96px);
  min-height: 560px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  overflow: hidden;
  background: var(--surface-panel);
}
.rc-map { position: absolute; inset: 0; }
.rc-map :deep(.map-panel) { height: 100%; border: none; background: transparent; }
.rc-map :deep(.leaflet-map-container) { height: 100%; }

/* 顶部汇总条 */
.rc-chip {
  position: absolute;
  z-index: 900;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--panel-strong, var(--surface-panel));
  color: var(--text-primary);
  font-size: 13px;
  white-space: nowrap;
}
.rc-chip--top { top: 14px; left: 50%; transform: translateX(-50%); max-width: min(92%, 860px); overflow: hidden; }
.rc-chip--top b { color: var(--color-primary); }
.rc-chip-warn { color: var(--text-secondary); }
.rc-chip-warn--on { color: var(--risk-critical, #ff6b6b); font-weight: 700; }
.rc-chip--error { border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 55%, transparent); color: var(--risk-critical, #ff6b6b); }
.rc-chip--updated { top: 14px; right: 396px; font-family: var(--font-mono); font-size: 12px; }
.rc-dot { width: 8px; height: 8px; border-radius: 999px; display: inline-block; }
.rc-dot--ok { background: var(--risk-low, #5fd6a4); }
.rc-dot--warn { background: var(--risk-medium, #f5b45d); }
.rc-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 30px;
  padding: 2px 12px;
  cursor: pointer;
}

/* 右侧卡片列 */
.rc-cards {
  position: absolute;
  z-index: 900;
  top: 14px;
  right: 14px;
  bottom: 44px;
  width: 368px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding-left: 2px;
}
.rc-card {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--panel-strong, var(--surface-panel));
  padding: 12px 14px;
  flex: none;
}
.rc-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.rc-card-head h2 { margin: 0; font-size: 14px; color: var(--text-primary); }
.rc-card-tag { font-size: 10.5px; color: var(--text-muted); }
.rc-grade { font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 999px; border: 1px solid var(--border-subtle); color: var(--risk-low, #5fd6a4); }
.rc-grade--fair { color: var(--risk-medium, #f5b45d); }
.rc-grade--poor { color: var(--risk-critical, #ff6b6b); }

.rc-health { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 12px; align-items: center; }
.rc-gauge { position: relative; width: 108px; height: 108px; }
.rc-gauge svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.rc-gauge-track, .rc-gauge-value { fill: none; stroke-width: 10; stroke-linecap: round; }
.rc-gauge-track { stroke: var(--border-subtle); }
.rc-gauge-value { stroke: var(--risk-low, #5fd6a4); transition: stroke-dasharray 0.6s ease; }
.rc-gauge-center { position: absolute; inset: 0; display: grid; place-items: center; }
.rc-gauge-center strong { font-family: var(--font-mono); font-size: 26px; color: var(--text-primary); }
.rc-bars { display: grid; gap: 7px; min-width: 0; }
.rc-bar-row { display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.rc-bar-label { font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
.rc-bar-track { height: 5px; border-radius: 999px; background: var(--border-subtle); overflow: hidden; display: block; }
.rc-bar-track i { display: block; height: 100%; border-radius: 999px; background: var(--color-primary); }
.rc-bar-num { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); white-space: nowrap; }

.rc-stats { display: flex; justify-content: space-between; gap: 6px; margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--border-subtle); }
.rc-stat { display: grid; gap: 1px; justify-items: center; min-width: 0; }
.rc-stat strong { font-family: var(--font-mono); font-size: 15px; color: var(--text-primary); }
.rc-stat span { font-size: 9.5px; color: var(--text-muted); white-space: nowrap; }
.rc-stat--bad strong { color: var(--risk-critical, #ff6b6b); }

.rc-badge {
  min-width: 20px;
  height: 20px;
  border-radius: 999px;
  background: var(--risk-critical, #ff6b6b);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: inline-grid;
  place-items: center;
  padding: 0 6px;
}
.rc-empty { margin: 0; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.rc-warn-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.rc-warn-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
  cursor: pointer;
  color: var(--text-primary);
  text-align: left;
}
.rc-warn-item:hover { border-color: color-mix(in srgb, var(--color-primary) 45%, transparent); }
.rc-warn-name { display: grid; gap: 1px; min-width: 0; }
.rc-warn-name strong { font-size: 13px; }
.rc-warn-name small { font-size: 10.5px; color: var(--text-muted); }
.rc-band { font-size: 10.5px; padding: 2px 9px; border-radius: 999px; border: 1px solid var(--border-subtle); flex: none; }
.rc-band--light { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent); }
.rc-band--moderate { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 50%, transparent); }

.rc-kpi-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.rc-kpi-list li { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto 64px; align-items: center; gap: 8px; }
.rc-kpi-dot { width: 8px; height: 8px; border-radius: 999px; }
.rc-kpi-label { font-size: 12.5px; color: var(--text-primary); }
.rc-kpi-unit { font-size: 10px; color: var(--text-muted); }
.rc-kpi-value { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); justify-self: end; }
.rc-kpi-trend { font-family: var(--font-mono); font-size: 11px; justify-self: end; white-space: nowrap; }
.rc-trend--up { color: var(--risk-critical, #ff6b6b); }
.rc-trend--down { color: var(--risk-low, #5fd6a4); }
.rc-trend--flat { color: var(--text-muted); }
.rc-kpi-note { margin: 8px 0 0; font-size: 10px; color: var(--text-muted); line-height: 1.6; }

/* 点位图例（chla 筛查口径） */
.rc-legend {
  position: absolute;
  z-index: 900;
  left: 14px;
  top: 96px;
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--panel-strong, var(--surface-panel));
  font-size: 11px;
  color: var(--text-secondary);
}
.rc-legend em { font-style: normal; color: var(--text-muted); font-size: 10px; }
.rc-lg-dot { width: 9px; height: 9px; border-radius: 999px; display: inline-block; margin-right: 4px; vertical-align: -1px; }

/* 底部真实快照回放时间轴 */
.rc-timeline {
  position: absolute;
  z-index: 900;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: min(680px, 46%);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--panel-strong, var(--surface-panel));
}
.rc-tl-play {
  appearance: none;
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}
.rc-tl-track {
  display: flex;
  flex: 1;
  min-width: 0;
  overflow-x: auto;
  gap: 2px;
}
.rc-tl-tick {
  appearance: none;
  position: relative;
  flex: 1;
  min-width: 74px;
  border: none;
  background: transparent;
  padding: 14px 2px 4px;
  cursor: pointer;
  color: var(--text-muted);
}
.rc-tl-line {
  position: absolute;
  top: 7px;
  left: 0;
  right: 0;
  height: 3px;
  border-radius: 2px;
  background: var(--border-subtle);
}
.rc-tl-tick::after {
  content: '';
  position: absolute;
  top: 4px;
  left: 50%;
  transform: translateX(-50%);
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--border-subtle);
}
.rc-tl-tick.latest::after { background: var(--risk-low, #5fd6a4); }
.rc-tl-tick.has-warn::after { background: var(--risk-critical, #ff6b6b); }
.rc-tl-tick.active::after {
  background: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 30%, transparent);
}
.rc-tl-tick.active { color: var(--text-primary); }
.rc-tl-tick.active .rc-tl-line { background: color-mix(in srgb, var(--color-primary) 60%, transparent); }
.rc-tl-label { font-family: var(--font-mono); font-size: 9.5px; white-space: nowrap; }
.rc-tl-state {
  flex: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--risk-low, #5fd6a4);
  white-space: nowrap;
}
.rc-tl-state--replay { color: var(--risk-medium, #f5b45d); }

@media (max-width: 1100px) {
  .page-rc { height: auto; min-height: 0; display: flex; flex-direction: column; gap: 10px; padding: 10px; }
  .rc-map { position: relative; inset: auto; height: 340px; flex: none; }
  .rc-chip--top { position: relative; top: auto; left: auto; transform: none; white-space: normal; order: -1; }
  .rc-chip--updated { position: relative; top: auto; right: auto; order: -2; align-self: flex-end; }
  .rc-legend { position: static; order: -1; align-self: flex-start; }
  .rc-cards { position: relative; inset: auto; width: 100%; overflow: visible; }
  .rc-timeline { position: relative; bottom: auto; left: auto; transform: none; width: 100%; }
  }
</style>

<style>
/* ===== 驾驶舱悬停指标卡（Leaflet tooltip 宿主，需全局作用域） ===== */
.leaflet-tooltip.rc-tip-host {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 0;
}
.leaflet-tooltip.rc-tip-host::before { display: none; }
.rc-hover-card {
  width: 248px;
  background: var(--panel-strong, #fff);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 10px 12px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.2);
  color: var(--text-primary);
}
.rhc-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
.rhc-head strong { font-size: 14px; }
.rhc-level {
  font-size: 10.5px;
  color: var(--risk-low, #5fd6a4);
  border: 1px solid color-mix(in srgb, var(--risk-low, #5fd6a4) 45%, transparent);
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.rhc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 14px; }
.rhc-item { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.rhc-k { color: var(--text-muted); font-size: 11px; }
.rhc-v { white-space: nowrap; }
.rhc-v b { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; }
.rhc-v small { color: var(--text-muted); font-size: 9.5px; }
.rhc-foot { margin-top: 7px; padding-top: 6px; border-top: 1px solid var(--border-subtle); color: var(--text-muted); font-size: 10.5px; }
</style>
