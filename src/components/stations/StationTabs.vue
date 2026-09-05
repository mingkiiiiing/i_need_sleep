<template>
  <section class="stn-block stn-tabs-block" aria-label="趋势与预测、驱动因素、数据质量">
    <div class="stn-tablist" role="tablist" aria-label="研判详情切换" @keydown="onTablistKeydown">
      <button
        v-for="(tab, i) in tabs"
        :key="tab.id"
        :id="`stn-tab-${tab.id}`"
        ref="tabRefs"
        type="button"
        role="tab"
        :aria-selected="String(active === tab.id)"
        :aria-controls="`stn-panel-${tab.id}`"
        :tabindex="active === tab.id ? 0 : -1"
        class="stn-tab"
        @click="active = tab.id"
      >{{ tab.label }}</button>
    </div>

    <!-- Tab 1：趋势与预测 -->
    <div
      v-show="active === 'trend'"
      id="stn-panel-trend"
      role="tabpanel"
      aria-labelledby="stn-tab-trend"
      tabindex="0"
      class="stn-tabpanel"
    >
      <div class="tp-grid">
        <div class="tp-col">
          <h4>模拟观测样本（接口实际返回）</h4>
          <p v-if="!observations.length" class="stn-none">暂无数据：接口未返回该分区的模拟观测。</p>
          <div v-else class="stn-table-wrap">
            <table class="stn-table">
              <caption class="sr-only">模拟观测样本明细</caption>
              <thead>
                <tr><th>时间</th><th>指标</th><th>数值</th><th>质量</th><th>来源</th><th>版本</th></tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in observations" :key="`${r.variable_code}-${r.observed_at}-${i}`">
                  <td class="stn-mono">{{ formatStamp(r.observed_at) }}</td>
                  <td>{{ variableLabel(r.variable_code) }}</td>
                  <td class="stn-mono">{{ formatValue(r.clean_value) }} {{ r.unit }}</td>
                  <td class="stn-mono">{{ r.quality_status }}</td>
                  <td class="stn-mono">{{ r.value_origin }}{{ r.is_imputed ? ' · 插补' : '' }}</td>
                  <td class="stn-mono">{{ r.dataset_version }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="tp-col">
          <h4>预测能力状态</h4>
          <div v-if="stageKey === 't30'" class="stn-forecast-blocked" role="note">
            <strong>30—90 天预测能力未就绪</strong>
            <p>当前仅允许模拟预演，不提供正式预测结论</p>
          </div>
          <template v-else-if="forecast">
            <dl class="stn-kv">
              <dt>档位</dt><dd class="stn-mono">{{ stageShortLabel }}</dd>
              <dt>演示风险分数</dt><dd class="stn-mono">{{ forecast.risk_score }}（{{ riskTextOf(forecast.risk_level) }}）</dd>
              <dt>不确定性</dt><dd class="stn-mono">{{ forecast.uncertainty ? `${forecast.uncertainty.lower} ~ ${forecast.uncertainty.upper}（${forecast.uncertainty.method}）` : '—' }}</dd>
              <dt>provider / model</dt><dd class="stn-mono">{{ forecast.provider_type }} / {{ forecast.model_version }}（演示规则）</dd>
              <dt>声明边界</dt><dd class="stn-mono">{{ forecast.claim_boundary }}</dd>
            </dl>
            <p class="tp-note">仅展示当前档位的演示预测；切换 T+1 / T+3 / T+7 / T+15 可查看对应档位，T+30 无正式预测。</p>
          </template>
          <p v-else class="stn-none">当前档位暂无演示预测。</p>
        </div>
      </div>
    </div>

    <!-- Tab 2：驱动因素 -->
    <div
      v-show="active === 'drivers'"
      id="stn-panel-drivers"
      role="tabpanel"
      aria-labelledby="stn-tab-drivers"
      tabindex="0"
      class="stn-tabpanel"
    >
      <header class="tp-head">
        <h4>演示规则贡献</h4>
        <em class="sf-sim">simulation_only · 非真实 SHAP 解释</em>
      </header>
      <div v-if="explainState === 'loading'" class="stn-skel-mini" role="status" aria-label="解释数据加载中">
        <div class="skel-row"></div>
        <div class="skel-row short"></div>
      </div>
      <StatePanel
        v-else-if="explainState === 'error'"
        state="error"
        title="解释接口不可用"
        :description="explainError || '演示规则贡献接口请求失败。算法接入状态：正式模型与真实 SHAP 解释尚未接入，当前阻塞原因见系统能力页说明。'"
      >
        <button type="button" class="stn-inline-btn" @click="$emit('retry-explain')">重试</button>
      </StatePanel>
      <template v-else-if="explanation">
        <p class="tp-note">
          以下贡献来自后端演示规则（{{ explanation.method }}），仅用于展示解释结构，不代表真实算法归因。
        </p>
        <ul class="drv-list">
          <li v-for="(f, i) in explanation.features" :key="f.name" class="drv-row">
            <span class="drv-rank mono">{{ i + 1 }}</span>
            <span class="drv-name">{{ f.label || f.name }}</span>
            <span class="drv-track" aria-hidden="true">
              <span
                class="drv-fill"
                :class="f.direction === 'negative' ? 'neg' : 'pos'"
                :style="{ width: barPct(f) + '%' }"
              ></span>
            </span>
            <span class="drv-val mono">{{ Math.round(f.contribution * 1000) / 10 }}%</span>
            <span class="drv-dir" :class="f.direction === 'negative' ? 'neg' : 'pos'">
              {{ f.direction === 'negative' ? '↓ 抑制' : '↑ 推高' }}
            </span>
          </li>
        </ul>
      </template>
      <p v-else class="stn-none">当前档位暂无演示规则解释。</p>
    </div>

    <!-- Tab 3：数据质量 -->
    <div
      v-show="active === 'quality'"
      id="stn-panel-quality"
      role="tabpanel"
      aria-labelledby="stn-tab-quality"
      tabindex="0"
      class="stn-tabpanel"
    >
      <div class="tp-grid">
        <div class="tp-col">
          <h4>质量字段（接口原始值）</h4>
          <p v-if="!quality" class="stn-none">暂无数据：质量接口未返回。</p>
          <dl v-else class="stn-kv">
            <dt>status</dt><dd class="stn-mono">{{ quality.status }}</dd>
            <dt>freshness</dt><dd class="stn-mono">{{ quality.freshness }}<span v-if="quality.freshness === 'simulated'">（模拟样本，非实时）</span></dd>
            <dt>observed_count</dt><dd class="stn-mono">{{ quality.observed_count }}</dd>
            <dt>source_count</dt><dd class="stn-mono">{{ quality.source_count }}</dd>
            <dt>is_imputed</dt><dd class="stn-mono">{{ quality.is_imputed ? 'true' : 'false' }}</dd>
            <dt>value_origin</dt><dd class="stn-mono">{{ quality.value_origin }}</dd>
            <dt>proxy_flag</dt><dd class="stn-mono">{{ quality.proxy_flag ? 'true' : 'false' }}<span v-if="quality.proxy_flag">（气温为驱动代理，非水温实测）</span></dd>
          </dl>
          <div v-if="quality && quality.limitations && quality.limitations.length" class="tp-limits">
            <h4>限制说明</h4>
            <ul>
              <li v-for="lim in quality.limitations" :key="lim">{{ lim }}</li>
            </ul>
          </div>
        </div>
        <div class="tp-col">
          <h4>数据来源与版本</h4>
          <dl class="stn-kv">
            <dt>观测数据集</dt><dd class="stn-mono">{{ obsVersion }}</dd>
            <dt>预测数据集</dt><dd class="stn-mono">{{ predVersion }}</dd>
            <dt>数据模式</dt><dd class="stn-mono">simulated</dd>
            <dt>统一基准时间</dt><dd class="stn-mono">{{ asOf || '—' }}</dd>
          </dl>
          <p class="tp-note">以上字段为接口返回的原始口径，未在前端做二次加工；数据仅用于联调演示。</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import { variableLabel, RISK_TEXT, formatStamp, formatValue } from './stationDisplay.js'

const props = defineProps({
  observations: { type: Array, default: () => [] },
  forecast: { type: Object, default: null },
  stageKey: { type: String, default: 't7' },
  stageShortLabel: { type: String, default: '' },
  quality: { type: Object, default: null },
  explanation: { type: Object, default: null },
  explainState: { type: String, default: 'loading' },
  explainError: { type: String, default: '' },
  obsVersion: { type: String, default: '—' },
  predVersion: { type: String, default: '—' },
  asOf: { type: String, default: '' }
})

defineEmits(['retry-explain'])

const tabs = [
  { id: 'trend', label: '趋势与预测' },
  { id: 'drivers', label: '驱动因素' },
  { id: 'quality', label: '数据质量' }
]
const active = ref('trend')

function barPct(f) {
  const features = (props.explanation && props.explanation.features) || []
  const max = Math.max(...features.map((x) => Math.abs(x.contribution)), 0.0001)
  return Math.max(4, Math.round((Math.abs(f.contribution) / max) * 100))
}

function riskTextOf(level) {
  return RISK_TEXT[level] || level
}

const tabRefs = ref([])

function onTablistKeydown(e) {
  const idx = tabs.findIndex((t) => t.id === active.value)
  let next = null
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = Math.min(tabs.length - 1, idx + 1)
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = Math.max(0, idx - 1)
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = tabs.length - 1
  if (next == null) return
  e.preventDefault()
  active.value = tabs[next].id
  const btn = tabRefs.value[next]
  if (btn && btn.focus) btn.focus()
}
</script>

<style scoped>
.stn-tabs-block { min-width: 0; }
.stn-tablist {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  margin-bottom: 8px;
}
.stn-tab {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 600;
  padding: 5px 16px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.stn-tab:hover { color: var(--text-primary); }
.stn-tab[aria-selected='true'] {
  background: var(--c-accent-soft, color-mix(in srgb, var(--color-primary) 14%, transparent));
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
}
.stn-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.stn-tabpanel { padding: 2px 0 4px; }
.stn-tabpanel:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 4px; border-radius: 8px; }

.tp-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
  gap: 14px;
}
@media (max-width: 960px) {
  .tp-grid { grid-template-columns: minmax(0, 1fr); }
  .stn-tab { min-height: 44px; }
}
.tp-col h4, .tp-head h4 {
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text-secondary);
  margin-bottom: 8px;
  letter-spacing: 0.04em;
}
.tp-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.sf-sim {
  font-style: normal;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--data-simulated, #f5b45d);
  border: 1px dashed color-mix(in srgb, currentColor 55%, transparent);
  border-radius: 999px;
  padding: 1px 8px;
}
.tp-note {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.7;
}
.tp-limits { margin-top: 8px; }
.tp-limits ul { display: grid; gap: 4px; }
.tp-limits li {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.6;
  padding-left: 14px;
  position: relative;
}
.tp-limits li::before { content: '·'; position: absolute; left: 2px; color: var(--text-muted); }

