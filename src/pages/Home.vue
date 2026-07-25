<template>
  <main class="shell">
    <section class="home-hero">
      <div>
        <p class="eyebrow">A23 服务外包大赛 · Vue 版首页</p>
        <h1>澜镜 A23 蓝藻水华监测预警展示站</h1>
        <p>首页负责项目介绍和导航入口，每个专题都进入独立页面；驾驶舱里的 tab 也独立成页，结构更接近真实产品。</p>
        <div class="actions">
          <RouterLink class="button primary" to="/cockpit">进入驾驶舱总览</RouterLink>
          <RouterLink class="button secondary" to="/project-overview">打开项目概览页</RouterLink>
        </div>
      </div>
      <div class="preview-map">
        <div class="preview-badge a">西北热点区</div>
        <div class="preview-badge b">入湖河口站</div>
        <div class="preview-badge c">东南监测站</div>
      </div>
    </section>

    <section class="home-grid">
      <RouterLink v-for="card in cards" :key="card.to" class="nav-card" :to="card.to">
        <small>{{ card.no }}</small>
        <strong>{{ card.title }}</strong>
        <p>{{ card.text }}</p>
      </RouterLink>
    </section>
  </main>
</template>

<script setup>
const cards = [
  { no: '01', title: '项目概览', text: '单独介绍命题背景、项目目标和业务价值。', to: '/project-overview' },
  { no: '02', title: '技术路线', text: '单独说明数据、机理、AI 与可视化闭环。', to: '/tech-route' },
  { no: '03', title: '演示流程', text: '单独放答辩讲解顺序和点击路径。', to: '/demo-flow' },
  { no: '04', title: '驾驶舱总览', text: '进入地图系统，再打开各个驾驶舱页面。', to: '/cockpit' }
]
</script>
