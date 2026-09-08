<template>
  <section class="rtl" aria-label="事件全过程时间线">
    <header class="rtl-head">
      <div>
        <p class="rtl-kicker">EVENT TIMELINE · 全过程</p>
        <h2>事件全过程时间线</h2>
      </div>
      <div class="rtl-legend" aria-label="节点颜色图例">
        <span v-for="(meta, tone) in TONE_META" :key="tone" class="rtl-legend-item">
          <i :style="{ background: meta.color }"></i>{{ meta.label }}
        </span>
      </div>
    </header>

    <p class="rtl-note">
      节点内容为当时发生的事实记录；「已关闭」只表示处置流程结束，不等于指标一定恢复。
      事件状态与证据状态分开展示。
    </p>

    <div v-if="!milestones.length" class="rtl-empty">该事件暂无时间线节点。</div>
    <ol v-else class="rtl-flow" data-role="event-timeline">
      <li v-for="(node, index) in milestones" :key="node.id" class="rtl-node" :class="{ 'rtl-node--last': index === milestones.length - 1 }">
        <span class="rtl-dot" :style="{ background: nodeColor(node) }" :data-node-kind="node.kind"></span>
        <button type="button" class="rtl-body" :data-node="node.id" @click="toggle(node.id)">
          <span class="rtl-row">
            <time class="rtl-time">{{ formatBeijing(node.at) }}</time>
            <b class="rtl-title">{{ node.title }}</b>
            <span v-if="node.actor" class="rtl-actor">{{ node.actor }}</span>
            <span class="rtl-toggle">{{ expanded === node.id ? '收起' : '当时数据' }}</span>
          </span>
          <span v-if="node.detail" class="rtl-detail">{{ node.detail }}</span>
        </button>
        <div v-if="expanded === node.id" class="rtl-snap" data-role="node-snapshot">
          <dl>
            <div>
              <dt>节点时间（北京时间）</dt>
              <dd class="rtl-mono">{{ formatBeijing(node.at) }}</dd>
            </div>
            <div v-if="node.value != null">
              <dt>当时观测值</dt>
              <dd class="rtl-mono">{{ node.value }} {{ detail?.event?.evidence?.unit || '' }}</dd>
            </div>
            <div v-if="node.snapshot_id">
              <dt>当时数据快照</dt>
              <dd class="rtl-mono">{{ node.snapshot_id }}</dd>
            </div>
            <div v-if="node.refs?.notification_id">
              <dt>关联通知</dt>
              <dd class="rtl-mono">{{ node.refs.notification_id }}</dd>
            </div>
            <div v-if="node.refs?.receipt_no">
              <dt>模拟回执编号</dt>
              <dd class="rtl-mono">{{ node.refs.receipt_no }}</dd>
            </div>
            <div v-if="!node.snapshot_id && node.value == null && !node.refs?.notification_id && !node.refs?.receipt_no">
              <dt>当时数据</dt>
              <dd>该节点为处理动作记录，无观测快照。</dd>
            </div>
          </dl>
          <button
            v-if="node.snapshot_id"
            type="button"
            class="rtl-link"
            @click="$emit('replay', node)"
          >在观测回放中查看该快照 →</button>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup>
// 事件复盘 · 中列：一次预警从发现到关闭的统一时间线。
// 节点颜色只表示性质；点击节点展示当时的数据快照（保留当时内容）。
import { ref } from 'vue'
import { TONE_META, formatBeijing, toneColor } from '../../services/historyReview.js'

const props = defineProps({
  milestones: { type: Array, default: () => [] },
  detail: { type: Object, default: null }
})

defineEmits(['replay'])

const expanded = ref('')

function toggle(id) {
  expanded.value = expanded.value === id ? '' : id
}

function nodeColor(node) {
  if (node.tone === 'risk' && typeof node.title === 'string' && node.title.includes('红色')) {
    return '#ef4444'
  }
  return toneColor(node.tone)
}
</script>

<style scoped>
.rtl {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.rtl-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.rtl-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.rtl-head h2 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.rtl-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
}
.rtl-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.rtl-legend-item i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.rtl-note {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.rtl-empty {
  font-size: 12px;
  color: var(--text-muted);
}
.rtl-flow {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0;
  overflow-y: auto;
  max-height: 560px;
}
.rtl-node {
  position: relative;
  padding: 0 0 10px 18px;
}
.rtl-node::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 14px;
  bottom: -2px;
  width: 2px;
  background: var(--border-subtle);
}
.rtl-node--last::before {
  display: none;
}
.rtl-dot {
  position: absolute;
  left: 0;
  top: 6px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--surface-panel);
  box-shadow: 0 0 0 1px var(--border-subtle);
}
.rtl-body {
  appearance: none;
  width: 100%;
  display: grid;
  gap: 2px;
  text-align: left;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}
.rtl-body:hover {
  border-color: var(--border-subtle);
  background: var(--surface-panel-soft);
}
.rtl-body:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.rtl-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.rtl-time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.rtl-title {
  font-size: 12px;
  color: var(--text-primary);
  min-width: 0;
}
.rtl-actor {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 0 6px;
}
.rtl-toggle {
  margin-left: auto;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--color-primary);
  white-space: nowrap;
}
.rtl-detail {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.rtl-snap {
  margin: 4px 0 0;
  padding: 8px 10px;
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  display: grid;
  gap: 6px;
}
.rtl-snap dl {
  margin: 0;
  display: grid;
  gap: 4px;
}
.rtl-snap dl > div {
  display: flex;
  gap: 10px;
}
.rtl-snap dt {
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.rtl-snap dd {
  margin: 0;
  font-size: 11px;
  color: var(--text-secondary);
  word-break: break-all;
}
.rtl-mono {
  font-family: var(--font-mono);
}
.rtl-link {
  appearance: none;
  justify-self: start;
  border: none;
  background: none;
  padding: 0;
  font-size: 11px;
  color: var(--color-primary);
  cursor: pointer;
}
.rtl-link:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
</style>
