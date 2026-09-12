<script setup>
import { computed } from 'vue'

// 范围性质标签（四态）：预测 / 参考 / 情景 / 暂无。
// 组件只负责按 kind 呈现，不做任何业务判定（判定逻辑在页面侧 Heatmap.vue）；
// 颜色全部取自全局设计令牌，随 data-theme（dark/light/sunrise）自动切换。
const props = defineProps({
  // 'forecast' 预测范围 | 'reference' 参考范围 | 'scenario' 情景范围 | 'none' 暂无范围
  kind: {
    type: String,
    required: true,
    validator: (value) => ['forecast', 'reference', 'scenario', 'none'].includes(value)
  },
  // 完整证据文本：非空时挂 title 悬浮提示；为空时不挂 title，不伪造证据
  evidence: { type: String, default: '' }
})

const KIND_META = {
  forecast: { label: '预测范围' },
  reference: { label: '参考范围' },
  scenario: { label: '情景范围' },
  none: { label: '暂无范围' }
}

// 未知 kind 一律按「暂无范围」呈现，绝不把无证据伪装成有范围
const safeKind = computed(() => (KIND_META[props.kind] ? props.kind : 'none'))
const label = computed(() => KIND_META[safeKind.value].label)
const hasEvidence = computed(() => Boolean(props.evidence))
const ariaLabel = computed(() => `范围性质：${label.value}`)
</script>

<template>
  <span
    class="range-badge"
    :data-state="safeKind"
    :title="hasEvidence ? evidence : undefined"
    :aria-label="ariaLabel"
    role="img"
  >
    <!-- 12px 内联图标：forecast=圆内对勾 reference=波浪线 scenario=虚线框 none=短横 -->
    <svg
      viewBox="0 0 12 12"
      width="12"
      height="12"
      fill="none"
      stroke="currentColor"
      stroke-width="1.4"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <template v-if="safeKind === 'forecast'">
        <circle cx="6" cy="6" r="4.6" />
        <path d="M4 6.2 5.5 7.7 8.2 4.5" />
      </template>
      <path v-else-if="safeKind === 'reference'" d="M1.2 6 Q 2.6 3.4 4 6 T 6.8 6 T 10.8 6" />
      <rect
        v-else-if="safeKind === 'scenario'"
        x="1.8"
        y="2.8"
        width="8.4"
        height="6.4"
        rx="1.4"
        stroke-dasharray="2 1.5"
      />
      <path v-else d="M3.4 6 H 8.6" />
    </svg>
    <span class="range-badge-text">{{ label }}</span>
  </span>
</template>

<style scoped>
.range-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 2px 10px;
  border: 1px solid color-mix(in srgb, currentColor 38%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, currentColor 9%, transparent);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
  white-space: nowrap;
  cursor: help;
}
.range-badge[data-state='forecast'] { color: var(--c-stable); }
.range-badge[data-state='reference'] { color: var(--c-watch); }
.range-badge[data-state='scenario'] { color: var(--c-ai); }
.range-badge[data-state='none'] { color: var(--text-muted); }
.range-badge svg { flex: none; }
.range-badge-text { overflow: hidden; text-overflow: ellipsis; }
</style>
