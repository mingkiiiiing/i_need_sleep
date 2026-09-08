<template>
  <div class="pev">
    <section class="pev-head-card" aria-label="预测评估能力状态" data-role="pred-eval-state">
      <StatePanel
        :state="state === 'error' ? 'error' : 'empty'"
        :title="state === 'error' ? '预测评估能力状态查询失败' : '预测评估尚未开放'"
        :description="state === 'error'
          ? (errorText || '/history/prediction-evaluations 请求失败，不推测模型能力。')
          : (data?.message || '正式预测服务尚未接入。')"
      >
        <button v-if="state === 'error'" type="button" class="pev-btn" @click="load">重试</button>
      </StatePanel>
    </section>

    <template v-if="data">
      <section class="pev-grid">
        <div class="pev-card">
          <h4>可验证预测样本</h4>
          <strong class="pev-num">{{ data.verifiable?.samples ?? 0 }}</strong>
          <p class="pev-dim">站缺测、预测运行失败或目标时间无对应观测的数据不进入准确率分母，单独统计为「不可验证」。</p>
        </div>
        <div class="pev-card">
          <h4>当前预测事件</h4>
          <strong class="pev-num">{{ data.predicted_events ?? 0 }}</strong>
          <p class="pev-dim">预测规则{{ data.predicted_rule_enabled ? '已配置但尚无带 forecast_id 的预测事件' : '未启用' }}；预警中心的预测预警为预留类型。</p>
        </div>
        <div class="pev-card">
          <h4>接入条件</h4>
          <ul class="pev-list">
            <li>正式预测稳定提供 <code>forecast_id</code> 与 <code>prediction_run_id</code></li>
            <li>预测发布后留存的解释与不确定性输出</li>
            <li>目标时间取得对应实测观测</li>
          </ul>
        </div>
      </section>

      <section class="pev-defs" aria-label="评价指标定义">
        <h4>评价指标定义（接入后按预测目标分别评价）</h4>
        <table class="pev-table">
          <thead>
            <tr><th>预测目标</th><th>建议评价方式</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in data.metric_definitions || []" :key="index">
              <td>{{ row.target }}</td>
              <td>{{ row.metrics }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="pev-notes" aria-label="统计口径">
        <h4>统计口径（预先约定，防止事后解释）</h4>
        <ul>
          <li v-for="(note, index) in data.criteria || []" :key="index">{{ note }}</li>
          <li>不同时间尺度分别评价：1—3 天、7—15 天、30—90 天。</li>
        </ul>
      </section>

      <p class="pev-remote">
        卫星年度遥感对比在
        <RouterLink class="pev-link" to="/heatmap">时空推演 · 年度对比</RouterLink>
        中提供，本页不复制完整遥感功能。
      </p>
    </template>
  </div>
</template>

<script setup>
// 预测评估视图：正式预测接入前只展示能力状态与预先约定的评价口径，
// 不伪造准确率、提前量或概率校准结果（能力诚实展示约定）。
import { onMounted, ref } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import { fetchPredictionEvaluations } from '../../services/historyReview.js'

const data = ref(null)
const state = ref('loading')
const errorText = ref('')

async function load() {
  state.value = 'loading'
  errorText.value = ''
  try {
    data.value = await fetchPredictionEvaluations()
    state.value = 'ok'
  } catch (err) {
    data.value = null
    state.value = 'error'
    errorText.value = err?.message || '预测评估能力状态查询失败'
  }
}

onMounted(load)
</script>

<style scoped>
.pev {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.pev-head-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 12px;
}
.pev-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}
.pev-card {
  display: grid;
  gap: 6px;
  align-content: start;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.pev-card h4 {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.pev-num {
  font-family: var(--font-mono);
  font-size: 26px;
  color: var(--text-primary);
}
.pev-list {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.pev-list code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-secondary);
}
.pev-dim {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.6;
}
.pev-defs,
.pev-notes {
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  display: grid;
  gap: 8px;
}
.pev-defs h4,
.pev-notes h4 {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.pev-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}
.pev-table th,
.pev-table td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
}
.pev-table th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10.5px;
}
.pev-notes ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.pev-remote {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}
.pev-link {
  color: var(--color-primary);
}
.pev-btn {
  appearance: none;
  min-height: 32px;
  padding: 2px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}
.pev-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
@media (max-width: 1100px) {
  .pev-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
