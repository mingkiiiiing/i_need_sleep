<template>
  <section class="panel time-axis">
    <div class="stage-list" role="tablist" aria-label="预测时间档位">
      <button
        v-for="s in stages"
        :key="s.key"
        type="button"
        class="stage-btn"
        :class="{ active: s.key === stageKey }"
        @click="selectStage(s.key)"
      >
        {{ s.label }}
        <span class="stage-btn-sub">{{ stageSubLabel(s.key) }}</span>
      </button>
    </div>

    <div class="play-controls">
      <button type="button" class="play-btn" :disabled="!hasPrev" @click="step(-1)" aria-label="上一档">‹</button>
      <button type="button" class="play-btn primary" @click="toggle" :aria-label="playing ? '暂停' : '播放'">
        <span v-if="!playing" aria-hidden="true">▶</span>
        <span v-else aria-hidden="true">❚❚</span>
      </button>
      <button type="button" class="play-btn" :disabled="!hasNext" @click="step(1)" aria-label="下一档">›</button>

      <div class="speed-pill" role="group" aria-label="播放倍速">
        <button
          v-for="sp in speeds"
          :key="sp"
          type="button"
          :class="{ active: sp === speed }"
          @click="setSpeed(sp)"
        >{{ sp }}×</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { cockpitState } from '../../stores/cockpit.js'

const props = defineProps({
  stages: { type: Array, required: true },
  // 用于播放器选择 stage 的可选项，默认 stages 全部
  autoRange: { type: Boolean, default: true }
})

const state = cockpitState()
const playing = computed(() => state.playing)
const stageKey = computed(() => state.stageKey)
const speed = computed(() => state.speed)

const speeds = [1, 2, 4]
const tickMs = 1400
let timer = null

const hasPrev = computed(() => indexOf(state.stageKey) > 0 || playing.value)
const hasNext = computed(() => indexOf(state.stageKey) < props.stages.length - 1 || playing.value)

function indexOf(key) {
  return props.stages.findIndex((s) => s.key === key)
}

function selectStage(key) {
  state.stageKey = key
}

function stageSubLabel(key) {
  if (key === 't1') return '紧急关注'
  if (key === 't3') return '短期研判'
  if (key === 't7') return '中期扩散'
  if (key === 't15') return '长期推演'
  if (key === 't30') return '综合研判'
  return ''
}

function step(dir) {
  const cur = indexOf(state.stageKey)
  const next = cur + dir
  if (next < 0 || next >= props.stages.length) return
  state.stageKey = props.stages[next].key
}

function setSpeed(sp) {
  state.speed = sp
  if (state.playing) {
    restartTimer()
  }
}

function toggle() {
  state.playing = !state.playing
  if (state.playing) restartTimer()
  else clearTimer()
}

function clearTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function restartTimer() {
  clearTimer()
  if (!state.playing) return
  const interval = Math.max(220, Math.round(tickMs / state.speed))
  timer = setInterval(() => {
    const cur = indexOf(state.stageKey)
    const next = cur + 1
    if (next >= props.stages.length) {
      state.stageKey = props.stages[0].key
    } else {
      state.stageKey = props.stages[next].key
    }
  }, interval)
}

watch(
  () => state.playing,
  () => {
    if (state.playing) restartTimer()
    else clearTimer()
  }
)

onBeforeUnmount(clearTimer)
</script>