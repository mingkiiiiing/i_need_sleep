<template>
  <main class="gr" aria-label="V0.3 门禁明细">
    <header class="gr-head">
      <div>
        <h1>10% 提升门禁 · 逐行明细</h1>
        <p class="gr-sub">
          唯一来源 evaluation/gate_table.json（实时生成）· 比较规则：融合 vs RF/XGBoost 较优者 ·
          冻结测试集 ≥2024-01，最低行数 {{ detail?.min_test_rows ?? 15 }}
        </p>
      </div>
      <div class="gr-filters" role="group" aria-label="行状态过滤">
        <button
          v-for="opt in FILTERS"
          :key="opt"
          type="button"
          :class="{ active: filter === opt }"
          @click="filter = opt"
        >{{ opt }}</button>
      </div>
    </header>

    <StatePanel v-if="state === 'loading'" state="loading" title="门禁明细加载中…" />
    <StatePanel
      v-else-if="state === 'error'"
      state="error"
      title="门禁明细不可用"
      :description="error || 'gate_table.json 缺失：请先运行 cli_real.py gate。'"
    >
      <button type="button" class="gr-btn" @click="load">重试</button>
    </StatePanel>

    <template v-else>
      <div class="gr-summary" data-role="gate-summary">
        <span>门禁版本 <b>{{ detail?.gate_version }}</b></span>
        <span>生成时间 <b>{{ detail?.generated_at }}</b></span>
        <span>汇总状态 <b :class="statusClass(summary?.status)">{{ summary?.status }}</b></span>
        <span>可评估 <b>{{ summary?.evaluable_comparisons }}/{{ summary?.comparison_rows }}</b></span>
      </div>

      <div class="gr-table-wrap">
        <table class="gr-table" data-role="gate-rows">
          <thead>
            <tr>
              <th>任务</th><th>变体</th><th>时效</th><th>月偏移</th>
              <th>n_test</th><th>指标</th><th>融合</th><th>单一最优</th><th>提升</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in visibleRows" :key="rowKey(row)" :data-status="row.status">
              <td>{{ row.task_label || row.task_id }}</td>
              <td>{{ row.variant }}</td>
              <td>T+{{ row.horizon_days }}d</td>
              <td>{{ row.month_offset ?? '—' }}</td>
              <td>{{ row.n_test ?? '—' }}</td>
              <td>{{ row.primary_metric || '—' }}</td>
              <td>{{ fmt(row.fusion_value) }}</td>
              <td>{{ fmt(row.best_single_value) }}</td>
              <td :class="{ 'gr-warn': row.status === 'FAIL', 'gr-good': row.status === 'PASS' }">
                {{ row.status === 'NA' ? '—' : percentDelta(row.uplift) }}
              </td>
              <td>
                <span class="gr-status" :class="`gr-status--${row.status.toLowerCase()}`">
                  {{ row.status }}<template v-if="row.status === 'NA' && row.na_reason"> · {{ row.na_reason }}</template>
                </span>
              </td>
            </tr>
            <tr v-if="!visibleRows.length">
              <td colspan="10" class="gr-empty">当前过滤条件下没有门禁行。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="detail?.honesty_note" class="gr-note gr-warn" data-role="gate-honesty">{{ detail.honesty_note }}</p>
      <p class="gr-note">
        N.A. 行表示冻结测试集真实标签行数不足或该任务在该时效不可训练（缺标签月）；
        结论是「无法判定」而非「达标」。补足真实标签后重训，禁止调整口径或拆小样本。
      </p>
    </template>
  </main>
</template>

<script setup>
// V0.3 门禁逐行明细：/model/acceptance/detail（后端读 gate_table.json + availability 补全）。
import { computed, onMounted, ref } from 'vue'
import StatePanel from '../components/common/StatePanel.vue'
import { getAlgorithmAcceptanceDetailEnvelope } from '../services/api.js'

const FILTERS = ['全部', 'PASS', 'FAIL', 'NA']
const state = ref('loading')
const error = ref('')
const detail = ref(null)
const filter = ref('全部')

const summary = computed(() => detail.value?.summary || null)
const visibleRows = computed(() => {
  const rows = detail.value?.rows || []
  if (filter.value === '全部') return rows
  return rows.filter((row) => row.status === filter.value)
})

function rowKey(row) {
  return `${row.task_id}-${row.variant}-${row.horizon_days}`
}
function statusClass(status) {
  return status === 'PASS' ? 'gr-good' : status === 'FAIL' ? 'gr-warn' : ''
}
function fmt(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
function percentDelta(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return `${num >= 0 ? '+' : ''}${(num * 100).toFixed(1)}%`
}

async function load() {
  state.value = 'loading'
  error.value = ''
  try {
    const { data } = await getAlgorithmAcceptanceDetailEnvelope()
    detail.value = data
    state.value = 'ok'
  } catch (err) {
    error.value = err?.message || '门禁明细请求失败'
    state.value = 'error'
  }
}

onMounted(load)
</script>

<style scoped>
.gr {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px 28px 48px;
  max-width: 1180px;
  margin: 0 auto;
}
.gr-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.gr-head h1 { margin: 0; font-size: 22px; }
.gr-sub { margin: 6px 0 0; font-size: 12px; color: var(--text-secondary); }
.gr-filters { display: flex; gap: 6px; }
.gr-filters button {
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.gr-filters button.active {
  background: var(--color-primary);
  color: var(--color-primary-ink);
  border-color: transparent;
}
.gr-summary {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 10px 14px;
}
.gr-summary b { color: var(--text-primary); }
.gr-table-wrap { overflow-x: auto; border: 1px solid var(--border-subtle); border-radius: 10px; }
.gr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  min-width: 860px;
}
.gr-table th,
.gr-table td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 8px 10px;
  text-align: left;
  white-space: nowrap;
}
.gr-table th { color: var(--text-muted); font-weight: 600; position: sticky; top: 0; background: var(--surface-panel); }
.gr-empty { text-align: center; color: var(--text-muted); padding: 20px; }
.gr-status { font-weight: 700; }
.gr-status--pass { color: #34d399; }
.gr-status--fail { color: #f87171; }
.gr-status--na { color: var(--text-muted); font-weight: 500; }
.gr-good { color: #34d399; }
.gr-warn { color: #f87171; }
.gr-note { margin: 0; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.gr-btn {
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-primary);
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 12px;
}
</style>
