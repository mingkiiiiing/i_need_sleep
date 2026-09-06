<template>
  <transition name="cap-rise">
    <section v-if="open" class="cap" aria-label="站点观测分析面板">
      <div class="cap-head">
        <div class="cap-tl">
          <button type="button" class="cap-play" :aria-label="playing ? '暂停回放' : '播放快照回放'" @click="togglePlay">
            {{ playing ? '❚❚' : '▶' }}
          </button>
          <div class="cap-track">
            <button
              v-for="(snap, i) in timelineSnaps"
              :key="snap.snapshot_id"
              type="button"
              class="cap-tick"
              :class="{ active: i === cursor }"
              :aria-selected="String(i === cursor)"
              :title="`${tickLabel(snap)} · 达标 ${snap.class_compliance.num}/${snap.class_compliance.den} · 预警 ${snap.warning_count}`"
              @click="cursor = i"
            >
              <span class="cap-tick-line"></span>
              <span class="cap-tick-label">{{ tickLabel(snap) }}</span>
            </button>
          </div>
          <span class="cap-state" :class="{ 'cap-state--replay': !isLatest }">
            {{ isLatest ? '● 最新' : '⟲ 历史回放' }}
          </span>
          <button type="button" class="cap-close" aria-label="收起分析面板" @click="$emit('close')">×</button>
        </div>

        <div class="cap-vars">
          <button
            v-for="v in VARIABLES"
            :key="v.code"
            type="button"
            class="cap-chip"
            :class="{ active: variable === v.code }"
            :aria-pressed="String(variable === v.code)"
            @click="variable = v.code"
          >
            {{ v.label }}
          </button>
          <select v-model="stationId" class="cap-select" aria-label="选择站点">
            <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.source_station_name }}</option>
          </select>
        </div>
      </div>

      <div class="cap-body">
        <div class="cap-chart">
          <div class="cap-chart-head">
            <span class="cap-unit">{{ activeVar.label }}（{{ activeVar.unit }}）</span>
            <span class="cap-series-tag"><i></i>实测（官方观测，未经跨源验证）</span>
          </div>
          <div v-if="chartState === 'loading'" class="cap-note">正在读取该站历史观测…</div>
          <div v-else-if="chartState === 'error'" class="cap-note cap-note--bad" role="alert">
            观测读取失败
            <button type="button" class="cap-btn" @click="loadSeries">重试</button>
          </div>
          <template v-else-if="chartPoints.length >= 2">
            <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${activeVar.label} 实测序列`">
              <line v-for="g in 4" :key="g" class="cap-grid" x1="0" :y1="(H / 4) * g" :x2="W" :y2="(H / 4) * g" />
              <polyline class="cap-line" :points="polyline" />
              <circle v-for="(p, i) in chartPoints" :key="i" class="cap-dot" :cx="p.x" :cy="p.y" r="3.4" />
            </svg>
            <div class="cap-axis">
              <span>{{ chartPoints[0].label }}</span>
              <span>仅实测累计 · {{ chartPoints.length }} 个快照 · 缺测不插值</span>
              <span>{{ chartPoints[chartPoints.length - 1].label }}</span>
            </div>
          </template>
          <p v-else class="cap-note cap-note--warn">
            尚未积累：该站{{ activeVar.label }}可用观测不足两个快照点（当前 {{ chartPoints.length }}），随抓取自动积累。
          </p>
        </div>
      </div>
    </section>
  </transition>
</template>

<script setup>
// 分析面板（图七交互的真实数据版）：时间轴行 + 变量切换 + 站点下拉 + 实测序列大图。
// 只有实测线，无预测虚线——系统当前没有单站预测模型，不伪造预测区间。
import { computed, ref, watch } from 'vue'
import { fetchRealtimeTimeline, fetchRealtimeStations, fetchStationObservations, formatStamp } from '../../services/realtime.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  initialStationId: { type: String, default: '' }
})
const emit = defineEmits(['close'])

const VARIABLES = [
  { code: 'chlorophyll_a', label: '叶绿素a', unit: 'μg/L' },
  { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L' },
  { code: 'total_phosphorus', label: '总磷', unit: 'mg/L' },
  { code: 'total_nitrogen', label: '总氮', unit: 'mg/L' },
  { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L' },
  { code: 'cod_mn', label: 'CODMn', unit: 'mg/L' },
  { code: 'water_temperature', label: '水温', unit: '℃' }
]

const W = 1000
const H = 260

const timelineSnaps = ref([])
const stations = ref([])
const stationId = ref('')
const variable = ref('chlorophyll_a')
const cursor = ref(0)
const playing = ref(false)
let playTimer = null

const rows = ref([])
const chartState = ref('loading')

const isLatest = computed(() => cursor.value >= timelineSnaps.value.length - 1)
const activeVar = computed(() => VARIABLES.find((v) => v.code === variable.value) || VARIABLES[0])

function tickLabel(snap) {
  const m = String(snap.latest_observed_at || snap.retrieved_at_utc || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '—'
}

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  playing.value = false
}

function togglePlay() {
  if (playing.value) return stopPlay()
  if (timelineSnaps.value.length < 2) return
  playing.value = true
  playTimer = setInterval(() => {
    if (cursor.value >= timelineSnaps.value.length - 1) return stopPlay()
    cursor.value += 1
  }, 2200)
}

async function loadSeries() {
  if (!stationId.value) return
  chartState.value = 'loading'
  rows.value = []
  try {
    rows.value = await fetchStationObservations(stationId.value, {
      window: 'range',
      start: '2026-09-01',
      end: new Date().toISOString().slice(0, 10)
    })
    chartState.value = 'ok'
  } catch {
    chartState.value = 'error'
  }
}

watch([stationId, variable], loadSeries)
watch(
  () => props.open,
  async (open) => {
    if (!open) return stopPlay()
    if (!timelineSnaps.value.length) {
      try {
        const tl = await fetchRealtimeTimeline()
        timelineSnaps.value = tl.snapshots || []
        cursor.value = timelineSnaps.value.length - 1
      } catch {
        timelineSnaps.value = []
      }
    }
    if (!stations.value.length) {
      try {
        stations.value = await fetchRealtimeStations()
      } catch {
        stations.value = []
      }
    }
    if (!stationId.value && props.initialStationId) stationId.value = props.initialStationId
    if (!stationId.value && stations.value.length) stationId.value = stations.value[0].id
  },
  { immediate: true }
)

const chartPoints = computed(() => {
  const series = rows.value
    .filter((r) => r.variable_code === variable.value && r.observation_status === 'ok' && r.value != null)
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
  const pad = { l: 16, r: 16, t: 14, b: 10 }
  const values = series.map((r) => Number(r.value))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return series.map((r, i) => ({
    label: formatStamp(r.observed_at),
    x: series.length === 1 ? W / 2 : pad.l + (i / (series.length - 1)) * (W - pad.l - pad.r),
    y: H - pad.b - ((Number(r.value) - min) / span) * (H - pad.t - pad.b)
  }))
})

const polyline = computed(() => chartPoints.value.map((p) => `${p.x},${p.y}`).join(' '))
</script>

<style scoped>
.cap {
  position: absolute;
  z-index: 960;
  left: 12px;
  right: 12px;
  bottom: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  background: var(--panel-strong, var(--surface-panel));
  padding: 12px 16px;
  display: grid;
  gap: 10px;
  max-height: 52vh;
  overflow-y: auto;
}
.cap-head { display: grid; gap: 8px; }
.cap-tl { display: flex; align-items: center; gap: 12px; min-width: 0; }
.cap-play {
  appearance: none;
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  cursor: pointer;
}
.cap-track { display: flex; flex: 1; min-width: 0; gap: 2px; overflow-x: auto; }
.cap-tick {
  appearance: none;
  position: relative;
  flex: 1;
  min-width: 78px;
  border: none;
  background: transparent;
  padding: 15px 2px 3px;
  cursor: pointer;
  color: var(--text-muted);
}
.cap-tick-line { position: absolute; top: 8px; left: 0; right: 0; height: 3px; border-radius: 2px; background: var(--border-subtle); }
.cap-tick::after {
  content: '';
  position: absolute;
  top: 5px;
  left: 50%;
  transform: translateX(-50%);
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--border-subtle);
}
.cap-tick.active::after { background: var(--color-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 28%, transparent); }
.cap-tick.active { color: var(--text-primary); }
.cap-tick.active .cap-tick-line { background: color-mix(in srgb, var(--color-primary) 55%, transparent); }
.cap-tick-label { font-family: var(--font-mono); font-size: 9.5px; white-space: nowrap; }
.cap-state { flex: none; font-family: var(--font-mono); font-size: 10.5px; color: var(--risk-low, #5fd6a4); white-space: nowrap; }
.cap-state--replay { color: var(--risk-medium, #f5b45d); }
.cap-close {
  appearance: none;
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 15px;
  cursor: pointer;
}
.cap-vars { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.cap-chip {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 32px;
  padding: 3px 12px;
  border-radius: 999px;
  cursor: pointer;
}
.cap-chip.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}
.cap-select {
  margin-left: auto;
  min-height: 34px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  padding: 2px 10px;
  max-width: 220px;
}
.cap-chart-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.cap-unit { font-size: 12px; color: var(--text-secondary); }
.cap-series-tag { display: inline-flex; align-items: center; gap: 6px; font-size: 10.5px; color: var(--text-muted); }
.cap-series-tag i { width: 14px; height: 3px; border-radius: 2px; background: var(--color-primary); display: inline-block; }
.cap-chart svg { width: 100%; height: 240px; display: block; }
.cap-grid { stroke: var(--border-subtle); stroke-width: 1; }
.cap-line { fill: none; stroke: var(--color-primary); stroke-width: 2.4; }
.cap-dot { fill: var(--color-primary); }
.cap-axis { display: flex; justify-content: space-between; gap: 8px; font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
.cap-note { font-size: 12px; color: var(--text-secondary); padding: 10px 0; }
.cap-note--warn { color: var(--risk-medium, #f5b45d); }
.cap-note--bad { color: var(--risk-critical, #ff6b6b); display: flex; gap: 10px; align-items: center; }
.cap-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 30px;
  padding: 2px 12px;
  cursor: pointer;
}
.cap-rise-enter-active, .cap-rise-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.cap-rise-enter-from, .cap-rise-leave-to { transform: translateY(20px); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .cap-rise-enter-active, .cap-rise-leave-active { transition: none; }
}
@media (max-width: 1100px) {
  .cap { position: relative; inset: auto; max-height: none; }
  .cap-chart svg { height: 180px; }
}
</style>
