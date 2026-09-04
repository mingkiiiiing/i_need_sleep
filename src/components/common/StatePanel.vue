<template>
  <section class="state-panel" :class="`state-panel--${normalized}`" role="status">
    <span class="sp-glyph" aria-hidden="true">{{ glyph }}</span>
    <h4 class="sp-title">{{ titleText }}</h4>
    <p v-if="description" class="sp-desc">{{ description }}</p>
    <div v-if="$slots.default" class="sp-actions">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // empty | error | loading
  state: { type: String, default: 'empty' },
  title: { type: String, default: '' },
  description: { type: String, default: '' }
})

const GLYPHS = { empty: '◌', error: '⚠', loading: '◠' }
const DEFAULT_TITLES = { empty: '暂无数据', error: '加载失败', loading: '加载中…' }
const VALID = ['empty', 'error', 'loading']

const normalized = computed(() => (VALID.includes(props.state) ? props.state : 'empty'))
const glyph = computed(() => GLYPHS[normalized.value])
const titleText = computed(() => props.title || DEFAULT_TITLES[normalized.value])
</script>

<style scoped>
.state-panel {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: var(--spacing-6) var(--spacing-4);
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel-soft);
  text-align: center;
}
.sp-glyph {
  font-size: 26px;
  line-height: 1;
  color: var(--text-muted);
}
.state-panel--error .sp-glyph { color: var(--risk-critical); }
.state-panel--loading .sp-glyph {
  color: var(--color-primary);
  animation: sp-spin 1.2s linear infinite;
}
@keyframes sp-spin {
  to { transform: rotate(360deg); }
}
.sp-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--text-primary);
}
.sp-desc {
  max-width: 46ch;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.sp-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 2px;
}
@media (prefers-reduced-motion: reduce) {
  .state-panel--loading .sp-glyph { animation: none; }
}
</style>
