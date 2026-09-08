<template>
  <div class="ftl" role="group" aria-label="时序推演控制条">
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

    <div class="ftl-zone">
      <div
        ref="trackRef"
        class="ftl-track"
        @pointerdown="onTrackPointer"
      >
        <div class="ftl-rail"></div>
        <div class="ftl-fill" :style="{ width: `${selectedPos}%` }"></div>
        <span
          v-for="stop in stops"
          :key="`dot-${stop.id}`"
          class="ftl-stopdot"
          :class="[`ftl-stopdot--${stop.kind}`, { 'ftl-stopdot--on': stop.id === modelValue }]"
          :style="{ left: `${stop.pos}%` }"
        ></span>
        <span
          class="ftl-handle"
          :style="{ left: `${selectedPos}%` }"
          aria-hidden="true"
        ></span>
      </div>
      <div class="ftl-ticks" aria-hidden="true">
        <span
          v-for="stop in stops"
          :key="`tick-${stop.id}`"
          class="ftl-tick"
          :class="[`ftl-tick--${stop.kind}`, { 'ftl-tick--on': stop.id === modelValue, 'ftl-tick--start': stop.pos < 9, 'ftl-tick--end': stop.pos > 91 }]"
          :style="{ left: `${stop.pos}%` }"
        >{{ stop.tick }}</span>
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
</template>

<script setup>
// 时序推演控制条：对标 taihu.lidantech.com 底部播放时间轴。
// 轨道为离散停靠点（实测快照日 → 今日 → 未来研判档位），拖拽/点击吸附到最近停靠点；
// 未来档位是规则研判不是逐日数值预报，因此不做连续自由拖动刻度。
import { computed, ref } from 'vue'

const props = defineProps({
  // [{ id, kind: 'observed'|'today'|'short'|'mid'|'long', pos: 0-100, tick, title, sub }]
  stops: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  playing: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'toggle-play', 'refresh'])

const trackRef = ref(null)
let dragging = false

const selectedPos = computed(() => {
  const stop = props.stops.find((s) => s.id === props.modelValue)
  return stop ? stop.pos : 0
})
const selected = computed(() => props.stops.find((s) => s.id === props.modelValue) || null)

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
  align-items: center;
  gap: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel);
  padding: 10px 14px;
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
.ftl-status {
  flex: none;
  min-width: 128px;
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

@media (max-width: 759px) {
  .ftl {
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
  .ftl-refresh {
    width: 44px;
    height: 44px;
  }
}
</style>
