<template>
  <section class="stn-block stp" aria-label="历史趋势（真实累计数据）">
    <div class="stn-sec-head">
      <h2>历史趋势</h2>
      <div class="stp-vars" role="group" aria-label="趋势指标切换">
        <button
          v-for="opt in TREND_VARIABLES"
          :key="opt.code"
          type="button"
          class="stn-chip"
          :class="{ active: variable === opt.code }"
          :aria-pressed="String(variable === opt.code)"
          @click="variable = opt.code"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">趋势数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </div>

    <template v-else>
      <div v-if="points.length >= 2" class="stp-chart">
        <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${variableLabel(variable)} 历史趋势图`">
          <line v-for="g in 3" :key="g" class="stp-grid" x1="0" :y1="(H / 3) * g" :x2="W" :y2="(H / 3) * g" />
          <polyline class="stp-line" :points="polylinePoints" />
          <circle v-for="(p, i) in points" :key="i" class="stp-dot" :cx="p.x" :cy="p.y" r="3" />
        </svg>
        <div class="stp-axis">
          <span>{{ formatStamp(points[0].t) }}</span>
          <span>仅真实累计观测 · {{ points.length }} 个快照</span>
          <span>{{ formatStamp(points[points.length - 1].t) }}</span>
        </div>
      </div>
      <p v-else class="stn-trend-note stn-trend-note--sparse">
        暂无可计算趋势：真实观测不足两个时间点（当前累计 {{ points.length }} 个快照）。系统随抓取持续积累，不做模拟补点。
      </p>
      <p v-if="skipped.length" class="stn-trend-note">缺测/质控不合格快照 {{ skipped.length }} 次未参与连线，不做插值。</p>
    </template>
  </section>
</template>

<script setup>
// 历史趋势：只画真实累计观测（observed 轨 range 查询）；
// 少于两个时间点显示“暂无可计算趋势”；缺测/质控不合格点断开不插值。
import { computed, ref, watch } from 'vue'
import { fetchStationObservations, formatStamp, variableLabel } from '../../services/realtime.js'

const props = defineProps({
  stationId: { type: String, default: '' }
})
defineEmits(['retry'])

const TREND_VARIABLES = [
  { code: 'chlorophyll_a', label: '叶绿素 a' },
  { code: 'total_phosphorus', label: '总磷' },
  { code: 'total_nitrogen', label: '总氮' },
  { code: 'dissolved_oxygen', label: '溶解氧' },
  { code: 'water_temperature', label: '水温' }
]

const W = 600
const H = 150
const variable = ref('chlorophyll_a')
const state = ref('loading')
const allRows = ref([])

async function load() {
  if (!props.stationId) return
  state.value = 'loading'
  allRows.value = []
  try {
    // 全量快照回看：起始日取首个快照（2026-09-04 起），range 由后端过滤
    allRows.value = await fetchStationObservations(props.stationId, {
      window: 'range',
      start: '2026-09-01',
      end: new Date().toISOString().slice(0, 10)
    })
    // 默认选第一个有可用观测的指标（上游 chla/藻密度缺测普遍，固定默认会频繁空图）
    const hasOk = new Set(
      allRows.value.filter((r) => r.observation_status === 'ok' && r.value != null).map((r) => r.variable_code)
    )
    if (!hasOk.has(variable.value)) {
      const firstOk = TREND_VARIABLES.find((v) => hasOk.has(v.code))
      if (firstOk) variable.value = firstOk.code
    }
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

watch(() => props.stationId, load, { immediate: true })

// 同一快照取该指标最新一行；缺测/质控不合格不参与连线
const series = computed(() => {
  const bySnapshot = new Map()
  allRows.value
    .filter((row) => row.variable_code === variable.value)
    .forEach((row) => {
      const prev = bySnapshot.get(row.snapshot_id)
      if (!prev || String(row.observed_at) > String(prev.observed_at)) bySnapshot.set(row.snapshot_id, row)
    })
  return Array.from(bySnapshot.values())
    .filter((row) => row.observation_status === 'ok' && row.value != null)
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
})

const skipped = computed(() => {
  const total = new Set(allRows.value.filter((r) => r.variable_code === variable.value).map((r) => r.snapshot_id)).size
  return Array.from({ length: Math.max(0, total - series.value.length) })
})

const points = computed(() => {
  if (series.value.length < 1) return []
  const values = series.value.map((r) => Number(r.value))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pad = 12
  return series.value.map((row, i) => ({
    t: row.observed_at,
    x: series.value.length === 1 ? W / 2 : pad + (i / (series.value.length - 1)) * (W - pad * 2),
    y: H - pad - ((Number(row.value) - min) / span) * (H - pad * 2)
  }))
})

const polylinePoints = computed(() => points.value.map((p) => `${p.x},${p.y}`).join(' '))
</script>

<style scoped>
.stp { display: flex; flex-direction: column; }
.stp-vars { display: flex; flex-wrap: wrap; gap: 4px; }
.stp-chart { display: grid; gap: 4px; }
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
</style>
