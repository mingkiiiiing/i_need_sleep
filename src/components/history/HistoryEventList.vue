<template>
  <div class="hel" data-role="event-list-panel">
    <StatePanel
      v-if="state === 'loading'"
      state="loading"
      title="事件加载中…"
      description="正在请求 /events 与 /cockpit/events 两个演示事件源。"
    />
    <StatePanel
      v-else-if="state === 'error'"
      state="error"
      title="事件列表加载失败"
      :description="error || '事件接口请求失败，不展示部分事件或不切换本地数据。'"
    >
      <button type="button" class="hel-retry" data-role="event-list-retry" @click="$emit('retry')">重试加载事件</button>
    </StatePanel>
    <div v-else-if="!groups.length" class="hel-empty" data-role="event-empty">
      <p>当前筛选条件下无事件</p>
      <button type="button" class="hel-retry" data-role="clear-filters" @click="$emit('clear-filters')">清除筛选</button>
    </div>
    <template v-else>
      <div
        ref="listRef"
        class="hel-scroll"
        data-role="event-list"
        role="listbox"
        aria-label="演示事件列表"
        @keydown="onKeydown"
      >
        <section v-for="group in groups" :key="group.key" class="hel-group">
          <h4 class="hel-group-title">{{ group.label }}</h4>
          <button
            v-for="ev in group.events"
            :key="ev.id"
            type="button"
            role="option"
            class="hel-item"
            :class="{ active: ev.id === selectedId }"
            :data-event-id="ev.id"
            :aria-selected="String(ev.id === selectedId)"
            @click="$emit('select', ev.id)"
          >
            <span class="hel-row1">
              <strong class="hel-time">{{ timeLabel(ev) || '时间未提供' }}</strong>
              <span class="hel-badge" :class="badgeClass(ev)">{{ badgeText(ev) }}</span>
            </span>
            <span class="hel-row2">
              <span class="hel-type">{{ typeText(ev.event_type) || '类型未提供' }}</span>
              <span class="hel-zone">{{ zoneLabel(ev.spatial_entity_id) }}</span>
            </span>
            <span class="hel-row3">
              <span class="hel-mode">模式 {{ ev.data_mode || '未提供' }}</span>
              <span class="hel-sources">源 {{ sourceLabel(ev) }}</span>
            </span>
          </button>
        </section>
      </div>
      <p class="hel-foot">事件源：/events + /cockpit/events（仅按相同事件 ID 合并）</p>
    </template>
  </div>
</template>

<script setup>
import StatePanel from '../common/StatePanel.vue'
import { eventTypeText, eventTimeLabel, severityText } from './historyCore.js'

const props = defineProps({
  state: { type: String, default: 'loading' },
  error: { type: String, default: '' },
  groups: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
  zoneNames: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['select', 'retry', 'clear-filters'])

function timeLabel(ev) {
  return eventTimeLabel(ev)
}

function typeText(t) {
  return eventTypeText(t)
}

function zoneLabel(id) {
  if (!id) return '分区未提供'
  const name = props.zoneNames[id]
  return name ? `${name}` : id
}

function badgeClass(ev) {
  const sev = ev.severity
  if (sev === 'high' || sev === 'mid' || sev === 'low') return `lv-${sev}`
  return 'lv-none'
}

function badgeText(ev) {
  const t = severityText(ev.severity)
  return t || '未提供'
}

function sourceLabel(ev) {
  const s = ev.sources || []
  return s.length ? s.join('+') : '未提供'
}

function flatItems() {
  return props.groups.flatMap((g) => g.events)
}

// ↑/↓ 在可见事件间移动选择并聚焦；Enter/Space 激活聚焦项（role=option 不触发原生 click）
function onKeydown(e) {
  if (e.key === 'Enter' || e.key === ' ') {
    const btn = e.target && e.target.closest ? e.target.closest('[data-event-id]') : null
    if (btn) {
      e.preventDefault()
      emit('select', btn.getAttribute('data-event-id'))
    }
    return
  }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const items = flatItems()
  if (!items.length) return
  e.preventDefault()
  const currentIdx = items.findIndex((ev) => ev.id === props.selectedId)
  const nextIdx = e.key === 'ArrowDown'
    ? Math.min(items.length - 1, currentIdx + 1)
    : Math.max(0, currentIdx <= 0 ? 0 : currentIdx - 1)
  const next = items[nextIdx]
  if (!next) return
  emit('select', next.id)
  const el = listRef.value && listRef.value.querySelector(`[data-event-id="${CSS.escape(next.id)}"]`)
  if (el) el.focus()
}
</script>

<style scoped>
.hel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.hel-scroll {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  min-height: 0;
}
.hel-group {
  display: grid;
  gap: 5px;
}
.hel-group-title {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}
.hel-item {
  appearance: none;
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
}
.hel-item:hover {
  border-color: var(--border-strong, rgba(255, 255, 255, 0.2));
}
.hel-item.active {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
}
.hel-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hel-row1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.hel-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.hel-badge {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}
.lv-high { color: var(--risk-critical, #ef4444); border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent); }
.lv-mid { color: var(--risk-medium, #facc15); border: 1px solid color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent); }
.lv-low { color: var(--risk-low, #22c55e); border: 1px solid color-mix(in srgb, var(--risk-low, #22c55e) 50%, transparent); }
.lv-none { color: var(--text-muted); border: 1px dashed var(--border-subtle); }
.hel-row2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
}
.hel-type {
  color: var(--text-secondary);
}
.hel-zone {
  font-family: var(--font-mono);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hel-row3 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.hel-foot {
  margin: 0;
  font-size: 9.5px;
  line-height: 1.6;
  color: var(--text-muted);
}
.hel-empty {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 26px 12px;
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel-soft);
  text-align: center;
}
.hel-empty p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.hel-retry {
  appearance: none;
  min-height: 34px;
  padding: 4px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.hel-retry:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

@media (max-width: 960px) {
  .hel-item,
  .hel-retry {
    min-height: 44px;
  }
}
</style>
