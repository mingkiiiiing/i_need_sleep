<template>
  <div class="bell-wrap" ref="wrapRef">
    <button
      type="button"
      class="bell-btn"
      :class="{ 'bell-btn--alert': activeTotal > 0 }"
      aria-label="预警通知"
      :title="bellTitle"
      :aria-expanded="String(open)"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </svg>
      <span v-if="activeTotal > 0" class="bell-badge" :class="badgeTone">{{ badgeText }}</span>
    </button>

    <transition name="bell-pop">
      <div v-if="open" class="bell-panel" role="dialog" aria-label="预警通知面板">
        <div class="bell-panel-head">
          <strong>预警通知</strong>
          <span class="bell-chip" :class="enabled ? 'bell-chip--ok' : 'bell-chip--off'">
            {{ enabled ? '自动推送已启用' : '推送未启用（仅评估记录）' }}
          </span>
        </div>

        <div v-if="state === 'error'" class="bell-state">
          预警服务加载失败
          <button type="button" class="bell-retry" @click="load(true)">重试</button>
        </div>
        <div v-else-if="state === 'loading'" class="bell-state">正在加载预警…</div>

        <template v-else>
          <div class="bell-section" v-if="activeTotal > 0">
            <p class="bell-section-title">当前生效（黄 {{ activeCounts.light }} / 红 {{ activeCounts.moderate }}）</p>
            <ul class="bell-list">
              <li v-for="a in activeAlerts" :key="a.id" class="bell-item">
                <span class="bell-dot" :class="`bell-dot--${a.level}`"></span>
                <span class="bell-item-main">
                  <strong>{{ a.station_name }}</strong>
                  <span class="bell-item-sub">叶绿素a {{ a.chla != null ? a.chla.toFixed(1) + ' μg/L' : '—' }} · {{ levelText(a.level) }}</span>
                </span>
                <span class="bell-item-time">{{ formatAlertTime(a.triggered_at) }}</span>
              </li>
            </ul>
          </div>
          <div class="bell-section" v-else>
            <p class="bell-empty">当前无生效预警（阈值 {{ thresholds.light }}/{{ thresholds.moderate }} μg/L）</p>
          </div>

          <div class="bell-section" v-if="recentDeliveries.length">
            <p class="bell-section-title">最近推送回执</p>
            <ul class="bell-list">
              <li v-for="(d, i) in recentDeliveries" :key="i" class="bell-item bell-item--receipt">
                <span class="bell-dot" :class="`bell-dot--${d.status}`"></span>
                <span class="bell-item-main">
                  <strong>{{ channelText(d.channel) }} · {{ deliveryText(d.status) }}</strong>
                  <span class="bell-item-sub">{{ d.detail }}</span>
                </span>
                <span class="bell-item-time">{{ formatAlertTime(d.at) }}</span>
              </li>
            </ul>
          </div>

          <div class="bell-foot">
            <RouterLink to="/alerts" class="bell-link" @click="open = false">查看预警通知页 →</RouterLink>
            <span class="bell-eval-time">巡检 {{ formatAlertTime(lastEvaluatedAt) }}</span>
          </div>
        </template>
      </div>
    </transition>
  </div>
</template>

<script setup>
// 右上角预警通知小组件：点击查看当前生效预警与推送发送/回执情况。
// 未配置通道时如实显示"推送未启用"，不制造假发送记录。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ALERT_LEVEL_TEXT,
  CHANNEL_TEXT,
  DELIVERY_STATUS_TEXT,
  fetchAlertOverview,
  formatAlertTime
} from '../../services/alerts.js'

const open = ref(false)
const state = ref('loading')
const overview = ref(null)
const wrapRef = ref(null)
let timer = null

const activeTotal = computed(() => overview.value?.active_total ?? 0)
const activeCounts = computed(() => overview.value?.active_counts || { light: 0, moderate: 0 })
const activeAlerts = computed(() => overview.value?.active_alerts || [])
const enabled = computed(() => overview.value?.enabled ?? false)
const thresholds = computed(() => overview.value?.thresholds || { light: 10, moderate: 25 })
const lastEvaluatedAt = computed(() => overview.value?.last_evaluated_at)

