<template>
  <header class="gnav" :class="{ 'gnav-scrolled': scrolled }">
    <div class="gnav-inner">
      <!-- Logo -->
      <RouterLink class="gnav-brand" to="/" aria-label="返回首页">
        <span class="gnav-brand-mark">A23</span>
        <span class="gnav-brand-copy">
          <strong>LAKE TWIN</strong>
          <small>蓝藻水华监测预警</small>
        </span>
      </RouterLink>

      <!-- 导航入口 -->
      <nav class="gnav-links" aria-label="全局页面导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.num"
          :to="item.to"
          class="gnav-link"
          :class="{ 'router-link-active': isActive(item) }"
        >
          <span class="gnav-link-num">{{ item.num }}</span>
          <span class="gnav-link-label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <!-- 右侧：时间 + 主题切换 -->
      <div class="gnav-right">
        <div class="gnav-clock" aria-label="当前时间">
          <span class="gnav-clock-dot" aria-hidden="true"></span>
          <time :datetime="isoTime">{{ liveTime }}</time>
        </div>

        <button
          type="button"
          class="gnav-theme-btn"
          :aria-label="themeAriaLabel"
          :title="themeTitle"
          @click="cycleTheme"
        >
          <svg v-if="theme === 'dark'" class="gnav-theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
          <svg v-else-if="theme === 'light'" class="gnav-theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </svg>
          <svg v-else class="gnav-theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3v3" />
            <path d="M5.6 7.6l2.1 2.1" />
            <path d="M18.4 7.6l-2.1 2.1" />
            <path d="M3 17h18" />
            <path d="M6 17a6 6 0 0 1 12 0" />
          </svg>
        </button>

        <!-- 移动端菜单按钮 -->
        <button
          type="button"
          class="gnav-mobile-toggle"
          :aria-expanded="mobileOpen"
          aria-label="切换导航菜单"
          @click="mobileOpen = !mobileOpen"
        >
          <span class="gnav-mobile-bar" :class="{ 'is-open': mobileOpen }"></span>
        </button>
      </div>
    </div>

    <!-- 移动端下拉面板 -->
    <Transition name="gnav-mobile">
      <nav v-if="mobileOpen" class="gnav-mobile-panel" aria-label="移动端导航">
        <RouterLink
          v-for="item in navItems"
          :key="item.num"
          :to="item.to"
          class="gnav-mobile-link"
          @click="mobileOpen = false"
        >
          <span class="gnav-link-num">{{ item.num }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </Transition>
  </header>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTheme } from '../composables/useTheme.js'

const route = useRoute()
const { theme, cycleTheme } = useTheme()

const navItems = [
  { num: '00', to: '/',                 label: '首页' },
  { num: '01', to: '/stations',         label: '监测站' },
  { num: '02', to: '/heatmap',          label: '热力图' },
  { num: '03', to: '/history',          label: '历史事件' }
]

const now = ref(new Date())
let clockTimer

