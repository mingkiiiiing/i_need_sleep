<template>
  <main class="page-alerts">
    <header class="al-head">
      <div class="al-title">
        <p class="al-kicker">ALERTS · CYANOBACTERIA EARLY WARNING</p>
        <h1>预警通知</h1>
      </div>
      <div class="al-head-actions">
        <DataModeBadge mode="observed" label="实时观测" />
        <button type="button" class="al-btn" :disabled="evaluating" @click="runEvaluate">
          {{ evaluating ? '巡检中…' : '立即巡检' }}
        </button>
      </div>
    </header>

    <section class="al-status" aria-label="推送状态">
      <div class="al-status-item">
        <span class="al-status-label">自动推送</span>
        <span class="al-status-value" :class="overview?.enabled ? 'al-ok' : 'al-off'">
          {{ overview?.enabled ? '已启用' : '未启用（仅评估记录）' }}
        </span>
      </div>
      <div class="al-status-item">
        <span class="al-status-label">邮箱通道</span>
        <span class="al-status-value" :class="channelOk('email') ? 'al-ok' : 'al-off'">
          {{ channelOk('email') ? '已配置 SMTP' : '未配置' }}
        </span>
      </div>
      <div class="al-status-item">
        <span class="al-status-label">短信通道</span>
        <span class="al-status-value" :class="channelOk('sms') ? 'al-ok' : 'al-off'">
          {{ channelOk('sms') ? '已配置网关' : '未配置' }}
        </span>
      </div>
      <div class="al-status-item">
        <span class="al-status-label">上次巡检</span>
        <span class="al-status-value al-mono">{{ formatAlertTime(overview?.last_evaluated_at) }}</span>
      </div>
      <p class="al-config-hint">
        判定口径：{{ overview?.threshold_note || `叶绿素a ≥ ${thresholds.moderate} 红色 / ≥ ${thresholds.light} 黄色（μg/L）` }}。
        启用推送：复制 backend/alerts-config.example.json 为 alerts-config.json 并填入 SMTP/短信网关与站点收件人。
      </p>
    </section>

    <div v-if="state === 'error'" class="al-error" role="alert">
      预警服务加载失败（不会回退情景数据）
      <button type="button" class="al-btn" @click="load(true)">重试</button>
    </div>
    <div v-else-if="state === 'loading'" class="al-loading">正在加载预警数据…</div>

    <template v-else>
      <section class="al-block" aria-label="当前生效预警">
        <h2 class="al-block-title">当前生效预警（{{ activeAlerts.length }}）</h2>
        <p v-if="!activeAlerts.length" class="al-empty">当前无生效预警。最新快照内所有站点叶绿素a 均低于 {{ thresholds.light }} μg/L（或未报数）。</p>
        <div v-else class="al-active-grid">
          <article v-for="a in activeAlerts" :key="a.id" class="al-card" :class="`al-card--${a.level}`">
            <div class="al-card-head">
              <span class="al-dot" :class="`al-dot--${a.level}`"></span>
              <strong>{{ a.station_name }}</strong>
              <span class="al-chip" :class="`al-chip--${a.level}`">{{ levelText(a.level) }}</span>
            </div>
            <div class="al-card-row">
              <span>叶绿素a <b class="al-mono">{{ a.chla != null ? a.chla.toFixed(1) : '—' }}</b> μg/L</span>
              <span>{{ a.province || '—' }}</span>
            </div>
            <div class="al-card-row al-dim">
              <span>触发 {{ formatAlertTime(a.triggered_at) }}</span>
              <span>{{ a.kind === 'escalation' ? '由黄色升级' : '新触发' }}</span>
            </div>
            <div class="al-deliveries">
              <span v-for="(d, i) in a.deliveries" :key="i" class="al-delivery" :class="`al-delivery--${d.status}`">
                {{ channelText(d.channel) }}{{ channelText(d.channel) === '推送' ? '' : channelAction(d) }}· {{ deliveryText(d.status) }}
              </span>
            </div>
          </article>
        </div>
      </section>

      <section class="al-block" aria-label="预警历史与推送回执">
        <h2 class="al-block-title">
          预警历史与推送回执
          <span class="al-filter">
            <button
              v-for="f in filters"
              :key="f.value"
              type="button"
              class="al-filter-btn"
              :class="{ 'al-filter-btn--on': historyStatus === f.value }"
              @click="historyStatus = f.value"
            >{{ f.label }}</button>
          </span>
        </h2>
        <p v-if="!history.length" class="al-empty">暂无告警记录。</p>
        <ul v-else class="al-history">
          <li v-for="a in history" :key="a.id + a.status" class="al-history-item" :class="`al-history-item--${a.level}`">
            <div class="al-history-main">
              <span class="al-dot" :class="`al-dot--${a.level}`"></span>
              <strong>{{ a.station_name }}</strong>
              <span class="al-chip al-chip--sm" :class="`al-chip--${a.level}`">{{ levelText(a.level) }}</span>
              <span class="al-chip al-chip--sm" :class="a.status === 'active' ? 'al-chip--active' : 'al-chip--resolved'">
                {{ a.status === 'active' ? '生效中' : resolveText(a) }}
              </span>
              <span class="al-history-chla al-mono">chla {{ a.chla != null ? a.chla.toFixed(1) : '—' }}</span>
            </div>
            <div class="al-history-side">
              <span class="al-dim">{{ formatAlertTime(a.triggered_at) }}</span>
              <span v-for="(d, i) in a.deliveries" :key="i" class="al-delivery al-delivery--sm" :class="`al-delivery--${d.status}`"
                    :title="d.detail + (d.receipt ? ` | 回执：${d.receipt}` : '')">
                {{ channelText(d.channel) }}· {{ deliveryText(d.status) }}
              </span>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </main>
