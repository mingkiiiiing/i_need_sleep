<template>
  <main class="alerts-shell">
    <header class="alerts-header">
      <div>
        <p class="alerts-eyebrow">LAKE TWIN · RESPONSE DESK</p>
        <h1>预警与应急预案中心</h1>
      </div>
      <div class="alerts-runtime">
        <span>{{ runtime }}</span><i></i><span class="weather">☁️ 18°C</span><i></i><span class="notice">12</span><span class="gear">⚙</span>
      </div>
    </header>

    <section class="alert-kpis" aria-label="预警概况">
      <article v-for="stat in stats" :key="stat.label" class="alert-kpi" :class="stat.tone">
        <div class="kpi-icon" aria-hidden="true">{{ stat.icon }}</div>
        <div><span>{{ stat.label }}</span><strong>{{ stat.value }}<small>{{ stat.unit }}</small></strong><em>{{ stat.note }}</em></div>
      </article>
    </section>

    <section class="alert-workbench">
      <aside class="alert-queue">
        <div class="queue-tabs">
          <button v-for="tab in severityTabs" :key="tab.value" type="button" :class="{ active: severityFilter === tab.value }" @click="severityFilter = tab.value">{{ tab.label }}</button>
        </div>
        <div class="queue-filters">
          <select v-model="statusFilter" aria-label="预警状态"><option value="all">全部状态</option><option value="new">新预警</option><option value="confirmed">已确认</option><option value="assigned">已指派</option><option value="processing">处理中</option><option value="resolved">已解决</option><option value="closed">已关闭</option></select>
          <select v-model="areaFilter" aria-label="区域"><option value="all">全部区域</option><option value="滨湖区">滨湖区</option><option value="惠山区">惠山区</option><option value="新吴区">新吴区</option></select>
          <button type="button" class="filter-icon" title="刷新预警列表" @click="refreshAlerts">↻</button>
        </div>
        <div class="queue-summary"><span>共 {{ filteredAlerts.length }} 条活动预警</span><span>{{ loading ? '同步中…' : '实时同步' }}</span></div>
        <div class="queue-list" aria-live="polite">
          <button v-for="alert in filteredAlerts" :key="alert.id" type="button" class="queue-item" :class="[{ selected: alert.id === selectedId }, alert.severity]" @click="selectedId = alert.id">
            <div class="queue-item-top"><span class="severity-tag">{{ severityLabel(alert.severity) }}</span><span>{{ alert.time }}</span></div>
            <strong>{{ alert.title }}</strong>
            <small>{{ alert.area }}</small>
            <div class="queue-item-bottom"><span>{{ statusLabel(alert.status) }}</span><span>{{ alert.owner }}</span></div>
          </button>
          <div v-if="!filteredAlerts.length" class="queue-empty">当前筛选条件下暂无活动预警</div>
        </div>
        <div class="queue-pagination"><span>共 {{ alerts.length }} 条</span><button type="button" disabled>‹</button><b>1</b><button type="button" disabled>›</button><select aria-label="分页"><option>1 / 1 页</option></select></div>
      </aside>

      <section v-if="selectedAlert" class="alert-detail">
        <header class="detail-heading">
          <div><div class="detail-title-row"><h2>{{ selectedAlert.title }}</h2><span class="severity-tag large" :class="selectedAlert.severity">{{ severityLabel(selectedAlert.severity) }}</span></div><p>预警ID：{{ selectedAlert.id }}</p></div>
          <div class="detail-tabs"><button class="active" type="button">预警详情</button><button type="button">历史趋势</button></div>
        </header>

        <div class="metric-grid">
          <article><span>预测指标</span><strong>{{ selectedAlert.metric }}</strong></article><article class="hot"><span>预测值</span><strong>{{ selectedAlert.value }} <small>{{ selectedAlert.unit }}</small></strong></article><article><span>阈值</span><strong>{{ selectedAlert.threshold }} <small>{{ selectedAlert.unit }}</small></strong></article>
          <article><span>超标倍数</span><strong>{{ selectedAlert.exceedance }} <small>倍</small></strong></article><article class="hot"><span>发生概率</span><strong>{{ selectedAlert.probability }}<small>%</small></strong></article><article><span>预警时间</span><strong>{{ selectedAlert.date }} {{ selectedAlert.time }}</strong></article>
        </div>

        <div class="detail-split">
          <section class="factor-panel"><h3>主要驱动因素 <small>(TOP 3)</small></h3><div v-for="(factor, index) in selectedAlert.factors" :key="factor.name" class="factor-line"><b :class="`rank-${index + 1}`">{{ index + 1 }}</b><span>{{ factor.name }}</span><i><em :style="{ width: factor.value + '%' }"></em></i><small>贡献度 {{ factor.value }}%</small></div></section>
          <section class="source-panel"><h3>预测来源</h3><dl><dt>模型名称</dt><dd>{{ selectedAlert.model }}</dd><dt>数据来源</dt><dd>{{ selectedAlert.source }}</dd><dt>更新时间</dt><dd>{{ selectedAlert.updatedAt }}</dd><dt>置信度</dt><dd>{{ selectedAlert.confidence }}</dd></dl></section>
        </div>

        <section class="process-panel"><h3>处置流程</h3><div class="process-track"><div v-for="(step, index) in selectedAlert.flow" :key="step.label" class="process-step" :class="{ done: step.done, current: index === currentStep }"><span>{{ index + 1 }}</span><b>{{ step.label }}</b><small>{{ step.time }}</small></div></div></section>

        <div class="action-bar">
          <button type="button" class="action confirm" :disabled="actionLoading" @click="runAction('confirm')">◉ 确认预警</button>
          <button type="button" class="action assign" :disabled="actionLoading" @click="runAction('assign')">♙ 指派</button>
          <button type="button" class="action start" :disabled="actionLoading" @click="runAction('start')">▷ 开始处置</button>
          <button type="button" class="action push" :disabled="actionLoading" @click="runAction('push')">➤ 模拟推送</button>
          <button type="button" class="action resolve" :disabled="actionLoading" @click="runAction('resolve')">⊙ 标记已解决</button>
          <button type="button" class="action close" :disabled="actionLoading" @click="runAction('close')">▣ 关闭预警</button>
        </div>
        <p v-if="actionMessage" class="action-message" :class="{ error: actionError }">{{ actionMessage }}</p>
      </section>

      <aside v-if="selectedAlert" class="plan-panel">
        <header class="plan-heading"><h2>推荐预案</h2><strong>匹配度 <b>{{ selectedAlert.plan.match }}%</b></strong></header>
        <article class="plan-card"><div><strong>{{ selectedAlert.plan.name }}</strong><a href="#plan" @click.prevent="showPlanDetails = !showPlanDetails">预案详情 ›</a></div><p>适用对象：{{ selectedAlert.plan.target }}</p></article>
        <div class="task-heading"><span>措施清单 <small>（建议执行）</small></span><span>负责人</span><span>预计完成时间</span></div>
        <div class="task-list">
          <label v-for="task in selectedAlert.plan.tasks" :key="task.id" class="task-row"><input v-model="task.checked" type="checkbox" @change="recordTaskChange(task)"><span class="checkmark">✓</span><strong>{{ task.label }}</strong><span>{{ task.owner }}</span><time>{{ task.due }}</time></label>
        </div>
        <div v-if="showPlanDetails" class="plan-note">预案更新时间：{{ selectedAlert.plan.updatedAt }}。勾选措施会写入当前处置记录，供后续审计追踪。</div>
        <footer class="plan-footer"><span>预案更新时间：{{ selectedAlert.plan.updatedAt }}</span><button type="button" @click="showPlanDetails = !showPlanDetails">调整预案</button></footer>
      </aside>
    </section>

    <section v-if="selectedAlert" class="logs-grid">
      <article class="log-panel"><header><h2>处置记录</h2><span>当前预警 {{ selectedAlert.id }}</span></header><div class="log-table"><div class="log-head"><span>时间</span><span>处置节点</span><span>处置内容</span><span>处置人</span><span>备注</span></div><div v-for="record in selectedAlert.records.slice(0, 4)" :key="record.time + record.node" class="log-row"><span>{{ record.time }}</span><span>{{ record.node }}</span><span>{{ record.content }}</span><span>{{ record.actor }}</span><span>{{ record.note }}</span></div></div></article>
      <article class="log-panel"><header><h2>审计日志</h2><span>操作留痕</span></header><div class="log-table"><div class="log-head"><span>时间</span><span>操作人</span><span>操作内容</span><span>结果</span><span>IP地址</span></div><div v-for="item in selectedAlert.audit.slice(0, 4)" :key="item.time + item.content" class="log-row"><span>{{ item.time }}</span><span>{{ item.actor }}</span><span>{{ item.content }}</span><span class="success">{{ item.result }}</span><span>{{ item.ip }}</span></div></div></article>
    </section>
    <footer class="alerts-footer"><RouterLink class="button secondary" to="/history">← 查看历史事件</RouterLink><span>最后同步：{{ runtime }}</span></footer>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { alertAction, getAlerts } from '../services/api.js'

