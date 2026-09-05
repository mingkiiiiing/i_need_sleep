<template>
  <div class="stn-brief">
    <!-- 分区档案 -->
    <section class="stn-block stn-sec-profile" aria-label="当前分区档案">
      <header class="stn-sec-head">
        <h2>分区档案</h2>
        <span class="stn-sec-tag">{{ briefRefreshing ? '更新中…' : 'SIMULATED' }}</span>
      </header>
      <div v-if="entity" class="stn-brief-head">
        <span class="sb-code">{{ entity.short }}</span>
        <h3 class="sb-name">{{ entity.display_name }}</h3>
        <span class="sb-risk" :class="`lv-${currentRiskClass}`">{{ currentRiskText }}</span>
      </div>
      <dl v-if="entity" class="stn-kv">
        <dt>编号</dt><dd class="stn-mono">{{ entity.short }}</dd>
        <dt>名称</dt><dd>{{ entity.display_name }}</dd>
        <dt>空间对象类型</dt><dd class="stn-mono">{{ entity.entity_type }}</dd>
        <dt>数据模式</dt><dd class="stn-mono">simulated</dd>
        <dt>几何状态</dt><dd class="stn-mono">{{ entity.geometry_status }}</dd>
        <dt>数据集版本</dt><dd class="stn-mono">{{ obsVersion }} / {{ predVersion }}</dd>
      </dl>
      <StatePanel
        v-else
        :state="entityState === 'error' ? 'error' : entityState === 'loading' ? 'loading' : 'empty'"
        description="分区详情接口请求失败，可重试。"
      >
        <button type="button" class="stn-inline-btn" @click="$emit('retry-entity')">重试</button>
      </StatePanel>
    </section>

    <!-- 当前指标 -->
    <section class="stn-block stn-sec-metrics" aria-label="当前演示指标">
      <header class="stn-sec-head">
        <h2>当前指标</h2>
        <span class="stn-sec-tag">最近模拟观测</span>
      </header>
      <div v-if="obsState === 'loading'" class="stn-skel-mini" role="status" aria-label="指标加载中">
        <div class="skel-row"></div>
        <div class="skel-row short"></div>
      </div>
      <StatePanel
        v-else-if="obsState === 'error'"
        state="error"
        description="观测接口请求失败，可重试。"
      >
        <button type="button" class="stn-inline-btn" @click="$emit('retry-obs')">重试</button>
      </StatePanel>
      <p v-else-if="!latestMetrics.length" class="stn-none">暂无数据：接口未返回该分区的模拟观测。</p>
      <ul v-else class="stn-metric-list">
        <li v-for="m in latestMetrics" :key="m.code">
          <span class="sm-name">{{ m.label }}</span>
          <span class="sm-value">{{ m.valueText }}<small>{{ m.unit }}</small></span>
          <span class="sm-meta">
            {{ m.time }}
            <em class="sm-tag" :class="{ warn: m.imputed }">{{ m.imputed ? '插补值' : '未插补' }}</em>
            <em class="sm-tag">{{ m.origin }}</em>
            <em class="sm-tag">{{ m.qualityShort }}</em>
          </span>
        </li>
      </ul>
    </section>

    <!-- 数据质量 -->
    <section class="stn-block stn-sec-quality" aria-label="数据质量">
      <header class="stn-sec-head">
        <h2>数据质量</h2>
        <span class="stn-sec-tag">{{ quality ? qualityStatusLabel : '—' }}</span>
      </header>
      <div v-if="qualityState === 'loading'" class="stn-skel-mini" role="status" aria-label="质量数据加载中">
        <div class="skel-row"></div>
        <div class="skel-row short"></div>
      </div>
      <StatePanel v-else-if="qualityState === 'error'" state="error" description="质量接口请求失败，可重试。">
        <button type="button" class="stn-inline-btn" @click="$emit('retry-quality')">重试</button>
      </StatePanel>
      <template v-else-if="quality">
        <dl class="stn-kv">
          <dt>status</dt><dd class="stn-mono">{{ quality.status }}</dd>
          <dt>freshness</dt><dd class="stn-mono">{{ freshnessText }}</dd>
          <dt>observed_count</dt><dd class="stn-mono">{{ quality.observed_count }}</dd>
          <dt>source_count</dt><dd class="stn-mono">{{ quality.source_count }}</dd>
          <dt>is_imputed</dt><dd class="stn-mono">{{ quality.is_imputed ? 'true' : 'false' }}</dd>
          <dt>value_origin</dt><dd class="stn-mono">{{ quality.value_origin }}</dd>
          <dt>proxy_flag</dt><dd class="stn-mono">{{ quality.proxy_flag ? 'true' : 'false' }}</dd>
        </dl>
        <ul v-if="quality.limitations && quality.limitations.length" class="stn-limitations">
          <li v-for="lim in quality.limitations" :key="lim">{{ lim }}</li>
        </ul>
      </template>
    </section>

    <!-- 预测能力 -->
    <section class="stn-block stn-sec-forecast" aria-label="预测能力">
      <header class="stn-sec-head">
        <h2>预测能力</h2>
        <span class="stn-sec-tag">{{ stageShortLabel }}</span>
      </header>
      <div v-if="stageKey === 't30'" class="stn-forecast-blocked" role="note">
        <strong>30—90 天预测能力未就绪</strong>
        <p>当前仅允许模拟预演，不提供正式预测结论</p>
      </div>
      <template v-else>
        <div v-if="forecastState === 'loading'" class="stn-skel-mini" role="status" aria-label="预测数据加载中">
          <div class="skel-row"></div>
          <div class="skel-row short"></div>
        </div>
        <StatePanel v-else-if="forecastState === 'error'" state="error" description="预测接口请求失败，可重试。">
          <button type="button" class="stn-inline-btn" @click="$emit('retry-forecast')">重试</button>
        </StatePanel>
        <div v-else-if="forecast" class="stn-forecast">
          <div class="sf-top">
            <span class="sf-score mono">{{ forecast.risk_score }}</span>
            <span class="sb-risk" :class="`lv-${forecast.risk_level}`">{{ riskTextOf(forecast.risk_level) }}</span>
            <em class="sf-sim">SIMULATED · 仅模拟</em>
          </div>
          <dl class="stn-kv">
            <dt>不确定性区间</dt>
            <dd class="stn-mono">{{ forecast.uncertainty ? `${forecast.uncertainty.lower} ~ ${forecast.uncertainty.upper}` : '—' }}</dd>
            <dt>provider</dt><dd class="stn-mono">{{ forecast.provider_type }}</dd>
            <dt>model</dt><dd class="stn-mono">{{ forecast.model_version }}（演示规则）</dd>
            <dt>quality_gate</dt>
            <dd class="stn-mono">{{ forecast.quality_gate ? `${forecast.quality_gate.status} · ${forecast.quality_gate.decision}` : '—' }}</dd>
          </dl>
          <p v-if="forecast.quality_gate && forecast.quality_gate.reason" class="stn-gate-reason">
            质量门禁：{{ forecast.quality_gate.reason }}
          </p>
        </div>
        <p v-else class="stn-none">暂无当前档位演示预测。</p>
      </template>
    </section>

    <!-- 分区事件与模拟预警由 ZoneEventsPanel 承载（移动端需独立排序） -->
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import {
  variableLabel, RISK_TEXT, qualityText, formatStamp, formatValue
} from './stationDisplay.js'

