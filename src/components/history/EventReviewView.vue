<template>
  <div class="erv">
    <!-- ===== 顶部统计 ===== -->
    <section class="erv-stats" aria-label="复盘统计" data-role="review-stats">
      <div v-if="!listData" class="erv-stat erv-stat--empty">{{ listState === 'error' ? '统计加载失败' : '统计加载中…' }}</div>
      <template v-else>
        <div class="erv-stat">
          <span class="erv-stat-label">事件总数</span>
          <strong class="erv-stat-value">{{ stats.total }}</strong>
          <span class="erv-stat-sub">
            实时 {{ stats.by_type?.realtime ?? 0 }} · 预测 {{ stats.by_type?.predicted ?? 0 }} · 当前筛选 {{ listData.total }} 个
          </span>
        </div>
        <div class="erv-stat">
          <span class="erv-stat-label">关闭率</span>
          <strong class="erv-stat-value">{{ stats.closed?.rate != null ? Math.round(stats.closed.rate * 100) + '%' : '—' }}</strong>
          <span class="erv-stat-sub">已关闭 {{ stats.closed?.num }} / 全部 {{ stats.closed?.den }} · 撤销 {{ stats.closed?.revoked }} · 处理中 {{ stats.closed?.open }}</span>
        </div>
        <div class="erv-stat">
          <span class="erv-stat-label">平均响应</span>
          <strong class="erv-stat-value">{{ stats.avg_response_min?.value != null ? stats.avg_response_min.value : '—' }}<small v-if="stats.avg_response_min?.value != null"> 分钟</small></strong>
          <span class="erv-stat-sub">触发→确认 · 样本 {{ stats.avg_response_min?.samples ?? 0 }}</span>
        </div>
        <div class="erv-stat">
          <span class="erv-stat-label">平均处置时长</span>
          <strong class="erv-stat-value">{{ stats.avg_handling_min?.value != null ? stats.avg_handling_min.value : '—' }}<small v-if="stats.avg_handling_min?.value != null"> 分钟</small></strong>
          <span class="erv-stat-sub">触发→关闭/撤销 · 样本 {{ stats.avg_handling_min?.samples ?? 0 }}</span>
        </div>
      </template>
    </section>

    <!-- ===== 三栏：列表 / 时间线 / 结论 ===== -->
    <div class="erv-main">
      <ReviewEventList
        :events="listData?.events || []"
        :total="listData?.total ?? 0"
        :state="listState"
        :error-text="listError"
        :filters="filters"
        :selected-id="selectedId"
        @update:filters="onFilters"
        @select="selectEvent"
        @retry="fetchList"
      />

      <ReviewTimeline
        v-if="detail"
        :milestones="detail.milestones"
        :detail="detail"
        @replay="jumpReplayFromNode"
      />
      <section v-else class="erv-center-empty" aria-label="事件时间线">
        <StatePanel
          :state="detailState === 'loading' ? 'loading' : detailState === 'error' ? 'error' : 'empty'"
          :title="detailState === 'loading' ? '事件复盘加载中…' : detailState === 'error' ? '事件复盘加载失败' : '未选择事件'"
          :description="detailState === 'error' ? detailError : '从左侧选择一条历史预警事件，查看从发现到关闭的完整证据链。'"
        >
          <button v-if="detailState === 'error'" type="button" class="erv-btn" @click="fetchDetail">重试</button>
        </StatePanel>
      </section>

      <ReviewConclusion :detail="detail" @saved="onNotesSaved" />
    </div>

    <!-- ===== 底部复盘证据标签 ===== -->
    <ReviewEvidenceTabs :detail="detail" @jump-replay="jumpReplay" />
  </div>
</template>

<script setup>
// 事件复盘视图：默认主视图。把监测数据、预测结果、预警通知、处置过程与最终结果
// 以 event_id 串成一条证据链。数据全部来自 /history/* 聚合接口（只读组合）。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StatePanel from '../common/StatePanel.vue'
import ReviewEventList from './ReviewEventList.vue'
import ReviewTimeline from './ReviewTimeline.vue'
import ReviewConclusion from './ReviewConclusion.vue'
import ReviewEvidenceTabs from './ReviewEvidenceTabs.vue'
import { fetchHistoryReview, fetchHistoryReviews, formatBeijing, formatDuration } from '../../services/historyReview.js'

const emit = defineEmits(['ready'])

const route = useRoute()
const router = useRouter()

const DEFAULT_FILTERS = {
  start: '', end: '', type: 'all', level: 'all', status: 'all',
  station: '', plan_adopted: 'all', tasks_done: 'all', push_failed: 'all'
}