</template>

<script setup>
// 预警通知页：当前生效告警 + 历史事件与每通道投递回执（含失败原因/网关回执，悬停可见）。
// 手动"立即巡检"触发一次评估（等价后台线程单轮）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import DataModeBadge from '../components/common/DataModeBadge.vue'
import {
  ALERT_LEVEL_TEXT,
  ALERT_RESOLVE_REASON_TEXT,
  DELIVERY_STATUS_TEXT,
  CHANNEL_TEXT,
  evaluateAlerts,
  fetchAlertHistory,
  fetchAlertOverview,
  formatAlertTime
} from '../services/alerts.js'

const state = ref('loading')
const overview = ref(null)
const historyAll = ref([])
const historyStatus = ref('all')
const evaluating = ref(false)
let timer = null

const filters = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '生效中' },
  { value: 'resolved', label: '已恢复' }
]

const thresholds = computed(() => overview.value?.thresholds || { light: 10, moderate: 25 })
const activeAlerts = computed(() => overview.value?.active_alerts || [])
const history = computed(() =>
  historyStatus.value === 'all' ? historyAll.value : historyAll.value.filter((a) => a.status === historyStatus.value)
)

function channelOk(name) {
  return Boolean(overview.value?.channels?.[name]?.configured)
}
function levelText(level) {
  return ALERT_LEVEL_TEXT[level] || level
}
function channelText(channel) {
  return CHANNEL_TEXT[channel] || channel
}
function deliveryText(status) {
  return DELIVERY_STATUS_TEXT[status] || status
}
function resolveText(a) {
  return a.resolve_reason ? ALERT_RESOLVE_REASON_TEXT[a.resolve_reason] || '已恢复' : '已恢复'
}
function channelAction(d) {
  return d.status === 'sent' ? '已' : ''
}

