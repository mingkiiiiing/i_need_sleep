<template>
  <HeroShell
    eyebrow="Demo Flow"
    title="演示流程"
    description="本页单独作为答辩讲解脚本，用于把讲解节奏和点击顺序说明清楚。"
  >
    <template #actions>
      <RouterLink class="button primary" to="/cockpit">进入驾驶舱总览</RouterLink>
      <RouterLink class="button secondary" to="/">返回首页</RouterLink>
    </template>
    <section class="content-panel">
      <h2>建议顺序</h2>
      <ul>
        <li>先讲命题背景和项目目标</li>
        <li>再讲系统闭环与技术路线</li>
        <li>然后进入驾驶舱总览页</li>
        <li>最后分别打开监测站页、风险热区页、历史轨迹页</li>
      </ul>
    </section>
  </HeroShell>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'
</script>
