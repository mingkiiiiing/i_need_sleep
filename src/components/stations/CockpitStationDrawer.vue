<template>
  <transition name="rcd-slide">
    <aside v-if="stationId" class="rcd" aria-label="站点详情">
      <div class="rcd-head">
        <div>
          <h2>{{ station?.name || '…' }}</h2>
          <p class="rcd-sub">{{ station?.basin || '太湖流域' }} · {{ station?.province || '—' }} · {{ coordText }}</p>
        </div>
        <button type="button" class="rcd-close" aria-label="关闭详情" @click="$emit('close')">×</button>
      </div>

      <div class="rcd-badges">
        <span v-if="station?.water_level" class="rcd-badge" :class="levelBadgeClass">水质 {{ station.water_level }} 类</span>
        <span v-else class="rcd-badge">水质 —</span>
        <span class="rcd-badge" :class="algaeBadge.class">{{ algaeBadge.text }}</span>
      </div>

      <div class="rcd-sec-head">
        <h3>实时监测</h3>
        <span>{{ observedAtText }}</span>
      </div>

      <div v-if="obsState === 'loading'" class="rcd-loading">正在读取该站观测…</div>
      <div v-else-if="obsState === 'error'" class="rcd-loading rcd-loading--bad" role="alert">
        观测读取失败
        <button type="button" class="rcd-btn" @click="loadObs">重试</button>
      </div>
      <ul v-else class="rcd-list">
        <li v-for="row in metricRows" :key="row.code">
          <span class="rcd-k">{{ row.label }}</span>
          <span class="rcd-v">
            <b>{{ row.text }}</b>
            <small>{{ row.unit }}</small>
          </span>
          <span class="rcd-flag" :class="`rcd-flag--${row.tone}`">{{ row.flag }}</span>
        </li>
      </ul>

      <div class="rcd-sec-head">
        <h3>快照历史（实测累计）</h3>
        <span>{{ historyPoints.length }} 个快照</span>
      </div>
      <div v-if="historyPoints.length >= 2" class="rcd-mini">
        <svg viewBox="0 0 300 74" preserveAspectRatio="none" role="img" aria-label="叶绿素 a 快照历史折线">
          <polyline class="rcd-mini-line" :points="miniPolyline" />
          <circle v-for="(p, i) in historyPoints" :key="i" class="rcd-mini-dot" :cx="p.x" :cy="p.y" r="2.6" />
        </svg>
        <div class="rcd-mini-axis">
          <span>{{ miniRange[0] }}</span>
          <span>叶绿素 a μg/L</span>
          <span>{{ miniRange[1] }}</span>
        </div>
      </div>
      <p v-else class="rcd-note">该站叶绿素 a 可用观测不足两个快照点，暂无可绘制趋势；不做插值补点。</p>

      <button type="button" class="rcd-open" @click="$emit('open-analysis', stationId)">
        在分析面板中打开 →
      </button>
    </aside>
  </transition>
</template>

<script setup>
// 站点详情抽屉（点击地图点位弹出）：11 项指标逐行如实展示，
// 徽标口径：正常=QC 通过 / 超限=范围 QC 未过 / 缺测=上游缺测；不引入任何预测数值。
import { computed, ref, watch } from 'vue'
import {
  fetchStationObservations,
  fmtMeasure,
  formatStamp,
  OBS_HISTORY_START,
  OBS_STATUS_TEXT,
  REALTIME_VARIABLES,
  todayLocalDate
} from '../../services/realtime.js'

const props = defineProps({
  stationId: { type: String, default: '' },
  // 来自 summary.markers 的该站静态信息（名称/坐标/类别/chla/metrics）
  station: { type: Object, default: null }
})

const emit = defineEmits(['close', 'open-analysis'])

const obsRows = ref([])
const obsState = ref('loading')

const coordText = computed(() => {
  if (!props.station) return '—'
  return `${Number(props.station.lat).toFixed(3)}°N, ${Number(props.station.lon).toFixed(3)}°E`
})

const observedAtText = computed(() => {
  const times = obsRows.value.map((r) => r.observed_at).filter(Boolean).sort()
  return times.length ? formatStamp(times[times.length - 1]) : '—'
})

const metricRows = computed(() =>
  REALTIME_VARIABLES.map(({ code, label, unit }) => {
    const row = obsRows.value.find((r) => r.variable_code === code)
    const status = row ? row.observation_status : 'missing'
    return {
      code,
      label,
      unit,
      text: row && row.value != null && status !== 'missing' ? fmtMeasure(row.value) : '--',
      // 与站点页「最新观测」同一措辞：qc_rejected = 质控不合格（非"超限"）
      flag: status === 'ok' ? '正常' : status === 'qc_rejected' ? '质控不合格' : OBS_STATUS_TEXT[status] || '无数据',
      tone: status === 'ok' ? 'ok' : status === 'qc_rejected' ? 'bad' : 'na'
    }
  })
)

const algaeBadge = computed(() => {
  const v = props.station?.chla
  if (v == null) return { text: '蓝藻 无数据', class: '' }
  if (v >= 25) return { text: '蓝藻 中度预警', class: 'rcd-badge--bad' }
  if (v >= 10) return { text: '蓝藻 轻度关注', class: 'rcd-badge--warn' }
  return { text: '蓝藻 正常', class: 'rcd-badge--ok' }
})

