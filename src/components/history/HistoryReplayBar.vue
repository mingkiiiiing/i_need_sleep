<template>
  <section class="hrp" data-role="replay-panel" aria-label="演示事件回放轴">
    <header class="hrp-head">
      <div>
        <p class="hrp-kicker">REPLAY · 演示回放轴</p>
        <h3>事件前 24h ← 事件时刻 → 事件后 24h → 事件后 48h</h3>
      </div>
      <span class="hrp-flag" data-role="replay-note">按日演示序列，不是 72 小时逐时真实观测</span>
    </header>

    <div v-if="state === 'idle'" class="hrp-state" data-role="replay-state" data-state="idle">
      <p>从上方事件列表选择一条演示事件后，按事件日期加载回放窗口。</p>
    </div>
    <div v-else-if="state === 'loading'" class="hrp-state" data-role="replay-state" data-state="loading" role="status">
      <p>回放时间轴加载中…（/cockpit/timeline）</p>
    </div>
    <div v-else-if="state === 'blocked'" class="hrp-state" data-role="replay-state" data-state="blocked">
      <p>该事件缺少发生时间，无法确定回放窗口。</p>
    </div>
    <div v-else-if="state === 'error'" class="hrp-state hrp-state--error" data-role="replay-state" data-state="error" role="alert">
      <p>回放时间轴加载失败：{{ error || '接口请求失败' }}。已清空上一事件的回放数据，不展示旧帧。</p>
      <button type="button" class="hrp-btn" data-role="replay-retry" @click="$emit('retry')">重试加载回放</button>
    </div>

    <template v-else>
      <div class="hrp-strip" data-role="replay-strip" role="group" aria-label="回放帧选择">
        <button
          v-for="(frame, i) in frames"
          :key="frame.key"
          type="button"
          class="hrp-frame"
          :class="[`hrp-frame--${frame.riskLevel || 'none'}`, { active: i === index }]"
          :data-role="`replay-frame-${i}`"
          :aria-pressed="String(i === index)"
          @click="$emit('select-frame', i)"
        >
          <span class="hrp-frame-label">{{ frame.label }}</span>
          <span class="hrp-frame-date">{{ frame.date || '日期未提供' }}</span>
          <span class="hrp-frame-risk">{{ frame.riskLevel ? riskText(frame.riskLevel) + '（演示）' : '接口未提供' }}</span>
        </button>
      </div>

      <div class="hrp-controls">
        <div class="hrp-transport">
          <button
            type="button"
            class="hrp-btn"
            data-role="replay-prev"
            :disabled="index <= 0"
            aria-label="上一帧"
            @click="$emit('prev')"
          >上一帧</button>
          <button
            type="button"
            class="hrp-btn hrp-btn--play"
            data-role="replay-play"
            :aria-label="playing ? '暂停回放' : '播放回放'"
            @click="$emit('toggle-play')"
          >{{ playing ? '暂停' : '播放' }}</button>
          <button
            type="button"
            class="hrp-btn"
            data-role="replay-next"
            :disabled="index >= frames.length - 1"
            aria-label="下一帧"
            @click="$emit('next')"
          >下一帧</button>
        </div>

        <div class="hrp-speeds" role="group" aria-label="播放倍速">
          <button
            v-for="s in [1, 2, 4]"
            :key="s"
            type="button"
            class="hrp-speed"
            :class="{ active: speed === s }"
            :data-role="`replay-speed-${s}`"
            :aria-pressed="String(speed === s)"
            @click="$emit('set-speed', s)"
          >{{ s }}×</button>
        </div>

        <span class="hrp-progress" data-role="replay-progress">第 {{ index + 1 }}/{{ frames.length }} 帧 · {{ currentLabel }}</span>
      </div>
      <p class="hrp-sync" data-role="replay-sync">
        当前帧：{{ currentLabel }} · {{ currentDate || '日期未提供' }} ·
        {{ currentRisk ? riskText(currentRisk) + '（演示风险等级）' : '该日数据接口未提供' }}。
        播放到事件后 48h 自动停止，不循环。
      </p>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { RISK_TEXT } from '../stations/stationDisplay.js'

const props = defineProps({
  state: { type: String, default: 'idle' },
  error: { type: String, default: '' },
  frames: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  playing: { type: Boolean, default: false },
  speed: { type: Number, default: 1 }
})

defineEmits(['prev', 'next', 'toggle-play', 'set-speed', 'select-frame', 'retry'])

const currentFrame = computed(() => props.frames[props.index] || null)
const currentLabel = computed(() => (currentFrame.value ? currentFrame.value.label : '—'))
const currentDate = computed(() => (currentFrame.value ? currentFrame.value.date : ''))
const currentRisk = computed(() => (currentFrame.value ? currentFrame.value.riskLevel : null))

function riskText(level) {
  return RISK_TEXT[level] || level
}
</script>

<style scoped>
.hrp {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.hrp-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.hrp-kicker {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.hrp-head h3 {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}
.hrp-flag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 3px 10px;
  white-space: nowrap;
}
.hrp-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  padding: 22px 12px;
  border: 1px dashed var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  text-align: center;
}
.hrp-state p {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  max-width: 60ch;
}
.hrp-state--error {
  border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 45%, transparent);
}
.hrp-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}
.hrp-frame {
  appearance: none;
  display: grid;
  gap: 3px;
  justify-items: start;
  min-height: 44px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-left-width: 4px;
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  min-width: 0;
}
.hrp-frame--high { border-left-color: var(--risk-critical, #ef4444); }
.hrp-frame--mid { border-left-color: var(--risk-medium, #facc15); }
.hrp-frame--low { border-left-color: var(--risk-low, #22c55e); }
.hrp-frame--none { border-left-style: dashed; }
.hrp-frame.active {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.hrp-frame:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hrp-frame-label {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.hrp-frame-date {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
}
.hrp-frame-risk {
  font-size: 10px;
  color: var(--text-muted);
}
.hrp-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.hrp-transport {
  display: flex;
  gap: 6px;
}
.hrp-btn {
  appearance: none;
  min-height: 44px;
  padding: 6px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 650;
  cursor: pointer;
}
.hrp-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.hrp-btn--play {
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  min-width: 72px;
}
.hrp-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hrp-speeds {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
}
.hrp-speed {
  appearance: none;
  min-width: 44px;
  min-height: 36px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.hrp-speed.active {
  background: color-mix(in srgb, var(--color-primary) 16%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
}
.hrp-speed:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hrp-progress {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
}
.hrp-sync {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--text-muted);
}

@media (max-width: 960px) {
  .hrp-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .hrp-speed {
    min-height: 44px;
  }
}
</style>
