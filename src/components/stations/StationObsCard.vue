<template>
  <section class="stn-block soc" aria-label="最新观测">
    <div class="stn-sec-head">
      <h2>最新观测</h2>
      <span class="stn-sec-tag">{{ stationName }} · {{ observedAtText }}</span>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 4" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">观测数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </div>

    <dl v-else class="soc-grid">
      <div v-for="item in view" :key="item.code" class="soc-cell" :class="`soc-cell--${item.tone}`">
        <dt>{{ item.label }}</dt>
        <dd>
          <strong v-if="item.status === 'ok'">{{ item.text }}</strong>
          <span v-else-if="item.status === 'qc_rejected'" class="soc-bad">质控不合格</span>
          <span v-else class="soc-miss">缺测</span>
          <small>{{ item.status === 'ok' ? item.unit : OBS_STATUS_TEXT[item.status] }}</small>
        </dd>
      </div>
    </dl>

    <p v-if="state === 'ok'" class="soc-note">
      官方接口观测，未经跨源验证（is_ground_truth=false）；缺测如实披露，不补模拟值。
    </p>
  </section>
</template>

<script setup>
// 最新观测卡：每站固定 11 项指标状态，缺测/质控不合格显式展示，不消失、不补值。
import { computed } from 'vue'
import { OBS_STATUS_TEXT, REALTIME_VARIABLES, formatStamp } from '../../services/realtime.js'

const props = defineProps({
  stationName: { type: String, default: '' },
  observedAt: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
  state: { type: String, default: 'loading' }
})

defineEmits(['retry'])

const byCode = computed(() => {
  const map = {}
  props.rows.forEach((row) => { map[row.variable_code] = row })
  return map
})

const view = computed(() =>
  REALTIME_VARIABLES.map(({ code, label }) => {
    const row = byCode.value[code]
    const status = row ? row.observation_status : 'missing'
    return {
      code,
      label,
      status,
      text: row && row.value != null ? row.value : '—',
      unit: row && row.unit ? row.unit : '',
      tone: status === 'ok' ? 'ok' : status === 'qc_rejected' ? 'bad' : 'miss'
    }
  })
)

const observedAtText = computed(() => (props.observedAt ? `观测 ${formatStamp(props.observedAt)}` : ''))
</script>

<style scoped>
.soc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
  gap: 6px;
  margin: 0;
}
.soc-cell {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 6px 9px;
  min-width: 0;
}
.soc-cell dt { font-size: 10.5px; color: var(--text-muted); margin: 0 0 2px; }
.soc-cell dd { margin: 0; display: flex; align-items: baseline; gap: 4px; min-width: 0; }
.soc-cell dd strong { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; }
.soc-cell dd small { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.soc-cell--bad { border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 45%, transparent); }
.soc-cell--miss dd span { font-size: 11px; color: var(--text-muted); }
.soc-miss { color: var(--text-muted); }
.soc-bad { font-size: 11px; color: var(--risk-critical, #ff6b6b); }
.soc-note { margin: 8px 0 0; font-size: 10.5px; color: var(--text-muted); line-height: 1.6; }
</style>
