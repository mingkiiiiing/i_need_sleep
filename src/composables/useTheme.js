// 全局主题管理：dark（默认）/ light。
// 通过 <html data-theme="dark|light"> 驱动两套 CSS token 切换，
// 状态持久化到 localStorage，未显式选择时跟随系统 prefers-color-scheme。

import { reactive, computed } from 'vue'

const STORAGE_KEY = 'i-need-sleep-theme'
const THEMES = ['dark', 'light']

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
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light'
  }
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
  // 循环切换：dark → light → dark
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
