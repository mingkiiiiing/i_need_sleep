<template>
  <main class="page-wallboard">
    <header class="wb-head">
      <div class="wb-title">
        <p class="wb-kicker">WALLBOARD · REALTIME STATIONS</p>
        <h1>太湖流域国控站点实时大屏</h1>
      </div>
      <DataModeBadge mode="observed" label="实时观测" />
    </header>

    <section class="wb-summary" aria-label="汇总指标">
      <div class="wb-card">
        <span class="wb-num">{{ summary.active }}</span>
        <span class="wb-label">活跃站点</span>
      </div>
      <div class="wb-card wb-card--red" :class="{ 'wb-card--zero': !alertCounts.moderate }">
        <span class="wb-num">{{ alertCounts.moderate }}</span>
        <span class="wb-label">红色告警（chla ≥ {{ thresholds.moderate }}）</span>
      </div>
      <div class="wb-card wb-card--yellow" :class="{ 'wb-card--zero': !alertCounts.light }">
        <span class="wb-num">{{ alertCounts.light }}</span>
        <span class="wb-label">黄色预警（chla ≥ {{ thresholds.light }}）</span>
      </div>
      <div class="wb-card">
        <span class="wb-num">{{ summary.missingRate }}</span>
        <span class="wb-label">最新快照缺测率</span>
      </div>
      <div class="wb-card">
        <span class="wb-num">{{ summary.locVerified }}</span>
        <span class="wb-label">已核验坐标</span>
      </div>
    </section>

    <div class="wb-legend" aria-label="着色图例">
      <span class="wb-legend-item"><i class="wb-swatch wb-swatch--red"></i>红色告警 · 叶绿素a ≥ {{ thresholds.moderate }} μg/L</span>
      <span class="wb-legend-item"><i class="wb-swatch wb-swatch--yellow"></i>黄色预警 · 叶绿素a ≥ {{ thresholds.light }} μg/L</span>
      <span class="wb-legend-item"><i class="wb-swatch wb-swatch--green"></i>无预警（左边条 = 数据状态）</span>
      <span class="wb-legend-note">推送状态见右上角 🔔 / <RouterLink to="/alerts" class="wb-legend-link">预警通知页</RouterLink></span>
    </div>

    <div v-if="state === 'error'" class="wb-error" role="alert">
      实时站点加载失败（不会回退情景数据）
      <button type="button" class="wb-btn" @click="load(true)">重试</button>
    </div>
    <div v-else-if="state === 'loading'" class="wb-loading">正在加载实时站点…</div>

    <section v-else class="wb-grid" aria-label="站点卡片墙">
      <article v-for="s in stations" :key="s.id" class="wb-station" :class="stationClass(s)">
        <div class="wb-station-head">
          <strong>{{ s.source_station_name }}</strong>
          <span class="wb-level">{{ s.latest_water_quality_level ? `类${s.latest_water_quality_level}` : '—' }}</span>
        </div>
        <div class="wb-station-meta">
          {{ s.province || '—' }}
          <span v-if="riskOf(s)" class="wb-risk-chip" :class="`wb-risk-chip--${riskOf(s).level}`">
            {{ riskOf(s).level === 'moderate' ? '红色告警' : '黄色预警' }} · chla {{ riskOf(s).chla.toFixed(1) }}
          </span>
        </div>
        <div class="wb-station-foot">
          <span>可用 {{ s.available_variable_count }}/{{ variableTotal(s) }}</span>
          <span v-if="s.missing_variable_count" class="wb-miss">缺测 {{ s.missing_variable_count }}</span>
          <span class="wb-time">{{ formatStamp(s.latest_observed_at) }}</span>
        </div>
      </article>
    </section>

    <p class="wb-foot">
      站点集合由最新成功快照动态决定；预警分级与实时汇总蓝藻筛查同口径（10/25 μg/L）。官方观测未经跨源验证，不用于监管决策。每 60 秒自动刷新。
    </p>
  </main>
</template>

<script setup>
// 展示大屏：与 /stations 共用同一实时站点服务（services/realtime.js），
// 不维护第二份站点数据副本；缺测率与坐标状态如实披露。
// 风险着色（黄/红）与预警服务（services/alerts.js）同口径，卡片底色按风险等级、左边条按数据状态。
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DataModeBadge from '../components/common/DataModeBadge.vue'
import {
  fetchRealtimeStations,
  fetchRealtimeStatus,
  formatStamp,
  stationDataStatus
} from '../services/realtime.js'
import { fetchAlertOverview } from '../services/alerts.js'

const stations = ref([])
const status = ref(null)
const alertOverview = ref(null)
const state = ref('loading')
let timer = null

const summary = computed(() => {
  const total = stations.value.length
  const variableTotalSum = stations.value.reduce((acc, s) => acc + variableTotal(s), 0)
  const missingSum = stations.value.reduce((acc, s) => acc + (s.missing_variable_count || 0), 0)
  const locVerified = stations.value.filter((s) => s.location?.location_status === 'verified').length
  return {
    active: status.value ? status.value.active_station_count : total,
    missingRate: variableTotalSum ? `${((missingSum / variableTotalSum) * 100).toFixed(1)}%` : '—',
    locVerified
  }
})

