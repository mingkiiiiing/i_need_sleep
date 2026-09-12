<template>
  <!--
    真实快照回放时间轴（kepler.gl 播放器手法升级版）
    根元素只做内容布局（flex 行：播放钮 + 轨道 + 状态章）。
    绝对定位浮层壳（bottom:12px 居中 / width:min(680px,46%) / 面板底色描边圆角）
    由集成页面提供（建议包一层 .rc-timeline 定位壳），本组件不自带定位。
  -->
  <div ref="rootRef" class="rpt" role="group" aria-label="真实快照回放时间轴">
    <template v-if="snaps.length">
      <!-- 1) 播放键：圆形主色钮，播放/暂停图标切换；定时器仍在父层，这里只上报意图 -->
      <button
        type="button"
        class="rpt-play"
        :aria-label="playing ? '暂停回放' : '播放回放'"
        @click="emit('toggle-play')"
      >
        <svg v-if="!playing" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path d="M8 5v14l11-7z" fill="currentColor" />
        </svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
          <path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor" />
        </svg>
      </button>

      <!-- 2) 轨道：底层灰轨 + 主色进度填充；tablist 键盘 ←/→/Home/End -->
      <div
        class="rpt-track"
        :class="{ 'rpt-track--dense': isDense }"
        role="tablist"
        aria-label="快照刻度"
        tabindex="0"
        @keydown="onTrackKeydown"
      >
        <div class="rpt-rail" :style="railStyle" aria-hidden="true">
          <div class="rpt-fill" :style="{ width: fillPct }"></div>
        </div>
        <button
          v-for="(snap, i) in snaps"
          :key="snap.snapshot_id"
          type="button"
          role="tab"
          class="rpt-tick"
          :class="{
            'rpt-tick--active': i === activeIndex,
            'rpt-tick--latest': snap.snapshot_id === timeline?.latest_snapshot_id,
            'rpt-tick--warn': (Number(snap.warning_count) || 0) > 0
          }"
          :aria-selected="String(i === activeIndex)"
          :title="tickTitle(snap)"
          @click="emit('select', snap.snapshot_id)"
        >
          <span class="rpt-dot" aria-hidden="true"></span>
          <!-- 3) 预警次数迷你条（kepler.gl 分布条手法）：只用真实 warning_count，0 不出条，全 0 整行不渲染 -->
          <span v-if="hasWarnRow" class="rpt-barzone" aria-hidden="true">
            <span
              v-if="warnBarHeight(snap) > 0"
              class="rpt-bar"
              :style="{ height: warnBarHeight(snap) + 'px' }"
            ></span>
          </span>
          <!-- 4) 刻度标签：过密时贪心抽稀，最新刻度与 active 刻度强制显示 -->
          <span v-if="visibleSet.has(i)" class="rpt-label">{{ tickLabel(snap) }}</span>
        </button>
      </div>

      <!-- 6) 状态章：● 最新（绿）/ ⟲ 历史回放（琥珀），title 说明当前快照时间 -->
      <span class="rpt-state" :class="{ 'rpt-state--replay': !isLatest }" :title="stateTitle">
        {{ isLatest ? '● 最新' : '⟲ 历史回放' }}
      </span>
    </template>
  </div>
</template>

<script setup>
// 综合驾驶舱 · 真实快照回放时间轴（升级版）
// 数据契约：
//   props.timeline        { snapshots: [{ snapshot_id, latest_observed_at, retrieved_at_utc,
//                            class_compliance:{num,den}, warning_count, chla_mean }], latest_snapshot_id } | null
//   props.activeSnapshotId String，'' = 最新
//   props.playing         Boolean，播放定时器在父层（2200ms/步），本组件只上报意图
//   emits: select(snapshot_id) / toggle-play()
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { formatStamp } from '../../services/realtime.js'

const props = defineProps({
  timeline: { type: Object, default: null },
  activeSnapshotId: { type: String, default: '' },
  playing: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'toggle-play'])

// ---------- 基础派生 ----------
const snaps = computed(() => props.timeline?.snapshots || [])

// isLatest 沿用原口径：'' 或等于 latest_snapshot_id 都算「最新」
const isLatest = computed(
  () => !props.activeSnapshotId || props.activeSnapshotId === props.timeline?.latest_snapshot_id
)

// active 刻度索引；'' → 最新一档，陈旧 id 兜底也归最新一档
const activeIndex = computed(() => {
  const n = snaps.value.length
  if (!n) return -1
  if (isLatest.value) return n - 1
  const i = snaps.value.findIndex((s) => s.snapshot_id === props.activeSnapshotId)
  return i >= 0 ? i : n - 1
})

