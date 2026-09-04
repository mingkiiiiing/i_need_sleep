<template>
  <aside
    ref="rootEl"
    class="sidebar"
    :class="{ 'sidebar--open': open }"
    :inert="drawerHidden"
    @keydown="onTrapKeydown"
  >
    <RouterLink class="sb-brand" to="/" aria-label="返回首页">
      <svg class="sb-brand-mark" viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <rect x="1.2" y="1.2" width="25.6" height="25.6" rx="7" stroke="currentColor" stroke-width="1.5" opacity="0.55" />
        <path d="M5.5 17.2c2.3-2.5 4.7-2.5 7 0s4.7 2.5 7 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        <path d="M5.5 11.4c2.3-2.5 4.7-2.5 7 0s4.7 2.5 7 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" opacity="0.55" />
      </svg>
      <span class="sb-brand-text">LAKE<br />TWIN</span>
    </RouterLink>

    <nav class="sb-nav" aria-label="全站主导航">
      <RouterLink
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        class="sb-item"
        :title="`${item.num} ${item.label}`"
      >
        <svg
          class="sb-icon"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
          v-html="item.icon"
        ></svg>
        <span class="sb-num" aria-hidden="true">{{ item.num }}</span>
        <span class="sb-label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <p class="sb-foot" aria-hidden="true">SIMULATED</p>
  </aside>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

// 仅含五个正式页面入口；选中态 = 青色实底方块 + 图标/编号反色 + aria-current（RouterLink 自动）
const props = defineProps({
  open: { type: Boolean, default: false }
})

const rootEl = ref(null)
const isMobile = ref(false)

let mq = null
function syncMq(e) {
  isMobile.value = e.matches
}
onMounted(() => {
  mq = window.matchMedia('(max-width: 960px)')
  isMobile.value = mq.matches
  mq.addEventListener('change', syncMq)
})
onBeforeUnmount(() => {
  if (mq) mq.removeEventListener('change', syncMq)
})

// 移动抽屉收起时整体 inert，键盘焦点不会落入屏幕外导航
const drawerHidden = computed(() => isMobile.value && !props.open)

watch(
  () => props.open,
  (v) => {
    if (!v || !isMobile.value) return
    nextTick(() => {
      const first = rootEl.value?.querySelector('.sb-item') || rootEl.value?.querySelector('a, button')
      first?.focus()
    })
  }
)

// 打开期间 Tab 焦点圈定在抽屉内循环
function onTrapKeydown(e) {
  if (e.key !== 'Tab' || !isMobile.value || !props.open) return
  const items = [...(rootEl.value?.querySelectorAll('a[href], button:not([disabled])') || [])]
  if (!items.length) return
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

const items = [
  {
    num: '00',
    to: '/',
    label: '首页',
    icon: '<path d="M3.5 9.2 10 3.4l6.5 5.8"/><path d="M5.2 8.8V16a1 1 0 0 0 1 1h7.6a1 1 0 0 0 1-1V8.8"/><path d="M8.2 17v-4.3h3.6V17"/>'
  },
  {
    num: '01',
    to: '/cockpit',
    label: '综合驾驶舱',
    icon: '<path d="M3.4 14.2a6.6 6.6 0 1 1 13.2 0"/><path d="m10 14 2.8-3.4"/><circle cx="10" cy="14" r="1.1"/>'
  },
  {
    num: '02',
    to: '/stations',
    label: '监测站点',
    icon: '<path d="M10 17s-5.2-4.7-5.2-8.4a5.2 5.2 0 0 1 10.4 0C15.2 12.3 10 17 10 17z"/><circle cx="10" cy="8.6" r="1.7"/>'
  },
  {
    num: '03',
    to: '/heatmap',
    label: '时空推演',
    icon: '<path d="M10 3.4 17 7l-7 3.6L3 7z"/><path d="m3 11 7 3.6 7-3.6"/><path d="m3 14.6 7 3.6 7-3.6"/>'
  },
  {
    num: '04',
    to: '/history',
    label: '历史复盘',
    icon: '<circle cx="10" cy="11" r="6.6"/><path d="M10 7.6V11l2.4 1.5"/><path d="M7 2.6h6"/>'
  }
]
</script>

<style scoped>
.sidebar {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 1200;
  width: 72px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
}

.sb-brand {
  display: grid;
  place-items: center;
  gap: 2px;
  height: 64px;
  color: var(--color-primary);
}
.sb-brand-mark {
  width: 30px;
  height: 30px;
}
.sb-brand-text {
  display: none;
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.28em;
  line-height: 1.35;
  text-align: center;
  color: var(--text-secondary);
}

.sb-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 0;
}
.sb-item {
  display: grid;
  justify-items: center;
  gap: 3px;
  margin: 0 10px;
  padding: 10px 2px 9px;
  min-height: 56px;
  border-radius: var(--radius-item);
  color: var(--text-secondary);
  transition: background 0.16s ease, color 0.16s ease;
}
.sb-item:hover {
  color: var(--text-primary);
  background: var(--surface-panel-soft);
}
.sb-icon { width: 20px; height: 20px; }
.sb-num {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.22em;
  color: var(--text-muted);
}
.sb-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  white-space: nowrap;
}
.sb-item.router-link-exact-active {
  background: var(--color-primary);
  color: var(--color-primary-ink);
}
.sb-item.router-link-exact-active .sb-num {
  color: var(--color-primary-ink);
  opacity: 0.78;
}
.sb-item.router-link-exact-active .sb-label {
  font-weight: 700;
}

.sb-foot {
  margin: auto 0 14px;
  align-self: center;
  writing-mode: vertical-rl;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  padding: 10px 5px;
}

/* ===== ≤960：折叠为抽屉 ===== */
@media (max-width: 960px) {
  .sidebar {
    width: 264px;
    transform: translateX(-102%);
    transition: transform 0.28s var(--ease-out);
    box-shadow: none;
  }
  .sidebar--open {
    transform: none;
    box-shadow: 24px 0 80px rgba(2, 8, 18, 0.55);
  }
  .sb-brand {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  .sb-brand-text { display: block; }
  .sb-nav { padding: 14px 0; }
  .sb-item {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0 12px;
    padding: 12px 16px;
    min-height: 48px;
  }
  .sb-num { font-size: 10px; }
  .sb-label { font-size: 14px; }
  .sb-item.router-link-exact-active {
    background: var(--color-primary-soft);
    color: var(--color-primary);
    box-shadow: inset 3px 0 0 var(--color-primary);
  }
  .sb-item.router-link-exact-active .sb-num { color: var(--color-primary); }
  .sb-foot { display: none; }
}
</style>
