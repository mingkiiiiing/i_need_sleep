<template>
  <div class="bell-wrap" ref="wrapRef">
    <button
      type="button"
      class="bell-btn"
      :class="{ 'bell-btn--alert': unreadCount > 0 }"
      aria-label="通知中心"
      :title="bellTitle"
      :aria-expanded="String(open)"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 0-3.4 0" />
      </svg>
      <span v-if="unreadCount > 0" class="bell-badge">{{ badgeText }}</span>
    </button>

    <!-- 不用过渡动画：通知面板必须即时可靠地出现/消失，不依赖 rAF -->
    <div v-if="open" class="bell-panel" role="dialog" aria-label="通知中心">
        <div class="bell-panel-head">
          <strong>通知中心</strong>
          <span class="bell-unread">未读 {{ unreadCount }}</span>
          <button
            v-if="unreadCount > 0" type="button" class="bell-readall"
            @click="markAllRead"
          >全部已读</button>
        </div>

        <div class="bell-tabs" role="tablist" aria-label="通知类型">
          <button
            v-for="t in tabs" :key="t.value" type="button" role="tab"
            class="bell-tab" :class="{ 'bell-tab--on': tab === t.value }"
            :aria-selected="String(tab === t.value)"
            @click="tab = t.value"
          >{{ t.label }}</button>
        </div>

        <div v-if="state === 'error'" class="bell-state">
          通知暂时无法更新
          <button type="button" class="bell-retry" @click="load(true)">重试</button>
        </div>
        <div v-else-if="state === 'loading'" class="bell-state">正在加载通知…</div>

        <template v-else>
          <p v-if="!visibleRows.length" class="bell-empty">
            {{ tab === 'predicted' ? '暂无预测预警通知：预测批次接入后，符合规则的未来风险会在这里提示。' : unreadOnlyFiltered ? '暂无未读通知。' : '当前暂无通知。' }}
          </p>
          <ul v-else class="bell-list">
            <li v-for="n in visibleRows" :key="n.id">
              <button
                type="button"
                class="bell-item"
                :class="{ 'bell-item--unread': !n.read }"
                @click="openNotification(n)"
              >
                <span class="bell-item-top">
                  <span class="bell-dot" :class="`bell-dot--${n.event_level || 'info'}`"></span>
                  <span v-if="!n.read" class="bell-unread-dot" aria-label="未读"></span>
                  <span class="bell-chip bell-chip--kind">{{ kindText(n) }}</span>
                  <span class="bell-chip" :class="`bell-chip--${n.event_level}`">{{ levelText(n.event_level) }}</span>
                  <strong class="bell-item-title">{{ n.title }}</strong>
                  <span class="bell-item-time">{{ relativeTime(n.at) }}</span>
                </span>
                <span class="bell-item-line">{{ n.lines?.[0] }}</span>
                <span v-if="n.lines?.[1]" class="bell-item-sub">{{ n.lines[1] }}</span>
                <span v-if="n.read" class="bell-item-status">已读 · {{ statusHint(n) }}</span>
              </button>
            </li>
          </ul>
        </template>

        <div class="bell-foot">
          <RouterLink to="/alerts" class="bell-link" @click="open = false">进入预警中心 →</RouterLink>
        </div>
    </div>
  </div>
</template>

<script setup>
// 全局通知中心（铃铛）：快速获知变化并进入预警中心处理。
// 未读数 = 当前用户未读通知数（不再是"生效预警数"）；打开弹层不自动已读，
// 点击单条 → 标记已读并跳转对应预警事件。已读只代表看过消息，处置仍在预警中心完成。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  NOTIFY_TYPE_TEXT,
  fetchCenterNotifications,
  markNotificationsRead
} from '../../services/alertCenter.js'
import { ALERT_LEVEL_TEXT } from '../../services/alerts.js'

const open = ref(false)
const state = ref('loading')
const notifications = ref([])
const unreadCount = ref(0)
const tab = ref('all')
const wrapRef = ref(null)
let timer = null

const route = useRoute()
const router = useRouter()

const tabs = [
  { value: 'all', label: '全部' },
  { value: 'realtime', label: '实时预警' },
  { value: 'predicted', label: '预测预警' },
  { value: 'process', label: '处理动态' }
]

const REALTIME_KINDS = ['new_event', 'escalation', 'recovery', 'unverified']
const PROCESS_KINDS = ['process', 'push_failure']

const filtered = computed(() => {
  if (tab.value === 'realtime') return notifications.value.filter((n) => REALTIME_KINDS.includes(n.type) && n.event_type !== 'predicted')
  if (tab.value === 'predicted') return notifications.value.filter((n) => REALTIME_KINDS.includes(n.type) && n.event_type === 'predicted')
  if (tab.value === 'process') return notifications.value.filter((n) => PROCESS_KINDS.includes(n.type))
  return notifications.value
})
const visibleRows = computed(() => filtered.value.slice(0, 40))
const unreadOnlyFiltered = computed(() => tab.value === 'all' && notifications.value.length > 0 && filtered.value.every((n) => n.read))