// 上游发布水质类别分档着色：≤III 正常 / IV 关注 / V 及以上预警
const levelBadgeClass = computed(() => {
  const n = parseInt(props.station?.water_level, 10)
  if (!Number.isFinite(n)) return 'rcd-badge--na'
  if (n <= 3) return 'rcd-badge--ok'
  if (n === 4) return 'rcd-badge--warn'
  return 'rcd-badge--bad'
})

async function loadObs() {
  if (!props.stationId) return
  obsState.value = 'loading'
  obsRows.value = []
  try {
    obsRows.value = await fetchStationObservations(props.stationId, { window: 'latest' })
    obsState.value = 'ok'
  } catch {
    obsState.value = 'error'
  }
}

// 快照历史（该站 chla 实测序列）
const history = ref([])
watch(
  () => props.stationId,
  async (id) => {
    loadObs()
    history.value = []
    if (!id) return
    try {
      history.value = await fetchStationObservations(id, {
        window: 'range',
        start: OBS_HISTORY_START,
        end: todayLocalDate()
      })
    } catch {
      history.value = []
    }
  },
  { immediate: true }
)

const historyPoints = computed(() => {
  const series = history.value
    .filter((r) => r.variable_code === 'chlorophyll_a' && r.observation_status === 'ok' && r.value != null)
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
  const W = 300
  const H = 74
  const values = series.map((r) => Number(r.value))
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 1)
  return series.map((r, i) => ({
    t: r.observed_at,
    x: series.length === 1 ? W / 2 : (i / (series.length - 1)) * (W - 12) + 6,
    y: H - 8 - ((Number(r.value) - min) / (max - min || 1)) * (H - 16)
  }))
})

const miniPolyline = computed(() => historyPoints.value.map((p) => `${p.x},${p.y}`).join(' '))
const miniRange = computed(() => [
  formatStamp(historyPoints.value[0]?.t).slice(5) || '—',
  formatStamp(historyPoints.value[historyPoints.value.length - 1]?.t).slice(5) || '—'
])
</script>

<style scoped>
.rcd {
  position: absolute;
  z-index: 950;
  top: 12px;
  right: 12px;
  bottom: 12px;
  width: 386px;
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  background: var(--panel-strong, var(--surface-panel));
  padding: 14px 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rcd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.rcd-head h2 { margin: 0; font-size: 20px; color: var(--text-primary); }
.rcd-sub { margin: 3px 0 0; font-size: 11.5px; color: var(--text-muted); }
.rcd-close {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  width: 30px;
  height: 30px;
  border-radius: 999px;
  font-size: 15px;
  cursor: pointer;
  flex: none;
}
.rcd-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.rcd-badge {
  font-size: 11.5px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.rcd-badge--na { color: var(--text-muted); }
.rcd-badge--ok { color: var(--risk-low, #22c55e); border-color: color-mix(in srgb, var(--risk-low, #22c55e) 45%, transparent); }
.rcd-badge--warn { color: var(--risk-medium, #facc15); border-color: color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent); }
.rcd-badge--bad { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent); }
.rcd-sec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
}
.rcd-sec-head h3 { margin: 0; font-size: 13px; color: var(--text-primary); }
.rcd-sec-head span { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); }
.rcd-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.rcd-list li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border-subtle);
}
.rcd-k { font-size: 12.5px; color: var(--text-secondary); }
.rcd-v { display: flex; align-items: baseline; gap: 4px; justify-self: end; }
.rcd-v b { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); }
.rcd-v small { font-size: 10px; color: var(--text-muted); }
.rcd-flag { font-size: 10.5px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-subtle); white-space: nowrap; }
.rcd-flag--ok { color: var(--risk-low, #22c55e); border-color: color-mix(in srgb, var(--risk-low, #22c55e) 45%, transparent); }
.rcd-flag--bad { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent); }
.rcd-flag--na { color: var(--text-muted); }
.rcd-mini svg { width: 100%; height: 74px; display: block; }
.rcd-mini-line { fill: none; stroke: var(--color-primary); stroke-width: 2; }
.rcd-mini-dot { fill: var(--color-primary); }
.rcd-mini-axis { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 9.5px; color: var(--text-muted); }
.rcd-note { margin: 0; font-size: 11px; color: var(--text-muted); line-height: 1.6; }
.rcd-loading { font-size: 12px; color: var(--text-secondary); padding: 8px 0; }
.rcd-loading--bad { color: var(--risk-critical, #ef4444); display: flex; gap: 10px; align-items: center; }
.rcd-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 30px;
  padding: 2px 12px;
  cursor: pointer;
}
.rcd-open {
  appearance: none;
  margin-top: auto;
  min-height: 44px;
  border: none;
  border-radius: 12px;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}
.rcd-open:hover { filter: brightness(1.08); }
.rcd-slide-enter-active, .rcd-slide-leave-active { transition: transform 0.22s ease, opacity 0.22s ease; }
.rcd-slide-enter-from, .rcd-slide-leave-to { transform: translateX(24px); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .rcd-slide-enter-active, .rcd-slide-leave-active { transition: none; }
}
@media (max-width: 1100px) {
  .rcd { position: relative; inset: auto; width: 100%; }
}
</style>
