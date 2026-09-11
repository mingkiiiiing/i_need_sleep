/* ============================================================
   stationCountUp · 监测站点研判右栏三卡共用的数字翻牌 composable
   ------------------------------------------------------------
   数据诚实约束（与 heatmap/ForecastResultPanel 的 useCountUpText 同口径）：
   · 只把文本解析为「数值 / 非数值」token，仅对数值 token 做 rAF 插值；
     单位、汉字、分隔符等非数值文本原样保留，不参与动画、不被改写。
   · 首次出现数值时从 0 滚起（占位 0 保留原有小数位，版面不跳动）；
     新旧文本数值结构一致（数值 token 数量相同）时从旧值滚到新值；
     结构变化、非有限值或数值未变时直接落终值。
   · 终帧严格等于真实文本——动画只发生在中间帧，最终显示值与数据一致。
   · prefers-reduced-motion: reduce（或环境无 rAF / duration=0）时
     跳过动画，直接显示终值。
   ============================================================ */
import { onScopeDispose, ref, watch } from 'vue'

const DEFAULT_DURATION_MS = 600
// 数值 token：负号 + 数字（可含千分位逗号）+ 可选小数部分
const NUMERIC_PATTERN = '-?\\d[\\d,]*(?:\\.\\d+)?'

export function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/* 把文本拆成 token：{ num: true, value, text } | { num: false, text } */
export function parseNumericTokens(text) {
  const tokens = []
  const re = new RegExp(NUMERIC_PATTERN, 'g')
  let last = 0
  let m
  while ((m = re.exec(text))) {
    if (m.index > last) tokens.push({ num: false, text: text.slice(last, m.index) })
    tokens.push({ num: true, value: Number(m[0].replace(/,/g, '')), text: m[0] })
    last = m.index + m[0].length
  }
  if (last < text.length) tokens.push({ num: false, text: text.slice(last) })
  return tokens
}

/* 首帧占位：把文本中的数值替换为同小数位数的 0（从 0 起滚） */
export function zeroedNumericText(text) {
  return text.replace(new RegExp(NUMERIC_PATTERN, 'g'), (m) => (0).toFixed((m.split('.')[1] || '').length))
}

/**
 * useCountUpText(source, options?)
 * @param {import('vue').Ref<string> | (() => string)} source 响应式文本源（ref/computed/getter）
 * @param {{ duration?: number }} [options] 动画时长 ms，默认 600；0 表示禁用滚动
 * @returns {import('vue').Ref<string>} 展示文本（终帧 === 真实文本）
 */
export function useCountUpText(source, options = {}) {
  const durationMs = options.duration == null
    ? DEFAULT_DURATION_MS
    : Math.max(0, Number(options.duration) || 0)
  const initial = String(source.value ?? '')
  const hasNums = parseNumericTokens(initial).some((t) => t.num)
  const reduced = prefersReducedMotion()
  const display = ref(reduced || !hasNums ? initial : zeroedNumericText(initial))
  let rafId = 0
  let prevNums = []
  const stop = () => {
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
  }
  watch(source, (next) => {
    const nextText = String(next ?? '')
    stop()
    const tokens = parseNumericTokens(nextText)
    const nextNums = tokens.filter((t) => t.num).map((t) => t.value)
    // 结构一致 → 从旧值滚到新值；结构变化或首次出现数值 → 从 0 滚起
    const fromNums = prevNums.length === nextNums.length && prevNums.length > 0
      ? prevNums
      : nextNums.map(() => 0)
    const animatable =
      !reduced &&
      durationMs > 0 &&
      typeof requestAnimationFrame === 'function' &&
      nextNums.length > 0 &&
      fromNums.every(Number.isFinite) &&
      nextNums.every(Number.isFinite) &&
      fromNums.some((v, i) => v !== nextNums[i])
    prevNums = nextNums
    if (!animatable) {
      display.value = nextText
      return
    }
    const formatters = tokens
      .filter((t) => t.num)
      .map((t) => {
        const decimals = (t.text.split('.')[1] || '').length
        // 仅当真实文本本身带千分位逗号时才补千分位，保持中间帧贴近终帧
        const useGrouping = t.text.includes(',')
        return (v) => v.toLocaleString('zh-CN', { maximumFractionDigits: decimals, useGrouping })
      })
    const startedAt = performance.now()
    const tick = (now) => {
      const t = Math.min(1, (now - startedAt) / durationMs)
      if (t >= 1) {
        display.value = nextText // 终帧严格回到原始字符串，最终显示值不被动画改变
        rafId = 0
        return
      }
      const eased = 1 - Math.pow(1 - t, 3) // ease-out cubic
      let i = 0
      display.value = tokens.map((token) => {
        if (!token.num) return token.text
        const k = i++
        const v = fromNums[k] + (nextNums[k] - fromNums[k]) * eased
        return formatters[k](v)
      }).join('')
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
  }, { immediate: true })
  onScopeDispose(stop)
  return display
}