const props = defineProps({
  entity: { type: Object, default: null },
  entityState: { type: String, default: 'loading' },
  observations: { type: Array, default: () => [] },
  obsState: { type: String, default: 'loading' },
  quality: { type: Object, default: null },
  qualityState: { type: String, default: 'loading' },
  forecast: { type: Object, default: null },
  forecastState: { type: String, default: 'loading' },
  stageKey: { type: String, default: 't7' },
  stageShortLabel: { type: String, default: '' },
  obsVersion: { type: String, default: '—' },
  predVersion: { type: String, default: '—' },
  briefRefreshing: { type: Boolean, default: false }
})

defineEmits(['retry-entity', 'retry-obs', 'retry-quality', 'retry-forecast'])

const currentRiskClass = computed(() => {
  if (props.forecast && props.forecast.risk_level) return props.forecast.risk_level
  return props.entity && props.entity.risk_hint ? props.entity.risk_hint : 'low'
})
const currentRiskText = computed(() => riskTextOf(currentRiskClass.value))

function riskTextOf(level) {
  return RISK_TEXT[level] || level
}

const qualityStatusLabel = computed(() => (props.quality ? qualityText(props.quality.status) : '—'))
const freshnessText = computed(() => {
  const f = props.quality && props.quality.freshness
  if (!f) return '—'
  return f === 'simulated' ? 'simulated（模拟样本，非实时）' : f
})

