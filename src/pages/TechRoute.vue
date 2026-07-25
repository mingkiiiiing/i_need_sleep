<template>
  <HeroShell
    eyebrow="Tech Route"
    title="技术路线"
    description="本页单独说明系统的技术闭环，避免在首页把技术逻辑和地图展示混在一起。"
  >
    <template #actions>
      <RouterLink class="button primary" to="/demo-flow">下一页：演示流程</RouterLink>
      <RouterLink class="button secondary" to="/">返回首页</RouterLink>
    </template>
    <section class="content-panel">
      <h2>核心链路</h2>
      <ul>
        <li>多源感知：遥感、水质、气象、水文等数据接入</li>
        <li>数据治理：缺失值插补、异常检测、时空对齐</li>
        <li>机理建模：藻类生长动力学与环境约束</li>
        <li>AI 增强：时序预测、风险分类、可解释性分析</li>
        <li>业务展示：地图驾驶舱、点位联动、预警推送</li>
      </ul>
    </section>
  </HeroShell>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'
</script>
