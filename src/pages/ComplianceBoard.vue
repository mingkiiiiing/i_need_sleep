<template>
  <main class="cb" aria-label="V0.3 达标看板">
    <header class="cb-head">
      <div>
        <h1>V0.3 真实数据达标看板</h1>
        <p class="cb-sub">
          数据版本 {{ overview?.claim_boundary === 'real_data_monthly_station_v0_3' ? 'TAIHU_CLEAN_FINAL_V1（真实清洗数据，月度标签粒度）' : '—' }}
          · 指标以冻结测试集（≥2024-01）评估为准
        </p>
      </div>
      <span class="cb-badge" :data-status="overviewStatus">{{ overviewStatusText }}</span>
    </header>

    <StatePanel v-if="state === 'loading'" state="loading" title="达标证据加载中…" />
    <StatePanel
      v-else-if="state === 'error' && !overview"
      state="error"
      title="达标看板数据不可用"
      :description="error || 'V0.3 运行包或评估产物缺失。'"
    >
      <button type="button" class="cb-btn" @click="load">重试</button>
    </StatePanel>

    <template v-else>
      <!-- P0 达标卡片 -->
      <section class="cb-grid" aria-label="P0 达标项">
        <article
          v-for="item in overview?.items || []"
          :key="item.id"
          class="cb-card"
          :data-status="item.status"
          :data-item="item.id"
        >
          <header class="cb-card-head">
            <span class="cb-card-id">{{ item.id }}</span>
            <b class="cb-card-title">{{ item.title }}</b>
            <span class="cb-card-status">{{ item.status }}</span>
          </header>
          <p class="cb-card-detail">{{ item.detail }}</p>
          <footer class="cb-card-evidence">
            <a v-for="ev in item.evidence" :key="ev.href" :href="ev.href" target="_blank" rel="noopener">{{ ev.label }} ↗</a>
          </footer>
        </article>
      </section>

      <!-- 10% 门禁汇总 -->
      <section class="cb-section" aria-label="10% 门禁汇总">
        <h2>10% 融合提升门禁</h2>
        <div v-if="acceptance" class="cb-kv" data-role="gate-summary">
          <div><dt>状态</dt><dd :class="{ 'cb-warn': acceptance.status !== 'PASS' }">{{ acceptance.status }}</dd></div>
          <div><dt>可评估比较</dt><dd>{{ acceptance.evaluable_comparisons }} / {{ acceptance.comparison_rows }}</dd></div>
          <div><dt>通过 / 失败</dt><dd>{{ acceptance.pass }} / {{ acceptance.fail }}</dd></div>
          <div><dt>N.A.（测试行数不足）</dt><dd>{{ acceptance.not_applicable }}</dd></div>
          <div><dt>基线口径</dt><dd>RF 与 XGBoost 的较优者（冻结测试集同口径）</dd></div>
        </div>
        <p v-if="acceptance?.honesty_note" class="cb-note cb-warn">{{ acceptance.honesty_note }}</p>
        <p class="cb-note">
          N.A. 表示该任务 × 时效组合的冻结测试集真实标签行数低于 {{ acceptance?.min_test_rows ?? 15 }} 行，
          无法支撑统计比较；须补足真实标签后重训再评，禁止调整口径凑数。
          <RouterLink class="cb-link" to="/gate-report">查看门禁逐行明细 →</RouterLink>
        </p>
      </section>

      <!-- conformal 覆盖率 -->
      <section class="cb-section" aria-label="conformal 覆盖率">
        <h2>残差校准置信区间（split-conformal P05/P95）</h2>
        <table v-if="coverage.items.length" class="cb-table" data-role="coverage-table">
          <thead>
            <tr>
              <th>run_id</th><th>时效</th><th>目标覆盖率</th><th>经验覆盖率（冻结测试集）</th><th>校准样本</th><th>测试样本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in coverage.items" :key="item.run_id">
              <td class="cb-mono">{{ item.run_id }}</td>
              <td>T+{{ item.horizon_days }}</td>
              <td>{{ percent(item.coverage_target) }}</td>
              <td :class="{ 'cb-warn': item.empirical_coverage == null }">
                {{ item.empirical_coverage == null ? '样本不足未核算' : percent(item.empirical_coverage) }}
              </td>
              <td>{{ item.calibration_n ?? '—' }}</td>
              <td>{{ item.test_n ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="cb-note">暂无带校准器的可训练 bundle。</p>
      </section>

      <!-- 遥感校准留出验证 -->
      <section class="cb-section" aria-label="遥感校准留出验证">
        <h2>遥感反演地面配对校准（留出验证）</h2>
        <table v-if="retrievalMetrics" class="cb-table" data-role="retrieval-metrics">
          <thead>
            <tr><th>传感器 / 指数</th><th>留出 R²</th><th>留出 RMSE（μg/L）</th><th>配对数</th></tr>
          </thead>
          <tbody>
            <tr v-for="(metrics, name) in retrievalMetrics" :key="name">
              <td>{{ sensorLabel(name) }}</td>
              <td :class="{ 'cb-warn': (metrics.r2 ?? 0) < 0 }">{{ fmt(metrics.r2) }}</td>
              <td>{{ fmt(metrics.rmse) }}</td>
              <td>{{ metrics.n ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="s2Choice" class="cb-note">
          S2 指数择优：{{ s2Choice.chosen }}（按留出 R² 最高规则）。
        </p>
        <p v-if="retrieval?.honesty_note" class="cb-note cb-warn">{{ retrieval.honesty_note }}</p>
        <p class="cb-note">反演 / 校准值永远是派生口径，不作为观测真值；R² 为负表示留出期线性校准外推失效，如实披露。</p>
      </section>

      <!-- 月度栅格场（P0-4 证据可视化） -->
      <section class="cb-section" aria-label="月度栅格空间场">
        <h2>月度栅格空间场与水华边界</h2>
        <RasterLayer :horizon-days="3" />
      </section>
    </template>
  </main>
</template>

<script setup>
// V0.3 达标看板：聚合 /acceptance/overview、门禁汇总、conformal 覆盖率、遥感校准验证与栅格场。
// 全部证据由后端评估产物实时读取，页面不做任何数值加工或粉饰。
import { computed, onMounted, ref } from 'vue'
import StatePanel from '../components/common/StatePanel.vue'
import RasterLayer from '../components/heatmap/RasterLayer.vue'
import {
  getAcceptanceOverviewEnvelope,
  getAlgorithmV3AcceptanceEnvelope,
  getCalibrationCoverageEnvelope,
  getRetrievalValidationEnvelope
} from '../services/api.js'

const state = ref('loading')
const error = ref('')
const overview = ref(null)
const acceptance = ref(null)
const coverage = ref({ items: [] })
const retrieval = ref(null)

const overviewStatus = computed(() =>
  (overview.value?.items || []).every((item) => item.status === '达标') ? 'pass' : 'partial'
)
const overviewStatusText = computed(() => {
  const items = overview.value?.items || []
  if (!items.length) return '—'
  const done = items.filter((item) => item.status === '达标').length
  return `${done}/${items.length} 项达标`
})
const retrievalMetrics = computed(() => retrieval.value?.metrics || null)
const s2Choice = computed(() => retrieval.value?.s2_group_choice || null)

const SENSOR_LABELS = {
  modis_lwq300: 'MODIS 内陆水色 300m',
  s2_30m_mci: 'Sentinel-2 30m MCI',
  s2_30m_ndci: 'Sentinel-2 30m NDCI'
}
function sensorLabel(name) {
  return SENSOR_LABELS[name] || name
}
function percent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return `${(num * 100).toFixed(1)}%`
}
function fmt(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return num.toFixed(3)
}

async function load() {
  state.value = 'loading'
  error.value = ''
  const results = await Promise.allSettled([
    getAcceptanceOverviewEnvelope(),
    getAlgorithmV3AcceptanceEnvelope(),
    getCalibrationCoverageEnvelope(),
    getRetrievalValidationEnvelope()
  ])
  const [overviewRes, acceptanceRes, coverageRes, retrievalRes] = results
  overview.value = overviewRes.status === 'fulfilled' ? overviewRes.value.data : null
  acceptance.value = acceptanceRes.status === 'fulfilled' ? acceptanceRes.value.data : null
  coverage.value = coverageRes.status === 'fulfilled' ? coverageRes.value.data : { items: [] }
  retrieval.value = retrievalRes.status === 'fulfilled' ? retrievalRes.value.data : null
  const failures = results.filter((r) => r.status === 'rejected')
  if (!overview.value) {
    state.value = 'error'
    error.value = failures[0]?.reason?.message || '达标证据不可用'
    return
  }
  state.value = 'ok'
}

onMounted(load)
</script>

<style scoped>
.cb {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 24px 28px 48px;
  max-width: 1180px;
  margin: 0 auto;
}
.cb-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.cb-head h1 { margin: 0; font-size: 22px; }
.cb-sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.cb-badge {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  border: 1px solid var(--border-subtle);
}
.cb-badge[data-status='pass'] { color: #34d399; border-color: rgba(52, 211, 153, 0.4); }
.cb-badge[data-status='partial'] { color: #fbbf24; border-color: rgba(251, 191, 36, 0.4); }
.cb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
}
.cb-card {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--surface-panel-soft, rgba(255, 255, 255, 0.03));
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.cb-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cb-card-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.cb-card-title { font-size: 13px; flex: 1; }
.cb-card-status { font-size: 12px; font-weight: 700; }
.cb-card[data-status='达标'] .cb-card-status { color: #34d399; }
.cb-card[data-status='部分达标'] .cb-card-status { color: #fbbf24; }
.cb-card[data-status='未达标'] .cb-card-status { color: #f87171; }
.cb-card-detail {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.55;
}
.cb-card-evidence { display: flex; gap: 12px; flex-wrap: wrap; }
.cb-card-evidence a {
  font-size: 11px;
  color: #38bdf8;
  text-decoration: none;
}
.cb-section {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cb-section h2 { margin: 0; font-size: 15px; }
.cb-kv {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.cb-kv > div {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
}
.cb-kv dt { font-size: 11px; color: var(--text-muted); }
.cb-kv dd { margin: 4px 0 0; font-size: 13px; font-weight: 600; }
.cb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.cb-table th,
.cb-table td {
  border-bottom: 1px solid var(--border-subtle);
  padding: 7px 10px;
  text-align: left;
}
.cb-table th { color: var(--text-muted); font-weight: 600; }
.cb-mono { font-family: var(--font-mono); font-size: 11px; }
.cb-note {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.cb-warn { color: #fbbf24; }
.cb-link { color: #38bdf8; text-decoration: none; }
.cb-btn {
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-primary);
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 12px;
}
</style>
