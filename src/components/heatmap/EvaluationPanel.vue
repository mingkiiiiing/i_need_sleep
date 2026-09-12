<template>
  <section class="evp" data-role="model-evaluation">
    <button
      type="button"
      class="evp-head"
      data-role="model-evaluation-toggle"
      :aria-expanded="String(open)"
      aria-controls="evp-body"
      @click="open = !open"
    >
      <span class="evp-title">模型评估</span>
      <span class="evp-sub">{{ metricLabel }}<template v-if="horizonDays"> · T+{{ horizonDays }}</template></span>
      <!-- gate_status 原样展示：PASS / FAIL / NA 不改写、不弱化；无诊断记录时如实给 — -->
      <span class="evp-gate" :data-gate="gateKey" data-role="model-evaluation-gate">{{ gateText }}</span>
      <svg
        class="evp-chevron"
        :class="{ 'evp-chevron--open': open }"
        viewBox="0 0 12 12"
        width="12"
        height="12"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M2.5 4.25 6 7.75l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <div v-show="open" id="evp-body" class="evp-body" role="region" aria-label="模型评估详情" data-role="model-evaluation-body">
      <template v-if="hasDiagnostic">
        <!-- 融合门禁行：10% 提升门禁（唯一来源 gate_table.json）的行状态 -->
        <div class="evp-block" data-role="eval-gate-row">
          <b class="evp-block-title">融合门禁（10% 提升）</b>
          <div class="evp-gate-line">
            <span class="evp-gate" :data-gate="gateKey">{{ gateStatus || '—' }}</span>
            <span v-if="showNaReason" class="evp-mono">na_reason: {{ gateNaReason }}</span>
          </div>
          <p v-if="naReasonNote" class="evp-note">{{ naReasonNote }}</p>
          <!-- comparison_evidence：按 envelope 实际字段结构以键值对如实展示。
               envelope 未携带 fusion vs single 的成对指标值（那只在 gate_table.json 里），
               因此这里不编造对比对，只列实际存在的字段。 -->
          <dl v-if="evidenceRows.length" class="evp-kv" data-role="eval-gate-evidence">
            <div v-for="row in evidenceRows" :key="row.key">
              <dt>{{ row.label }}</dt>
              <dd>
                <span class="evp-mono">{{ row.value }}</span>
                <i v-if="row.hint" class="evp-hint">{{ row.hint }}</i>
              </dd>
            </div>
          </dl>
        </div>

        <!-- 留出集指标：本档模型在冻结测试段的真实精度 -->
        <div v-if="metricRows.length" class="evp-block" data-role="eval-test-metrics">
          <b class="evp-block-title">留出集指标（冻结测试段）</b>
          <dl class="evp-kv">
            <div v-for="row in metricRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd class="evp-mono">{{ row.value }}</dd>
            </div>
          </dl>
        </div>

        <!-- 校准证据：预测区间的覆盖率核算（entity_diagnostic + 焦点任务 box 证据） -->
        <div v-if="calibrationRows.length" class="evp-block" data-role="eval-calibration">
          <b class="evp-block-title">校准证据（预测区间）</b>
          <dl class="evp-kv">
            <div v-for="row in calibrationRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>
                <span class="evp-mono">{{ row.value }}</span>
                <i v-if="row.hint" class="evp-hint">{{ row.hint }}</i>
              </dd>
            </div>
          </dl>
        </div>
      </template>
      <p v-else class="evp-empty" data-role="model-evaluation-empty">
        该对象在此时效没有逐实体诊断记录：全湖口径由站点预测分布聚合得出，不提供单实体门禁与留出证据。
      </p>
      <p class="evp-note evp-note--foot">门禁与用途限制的完整记录见 gate_table.json（保留于交付包）。</p>
    </div>
  </section>
</template>

<script setup>
// 「模型评估」可展开块（W2 2026-09-12）：承接从主视图移出的门禁证据——
// 融合门禁（gate_table.json 的 10% 提升验收行状态）+ 留出集指标 + 区间校准证据。
// 诚实约束：gate_status 原样展示（PASS/FAIL/NA 不改写不美化）；comparison_evidence
// 按 envelope 实际字段结构以键值对展示；诊断缺失（全湖聚合口径）时如实说明，
// 不用占位数据顶替。
import { computed, ref } from 'vue'
import { sourceSemantics } from '../../stores/predictionSnapshot.js'

const props = defineProps({
  // focusEvaluation(horizonDays) 返回的完整诊断对象；null = 当前时效无快照数据
  diagnostics: { type: Object, default: null },
  horizonDays: { type: Number, default: 1 },
  metricLabel: { type: String, default: '' }
})

// 折叠状态本地持有：默认收起
const open = ref(false)

const diag = computed(() => props.diagnostics?.entityDiagnostic || null)
const hasDiagnostic = computed(() => Boolean(diag.value))
const gateStatus = computed(() => diag.value?.gate_status || '')
const gateKey = computed(() => (['PASS', 'FAIL', 'NA'].includes(gateStatus.value) ? gateStatus.value : 'none'))
const gateText = computed(() => gateStatus.value || '—')
const gateNaReason = computed(() => diag.value?.gate_na_reason || '')
const showNaReason = computed(() => gateStatus.value === 'NA' && Boolean(gateNaReason.value))

// 已知 na_reason 的中性解释；未知的只展示原始码，不编造含义
const NA_REASON_TEXT = {
  test_n_below_minimum_15: '测试样本数低于最低要求（15 行），门禁不做达标判定（N.A.），不视为通过。'
}
const naReasonNote = computed(() => (showNaReason.value ? NA_REASON_TEXT[gateNaReason.value] || '' : ''))

