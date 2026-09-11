<template>
  <div class="ftl" role="group" aria-label="预测时间轴">
    <!-- 一级：时间尺度档（仅预测推演模式） -->
    <div v-if="showScales && scales.length" class="ftl-scales" role="group" aria-label="预测时间尺度">
      <button
        v-for="scale in scales"
        :key="scale.id"
        type="button"
        class="ftl-scale"
        :class="{ active: activeScale === scale.id }"
        :aria-pressed="String(activeScale === scale.id)"
        data-role="ftl-scale"
        :data-scale="scale.id"
        @click="$emit('select-scale', scale.id)"
      >
        <b>{{ scale.label }}</b>
        <small>{{ scale.hint }}</small>
      </button>
    </div>

    <div class="ftl-row">
      <!-- 步进：上一停靠点 -->
      <button
        type="button"
        class="ftl-step"
        aria-label="上一停靠点"
        :disabled="prevDisabled"
        data-role="ftl-step-prev"
        @click="step(-1)"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 5v14L7 12z" /></svg>
      </button>

      <button
        type="button"
        class="ftl-play"
        :aria-label="playing ? '暂停推演' : '播放推演'"
        data-role="ftl-play"
        @click="$emit('toggle-play')"
      >
        <svg v-if="!playing" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" /></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.6v14H7zM13.4 5H17v14h-3.6z" /></svg>
      </button>

      <!-- 步进：下一停靠点 -->
      <button
        type="button"
        class="ftl-step"
        aria-label="下一停靠点"
        :disabled="nextDisabled"
        data-role="ftl-step-next"
        @click="step(1)"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5v14l10-7z" /></svg>
      </button>

      <div class="ftl-zone">
        <div
          ref="trackRef"
          class="ftl-track"
          role="slider"
          tabindex="0"
          aria-label="推演时间轴"
          :aria-valuemin="0"
          :aria-valuemax="sliderMax"
          :aria-valuenow="sliderNow"
          :aria-valuetext="sliderText"
          @pointerdown="onTrackPointer"
          @keydown="onTrackKeydown"
        >
          <div class="ftl-rail" aria-hidden="true"></div>
          <!-- 尺度段分隔（预测段内部的三档分界） -->
          <span
            v-for="cut in scaleCuts"
            :key="`cut-${cut}`"
            class="ftl-cut"
            :style="{ left: `${cut}%` }"
            aria-hidden="true"
          ></span>
          <div class="ftl-fill" :style="{ width: `${selectedPos}%` }" aria-hidden="true"></div>
          <span
            v-for="stop in stops"
            :key="`dot-${stop.id}`"
            class="ftl-stopdot"
            :class="[`ftl-stopdot--${stop.kind}`, { 'ftl-stopdot--on': stop.id === modelValue }]"
            :style="{ left: `${stop.pos}%` }"
            aria-hidden="true"
          ></span>
          <span
            class="ftl-handle"
            :style="{ left: `${selectedPos}%` }"
            aria-hidden="true"
          ></span>
        </div>
        <div class="ftl-ticks" aria-hidden="true">
          <span
            v-for="stop in visibleTicks"
            :key="`tick-${stop.id}`"
            class="ftl-tick"
            :class="[
              `ftl-tick--${stop.kind}`,
              { 'ftl-tick--on': stop.id === modelValue, 'ftl-tick--start': stop.pos < 9, 'ftl-tick--end': stop.pos > 91 }
            ]"
            :style="{ left: `${stop.pos}%` }"
          >{{ stop.tick }}</span>
        </div>
        <!-- kepler.gl 式停靠点数值分布迷你条：stopValues 为空时整条隐藏（不渲染占位） -->
        <div v-if="barShown" class="ftl-bars" role="group" aria-label="各停靠点数值分布">
          <button
            v-for="bar in barEntries"
            :key="`bar-${bar.id}`"
            type="button"
            class="ftl-bar"
            :class="{ 'ftl-bar--on': bar.id === modelValue }"
            :style="{ left: `${bar.pos}%` }"
            :aria-label="barLabel(bar)"
            :aria-pressed="String(bar.id === modelValue)"
            data-role="ftl-bar"
            @click="selectStop(bar.id)"
          ><i :style="{ height: `${bar.pct}%` }"></i></button>
        </div>
      </div>

      <div class="ftl-status">
        <b data-role="ftl-status-title">{{ selected ? selected.title : '—' }}</b>
        <span data-role="ftl-status-sub">{{ selected ? selected.sub : '' }}</span>
      </div>

      <button type="button" class="ftl-refresh" aria-label="刷新观测数据" data-role="ftl-refresh" @click="$emit('refresh')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5V2L7.5 6 12 10V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z" /></svg>
      </button>
    </div>

    <!-- 播放速度档（定时器在父组件，本组件只发 speed-change） -->
    <div class="ftl-foot">
      <div class="ftl-speeds" role="group" aria-label="播放速度">
        <span class="ftl-speeds-cap" aria-hidden="true">速度</span>
        <button
          v-for="(s, i) in SPEEDS"
          :key="s.ms"
          type="button"
          class="ftl-speed"
          :class="{ active: i === speedIdx }"
          :aria-pressed="String(i === speedIdx)"
          :data-speed="s.ms"
          data-role="ftl-speed"
          @click="setSpeed(i)"
        >{{ s.label }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
// 预测时间轴（两级控制）：
// 一级 = 时间尺度档（短临 1-3 天 / 趋势 7-15 天 / 中长期 30-90 天）；
// 二级 = 轨道上具体预测时刻（T+1…T+90，实测段为逐日快照）。
// 拖拽/点击吸附最近停靠点；未来档位是规则研判不是逐日数值预报，
// 相邻 T 点共享该尺度档的研判结论，仅预测日期不同。
//
// 播放器扩展（借鉴 kepler.gl / Leaflet.TimeDimension）：
// - 上一帧/下一帧步进按钮（吸附相邻停靠点，emit update:modelValue）；
// - 0.5×/1×/2×/4× 速度档 pill（emit speed-change = 毫秒数；定时器在父组件，
//   本组件仅维护 UI 选中态，选中态初始值跟随 props.speedMs）；
// - 轨道下方停靠点数值分布迷你条（props.stopValues 可选，空数组时整条隐藏）；
// - 轨道 role="slider" 键盘操作：←/→ 步进，Home/End 跳首末。
import { computed, ref, watch } from 'vue'

const props = defineProps({
  // [{ id, kind: 'observed'|'today'|'short'|'mid'|'long', scale?, pos: 0-100, tick, title, sub }]
  stops: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  playing: { type: Boolean, default: false },
  // 预测推演模式显示尺度档；实测回放隐藏
  showScales: { type: Boolean, default: false },
  // [{ id, label, hint, first, last }]，first/last 为该尺度档首个/末个停靠点 id
  scales: { type: Array, default: () => [] },
  // 父组件播放循环的每步间隔（毫秒）。组件不持有定时器，仅用于初始化/同步速度档选中态
  speedMs: { type: Number, default: 1800 },
  // [{ id, value }] 各停靠点数值（可选）。空数组或与 stops 无交集时隐藏迷你条
  stopValues: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:modelValue', 'toggle-play', 'refresh', 'select-scale', 'speed-change'])

const trackRef = ref(null)
let dragging = false

const selected = computed(() => props.stops.find((s) => s.id === props.modelValue) || null)
const selectedPos = computed(() => (selected.value ? selected.value.pos : 0))
const activeScale = computed(() => selected.value?.scale || '')

// 刻度标签抽稀：观测段逐日停靠点密集（pos 3–42% 区间可挤下 10+ 天），
// 相邻日期标签宽度>间距时相互压盖成乱码。规则：未来段/今日刻度永远显示，
// 纯观测日按最小间距（百分点）贪心抽稀；被抽稀的当前选中刻度强制补回。
const MIN_TICK_GAP = 7
const visibleTicks = computed(() => {
  const stops = props.stops
  if (!stops.length) return []
  const shown = []
  let lastPos = -Infinity
  for (const s of stops) {
    if (s.kind !== 'observed' || s.pos - lastPos >= MIN_TICK_GAP) {
      shown.push(s)
      lastPos = s.pos
    }
  }
  if (selected.value && !shown.some((s) => s.id === selected.value.id)) {
    shown.push(selected.value)
    shown.sort((a, b) => a.pos - b.pos)
  }
  return shown
})

// ---------- 步进（上一帧 / 下一帧） ----------
const currentIdx = computed(() => props.stops.findIndex((s) => s.id === props.modelValue))
const prevDisabled = computed(() => !props.stops.length || currentIdx.value <= 0)
// 未选中任何停靠点时允许「下一帧」跳到首个停靠点
const nextDisabled = computed(
  () => !props.stops.length || (currentIdx.value >= 0 && currentIdx.value >= props.stops.length - 1)
)

function goToIndex(i) {
  const s = props.stops[i]
  if (s && s.id !== props.modelValue) emit('update:modelValue', s.id)
}

function step(dir) {
  if (!props.stops.length) return
  const idx = currentIdx.value
  if (dir < 0) {
    if (idx > 0) goToIndex(idx - 1)
  } else {
    goToIndex(idx < 0 ? 0 : Math.min(idx + 1, props.stops.length - 1))
  }
}

// ---------- 键盘（role="slider"） ----------
const sliderMax = computed(() => Math.max(props.stops.length - 1, 0))
const sliderNow = computed(() => (currentIdx.value < 0 ? 0 : currentIdx.value))
const sliderText = computed(() => {
  if (!selected.value) return '未选择'
  return `${selected.value.tick || ''} ${selected.value.title || ''}`.trim() || '未选择'
})

function onTrackKeydown(e) {
  if (!props.stops.length) return
  const idx = currentIdx.value < 0 ? 0 : currentIdx.value
  const last = props.stops.length - 1
  if (e.key === 'ArrowRight') {
    e.preventDefault()
    // 未选中任何停靠点时，→ 与「下一帧」按钮一致：先落到首个停靠点
    goToIndex(currentIdx.value < 0 ? 0 : Math.min(idx + 1, last))
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    goToIndex(Math.max(idx - 1, 0))
  } else if (e.key === 'Home') {
    e.preventDefault()
    goToIndex(0)
  } else if (e.key === 'End') {
    e.preventDefault()
    goToIndex(last)
  }
}

// ---------- 速度档（定时器在父组件） ----------
const SPEEDS = [
  { label: '0.5×', ms: 3600 },
  { label: '1×', ms: 1800 },
  { label: '2×', ms: 900 },
  { label: '4×', ms: 450 }
]

const matchSpeedIdx = (ms) => {
  const i = SPEEDS.findIndex((s) => s.ms === Number(ms))
  return i >= 0 ? i : 1 // 非预设值回退到 1×
}
const speedIdx = ref(matchSpeedIdx(props.speedMs))
watch(
  () => props.speedMs,
  (ms) => {
    speedIdx.value = matchSpeedIdx(ms)
  }
)

function setSpeed(i) {
  if (i === speedIdx.value) return
  speedIdx.value = i
  emit('speed-change', SPEEDS[i].ms)
}

// ---------- 停靠点数值分布迷你条（kepler.gl 式） ----------
const barEntries = computed(() => {
  if (!props.stopValues.length || !props.stops.length) return []
  const byId = new Map()
  props.stopValues.forEach((v) => {
    if (v && v.id != null && Number.isFinite(Number(v.value))) byId.set(v.id, Number(v.value))
  })
  if (!byId.size) return []
  const entries = []
  props.stops.forEach((s) => {
    if (!s || !byId.has(s.id)) return
    entries.push({ id: s.id, pos: s.pos, tick: s.tick || '', value: byId.get(s.id), pct: 55 })
  })
  if (!entries.length) return []
  const vals = entries.map((e) => e.value)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  entries.forEach((e) => {
    // min-max 归一化到 18%–100%；全等值时统一中等高度
    e.pct = max === min ? 55 : Math.round((18 + (82 * (e.value - min)) / (max - min)) * 10) / 10
  })
  return entries.slice().sort((a, b) => a.pos - b.pos)
})
const barShown = computed(() => barEntries.value.length > 0)

const barLabel = (bar) => `${bar.tick ? `${bar.tick}：` : ''}${bar.value}`

function selectStop(id) {
  if (id !== props.modelValue) emit('update:modelValue', id)
}

// ---------- 轨道指针交互（原逻辑不变） ----------
function pickByClientX(clientX) {
  const el = trackRef.value
  if (!el || !props.stops.length) return
  const rect = el.getBoundingClientRect()
  const pct = ((clientX - rect.left) / rect.width) * 100
  let best = props.stops[0]
  let bestDist = Infinity
  props.stops.forEach((s) => {
    const d = Math.abs(s.pos - pct)
    if (d < bestDist) {
      best = s
      bestDist = d
    }
  })
  if (best && best.id !== props.modelValue) emit('update:modelValue', best.id)
}

function onTrackPointer(e) {
  dragging = true
  pickByClientX(e.clientX)
  const move = (ev) => {
    if (!dragging) return
    pickByClientX(ev.clientX)
  }
  const up = () => {
    dragging = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}
</script>

<style scoped>
.ftl {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel);
  padding: 10px 14px;
}
.ftl-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ---------- 一级尺度档 ---------- */
.ftl-scales {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 6px;
  border-bottom: 1px dashed var(--border-subtle);
}
.ftl-scale {
  appearance: none;
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
}
.ftl-scale b {
  font-size: 12px;
  font-weight: 700;
}
.ftl-scale small {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.ftl-scale.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
}
.ftl-scale:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 步进按钮（上一帧 / 下一帧） ---------- */
.ftl-step {
  appearance: none;
  flex: none;
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: 50%;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: opacity 160ms ease, color 160ms ease;
}
.ftl-step svg {
  width: 15px;
  height: 15px;
  fill: currentColor;
}
.ftl-step:disabled {
  opacity: 0.35;
  cursor: default;
}
.ftl-step:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.ftl-play {
  appearance: none;
  flex: none;
  width: 42px;
  height: 42px;
  border: none;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 10px color-mix(in srgb, var(--color-primary) 45%, transparent);
}
.ftl-play svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}
.ftl-play:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.ftl-zone {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.ftl-track {
  position: relative;
  height: 24px;
  cursor: pointer;
  touch-action: none;
  border-radius: 6px;
}
.ftl-track:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
.ftl-rail,
.ftl-fill {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  height: 6px;
  border-radius: 999px;
}
.ftl-rail {
  left: 0;
  right: 0;
  background: color-mix(in srgb, var(--text-muted, #7d93a8) 28%, transparent);
}
.ftl-fill {
  left: 0;
  background: linear-gradient(to right, color-mix(in srgb, var(--color-primary) 55%, transparent), var(--color-primary));
  transition: width 220ms cubic-bezier(0.33, 1, 0.68, 1);
}
.ftl-handle {
  position: absolute;
  top: 50%;
  width: 18px;
  height: 18px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--color-primary);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
  pointer-events: none;
  transition: left 220ms cubic-bezier(0.33, 1, 0.68, 1);
}
.ftl-cut {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 0;
  height: 14px;
  border-left: 1px dashed color-mix(in srgb, var(--text-muted, #7d93a8) 55%, transparent);
  pointer-events: none;
}
.ftl-stopdot {
  position: absolute;
  top: 50%;
  width: 11px;
  height: 11px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: var(--surface-panel);
  border: 2px solid color-mix(in srgb, var(--text-muted, #7d93a8) 75%, transparent);
  pointer-events: none;
}
.ftl-stopdot--today {
  border-color: var(--color-primary);
}
.ftl-stopdot--short,
.ftl-stopdot--mid,
.ftl-stopdot--long {
  border-style: dashed;
}
.ftl-stopdot--on {
  background: var(--color-primary);
  border-color: var(--color-primary);
  box-shadow: 0 0 8px color-mix(in srgb, var(--color-primary) 60%, transparent);
}
.ftl-ticks {
  position: relative;
  height: 30px;
}
.ftl-tick {
  position: absolute;
  top: 2px;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}
.ftl-tick--start {
  transform: none;
}
.ftl-tick--end {
  transform: translateX(-100%);
}
.ftl-tick--today,
.ftl-tick--on {
  color: var(--color-primary);
  font-weight: 700;
}

/* ---------- 停靠点数值分布迷你条（kepler.gl 式） ---------- */
.ftl-bars {
  position: relative;
  height: 26px;
  border-bottom: 1px solid color-mix(in srgb, var(--text-muted, #7d93a8) 22%, transparent);
}
.ftl-bar {
  appearance: none;
  position: absolute;
  top: 0;
  bottom: 0;
  transform: translateX(-50%);
  width: 18px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
/* 扩大触控/点击热区（视觉不变） */
.ftl-bar::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: -3px;
  bottom: -3px;
}
.ftl-bar i {
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  width: 4px;
  border-radius: 2px 2px 0 0;
  background: color-mix(in srgb, var(--color-primary) 32%, transparent);
  transition: height 160ms ease, background-color 160ms ease;
}
.ftl-bar:hover i {
  background: color-mix(in srgb, var(--color-primary) 52%, transparent);
}
.ftl-bar--on i {
  background: var(--color-primary);
  box-shadow: 0 0 7px color-mix(in srgb, var(--color-primary) 55%, transparent);
}
.ftl-bar:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 速度档 ---------- */
.ftl-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
}
.ftl-speeds {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ftl-speeds-cap {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  margin-right: 2px;
}
.ftl-speed {
  appearance: none;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1;
  padding: 4px 10px;
  min-width: 38px;
  text-align: center;
  border-radius: 999px;
  cursor: pointer;
  transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease;
}
.ftl-speed.active {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
}
.ftl-speed:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.ftl-status {
  flex: none;
  min-width: 150px;
  display: grid;
  gap: 1px;
  justify-items: end;
  text-align: right;
}
.ftl-status b {
  font-size: 12.5px;
  color: var(--color-primary);
  white-space: nowrap;
}
.ftl-status span {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  white-space: nowrap;
}
.ftl-refresh {
  appearance: none;
  flex: none;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-subtle);
  border-radius: 50%;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ftl-refresh svg {
  width: 16px;
  height: 16px;
  fill: currentColor;
}
.ftl-refresh:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 动效降级：偏好减少动效时全部关闭 ---------- */
@media (prefers-reduced-motion: reduce) {
  .ftl-fill,
  .ftl-handle,
  .ftl-bar i,
  .ftl-step,
  .ftl-speed {
    transition: none !important;
  }
}

@media (max-width: 759px) {
  .ftl-row {
    flex-wrap: wrap;
    gap: 8px;
  }
  .ftl-zone {
    order: 3;
    flex-basis: 100%;
  }
  .ftl-status {
    flex: 1;
    justify-items: end;
  }
  .ftl-play,
  .ftl-refresh,
  .ftl-step {
    width: 44px;
    height: 44px;
  }
  .ftl-scale {
    min-height: 44px;
  }
  .ftl-speed {
    min-height: 44px;
    padding-top: 0;
    padding-bottom: 0;
  }
  .ftl-foot {
    justify-content: flex-start;
  }
  /* 迷你条热区补足到 44px 高（视觉条带仍为 26px） */
  .ftl-bar {
    width: 24px;
  }
  .ftl-bar::after {
    top: -9px;
    bottom: -9px;
  }
}
</style>