// ---------- 2) 轨道进度填充 ----------
// 灰轨两端各内缩半格（50/N %），使填充终点正好落在 active 圆点圆心：
// 圆点 i 位于 (i+0.5)/N，相对内缩后的轨段即 i/(N-1)，与任务口径一致。
const railStyle = computed(() => {
  const n = snaps.value.length
  if (n < 2) return { left: '50%', right: '50%' }
  const inset = `${(50 / n).toFixed(3)}%`
  return { left: inset, right: inset }
})

const fillPct = computed(() => {
  const n = snaps.value.length
  if (!n) return '0%'
  if (n === 1) return '100%'
  const pct = (activeIndex.value / (n - 1)) * 100
  return `${Math.max(0, Math.min(100, pct)).toFixed(3)}%`
})

// ---------- 3) 预警次数迷你条（真实数据，绝不造占位） ----------
const BAR_MAX_H = 18
const maxWarn = computed(() =>
  snaps.value.reduce((m, s) => Math.max(m, Number(s.warning_count) || 0), 0)
)
const hasWarnRow = computed(() => maxWarn.value > 0)

function warnBarHeight(snap) {
  const c = Number(snap.warning_count) || 0
  if (c <= 0 || !maxWarn.value) return 0
  // 按 warning_count/maxWarn 归一化；保底 3px，count=1 也不至于不可感知
  return Math.max(3, Math.round((c / maxWarn.value) * BAR_MAX_H))
}

// ---------- 4) 刻度标签抽稀（参考 ForecastTimeline.visibleTicks 贪心写法） ----------
const MIN_LABEL_GAP = 56
// 侧边固定件宽度估算：播放钮 44 + 两侧 gap 20 + 状态章约 64
const SIDE_CHROME = 128
const TRACK_FALLBACK_W = 600

const rootRef = ref(null)
const rootWidth = ref(0)
let resizeObs = null

onMounted(() => {
  if (typeof ResizeObserver === 'undefined' || !rootRef.value) return
  resizeObs = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect?.width
    if (typeof w === 'number') rootWidth.value = w
  })
  resizeObs.observe(rootRef.value)
})

onBeforeUnmount(() => {
  if (resizeObs) {
    resizeObs.disconnect()
    resizeObs = null
  }
})

const visibleSet = computed(() => {
  const set = new Set()
  const n = snaps.value.length
  if (!n) return set
  const trackW = Math.max(0, rootWidth.value - SIDE_CHROME) || TRACK_FALLBACK_W
  const cell = trackW / n
  const step = cell >= MIN_LABEL_GAP ? 1 : Math.ceil(MIN_LABEL_GAP / cell)
  let lastShown = -Infinity
  for (let i = 0; i < n; i++) {
    if (i - lastShown >= step) {
      set.add(i)
      lastShown = i
    }
  }
  // 最新刻度与 active 刻度强制显示
  set.add(n - 1)
  if (activeIndex.value >= 0) set.add(activeIndex.value)
  return set
})

// 密集态：格子宽小于圆点直径（9px）时圆点互相重叠成实心带，读起来像红色进度条——
// 隐藏圆点只留直方图条+轨道+进度填充（kepler.gl 分布条形态）
const isDense = computed(() => {
  const n = snaps.value.length
  if (!n) return false
  const trackW = Math.max(0, rootWidth.value - SIDE_CHROME) || TRACK_FALLBACK_W
  return trackW / n < 9
})

// ---------- 文案（沿用原口径） ----------
function stampTick(snap) {
  return formatStamp(snap.latest_observed_at || snap.retrieved_at_utc)
}

function tickLabel(snap) {
  const m = String(snap.latest_observed_at || snap.retrieved_at_utc || '').match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/
  )
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '—'
}

function tickTitle(snap) {
  const cc = snap.class_compliance || {}
  return `${stampTick(snap)} · 达标 ${cc.num ?? '—'}/${cc.den ?? '—'} · 预警 ${snap.warning_count ?? 0}`
}

const activeSnap = computed(() => snaps.value[activeIndex.value] || null)
const stateTitle = computed(() =>
  activeSnap.value ? `当前快照：${stampTick(activeSnap.value)}` : ''
)

