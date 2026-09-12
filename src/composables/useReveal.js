/* ============================================================
   useReveal · 滚动入场 composable（首页「入场编排套件」H4）
   ------------------------------------------------------------
   用法（两步）：
     <script setup>
     import { useReveal } from '../composables/useReveal'   // 按实际相对路径
     const { targetRef, visible } = useReveal()             // 可传 { threshold, rootMargin, once }
     </script>
     <template>
       <div ref="targetRef" :class="{ 'is-in': visible }">…</div>
     </template>
   使用方 CSS 自行定义 .is-in 的前后态（本 composable 不写任何样式），例如：
     .panel { opacity: 0; transform: translateY(24px);
              transition: opacity .6s ease, transform .6s cubic-bezier(.22,1,.36,1); }
     .panel.is-in { opacity: 1; transform: none; }
     // 无障碍兜底：系统开启「减弱动态效果」时直接显示，不参与入场
     @media (prefers-reduced-motion: reduce) {
       .panel { opacity: 1; transform: none; transition: none; }
     }

   契约：
     useReveal(options?) => { targetRef, visible }
     · options.threshold   = 0.15   交叉比例阈值（元素 15% 进入视口即触发）
     · options.rootMargin  = '0px'  视口扩边（如 '0px 0px -10% 0px' 提前量）
     · options.once        = true   触发一次后 unobserve（visible 永久 true）
     · targetRef                     模板 ref，绑定到要入场的元素
     · visible                       ref<boolean>，进入视口置 true
   降级与清理：
     · IntersectionObserver 不可用（SSR / 老 WebView）→ visible 直接 true，
       内容绝不因能力检测而缺失；
     · once=true 触发后断开观察（unobserve），不重复回调；
     · onScopeDispose 自动 observer.disconnect()，无泄漏。
   ============================================================ */
import { onScopeDispose, ref, watch } from 'vue'

export function useReveal(options = {}) {
  const threshold = options.threshold == null ? 0.15 : options.threshold
  const rootMargin = options.rootMargin == null ? '0px' : options.rootMargin
  const once = options.once == null ? true : !!options.once

  const targetRef = ref(null)
  const visible = ref(false)

  let observer = null
  let finished = false // once 触发后置 true，元素重挂载也不再重新观察

  const disconnect = () => {
    if (observer) {
      observer.disconnect()
      observer = null
    }
  }

  const observe = (el) => {
    disconnect()
    if (!el || typeof el.nodeType !== 'number') return
    // 能力检测失败（SSR / 老 WebView 无 IntersectionObserver）：不藏内容，直接可见
    if (typeof IntersectionObserver !== 'function') {
      visible.value = true
      finished = true
      return
    }
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          visible.value = true
          if (once) {
            finished = true
            disconnect() // 触发一次后即断开，之后不再回调
          }
        } else if (!once) {
          // once=false：跟随视口往返切换（离开视口复位为 false）
          visible.value = false
        }
      }
    }, { threshold, rootMargin })
    observer.observe(el)
  }

  // 元素可能晚挂载（v-if / 异步渲染）：watch 到真实节点后再 observe；
  // flush:'post' 保证此刻 DOM 已更新、模板 ref 已赋值。
  watch(
    targetRef,
    (el) => {
      if (finished && once) {
        if (el) visible.value = true // 已触发过：重挂载元素保持可见态
        return
      }
      observe(el)
    },
    { immediate: true, flush: 'post' }
  )

  onScopeDispose(disconnect)

  return { targetRef, visible }
}