const recentDeliveries = computed(() => {
  const rows = []
  for (const a of overview.value?.recent_alerts || []) {
    for (const d of a.deliveries || []) rows.push(d)
    if (rows.length >= 5) break
  }
  return rows.slice(0, 5)
})

const badgeTone = computed(() => (activeCounts.value.moderate > 0 ? 'bell-badge--red' : 'bell-badge--yellow'))
const badgeText = computed(() => (activeTotal.value > 99 ? '99+' : String(activeTotal.value)))
const bellTitle = computed(() => (activeTotal.value ? `当前 ${activeTotal.value} 条生效预警` : '预警通知'))

function levelText(level) {
  return ALERT_LEVEL_TEXT[level] || level
}
function channelText(channel) {
  return CHANNEL_TEXT[channel] || channel
}
function deliveryText(status) {
  return DELIVERY_STATUS_TEXT[status] || status
}

function toggle() {
  open.value = !open.value
  if (open.value) load(true)
}

async function load(force = false) {
  try {
    overview.value = await fetchAlertOverview({ force })
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

function onDocClick(e) {
  if (open.value && wrapRef.value && !wrapRef.value.contains(e.target)) open.value = false
}

// 路由切换（含面板内链接跳转）自动收起
const route = useRoute()
watch(() => route.fullPath, () => { open.value = false })

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 60_000)
  document.addEventListener('click', onDocClick)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.bell-wrap { position: relative; }
.bell-btn {
  position: relative;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.bell-btn:hover { color: var(--color-primary); border-color: var(--border-strong); }
.bell-btn--alert { color: var(--risk-medium); border-color: color-mix(in srgb, var(--risk-medium) 55%, transparent); }
.bell-btn svg { width: 20px; height: 20px; pointer-events: none; }

.bell-badge {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  color: #fff;
}
.bell-badge--yellow { background: var(--risk-medium, #f5b45d); }
.bell-badge--red { background: var(--risk-critical, #ff6b6b); }

.bell-panel {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: min(400px, calc(100vw - 32px));
  max-height: min(560px, calc(100vh - 96px));
  overflow: auto;
  z-index: 1300;
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel, 14px);
  background: var(--surface-panel);
  box-shadow: 0 18px 48px rgba(2, 8, 18, 0.28);
}
.bell-pop-enter-active, .bell-pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.bell-pop-enter-from, .bell-pop-leave-to { opacity: 0; transform: translateY(-6px); }

.bell-panel-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.bell-panel-head strong { font-size: 14px; color: var(--text-primary); }
.bell-chip {
  font-size: 10.5px;
  padding: 3px 8px;
  border-radius: 999px;
  white-space: nowrap;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}
.bell-chip--ok { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, var(--risk-low) 45%, transparent); }
.bell-chip--off { color: var(--text-muted); }

.bell-state { font-size: 12.5px; color: var(--text-secondary); padding: 12px 0; }
.bell-retry {
  margin-left: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  border-radius: 999px;
  padding: 2px 12px;
  cursor: pointer;
}

.bell-section { display: grid; gap: 6px; }
.bell-section-title {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}
.bell-empty { margin: 0; font-size: 12.5px; color: var(--text-secondary); padding: 4px 0; }

.bell-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.bell-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.bell-item-main { flex: 1; min-width: 0; display: grid; gap: 1px; }
.bell-item-main strong { font-size: 12.5px; color: var(--text-primary); }
.bell-item-sub { font-size: 11px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bell-item-time { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); flex: none; }

.bell-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.bell-dot--light { background: var(--risk-medium, #f5b45d); }
.bell-dot--moderate { background: var(--risk-critical, #ff6b6b); }
.bell-dot--sent { background: var(--risk-low, #5fd6a4); }
.bell-dot--failed { background: var(--risk-critical, #ff6b6b); }
.bell-dot--skipped { background: var(--text-muted, #7d93a8); }

.bell-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 10px;
}
.bell-link { font-size: 12px; color: var(--color-primary); text-decoration: none; }
.bell-link:hover { text-decoration: underline; }
.bell-eval-time { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
</style>
