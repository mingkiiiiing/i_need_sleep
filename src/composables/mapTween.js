/* ============================================================
   mapTween · Leaflet 图层平滑过渡通用工具（rAF + 分组取消令牌）
   ------------------------------------------------------------
   设计要点（数据诚实）：
   · 补间只在「同一目标的旧真实渲染值 → 新真实渲染值」之间插值，
     不造数据、不参与任何数值→颜色的映射计算（映射仍由组件完成）。
   · TweenGroup 内一组动画共享单个 rAF 时钟；run() 返回取消句柄，
     cancelAll()/destroy() 用于组件重渲染 / 卸载时取消旧动画，
     防止 rAF 串扰与内存泄漏。
   · prefers-reduced-motion: reduce 命中时 run() 同步直落终态
     （终态 = 新真实值），不产生任何动画帧。
   ============================================================ */

/* ease-out 三次方缓动：起步快、收尾缓（对标 kepler.gl/Windy 的过渡手感） */
export const EASE_OUT = (t) => 1 - Math.pow(1 - t, 3)

export function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

export function lerp(a, b, t) {
  return a + (b - a) * t
}

export function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/* —— 颜色解析/插值（仅服务于新旧真实色值之间的视觉过渡） ——
   支持 #rgb / #rrggbb / rgb() / rgba()；解析失败返回 null，
   调用方应跳过插值、直接使用原始色（绝不猜测替换）。 */
export function colorToRgb(input) {
  if (Array.isArray(input) && input.length >= 3) {
    return [Number(input[0]) || 0, Number(input[1]) || 0, Number(input[2]) || 0]
  }
  if (typeof input !== 'string') return null
  const s = input.trim().toLowerCase()
  let m = s.match(/^#([0-9a-f]{6})$/)
  if (m) {
    const n = parseInt(m[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  m = s.match(/^#([0-9a-f]{3})$/)
  if (m) {
    return m[1].split('').map((ch) => parseInt(ch + ch, 16))
  }
  m = s.match(/^rgba?\(([^)]+)\)$/)
  if (m) {
    const parts = m[1].split(/[,/\s]+/).filter(Boolean).slice(0, 3).map(Number)
    if (parts.length === 3 && parts.every((v) => Number.isFinite(v))) return parts
  }
  return null
}

export function rgbToCss(rgb) {
  return `rgb(${Math.round(rgb[0])}, ${Math.round(rgb[1])}, ${Math.round(rgb[2])})`
}

/* —— 级联错峰延迟：按索引每 step 毫秒一档，超过 maxSteps 后封顶，
     避免大数组（上百场点）拖出过长动画总时长 —— */
export function staggerDelay(index, step = 32, maxSteps = 12) {
  const i = Math.max(0, Math.min(Number(index) || 0, maxSteps))
  return i * step
}

/* —— TweenGroup：一组补间动画共享一个 rAF 时钟 ——
   run({ from, to, duration, delay, ease, update, done })
     · from/to：数值或等长数值数组（半径/透明度/rgb 通道等混排）
     · update(values, k, p)：每帧回调，values 为插值结果数组
     · 返回 { cancel() } 取消句柄（token），防旧动画串扰 */
export function createTweenGroup() {
  const active = new Set()
  let rafId = 0
  let destroyed = false

  function tick() {
    rafId = 0
    if (destroyed) {
      active.clear()
      return
    }
    const now = performance.now()
    let pending = 0
    for (const tw of active) {
      if (tw.cancelled) continue
      const elapsed = now - tw.startAt
      if (elapsed <= 0) {
        // 仍在延迟（级联错峰）窗口内
        pending += 1
        continue
      }
      const p = tw.duration > 0 ? clamp01(elapsed / tw.duration) : 1
      const k = tw.ease(p)
      const values = tw.from.map((fv, i) => lerp(fv, tw.to[i], k))
      tw.update(values, k, p)
      if (p >= 1) {
        tw.cancelled = true
        active.delete(tw)
        if (tw.done) tw.done()
      } else {
        pending += 1
      }
    }
    if (pending > 0 && !destroyed) rafId = requestAnimationFrame(tick)
    else if (active.size === 0) rafId = 0
  }

  function run(options) {
    const opts = options || {}
    const from = (Array.isArray(opts.from) ? opts.from : [opts.from == null ? 0 : opts.from]).map(Number)
    const to = (Array.isArray(opts.to) ? opts.to : [opts.to == null ? 0 : opts.to]).map(Number)
    const duration = Math.max(0, Number(opts.duration) || 450)
    const delay = Math.max(0, Number(opts.delay) || 0)
    const ease = opts.ease || EASE_OUT
    const update = opts.update || (() => {})
    const done = opts.done || null

    // reduced-motion / 环境不支持 / 零时长：同步直落终态（终态 = 新真实值）
    if (destroyed || prefersReducedMotion() || duration === 0 || typeof requestAnimationFrame === 'undefined') {
      update(to.slice(), 1, 1)
      if (done) done()
      return { cancel() {} }
    }

    const tw = {
      from,
      to,
      duration,
      ease,
      update,
      done,
      startAt: performance.now() + delay,
      cancelled: false
    }
    const handle = {
      cancel() {
        tw.cancelled = true
        active.delete(tw)
      }
    }
    active.add(tw)
    if (!rafId) rafId = requestAnimationFrame(tick)
    return handle
  }

  function cancelAll() {
    for (const tw of active) tw.cancelled = true
    active.clear()
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
  }

  function destroy() {
    destroyed = true
    cancelAll()
  }

  return {
    run,
    cancelAll,
    destroy,
    get size() {
      return active.size
    }
  }
}