const alerts = ref([])
const selectedId = ref('')
const severityFilter = ref('all')
const statusFilter = ref('all')
const areaFilter = ref('all')
const loading = ref(false)
const actionLoading = ref(false)
const actionMessage = ref('')
const actionError = ref(false)
const showPlanDetails = ref(false)
const runtime = ref(new Date().toLocaleString('zh-CN', { hour12: false }))
const severityTabs = [{ value: 'all', label: '全部' }, { value: 'high', label: '高风险' }, { value: 'mid', label: '中风险' }, { value: 'low', label: '低风险' }]

const selectedAlert = computed(() => alerts.value.find((item) => item.id === selectedId.value) || filteredAlerts.value[0] || null)
const filteredAlerts = computed(() => alerts.value.filter((item) => (severityFilter.value === 'all' || item.severity === severityFilter.value) && (statusFilter.value === 'all' || item.status === statusFilter.value) && (areaFilter.value === 'all' || item.area.includes(areaFilter.value))))
const currentStep = computed(() => ({ new: 0, confirmed: 1, assigned: 1, processing: 2, resolved: 3, closed: 4 }[selectedAlert.value?.status] ?? 0))
const stats = computed(() => {
  const active = alerts.value.filter((item) => !['resolved', 'closed'].includes(item.status))
  const processing = alerts.value.filter((item) => item.status === 'processing').length
  const closed = alerts.value.filter((item) => ['resolved', 'closed'].includes(item.status)).length
  const response = alerts.value.filter((item) => item.responseTime && item.responseTime !== '—').map((item) => Number.parseInt(item.responseTime, 10)).filter(Number.isFinite)
  return [{ label: '新预警', value: alerts.value.filter((item) => item.status === 'new').length, unit: '条', note: '较昨日 +3', tone: 'alert', icon: '◉' }, { label: '处理中', value: processing, unit: '条', note: '较昨日 +2', tone: 'watch', icon: '◌' }, { label: '今日关闭', value: closed, unit: '条', note: '较昨日 +6', tone: 'stable', icon: '✓' }, { label: '平均响应时间', value: response.length ? Math.round(response.reduce((a, b) => a + b, 0) / response.length) : 28, unit: '分钟', note: '较昨日 -6 分钟', tone: 'info', icon: '◷' }]
})

