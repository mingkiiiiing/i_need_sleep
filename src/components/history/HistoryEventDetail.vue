<template>
  <div class="hed" data-role="event-detail-panel">
    <button type="button" class="hed-mobile-back" data-role="back-to-list" @click="$emit('back-to-list')">
      ← 返回事件列表
    </button>

    <header class="hed-head">
      <div class="hed-head-text">
        <p class="hed-kicker">EVENT DETAIL · 演示事件详情</p>
        <h2 data-role="detail-title">{{ event.title || '事件标题未提供' }}</h2>
      </div>
      <span class="hed-badge" :class="severity ? `lv-${severity}` : 'lv-none'" data-role="detail-severity">
        {{ severityText(severity) || '未提供' }}
      </span>
    </header>

    <dl class="hed-kv" data-role="detail-kv">
      <div><dt>发生时间</dt><dd data-role="detail-time">{{ timeLabel || '未提供' }}</dd></div>
      <div><dt>事件 ID</dt><dd data-role="detail-id" class="mono">{{ event.id || '—' }}</dd></div>
      <div><dt>事件类型</dt><dd data-role="detail-type">{{ typeText || '未提供' }}</dd></div>
      <div>
        <dt>关联演示分区</dt>
        <dd data-role="detail-zone">
          <template v-if="zoneName">{{ zoneName }}（{{ event.spatial_entity_id }}）</template>
          <template v-else>{{ event.spatial_entity_id || '未提供' }}</template>
          <em class="hed-zone-note">演示分区，非真实监测站</em>
        </dd>
      </div>
      <div><dt>数据模式</dt><dd data-role="detail-mode">{{ event.data_mode || '未提供' }}</dd></div>
      <div><dt>数据集版本</dt><dd data-role="detail-version">{{ meta.datasetVersion || '未提供' }}</dd></div>
      <div><dt>预测运行 ID</dt><dd data-role="detail-run">{{ event.prediction_run_id || '未提供' }}</dd></div>
      <div><dt>对应预测档位</dt><dd data-role="detail-stage">{{ stageText || '未提供' }}</dd></div>
      <div><dt>当前回放帧</dt><dd data-role="detail-frame">{{ frameSummary || '未开始回放' }}</dd></div>
    </dl>

    <section class="hed-sec">
      <h3>事件摘要</h3>
      <p data-role="detail-summary">{{ event.summary || '未提供' }}</p>
    </section>

    <section class="hed-sec">
      <h3>证据与能力边界</h3>
      <ul class="hed-missing" data-role="detail-missing">
        <li data-role="detail-trigger"><b>触发规则</b><span>接口未提供</span></li>
        <li data-role="detail-scope"><b>影响范围</b><span>接口未提供</span></li>
        <li data-role="detail-handle"><b>真实处置状态</b><span>接口未提供</span></li>
      </ul>
    </section>

    <section class="hed-sec">
      <h3>关联视图</h3>
      <div class="hed-links">
        <RouterLink
          v-if="stageKey && event.spatial_entity_id"
          class="hed-link"
          data-role="detail-link-stations"
          :to="{ path: '/stations', query: { t: stageKey, p: event.spatial_entity_id } }"
        >查看演示分区研判 →</RouterLink>
        <span v-else class="hed-link hed-link--off" aria-disabled="true">查看演示分区研判（缺少档位或分区）</span>
        <RouterLink
          v-if="stageKey && event.spatial_entity_id"
          class="hed-link"
          data-role="detail-link-heatmap"
          :to="{ path: '/heatmap', query: { t: stageKey, p: event.spatial_entity_id } }"
        >查看对应空间预演 →</RouterLink>
        <span v-else class="hed-link hed-link--off" aria-disabled="true">查看对应空间预演（缺少档位或分区）</span>
      </div>
    </section>

    <section class="hed-sec">
      <h3>模拟发送预警（演示）</h3>
      <p class="hed-gate" data-role="warn-gate">
        仅高风险演示事件可发起模拟发送；真实预警通道未启用。
      </p>
      <div class="hed-actions">
        <button
          type="button"
          class="hed-warn-btn"
          data-role="warn-trigger"
          :disabled="!canWarn"
          :aria-disabled="String(!canWarn)"
          @click="$emit('open-warning')"
        >
          模拟发送预警
          <small v-if="!canWarn">仅高风险（high）演示事件可发起</small>
        </button>
        <button
          type="button"
          class="hed-record-btn"
          data-role="dispatch-record"
          disabled
          aria-disabled="true"
          title="后端持久化能力未接入，无法查看处置记录"
        >查看处置记录 · 未接入</button>
      </div>
      <p v-if="dispatchResult" class="hed-result" data-role="dispatch-result" role="status">
        模拟发送结果：<b>{{ dispatchResult.status }}</b> · 渠道 {{ (dispatchResult.channels || []).join('、') || '—' }} ·
        事件 {{ dispatchResult.event_id }} · {{ dispatchResult.data_mode }}。
        该结果<b>未形成持久化处置记录</b>，仅本次会话展示。
      </p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { eventTypeText, eventTimeLabel, severityText, stageLabelOf } from './historyCore.js'

