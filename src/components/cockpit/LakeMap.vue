<template>
  <section class="panel map-panel">
    <header class="panel-head">
      <div>
        <p class="panel-kicker">LAKE TWIN MAP</p>
        <h2>{{ title }}</h2>
      </div>
      <div class="map-tools">
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'stations' }" to="/stations">监测站</RouterLink>
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'heatmap' }" to="/heatmap">风险分区</RouterLink>
        <RouterLink class="tool-chip" :class="{ active: activeTab === 'history' }" to="/history">历史轨迹</RouterLink>
      </div>
    </header>

    <div class="map-stage">
      <div class="water-grid"></div>
      <div class="shoreline shoreline-main"></div>
      <div class="shoreline shoreline-island"></div>
      <div class="flow-line flow-line-a"></div>
      <div class="flow-line flow-line-b"></div>

      <button
        v-for="point in pointList"
        :key="point.id"
        type="button"
        class="map-point"
        :class="[`level-${point.riskClass}`, { active: point.id === modelValue }]"
        :style="positions[point.id]"
        @click="$emit('update:modelValue', point.id)"
      >
        <span class="dot"></span>
        <span class="label">{{ point.short }} {{ point.name }}</span>
      </button>
    </div>

    <footer class="map-footer">
      <div class="legend-row">
        <span><span class="legend-dot high"></span>红色预警</span>
        <span><span class="legend-dot mid"></span>橙色关注</span>
        <span><span class="legend-dot low"></span>绿色稳定</span>
      </div>
      <span class="legend-row">点击点位查看详情 · 当前档位 {{ stageLabel }}</span>
    </footer>
  </section>
</template>

<script setup>
defineProps({
  modelValue: { type: String, required: true },
  pointList: { type: Array, required: true },
  positions: { type: Object, required: true },
  stageLabel: { type: String, default: '' },
  title: { type: String, default: '监测点位全景' },
  activeTab: { type: String, default: 'stations' }
})

defineEmits(['update:modelValue'])
</script>