function severityLabel(value) { return value === 'high' ? '高风险' : value === 'mid' ? '中风险' : '低风险' }
function statusLabel(value) { return ({ new: '新预警', confirmed: '已确认', assigned: '已指派', processing: '处理中', resolved: '已解决', closed: '已关闭' })[value] || value }
async function refreshAlerts() { loading.value = true; try { alerts.value = await getAlerts(); if (!selectedId.value && alerts.value[0]) selectedId.value = alerts.value[0].id } finally { loading.value = false } }
async function runAction(action) {
  if (!selectedAlert.value) return
  actionLoading.value = true; actionMessage.value = ''; actionError.value = false
  try {
    const updated = await alertAction(selectedAlert.value.id, action, { actor: '当前用户', owner: action === 'assign' || action === 'start' ? '处置组' : undefined })
    const index = alerts.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) alerts.value[index] = updated
    actionMessage.value = `${action === 'push' ? '模拟推送已完成' : statusLabel(updated.status) + '操作已完成'}，记录已同步`
  } catch (error) { actionError.value = true; actionMessage.value = error.message || '操作失败，请稍后重试' } finally { actionLoading.value = false }
}
function recordTaskChange(task) { actionMessage.value = `${task.label}已${task.checked ? '纳入' : '移出'}执行清单`; actionError.value = false }

