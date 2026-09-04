// 全局主题管理：dark（默认）/ light / sunrise（日式暖阳）。
// 通过 <html data-theme="dark|light|sunrise"> 驱动三套 CSS token 切换，
// 状态持久化到 localStorage；无合法保存值时固定使用 dark，不跟随系统。

import { reactive, computed } from 'vue'

const STORAGE_KEY = 'i-need-sleep-theme'
const THEMES = ['dark', 'light', 'sunrise']

const state = reactive({
  theme: 'dark'
})

function resolveInitialTheme() {
  if (typeof window === 'undefined') return 'dark'
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (THEMES.includes(saved)) return saved
  } catch (e) {
    // localStorage 不可用（隐私模式等），忽略
  }
  // 演示环境固定深色起步，不再跟随系统 prefers-color-scheme
  return 'dark'
}

function applyTheme(theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.theme = theme
  // 让滚动条、表单控件等原生 UI 跟随主题
  root.style.colorScheme = theme === 'dark' ? 'dark' : 'light'
}

// 应用启动时尽早调用（main.js 顶部），避免首屏闪烁
export function initTheme() {
  const theme = resolveInitialTheme()
  state.theme = theme
  applyTheme(theme)
}

export function useTheme() {
  // 循环切换：dark → light → sunrise → dark
  const cycleTheme = () => {
    const idx = THEMES.indexOf(state.theme)
    const next = THEMES[(idx + 1) % THEMES.length]
    state.theme = next
    applyTheme(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch (e) {
      // 忽略持久化失败
    }
  }

  return {
    theme: computed(() => state.theme),
    isDark: computed(() => state.theme === 'dark'),
    cycleTheme
  }
}
