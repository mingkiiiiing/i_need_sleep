<template>
  <aside class="rel" aria-label="历史预警事件列表">
    <header class="rel-head">
      <div>
        <p class="rel-kicker">EVENT REVIEW LIST · 历史事件</p>
        <h2>历史事件列表</h2>
      </div>
      <span class="rel-count">共 <b data-role="event-count">{{ total }}</b> 个</span>
    </header>

    <div class="rel-filters" data-role="event-filters">
      <div class="rel-filter-row">
        <label class="rel-field">
          <span>开始日期</span>
          <input v-model="draft.start" type="date" data-role="filter-start" aria-label="开始日期" />
        </label>
        <label class="rel-field">
          <span>结束日期</span>
          <input v-model="draft.end" type="date" data-role="filter-end" aria-label="结束日期" />
        </label>
      </div>
      <div class="rel-filter-row">
        <label class="rel-field">
          <span>类型</span>
          <select v-model="draft.type" aria-label="事件类型">
            <option value="all">全部类型</option>
            <option value="realtime">实时预警</option>
            <option value="predicted">预测预警</option>
          </select>
        </label>
        <label class="rel-field">
          <span>风险等级</span>
          <select v-model="draft.level" aria-label="风险等级">
            <option value="all">全部等级</option>
            <option value="light">黄色预警</option>
            <option value="moderate">红色告警</option>
          </select>
        </label>
        <label class="rel-field">
          <span>状态</span>
          <select v-model="draft.status" aria-label="处理状态">
            <option value="all">全部状态</option>
            <option value="closed">已关闭</option>
            <option value="revoked">已撤销</option>
            <option value="pending">待确认</option>
            <option value="acknowledged">已确认</option>
            <option value="processing">处理中</option>
            <option value="review">待复核</option>
          </select>
        </label>
      </div>
      <label class="rel-field rel-field--wide">
        <span>站点 / 编号</span>
        <input v-model.trim="draft.station" type="search" placeholder="站点名或事件编号" aria-label="搜索站点或编号" />
      </label>
      <details class="rel-advanced" data-role="advanced-filters">
        <summary>更多筛选</summary>
        <div class="rel-filter-row">
          <label class="rel-field">
            <span>采用预案</span>
            <select v-model="draft.plan_adopted" aria-label="是否采用预案">
              <option value="all">不限</option>
              <option value="yes">已采用</option>
              <option value="no">未采用</option>
            </select>
          </label>
          <label class="rel-field">
            <span>措施全部完成</span>
            <select v-model="draft.tasks_done" aria-label="措施是否全部完成">
              <option value="all">不限</option>
              <option value="yes">全部完成</option>
              <option value="no">有未完成</option>
            </select>
          </label>
          <label class="rel-field">
            <span>模拟推送失败</span>
            <select v-model="draft.push_failed" aria-label="是否存在模拟推送失败">
              <option value="all">不限</option>
              <option value="yes">存在失败</option>
              <option value="no">无失败</option>
            </select>
          </label>
        </div>
      </details>
      <div class="rel-filter-actions">
        <button type="button" class="rbtn rbtn--primary" data-role="filter-apply" @click="apply">应用</button>
        <button type="button" class="rbtn" data-role="filter-reset" @click="reset">重置</button>
        <span v-if="error" class="rel-error" role="alert">{{ error }}</span>
      </div>
    </div>

    <div v-if="state === 'loading'" class="rel-note">正在加载历史事件…</div>
    <div v-else-if="state === 'error'" class="rel-note rel-note--bad" role="alert">
      {{ errorText || '历史事件列表请求失败' }}
      <button type="button" class="rbtn" @click="$emit('retry')">重试</button>
    </div>
    <p v-else-if="!events.length" class="rel-note">
      该筛选条件下没有历史预警事件。当前事件数据自预警中心上线起积累，不做模拟补齐。
    </p>
    <ul v-else class="rel-list" data-role="event-list">
      <li v-for="e in events" :key="e.id">
        <button
          type="button"
          class="rel-item"
          :class="{ active: e.id === selectedId }"
          :data-event="e.id"
          @click="$emit('select', e.id)"
        >
          <span class="rel-item-row">
            <span class="rel-chip" :class="e.type === 'predicted' ? 'rel-chip--predicted' : 'rel-chip--realtime'">
              {{ EVENT_TYPE_TEXT[e.type] || e.type }}
            </span>
            <span class="rel-chip" :class="e.level === 'moderate' ? 'rel-chip--moderate' : 'rel-chip--light'">
              {{ levelText(e.level) }}
            </span>
            <b class="rel-item-station">{{ e.station_name }}</b>
            <span class="rel-item-no">{{ e.no }}</span>
          </span>
          <span class="rel-item-row rel-item-title">{{ e.title }}</span>
          <span class="rel-item-row rel-item-meta">
            <span class="rel-chip" :class="`rel-chip--st-${e.status}`">{{ e.status_label }}</span>
            <span class="rel-chip" :class="`rel-chip--ev-${e.evidence_state}`">{{ evidenceStateText(e.evidence_state) }}</span>
          </span>
          <span class="rel-item-row rel-item-sub">
            触发 {{ formatBeijing(e.triggered_at) }}
            · 响应 {{ formatDuration(e.response_min) }}
            · 处置 {{ e.handling_ongoing ? '进行中' : formatDuration(e.handling_min) }}
          </span>
          <span class="rel-item-row rel-item-sub">
            预案 {{ e.plan_adopted ? `已采用（任务 ${e.tasks_done}/${e.tasks_total}）` : '未采用' }}
            · 推送 {{ e.push_success }}成功/{{ e.push_failed }}失败
            <span v-if="e.push_failed > 0" class="rel-flag-bad">推送失败</span>
            <span v-if="e.escalated" class="rel-flag-warn">曾升级</span>
            <span v-if="e.recurrence_count > 0" class="rel-flag-warn">7天重复×{{ e.recurrence_count }}</span>
          </span>
        </button>
      </li>
    </ul>
  </aside>