onMounted(refreshAlerts)
</script>

<style scoped>
.alerts-shell { max-width: 1640px; min-height: 100vh; margin: 0 auto; padding: 18px 24px 40px; color: var(--c-text); }
.alerts-header { display:flex; align-items:center; justify-content:space-between; padding: 0 12px 14px; border-bottom:1px solid var(--c-line-strong); }
.alerts-eyebrow { margin:0 0 4px; color:var(--c-accent); font:700 10px var(--font-mono); letter-spacing:2px; }
.alerts-header h1 { font-size: clamp(24px, 2.2vw, 34px); letter-spacing:.4px; }
.alerts-runtime { display:flex; align-items:center; gap:14px; color:var(--c-text-soft); font:12px var(--font-mono); white-space:nowrap; }.alerts-runtime i { width:1px; height:14px; background:var(--c-line-strong); }.notice { width:20px;height:20px;display:grid;place-items:center;border-radius:50%;background:var(--c-alert);color:var(--c-on-alert);font:700 11px var(--font-body); }.gear{font-size:19px;color:var(--c-text);}
.alert-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin:16px 0 12px; }.alert-kpi { display:flex; align-items:center; gap:14px; min-height:108px; padding:16px 22px; border:1px solid var(--c-line); border-radius:10px; background:linear-gradient(135deg,var(--c-surface-strong),var(--c-surface)); box-shadow:var(--shadow-sm); }.kpi-icon { display:grid; place-items:center; width:58px;height:58px;border-radius:50%;font-size:31px;background:var(--c-surface-soft);color:var(--c-accent); }.alert-kpi.alert .kpi-icon{color:var(--c-alert);background:var(--c-alert-soft)}.alert-kpi.watch .kpi-icon{color:var(--c-watch);background:var(--c-watch-soft)}.alert-kpi.stable .kpi-icon{color:var(--c-stable);background:var(--c-stable-soft)}.alert-kpi.info .kpi-icon{color:var(--c-accent);background:var(--c-accent-soft)}.alert-kpi span{display:block;color:var(--c-text-soft);font-size:13px}.alert-kpi strong{display:block;margin:3px 0;font-size:30px;line-height:1;color:var(--c-text)}.alert-kpi.alert strong{color:var(--c-alert)}.alert-kpi.watch strong{color:var(--c-watch)}.alert-kpi.stable strong{color:var(--c-stable)}.alert-kpi.info strong{color:var(--c-accent)}.alert-kpi small{margin-left:6px;font-size:12px;color:var(--c-text-soft)}.alert-kpi em{font-style:normal;font-size:11px;color:var(--c-muted)}
.alert-workbench { display:grid; grid-template-columns: minmax(280px, .82fr) minmax(500px, 1.42fr) minmax(360px, 1fr); gap:12px; align-items:stretch; }.alert-queue,.alert-detail,.plan-panel,.log-panel{border:1px solid var(--c-line);background:linear-gradient(180deg,var(--c-surface-strong),var(--c-surface));box-shadow:var(--shadow-sm),inset 0 1px 0 var(--glass-highlight);transition:background-color .25s var(--ease-out),border-color .25s var(--ease-out),box-shadow .25s var(--ease-out)}.alert-queue{padding:12px;min-height:600px}.queue-tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-bottom:9px}.queue-tabs button,.detail-tabs button{border:1px solid transparent;border-radius:999px;background:var(--c-surface-soft);color:var(--c-text-soft);padding:7px 4px;font-size:12px;cursor:pointer}.queue-tabs button.active,.queue-tabs button:hover,.detail-tabs button.active{border-color:var(--c-accent);color:var(--c-accent);background:var(--c-accent-soft)}.queue-filters{display:grid;grid-template-columns:1fr 1fr 38px;gap:6px}.queue-filters select,.queue-pagination select{min-height:31px;border:1px solid var(--c-line);border-radius:4px;padding:0 8px;background:var(--c-surface-strong);color:var(--c-text-soft);font-size:12px}.filter-icon{border:1px solid var(--c-line);background:var(--c-surface-soft);color:var(--c-text-soft);border-radius:4px;font-size:18px;cursor:pointer}.queue-summary{display:flex;justify-content:space-between;padding:12px 4px 8px;color:var(--c-muted);font-size:11px}.queue-summary span:last-child{color:var(--c-accent)}.queue-list{display:grid;gap:6px;max-height:470px;overflow:auto;padding-right:3px}.queue-item{display:block;width:100%;text-align:left;padding:10px 11px;border:1px solid var(--c-line);border-radius:6px;background:color-mix(in srgb,var(--c-surface-strong) 78%,var(--c-bg-soft));color:var(--c-text);cursor:pointer;transition:transform .18s var(--ease-out),border-color .18s,background-color .18s}.queue-item:hover{transform:translateX(2px);border-color:var(--c-line-strong);background:var(--c-surface-strong)}.queue-item.selected{border-color:var(--c-accent);background:linear-gradient(90deg,var(--c-accent-soft),var(--c-surface-strong))}.queue-item-top,.queue-item-bottom{display:flex;align-items:center;justify-content:space-between;color:var(--c-muted);font-size:11px}.queue-item strong{display:block;margin:7px 0 3px;font-size:13px}.queue-item small{display:block;color:var(--c-text-soft);font-size:11px}.queue-item-bottom{margin-top:8px}.severity-tag{padding:3px 7px;border:1px solid currentColor;border-radius:3px;font-size:10px}.severity-tag.high{color:var(--c-alert);background:var(--c-alert-soft)}.severity-tag.mid{color:var(--c-watch);background:var(--c-watch-soft)}.severity-tag.low{color:var(--c-stable);background:var(--c-stable-soft)}.severity-tag.large{padding:4px 10px;font-size:11px}.queue-empty{padding:36px 10px;text-align:center;color:var(--c-muted);font-size:12px}.queue-pagination{display:flex;align-items:center;gap:9px;padding:12px 3px 0;color:var(--c-muted);font-size:11px}.queue-pagination button,.queue-pagination b{width:26px;height:26px;display:grid;place-items:center;border:1px solid var(--c-line);border-radius:4px;background:var(--c-surface-soft);color:var(--c-text-soft)}.queue-pagination b{color:var(--c-accent);border-color:var(--c-accent)}.queue-pagination select{margin-left:auto}
.alert-detail{padding:16px;min-width:0}.detail-heading{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--c-line);padding-bottom:10px}.detail-title-row{display:flex;align-items:center;gap:10px}.detail-heading h2{font-size:19px}.detail-heading p{margin-top:5px;color:var(--c-muted);font:11px var(--font-mono)}.detail-tabs{display:flex;gap:22px;align-items:flex-end}.detail-tabs button{border:0;border-bottom:2px solid transparent;border-radius:0;padding:0 0 8px;background:transparent}.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:10px 0}.metric-grid article{min-height:66px;padding:10px 12px;border:1px solid var(--c-line);border-radius:4px;background:var(--c-surface-soft)}.metric-grid span{display:block;color:var(--c-muted);font-size:11px}.metric-grid strong{display:block;margin-top:6px;font-size:17px}.metric-grid strong small{font-size:11px;color:var(--c-text-soft)}.metric-grid .hot strong{color:var(--c-alert);font-size:20px}.detail-split{display:grid;grid-template-columns:1.2fr 1fr;gap:7px}.factor-panel,.source-panel,.process-panel{padding:11px;border:1px solid var(--c-line);border-radius:4px;background:var(--c-surface-soft)}.factor-panel h3,.source-panel h3,.process-panel h3{font-size:13px;margin-bottom:10px}.factor-panel h3 small{color:var(--c-muted);font-size:10px}.factor-line{display:grid;grid-template-columns:22px 1fr 1.2fr 68px;align-items:center;gap:7px;margin:10px 0;font-size:11px}.factor-line b{display:grid;place-items:center;width:17px;height:17px;border-radius:50%;background:var(--c-accent);color:var(--c-accent-ink);font-size:10px}.factor-line b.rank-1{background:var(--c-ai);color:var(--c-on-alert)}.factor-line b.rank-3{background:var(--c-alert);color:var(--c-on-alert)}.factor-line i{height:5px;border-radius:4px;background:var(--c-line);overflow:hidden}.factor-line i em{display:block;height:100%;background:linear-gradient(90deg,var(--c-ai),var(--c-accent));border-radius:inherit}.factor-line small{color:var(--c-muted);font-size:10px;text-align:right}.source-panel dl{display:grid;grid-template-columns:70px 1fr;gap:7px;margin:0;font-size:11px}.source-panel dt{color:var(--c-muted)}.source-panel dd{margin:0;text-align:right;color:var(--c-text-soft)}.process-panel{margin-top:7px}.process-track{display:grid;grid-template-columns:repeat(5,1fr);position:relative;padding-top:2px}.process-track:before{content:"";position:absolute;left:7%;right:7%;top:14px;height:1px;background:var(--c-line-strong)}.process-step{position:relative;z-index:1;display:grid;justify-items:center;gap:4px;color:var(--c-muted);font-size:10px}.process-step span{display:grid;place-items:center;width:27px;height:27px;border:1px solid var(--c-line-strong);border-radius:50%;background:var(--c-surface-strong);font:700 13px var(--font-mono)}.process-step.done span,.process-step.current span{border-color:var(--c-accent);background:var(--c-accent);color:var(--c-accent-ink)}.process-step.current b,.process-step.done b{color:var(--c-accent)}.process-step b{font-size:11px}.process-step small{font:10px var(--font-mono)}
.action-bar{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-top:12px}.action{min-height:38px;border:1px solid transparent;border-radius:4px;color:var(--c-accent-ink);font-weight:700;font-size:12px;cursor:pointer;transition:transform .15s var(--ease-out),filter .15s}.action:hover:not(:disabled){transform:translateY(-1px);filter:brightness(1.08)}.action:disabled{opacity:.5;cursor:not-allowed}.action.confirm,.action.assign,.action.push{background:var(--c-accent-deep)}.action.start{background:var(--c-accent)}.action.resolve{background:var(--c-watch);color:var(--c-on-watch)}.action.close{background:var(--c-stable);color:var(--c-on-stable)}.action-message{margin:8px 0 0;text-align:right;color:var(--c-stable);font-size:11px}.action-message.error{color:var(--c-alert)}
.plan-panel{padding:16px}.plan-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.plan-heading h2{font-size:17px}.plan-heading strong{font-size:12px;color:var(--c-text-soft)}.plan-heading b{color:var(--c-stable);font-size:20px}.plan-card{padding:13px;border:1px solid var(--c-line-strong);border-radius:5px;background:var(--c-accent-soft)}.plan-card>div{display:flex;justify-content:space-between;gap:10px}.plan-card strong{font-size:13px}.plan-card a{color:var(--c-accent);font-size:11px;white-space:nowrap}.plan-card p{margin-top:10px;font-size:11px}.task-heading,.task-row{display:grid;grid-template-columns:1.65fr .75fr .75fr;gap:10px;align-items:center}.task-heading{padding:18px 6px 8px;color:var(--c-muted);font-size:11px}.task-heading span:nth-child(n+2){text-align:right}.task-list{border-radius:5px;background:var(--c-surface-soft)}.task-row{position:relative;padding:11px 8px;border-bottom:1px solid var(--c-line);font-size:11px}.task-row:last-child{border-bottom:0}.task-row input{position:absolute;opacity:0}.checkmark{display:inline-grid;place-items:center;position:absolute;left:8px;width:18px;height:18px;border:1px solid var(--c-line-strong);border-radius:2px;color:transparent}.task-row input:checked + .checkmark{background:var(--c-accent);border-color:var(--c-accent);color:var(--c-accent-ink)}.task-row strong{padding-left:27px;font-weight:600}.task-row span:nth-of-type(2),.task-row time{text-align:right;color:var(--c-text-soft);font-style:normal}.plan-note{margin-top:10px;padding:9px;color:var(--c-muted);background:var(--c-surface-soft);font-size:11px;line-height:1.6}.plan-footer{display:flex;align-items:center;justify-content:space-between;margin-top:16px;color:var(--c-muted);font-size:11px}.plan-footer button{padding:8px 12px;border:1px solid var(--c-accent);border-radius:4px;background:transparent;color:var(--c-accent);font-size:11px;cursor:pointer}
.logs-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.log-panel{padding:12px}.log-panel header{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}.log-panel h2{font-size:16px}.log-panel header span{color:var(--c-muted);font-size:11px}.log-table{border:1px solid var(--c-line);border-radius:4px;overflow:auto}.log-head,.log-row{display:grid;grid-template-columns:1.1fr .8fr 1.4fr 1fr 1.2fr;min-width:650px;gap:8px;padding:8px 9px;font-size:10px}.log-head{color:var(--c-muted);background:var(--c-surface-soft)}.log-row{border-top:1px solid var(--c-line);color:var(--c-text-soft)}.log-row span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.log-row .success{color:var(--c-stable)}.alerts-footer{display:flex;align-items:center;justify-content:space-between;margin-top:14px;color:var(--c-muted);font-size:11px}.alerts-footer .button{min-height:34px;font-size:12px}
.alerts-shell button:focus-visible,.alerts-shell select:focus-visible,.alerts-shell input:focus-visible,.alerts-shell a:focus-visible{outline:3px solid var(--c-accent-glow);outline-offset:2px}
@media (max-width: 1260px){.alert-workbench{grid-template-columns:280px minmax(0,1fr)}.plan-panel{grid-column:1 / -1}.action-bar{grid-template-columns:repeat(3,1fr)}}
@media (max-width: 900px){.alerts-shell{padding:14px}.alerts-runtime{display:none}.alert-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.alert-workbench{grid-template-columns:1fr}.alert-queue{min-height:0}.queue-list{max-height:none}.logs-grid{grid-template-columns:1fr}.detail-split{grid-template-columns:1fr}}
@media (max-width: 560px){.alert-kpis{grid-template-columns:1fr}.alert-kpi{min-height:86px}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.detail-heading{display:block}.detail-tabs{margin-top:12px}.action-bar{grid-template-columns:repeat(2,1fr)}.process-track{min-width:0}.process-track:before{left:9%;right:9%}.process-step{min-width:0;gap:3px}.process-step span{width:24px;height:24px;font-size:11px}.process-step b{font-size:9px;white-space:nowrap}.process-step small{font-size:8px}.task-heading,.task-row{grid-template-columns:1.4fr .7fr .7fr}.alerts-footer{align-items:flex-start;gap:10px;flex-direction:column}}
@media (prefers-reduced-motion: reduce){.queue-item,.action{transition:none}}
</style>
