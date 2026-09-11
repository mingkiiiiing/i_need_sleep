<template>
  <section class="stn-block sac" aria-label="活动预警">
    <div class="stn-sec-head">
      <h2>活动预警</h2>
      <span v-if="state === 'ok' && !stationAlerts.length" class="stn-sec-tag">无</span>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">预警状态加载失败</p>
      <button type="button" class="stn-inline-btn" @click="load(true)">重试</button>
    </div>

    <ul v-else-if="stationAlerts.length" class="sac-list" data-role="station-alerts">
      <li v-for="a in stationAlerts" :key="a.id" class="sac-item" :class="`sac-item--${a.level}`">
        <span class="sac-level">{{ ALERT_LEVEL_TEXT[a.level] || a.level }}</span>
        <span class="sac-main">
          <b>叶绿素 a {{ a.chla != null ? `${a.chla} μg/L` : '—' }}</b>
          <small>触发 {{ formatAlertTime(a.triggered_at) }}{{ durationText(a) }}</small>
        </span>
      </li>
    </ul>

    <p v-else class="sac-none" data-role="no-alert">
      <svg class="sac-none-ico" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
        <path d="M8 1.6 13.4 3.6v4c0 3.1-2.2 5.5-5.4 6.8C4.8 13.1 2.6 10.7 2.6 7.6v-4L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
        <path d="m5.8 7.9 1.6 1.6 3-3.2" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span>当前无活动预警</span>
    </p>
  </section>
</template>

<script setup>
// 活动预警：来自 /realtime/alerts/overview 的 active 告警，按当前站过滤；
// 无预警时只显示一行“当前无活动预警”，不造状态。
import { computed, onMounted, ref } from 'vue'
import { ALERT_LEVEL_TEXT, fetchAlertOverview, formatAlertTime } from '../../services/alerts.js'

const props = defineProps({
  stationId: { type: String, default: '' }
})

const state = ref('loading')
const overview = ref(null)

async function load(force = false) {
  state.value = 'loading'
  try {
    overview.value = await fetchAlertOverview({ force })
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

const stationAlerts = computed(() =>
  (overview.value?.active_alerts || []).filter((a) => a.station_id === props.stationId)
)

function durationText(a) {
  if (!a.triggered_at) return ''
  const ms = Date.now() - Date.parse(a.triggered_at)
  if (!Number.isFinite(ms) || ms < 0) return ''
  const hours = ms / 3_600_000
  const text = hours < 1 ? `${Math.round(ms / 60_000)} 分钟` : hours < 48 ? `${hours.toFixed(1)} 小时` : `${(hours / 24).toFixed(1)} 天`
  return ` · 持续 ${text}`
}

onMounted(() => load())
</script>

<style scoped>
.sac-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.sac-item {
  --sac-bar: var(--color-primary);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 6px 9px 6px 12px;
  background: var(--surface-panel-soft);
  position: relative;
  overflow: hidden;
}
/* 左缘 3px 严重度色条：moderate= critical 红 / light= medium 琥珀（既有映射），
   无等级字段时退统一主色，不另造等级 */
.sac-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--sac-bar);
}
.sac-item--moderate { --sac-bar: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 45%, transparent); }
.sac-item--light { --sac-bar: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 45%, transparent); }
.sac-item:hover { filter: brightness(1.12); }
.sac-level {
  font-size: 10.5px;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
}
.sac-item--moderate .sac-level { color: var(--risk-critical, #ef4444); }
.sac-item--light .sac-level { color: var(--risk-medium, #f5b45d); }
.sac-main { display: grid; gap: 1px; min-width: 0; }
.sac-main b { font-size: 12px; color: var(--text-primary); font-family: var(--font-mono); font-weight: 600; }
.sac-main small { font-size: 10.5px; color: var(--text-muted); }
.sac-none {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  opacity: 0.85;
}
.sac-none-ico { flex: none; }
@media (prefers-reduced-motion: no-preference) {
  .sac-item { transition: filter 160ms var(--ease-out, ease); }
}
</style>