.drv-list { display: grid; gap: 10px; }
.drv-row {
  display: grid;
  grid-template-columns: 26px minmax(90px, 150px) minmax(0, 1fr) 56px 70px;
  align-items: center;
  gap: 10px;
}
.drv-rank { color: var(--text-muted); font-size: 12px; }
.drv-name { font-size: 12.5px; color: var(--text-primary); }
.drv-track {
  height: 8px;
  border-radius: 999px;
  background: var(--surface-panel-soft);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
}
.drv-fill { display: block; height: 100%; border-radius: 999px; }
.drv-fill.pos { background: var(--c-accent, #2bc4b4); }
.drv-fill.neg { background: var(--c-watch, #f5b45d); }
.drv-val { font-size: 12px; color: var(--text-primary); text-align: right; }
.drv-dir { font-size: 11.5px; }
.drv-dir.pos { color: var(--c-accent, #2bc4b4); }
.drv-dir.neg { color: var(--c-watch, #f5b45d); }
@media (max-width: 640px) {
  .drv-row { grid-template-columns: 22px minmax(70px, 110px) minmax(0, 1fr) 48px; }
  .drv-dir { display: none; }
}

.stn-forecast-blocked {
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent);
  border-radius: var(--radius-item, 10px);
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 8%, transparent);
  padding: 12px 14px;
}
.stn-forecast-blocked strong { display: block; font-size: 13px; color: var(--text-primary); margin-bottom: 4px; }
.stn-forecast-blocked p { font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.stn-none { font-size: 12.5px; color: var(--text-secondary); padding: 4px 0; }
.stn-skel-mini { display: grid; gap: 8px; padding: 4px 0; }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
