<template>
  <main class="shell">
    <section class="cockpit-header">
      <div>
        <p class="eyebrow">驾驶舱 · 监测站页面</p>
        <h1>监测站点位总览</h1>
      </div>
      <div class="top-metrics">
        <article><span>页面</span><strong>监测站</strong></article>
        <article><span>点位数</span><strong>6</strong></article>
        <article><span>当前风险</span><strong>{{ selectedPoint.risk }}</strong></article>
      </div>
    </section>

    <main class="dashboard-layout">
      <LakeMap v-model="selectedKey" active-tab="stations" title="地图点位总览" />
      <PointDetail :point="selectedPoint" :stage="stage" />
    </main>

    <section class="bottom-grid">
      <article class="panel mini-panel">
        <div class="section-line"><h3>页面导航</h3><span>Vue Router</span></div>
        <div class="loop-list">
          <RouterLink class="loop-link active" to="/stations">监测站</RouterLink>
          <RouterLink class="loop-link" to="/heatmap">风险热区</RouterLink>
          <RouterLink class="loop-link" to="/history">历史轨迹</RouterLink>
        </div>
      </article>
      <article class="panel mini-panel">
        <div class="section-line"><h3>时间推演</h3><span>{{ stageLabel }}</span></div>
        <input v-model="stage" class="wide-range" type="range" min="0" max="3">
      </article>
      <article class="panel mini-panel trend-panel">
        <div class="section-line"><h3>趋势曲线</h3><span>点位风险变化</span></div>
        <TrendCanvas :values="selectedPoint.trend" />
      </article>
    </section>
  </main>
</template>

<script setup>
import { computed, ref } from 'vue'
import { pointData, timeStages } from '../data/points'
import LakeMap from '../components/LakeMap.vue'
import PointDetail from '../components/PointDetail.vue'
import TrendCanvas from '../components/TrendCanvas.vue'

const selectedKey = ref('northwest_hotspot')
const stage = ref(1)
const selectedPoint = computed(() => pointData[selectedKey.value])
const stageLabel = computed(() => timeStages[stage.value].label)
</script>
