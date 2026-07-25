<template>
  <section class="map-panel panel">
    <div class="panel-head">
      <div>
        <p class="panel-kicker">{{ kicker }}</p>
        <h2>{{ title }}</h2>
      </div>
      <div class="map-tools">
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'stations' }" to="/stations">监测站</RouterLink>
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'heatmap' }" to="/heatmap">风险热区</RouterLink>
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'history' }" to="/history">历史轨迹</RouterLink>
      </div>
    </div>

    <div class="map-stage">
      <div class="water-grid"></div>
      <div class="shoreline shoreline-main"></div>
      <div class="shoreline shoreline-island"></div>
      <div class="heat-zone heat-zone-a"></div>
      <div class="heat-zone heat-zone-b"></div>
      <div class="flow-line flow-line-a"></div>
      <div class="flow-line flow-line-b"></div>

      <button
        v-for="(point, key) in pointData"
        :key="key"
        class="map-point"
        :class="[`level-${point.riskClass}`, { active: modelValue === key }]"
        :data-point="key"
        :style="pointPositions[key]"
        @click="$emit('update:modelValue', key)"
      >
        <span class="dot"></span>
        <span class="label">{{ point.name }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
import { pointData, pointPositions } from '../data/points'

defineProps({
  modelValue: { type: String, required: true },
  activeTab: { type: String, default: 'stations' },
  kicker: { type: String, default: 'Lake Twin Map' },
  title: { type: String, default: '地图点位总览' }
})

defineEmits(['update:modelValue'])
</script>