const liveTime = computed(() => {
  const v = now.value
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(v.getMonth() + 1)}-${pad(v.getDate())} ${pad(v.getHours())}:${pad(v.getMinutes())}`
})
const isoTime = computed(() => now.value.toISOString())

const themeAriaLabel = computed(() =>
  theme.value === 'dark' ? '切换到浅色主题' : theme.value === 'light' ? '切换到日式暖阳主题' : '切换到深色主题'
)
const themeTitle = computed(() =>
  theme.value === 'dark' ? '深色主题 · 点击切换浅色' : theme.value === 'light' ? '浅色主题 · 点击切换日式暖阳' : '日式暖阳 · 点击切换深色'
)

function isActive(item) {
  const path = typeof item.to === 'string' ? item.to : item.to.path
  const hash = typeof item.to === 'object' ? (item.to.hash || '') : ''
  if (path === '/') {
    if (hash) return route.path === '/' && route.hash === hash
    return route.path === '/' && !route.hash
  }
  return route.path.startsWith(path)
}

// 滚动时增加阴影
const scrolled = ref(false)
function onScroll() {
  scrolled.value = window.scrollY > 8
}

// 路由变化时关闭移动端菜单
watch(() => route.fullPath, () => {
  mobileOpen.value = false
})

const mobileOpen = ref(false)

onMounted(() => {
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 30000)
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
})

onBeforeUnmount(() => {
  window.clearInterval(clockTimer)
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.gnav {
  position: sticky;
  top: 0;
  z-index: 1000;
  border-bottom: 1px solid var(--c-line);
  background: var(--glass-bg-strong);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  transition: box-shadow 0.3s var(--ease-out), border-color 0.3s ease;
}

.gnav-scrolled {
  box-shadow: 0 6px 28px rgba(0, 0, 0, 0.22);
  border-bottom-color: var(--c-line-strong);
}

.gnav-inner {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 1560px;
  margin: 0 auto;
  padding: 0 28px;
  height: 60px;
}

/* ============ Logo ============ */
.gnav-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  transition: opacity 0.15s ease;
}
.gnav-brand:hover { opacity: 0.82; }

.gnav-brand-mark {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid var(--c-accent);
  border-radius: var(--radius-sm);
  color: var(--c-accent);
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.gnav-brand-copy {
  display: grid;
  gap: 1px;
}
.gnav-brand-copy strong {
  font-family: var(--font-display);
  font-size: 13px;
  letter-spacing: 0.16em;
  color: var(--c-text);
}
.gnav-brand-copy small {
  color: var(--c-muted);
  font-size: 10px;
}

/* ============ 导航链接 ============ */
.gnav-links {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
  justify-content: center;
  min-width: 0;
}

.gnav-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  color: var(--c-text-soft);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: color 0.15s ease, background 0.15s ease;
}

.gnav-link:hover {
  color: var(--c-text);
  background: var(--c-surface-soft);
}

.gnav-link.router-link-active {
  color: var(--c-accent);
  background: var(--c-accent-soft);
}

.gnav-link-num {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--c-muted);
  letter-spacing: 1px;
}
.gnav-link.router-link-active .gnav-link-num {
  color: var(--c-accent);
}

/* ============ 右侧 ============ */
.gnav-right {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.gnav-clock {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--c-line);
  background: var(--c-surface-soft);
  color: var(--c-text-soft);
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 1px;
}

.gnav-clock-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c-accent);
  box-shadow: 0 0 0 4px var(--c-accent-soft);
  animation: gnav-pulse 2s var(--ease-in-out) infinite;
}

@keyframes gnav-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

.gnav-theme-btn {
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid var(--c-line-strong);
  border-radius: var(--radius-pill);
  background: var(--c-surface-soft);
  color: var(--c-text-soft);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}
.gnav-theme-btn:hover {
  color: var(--c-accent);
  border-color: var(--c-accent-border);
  transform: translateY(-1px);
}
.gnav-theme-btn:active { transform: translateY(1px); }
.gnav-theme-btn:focus-visible {
  outline: 3px solid var(--c-accent-glow);
  outline-offset: 3px;
}

.gnav-theme-icon {
  width: 18px;
  height: 18px;
  pointer-events: none;
}

/* ============ 移动端菜单按钮 ============ */
.gnav-mobile-toggle {
  display: none;
  position: relative;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid var(--c-line-strong);
  border-radius: var(--radius-sm);
  background: var(--c-surface-soft);
  cursor: pointer;
}
.gnav-mobile-bar,
.gnav-mobile-bar::before,
.gnav-mobile-bar::after {
  content: "";
  position: absolute;
  left: 50%;
  width: 16px;
  height: 2px;
  background: var(--c-text);
  border-radius: 2px;
  transform: translateX(-50%);
  transition: transform 0.25s ease, opacity 0.2s ease;
}
.gnav-mobile-bar { top: 50%; margin-top: -1px; }
.gnav-mobile-bar::before { top: -6px; }
.gnav-mobile-bar::after { top: 6px; }
.gnav-mobile-bar.is-open { background: transparent; }
.gnav-mobile-bar.is-open::before { transform: translateX(-50%) rotate(45deg); top: 0; }
.gnav-mobile-bar.is-open::after { transform: translateX(-50%) rotate(-45deg); top: 0; }

/* ============ 移动端下拉面板 ============ */
.gnav-mobile-panel {
  display: grid;
  gap: 2px;
  padding: 12px 28px 18px;
  border-top: 1px solid var(--c-line);
  background: var(--glass-bg-strong);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}

.gnav-mobile-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  color: var(--c-text-soft);
  font-size: 14px;
  font-weight: 600;
  transition: color 0.15s ease, background 0.15s ease;
}
.gnav-mobile-link:hover {
  color: var(--c-text);
  background: var(--c-surface-soft);
}
.gnav-mobile-link.router-link-active {
  color: var(--c-accent);
  background: var(--c-accent-soft);
}

.gnav-mobile-enter-active,
.gnav-mobile-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.gnav-mobile-enter-from,
.gnav-mobile-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* ============ 响应式 ============ */
@media (max-width: 1100px) {
  .gnav-link-label { display: none; }
  .gnav-link { padding: 8px 10px; }
  .gnav-link-num { font-size: 11px; }
  .gnav-brand-copy { display: none; }
}

@media (max-width: 820px) {
  .gnav-links { display: none; }
  .gnav-mobile-toggle { display: inline-grid; place-items: center; }
  .gnav-clock { display: none; }
  .gnav-inner { padding: 0 18px; }
  .gnav-mobile-panel { padding: 12px 18px 18px; }
}

@media (prefers-reduced-motion: reduce) {
  .gnav-clock-dot { animation: none; }
}
</style>
