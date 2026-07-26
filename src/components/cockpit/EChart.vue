<template>
  <div ref="rootRef" style="width: 100%; height: 260px;"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  TitleComponent,
  DataZoomComponent,
  MarkAreaComponent,
  MarkLineComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { echartsBase, tooltipBase, gridBase, axisLine, splitLine, axisLabel } from './echartsTheme.js'

echarts.use([
  LineChart,
  BarChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  TitleComponent,
  DataZoomComponent,
  MarkAreaComponent,
  MarkLineComponent,
  CanvasRenderer
])

const props = defineProps({
  option: { type: Object, required: true }
})

const rootRef = ref(null)
let chart = null

function init() {
  if (!rootRef.value) return
  chart = echarts.init(rootRef.value, null, { renderer: 'canvas' })
  chart.setOption({
    ...echartsBase,
    ...props.option
  })
}

function onResize() {
  chart && chart.resize()
}

onMounted(() => {
  init()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})

watch(
  () => props.option,
  () => {
    if (chart) {
      chart.setOption({
        ...echartsBase,
        ...props.option
      }, true)
    }
  },
  { deep: true }
)

defineExpose({ getInstance: () => chart })
</script>