async function load(force = false) {
  if (force) state.value = 'loading'
  try {
    const [ov, historyData] = await Promise.all([
      fetchAlertOverview({ force }),
      fetchAlertHistory({ force, status: 'all' })
    ])
    overview.value = ov
    historyAll.value = historyData
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

async function runEvaluate() {
  evaluating.value = true
  try {
    await evaluateAlerts()
    await load(true)
  } catch {
    state.value = 'error'
  } finally {
    evaluating.value = false
  }
}

watch(historyStatus, () => {})

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 60_000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.page-alerts {
  max-width: 1180px;
  margin: 0 auto;
  padding: 14px 20px 32px;
  display: grid;
  gap: 12px;
}
.al-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.al-kicker { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.22em; color: var(--color-primary); margin: 0; }
.al-title h1 { margin: 2px 0 0; font-family: var(--font-display); font-size: clamp(20px, 2vw, 26px); color: var(--text-primary); }
.al-head-actions { display: flex; align-items: center; gap: 10px; }

.al-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 34px;
  padding: 2px 14px;
  cursor: pointer;
}
.al-btn:disabled { opacity: 0.6; cursor: default; }

.al-status {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel, 14px);
  background: var(--surface-panel);
  padding: 12px 14px;
}
.al-status-item { display: grid; gap: 2px; }
.al-status-label { font-size: 11px; color: var(--text-muted); }
.al-status-value { font-size: 13px; font-weight: 650; color: var(--text-primary); }
.al-ok { color: var(--risk-low, #5fd6a4); }
.al-off { color: var(--text-muted); }
.al-mono { font-family: var(--font-mono); }
.al-config-hint {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--text-muted);
  border-top: 1px dashed var(--border-subtle);
  padding-top: 8px;
}

.al-error, .al-loading {
  border: 1px dashed var(--border-subtle);
  border-radius: 12px;
  padding: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 12px;
}

.al-block { display: grid; gap: 8px; }
.al-block-title {
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 15px;
  color: var(--text-primary);
}
.al-filter { display: inline-flex; gap: 4px; }
.al-filter-btn {
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  border-radius: 999px;
  font-size: 11px;
  padding: 3px 12px;
  cursor: pointer;
}
.al-filter-btn--on { color: var(--text-primary); border-color: var(--color-primary); }

.al-empty { margin: 0; font-size: 12.5px; color: var(--text-muted); border: 1px dashed var(--border-subtle); border-radius: 12px; padding: 14px; }

.al-active-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; }
.al-card {
  display: grid;
  gap: 7px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  padding: 11px 13px;
}
.al-card--light { border-color: color-mix(in srgb, var(--risk-medium, #f5b45d) 55%, transparent); background: color-mix(in srgb, var(--risk-medium, #f5b45d) 10%, var(--surface-panel)); }
.al-card--moderate { border-color: color-mix(in srgb, var(--risk-critical, #ff6b6b) 60%, transparent); background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 11%, var(--surface-panel)); }
.al-card-head { display: flex; align-items: center; gap: 7px; }
.al-card-head strong { font-size: 14px; color: var(--text-primary); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.al-chip { font-size: 10.5px; padding: 2px 8px; border-radius: 999px; white-space: nowrap; border: 1px solid var(--border-subtle); color: var(--text-secondary); }
.al-chip--sm { font-size: 10px; padding: 1px 7px; }
.al-chip--light { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 55%, transparent); }
.al-chip--moderate { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, var(--risk-critical) 60%, transparent); }
.al-chip--active { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, var(--risk-critical) 45%, transparent); }
.al-chip--resolved { color: var(--text-muted); }
.al-card-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.al-card-row b { color: var(--text-primary); }
.al-dim { color: var(--text-muted); font-size: 11px; }

.al-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.al-dot--light { background: var(--risk-medium, #f5b45d); }
.al-dot--moderate { background: var(--risk-critical, #ff6b6b); }

.al-deliveries { display: flex; flex-wrap: wrap; gap: 6px; }
.al-delivery {
  font-size: 10.5px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.al-delivery--sm { font-size: 10px; padding: 1px 7px; }
.al-delivery--sent { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.al-delivery--failed { color: var(--risk-critical, #ff6b6b); border-color: color-mix(in srgb, var(--risk-critical) 55%, transparent); }
.al-delivery--skipped { color: var(--text-muted); }

.al-history { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.al-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  border: 1px solid var(--border-subtle);
  border-left-width: 3px;
  border-radius: 10px;
  background: var(--surface-panel);
  padding: 8px 12px;
}
.al-history-item--light { border-left-color: var(--risk-medium, #f5b45d); }
.al-history-item--moderate { border-left-color: var(--risk-critical, #ff6b6b); }
.al-history-main { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.al-history-main strong { font-size: 13px; color: var(--text-primary); }
.al-history-chla { font-size: 11px; color: var(--text-secondary); }
.al-history-side { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
</style>
