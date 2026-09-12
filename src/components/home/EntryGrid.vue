<!-- ============================================================
     EntryGrid.vue · 首页「核心业务入口」六卡（工程炫技升级版，H2）
     ------------------------------------------------------------
     props 契约：entries: Array (required)，同构于 Home.vue entries
       —— [{ to: string, title: string, desc: string }]
     to/title/desc 由父组件原样传入，本组件逐字渲染，不加工文案。

     手法清单（awwwards 风格，克制）：
     1. 聚光边框卡：pointermove 写入 --mx/--my，双层卡 + 1px 渐变遮罩
        边框（mask-composite 掏空），悬停处卡缘泛卡主题色光。
     2. 磁吸微倾斜：hover 映射指针位置 → rotateX/rotateY ≤4°
        （perspective 800px）+ 轻微上浮，200ms 回弹；
        prefers-reduced-motion / 触屏（pointerType=touch）关闭倾斜。
     3. 滚动 stagger 入场：IntersectionObserver 阈值 0.15 一次性触发，
        每卡 delay 60ms 阶梯 translate+opacity；reduced-motion 直接显示；
        触发完成后观察器即断开。
     4. 语义图标：40px 内联 svg 线框（stroke=currentColor，随卡主题色）。
     5. 卡主题色：--card-c 语义令牌（含一个中性钢青）。
     6. CTA「进入 →」原文案 + hover 箭头位移。
     7. 可访问性：focus-visible 主色描边；装饰/图标 aria-hidden；h2 层级。
     8. 响应式：桌面 3×2 / ≤1100px 2×3 / ≤700px 单列。
     ============================================================ -->

<template>
  <section class="entgrid" aria-labelledby="entries-title">
    <header class="entgrid-head">
      <h2 id="entries-title" class="entgrid-title">核心业务入口</h2>
      <span class="entgrid-rule" aria-hidden="true"></span>
    </header>

    <div ref="gridEl" class="entgrid-grid">
      <div
        v-for="(e, i) in entries"
        :key="e.to"
        class="entcell"
        :style="{ '--d': i * 60 + 'ms' }"
      >
        <RouterLink
          :to="e.to"
          class="entcard"
          :class="'entcard--' + toneOf(e.to)"
          @pointermove="handlePointerMove"
          @pointerleave="handlePointerLeave"
        >
          <!-- 聚光层（跟随指针的内部柔光） -->
          <span class="entcard-spot" aria-hidden="true"></span>
          <!-- 1px 渐变遮罩边框（悬停泛主色光） -->
          <span class="entcard-edge" aria-hidden="true"></span>

          <span class="entcard-idx" aria-hidden="true">{{ String(i + 1).padStart(2, '0') }}</span>

          <span class="entcard-icon" aria-hidden="true">
            <svg
              class="entcard-svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              focusable="false"
            >
              <!-- 综合驾驶舱：罗盘 -->
              <g v-if="iconOf(e.to) === 'compass'">
                <circle cx="12" cy="12" r="8.6" />
                <path d="M15.4 8.6 13.4 13.4 8.6 15.4 10.6 10.6z" />
                <path d="M12 3.4v1.4M20.6 12h-1.4M12 20.6v-1.4M3.4 12h1.4" />
              </g>
              <!-- 监测站点研判：定位节点 -->
              <g v-else-if="iconOf(e.to) === 'node'">
                <path d="M12 21.2s-6.6-5.4-6.6-10.4a6.6 6.6 0 1 1 13.2 0c0 5-6.6 10.4-6.6 10.4z" />
                <circle cx="12" cy="10.6" r="2.5" />
              </g>
              <!-- 预警与应急预案中心：铃铛 -->
              <g v-else-if="iconOf(e.to) === 'bell'">
                <path d="M6.2 9.9a5.8 5.8 0 0 1 11.6 0c0 3.1.6 5 1.5 6.3H4.7c.9-1.3 1.5-3.2 1.5-6.3z" />
                <path d="M10 19.6a2.1 2.1 0 0 0 4 0" />
              </g>
              <!-- 卫星遥感与时空推演：卫星 -->
              <g v-else-if="iconOf(e.to) === 'satellite'">
                <rect x="9.9" y="9.9" width="4.2" height="4.2" rx="0.7" transform="rotate(45 12 12)" />
                <path d="M5.2 8.6 8.6 5.2l2.2 2.2-3.4 3.4z" />
                <path d="m18.8 15.4-3.4 3.4-2.2-2.2 3.4-3.4z" />
                <path d="M12 9V5.8" />
                <circle cx="12" cy="4.9" r="0.9" />
              </g>
              <!-- 实时观测历史复盘：时钟回箭头 -->
              <g v-else-if="iconOf(e.to) === 'history'">
                <path d="M3.6 12a8.4 8.4 0 1 0 8.4-8.4 8.9 8.9 0 0 0-6.3 2.7L3.6 8.4" />
                <path d="M3.6 3.9v4.5h4.5" />
                <path d="M12 7.6V12l3.1 1.8" />
              </g>
              <!-- 实时大屏：显示器网格 -->
              <g v-else>
                <rect x="3" y="4" width="18" height="13" rx="1.6" />
                <path d="M12 4v13" />
                <path d="M3 10.5h18" />
                <path d="M9.5 20.5h5" />
                <path d="M12 17v3.5" />
              </g>
            </svg>
          </span>

          <span class="entcard-title">{{ e.title }}</span>
          <span class="entcard-desc">{{ e.desc }}</span>
          <span class="entcard-cta">进入 <i aria-hidden="true">→</i></span>
        </RouterLink>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

