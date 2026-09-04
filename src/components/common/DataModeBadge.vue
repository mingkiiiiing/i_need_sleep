<template>
  <span class="dmb" :class="`dmb--${variant}`">
    <span class="dmb-dot" aria-hidden="true"></span>
    <span class="dmb-text">{{ text }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // observed | forecast | experimental | simulated
  mode: { type: String, default: 'simulated' },
  label: { type: String, default: '' }
})

const VALID = ['observed', 'forecast', 'experimental', 'simulated']
const DEFAULT_LABELS = {
  observed: '观测数据',
  forecast: '预测数据',
  experimental: '实验数据',
  simulated: '模拟数据'
}

const variant = computed(() => (VALID.includes(props.mode) ? props.mode : 'simulated'))
const text = computed(() => props.label || DEFAULT_LABELS[variant.value])
</script>

<style scoped>
.dmb {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  border: 1px solid color-mix(in srgb, currentColor 36%, transparent);
  background: color-mix(in srgb, currentColor 10%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  line-height: 1.7;
  white-space: nowrap;
}
.dmb-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
.dmb--observed { color: var(--data-observed); }
.dmb--forecast { color: var(--data-forecast); }
.dmb--experimental { color: var(--data-experimental); }
.dmb--simulated { color: var(--data-simulated); }
</style>
