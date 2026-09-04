<template>
  <div class="ctxbar">
    <p
      class="ctx-line"
      :aria-label="`数据身份：${identity.lakeName}，${identity.dataMode}，${identity.datasetVersionId}，${identity.asOfLabel}，${identity.claimBoundary}`"
    >
      <span class="ctx-strong">{{ identity.lakeName }}</span>
      <span class="ctx-sep" aria-hidden="true">｜</span>
      <span class="ctx-mode">{{ identity.dataMode }}</span>
      <span class="ctx-sep" aria-hidden="true">｜</span>
      <span>{{ identity.datasetVersionId }}</span>
      <span class="ctx-sep ctx-hide-sm" aria-hidden="true">｜</span>
      <span class="ctx-hide-sm">{{ identity.asOfLabel }}</span>
      <span class="ctx-sep ctx-hide-sm" aria-hidden="true">｜</span>
      <span class="ctx-boundary ctx-hide-sm">{{ identity.claimBoundary }}</span>
    </p>
    <p class="ctx-line-sm">{{ identity.dataModeLabel }} · {{ identity.datasetVersionId }} · {{ identity.claimBoundary }}</p>

    <button
      ref="sourceBtn"
      type="button"
      class="ctx-source"
      aria-haspopup="dialog"
      :aria-expanded="String(open)"
      aria-controls="ctx-source-drawer"
      @click="open = true"
    >
      查看来源
    </button>

    <Teleport to="body">
      <div v-if="open" class="ctx-mask" @click="close()"></div>
      <aside
        v-if="open"
        id="ctx-source-drawer"
        class="ctx-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="数据来源与使用边界"
        @keydown="onDrawerKeydown"
      >
          <header class="ctx-head">
            <h3>数据来源与使用边界</h3>
            <button ref="closeBtn" type="button" class="ctx-close" aria-label="关闭数据来源说明" @click="close()">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
                <path d="m5 5 10 10M15 5 5 15" />
              </svg>
            </button>
          </header>
          <dl class="ctx-list">
            <div v-for="row in identity.provenance" :key="row.label" class="ctx-row">
              <dt>{{ row.label }}</dt>
              <dd>
                <strong>{{ row.value }}</strong>
                <span>{{ row.note }}</span>
              </dd>
            </div>
          </dl>
          <p class="ctx-note">{{ identity.claimNote }}</p>
        </aside>
    </Teleport>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { dataIdentity as identity } from '../../data/dataIdentity.js'

const open = ref(false)
const sourceBtn = ref(null)
const closeBtn = ref(null)

function close() {
  open.value = false
}

function onKey(e) {
  if (e.key === 'Escape') close()
}

// 打开时焦点移入抽屉（关闭按钮），关闭后焦点还给触发按钮
watch(open, (v) => {
  if (v) {
    window.addEventListener('keydown', onKey)
    nextTick(() => closeBtn.value?.focus())
  } else {
    window.removeEventListener('keydown', onKey)
    sourceBtn.value?.focus()
  }
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// 抽屉内唯一可聚焦元素是关闭按钮：Tab/Shift+Tab 停留原处，不逃逸到背景页
function onDrawerKeydown(e) {
  if (e.key === 'Tab') e.preventDefault()
}
</script>

<style scoped>
.ctxbar {
  position: sticky;
  top: 64px;
  z-index: 1050;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 40px;
  padding: 0 20px 0 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.ctx-line {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}
.ctx-strong { color: var(--text-primary); font-weight: 700; }
.ctx-mode { color: var(--color-primary); font-weight: 700; }
.ctx-boundary { color: var(--text-primary); font-weight: 700; }
.ctx-sep {
  margin: 0 2px;
  color: var(--text-muted);
}

.ctx-line-sm { display: none; }

.ctx-source {
  flex-shrink: 0;
  min-height: 32px;
  padding: 4px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}
.ctx-source:hover { background: var(--color-primary-soft); }

/* ===== 来源抽屉（纯 CSS 挂载动画，无 Transition 状态机） ===== */
.ctx-mask {
  position: fixed;
  inset: 0;
  z-index: 1600;
  background: rgba(2, 8, 18, 0.55);
  animation: ctx-fade-in 0.25s ease both;
}
@keyframes ctx-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
.ctx-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 1601;
  width: min(420px, 92vw);
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  overflow-y: auto;
  border-left: 1px solid var(--border-strong);
  background: var(--surface-panel-raised);
  box-shadow: -24px 0 80px rgba(2, 8, 18, 0.5);
  animation: ctx-drawer-in 0.28s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}
@keyframes ctx-drawer-in {
  from { transform: translateX(100%); }
  to { transform: none; }
}
.ctx-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.ctx-head h3 {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}
.ctx-close {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.ctx-close:hover {
  color: var(--color-primary);
  border-color: var(--border-strong);
}
.ctx-close svg {
  width: 16px;
  height: 16px;
}

.ctx-list {
  display: grid;
  gap: 12px;
  margin: 0;
}
.ctx-row {
  display: grid;
  gap: 3px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--border-subtle);
}
.ctx-row dt {
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
}
.ctx-row dd {
  margin: 0;
  display: grid;
  gap: 2px;
}
.ctx-row strong {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}
.ctx-row span {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.ctx-note {
  margin-top: auto;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--risk-medium) 40%, transparent);
  border-radius: var(--radius-item);
  background: color-mix(in srgb, var(--risk-medium) 10%, transparent);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-primary);
}

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .ctxbar {
    top: 64px;
    height: 48px;
    padding: 0 12px;
  }
  .ctx-line { display: none; }
  .ctx-hide-sm { display: none; }
  .ctx-line-sm {
    display: block;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
  }
  .ctx-source { min-height: 40px; }
}
</style>
