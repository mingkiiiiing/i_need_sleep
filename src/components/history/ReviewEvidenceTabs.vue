<template>
  <section class="ret" aria-label="复盘证据标签">
    <div class="ret-tabs" role="tablist" aria-label="复盘证据类别">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        type="button"
        role="tab"
        class="ret-tab"
        :class="{ 'ret-tab--on': active === tab.key }"
        :aria-selected="String(active === tab.key)"
        :data-role="`evidence-tab-${tab.key}`"
        @click="active = tab.key"
      >{{ tab.label }}</button>
    </div>

    <div v-if="!detail" class="ret-empty">选中左侧事件后展示复盘证据。</div>

    <!-- ===== 观测证据 ===== -->
    <div v-else-if="active === 'observed'" class="ret-body" role="tabpanel">
      <EvidenceObserved :evidence="detail.observed_evidence" :detail="detail" @jump-replay="(q) => emit('jump-replay', q)" />
    </div>

    <!-- ===== 预测验证 ===== -->
    <div v-else-if="active === 'forecast'" class="ret-body" role="tabpanel" data-role="evidence-forecast">
      <StatePanel
        state="empty"
        title="本事件无可验证的正式预测"
        :description="detail.forecast_evidence_note || '该事件没有关联的正式预测结果。'"
      />
      <div class="ret-pending">
        <p>正式预测接入后，这里将展示：</p>
        <ul>
          <li>当时的预测发布时间与目标时间（forecast_id / prediction_run_id）</li>
          <li>当时预测值、预测区间（P05—P95）和风险概率</li>
          <li>后来实际观测值与预测等级是否一致、是否提前发现风险</li>
          <li>当时的驱动因素解释与模型/数据版本</li>
        </ul>
        <p class="ret-pending-note">
          当前预测规则未启用，系统不会用规则研判补充历史预测结果；预测评估只能使用预测发布后取得的实测数据。
        </p>
      </div>
    </div>

    <!-- ===== 预案执行 ===== -->
    <div v-else-if="active === 'plan'" class="ret-body" role="tabpanel" data-role="evidence-plan">
      <template v-if="plan?.adopted">
        <div class="ret-plan-head">
          <div>
            <h4>{{ plan.name }}<span class="ret-mono">（{{ plan.version }}）</span></h4>
            <p class="ret-sub">采用时间：{{ formatBeijing(plan.adopted_at) }}（北京时间）· 采用时快照，预案库后续修改不覆盖</p>
          </div>
          <span class="ret-complete" :class="{ 'ret-complete--full': plan.completion_rate === 1 }">
            完成率 {{ plan.tasks_done }}/{{ plan.tasks_total }}
            <template v-if="plan.completion_rate != null">（{{ Math.round(plan.completion_rate * 100) }}%）</template>
          </span>
        </div>
        <table class="ret-table">
          <thead>
            <tr><th>措施任务</th><th>责任组</th><th>状态</th><th>完成时间/说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="task in plan.tasks" :key="task.id">
              <td>{{ task.text }}</td>
              <td>{{ PUSH_GROUP_TEXT[task.group] || task.group || '—' }}</td>
              <td>
                <span class="ret-chip" :class="`ret-chip--task-${task.status}`">{{ TASK_STATUS_TEXT[task.status] || task.status }}</span>
              </td>
              <td class="ret-dim">{{ task.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="plan.unfinished?.length" class="ret-warn" data-role="unfinished-tasks">
          未完成措施 {{ plan.unfinished.length }} 项：{{ plan.unfinished.map((t) => t.text).join('；') }}
        </p>
        <p class="ret-note">{{ plan.plan_library_changed_after_adoption?.note }}</p>
        <p class="ret-note">口径：预案任务完成不等于预案措施被证明有效。</p>
      </template>
      <template v-else>
        <StatePanel state="empty" title="本事件未采用应急预案" :description="plan?.note || '该事件处置过程未采用预案。'" />
      </template>
    </div>

    <!-- ===== 通知与模拟推送 ===== -->
    <div v-else-if="active === 'notify'" class="ret-body" role="tabpanel" data-role="evidence-notify">
      <div class="ret-cols">
        <section aria-label="站内通知">
          <h4>站内通知（{{ notifications.length }}）</h4>
          <p v-if="!notifications.length" class="ret-dim">该事件没有生成过站内通知。</p>
          <table v-else class="ret-table">
            <thead>
              <tr><th>时间（北京时间）</th><th>类型</th><th>内容</th><th>已读</th></tr>
            </thead>
            <tbody>
              <tr v-for="n in notifications" :key="n.id">
                <td class="ret-mono">{{ formatBeijing(n.at) }}</td>
                <td>{{ NOTIFY_TYPE_TEXT[n.type] || n.type }}</td>
                <td>
                  {{ n.title }}
                  <span v-for="(line, index) in n.lines" :key="index" class="ret-dim ret-block">{{ line }}</span>
                </td>
                <td>
                  <span :class="n.read ? 'ret-ok' : 'ret-warn-txt'">{{ n.read ? `已读 ${formatBeijing(n.read_at)}` : '未读' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="ret-note">口径：未读通知不等于未确认事件；已读时间仅代表铃铛通知被查看。</p>
        </section>
        <section aria-label="模拟推送">
          <h4>短信 / 邮件模拟推送（{{ pushes.length }}）</h4>
          <p v-if="!pushes.length" class="ret-dim">该事件没有执行过模拟推送。</p>
          <table v-else class="ret-table">
            <thead>
              <tr><th>时间（北京时间）</th><th>渠道</th><th>接收组</th><th>收件人（脱敏）</th><th>结果</th><th>回执</th></tr>
            </thead>
            <tbody>
              <tr v-for="push in pushes" :key="push.id">
                <td class="ret-mono">{{ formatBeijing(push.at) }}</td>
                <td>{{ push.channel === 'sms' ? '短信' : '邮件' }}</td>
                <td>{{ (push.groups || []).join('、') || '—' }}</td>
                <td class="ret-mono">{{ (push.recipients_masked || []).join('，') || '—' }}</td>
                <td>
                  <span :class="push.status === 'simulated_success' ? 'ret-ok' : 'ret-bad'">{{ PUSH_STATUS_TEXT[push.status] || push.status }}</span>
                  <span class="ret-dim ret-block">{{ push.reason }}</span>
                </td>
                <td class="ret-mono">{{ push.receipt_no || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <details v-if="pushes.some((p) => p.body)" class="ret-fold">
            <summary>查看推送内容快照</summary>
            <div v-for="push in pushes.filter((p) => p.body)" :key="`body-${push.id}`" class="ret-push-body">
              <b class="ret-mono">{{ push.channel === 'sms' ? '短信' : '邮件' }} · {{ push.subject }}</b>
              <p>{{ push.body }}</p>
            </div>
          </details>
          <p class="ret-note">口径：模拟推送成功不等于短信或邮件真实送达。</p>
        </section>
      </div>
    </div>

    <!-- ===== 完整操作记录 ===== -->
    <div v-else class="ret-body" role="tabpanel" data-role="evidence-records">
      <p v-if="!records.length" class="ret-dim">该事件没有处理记录。</p>
      <table v-else class="ret-table ret-table--records">
        <thead>
          <tr><th>时间（北京时间）</th><th>操作人</th><th>动作</th><th>业务内容</th><th>技术详情</th></tr>
        </thead>
        <tbody>
          <template v-for="(r, index) in records" :key="index">
            <tr>
              <td class="ret-mono">{{ formatBeijing(r.at) }}</td>
              <td>{{ r.actor || '—' }}</td>
              <td>{{ RECORD_ACTION_TEXT[r.action] || r.action }}</td>
              <td>{{ r.detail || '—' }}</td>
              <td>
                <button type="button" class="ret-expand" @click="toggleRow(index)">{{ expandedRow === index ? '收起' : '展开' }}</button>
              </td>
            </tr>
            <tr v-if="expandedRow === index" class="ret-tech-row">
              <td colspan="5">
                <span class="ret-mono">action={{ r.action }} · event_no={{ r.event_no }} · 原始时间={{ r.at }}</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
// 事件复盘 · 底部五标签：观测证据 / 预测验证 / 预案执行 / 通知与模拟推送 / 完整操作记录。
// 预案执行读取事件采用时保存的预案快照；预测验证为诚实空态。
import { computed, ref, watch } from 'vue'
import StatePanel from '../common/StatePanel.vue'
import EvidenceObserved from './EvidenceObserved.vue'
import {
  NOTIFY_TYPE_TEXT,
  PUSH_GROUP_TEXT,
  PUSH_STATUS_TEXT,
  RECORD_ACTION_TEXT,
  TASK_STATUS_TEXT,
  formatBeijing
} from '../../services/historyReview.js'

const TABS = [
  { key: 'observed', label: '观测证据' },
  { key: 'forecast', label: '预测验证' },
  { key: 'plan', label: '预案执行' },
  { key: 'notify', label: '通知推送' },
  { key: 'records', label: '完整操作记录' }
]

const props = defineProps({
  detail: { type: Object, default: null }
})

const emit = defineEmits(['jump-replay'])

const active = ref('observed')
const expandedRow = ref(-1)

const plan = computed(() => props.detail?.plan_execution || null)
const notifications = computed(() => props.detail?.notifications || [])
const pushes = computed(() => props.detail?.pushes || [])
const records = computed(() => props.detail?.records || [])

watch(() => props.detail?.event?.id, () => {
  expandedRow.value = -1
})

function toggleRow(index) {
  expandedRow.value = expandedRow.value === index ? -1 : index
}
</script>

<style scoped>
.ret {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  padding: 10px 12px 14px;
  display: grid;
  gap: 10px;
  min-width: 0;
}
.ret-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 8px;
}
.ret-tab {
  appearance: none;
  min-height: 32px;
  padding: 3px 14px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.ret-tab:hover {
  color: var(--text-primary);
}
.ret-tab--on {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
  color: var(--text-primary);
}
.ret-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.ret-empty {
  font-size: 12px;
  color: var(--text-muted);
  padding: 10px 0;
}
.ret-body {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.ret-pending {
  display: grid;
  gap: 6px;
  padding: 10px 14px;
  border: 1px dashed var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.ret-pending p {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.ret-pending ul {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.ret-pending-note {
  font-size: 10.5px !important;
  color: var(--text-muted) !important;
}
.ret-plan-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.ret-plan-head h4 {
  margin: 0;
  font-size: 13px;
  color: var(--text-primary);
}
.ret-sub {
  margin: 3px 0 0;
  font-size: 10.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.ret-complete {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--risk-medium, #f5b45d);
  white-space: nowrap;
}
.ret-complete--full {
  color: #5fd6a4;
}
.ret-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
}
.ret-table th,
.ret-table td {
  padding: 5px 9px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
  vertical-align: top;
}
.ret-table th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10.5px;
  white-space: nowrap;
}
.ret-table--records td {
  white-space: normal;
}
.ret-chip {
  display: inline-flex;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.ret-chip--task-done {
  border-color: color-mix(in srgb, #5fd6a4 50%, transparent);
  color: #5fd6a4;
}
.ret-chip--task-doing {
  border-color: color-mix(in srgb, #f5b45d 50%, transparent);
  color: #f5b45d;
}
.ret-warn {
  margin: 0;
  font-size: 11.5px;
  color: var(--risk-medium, #f5b45d);
  line-height: 1.6;
}
.ret-note {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.6;
}
.ret-dim {
  color: var(--text-muted);
  font-size: 10.5px;
}
.ret-block {
  display: block;
}
.ret-ok {
  color: #5fd6a4;
  font-size: 11px;
}
.ret-bad {
  color: var(--risk-critical, #ef4444);
  font-size: 11px;
}
.ret-warn-txt {
  color: var(--risk-medium, #f5b45d);
  font-size: 11px;
}
.ret-cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.ret-cols h4 {
  margin: 0 0 6px;
  font-size: 12.5px;
  color: var(--text-secondary);
}
.ret-fold {
  font-size: 11.5px;
  color: var(--text-secondary);
}
.ret-fold summary {
  cursor: pointer;
  user-select: none;
  color: var(--color-primary);
}
.ret-push-body {
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
}
.ret-push-body p {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.ret-expand {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  font-size: 10.5px;
  font-family: var(--font-mono);
  color: var(--color-primary);
  cursor: pointer;
}
.ret-expand:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.ret-tech-row td {
  background: var(--surface-panel-soft);
  font-size: 10px;
  color: var(--text-muted);
  white-space: normal;
  word-break: break-all;
}
.ret-mono {
  font-family: var(--font-mono);
}
@media (max-width: 1100px) {
  .ret-cols {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
