<!-- ============================================================
     ScrambleText.vue · 标题「解码 / 打乱收敛」动画组件（入场编排套件 H4）
     ------------------------------------------------------------
     props 契约：
       text     String  required  目标文本（终帧严格 === text，绝不残留错字）
       duration Number  = 900     收敛总时长 ms（0 或负数视为禁用动画）
       play     Boolean = true    挂载时播放；false → true 时重播
       tag      String  = 'span'  外层渲染标签（如 'h1' 'h2' 'div'）
     重播规则（按字面约定）：
       · 挂载时 play=true → 播放；
       · play 从 false 变 true → 重播；
       · props.text 变化 → 无条件重播（reduced-motion 下内部直出新文本）。

     收敛算法：
       · 字符按码点拆分（Array.from，兼容代理对）；第 i 位在 (i/n)*duration
         时刻锁定，从左到右扫掠收敛；未锁定位每帧（约 40ms，落在 30–50ms
         区间）从工程字符池随机跳动；
       · 空白字符（空格等）自始保持真实字形——既无解码观感价值，也避免
         动画期间行内空隙跳变；
       · 全部位锁定后立即切回静态真实文本节点（DOM 内即真实文案，可选中、
         可翻译），终帧 === text；
       · prefers-reduced-motion: reduce / 无 rAF / duration<=0 / 空文本 →
         零动画直出 text。

     可访问性：
       · 外层元素 aria-label=text —— 读屏任何时候听到的都是真实文本；
       · 动画字符容器（sizer + live）aria-hidden —— 打乱字符不进无障碍树。

     布局稳定（收敛期间零回流抖动）：
       · 动画期间渲染两份内容：隐藏 sizer（visibility:hidden 的真实文本）
         精确预留终态宽度/高度（中文全角字符按原字号占位），打乱字符层
         absolute 覆盖其上，只在自己的盒子内变化，不影响周边排版；
       · 组件只管结构与动画定位，不加颜色/字体装饰，字号字重颜色全部
         继承使用处（tokens.css 三主题自然生效）。

     用法示例：
       <ScrambleText tag="h1" text="太湖蓝藻智能研判" :duration="900" />
     ============================================================ -->
<script setup>
import { onMounted, onScopeDispose, ref, watch } from 'vue'

defineOptions({ name: 'ScrambleText' })

const props = defineProps({
  text: { type: String, required: true },
  duration: { type: Number, default: 900 },
  play: { type: Boolean, default: true },
  tag: { type: String, default: 'span' }
})

/* 克制的工程字符池：ASCII 工程符号 + 少量半角片假名（宽度近似半角） */
const GLYPH_POOL =
  '01<>[]{}#%&@$=+*/\\|~^' +
  'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ'

const FRAME_MS = 40 // 打乱字符跳动节拍（30–50ms/帧 区间中值）

const animating = ref(false)
const frame = ref('') // 动画期间的展示串；非动画态模板直接渲染 props.text

let rafId = 0

function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function randomGlyph() {
  return GLYPH_POOL[(Math.random() * GLYPH_POOL.length) | 0]
}

function stop() {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = 0
  }
}

function playScramble() {
  stop()
  const chars = Array.from(String(props.text ?? ''))
  const dur = Math.max(0, Number(props.duration) || 0)
  // 降级链：reduced-motion / 无 rAF / duration<=0 / 空文本 → 零动画直出
  if (
    !chars.length ||
    dur <= 0 ||
    prefersReducedMotion() ||
    typeof window === 'undefined' ||
    typeof requestAnimationFrame !== 'function' ||
    typeof performance === 'undefined'
  ) {
    animating.value = false
    frame.value = ''
    return
  }

  const n = chars.length
  // 第 i 位锁定时刻：(i/n)*duration —— 从左到右扫掠；首位 t=0 即锁定
  const lockTimes = chars.map((_, i) => (i / n) * dur)
  let startAt = 0
  let lastShuffleAt = -Infinity
  let shuffled = chars.map(randomGlyph).join('')

  animating.value = true

  const tick = (now) => {
    if (!startAt) startAt = now
    const t = now - startAt
    // 打乱层节流：至多每 FRAME_MS 重新随机一次，锁定判定仍每帧精确
    if (t - lastShuffleAt >= FRAME_MS) {
      lastShuffleAt = t
      shuffled = chars.map(randomGlyph).join('')
    }
    let done = true
    let out = ''
    for (let i = 0; i < n; i++) {
      const c = chars[i]
      // 空白字符自始锁定，避免行内空隙跳变
      if (t >= lockTimes[i] || /\s/.test(c)) {
        out += c
      } else {
        out += shuffled[i]
        done = false
      }
    }
    if (done) {
      // 全部位锁定：直接退回静态真实文本节点，终帧严格 === text
      rafId = 0
      animating.value = false
      frame.value = ''
      return
    }
    frame.value = out
    rafId = requestAnimationFrame(tick)
  }
  rafId = requestAnimationFrame(tick)
}

onMounted(() => {
  if (props.play) playScramble()
})
watch(
  () => props.play,
  (v) => {
    if (v) playScramble() // false → true 重播
  }
)
watch(
  () => props.text,
  () => playScramble() // 文本变化无条件重播（reduced-motion 内部直出）
)
onScopeDispose(stop)
</script>

<template>
  <component :is="tag" class="scramble" :aria-label="text">
    <template v-if="animating">
      <!-- sizer：隐藏的真实文本，精确预留终态宽高（全角字符按原字号占位） -->
      <span class="scramble-sizer" aria-hidden="true">{{ text }}</span><span class="scramble-live" aria-hidden="true">{{ frame }}</span>
    </template>
    <template v-else>{{ text }}</template>
  </component>
</template>

<style scoped>
/* 只管结构与动画定位，不加任何颜色/字体装饰（全部继承使用处） */
.scramble {
  position: relative;
  display: inline-block;
  max-width: 100%;
}
.scramble-sizer {
  visibility: hidden;
}
.scramble-live {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  pointer-events: none;
  user-select: none;
}
</style>
