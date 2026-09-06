<template>
  <section class="stn-block sqc" aria-label="数据质量">
    <div class="stn-sec-head">
      <h2>数据质量</h2>
      <span class="stn-sec-tag">{{ statusText }}</span>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 3" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">质量数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </div>

    <template v-else-if="quality">
      <dl class="stn-kv sqc-kv">
        <dt>指标覆盖</dt>
        <dd class="stn-mono">{{ quality.coverage_ratio != null ? `${(quality.coverage_ratio * 100).toFixed(1)}%` : '—' }}（{{ quality.variable_coverage?.ok ?? 0 }}/{{ quality.variable_coverage?.total ?? 11 }}）</dd>
        <dt>观测滞后</dt>
        <dd class="stn-mono">{{ formatLag(quality.observed_lag_h) }}</dd>
        <dt>位置状态</dt>
        <dd :class="{ 'sqc-warn': quality.location_status !== 'verified' }">{{ locationText }}</dd>
        <dt>快照累计</dt>
        <dd class="stn-mono">{{ quality.snapshot_count }} 次</dd>
      </dl>

      <p v-if="quality.missing_variables && quality.missing_variables.length" class="sqc-line">
        <strong>缺测指标：</strong>{{ quality.missing_variables.map(variableLabel).join('、') }}
      </p>
      <p v-if="quality.qc_rejected_variables && quality.qc_rejected_variables.length" class="sqc-line sqc-line--bad">
        <strong>上游质控不合格：</strong>{{ quality.qc_rejected_variables.map(variableLabel).join('、') }}
      </p>

      <ul class="sqc-limits">
        <li v-for="(item, i) in quality.limitations" :key="i">{{ item }}</li>
      </ul>

      <p class="sqc-suit">
        适用性：展示 {{ quality.suitability?.display ? '✓' : '✗' }} ·
        趋势分析 {{ quality.suitability?.trend ? '✓' : '✗' }} ·
        模型使用 {{ quality.suitability?.model_use ? '✓' : '✗' }}
      </p>
    </template>
  </section>
</template>

<script setup>
// 数据质量卡：覆盖率、滞后、缺测/质控不合格指标、坐标可信度与适用性，全部来自 /quality 端点。
import { computed } from 'vue'
import { LOCATION_STATUS_TEXT, formatLag, variableLabel } from '../../services/realtime.js'

const props = defineProps({
  quality: { type: Object, default: null },
  state: { type: String, default: 'loading' }
})

defineEmits(['retry'])

const statusText = computed(() => {
  if (!props.quality) return ''
  return {
    normal: '数据正常',
    delayed: '数据延迟',
    severely_overdue: '严重过期',
    unavailable: '不可用'
  }[props.quality.status] || props.quality.status
})

const locationText = computed(() => {
  const key = props.quality && props.quality.location_status
  return LOCATION_STATUS_TEXT[key] || key || '—'
})
</script>

<style scoped>
.sqc-kv { margin-bottom: 6px; }
.sqc-warn { color: var(--risk-medium, #f5b45d); }
.sqc-line { margin: 4px 0; font-size: 11.5px; color: var(--text-secondary); line-height: 1.6; }
.sqc-line--bad strong { color: var(--risk-critical, #ff6b6b); }
.sqc-limits {
  margin: 6px 0;
  padding-left: 16px;
  display: grid;
  gap: 3px;
}
.sqc-limits li { font-size: 11px; color: var(--text-muted); line-height: 1.6; }
.sqc-suit { margin: 6px 0 0; font-size: 11.5px; color: var(--text-secondary); }
</style>
