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
          <!-- 尺度段分隔（预测段内部的三档分界） -->
          <span
            v-for="cut in scaleCuts"
            :key="`cut-${cut}`"
            class="ftl-cut"
            :style="{ left: `${cut}%` }"
            aria-hidden="true"
          ></span>
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
            :class="[
              `ftl-tick--${stop.kind}`,
              { 'ftl-tick--on': stop.id === modelValue, 'ftl-tick--start': stop.pos < 9, 'ftl-tick--end': stop.pos > 91 }
            ]"
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
  </div>
</template>

<script setup>
// 预测时间轴（两级控制）：
// 一级 = 时间尺度档（短临 1-3 天 / 趋势 7-15 天 / 中长期 30-90 天）；
// 二级 = 轨道上具体预测时刻（T+1…T+90，实测段为逐日快照）。
// 拖拽/点击吸附最近停靠点；未来档位是规则研判不是逐日数值预报，
// 相邻 T 点共享该尺度档的研判结论，仅预测日期不同。
import { computed, ref } from 'vue'

const props = defineProps({
  // [{ id, kind: 'observed'|'today'|'short'|'mid'|'long', scale?, pos: 0-100, tick, title, sub }]
  stops: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  playing: { type: Boolean, default: false },
  // 预测推演模式显示尺度档；实测回放隐藏
  showScales: { type: Boolean, default: false },
  // [{ id, label, hint, first, last }]，first/last 为该尺度档首个/末个停靠点 id
  scales: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:modelValue', 'toggle-play', 'refresh', 'select-scale'])

const trackRef = ref(null)
let dragging = false

const selected = computed(() => props.stops.find((s) => s.id === props.modelValue) || null)
const selectedPos = computed(() => (selected.value ? selected.value.pos : 0))
const activeScale = computed(() => selected.value?.scale || '')

// 尺度档之间的分隔位置（取相邻档位停靠点的中点）
const scaleCuts = computed(() => {
  if (!props.scales.length) return []
  const cuts = []
  for (let i = 0; i < props.scales.length - 1; i += 1) {
    const a = props.stops.find((s) => s.id === props.scales[i].last)
    const b = props.stops.find((s) => s.id === props.scales[i + 1].first)
    if (a && b) cuts.push(Math.round(((a.pos + b.pos) / 2) * 10) / 10)
  }
  return cuts
})

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
  .ftl-refresh {
    width: 44px;
    height: 44px;
  }
  .ftl-scale {
    min-height: 44px;
  }
}
</style>
