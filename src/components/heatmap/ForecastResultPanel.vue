<template>
  <div class="frp">
    <div class="frp-tabs" role="tablist" aria-label="预测结果视图切换">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        role="tab"
        class="frp-tab"
        :class="{ active: activeTab === tab.key }"
        :aria-selected="String(activeTab === tab.key)"
        :data-role="`result-tab-${tab.key}`"
        @click="activeTab = tab.key"
      >{{ tab.label }}</button>
    </div>

    <!-- 站点环比变化摘要（实测参考，非预测内容）：图层开启时显示 -->
    <div v-if="diffEnabled" class="frp-diff" data-role="panel-diff-summary" aria-label="站点环比变化摘要">
      <div class="frp-diff-head">
        <b>实测环比参考</b>
        <span>相对上一快照 {{ diffBaseTime }} · 红升绿降</span>
      </div>
      <p class="frp-diff-counts" data-role="panel-diff-counts">
        <b class="frp-diff-up">↑ {{ diffSummary.up }} 站</b>
        <b class="frp-diff-down">↓ {{ diffSummary.down }} 站</b>
        <span>持平/缺测 {{ diffSummary.flat }} 站</span>
      </p>
      <ul v-if="diffSummary.top.length" class="frp-diff-list" data-role="panel-diff-top">
        <li v-for="r in diffSummary.top" :key="r.id">
          <i :class="r.delta > 0 ? 'frp-diff-dot--up' : 'frp-diff-dot--down'" aria-hidden="true"></i>
          <span class="frp-diff-name">{{ r.name }}</span>
          <span class="frp-diff-delta" :class="r.delta > 0 ? 'frp-diff-up' : 'frp-diff-down'">
            {{ r.delta > 0 ? '+' : '' }}{{ r.delta }} μg/L
          </span>
        </li>
      </ul>
      <p v-else class="frp-note">相邻两快照暂无可对比的叶绿素 a 报数，暂无升降可标。</p>
    </div>

    <!-- ===== 结果总览 ===== -->
    <div v-if="activeTab === 'overview'" class="frp-body" role="tabpanel" aria-label="结果总览" data-role="result-overview">
      <div class="frp-object">
        <span class="frp-object-name">{{ scope === 'station' ? stationName : '全湖' }}</span>
        <span class="frp-object-tag">{{ stop ? stop.title : '—' }}</span>
        <button
          v-if="scope === 'station'"
          type="button"
          class="frp-back"
          data-role="back-to-lake"
          @click="$emit('back-to-lake')"
        >返回全湖结果</button>
      </div>
      <p v-if="stop && stop.sub" class="frp-stop-sub">{{ stop.sub }}</p>

      <StatePanel
        v-if="modelState === 'loading'"
        state="loading"
        title="正在运行 63 模型交付包…"
        description="读取 MEE 最新快照并执行当前时效的 9 个任务模型。"
      />
      <StatePanel
        v-else-if="modelState === 'error' || !modelForecast"
        state="error"
        title="算法模型暂不可用"
        :description="modelError || '模型运行包或实时输入不可用。'"
      >
        <button type="button" class="frp-inline-btn" data-role="model-retry" @click="$emit('retry-model')">重试模型</button>
      </StatePanel>
      <template v-else>
        <span class="frp-metric-tag" data-role="metric-tag">当前指标：{{ metricLabel }}</span>
        <div class="frp-risk frp-risk--focus" data-role="model-primary-result">
          <b>{{ primaryPrediction }}</b>
          <span>算法交付包 V0.2 · T+{{ modelForecast.horizon_days }} · 情景推演</span>
        </div>
        <p class="frp-note frp-warn">{{ modelForecast.quality_gate.reason }}</p>

        <h4 class="frp-sub-h">本次模型输出 <span>9 任务同一时效</span></h4>
        <dl class="frp-kv" data-role="model-results">
          <div><dt>风险等级 / 概率</dt><dd>{{ riskLevelText }} / {{ resultValue('probability', 1, true) }}</dd></div>
          <div><dt>叶绿素 a</dt><dd>{{ resultValue('chla', 3) }}</dd></div>
          <div><dt>水华面积</dt><dd>{{ resultValue('area', 4) }}</dd></div>
          <div><dt>水华覆盖率</dt><dd>{{ resultValue('coverage', 2, true) }}</dd></div>
          <div><dt>蓝藻密度</dt><dd>{{ resultValue('density', 0) }}</dd></div>
          <div><dt>蓝藻生物量</dt><dd>{{ resultValue('biomass', 4) }}</dd></div>
        </dl>

        <h4 class="frp-sub-h">输入衔接与追踪</h4>
        <dl class="frp-kv" data-role="model-provenance">
          <div><dt>MEE 实测输入字段</dt><dd>{{ modelForecast.input_provenance.observed_feature_count }} 个</dd></div>
          <div><dt>冻结预处理器插补</dt><dd>{{ modelForecast.input_provenance.imputed_feature_count }} 个</dd></div>
          <div><dt>快照</dt><dd>{{ modelForecast.scope.snapshot_id }}</dd></div>
          <div><dt>运行 ID</dt><dd>{{ modelForecast.prediction_run_id }}</dd></div>
          <div><dt>当前选中模型</dt><dd>{{ focusedResult?.selected_model || '—' }}</dd></div>
          <div><dt>融合提升 ≥10%</dt><dd :class="{ 'frp-warn': modelForecast.acceptance?.status !== 'PASS' }">{{ modelForecast.acceptance?.status || '—' }}（{{ modelForecast.acceptance?.pass ?? 0 }}/{{ modelForecast.acceptance?.comparison_rows ?? 0 }}）</dd></div>
        </dl>
        <p class="frp-note">{{ modelForecast.input_provenance.note }}</p>
      </template>

      <template v-if="scope === 'station'">
        <h4 class="frp-sub-h">站点最新关键观测 <span>{{ stationObservedAt }}</span></h4>
        <dl v-if="stationKeyRows.length" class="frp-kv" data-role="station-obs">
          <div v-for="row in stationKeyRows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd :class="{ 'frp-miss': row.miss }">{{ row.text }}</dd>
          </div>
        </dl>
      </template>
      <template v-else>
        <h4 class="frp-sub-h">MEE 最新实测参考</h4>
        <dl class="frp-kv" data-role="observed-inputs">
          <div><dt>叶绿素 a 现状</dt><dd>{{ inputs.chlaText }}<i v-if="inputs.chlaTrend" class="frp-trend">{{ inputs.chlaTrend }}</i></dd></div>
          <div><dt>水温</dt><dd>{{ inputs.tempText }}</dd></div>
          <div><dt>总磷 / 总氮</dt><dd>{{ inputs.nutrientText }}</dd></div>
        </dl>
      </template>

      <p v-if="!diffEnabled" class="frp-note" data-role="panel-diff-hint">
        实测参考：开启左侧「站点环比变化」图层，可对比上一快照各站升降，此处将显示变化摘要。
      </p>
    </div>

    <!-- ===== 驱动因素 ===== -->
    <div v-else-if="activeTab === 'drivers'" class="frp-body" role="tabpanel" aria-label="驱动因素" data-role="result-drivers">
      <div class="frp-method">
        <b>当前口径：局部单因素敏感性</b>
        <span>{{ modelExplanation?.note || '当前模型解释未返回。' }}</span>
      </div>

      <template v-if="modelFactors.length">
        <h4 class="frp-sub-h">关键驱动因子（按绝对响应贡献排序）</h4>
        <ul class="frp-bars" data-role="driver-bars">
          <li v-for="f in modelFactors" :key="f.feature">
            <span class="frp-bar-label">{{ f.label }}</span>
            <span class="frp-bar-track">
              <i class="frp-bar-warm" :style="{ width: barWidth(f.contribution_percent) }"></i>
            </span>
            <span class="frp-bar-value">{{ Number(f.baseline).toLocaleString('zh-CN', { maximumFractionDigits: 3 }) }}<small>{{ f.direction === 'increase' ? '↑' : f.direction === 'decrease' ? '↓' : '→' }} {{ f.contribution_percent }}%</small></span>
          </li>
        </ul>
        <p class="frp-note">条长 = 因子 ±10% 扰动引起的绝对模型响应占比；右侧为基线值和响应方向。</p>
      </template>
      <p v-else class="frp-empty" data-role="drivers-empty">
        当前任务没有可量化的连续敏感性结果。
      </p>

      <template v-if="unavailableFactors.length">
        <h4 class="frp-sub-h">当前冻结特征契约缺口</h4>
        <ul class="frp-neutral" data-role="driver-neutral">
          <li v-for="n in unavailableFactors" :key="n.feature">
            <b>{{ n.label }}</b>
            <span>{{ n.action }}</span>
          </li>
        </ul>
      </template>
    </div>

    <!-- ===== 不确定性 ===== -->
    <div v-else class="frp-body" role="tabpanel" aria-label="不确定性" data-role="result-uncertainty">
      <div v-if="modelUncertainty" class="frp-method" data-role="uncertainty-result">
        <b>输入扰动情景分布 · {{ modelUncertainty.sample_count }} 次</b>
        <span>{{ modelUncertainty.note }}</span>
      </div>
      <dl v-if="modelUncertainty?.p50 != null" class="frp-kv" data-role="uncertainty-quantiles">
        <div><dt>P05</dt><dd>{{ uncertaintyValue(modelUncertainty.p05) }}</dd></div>
        <div><dt>P50（中位数）</dt><dd>{{ uncertaintyValue(modelUncertainty.p50) }}</dd></div>
        <div><dt>P95</dt><dd>{{ uncertaintyValue(modelUncertainty.p95) }}</dd></div>
        <div><dt>标准差</dt><dd>{{ uncertaintyValue(modelUncertainty.std) }}</dd></div>
      </dl>
      <p v-else class="frp-empty">当前任务未返回连续量分位数。</p>
      <!-- V0.3 split-conformal 区间：真实测试残差校准（与 V0.2 输入扰动情景分布严格区分） -->
      <template v-if="v3Uncertainty">
        <div class="frp-method" data-role="v3-conformal-result">
          <b>V0.3 conformal 校准区间（split-conformal 残差分位）</b>
          <span>
            校准样本 {{ v3Uncertainty.coverage?.calibration_n ?? '—' }} · 目标覆盖率 90%
            <template v-if="v3Uncertainty.coverage?.empirical_coverage_test != null">
              · 冻结测试集经验覆盖率 {{ (Number(v3Uncertainty.coverage.empirical_coverage_test) * 100).toFixed(1) }}%（n={{ v3Uncertainty.coverage.test_n }}）
            </template>
            <template v-else>· 冻结测试集样本不足，经验覆盖率未核算</template>
          </span>
        </div>
        <dl class="frp-kv" data-role="v3-conformal-quantiles">
          <div><dt>P05</dt><dd>{{ conformalValue(v3Uncertainty.p05) }}</dd></div>
          <div><dt>点预测</dt><dd>{{ conformalPoint }}</dd></div>
          <div><dt>P95</dt><dd>{{ conformalValue(v3Uncertainty.p95) }}</dd></div>
        </dl>
        <p class="frp-note">
          该区间由训练/验证残差分位数校准，经冻结测试集（≥2024-01）经验核算；与上方输入扰动情景分布口径不同，不得混用。
        </p>
      </template>
      <div class="frp-blocked">
        <b>统计置信区间仍未达成</b>
        <span>当前结果量化的是输入变化下的模型响应；交付包没有真实测试残差区间校准器，因此页面不会把 P05—P95 情景范围写成置信区间。</span>
      </div>
    </div>
  </div>
