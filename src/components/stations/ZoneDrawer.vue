<template>
  <Teleport to="body">
    <div v-if="open" class="stn-drawer-mask" @click.self="$emit('close')">
      <div
        ref="drawerRef"
        class="stn-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="切换演示分区"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <header class="dr-head">
          <h3>切换演示分区</h3>
          <button ref="closeRef" type="button" class="dr-close" aria-label="关闭分区抽屉" @click="$emit('close')">×</button>
        </header>
        <p class="dr-sub">共 {{ rows.length }} 个演示分区 · 按当前档位风险排序</p>
        <div class="dr-list">
          <button
            v-for="row in rows"
            :key="row.id"
            type="button"
            class="dr-item"
            :class="{ selected: row.id === selectedId }"
            :aria-current="row.id === selectedId ? 'true' : undefined"
            @click="onPick(row.id)"
          >
            <span class="dr-rank mono">{{ String(row.rank).padStart(2, '0') }}</span>
            <span class="dr-main">
              <span class="dr-code mono">{{ row.short }}</span>
              <span class="dr-name">{{ row.name }}</span>
            </span>
            <span class="dr-side">
              <span class="dr-risk" :class="`lv-${row.riskClass}`">{{ row.riskText }}</span>
              <span class="dr-score mono">{{ row.score == null ? '—' : row.score }}</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  rows: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' }
})

const emit = defineEmits(['close', 'select'])

const drawerRef = ref(null)
const closeRef = ref(null)

// Esc 全局兜底：焦点不在抽屉内（如刚点击遮罩）也能关闭
function onWindowKeydown(e) {
  if (e.key === 'Escape' && props.open) emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      nextTick(() => drawerRef.value && drawerRef.value.focus())
      window.addEventListener('keydown', onWindowKeydown)
    } else {
      window.removeEventListener('keydown', onWindowKeydown)
    }
  }
)

onBeforeUnmount(() => window.removeEventListener('keydown', onWindowKeydown))

function onPick(id) {
  emit('select', id)
  emit('close')
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
    return
  }
  if (e.key !== 'Tab') return
  const focusables = [...drawerRef.value.querySelectorAll('button')]
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const activeEl = document.activeElement
  if (e.shiftKey && (activeEl === first || activeEl === drawerRef.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && activeEl === last) {
    e.preventDefault()
    first.focus()
  }
}
</script>

<style scoped>
.stn-drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 1800;
  background: rgba(2, 8, 18, 0.55);
  animation: dr-mask-in 0.18s ease both;
}
@keyframes dr-mask-in { from { opacity: 0; } to { opacity: 1; } }

.stn-drawer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  max-height: 72vh;
  display: flex;
  flex-direction: column;
  border-radius: 18px 18px 0 0;
  border: 1px solid var(--border-subtle);
  border-bottom: none;
  background: var(--surface-panel, rgba(15, 27, 42, 0.97));
  padding: 14px 16px calc(14px + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -18px 50px rgba(0, 0, 0, 0.45);
  animation: dr-slide-up 0.22s ease both;
}
@keyframes dr-slide-up {
  from { transform: translateY(24px); opacity: 0.4; }
  to { transform: none; opacity: 1; }
}
.stn-drawer:focus { outline: none; }
.stn-drawer:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -4px; }

.dr-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.dr-head h3 { font-size: 15px; color: var(--text-primary); }
.dr-close {
  width: 44px;
  height: 44px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 20px;
  cursor: pointer;
}
.dr-sub { margin: 4px 0 10px; font-size: 11.5px; color: var(--text-muted); }

.dr-list {
  overflow-y: auto;
  display: grid;
  gap: 8px;
  padding-bottom: 4px;
}
.dr-item {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 52px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
}
.dr-item.selected {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.dr-rank { color: var(--text-muted); font-size: 12px; }
.dr-main { display: grid; gap: 1px; min-width: 0; }
.dr-code { font-size: 11px; color: var(--color-primary); }
.dr-name {
  font-size: 13.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dr-side { display: grid; gap: 2px; justify-items: end; }
.dr-risk { font-size: 11px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-subtle); }
.dr-risk.lv-high { color: var(--risk-critical, #ff6b6b); }
.dr-risk.lv-mid { color: var(--risk-medium, #f5b45d); }
.dr-risk.lv-low { color: var(--risk-low, #5fd6a4); }
.dr-score { font-size: 12px; color: var(--text-secondary); }

@media (prefers-reduced-motion: reduce) {
  .stn-drawer-mask, .stn-drawer { animation: none; }
}
</style>
