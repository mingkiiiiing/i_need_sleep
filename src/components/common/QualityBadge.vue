<template>
  <span class="qb" :class="`qb--${variant}`">
    <span class="qb-dot" aria-hidden="true"></span>{{ text }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // good | missing | pending | fault —— 数据质量（与 DataModeBadge 的数据性质互补，不重复）
  quality: { type: String, default: 'good' },
  label: { type: String, default: '' }
})

const VALID = ['good', 'missing', 'pending', 'fault']
const DEFAULT_LABELS = {
  good: '质量正常',
  missing: '缺测',
  pending: '待质控',
  fault: '质控异常'
}

const variant = computed(() => (VALID.includes(props.quality) ? props.quality : 'pending'))
const text = computed(() => props.label || DEFAULT_LABELS[variant.value])
</script>

<style scoped>
.qb {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  line-height: 1.7;
  white-space: nowrap;
}
.qb-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
/* 质量语义用中性/警示色表达，不与风险色、数据身份色混用 */
.qb--good { color: var(--text-secondary); }
.qb--missing { color: var(--text-muted); }
.qb--pending { color: var(--risk-medium); }
.qb--fault { color: var(--risk-critical); }
</style>