const filters = reactive({ ...DEFAULT_FILTERS })
const listState = ref('loading')
const listError = ref('')
const listData = ref(null)

const detailState = ref('idle')
const detailError = ref('')
const detail = ref(null)

const selectedId = computed(() => (typeof route.query.event === 'string' ? route.query.event : ''))

const stats = computed(() => listData.value?.stats || {})

// ---------- 列表 ----------
async function fetchList() {
  listState.value = 'loading'
  listError.value = ''
  try {
    listData.value = await fetchHistoryReviews(filters)
    listState.value = 'ok'
  } catch (err) {
    listData.value = null
    listState.value = 'error'
    listError.value = err?.message || '历史事件列表请求失败'
  }
}

function onFilters(next) {
  Object.assign(filters, next)
  fetchList()
}

// ---------- 事件选择（URL 为事实来源） ----------
function selectEvent(id) {
  if (!id || id === selectedId.value) return
  router.replace({ query: { ...route.query, event: id } }).catch(() => {})
}

async function fetchDetail() {
  const id = selectedId.value
  if (!id) {
    detail.value = null
    detailState.value = 'idle'
    emitReady()
    return
  }
  detailState.value = 'loading'
  detailError.value = ''
  try {
    detail.value = await fetchHistoryReview(id)
    detailState.value = 'ok'
  } catch (err) {
    detail.value = null
    detailState.value = 'error'
    detailError.value = err?.message || '事件复盘详情请求失败'
  }
  emitReady()
}

function emitReady() {
  emit('ready', detailState.value === 'ok' && Boolean(detail.value))
}

watch(selectedId, fetchDetail)

function onNotesSaved() {
  // 复盘意见版本变化后刷新详情（保留当前事件）
  fetchDetail()
}

// ---------- 跳转观测回放（带事件上下文写入 URL） ----------
function jumpReplay(query) {
  router.push({
    query: {
      view: 'replay',
      ...(query.station ? { station: query.station } : {}),
      ...(query.start ? { start: query.start } : {}),
      ...(query.end ? { end: query.end } : {}),
      ...(query.snapshot ? { snapshot: query.snapshot } : {})
    }
  }).catch(() => {})
}

function jumpReplayFromNode(node) {
  jumpReplay({
    station: detail.value?.event?.station_id || '',
    snapshot: node.snapshot_id || '',
    start: '',
    end: ''
  })
}

