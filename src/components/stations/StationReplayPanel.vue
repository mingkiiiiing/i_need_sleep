<template>
  <section class="srp" aria-label="实时快照回放（observed 轨）">
    <div class="srp-head">
      <div>
        <p class="srp-kicker">REALTIME SNAPSHOT REPLAY · OBSERVED</p>
        <h2>实时快照回放</h2>
        <p class="srp-sub">按真实站点逐次快照回放官方观测；快照积累不足时明确提示，不做模拟补齐。</p>
      </div>
      <select v-model="selectedId" class="srp-select" aria-label="选择实时站点">
        <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.source_station_name }}（{{ s.province || '—' }}）</option>
      </select>
    </div>

    <div v-if="state === 'loading'" class="srp-note">正在加载快照…</div>
    <div v-else-if="state === 'error'" class="srp-note srp-note--bad" role="alert">
      快照数据加载失败
      <button type="button" class="srp-btn" @click="load">重试</button>
    </div>
    <div v-else-if="!stations.length" class="srp-note">
      实时站点目录为空：从未成功抓取，禁止回退情景数据。
    </div>
    <template v-else>
      <div v-if="snapshots.length < 2" class="srp-note srp-note--warn">
        尚未积累：该站点目前仅有 {{ snapshots.length }} 次快照，暂不可回放趋势；系统随抓取自动积累。
      </div>
      <div class="srp-table-wrap">
        <table class="srp-table">
          <thead>
            <tr>
              <th>快照时间</th>
              <th>观测时间</th>
              <th v-for="col in COLUMNS" :key="col.code">{{ col.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in replayRows" :key="row.snapshot_id">
              <td class="srp-mono">{{ row.retrievedText }}</td>
              <td class="srp-mono">{{ row.observedText }}</td>
              <td
                v-for="col in COLUMNS"
                :key="col.code"
                :class="{ 'srp-miss': cell(row, col.code).status !== 'ok' }"
                :title="cell(row, col.code).title"
              >
                {{ cell(row, col.code).text }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup>
// 历史页 · 实时快照回放：observed 轨唯一数据源；缺测单元格显式标“缺测”，不插值。
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchRealtimeStations,
  fetchStationObservations,
  formatStamp
} from '../../services/realtime.js'

const COLUMNS = [
  { code: 'water_temperature', label: '水温℃' },
  { code: 'pH', label: 'pH' },
  { code: 'dissolved_oxygen', label: '溶解氧' },
  { code: 'total_phosphorus', label: '总磷' },
  { code: 'total_nitrogen', label: '总氮' },
  { code: 'chlorophyll_a', label: '叶绿素a' },
  { code: 'cyanobacteria_density', label: '藻密度' }
]

const stations = ref([])
const selectedId = ref('')
const rows = ref([])
const state = ref('loading')

// 同一快照按观测时间取最新一行
const snapshots = computed(() => {
  const bySnapshot = new Map()
  rows.value.forEach((row) => {
    const prev = bySnapshot.get(row.snapshot_id)
    if (!prev || String(row.observed_at) > String(prev.observed_at)) bySnapshot.set(row.snapshot_id, row)
  })
  return Array.from(bySnapshot.values()).sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)))
})

const replayRows = computed(() =>
  snapshots.value.map((row) => ({
    snapshot_id: row.snapshot_id,
    retrievedText: formatStamp(row.retrieved_at),
    observedText: formatStamp(row.observed_at)
  }))
)

function cell(row, code) {
  const match = rows.value.find((r) => r.snapshot_id === row.snapshot_id && r.variable_code === code)
  if (!match || match.observation_status !== 'ok' || match.value == null) {
    return { text: '缺测', status: 'missing', title: (match && (match.missing_reason || match.observation_status)) || '缺测' }
  }
  return { text: match.value, status: 'ok', title: `${match.unit || ''}` }
}

async function loadRows() {
  if (!selectedId.value) return
  state.value = 'loading'
  rows.value = []
  try {
    rows.value = await fetchStationObservations(selectedId.value, {
      window: 'range',
      start: '2026-09-01',
      end: new Date().toISOString().slice(0, 10)
    })
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

watch(selectedId, loadRows)

onMounted(async () => {
  try {
    stations.value = await fetchRealtimeStations()
    if (stations.value.length) {
      selectedId.value = stations.value[0].id
    } else {
      state.value = 'ok'
    }
  } catch {
    state.value = 'error'
  }
})
</script>

<style scoped>
.srp {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 14px 16px;
  display: grid;
  gap: 10px;
}
.srp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.srp-kicker { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.2em; color: var(--color-primary); margin: 0 0 2px; }
.srp-head h2 { margin: 0; font-size: 16px; color: var(--text-primary); }
.srp-sub { margin: 3px 0 0; font-size: 11.5px; color: var(--text-secondary); line-height: 1.6; }
.srp-select {
  min-height: 40px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
  padding: 4px 10px;
  max-width: 260px;
}
.srp-select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.srp-note { font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.srp-note--warn { color: var(--risk-medium, #f5b45d); }
.srp-note--bad { color: var(--risk-critical, #ff6b6b); display: flex; gap: 10px; align-items: center; }
.srp-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 32px;
  padding: 2px 12px;
  cursor: pointer;
}
.srp-table-wrap { overflow-x: auto; }
.srp-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.srp-table th, .srp-table td { text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
.srp-table th { color: var(--text-muted); font-weight: 600; font-size: 10.5px; }
.srp-table td { color: var(--text-primary); font-family: var(--font-mono); }
.srp-miss { color: var(--text-muted); }
.srp-mono { font-family: var(--font-mono); font-size: 11px; }
</style>
