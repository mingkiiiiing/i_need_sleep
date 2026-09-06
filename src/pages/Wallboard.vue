<template>
  <main class="page-wallboard">
    <header class="wb-head">
      <div class="wb-title">
        <p class="wb-kicker">WALLBOARD · REALTIME STATIONS</p>
        <h1>太湖流域国控站点实时大屏</h1>
      </div>
      <DataModeBadge mode="observed" label="实时观测" />
    </header>

    <RealtimeStatusBar />

    <section class="wb-summary" aria-label="汇总指标">
      <div class="wb-card">
        <span class="wb-num">{{ summary.active }}</span>
        <span class="wb-label">活跃站点</span>
      </div>
      <div class="wb-card">
        <span class="wb-num">{{ summary.missingRate }}</span>
        <span class="wb-label">最新快照缺测率</span>
      </div>
      <div class="wb-card">
        <span class="wb-num">{{ summary.locVerified }}</span>
        <span class="wb-label">已核验坐标</span>
      </div>
      <div class="wb-card">
        <span class="wb-num">{{ summary.locPending }}</span>
        <span class="wb-label">位置待核验/无坐标</span>
      </div>
    </section>

    <div v-if="state === 'error'" class="wb-error" role="alert">
      实时站点加载失败（不会回退情景数据）
      <button type="button" class="wb-btn" @click="load(true)">重试</button>
    </div>
    <div v-else-if="state === 'loading'" class="wb-loading">正在加载实时站点…</div>

    <section v-else class="wb-grid" aria-label="站点卡片墙">
      <article v-for="s in stations" :key="s.id" class="wb-station" :class="`wb-station--${toneOf(s)}`">
        <div class="wb-station-head">
          <strong>{{ s.source_station_name }}</strong>
          <span class="wb-level">{{ s.latest_water_quality_level ? `类${s.latest_water_quality_level}` : '—' }}</span>
        </div>
        <div class="wb-station-meta">
          {{ s.province || '—' }} · {{ LOCATION_STATUS_TEXT[s.location?.location_status] || '无坐标' }}
        </div>
        <div class="wb-station-foot">
          <span>可用 {{ s.available_variable_count }}/{{ variableTotal(s) }}</span>
          <span v-if="s.missing_variable_count" class="wb-miss">缺测 {{ s.missing_variable_count }}</span>
          <span class="wb-time">{{ formatStamp(s.latest_observed_at) }}</span>
        </div>
      </article>
    </section>

    <p class="wb-foot">
      站点集合由最新成功快照动态决定；官方观测未经跨源验证，不用于监管决策。每 60 秒自动刷新。
    </p>
  </main>
</template>

<script setup>
// 展示大屏：与 /stations 共用同一实时站点服务（services/realtime.js），
// 不维护第二份站点数据副本；缺测率与坐标状态如实披露。
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import DataModeBadge from '../components/common/DataModeBadge.vue'
import RealtimeStatusBar from '../components/stations/RealtimeStatusBar.vue'
import {
  fetchRealtimeStations,
  fetchRealtimeStatus,
  formatStamp,
  LOCATION_STATUS_TEXT,
  stationDataStatus
} from '../services/realtime.js'

const stations = ref([])
const status = ref(null)
const state = ref('loading')
let timer = null

const summary = computed(() => {
  const total = stations.value.length
  const variableTotalSum = stations.value.reduce((acc, s) => acc + variableTotal(s), 0)
  const missingSum = stations.value.reduce((acc, s) => acc + (s.missing_variable_count || 0), 0)
  const locVerified = stations.value.filter((s) => s.location?.location_status === 'verified').length
  const locPending = stations.value.filter((s) => ['metadata_only', 'suspicious', 'missing'].includes(s.location?.location_status)).length
  return {
    active: status.value ? status.value.active_station_count : total,
    missingRate: variableTotalSum ? `${((missingSum / variableTotalSum) * 100).toFixed(1)}%` : '—',
    locVerified,
    locPending
  }
})

function variableTotal(s) {
  return s.available_variable_count + s.missing_variable_count + s.qc_rejected_variable_count
}

function toneOf(s) {
  const key = stationDataStatus(s)
  return key === 'normal' ? 'ok' : key === 'delayed' ? 'warn' : 'bad'
}

async function load(force = false) {
  if (force) state.value = 'loading'
  try {
    const [list, st] = await Promise.all([
      fetchRealtimeStations({ force }),
      fetchRealtimeStatus({ force })
    ])
    stations.value = list
    status.value = st
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
.wb-station-head { display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.wb-station-head strong { font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb-level { font-family: var(--font-mono); font-size: 11px; color: var(--color-primary); flex: none; }
.wb-station-meta { font-size: 10.5px; color: var(--text-muted); }
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