const alertCounts = computed(() => alertOverview.value?.active_counts || { light: 0, moderate: 0 })
const thresholds = computed(() => alertOverview.value?.thresholds || { light: 10, moderate: 25 })
const alertByStation = computed(() => {
  const map = new Map()
  for (const a of alertOverview.value?.active_alerts || []) map.set(a.station_id, a)
  return map
})

function riskOf(s) {
  const alert = alertByStation.value.get(s.id)
  if (!alert) return null
  return { level: alert.level, chla: alert.chla ?? 0 }
}

function stationClass(s) {
  const risk = riskOf(s)
  if (risk) return `wb-station--risk-${risk.level}`
  const key = stationDataStatus(s)
  return key === 'normal' ? 'wb-station--ok' : key === 'delayed' ? 'wb-station--warn' : 'wb-station--bad'
}

function variableTotal(s) {
  return s.available_variable_count + s.missing_variable_count + s.qc_rejected_variable_count
}

async function load(force = false) {
  if (force) state.value = 'loading'
  try {
    const [list, st, alerts] = await Promise.all([
      fetchRealtimeStations({ force }),
      fetchRealtimeStatus({ force }),
      fetchAlertOverview({ force }).catch(() => null)
    ])
    stations.value = list
    status.value = st
    if (alerts) alertOverview.value = alerts
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 60_000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.page-wallboard {
  max-width: 1780px;
  margin: 0 auto;
  padding: 14px 20px 28px;
  display: grid;
  gap: 10px;
  min-height: 100vh;
  align-content: start;
}
.wb-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.wb-kicker { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.22em; color: var(--color-primary); margin: 0; }
.wb-title h1 { margin: 2px 0 0; font-family: var(--font-display); font-size: clamp(20px, 2.2vw, 28px); color: var(--text-primary); }
.wb-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
.wb-card {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 14px;
}
.wb-num { font-family: var(--font-mono); font-size: 22px; font-weight: 700; color: var(--text-primary); }
.wb-label { font-size: 11px; color: var(--text-muted); }
.wb-card--red.wb-card--zero .wb-num, .wb-card--yellow.wb-card--zero .wb-num { color: var(--text-secondary); }
.wb-card--red:not(.wb-card--zero) { border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 55%, transparent); }
.wb-card--red:not(.wb-card--zero) .wb-num { color: var(--risk-critical, #ff6b6b); }
.wb-card--yellow:not(.wb-card--zero) { border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent); }
.wb-card--yellow:not(.wb-card--zero) .wb-num { color: var(--risk-medium, #f5b45d); }

.wb-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  font-size: 11px;
  color: var(--text-secondary);
}
.wb-legend-item { display: inline-flex; align-items: center; gap: 6px; }
.wb-legend-note { margin-left: auto; color: var(--text-muted); }
.wb-legend-link { color: var(--color-primary); text-decoration: none; }
.wb-legend-link:hover { text-decoration: underline; }
.wb-swatch { width: 14px; height: 10px; border-radius: 3px; display: inline-block; }
.wb-swatch--red { background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 30%, transparent); border: 1px solid var(--risk-critical, #ff6b6b); }
.wb-swatch--yellow { background: color-mix(in srgb, var(--risk-medium, #f5b45d) 30%, transparent); border: 1px solid var(--risk-medium, #f5b45d); }
.wb-swatch--green { background: transparent; border: 1px dashed var(--border-subtle); border-left: 3px solid var(--risk-low, #5fd6a4); }

.wb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; }
.wb-station {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border-subtle);
  border-left-width: 3px;
  border-radius: 12px;
  background: var(--surface-panel);
  padding: 9px 11px;
  min-width: 0;
}
.wb-station--ok { border-left-color: var(--risk-low, #5fd6a4); }
.wb-station--warn { border-left-color: var(--risk-medium, #f5b45d); }
.wb-station--bad { border-left-color: var(--risk-critical, #ff6b6b); }
.wb-station--risk-light {
  border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 60%, transparent);
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 14%, var(--surface-panel));
}
.wb-station--risk-moderate {
  border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 65%, transparent);
  background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 16%, var(--surface-panel));
  animation: wb-risk-pulse 2.4s ease-in-out infinite;
}
@keyframes wb-risk-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--risk-critical, #ff6b6b) 22%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--risk-critical, #ff6b6b) 0%, transparent); }
}
.wb-station-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.wb-station-head strong { font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb-level { font-family: var(--font-mono); font-size: 11px; color: var(--color-primary); flex: none; }
.wb-station-meta { font-size: 10.5px; color: var(--text-muted); display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.wb-risk-chip {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  white-space: nowrap;
}
.wb-risk-chip--light {
  color: var(--risk-medium, #f5b45d);
  border: 1px solid color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent);
}
.wb-risk-chip--moderate {
  color: var(--risk-critical, #ff6b6b);
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ff6b6b) 60%, transparent);
}
.wb-station-foot { display: flex; flex-wrap: wrap; gap: 8px; font-family: var(--font-mono); font-size: 10.5px; color: var(--text-secondary); }
.wb-miss { color: var(--risk-medium, #f5b45d); }
.wb-time { margin-left: auto; color: var(--text-muted); }
.wb-error, .wb-loading {
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
  padding: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 12px;
}
.wb-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 34px;
  padding: 2px 14px;
  cursor: pointer;
}
.wb-foot { font-size: 10.5px; color: var(--text-muted); line-height: 1.6; }
</style>