// ---------- 5) 键盘：←/→ 相邻步进，Home/End 跳首末 ----------
function onTrackKeydown(e) {
  const n = snaps.value.length
  if (!n) return
  const cur = activeIndex.value
  let target = -1
  if (e.key === 'ArrowLeft') target = Math.max(0, cur - 1)
  else if (e.key === 'ArrowRight') target = Math.min(n - 1, cur + 1)
  else if (e.key === 'Home') target = 0
  else if (e.key === 'End') target = n - 1
  if (target < 0 || target === cur) return
  e.preventDefault()
  const id = snaps.value[target]?.snapshot_id
  if (id) emit('select', id)
}
</script>

<style scoped>
.rpt {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-width: 0;
}

/* ===== 1) 播放键：44px 圆形主色钮 ===== */
.rpt-play {
  appearance: none;
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: 999px;
  border: none;
  background: var(--c-accent);
  color: var(--c-accent-ink, #06201d);
  display: grid;
  place-items: center;
  cursor: pointer;
  box-shadow: 0 2px 10px color-mix(in srgb, var(--c-accent) 35%, transparent);
  transition: transform 120ms ease, filter 120ms ease;
}
.rpt-play:hover { filter: brightness(1.08); }
.rpt-play:active { transform: scale(0.95); }

.rpt-play:focus-visible,
.rpt-track:focus-visible,
.rpt-tick:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

/* ===== 2) 轨道：灰轨 + 主色填充 + 圆点 ===== */
.rpt-track {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  align-items: stretch;
  padding: 0 2px;
  border-radius: 6px;
  /* 快照数很多（>100）时刻度总宽超轨道：裁剪+允许收缩，呈直方图密排态 */
  overflow: hidden;
}
.rpt-rail {
  position: absolute;
  top: 7px;
  height: 3px;
  border-radius: 2px;
  background: var(--border-subtle);
}
.rpt-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  width: 0;
  border-radius: 2px;
  background: var(--c-accent);
  transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1);
}

.rpt-tick {
  appearance: none;
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  border: none;
  background: transparent;
  padding: 16px 2px 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  color: var(--text-muted);
}
.rpt-tick:hover { color: var(--text-primary); }
.rpt-tick--active { color: var(--text-primary); }

.rpt-dot {
  position: absolute;
  top: 4px;
  left: 50%;
  transform: translateX(-50%);
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--border-subtle);
}
/* 配色沿用原口径：最新=绿，有预警=高警红，active=主色 + 脉冲光圈（后者优先） */
.rpt-tick--latest .rpt-dot { background: var(--risk-low, #22c55e); }
.rpt-tick--warn .rpt-dot { background: var(--risk-critical, #ef4444); }
.rpt-tick--active .rpt-dot {
  background: var(--c-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-accent) 30%, transparent);
}
/* 密集态（格子 <9px）：圆点重叠成实心带，隐藏之 */
.rpt-track--dense .rpt-dot { display: none; }

/* ===== 3) 预警迷你条（kepler.gl 分布条手法） ===== */
.rpt-barzone {
  height: 20px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.rpt-bar {
  width: 4px;
  border-radius: 1px 1px 0 0;
  background: var(--risk-critical, var(--c-alert, #ff6b6b));
}

/* ===== 4) 刻度标签 ===== */
.rpt-label {
  font-family: var(--font-mono);
  font-size: 9.5px;
  line-height: 1.2;
  white-space: nowrap;
}
/* 首末可见标签内锚：标签宽大于密集格子时避免溢出轨道被裁剪 */
.rpt-tick:first-child .rpt-label { transform: translateX(50%); }
.rpt-tick:last-child .rpt-label { transform: translateX(-50%); }

/* ===== 6) 状态章 ===== */
.rpt-state {
  flex: none;
  font-family: var(--font-mono);
  font-size: 10.5px;
  white-space: nowrap;
  color: var(--risk-stable, var(--c-stable, #5fd6a4));
  cursor: default;
}
.rpt-state--replay { color: var(--risk-medium, #facc15); }

/* reduced-motion：脉冲改静态光圈，填充不做过渡 */
@media (prefers-reduced-motion: no-preference) {
  .rpt-tick--active .rpt-dot {
    animation: rpt-pulse 1.8s ease-out infinite;
  }
  @keyframes rpt-pulse {
    0% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--c-accent) 30%, transparent); }
    100% { box-shadow: 0 0 0 10px color-mix(in srgb, var(--c-accent) 0%, transparent); }
  }
}
@media (prefers-reduced-motion: reduce) {
  .rpt-fill { transition: none; }
  .rpt-play { transition: none; }
}
</style>
