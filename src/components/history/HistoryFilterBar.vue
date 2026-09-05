<template>
  <form class="hfb" :class="{ 'hfb--compact': compact }" data-role="history-filter" novalidate @submit.prevent="onApply">
    <div class="hfb-fields">
      <span class="hfb-label" id="hfb-range-label">日期范围</span>
      <!-- 不设 :max：未来日期允许查询（空结果即诚实空态），先后/90 天校验在查询时执行 -->
      <input
        v-model="draftModel.start"
        class="hfb-input hfb-date"
        data-role="filter-start"
        type="date"
        aria-label="开始日期"
      />
      <span class="hfb-sep" aria-hidden="true">~</span>
      <input
        v-model="draftModel.end"
        class="hfb-input hfb-date"
        data-role="filter-end"
        type="date"
        aria-label="结束日期"
      />

      <span class="hfb-label">事件类型</span>
      <select v-model="draftModel.type" class="hfb-input" data-role="filter-type" aria-label="事件类型">
        <option value="">全部类型</option>
        <option v-for="t in options.types" :key="t" :value="t">{{ typeText(t) }}</option>
      </select>

      <span class="hfb-label">演示分区</span>
      <select v-model="draftModel.p" class="hfb-input" data-role="filter-zone" aria-label="演示分区">
        <option value="">全部分区</option>
        <option v-for="z in options.zones" :key="z.id" :value="z.id">{{ z.label }}</option>
      </select>

      <span class="hfb-label">数据模式</span>
      <select v-model="draftModel.mode" class="hfb-input" data-role="filter-mode" aria-label="数据模式">
        <option value="">全部模式</option>
        <option v-for="m in options.modes" :key="m" :value="m">{{ m }}</option>
      </select>

      <span class="hfb-label">处置状态</span>
      <select
        class="hfb-input"
        data-role="filter-status"
        aria-label="处置状态（接口未提供，无法筛选）"
        disabled
        aria-disabled="true"
        title="处置状态接口未提供，无法按状态筛选"
      >
        <option value="">接口未提供</option>
      </select>
    </div>

    <p v-if="error" class="hfb-error" data-role="filter-error" role="alert">{{ error }}</p>

    <div class="hfb-actions">
      <button type="submit" class="hfb-btn hfb-btn--primary" data-role="filter-query">查询</button>
      <button type="button" class="hfb-btn" data-role="filter-reset" @click="$emit('reset')">重置</button>
      <span v-if="!compact" class="hfb-note">处置状态筛选需后端提供处置记录接口后开放</span>
    </div>
  </form>
</template>

<script setup>
import { computed } from 'vue'
import { eventTypeText } from './historyCore.js'

const props = defineProps({
  draft: { type: Object, required: true },
  options: {
    type: Object,
    default: () => ({ types: [], zones: [], modes: [] })
  },
  error: { type: String, default: '' },
  compact: { type: Boolean, default: false }
})

const emit = defineEmits(['apply', 'reset', 'update:draft'])

const draftModel = computed({
  get: () => props.draft,
  set: (v) => emit('update:draft', v)
})

function typeText(t) {
  return eventTypeText(t) || t
}

function onApply() {
  emit('apply')
}
</script>

<style scoped>
.hfb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.hfb-fields {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  min-width: 0;
}
.hfb-label {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hfb-input {
  min-height: 34px;
  padding: 4px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  font-family: var(--font-mono);
}
.hfb-input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.hfb-input:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hfb-date {
  width: 132px;
}
.hfb-sep {
  color: var(--text-muted);
  font-size: 11px;
}
.hfb-error {
  margin: 0;
  width: 100%;
  font-size: 11.5px;
  color: var(--risk-critical, #ef4444);
}
.hfb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hfb-btn {
  appearance: none;
  min-height: 34px;
  padding: 4px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 650;
  cursor: pointer;
}
.hfb-btn--primary {
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 16%, transparent);
}
.hfb-btn:hover {
  border-color: var(--border-strong, rgba(255, 255, 255, 0.2));
}
.hfb-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hfb-note {
  font-size: 10px;
  color: var(--text-muted);
}
.hfb--compact .hfb-fields {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px 8px;
}
.hfb--compact .hfb-sep {
  display: none;
}
.hfb--compact .hfb-date {
  width: 100%;
}
.hfb--compact .hfb-input,
.hfb--compact .hfb-btn {
  min-height: 44px;
}
.hfb--compact .hfb-actions {
  margin-top: 4px;
}
.hfb--compact .hfb-btn {
  flex: 1;
  justify-content: center;
}

/* 移动端触摸目标 ≥44×44（含桌面筛选行在窄屏复用的场景） */
@media (max-width: 960px) {
  .hfb-input,
  .hfb-btn {
    min-height: 44px;
  }
}
</style>
