<template>
  <section class="stn-block stp" aria-label="站点时序分析（真实累计数据）">
    <div class="stn-sec-head">
      <h2>站点时序分析</h2>
      <div class="stp-controls">
        <div class="stp-range" role="group" aria-label="时间范围">
          <button
            v-for="r in RANGES"
            :key="r.key"
            type="button"
            class="stn-chip stn-chip--sm"
            :class="{ active: range === r.key }"
            :aria-pressed="String(range === r.key)"
            @click="range = r.key"
          >
            {{ r.label }}
          </button>
        </div>
        <button
          type="button"
          class="stn-chip stn-chip--sm"
          :class="{ active: compareMode }"
          :aria-pressed="String(compareMode)"
          data-role="trend-compare-toggle"
          @click="toggleCompare"
        >
          指标对比
        </button>
      </div>
    </div>

    <!-- 指标切换：单选（单指标模式）/ 多选最多 3 项（对比模式） -->
    <div class="stp-vars" role="group" :aria-label="compareMode ? '对比指标选择（最多 3 项）' : '趋势指标切换'">
      <button
        v-for="opt in TREND_VARIABLES"
        :key="opt.code"
        type="button"
        class="stn-chip stn-chip--sm"
        :class="{ active: isActive(opt.code) }"
        :aria-pressed="String(isActive(opt.code))"
        :data-role="`trend-var-${opt.code}`"
        @click="pickVariable(opt.code)"
      >
        {{ opt.label }}
      </button>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">趋势数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="load">重试</button>
    </div>

    <template v-else>
      <!-- 单指标模式 -->
      <template v-if="!compareMode">
        <p class="stp-title" data-role="trend-title">{{ titleText }}</p>
        <div v-if="points.length >= 2" class="stp-chart">
          <div class="stp-bounds">
            <span>{{ maxText }}</span>
            <span>{{ minText }}</span>
          </div>
          <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${variableLabel(variable)} 历史趋势图`">
            <line v-for="g in 3" :key="g" class="stp-grid" x1="0" :y1="(H / 3) * g" :x2="W" :y2="(H / 3) * g" />
            <polyline class="stp-line" :points="polylinePoints" />
            <circle v-for="(p, i) in points" :key="i" class="stp-dot" :cx="p.x" :cy="p.y" r="3" />
          </svg>
          <div class="stp-axis">
            <span>{{ formatStamp(points[0].t) }}</span>
            <span>仅真实累计观测 · {{ points.length }} 个快照 · {{ rangeLabel }}</span>
            <span>{{ formatStamp(points[points.length - 1].t) }}</span>
          </div>
        </div>
        <p v-else class="stn-trend-note stn-trend-note--sparse" data-role="trend-empty">
          真实观测尚在积累：{{ variableLabel(variable) }} 在该时间范围内不足两个有效时间点（当前 {{ points.length }} 个）。系统随抓取持续积累，不做模拟补点。
        </p>
      </template>

      <!-- 对比模式：小多图纵向排列，各图独立纵轴，不共用刻度 -->
      <template v-else>
        <p class="stp-title" data-role="trend-title">{{ compareTitleText }}</p>
        <p v-if="!compareVars.length" class="stn-trend-note">在上方选择 1—3 项指标进行对比。</p>
        <div v-else class="stp-multi">
          <div v-for="cv in compareCharts" :key="cv.code" class="stp-multi-item">
            <div class="stp-multi-head">
              <span class="stp-multi-name">{{ cv.label }}</span>
              <span class="stp-multi-latest">{{ cv.latestText }}</span>
            </div>
            <svg v-if="cv.points.length >= 2" :viewBox="`0 0 ${W} ${MULTI_H}`" preserveAspectRatio="none" role="img" :aria-label="`${cv.label} 趋势小图`">
              <line v-for="g in 2" :key="g" class="stp-grid" x1="0" :y1="(MULTI_H / 2) * g" :x2="W" :y2="(MULTI_H / 2) * g" />
              <polyline class="stp-line" :points="cv.polyline" />
            </svg>
            <p v-else class="stn-trend-note">该时间范围内有效点不足，不绘制。</p>
          </div>
        </div>
        <p class="stn-trend-note">对比模式为上下小多图，各指标独立纵轴；不同量纲指标不共用一条纵轴，不做标准化伪装。</p>
      </template>

      <p v-if="skipped.length" class="stn-trend-note">缺测/质控不合格快照 {{ skipped.length }} 次未参与连线，不做插值。</p>
    </template>
  </section>
</template>

<script setup>
// 站点时序分析区：只画真实累计观测（observed 轨 range 查询）。
// 单指标模式保证数值与单位清晰；对比模式最多 3 项、小多图独立纵轴；
// 时间范围 24 小时 / 7 天 / 30 天 / 全部；缺测断点不插值；少于两个时间点显式说明。
import { computed, ref, watch } from 'vue'
import { fetchStationObservations, fmtMeasure, formatStamp, OBS_HISTORY_START, todayLocalDate, variableLabel } from '../../services/realtime.js'

const props = defineProps({
  stationId: { type: String, default: '' },
  stationName: { type: String, default: '' }
})

const TREND_VARIABLES = [
  { code: 'chlorophyll_a', label: '叶绿素 a' },
  { code: 'total_phosphorus', label: '总磷' },
  { code: 'total_nitrogen', label: '总氮' },
  { code: 'dissolved_oxygen', label: '溶解氧' },
  { code: 'water_temperature', label: '水温' }
]

const RANGES = [
  { key: '24h', label: '24小时', hours: 24 },
  { key: '7d', label: '7天', hours: 24 * 7 },
  { key: '30d', label: '30天', hours: 24 * 30 },
  { key: 'all', label: '全部', hours: null }
]

const W = 600
const H = 150
const MULTI_H = 56

const variable = ref('chlorophyll_a')
const compareMode = ref(false)
const compareVars = ref([])
const range = ref('all')
const state = ref('loading')
const allRows = ref([])

const rangeLabel = computed(() => RANGES.find((r) => r.key === range.value)?.label || '')

function seriesOf(code) {
  // 每个快照取该指标最新一行（任意状态），保留缺测/质控行供 skipped 统计
  const bySnapshot = new Map()
  allRows.value
    .filter((row) => row.variable_code === code)
    .forEach((row) => {
      const prev = bySnapshot.get(row.snapshot_id)
      if (!prev || String(row.observed_at) > String(prev.observed_at)) bySnapshot.set(row.snapshot_id, row)
    })
  return Array.from(bySnapshot.values())
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
}

// 时间范围过滤：以该指标最新快照为基准截取（范围只影响横轴窗口）
function inRange(series) {
  if (!series.length) return series
  const r = RANGES.find((item) => item.key === range.value)
  if (!r || r.hours == null) return series
  const latest = Date.parse(series[series.length - 1].observed_at)
  if (!Number.isFinite(latest)) return series
  const cut = latest - r.hours * 3_600_000
  return series.filter((row) => Date.parse(row.observed_at) >= cut)
}

const rangeRows = computed(() => inRange(seriesOf(variable.value)))
const series = computed(() => rangeRows.value.filter((row) => row.observation_status === 'ok' && row.value != null))
// 仅统计所选时间范围内未参与连线的快照数（缺测/质控不合格），范围外的不计
const skippedTotal = computed(() => rangeRows.value.length - series.value.length)
const skipped = computed(() => Array.from({ length: Math.max(0, skippedTotal.value) }))

const points = computed(() => {
  if (series.value.length < 1) return []
  const values = series.value.map((r) => Number(r.value))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pad = 12
  return series.value.map((row, i) => ({
    t: row.observed_at,
    value: Number(row.value),
    x: series.value.length === 1 ? W / 2 : pad + (i / (series.value.length - 1)) * (W - pad * 2),
    y: H - pad - ((Number(row.value) - min) / span) * (H - pad * 2)
  }))
})

const minText = computed(() => {
  if (points.value.length < 2) return ''
  return `min ${fmtMeasure(Math.min(...points.value.map((p) => p.value)))}`
})
const maxText = computed(() => {
  if (points.value.length < 2) return ''
  return `max ${fmtMeasure(Math.max(...points.value.map((p) => p.value)))}`
})

const polylinePoints = computed(() => points.value.map((p) => `${p.x},${p.y}`).join(' '))

// 对比模式小图
const compareCharts = computed(() =>
  compareVars.value.map((code) => {
    const pts = inRange(seriesOf(code))
      .filter((r) => r.observation_status === 'ok' && r.value != null)
      .map((r) => ({ t: r.observed_at, value: Number(r.value) }))
    const values = pts.map((p) => p.value)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    const pad = 6
    const xy = pts.map((p, i) => ({
      x: pts.length === 1 ? W / 2 : pad + (i / (pts.length - 1)) * (W - pad * 2),
      y: MULTI_H - pad - ((p.value - min) / span) * (MULTI_H - pad * 2)
    }))
    const latest = pts.length ? pts[pts.length - 1] : null
    const unitRow = allRows.value.find((r) => r.variable_code === code && r.unit)
    return {
      code,
      label: variableLabel(code),
      points: xy,
      polyline: xy.map((p) => `${p.x},${p.y}`).join(' '),
      latestText: latest ? `${latest.value}${unitRow && unitRow.unit ? ` ${unitRow.unit}` : ''}` : '—'
    }
  })
)

const titleText = computed(() => {
  const name = props.stationName || '站点'
  return `${name} · ${variableLabel(variable.value)}历史趋势`
})
const compareTitleText = computed(() => {
  const name = props.stationName || '站点'
  const labels = compareVars.value.map((c) => variableLabel(c)).join(' / ')
  return labels ? `${name} · ${labels} 对比` : `${name} · 指标对比`
})

function isActive(code) {
  return compareMode.value ? compareVars.value.includes(code) : variable.value === code
}

function pickVariable(code) {
  if (!compareMode.value) {
    variable.value = code
    return
  }
  const at = compareVars.value.indexOf(code)
  if (at >= 0) compareVars.value.splice(at, 1)
  else if (compareVars.value.length < 3) compareVars.value.push(code)
}

function toggleCompare() {
  compareMode.value = !compareMode.value
  if (compareMode.value && !compareVars.value.length) {
    compareVars.value = [variable.value]
  }
  if (!compareMode.value) {
    variable.value = compareVars.value[0] || variable.value
    compareVars.value = []
  }
}

async function load() {
  if (!props.stationId) return
  state.value = 'loading'
  allRows.value = []
  try {
    // 全量快照回看：起始日取历史窗口起点，end 用本地当天（toISOString 是 UTC，凌晨会差一天）
    allRows.value = await fetchStationObservations(props.stationId, {
      window: 'range',
      start: OBS_HISTORY_START,
      end: todayLocalDate()
    })
    // 默认选第一个有可用观测的指标（上游 chla/藻密度缺测普遍，固定默认会频繁空图）
    const hasOk = new Set(
      allRows.value.filter((r) => r.observation_status === 'ok' && r.value != null).map((r) => r.variable_code)
    )
    if (!compareMode.value && !hasOk.has(variable.value)) {
      const firstOk = TREND_VARIABLES.find((v) => hasOk.has(v.code))
      if (firstOk) variable.value = firstOk.code
    }
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

watch(() => props.stationId, load, { immediate: true })
</script>

<style scoped>
.stp { display: flex; flex-direction: column; gap: 5px; }
.stp-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.stp-range { display: inline-flex; gap: 4px; }
.stp-vars { display: flex; flex-wrap: wrap; gap: 4px; }
.stp-title {
  margin: 2px 0 0;
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text-primary);
}
.stp-chart { display: grid; gap: 4px; position: relative; }
.stp-bounds {
  position: absolute;
  top: 2px;
  right: 4px;
  display: grid;
  justify-items: end;
  gap: 58px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-muted);
  pointer-events: none;
  z-index: 1;
}
.stp-chart svg { width: 100%; height: 150px; display: block; }
.stp-grid { stroke: var(--border-subtle); stroke-width: 1; }
.stp-line { fill: none; stroke: var(--color-primary); stroke-width: 2; }
.stp-dot { fill: var(--color-primary); }
.stp-axis {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

.stp-multi { display: grid; gap: 8px; }
.stp-multi-item {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 6px 8px;
  display: grid;
  gap: 3px;
}
.stp-multi-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.stp-multi-name { font-size: 11.5px; font-weight: 650; color: var(--text-secondary); }
.stp-multi-latest { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); }
.stp-multi-item svg { width: 100%; height: 56px; display: block; }
</style>