const badgeText = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))
const bellTitle = computed(() => (unreadCount.value ? `${unreadCount.value} 条未读通知` : '通知中心'))

function kindText(n) {
  if (n.type === 'new_event' || n.type === 'escalation') return n.event_type === 'predicted' ? '预测' : '实时'
  if (n.type === 'recovery') return '恢复'
  if (n.type === 'unverified') return '待核实'
  return NOTIFY_TYPE_TEXT[n.type] || '通知'
}
function levelText(level) {
  if (!level || level === 'info') return '提示'
  return ALERT_LEVEL_TEXT[level] || level
}
function statusHint(n) {
  if (n.type === 'recovery') return '事件待复核'
  if (n.type === 'process') return '可在预警中心跟进'
  return ''
}
function relativeTime(iso) {
  const then = Date.parse(String(iso))
  if (!Number.isFinite(then)) return '—'
  const diff = Date.now() - then
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`
  return `${Math.floor(diff / 86_400_000)}天前`
}

function toggle() {
  open.value = !open.value
  if (open.value) load(true)
}

async function load(force = false) {
  try {
    const data = await fetchCenterNotifications({ force })
    notifications.value = data.notifications || []
    unreadCount.value = data.unread_count || 0
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

async function openNotification(n) {
  if (!n.read) {
    try {
      const { unread_count } = await markNotificationsRead({ ids: [n.id] })
      unreadCount.value = unread_count
      n.read = true
    } catch {
      // 已读标记失败不阻断跳转
    }
  }
  open.value = false
  router.push({ path: '/alerts', query: { event: n.event_id } })
}

async function markAllRead() {
  try {
    const { unread_count } = await markNotificationsRead({ all: true })
    unreadCount.value = unread_count
    notifications.value = notifications.value.map((n) => ({ ...n, read: true }))
  } catch {
    // 失败保留原状，下次打开重试
  }
}

function onDocClick(e) {
  if (open.value && wrapRef.value && !wrapRef.value.contains(e.target)) open.value = false
}
function onKeydown(e) {
  if (e.key === 'Escape' && open.value) open.value = false
}

watch(() => route.fullPath, () => {
  open.value = false
})

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 60_000)
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
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
  background: var(--risk-critical, #ef4444);
}

/* 接近不透明的面板：底层页面文字不得穿透影响阅读 */
.bell-panel {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  width: min(440px, calc(100vw - 32px));
  max-height: min(75vh, 640px);
  overflow: auto;
  z-index: 1300;
  display: grid;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border-strong, var(--border-subtle));
  border-radius: var(--radius-panel, 14px);
  background: var(--panel-strong, var(--surface-panel));
  box-shadow: 0 18px 48px rgba(2, 8, 18, 0.4);
}
.bell-panel-head { display: flex; align-items: center; gap: 10px; }
.bell-panel-head strong { font-size: 14px; color: var(--text-primary); }
.bell-unread { font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); }
.bell-readall {
  margin-left: auto;
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  border-radius: 999px;
  font-size: 11px;
  padding: 3px 10px;
  cursor: pointer;
}

.bell-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
.bell-tab {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  border-radius: 999px;
  font-size: 11.5px;
  padding: 3px 12px;
  cursor: pointer;
}
.bell-tab--on { color: var(--text-primary); border-color: var(--color-primary); background: color-mix(in srgb, var(--color-primary) 12%, transparent); }

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
.bell-empty { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--text-secondary); padding: 8px 2px; }

.bell-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.bell-item {
  width: 100%;
  display: grid;
  gap: 3px;
  text-align: left;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
  cursor: pointer;
  color: var(--text-primary);
}
.bell-item--unread { border-color: color-mix(in srgb, var(--color-primary) 45%, transparent); }
.bell-item:hover { border-color: var(--color-primary); }
.bell-item-top { display: flex; align-items: center; gap: 6px; min-width: 0; }
.bell-item-title { font-size: 12.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bell-item-time { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); flex: none; }
.bell-item-line { font-size: 11.5px; color: var(--text-secondary); }
.bell-item-sub { font-size: 10.5px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bell-item-status { font-size: 10px; color: var(--text-muted); }

.bell-chip {
  font-size: 9.5px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  flex: none;
}
.bell-chip--kind { background: var(--surface-panel); }
.bell-chip--light { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, var(--risk-medium) 55%, transparent); }
.bell-chip--moderate { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 60%, transparent); }

.bell-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.bell-dot--light { background: var(--risk-medium, #f5b45d); }
.bell-dot--moderate { background: var(--risk-critical, #ef4444); }
.bell-dot--info { background: var(--color-primary); }
.bell-unread-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: var(--color-primary);
  flex: none;
}

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
</style>