// ---- props 契约：[{ to, title, desc }]，与 Home.vue entries 数组同构 ----
defineProps({
  entries: { type: Array, required: true }
})

// ---- 卡主题色映射（按 to 路径；顺序 = 业务动线） ----
const TONE_BY_PATH = {
  '/cockpit': 'accent',    // 湖青 var(--c-accent)
  '/stations': 'stable',   // 薄荷绿 var(--c-stable)
  '/alerts': 'alert',      // 珊瑚红 var(--c-alert)
  '/heatmap': 'ai',        // 紫罗兰 var(--c-ai)
  '/history': 'watch',     // 琥珀 var(--c-watch)
  '/wallboard': 'neutral'  // 中性钢青 var(--data-simulated)
}

function toneOf(to) {
  return TONE_BY_PATH[to] || 'neutral'
}

// ---- 语义图标映射（按 to 路径） ----
function iconOf(to) {
  switch (to) {
    case '/cockpit': return 'compass'
    case '/stations': return 'node'
    case '/alerts': return 'bell'
    case '/heatmap': return 'satellite'
    case '/history': return 'history'
    case '/wallboard': return 'wall'
    default: return 'compass'
  }
}

const gridEl = ref(null)

// ---- 磁吸微倾斜 + 聚光坐标：pointermove → CSS 变量（rAF 节流） ----
let reducedMQ = null
let reducedMotion = false
let frame = 0

function handlePointerMove(ev) {
  const card = ev.currentTarget
  if (!card || ev.pointerType === 'touch') return
  const box = card.getBoundingClientRect()
  const px = ev.clientX - box.left
  const py = ev.clientY - box.top
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    const s = card.style
    s.setProperty('--mx', px.toFixed(1) + 'px')
    s.setProperty('--my', py.toFixed(1) + 'px')
    // reduced-motion / 异常尺寸下只更新聚光坐标，不写入倾斜角
    if (reducedMotion || !box.width || !box.height) return
    const rx = Math.max(-4, Math.min(4, (0.5 - py / box.height) * 8))
    const ry = Math.max(-4, Math.min(4, (px / box.width - 0.5) * 8))
    s.setProperty('--rx', rx.toFixed(2) + 'deg')
    s.setProperty('--ry', ry.toFixed(2) + 'deg')
  })
}

function handlePointerLeave(ev) {
  const card = ev.currentTarget
  if (!card) return
  if (frame) { cancelAnimationFrame(frame); frame = 0 }
  card.style.setProperty('--rx', '0deg')
  card.style.setProperty('--ry', '0deg')
}

// ---- 滚动 stagger 入场：IntersectionObserver 一次性触发，触发后断开 ----
let revealIO = null
const cleanups = []

onMounted(() => {
  reducedMQ = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion = reducedMQ.matches
  const onMqChange = () => { reducedMotion = reducedMQ.matches }
  if (typeof reducedMQ.addEventListener === 'function') {
    reducedMQ.addEventListener('change', onMqChange)
    cleanups.push(() => reducedMQ.removeEventListener('change', onMqChange))
  }

  const cells = gridEl.value ? Array.from(gridEl.value.querySelectorAll('.entcell')) : []
  if (!cells.length) return

  // reduced-motion（或无 IO 支持）直接显示，不依赖观察器
  if (reducedMotion || typeof window.IntersectionObserver !== 'function') {
    cells.forEach((c) => c.classList.add('is-in'))
    return
  }

  let pending = cells.length
  revealIO = new IntersectionObserver(
    (records) => {
      for (const rec of records) {
        if (!rec.isIntersecting) continue
        rec.target.classList.add('is-in')
        if (revealIO) revealIO.unobserve(rec.target)
        pending -= 1
      }
      if (pending <= 0 && revealIO) {
        revealIO.disconnect()
        revealIO = null
      }
    },
    { threshold: 0.15 }
  )
  cells.forEach((c) => revealIO.observe(c))
})

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame)
  if (revealIO) { revealIO.disconnect(); revealIO = null }
  cleanups.forEach((fn) => fn())
})
</script>