// ---------- 复盘报告导出（由页面头部按钮调用） ----------
function exportReport() {
  if (!detail.value) return
  const d = detail.value
  const ev = d.event
  const m = d.response_metrics || {}
  const lines = []
  lines.push(`# 太湖蓝藻水华预警事件复盘报告`)
  lines.push('')
  lines.push(`- 事件编号：${ev.no}（${ev.id}）`)
  lines.push(`- 标题：${ev.title}`)
  lines.push(`- 类型：${ev.type === 'predicted' ? '预测预警' : '实时预警'} · 等级：${ev.level_label}`)
  lines.push(`- 站点：${ev.station_name}（${ev.station_id}）· ${ev.province || '—'}`)
  lines.push(`- 事件状态：${ev.status_label} · 证据状态：${{ valid: '有效', recovered: '已恢复', unverified: '待核实' }[ev.evidence?.state] || ev.evidence?.state}`)
  lines.push(`- 首次触发：${formatBeijing(ev.evidence?.triggered_at || ev.created_at)}（北京时间）`)
  lines.push(`- 关闭/撤销：${formatBeijing(ev.closed_at)}`)
  lines.push(`- 导出时间：${formatBeijing(new Date().toISOString())}`)
  lines.push('')
  lines.push('## 一、系统统计（自动生成）')
  lines.push('')
  lines.push(`- 触发→首次确认：${formatDuration(m.trigger_to_confirm?.minutes)}`)
  lines.push(`- 确认→开始处置：${formatDuration(m.confirm_to_start?.minutes)}`)
  lines.push(`- 总处置时长：${m.total_handling?.ongoing ? '进行中' : formatDuration(m.total_handling?.minutes)}`)
  lines.push(`- 预案任务：${m.plan_tasks?.done ?? 0}/${m.plan_tasks?.total ?? 0} 完成（任务完成≠措施被证明有效）`)
  lines.push(`- 模拟推送：${m.pushes?.success ?? 0} 成功 / ${m.pushes?.failed ?? 0} 失败（模拟推送≠真实送达）`)
  lines.push(`- 风险升级：${m.escalated ? '是' : '否'} · 有效恢复观测：${m.valid_recovery ? '有' : '无'} · 曾待核实：${m.unverified_period ? '是' : '否'}`)
  lines.push(`- 重复发生（${m.recurrence?.window_days ?? 7} 天内同站）：${m.recurrence?.count ?? 0} 次`)
  lines.push('')
  lines.push('## 二、事件时间线（当时事实）')
  lines.push('')
  d.milestones.forEach((node) => {
    lines.push(`- ${formatBeijing(node.at)} 【${node.title}】${node.detail || ''}${node.actor ? `（${node.actor}）` : ''}`)
  })
  lines.push('')
  const plan = d.plan_execution || {}
  lines.push('## 三、预案执行')
  lines.push('')
  if (plan.adopted) {
    lines.push(`- 预案：${plan.name}（${plan.version}），采用于 ${formatBeijing(plan.adopted_at)}`)
    lines.push(`- 完成率：${plan.tasks_done}/${plan.tasks_total}`)
    plan.tasks.forEach((task) => {
      lines.push(`  - [${task.status === 'done' ? 'x' : ' '}] ${task.text}（${task.group || '—'}，${task.status}）`)
    })
  } else {
    lines.push('- 本事件未采用应急预案（复盘不做事后推测）')
  }
  lines.push('')
  lines.push('## 四、通知与模拟推送')
  lines.push('')
  lines.push(`- 站内通知 ${d.notifications.length} 条（未读≠未确认事件）`)
  d.notifications.forEach((n) => {
    lines.push(`  - ${formatBeijing(n.at)} ${n.title}（${n.read ? '已读' : '未读'}）`)
  })
  lines.push(`- 模拟推送 ${d.pushes.length} 条（模拟成功≠真实送达）`)
  d.pushes.forEach((p) => {
    lines.push(`  - ${formatBeijing(p.at)} ${p.channel === 'sms' ? '短信' : '邮件'} → ${(p.groups || []).join('、')}：${p.status === 'simulated_success' ? '模拟成功' : '模拟失败'}`)
  })
  lines.push('')
  const notes = d.review_notes || {}
  lines.push('## 五、复盘意见（人工填写，与系统证据分离）')
  lines.push('')
  if (notes.exists) {
    lines.push(`- 版本：第 ${notes.version} 版 · 保存于 ${formatBeijing(notes.saved_at)} · 编辑人 ${notes.editor}`)
    const f = notes.fields || {}
    lines.push(`- 事件原因或可能原因：${f.cause || '（未填写）'}`)
    lines.push(`- 有效措施：${f.effective_measures || '（未填写）'}`)
    lines.push(`- 存在问题：${f.problems || '（未填写）'}`)
    lines.push(`- 是否调整阈值：${f.threshold_adjustment || '（未填写）'}`)
    lines.push(`- 是否修改预案：${f.plan_adjustment || '（未填写）'}`)
    const improvements = f.improvements || []
    if (improvements.length) {
      lines.push('- 后续改进事项：')
      improvements.forEach((row) => {
        lines.push(`  - ${row.item}（责任人 ${row.owner || '—'}，完成时间 ${row.due || '—'}）`)
      })
    }
  } else {
    lines.push('- 尚无人工复盘意见。')
  }
  lines.push('')
  lines.push('---')
  lines.push('数据口径：observed 官方实时观测，未经跨源验证；阈值为筛查口径非监管判定；')
  lines.push('事件关闭≠环境风险解除；历史节点保留当时内容，本文档由系统聚合生成。')

  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `复盘报告_${ev.no}_${ev.station_name}_${(ev.evidence?.triggered_at || ev.created_at || '').slice(0, 10)}.md`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

defineExpose({ exportReport })

onMounted(() => {
  fetchList()
  fetchDetail()
})
</script>

<style scoped>
.erv {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.erv-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}
.erv-stat {
  display: grid;
  gap: 2px;
  padding: 10px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.erv-stat--empty {
  grid-column: 1 / -1;
  align-content: center;
  font-size: 12px;
  color: var(--text-muted);
}
.erv-stat-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.erv-stat-value {
  font-family: var(--font-mono);
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.erv-stat-value small {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
}
.erv-stat-sub {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.erv-main {
  display: grid;
  grid-template-columns: minmax(0, 34fr) minmax(0, 40fr) minmax(0, 26fr);
  gap: 6px;
  align-items: start;
  min-width: 0;
}
.erv-center-empty {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  display: grid;
  min-height: 420px;
  align-items: center;
  padding: 12px;
}
.erv-btn {
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
.erv-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
@media (max-width: 1200px) {
  .erv-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .erv-main {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