</template>

<script setup>
// 事件复盘 · 左列：以预警事件为单位的历史列表（不再以快照为单位）。
import { reactive, ref, watch } from 'vue'
import {
  EVENT_TYPE_TEXT,
  evidenceStateText,
  formatBeijing,
  formatDuration,
  levelText
} from '../../services/historyReview.js'

const props = defineProps({
  events: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  state: { type: String, default: 'loading' },
  errorText: { type: String, default: '' },
  filters: { type: Object, required: true },
  selectedId: { type: String, default: '' }
})

const emit = defineEmits(['update:filters', 'select', 'retry'])

const draft = reactive({ ...props.filters })
const error = ref('')

watch(() => props.filters, (next) => {
  Object.assign(draft, next)
}, { deep: true })

function apply() {
  if (draft.start && draft.end && draft.start > draft.end) {
    error.value = '开始日期不能晚于结束日期'
    return
  }
  error.value = ''
  emit('update:filters', { ...draft })
}

function reset() {
  error.value = ''
  Object.assign(draft, {
    start: '', end: '', type: 'all', level: 'all', status: 'all',
    station: '', plan_adopted: 'all', tasks_done: 'all', push_failed: 'all'
  })
  emit('update:filters', { ...draft })
}
</script>

<style scoped>
.rel {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.rel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.rel-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.rel-head h2 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.rel-count {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.rel-count b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.rel-filters {
  display: grid;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.rel-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rel-field {
  display: grid;
  gap: 2px;
  min-width: 0;
  flex: 1 1 96px;
}
.rel-field--wide {
  flex: 1 1 100%;
}
.rel-field span {
  font-size: 10px;
  color: var(--text-muted);
}
.rel-field input,
.rel-field select {
  min-height: 30px;
  padding: 2px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  color: var(--text-primary);
  font-size: 12px;
  font-family: var(--font-mono);
  width: 100%;
}
.rel-field input:focus-visible,
.rel-field select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rel-advanced summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--text-secondary);
  user-select: none;
}
.rel-advanced[open] summary {
  margin-bottom: 6px;
}
.rel-filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rbtn {
  appearance: none;
  min-height: 30px;
  padding: 2px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.rbtn--primary {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}
.rbtn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rel-error {
  font-size: 11px;
  color: var(--risk-critical, #ef4444);
}
.rel-note {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  display: grid;
  gap: 8px;
  justify-items: start;
}
.rel-note--bad {
  color: var(--risk-critical, #ef4444);
}
.rel-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
  overflow-y: auto;
}
.rel-item {
  appearance: none;
  width: 100%;
  display: grid;
  gap: 3px;
  text-align: left;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  cursor: pointer;
}
.rel-item:hover {
  border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
}
.rel-item.active {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.rel-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rel-item-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}
.rel-item-station {
  font-size: 12.5px;
  color: var(--text-primary);
}
.rel-item-no {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.rel-item-title {
  font-size: 11px;
  color: var(--text-secondary);
}
.rel-item-meta {
  gap: 4px;
}
.rel-item-sub {
  font-size: 10.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.rel-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
  white-space: nowrap;
}
.rel-chip--realtime {
  border-color: color-mix(in srgb, #4da3ff 50%, transparent);
  color: #4da3ff;
}
.rel-chip--predicted {
  border-color: color-mix(in srgb, #a78bfa 50%, transparent);
  color: #a78bfa;
}
.rel-chip--light {
  border-color: color-mix(in srgb, #f5b45d 55%, transparent);
  color: #f5b45d;
}
.rel-chip--moderate {
  border-color: color-mix(in srgb, #ef4444 55%, transparent);
  color: #ef4444;
}
.rel-chip--st-closed,
.rel-chip--ev-recovered {
  border-color: color-mix(in srgb, #5fd6a4 50%, transparent);
  color: #5fd6a4;
}
.rel-chip--st-revoked,
.rel-chip--ev-unverified {
  border-color: color-mix(in srgb, #8296ab 55%, transparent);
  color: #8296ab;
}
.rel-chip--st-pending {
  border-color: color-mix(in srgb, #f5b45d 55%, transparent);
  color: #f5b45d;
}
.rel-flag-bad,
.rel-flag-warn {
  font-family: var(--font-mono);
  font-size: 10px;
  white-space: nowrap;
}
.rel-flag-bad {
  color: var(--risk-critical, #ef4444);
}
.rel-flag-warn {
  color: var(--risk-medium, #f5b45d);
}
</style>
