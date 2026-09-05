<template>
  <section class="stn-block stn-sec-events" aria-label="分区事件与模拟预警">
    <header class="stn-sec-head">
      <h2>事件与模拟预警</h2>
      <span class="stn-sec-tag">演示事件流</span>
    </header>
    <div v-if="eventsState === 'loading'" class="stn-skel-mini" role="status" aria-label="事件加载中">
      <div class="skel-row"></div>
    </div>
    <StatePanel v-else-if="eventsState === 'error'" state="error" description="事件接口请求失败，可重试。">
      <button type="button" class="stn-inline-btn" @click="$emit('retry-events')">重试</button>
    </StatePanel>
    <p v-else-if="!events.length" class="stn-none">该分区暂无演示事件。</p>
    <ul v-else class="stn-event-list">
      <li v-for="ev in events" :key="ev.id">
        <span class="se-time mono">{{ formatStamp(ev.occurred_at) }}</span>
        <span class="se-title">{{ ev.title }}</span>
        <em class="se-mode">simulated</em>
      </li>
    </ul>

    <div v-if="warningResult" class="stn-warn-result" role="status">
      演示处理结果：<b class="stn-mono">{{ warningResult.status }}</b>
      <span v-if="warningResult.channels && warningResult.channels.length" class="stn-mono">（{{ warningResult.channels.join(' / ') }}）</span>
    </div>
    <p v-else-if="warningError" class="stn-warn-error" role="alert">模拟处理调用失败：{{ warningError }}</p>

    <button
      type="button"
      class="stn-warn-btn"
      :disabled="warningBusy"
      data-role="warn-trigger"
      @click="$emit('warn')"
    >
      <span aria-hidden="true">⚠</span>
      模拟预警（演示处理，非真实发布）
    </button>
  </section>
</template>

<script setup>
import StatePanel from '../common/StatePanel.vue'
import { formatStamp } from './stationDisplay.js'

defineProps({
  events: { type: Array, default: () => [] },
  eventsState: { type: String, default: 'loading' },
  warningBusy: { type: Boolean, default: false },
  warningResult: { type: Object, default: null },
  warningError: { type: String, default: '' }
})

defineEmits(['retry-events', 'warn'])
</script>

<style scoped>
.stn-event-list { display: grid; gap: 6px; }
.stn-event-list li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}
.se-time { color: var(--text-muted); font-size: 11px; }
.se-title { color: var(--text-primary); }
.se-mode {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--data-simulated, #f5b45d);
  border: 1px dashed color-mix(in srgb, currentColor 55%, transparent);
  border-radius: 999px;
  padding: 0 6px;
}

.stn-warn-result {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  padding: 6px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 10px);
  background: var(--surface-panel-soft);
}
.stn-warn-result b { color: var(--data-simulated, #f5b45d); }
.stn-warn-error {
  margin-top: 10px;
  font-size: 12px;
  color: var(--risk-critical, #ff6b6b);
}

.stn-warn-btn {
  margin-top: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 44px;
  padding: 10px 14px;
  border-radius: var(--radius-item, 10px);
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ff6b6b) 55%, transparent);
  background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 12%, transparent);
  color: var(--risk-critical, #ff6b6b);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  transition: filter 0.15s ease, background 0.15s ease;
}
.stn-warn-btn:hover:not(:disabled) { filter: brightness(1.12); }
.stn-warn-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.stn-warn-btn:focus-visible { outline: 2px solid var(--risk-critical, #ff6b6b); outline-offset: 2px; }
</style>