</template>

<script setup>
// 时空推演右侧预测结果面板：结果总览 / 驱动因素 / 不确定性 三标签。
// 63 bundle 数值预测、局部敏感性和输入扰动情景分布已接入。
import { computed, ref, watch } from 'vue'
import StatePanel from '../common/StatePanel.vue'

const props = defineProps({
  scope: { type: String, default: 'lake' }, // lake | station
  stationName: { type: String, default: '' },
  // 选中预测时刻 { title, sub }
  stop: { type: Object, default: null },
  // 预测指标重点：risk | chla
  metric: { type: String, default: 'risk' },
  // 全湖规则研判结果（riskAssessment.assess* 输出）
  assessment: { type: Object, default: null },
  // 站点规则研判结果（assessStationFactors 输出）
  stationAssessment: { type: Object, default: null },
  // 站点最新观测行（observed）
  stationRows: { type: Array, default: () => [] },
  // 全湖指标输入文本 { chlaText, chlaTrend, tempText, nutrientText }
  inputs: { type: Object, default: () => ({}) },
  // 站点环比变化摘要（实测参考）：左侧「站点环比变化」图层开启时显示
  diffEnabled: { type: Boolean, default: false },
  // { up, down, flat, top: [{ id, name, delta }] }
  diffSummary: { type: Object, default: () => ({ up: 0, down: 0, flat: 0, top: [] }) },
  diffBaseTime: { type: String, default: '上一快照' },
  // MEE 实时观测汇总加载中：研判未生成时显示加载态而非错误态
  summaryLoading: { type: Boolean, default: false },
  modelForecast: { type: Object, default: null },
  modelState: { type: String, default: 'loading' },
  modelError: { type: String, default: '' },
  // V0.3 真实数据包同时效预测（月度标签粒度 + conformal 区间）；null 时隐藏 V0.3 板块
  v3Forecast: { type: Object, default: null }
})