<style scoped>
/* ============ 区块头部 ============ */
.entgrid-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 0 0 14px;
}
.entgrid-title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text-primary);
}
.entgrid-rule {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border-strong), transparent);
}

/* ============ 网格：3×2 / 2×3 / 单列 ============ */
.entgrid-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.entcell {
  display: flex;
  min-width: 0;
}
@media (max-width: 1100px) {
  .entgrid-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .entgrid-grid { grid-template-columns: minmax(0, 1fr); }
}

/* ============ 卡主题色（语义令牌） ============ */
.entcard--accent  { --card-c: var(--c-accent); }
.entcard--stable  { --card-c: var(--c-stable); }
.entcard--alert   { --card-c: var(--c-alert); }
.entcard--ai      { --card-c: var(--c-ai); }
.entcard--watch   { --card-c: var(--c-watch); }
.entcard--neutral { --card-c: var(--data-simulated); }

/* ============ 卡本体（双层卡外层：磁吸倾斜作用于此） ============ */
.entcard {
  --mx: 50%;
  --my: 50%;
  --rx: 0deg;
  --ry: 0deg;
  --lift: 0px;

  position: relative;
  isolation: isolate;
  overflow: hidden;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  min-height: 188px;
  padding: 20px 20px 18px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  color: inherit;
  text-decoration: none;
  transform: perspective(800px) rotateX(var(--rx)) rotateY(var(--ry)) translateY(var(--lift));
  transition:
    transform 200ms var(--ease-out),
    border-color 200ms var(--ease-out),
    box-shadow 200ms var(--ease-out);
}
.entcard:hover {
  --lift: -4px;
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
  box-shadow: var(--shadow-sm), 0 18px 44px -20px color-mix(in srgb, var(--card-c) 55%, transparent);
}
.entcard:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 3px;
  border-color: var(--border-strong);
}

/* ============ 聚光层：指针跟随的内部柔光 ============ */
.entcard-spot {
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: inherit;
  pointer-events: none;
  background: radial-gradient(300px circle at var(--mx) var(--my), rgba(120, 160, 180, 0.08), transparent 70%);
  background: radial-gradient(
    300px circle at var(--mx) var(--my),
    color-mix(in srgb, var(--card-c) 12%, transparent),
    transparent 70%
  );
  opacity: 0;
  transition: opacity 250ms var(--ease-out);
}
.entcard:hover .entcard-spot,
.entcard:focus-visible .entcard-spot { opacity: 1; }

/* ============ 1px 渐变遮罩边框（content-box 掏空） ============ */
.entcard-edge {
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: inherit;
  padding: 1px;
  pointer-events: none;
  background: radial-gradient(240px circle at var(--mx) var(--my), var(--card-c), transparent 75%);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 250ms var(--ease-out);
}
.entcard:hover .entcard-edge,
.entcard:focus-visible .entcard-edge { opacity: 1; }

/* ============ 内容层（置于装饰层之上） ============ */
.entcard-idx {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 1;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--text-muted);
}
.entcard-icon {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 50px;
  height: 50px;
  border: 1px solid color-mix(in srgb, var(--card-c) 24%, transparent);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--card-c) 10%, transparent);
  color: var(--card-c);
  transition: box-shadow 200ms var(--ease-out);
}
.entcard:hover .entcard-icon {
  box-shadow: 0 6px 18px -6px color-mix(in srgb, var(--card-c) 55%, transparent);
}
.entcard-svg {
  width: 40px;
  height: 40px;
}
.entcard-title {
  position: relative;
  z-index: 1;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.entcard-desc {
  position: relative;
  z-index: 1;
  flex: 1;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.entcard-cta {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--card-c);
}
.entcard-cta i {
  font-style: normal;
  transition: transform 200ms var(--ease-out);
}
.entcard:hover .entcard-cta i { transform: translateX(4px); }

/* ============ 滚动 stagger 入场（仅无 reduced-motion 时隐藏） ============ */
@media (prefers-reduced-motion: no-preference) {
  .entcell {
    opacity: 0;
    transform: translateY(20px);
    transition:
      opacity 560ms var(--ease-out) var(--d, 0ms),
      transform 560ms var(--ease-out) var(--d, 0ms);
  }
  .entcell.is-in {
    opacity: 1;
    transform: none;
  }
}

/* ============ reduced-motion：关闭倾斜与位移，只留边框光 ============ */
@media (prefers-reduced-motion: reduce) {
  .entcard {
    transform: none;
    transition: border-color 200ms var(--ease-out);
  }
  .entcard:hover { --lift: 0px; }
  .entcard-cta i { transition: none; }
  .entcard:hover .entcard-cta i { transform: none; }
  .entcard-spot,
  .entcard-edge { transition: none; }
}
</style>
