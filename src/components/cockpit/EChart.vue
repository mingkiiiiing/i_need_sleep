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
import { textTheme } from './echartsTheme.js'

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
const themeObserver = typeof MutationObserver !== 'undefined'
  ? new MutationObserver(() => onThemeChange())
  : null

function baseTheme() {
  return { textStyle: textTheme() }
}

function init() {
  if (!rootRef.value) return
  chart = echarts.init(rootRef.value, null, { renderer: 'canvas' })
  chart.setOption({
    ...baseTheme(),
    ...props.option
  })
}

function onResize() {
  chart && chart.resize()
}

function onThemeChange() {
  // 主题切换（html[data-theme] 变化）时，用最新 token 重绘
  if (chart) {
    chart.setOption({ ...baseTheme(), ...props.option }, true)
  }
}

onMounted(() => {
  init()
  window.addEventListener('resize', onResize)
  if (themeObserver) themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (themeObserver) themeObserver.disconnect()
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
        ...baseTheme(),
        ...props.option
      }, true)
    }
  },
  { deep: true }
)

defineExpose({ getInstance: () => chart })
</script>