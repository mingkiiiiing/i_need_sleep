// ============================================================
// ECharts 主题：所有配色从 tokens.css 的 CSS 变量动态读取，
// 跟随 <html data-theme="dark|light|sunrise"> 三主题自动切换。
// ============================================================

/** 读取 CSS 变量（运行时），带 fallback */
export function readCssVar(name, fallback = '') {
  if (typeof window === 'undefined' || typeof getComputedStyle !== 'function') return fallback
  const root = getComputedStyle(document.documentElement)
  const v = root.getPropertyValue(name)
  return v ? v.trim() : fallback
}

/**
 * 返回当前主题的调色板。调用方应在 computed 里引用，
 * 并额外依赖 useTheme().theme 以在主题切换时触发重算。
 */
export function palette() {
  return {
    accent: readCssVar('--c-accent', '#2bc4b4'),
    accentDeep: readCssVar('--c-accent-deep', '#12a094'),
    alert: readCssVar('--c-alert', '#ff6b6b'),
    watch: readCssVar('--c-watch', '#f5b45d'),
    stable: readCssVar('--c-stable', '#5fd6a4'),
    ai: readCssVar('--c-ai', '#a78bfa'),
    text: readCssVar('--c-text', '#e8f1f8'),
    textSoft: readCssVar('--c-text-soft', '#a6bccd'),
    muted: readCssVar('--c-muted', '#6c8499'),
    line: readCssVar('--c-line', 'rgba(96,165,190,0.16)'),
    lineStrong: readCssVar('--c-line-strong', 'rgba(130,200,220,0.30)'),
    surface: readCssVar('--c-surface', 'rgba(15,27,42,0.72)')
  }
}

/** 通用 tooltip 样式 */
export function tooltipTheme() {
  const p = palette()
  return {
    backgroundColor: p.surface,
    borderColor: p.lineStrong,
    borderWidth: 1,
    textStyle: { color: p.text, fontSize: 12 },
    extraCssText: 'backdrop-filter: blur(8px); box-shadow: 0 12px 28px rgba(0,0,0,0.35); border-radius: 10px;'
  }
}

/** 通用坐标轴线 */
export function axisLineTheme() {
  return { lineStyle: { color: palette().lineStrong } }
}

/** 通用分割线 */
export function splitLineTheme() {
  return { lineStyle: { color: palette().line } }
}

/** 通用坐标轴标签 */
export function axisLabelTheme() {
  return { color: palette().muted, fontSize: 11 }
}

/** 通用文本样式 */
export function textTheme() {
  return { color: palette().textSoft, fontFamily: 'Microsoft YaHei, PingFang SC, sans-serif' }
}

// 兼容旧引用：保持原有具名导出，供现有代码无缝过渡
export const echartsBase = { textStyle: textTheme() }
export const tooltipBase = tooltipTheme()
export const gridBase = (extra = {}) => ({
  left: 40,
  right: 16,
  top: 24,
  bottom: 28,
  containLabel: true,
  ...extra
})
export const axisLine = axisLineTheme()
export const splitLine = splitLineTheme()
export const axisLabel = axisLabelTheme()
