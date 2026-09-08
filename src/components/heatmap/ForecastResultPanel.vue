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

      <!-- 站点视图 -->
      <template v-if="scope === 'station'">
        <div class="frp-blocked" data-role="station-forecast-blocked">
          <b>站点级数值预测未接入</b>
          <span>该站点当前无法生成模型预测；正式模型接入前不提供模拟值。</span>
        </div>
        <h4 class="frp-sub-h">所在区域（全湖）规则研判 <span>非站点预测</span></h4>
        <div v-if="assessment" class="frp-risk" :class="`frp-risk--${assessment.code}`" data-role="risk-level">
          <b>{{ assessment.text }}</b>
          <span>研判分 {{ assessment.score }}/100 · 规则研判</span>
        </div>
        <h4 class="frp-sub-h">站点最新关键观测 <span>{{ stationObservedAt }}</span></h4>
        <dl v-if="stationKeyRows.length" class="frp-kv" data-role="station-obs">
          <div v-for="row in stationKeyRows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd :class="{ 'frp-miss': row.miss }">{{ row.text }}</dd>
          </div>
        </dl>
        <p v-else class="frp-empty">站点观测加载中或暂无数据。</p>
      </template>

      <!-- 全湖视图 -->
      <template v-else>
        <span class="frp-metric-tag" data-role="metric-tag">当前指标：{{ metric === 'chla' ? '叶绿素 a 浓度' : '风险等级' }}</span>
        <!-- 叶绿素重点：现状块前置 -->
        <template v-if="metric === 'chla'">
          <h4 class="frp-sub-h">叶绿素 a 研判重点</h4>
          <div class="frp-risk frp-risk--focus" data-role="chla-focus">
            <b>{{ inputs.chlaText }}<i v-if="inputs.chlaTrend" class="frp-trend"> {{ inputs.chlaTrend }}</i></b>
            <span>现状均值 · 全湖</span>
          </div>
          <p class="frp-note">叶绿素 a 未来浓度数值预测未接入；以下风险研判由现状与趋势规则推导。</p>
        </template>
        <div v-if="assessment" class="frp-risk" :class="[`frp-risk--${assessment.code}`, { 'frp-risk--secondary': metric === 'chla' }]" data-role="risk-level">
          <b>{{ assessment.text }}</b>
          <span>研判分 {{ assessment.score }}/100 · 规则研判</span>
        </div>
        <StatePanel
          v-if="!assessment && summaryLoading"
          state="loading"
          title="正在获取 MEE 实时观测…"
          description="观测数值就绪后自动生成研判。"
        />
        <StatePanel
          v-else-if="!assessment"
          state="error"
          title="观测数据暂不可用"
          description="已自动重试多次仍失败；研判仅由 MEE 实时观测推导，不回退模拟。"
        >
          <button type="button" class="frp-inline-btn" data-role="risk-retry" @click="$emit('retry')">重试</button>
        </StatePanel>

        <h4 class="frp-sub-h">指标研判明细</h4>
        <dl class="frp-kv" data-role="metric-rows">
          <div>
            <dt>叶绿素 a 现状</dt>
            <dd>{{ inputs.chlaText }}<i v-if="inputs.chlaTrend" class="frp-trend">{{ inputs.chlaTrend }}</i></dd>
          </div>
          <div><dt>水温</dt><dd>{{ inputs.tempText }}</dd></div>
          <div><dt>总磷 / 总氮</dt><dd>{{ inputs.nutrientText }}</dd></div>
          <div class="frp-row--blocked">
            <dt>水华面积</dt>
            <dd class="frp-blocked-chip">数值模型待接入</dd>
          </div>
          <div class="frp-row--blocked">
            <dt>蓝藻生物量</dt>
            <dd class="frp-blocked-chip">数值模型待接入</dd>
          </div>
        </dl>
      </template>

      <p v-if="!diffEnabled" class="frp-note" data-role="panel-diff-hint">
        实测参考：开启左侧「站点环比变化」图层，可对比上一快照各站升降，此处将显示变化摘要。
      </p>
    </div>

    <!-- ===== 驱动因素 ===== -->
    <div v-else-if="activeTab === 'drivers'" class="frp-body" role="tabpanel" aria-label="驱动因素" data-role="result-drivers">
      <div class="frp-method">
        <b>当前口径：规则贡献度排序</b>
        <span>{{ scope === 'station' ? '站点最新实测逐项计分（透明阈值）' : '全湖规则研判的因子得分贡献' }}；非 SHAP / 注意力 / 敏感性等模型解释。</span>
      </div>

      <template v-if="activeFactors.length">
        <h4 class="frp-sub-h">推高风险的因子（按贡献排序）</h4>
        <ul class="frp-bars" data-role="driver-bars">
          <li v-for="f in activeFactors" :key="f.name + f.label">
            <span class="frp-bar-label">{{ f.label }}</span>
            <span class="frp-bar-track">
              <i class="frp-bar-warm" :style="{ width: barWidth(f.contribution) }"></i>
            </span>
            <span class="frp-bar-value">{{ f.value }}<small>+{{ f.contribution }}</small></span>
          </li>
        </ul>
        <p class="frp-note">条长 = 该因子对研判分的贡献点数（满分 100）；右侧为原始输入值。</p>
      </template>
      <p v-else class="frp-empty" data-role="drivers-empty">
        {{ scope === 'station' ? '站点观测不足，暂无可排序的驱动因子。' : '观测数据不足，暂无可排序的驱动因子。' }}
      </p>

      <template v-if="activeNeutral.length">
        <h4 class="frp-sub-h">抑制 / 中性 / 缺测</h4>
        <ul class="frp-neutral" data-role="driver-neutral">
          <li v-for="(n, i) in activeNeutral" :key="i">
            <b>{{ n.label }} {{ n.value }}</b>
            <span>{{ n.note }}</span>
          </li>
        </ul>
      </template>

      <div class="frp-blocked" data-role="model-explain-blocked">
        <b>模型解释能力未接入</b>
        <span>以下方法将在正式模型接入后提供，当前不以规则分数冒充：</span>
        <ul>
          <li><b>SHAP 值</b>——树模型的逐因子贡献（局部 + 全局重要性）</li>
          <li><b>注意力权重</b>——深度时序模型的“模型关注度”（不等同因果贡献）</li>
          <li><b>敏感性分析</b>——单因素变化 ±10% 时预测结果的响应</li>
        </ul>
      </div>
    </div>

    <!-- ===== 不确定性 ===== -->
    <div v-else class="frp-body" role="tabpanel" aria-label="不确定性" data-role="result-uncertainty">
      <div class="frp-blocked" data-role="uncertainty-blocked">
        <b>模型未提供不确定性量化</b>
        <span>规则研判为确定性档位结论，不产生置信区间或概率分布；系统不会以固定带宽伪造区间。</span>
      </div>
      <h4 class="frp-sub-h">正式模型接入后将提供</h4>
      <ul class="frp-plan" data-role="uncertainty-plan">
        <li>叶绿素 a / 蓝藻生物量：预测中位数 + 80% / 95% 置信区间</li>
        <li>水华面积：预测面积区间（如 28—41 km²）</li>
        <li>风险等级：低 / 中 / 高的概率分布</li>
        <li>区间宽度随预测期 T+1 → T+90 自然增大</li>
        <li>地图低可信区域以纹理 / 虚线边界标注</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
