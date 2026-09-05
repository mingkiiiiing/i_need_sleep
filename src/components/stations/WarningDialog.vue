<template>
  <Teleport to="body">
    <div v-if="open" class="stn-dlg-mask" @click.self="$emit('cancel')">
      <div
        ref="dlgRef"
        class="stn-dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="stn-dlg-title"
        aria-describedby="stn-dlg-desc"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <header class="dlg-head">
          <span class="dlg-glyph" aria-hidden="true">⚠</span>
          <h3 id="stn-dlg-title">确认发起模拟预警（演示）</h3>
        </header>
        <div id="stn-dlg-desc" class="dlg-body">
          <p>
            即将对演示分区 <b class="mono">{{ zoneName }}</b> 执行<b>模拟预警处理</b>。
          </p>
          <p class="dlg-warn-line">
            这只是系统演示流程：<b>不会发送真实短信、邮件或政府预警</b>，不会通知任何真实人员；处理记录仅标记为
            <b class="mono">simulated_dispatched</b>。
          </p>
          <p class="dlg-note">所有数据均为演示用模拟数据，不用于任何实际决策。</p>
        </div>
        <p v-if="error" class="dlg-error" role="alert">调用失败：{{ error }}</p>
        <footer class="dlg-foot">
          <button ref="cancelRef" type="button" class="dlg-btn dlg-btn--ghost" :disabled="busy" @click="$emit('cancel')">
            取消
          </button>
          <button ref="confirmRef" type="button" class="dlg-btn dlg-btn--danger" :disabled="busy" @click="$emit('confirm')">
            <span v-if="busy" class="dlg-spinner" aria-hidden="true"></span>
            {{ busy ? '处理中…' : '确认模拟发送' }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  zoneName: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['cancel', 'confirm'])

const dlgRef = ref(null)
const cancelRef = ref(null)
const confirmRef = ref(null)

watch(
  () => props.open,
  (open) => {
    if (open) nextTick(() => dlgRef.value && dlgRef.value.focus())
  }
)

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('cancel')
    return
  }
  if (e.key !== 'Tab') return
  // 焦点圈定：弹窗内只有取消 / 确认两个可聚焦控件
  const focusables = [cancelRef.value, confirmRef.value].filter(Boolean)
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const activeEl = document.activeElement
  if (e.shiftKey && (activeEl === first || activeEl === dlgRef.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && activeEl === last) {
    e.preventDefault()
    first.focus()
  }
}
</script>

<style scoped>
.stn-dlg-mask {
  position: fixed;
  inset: 0;
  z-index: 1900;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(2, 8, 18, 0.62);
  backdrop-filter: blur(4px);
  animation: dlg-mask-in 0.18s ease both;
}
@keyframes dlg-mask-in { from { opacity: 0; } to { opacity: 1; } }

.stn-dlg {
  width: min(520px, 100%);
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ff6b6b) 40%, var(--border-subtle));
  border-radius: var(--radius-panel, 18px);
  background: var(--surface-panel, rgba(15, 27, 42, 0.92));
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
  padding: 20px 22px;
  animation: dlg-pop-in 0.2s ease both;
}
@keyframes dlg-pop-in {
  from { opacity: 0; transform: translateY(10px) scale(0.98); }
  to { opacity: 1; transform: none; }
}
.stn-dlg:focus { outline: none; }
.stn-dlg:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 4px; }

.dlg-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.dlg-glyph { color: var(--risk-critical, #ff6b6b); font-size: 20px; }
.dlg-head h3 { font-size: 16px; color: var(--text-primary); }

.dlg-body { display: grid; gap: 8px; }
.dlg-body p { font-size: 13px; line-height: 1.75; color: var(--text-secondary); }
.dlg-body b { color: var(--text-primary); }
.dlg-warn-line {
  border: 1px dashed color-mix(in srgb, var(--risk-critical, #ff6b6b) 50%, transparent);
  border-radius: 10px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--risk-critical, #ff6b6b) 8%, transparent);
}
.dlg-note { font-size: 11.5px; color: var(--text-muted); }

.dlg-error {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--risk-critical, #ff6b6b);
}

.dlg-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.dlg-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 18px;
  border-radius: var(--radius-item, 10px);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  border: 1px solid transparent;
  transition: filter 0.15s ease;
}
.dlg-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.dlg-btn--ghost {
  border-color: var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.dlg-btn--danger {
  background: var(--risk-critical, #ff6b6b);
  color: #fff;
}
.dlg-btn--danger:hover:not(:disabled) { filter: brightness(1.1); }
.dlg-btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.dlg-spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.45);
  border-top-color: #fff;
  animation: dlg-spin 0.8s linear infinite;
}
@keyframes dlg-spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .stn-dlg-mask, .stn-dlg, .dlg-spinner { animation: none; }
}
</style>