// 每个指标取最新一条观测（不拼值、不补点）
const latestMetrics = computed(() => {
  const byVar = new Map()
  props.observations.forEach((r) => {
    const prev = byVar.get(r.variable_code)
    if (!prev || Date.parse(r.observed_at) > Date.parse(prev.observed_at)) byVar.set(r.variable_code, r)
  })
  return [...byVar.values()]
    .sort((a, b) => a.variable_code.localeCompare(b.variable_code))
    .map((r) => ({
      code: r.variable_code,
      label: variableLabel(r.variable_code),
      valueText: formatValue(r.clean_value),
      unit: r.unit || '',
      time: formatStamp(r.observed_at),
      imputed: Boolean(r.is_imputed),
      origin: r.value_origin || '—',
      qualityShort: qualityText(r.quality_status)
    }))
})
</script>

<style scoped>
/* 根节点不参与布局：四个区块作为页面 grid 的独立格子参与桌面/移动排版 */
.stn-brief {
  display: contents;
}
.stn-brief-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.sb-code {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-primary);
  letter-spacing: 0.08em;
}
.sb-name {
  font-size: 15px;
  font-weight: 650;
  color: var(--text-primary);
}
.sb-risk {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  border: 1px solid transparent;
}
.sb-risk.lv-high { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, currentColor 45%, transparent); background: color-mix(in srgb, currentColor 10%, transparent); }
.sb-risk.lv-mid { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, currentColor 45%, transparent); background: color-mix(in srgb, currentColor 10%, transparent); }
.sb-risk.lv-low { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, currentColor 45%, transparent); background: color-mix(in srgb, currentColor 10%, transparent); }

.stn-none {
  font-size: 12.5px;
  color: var(--text-secondary);
  padding: 6px 0;
}

.stn-metric-list {
  display: grid;
  gap: 5px;
}
.stn-metric-list li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 10px;
  padding: 5px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 10px);
  background: var(--surface-panel-soft);
}
.sm-name { font-size: 12px; color: var(--text-secondary); }
.sm-value {
  text-align: right;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}
.sm-value small { font-size: 11px; font-weight: 500; color: var(--text-secondary); margin-left: 3px; }
.sm-meta {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 10.5px;
  color: var(--text-muted);
}
.sm-tag {
  font-style: normal;
  font-family: var(--font-mono);
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
}
.sm-tag.warn { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, currentColor 45%, transparent); }

.stn-limitations {
  margin-top: 5px;
  display: grid;
  gap: 4px;
}
.stn-limitations li {
  font-size: 11.5px;
  color: var(--text-secondary);
  padding-left: 14px;
  position: relative;
  line-height: 1.6;
}
.stn-limitations li::before {
  content: '·';
  position: absolute;
  left: 2px;
  color: var(--text-muted);
}

.stn-forecast .sf-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}
.sf-score { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.sf-sim {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--data-simulated, #f5b45d);
  border: 1px dashed color-mix(in srgb, currentColor 55%, transparent);
  border-radius: 999px;
  padding: 1px 8px;
}
.stn-gate-reason {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.stn-forecast-blocked {
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent);
  border-radius: var(--radius-item, 10px);
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 8%, transparent);
  padding: 9px 11px;
}
.stn-forecast-blocked strong { display: block; font-size: 13px; color: var(--text-primary); margin-bottom: 4px; }
.stn-forecast-blocked p { font-size: 12px; color: var(--text-secondary); line-height: 1.6; }

.stn-skel-mini { display: grid; gap: 8px; padding: 4px 0; }
</style>
