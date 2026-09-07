<template>
  <section class="rt-bar" :class="`rt-bar--${tone}`" aria-label="实时数据链路状态">
    <span class="rt-dot" aria-hidden="true"></span>
    <div v-if="state === 'error'" class="rt-main">
      <strong>实时链路状态获取失败</strong>
      <button type="button" class="rt-btn" @click="load(true)">重试</button>
    </div>
    <template v-else-if="status">
      <div class="rt-main">
        <template v-if="!status.available">
          <strong class="rt-warn">实时抓取不可用：从未成功抓取，当前无任何真实数据展示</strong>
        </template>
        <template v-else-if="status.freshness_status !== 'normal'">
          <strong class="rt-warn">
            实时数据{{ FRESHNESS_TEXT[status.freshness_status] || status.freshness_status }}：
            当前展示最后成功抓取数据（观测时间 {{ formatStamp(status.latest_observed_at) }}）
          </strong>
        </template>
        <template v-else>
          <strong>实时数据链路正常</strong>
        </template>
        <span class="rt-meta">
          最后成功抓取 {{ formatStamp(status.last_success_at) }}
          <template v-if="status.last_attempt_at && status.collection_status !== 'completed'">
            · 最近一次抓取失败（{{ status.last_error_code || '抓取异常' }}），保留最后成功数据
          </template>
          · 最新观测 {{ formatStamp(status.latest_observed_at) }}
          · 活跃站点 {{ status.active_station_count }}
          · 观测滞后 {{ formatLag(status.observed_lag_h) }}
        </span>
      </div>
      <span class="rt-tag">数据口径 observed · 官方观测未经跨源验证</span>
    </template>
    <div v-else class="rt-main"><span class="rt-loading">正在获取实时链路状态…</span></div>
  </section>
</template>

<script setup>
// 实时状态条：唯一数据来源 /api/v1/realtime/status（observed 轨）。
// 抓取失败/延迟必须醒目展示，禁止静默当作实时数据。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchRealtimeStatus, FRESHNESS_TEXT, formatLag, formatStamp } from '../../services/realtime.js'

const status = ref(null)
const state = ref('loading')
let refreshTimer = null

const tone = computed(() => {
  if (state.value === 'error') return 'error'
  if (!status.value) return 'idle'
  if (!status.value.available) return 'error'
  if (status.value.freshness_status === 'normal') return 'ok'
  return 'warn'
})

async function load(force = false) {
  state.value = 'loading'
  try {
    status.value = await fetchRealtimeStatus({ force })
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

onMounted(() => {
  load()
  refreshTimer = setInterval(() => load(true), 60_000)
})

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.rt-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.rt-bar--ok { border-color: color-mix(in srgb, var(--risk-low, #5fd6a4) 40%, transparent); }
.rt-bar--warn { border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent); background: color-mix(in srgb, var(--risk-medium, #f5b45d) 8%, var(--surface-panel)); }
.rt-bar--error { border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 55%, transparent); background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 8%, var(--surface-panel)); }
.rt-dot { width: 9px; height: 9px; border-radius: 999px; background: var(--text-muted); flex: none; }
.rt-bar--ok .rt-dot { background: var(--risk-low, #5fd6a4); }
.rt-bar--warn .rt-dot { background: var(--risk-medium, #f5b45d); }
.rt-bar--error .rt-dot { background: var(--risk-critical, #ff6b6b); }
.rt-main { display: grid; gap: 2px; min-width: 0; flex: 1; }
.rt-main strong { font-size: 12.5px; color: var(--text-primary); }
.rt-warn { color: var(--risk-medium, #f5b45d); }
.rt-bar--error .rt-warn { color: var(--risk-critical, #ff6b6b); }
.rt-meta { font-size: 11px; color: var(--text-secondary); line-height: 1.5; }
.rt-tag {
  flex: none;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 3px 9px;
  white-space: nowrap;
}
.rt-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  min-height: 30px;
  padding: 2px 12px;
  border-radius: 999px;
  cursor: pointer;
  justify-self: start;
}
.rt-loading { font-size: 12px; color: var(--text-secondary); }
@media (max-width: 720px) {
  .rt-tag { display: none; }
}
</style>
