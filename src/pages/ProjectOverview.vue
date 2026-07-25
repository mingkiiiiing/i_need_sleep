<template>
  <HeroShell
    eyebrow="Project Goal"
    title="项目概览"
    description="本页单独承担项目介绍功能，用来说明 A23 命题背景、蓝藻水华治理痛点，以及为什么采用数据治理、机理模型、AI 增强和驾驶舱展示的整体方案。"
  >
    <template #actions>
      <RouterLink class="button primary" to="/tech-route">下一页：技术路线</RouterLink>
      <RouterLink class="button secondary" to="/">返回首页</RouterLink>
    </template>
    <section class="content-panel">
      <h2>页面内容</h2>
      <ul>
        <li>命题背景与业务场景</li>
        <li>项目目标与核心价值</li>
        <li>监测、预测、预警一体化系统的必要性</li>
      </ul>
    </section>
  </HeroShell>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'
</script>