defineEmits(['back-to-lake', 'retry', 'retry-model'])

const TABS = [
  { key: 'overview', label: '结果总览' },
  { key: 'drivers', label: '驱动因素' },
  { key: 'uncertainty', label: '不确定性' }
]
const activeTab = ref('overview')

const METRIC_LABELS = { risk: '风险等级', chla: '叶绿素 a', area: '水华面积', biomass: '蓝藻生物量' }
const metricLabel = computed(() => METRIC_LABELS[props.metric] || props.metric)
// V0.3 口径：情景推演锁定（30/60/90 天）与 conformal 区间
const v3Scenario = computed(() => {
  const v3 = props.v3Forecast
  if (!v3) return false
  return Boolean(v3.results?.probability?.compliance?.locked) || Number(v3.horizon_days) >= 30
})
const v3Uncertainty = computed(() => {
  const u = props.v3Forecast?.results?.probability?.uncertainty
  return u && u.is_calibrated_confidence_interval ? u : null
})
const conformalPoint = computed(() => {
  const raw = props.v3Forecast?.results?.probability?.value
  const num = Number(raw)
  return Number.isFinite(num) ? num.toLocaleString('zh-CN', { maximumFractionDigits: 3 }) : '—'
})
function conformalValue(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}
const riskLevelText = computed(() => {
  const value = props.modelForecast?.results?.risk_level?.value
  return ({ none: '无', low: '低', medium: '中', high: '高' })[value] || value || '—'
})
function resultValue(key, digits = 2, percent = false) {
  const item = props.modelForecast?.results?.[key]
  const raw = item?.value
  if (raw == null || Number.isNaN(Number(raw))) return '—'
  const numeric = Number(raw) * (percent ? 100 : 1)
  const unit = percent ? '%' : (item.unit || '')
  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: digits })}${unit ? ` ${unit}` : ''}`
}
const primaryPrediction = computed(() => {
  if (props.metric === 'risk') return `${riskLevelText.value} · ${resultValue('probability', 1, true)}`
  const digits = props.metric === 'area' || props.metric === 'biomass' ? 4 : 3
  return resultValue(props.metric, digits)
})

// 切换对象时回到总览，避免停留在旧上下文的标签
watch(() => [props.scope, props.stationName], () => {
  activeTab.value = 'overview'
})

const focusedResult = computed(() => {
  const key = props.modelForecast?.analysis_focus?.result_key
  return key ? props.modelForecast?.results?.[key] : null
})
const modelExplanation = computed(() => focusedResult.value?.explainability || null)
const modelFactors = computed(() => (modelExplanation.value?.factors || []).slice(0, 8))
const unavailableFactors = computed(() => modelExplanation.value?.unavailable_factors || [])
const modelUncertainty = computed(() => focusedResult.value?.uncertainty || null)
const maxContribution = computed(() =>
  modelFactors.value.reduce((m, f) => Math.max(m, f.contribution_percent), 0) || 1
)
function barWidth(v) {
  return `${Math.max(4, Math.round((v / maxContribution.value) * 100))}%`
}
function uncertaintyValue(value) {
  if (value == null) return '—'
  const unit = props.metric === 'risk' ? '%' : (focusedResult.value?.unit || '')
  const numeric = Number(value) * (props.metric === 'risk' ? 100 : 1)
  return `${numeric.toLocaleString('zh-CN', { maximumFractionDigits: 4 })}${unit ? ` ${unit}` : ''}`
}

const STATION_KEY_VARS = [
  { code: 'chlorophyll_a', label: '叶绿素 a', unit: 'μg/L' },
  { code: 'water_temperature', label: '水温', unit: '℃' },
  { code: 'total_phosphorus', label: '总磷', unit: 'mg/L' },
  { code: 'total_nitrogen', label: '总氮', unit: 'mg/L' },
  { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L' },
  { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L' }
]

const stationKeyRows = computed(() => {
  if (!props.stationRows.length) return []
  const byCode = {}
  props.stationRows.forEach((row) => {
    const prev = byCode[row.variable_code]
    if (!prev || String(row.observed_at) > String(prev.observed_at)) byCode[row.variable_code] = row
  })
  return STATION_KEY_VARS.map(({ code, label, unit }) => {
    const row = byCode[code]
    const ok = row && row.observation_status === 'ok' && row.value != null
    return {
      label,
      text: ok ? `${row.value} ${unit}` : '缺测',
      miss: !ok
    }
  })
})

const stationObservedAt = computed(() => {
  const times = props.stationRows.map((r) => r.observed_at).filter(Boolean).sort()
  if (!times.length) return ''
  const m = String(times[times.length - 1]).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `观测 ${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : ''
})
</script>