const props = defineProps({
  event: { type: Object, required: true },
  zoneName: { type: String, default: '' },
  meta: { type: Object, default: () => ({ datasetVersion: '', claimBoundary: '' }) },
  frameSummary: { type: String, default: '' },
  canWarn: { type: Boolean, default: false },
  dispatchResult: { type: Object, default: null }
})

defineEmits(['open-warning', 'back-to-list'])

const severity = computed(() => props.event.severity || '')
const timeLabel = computed(() => eventTimeLabel(props.event))
const typeText = computed(() => eventTypeText(props.event.event_type))
const stageKey = computed(() => (typeof props.event.stageKey === 'string' ? props.event.stageKey : ''))
const stageText = computed(() => stageLabelOf(stageKey.value))
</script>

<style scoped>
.hed {
  display: grid;
  gap: 14px;
  min-width: 0;
}
.hed-mobile-back {
  display: none;
  appearance: none;
  min-height: 44px;
  padding: 8px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  justify-self: start;
}
.hed-mobile-back:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hed-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.hed-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.hed-head h2 {
  margin: 0;
  font-family: var(--font-display, inherit);
  font-size: 18px;
  color: var(--text-primary);
  line-height: 1.3;
}
.hed-badge {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.lv-high { color: var(--risk-critical, #ef4444); border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent); }
.lv-mid { color: var(--risk-medium, #facc15); border: 1px solid color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent); }
.lv-low { color: var(--risk-low, #22c55e); border: 1px solid color-mix(in srgb, var(--risk-low, #22c55e) 50%, transparent); }
.lv-none { color: var(--text-muted); border: 1px dashed var(--border-subtle); }

.hed-kv {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 18px;
}
.hed-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}
.hed-kv dt {
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hed-kv dd {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary);
  text-align: right;
  min-width: 0;
}
.hed-kv dd.mono,
.mono {
  font-family: var(--font-mono);
  word-break: break-all;
}
.hed-zone-note {
  display: block;
  font-style: normal;
  font-size: 9.5px;
  color: var(--text-muted);
}

.hed-sec {
  display: grid;
  gap: 7px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-subtle);
}
.hed-sec h3 {
  margin: 0;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.hed-sec p {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.hed-missing {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 5px;
}
.hed-missing li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px;
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
}
.hed-missing b {
  font-size: 11.5px;
  color: var(--text-secondary);
}
.hed-missing span {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.hed-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.hed-link {
  display: inline-flex;
  align-items: center;
  min-height: 36px;
  padding: 4px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}
a.hed-link:hover {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  color: var(--color-primary);
}
.hed-link--off {
  color: var(--text-muted);
  cursor: not-allowed;
}
.hed-gate {
  font-size: 11px;
  color: var(--text-muted);
}
.hed-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 10px;
}
.hed-warn-btn {
  appearance: none;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-height: 44px;
  padding: 6px 16px;
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--risk-critical, #ef4444) 10%, transparent);
  color: var(--risk-critical, #ef4444);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
.hed-warn-btn small {
  font-size: 9px;
  font-weight: 500;
  color: var(--text-muted);
}
.hed-warn-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.hed-warn-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hed-record-btn {
  appearance: none;
  min-height: 44px;
  padding: 6px 14px;
  border: 1px dashed var(--border-subtle);
  border-radius: 9px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: not-allowed;
}
.hed-result {
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-secondary);
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  padding: 7px 10px;
}
.hed-result b {
  color: var(--text-primary);
  font-family: var(--font-mono);
}

@media (max-width: 960px) {
  .hed-mobile-back {
    display: inline-flex;
  }
  .hed-kv {
    grid-template-columns: minmax(0, 1fr);
  }
  .hed-kv > div {
    flex-direction: column;
    gap: 2px;
  }
  .hed-kv dd {
    text-align: left;
  }
  .hed-link {
    min-height: 44px;
  }
}
</style>