// comparison_evidence 键值对标签：键名与 envelope 实际字段一一对应
const EVIDENCE_LABELS = {
  value_origin: '结果来源 value_origin',
  model_family: '融合模型族 model_family',
  model_run_id: '运行 ID model_run_id',
  gate_uplift: '门禁提升值 gate_uplift',
  test_n: '留出测试样本 n',
  roc_auc: 'ROC AUC',
  r2: 'R²',
  min_test_rows: '最低测试样本要求'
}

function fmtNum(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
}

const evidenceRows = computed(() => {
  const ev = props.diagnostics?.comparisonEvidence
  if (!ev || typeof ev !== 'object') return []
  return Object.entries(ev)
    // gate_status / gate_na_reason 已在门禁行原样展示，不在列表中重复
    .filter(([k]) => k !== 'gate_status' && k !== 'gate_na_reason')
    .map(([k, v]) => ({
      key: k,
      label: EVIDENCE_LABELS[k] || k,
      value: v == null ? '—' : typeof v === 'number' ? fmtNum(v) : String(v),
      hint: k === 'value_origin' && v != null ? sourceSemantics(String(v)).label || '' : ''
    }))
})

const metricRows = computed(() => {
  const m = props.diagnostics?.testMetrics
  if (!m || typeof m !== 'object') return []
  const rows = []
  if (m.mae != null) rows.push({ label: 'MAE', value: fmtNum(m.mae) })
  if (m.r2 != null) rows.push({ label: 'R²', value: fmtNum(m.r2) })
  if (m.n != null) rows.push({ label: 'n（测试样本数）', value: String(m.n) })
  return rows
})

const CALIBRATION_TEXT = {
  validated: '已核算',
  undercovered: '覆盖率未达标',
  no_test_evidence: '无测试证据',
  insufficient_test_evidence: '样本不足',
  single_class_test: '单类别测试段',
  unavailable: '不适用'
}

const calibrationRows = computed(() => {
  const d = props.diagnostics
  if (!d) return []
  const rows = []
  if (d.calibrationStatus) {
    rows.push({
      label: '校准状态 calibration_status',
      value: d.calibrationStatus,
      hint: CALIBRATION_TEXT[d.calibrationStatus] || ''
    })
  }
  if (d.empiricalCoverage != null) {
    rows.push({ label: '经验覆盖率', value: `${(Number(d.empiricalCoverage) * 100).toFixed(2)}%` })
  }
  if (d.testN != null) rows.push({ label: 'test_n', value: String(d.testN) })
  if (d.calibrationN != null) rows.push({ label: 'calibration_n', value: String(d.calibrationN) })
  // 验收线（若 envelope 带）：88% = 标称 90% − 容差 2%
  if (d.coverageAcceptanceMin != null) {
    const target = d.coverageTarget
    const tolerance = d.coverageTolerance
    rows.push({
      label: '覆盖率验收线',
      value: `${(Number(d.coverageAcceptanceMin) * 100).toFixed(0)}%`,
      hint:
        target != null && tolerance != null
          ? `（标称 ${Math.round(Number(target) * 100)}% − 容差 ${Math.round(Number(tolerance) * 100)}%）`
          : ''
    })
  }
  return rows
})
</script>

<style scoped>
.evp {
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.evp-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  appearance: none;
  border: 0;
  background: transparent;
  padding: 9px 12px;
  cursor: pointer;
  text-align: left;
}
.evp-head:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
  border-radius: 10px;
}
.evp-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
}
.evp-sub {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.evp-gate {
  margin-left: auto;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 1px 8px;
  color: var(--text-muted);
}
/* 徽标配色：PASS 绿 / FAIL 琥珀红字样如实 / NA 灰——与面板既有门禁行同源 */
.evp-gate[data-gate='PASS'] {
  color: var(--c-stable);
  border-color: color-mix(in srgb, var(--c-stable) 55%, transparent);
}
.evp-gate[data-gate='FAIL'] {
  color: var(--risk-critical, #ef4444);
  border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent);
}
.evp-gate[data-gate='NA'] {
  color: var(--text-muted);
}
.evp-chevron {
  flex: 0 0 auto;
  color: var(--text-muted);
  transition: transform 0.2s ease;
}
.evp-chevron--open {
  transform: rotate(180deg);
}
@media (prefers-reduced-motion: reduce) {
  .evp-chevron {
    transition: none;
  }
}
.evp-body {
  display: grid;
  gap: 10px;
  padding: 9px 12px 10px;
  border-top: 1px dashed var(--border-subtle);
}
.evp-block {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.evp-block-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
}
.evp-gate-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.evp-kv {
  margin: 0;
  display: grid;
  gap: 3px;
  min-width: 0;
}
.evp-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.evp-kv dt {
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.evp-kv dd {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-primary);
  text-align: right;
  word-break: break-all;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.evp-mono {
  font-family: var(--font-mono);
}
.evp-hint {
  font-style: normal;
  font-size: 9px;
  color: var(--text-muted);
  white-space: nowrap;
}
.evp-note {
  margin: 0;
  font-size: 9.5px;
  line-height: 1.6;
  color: var(--text-muted);
}
.evp-note--foot {
  border-top: 1px dashed var(--border-subtle);
  padding-top: 7px;
}
.evp-empty {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-muted);
}
</style>
