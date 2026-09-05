<template>
  <Teleport to="body">
    <div v-if="open" class="hwd-mask" @click.self="$emit('cancel')">
      <div
        ref="dlgRef"
        class="hwd"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hwd-title"
        aria-describedby="hwd-desc"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <header class="hwd-head">
          <span class="hwd-glyph" aria-hidden="true">⚠</span>
          <h3 id="hwd-title">确认模拟发送预警（演示）</h3>
        </header>
        <div id="hwd-desc" class="hwd-body" data-role="warn-confirm-body">
          <dl class="hwd-kv">
            <div><dt>数据模式</dt><dd>SIMULATED（simulated）</dd></div>
            <div><dt>演示事件 ID</dt><dd class="mono">{{ eventId || '—' }}</dd></div>
            <div><dt>演示分区</dt><dd>{{ zoneLabel || '—' }}</dd></div>
            <div><dt>风险等级</dt><dd>{{ levelText || '—' }}（演示）</dd></div>
            <div><dt>渠道</dt><dd class="mono">platform_simulation</dd></div>
            <div><dt>模板</dt><dd>接口未提供</dd></div>
            <div><dt>接收人</dt><dd>无真实接收人</dd></div>
          </dl>
          <p class="hwd-warn-line">
            这是系统演示流程：<b>不会发送真实短信、邮件或政府预警</b>，不会通知任何真实人员。
            成功后仅返回 <b class="mono">simulated_dispatched</b> 模拟状态，
            <b>不形成持久化处置记录</b>。
          </p>
          <p class="hwd-note">当前事件为演示事件（SIMULATED · simulation_only · 非决策用途）。</p>
        </div>
        <p v-if="error" class="hwd-error" role="alert">发送失败：{{ error }}（可重试，未产生真实发送）</p>
        <footer class="hwd-foot">
          <button ref="cancelRef" type="button" class="hwd-btn hwd-btn--ghost" :disabled="busy" data-role="warn-cancel" @click="$emit('cancel')">
            取消
          </button>
          <button ref="confirmRef" type="button" class="hwd-btn hwd-btn--danger" :disabled="busy" data-role="warn-confirm" @click="$emit('confirm')">
            <span v-if="busy" class="hwd-spinner" aria-hidden="true"></span>
            {{ busy ? '发送中…' : '确认模拟发送' }}
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
  eventId: { type: String, default: '' },
  zoneLabel: { type: String, default: '' },
  levelText: { type: String, default: '' },
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
.hwd-mask {
  position: fixed;
  inset: 0;
  z-index: 1900;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(2, 8, 18, 0.62);
  backdrop-filter: blur(4px);
}
.hwd {
  width: min(540px, 100%);
  max-height: min(86vh, 720px);
  overflow-y: auto;
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 40%, var(--border-subtle));
  border-radius: var(--radius-panel, 10px);
  background: var(--surface-panel, rgba(9, 28, 48, 0.88));
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
  padding: 20px 22px;
}
.hwd:focus { outline: none; }
.hwd:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 4px; }

.hwd-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.hwd-glyph { color: var(--risk-critical, #ef4444); font-size: 20px; }
.hwd-head h3 { font-size: 16px; color: var(--text-primary); }

.hwd-body { display: grid; gap: 10px; }
.hwd-kv {
  margin: 0;
  display: grid;
  gap: 5px;
}
.hwd-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.hwd-kv dt {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hwd-kv dd {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary);
  text-align: right;
  min-width: 0;
}
.mono { font-family: var(--font-mono); word-break: break-all; }
.hwd-warn-line {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-secondary);
  border: 1px dashed color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent);
  border-radius: 10px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--risk-critical, #ef4444) 8%, transparent);
}
.hwd-warn-line b { color: var(--text-primary); }
.hwd-note { margin: 0; font-size: 11px; color: var(--text-muted); }

.hwd-error {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--risk-critical, #ef4444);
}

.hwd-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
.hwd-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 18px;
  border-radius: var(--radius-item, 8px);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  border: 1px solid transparent;
}
.hwd-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.hwd-btn--ghost {
  border-color: var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.hwd-btn--danger {
  background: var(--risk-critical, #ef4444);
  color: #fff;
}
.hwd-btn--danger:hover:not(:disabled) { filter: brightness(1.1); }
.hwd-btn:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.hwd-spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.45);
  border-top-color: #fff;
  animation: hwd-spin 0.8s linear infinite;
}
@keyframes hwd-spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .hwd-mask, .hwd-spinner { animation: none; }
}
</style>
