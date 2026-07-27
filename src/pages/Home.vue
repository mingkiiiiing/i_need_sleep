<template>
  <main class="home-shell">
    <!-- 顶部边角签名 + 状态 -->
    <header class="home-corner" :class="{ 'in': ready }">
      <div class="home-corner-left">
        <span class="corner-tag">A23 · LAKE TWIN · v1.0</span>
        <span class="corner-tag-sub">CYANOBACTERIA · 蓝藻水华</span>
      </div>
      <div class="home-corner-right">
        <span class="status-pill">
          <span class="status-dot"></span>
          实时：{{ liveSummary }}
        </span>
        <span class="corner-tag-sub">{{ liveTime }}</span>
      </div>
    </header>

    <!-- 主体：左侧 hero，右侧并列入口 sticky 边栏 -->
    <section class="home-main" :class="{ 'in': ready }" :style="parallax">
      <article class="home-hero">
        <p class="hero-eyebrow" style="--enter-delay: 80ms;">
          <span class="eyebrow-num">01 / 04</span>
          <span class="eyebrow-rule"></span>
          <span class="eyebrow-label">项目主页 · HOMEPAGE</span>
        </p>

        <h1 class="hero-title">
          <span class="hero-line" style="--enter-delay: 160ms;">蓝藻水华</span>
          <span class="hero-line accent-shift" style="--enter-delay: 280ms;">监测预警 /</span>
          <span class="hero-line" style="--enter-delay: 400ms;">机理 &times; AI 融合</span>
        </h1>

        <div class="hero-meta" style="--enter-delay: 540ms;">
          <div class="meta-cell">
            <span class="meta-key">主题</span>
            <span class="meta-value">数据与计算</span>
          </div>
          <div class="meta-cell">
            <span class="meta-key">赛题</span>
            <span class="meta-value">A23 · 应用类</span>
          </div>
          <div class="meta-cell">
            <span class="meta-key">主办</span>
            <span class="meta-value">我有一点困</span>
          </div>
        </div>

        <p class="hero-prose" style="--enter-delay: 700ms;">
          地表水湖华是富营养化水体在特定水文气候条件下发生的生态灾变现象，传统"人工采样 + 实验室分析"的监测模式已经难以满足提前预警与精准防控的管理需要。
          本项目以机理 + AI 融合的思路构建模型，把藻类生长动力学、水流输运守恒等物理机理嵌入神经网络架构，或利用 AI 对机理模型参数进行实时校正，
          形成兼具物理可解释性与数据自适应性的混合智能模型，依托多源数据驱动实现蓝藻水华早识别、早预报、早预警。
        </p>

        <div class="hero-keyline" style="--enter-delay: 880ms;">
          <span>机理可解释</span><span class="keyline-dot"></span>
          <span>数据自适应</span><span class="keyline-dot"></span>
          <span>短 / 中 / 长期尺度</span><span class="keyline-dot"></span>
          <span>数字孪生驾驶舱</span>
        </div>
      </article>

      <!-- 右侧 sticky 入口边栏（克制不抢戏） -->
      <aside class="home-rail" style="--enter-delay: 320ms;">
        <p class="rail-eyebrow">SECTION INDEX</p>
        <ol class="rail-list">
          <li
            v-for="(entry, i) in entries"
            :key="entry.to"
            :style="{ '--enter-delay': (420 + i * 90) + 'ms' }"
          >
            <RouterLink :to="entry.to" class="rail-link">
              <span class="rail-num">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="rail-title">
                <strong>{{ entry.title }}</strong>
                <small>{{ entry.voice }}</small>
              </span>
              <span class="rail-arrow">→</span>
            </RouterLink>
          </li>
        </ol>
        <p class="rail-foot">点击右侧编号进入对应模块</p>
      </aside>
    </section>

    <!-- 底部主办 + 能力脚注（一行纯文本） -->
    <footer class="home-foot" style="--enter-delay: 1080ms;">
      <span>主办：<strong>我有一点困</strong></span>
      <span class="foot-sep">/</span>
      <span>承办：<strong>蓝竞系统</strong></span>
      <span class="foot-sep">/</span>
      <span>机理 + AI 融合范式</span>
      <span class="foot-sep">/</span>
      <span>T+1 · T+3 · T+7 · T+15 · T+30 跨尺度预测</span>
    </footer>
  </main>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'

const entries = [
  { to: '/project-overview', title: '项目概览', voice: 'PROJECT OVERVIEW' },
  { to: '/tech-route',        title: '技术路线', voice: 'TECH ROUTE' },
  { to: '/demo-flow',         title: '演示流程', voice: 'DEMO FLOW' },
  { to: '/cockpit',           title: '驾驶舱',   voice: 'COCKPIT' }
]

const ready = ref(false)
const scrollY = ref(0)

const liveSummary = '湖体 6 监测点 · 1 处红色预警'
const liveTime = computed(() => {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

// 滚动驱动视差：仅在桌面且滚动区间足够时启用
const parallax = computed(() => {
  const dy = scrollY.value
  return {
    '--py-title': `${Math.min(40, dy * 0.06)}px`,
    '--py-meta':  `${Math.min(-30, dy * -0.04)}px`,
    '--py-prose': `${Math.min(28, dy * 0.035)}px`
  }
})

function onScroll() {
  scrollY.value = window.scrollY || window.pageYOffset || 0
}

onMounted(() => {
  // 入场入场：先阻塞状态，等一帧再触发 in，配合 CSS 过渡
  requestAnimationFrame(() => {
    ready.value = true
  })
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>