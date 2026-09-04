<template>
  <article class="metric-card">
    <header class="mc-head">
      <span class="mc-label">{{ label }}</span>
      <QualityBadge v-if="quality" :quality="quality" :label="qualityLabel" />
    </header>
    <p class="mc-value">
      <span class="mc-num">{{ value }}</span>
      <span v-if="unit" class="mc-unit">{{ unit }}</span>
    </p>
    <p v-if="delta" class="mc-delta" :class="`mc-delta--${normalizedTone}`">{{ delta }}</p>
    <footer v-if="asOf || mode" class="mc-foot">
      <span v-if="asOf" class="mc-asof">{{ asOf }}</span>
      <DataModeBadge v-if="mode" :mode="mode" :label="modeLabel" />
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import QualityBadge from './QualityBadge.vue'
import DataModeBadge from './DataModeBadge.vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  unit: { type: String, default: '' },
  // 变化说明文本（可含 ▲/▼），配合 tone 决定颜色
  delta: { type: String, default: '' },
  // good | warn | bad | neutral
  tone: { type: String, default: 'neutral' },
  // 传给 QualityBadge 的数据质量标识（good | missing | pending | fault）
  quality: { type: String, default: '' },
  qualityLabel: { type: String, default: '' },
  asOf: { type: String, default: '' },
  // 传给 DataModeBadge 的数据模式标识
  mode: { type: String, default: '' },
  modeLabel: { type: String, default: '' }
})

const TONES = ['good', 'warn', 'bad', 'neutral']
const normalizedTone = computed(() => (TONES.includes(props.tone) ? props.tone : 'neutral'))
</script>

<style scoped>
.metric-card {
  display: grid;
  gap: 8px;
  padding: var(--spacing-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.mc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.mc-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}
.mc-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.mc-num {
  font-family: var(--font-mono);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.mc-unit {
  font-size: 12px;
  color: var(--text-muted);
}
.mc-delta {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
}
.mc-delta--good { color: var(--risk-low); }
.mc-delta--warn { color: var(--risk-medium); }
.mc-delta--bad { color: var(--risk-critical); }
.mc-delta--neutral { color: var(--text-secondary); }
.mc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 22px;
}
.mc-asof {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
</style>
