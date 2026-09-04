<template>
  <header class="topbar">
    <div class="tb-left">
      <button
        ref="menuButton"
        type="button"
        class="tb-btn tb-menu"
        aria-label="打开导航菜单"
        :aria-expanded="String(open)"
        @click="$emit('toggle-sidebar')"
      >
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path d="M3 5.5h14M3 10h14M3 14.5h14" />
        </svg>
      </button>
      <p class="tb-brand">
        <span class="tb-brand-strong">太湖</span>
        <span class="tb-brand-sep" aria-hidden="true">·</span>
        <span class="tb-brand-full">蓝藻水华监测预警系统</span>
        <span class="tb-brand-short">监测预警</span>
      </p>
    </div>

    <div class="tb-right">
      <span class="tb-service" title="当前为演示联调环境，无真实生产服务">
        <span class="tb-service-dot" aria-hidden="true"></span>演示联调
      </span>
      <span class="tb-update" title="演示数据统一基准时间">数据基准 {{ asOfShort }}</span>
      <button
        type="button"
        class="tb-btn tb-theme"
        :aria-label="themeAria"
        :title="themeTitle"
        @click="cycleTheme"
      >
        <svg v-if="theme === 'dark'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <svg v-else-if="theme === 'light'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3v3" />
          <path d="M5.6 7.6l2.1 2.1" />
          <path d="M18.4 7.6l-2.1 2.1" />
          <path d="M3 17h18" />
          <path d="M6 17a6 6 0 0 1 12 0" />
        </svg>
      </button>
    </div>
  </header>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useTheme } from '../../composables/useTheme.js'
import { dataIdentity } from '../../data/dataIdentity.js'

defineProps({
  open: { type: Boolean, default: false }
})
defineEmits(['toggle-sidebar'])

const menuButton = ref(null)
defineExpose({ menuButton })

const { theme, cycleTheme } = useTheme()

const asOfShort = computed(() => dataIdentity.asOfFull.slice(5))
const themeAria = computed(() =>
  theme.value === 'dark'
    ? '切换到浅色主题'
    : theme.value === 'light'
      ? '切换到日式暖阳主题'
      : '切换到深色主题'
)
const themeTitle = computed(() =>
  theme.value === 'dark'
    ? '深色主题 · 点击切换浅色'
    : theme.value === 'light'
      ? '浅色主题 · 点击切换日式暖阳'
      : '日式暖阳主题 · 点击切换深色'
)
</script>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 64px;
  padding: 0 20px 0 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  backdrop-filter: blur(16px) saturate(1.2);
  -webkit-backdrop-filter: blur(16px) saturate(1.2);
}

.tb-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.tb-btn {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.tb-btn:hover {
  color: var(--color-primary);
  border-color: var(--border-strong);
}
.tb-btn svg {
  width: 20px;
  height: 20px;
  pointer-events: none;
}
.tb-menu { display: none; }

.tb-brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.tb-brand-strong { color: var(--text-primary); font-weight: 700; }
.tb-brand-sep { color: var(--text-muted); }
.tb-brand-short { display: none; }

.tb-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.tb-service,
.tb-update {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.tb-service-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--risk-medium);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--risk-medium) 22%, transparent);
}

@media (max-width: 960px) {
  .tb-menu { display: grid; }
  .tb-brand-full { display: none; }
  .tb-brand-short { display: inline; }
}
@media (max-width: 640px) {
  .topbar { padding: 0 12px; }
  .tb-update { display: none; }
  .tb-service { padding: 5px 10px; }
}
</style>