<style scoped>
.frp {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.frp-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  align-self: flex-start;
}
.frp-tab {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 32px;
  padding: 4px 13px;
  border-radius: 999px;
  cursor: pointer;
}
.frp-tab.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.frp-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-body {
  display: grid;
  gap: 9px;
  align-content: start;
}

.frp-object {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
}
.frp-object-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}
.frp-object-tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-primary);
}
.frp-back {
  appearance: none;
  margin-left: auto;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  min-height: 28px;
  cursor: pointer;
}
.frp-back:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-stop-sub {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.frp-sub-h {
  margin: 2px 0 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}
.frp-sub-h span {
  font-size: 10px;
  font-weight: 500;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.frp-risk {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
}
.frp-risk b {
  font-size: 14px;
}
.frp-risk span {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}
.frp-risk--high {
  border-color: color-mix(in srgb, #ef4444 55%, transparent);
  background: color-mix(in srgb, #ef4444 10%, transparent);
}
.frp-risk--high b { color: #ef4444; }
.frp-risk--secondary {
  opacity: 0.88;
}
.frp-risk--focus b {
  font-size: 18px;
  font-family: var(--font-mono);
}
.frp-metric-tag {
  justify-self: start;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--color-primary);
  border: 1px solid color-mix(in srgb, var(--color-primary) 40%, transparent);
  border-radius: 999px;
  padding: 2px 9px;
}
.frp-risk--mid {
  border-color: color-mix(in srgb, #f5b45d 55%, transparent);
  background: color-mix(in srgb, #f5b45d 10%, transparent);
}
.frp-risk--mid b { color: #f5b45d; }
.frp-risk--low {
  border-color: color-mix(in srgb, #5fd6a4 55%, transparent);
  background: color-mix(in srgb, #5fd6a4 10%, transparent);
}
.frp-risk--low b { color: #5fd6a4; }

.frp-kv {
  margin: 0;
  display: grid;
  gap: 4px;
}
.frp-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.frp-kv dt {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.frp-kv dd {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  text-align: right;
  word-break: break-all;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.frp-trend {
  font-style: normal;
  color: var(--risk-medium, #f5b45d);
}
.frp-miss {
  color: var(--text-muted) !important;
}
.frp-row--blocked dt {
  color: var(--text-muted);
}
.frp-blocked-chip {
  font-size: 10px !important;
  font-family: inherit !important;
  color: var(--text-muted) !important;
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 1px 8px;
}

.frp-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}

/* ---------- 站点环比变化摘要（实测参考） ---------- */
.frp-diff {
  display: grid;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
}
.frp-diff-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.frp-diff-head b {
  font-size: 12px;
  color: var(--text-primary);
}
.frp-diff-head span {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.frp-diff-counts {
  margin: 0;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11.5px;
}
.frp-diff-counts > span {
  font-size: 10.5px;
  color: var(--text-muted);
}
.frp-diff-up { color: var(--risk-critical, #ef4444); }
.frp-diff-down { color: var(--risk-low, #5fd6a4); }
.frp-diff-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.frp-diff-list li {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
}
.frp-diff-list i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 5px currentColor;
}
.frp-diff-dot--up { background: #ef4444; color: #ef4444; }
.frp-diff-dot--down { background: #5fd6a4; color: #5fd6a4; }
.frp-diff-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.frp-diff-delta {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.frp-empty {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

.frp-scenario {
  display: grid;
  gap: 3px;
  border: 1px solid color-mix(in srgb, #38bdf8 45%, transparent);
  border-radius: 10px;
  padding: 8px 10px;
  background: color-mix(in srgb, #38bdf8 8%, transparent);
}
.frp-scenario > b {
  font-size: 12px;
  color: #38bdf8;
}
.frp-scenario > span {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.frp-blocked {
  display: grid;
  gap: 3px;
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent);
  border-radius: 10px;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 5%, transparent);
}
.frp-blocked > b {
  font-size: 12px;
  color: var(--risk-medium, #f5b45d);
}
.frp-blocked > span {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.frp-blocked ul {
  margin: 2px 0 0;
  padding-left: 16px;
  display: grid;
  gap: 3px;
}
.frp-blocked li {
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}
.frp-blocked li b {
  color: var(--text-primary);
}

.frp-method {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 7px 10px;
  background: var(--surface-panel-soft);
}
.frp-method b {
  font-size: 12px;
  color: var(--text-primary);
}
.frp-method span {
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--text-muted);
}

.frp-bars {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.frp-bars li {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.frp-bar-label {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.frp-bar-track {
  height: 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text-muted, #7d93a8) 16%, transparent);
  overflow: hidden;
}
.frp-bar-warm {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(to right, color-mix(in srgb, #f5b45d 70%, transparent), #ef4444);
}
.frp-bar-value {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-primary);
  white-space: nowrap;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.frp-bar-value small {
  color: var(--risk-critical, #ef4444);
  font-weight: 700;
}

.frp-neutral {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.frp-neutral li {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 10.5px;
  line-height: 1.5;
}
.frp-neutral b {
  font-weight: 600;
  color: var(--color-primary);
  white-space: nowrap;
  font-family: var(--font-mono);
}
.frp-neutral span {
  color: var(--text-muted);
}

.frp-plan {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 4px;
}
.frp-plan li {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.frp-caliber {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.frp-caliber summary {
  padding: 7px 10px;
  cursor: pointer;
  font-size: 11.5px;
  font-weight: 650;
  color: var(--text-secondary);
  min-height: 34px;
  display: flex;
  align-items: center;
}
.frp-caliber summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.frp-caliber p {
  margin: 0;
  padding: 0 10px 9px;
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--text-muted);
}

.frp-inline-btn {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 4px 12px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.frp-inline-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

@media (max-width: 759px) {
  .frp-tab {
    min-height: 44px;
  }
}
</style>