// 时空推演右侧预测结果面板：结果总览 / 驱动因素 / 不确定性 三标签。
// 能力边界：站点级数值预测、SHAP/注意力/敏感性解释、不确定性量化均未接入，
// 一律显式“未接入/待提供”，不用规则分数或固定带宽冒充模型输出。
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
  summaryLoading: { type: Boolean, default: false }
})

defineEmits(['back-to-lake', 'retry'])

const TABS = [
  { key: 'overview', label: '结果总览' },
  { key: 'drivers', label: '驱动因素' },
  { key: 'uncertainty', label: '不确定性' }
]
const activeTab = ref('overview')

// 切换对象时回到总览，避免停留在旧上下文的标签
watch(() => [props.scope, props.stationName], () => {
  activeTab.value = 'overview'
})

const activeFactors = computed(() => {
  const source = props.scope === 'station' ? props.stationAssessment : props.assessment
  const factors = (source && source.factors) || []
  return factors.slice().sort((a, b) => b.contribution - a.contribution).slice(0, 6)
})
const activeNeutral = computed(() => {
  const source = props.scope === 'station' ? props.stationAssessment : props.assessment
  return (source && source.neutral) || []
})
const maxContribution = computed(() =>
  activeFactors.value.reduce((m, f) => Math.max(m, f.contribution), 0) || 1
)
function barWidth(v) {
  return `${Math.max(4, Math.round((v / maxContribution.value) * 100))}%`
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
