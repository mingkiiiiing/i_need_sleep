<template>
  <section class="stn-block stn-trend-panel" aria-label="指标趋势与预测能力状态">
    <header class="stn-sec-head">
      <h2>指标趋势</h2>
      <span class="stn-sec-tag">模拟观测样本 · 不插值</span>
    </header>

    <div class="stn-chip-rows">
      <div class="stn-chip-row" role="group" aria-label="展示指标">
        <button
          v-for="v in variables"
          :key="v.code"
          type="button"
          class="stn-chip"
          :class="{ active: selectedVars.includes(v.code) }"
          :aria-pressed="String(selectedVars.includes(v.code))"
          :aria-disabled="!selectedVars.includes(v.code) && selectedVars.length >= 4 ? 'true' : undefined"
          :title="!selectedVars.includes(v.code) && selectedVars.length >= 4 ? '最多同时选择 4 项指标' : undefined"
          @click="toggleVar(v.code)"
        >{{ v.label }}<small v-if="v.unit">（{{ v.unit }}）</small></button>
        <span v-if="!variables.length && state === 'ok'" class="stn-chip-none">接口未返回可绘制指标</span>
      </div>
      <div class="stn-chip-row" role="group" aria-label="时间范围">
        <button
          v-for="w in windows"
          :key="w.value"
          type="button"
          class="stn-chip stn-chip--win"
          :class="{ active: window === w.value }"
          :aria-pressed="String(window === w.value)"
          @click="window = w.value"
        >{{ w.label }}</button>
      </div>
    </div>

    <div v-if="state === 'loading'" class="stn-trend-body" role="status" aria-label="趋势数据加载中">
      <div class="skel-chart"></div>
    </div>

    <StatePanel
      v-else-if="state === 'error'"
      state="error"
      title="观测数据加载失败"
      description="模拟观测接口请求失败，可重试加载。"
    >
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </StatePanel>

    <template v-else>
      <div v-if="windowRows.length" class="stn-trend-body">
        <EChart :option="chartOption" :height="chartHeight" />
        <p v-if="singlePointOnly" class="stn-trend-note stn-trend-note--sparse" role="status">
          当前数据不足以形成连续趋势：窗口内每个指标最多 1 个模拟观测点，仅显示点标记。
        </p>
      </div>
      <StatePanel
        v-else
        state="empty"
        title="当前时间窗口内没有观测点"
        description="模拟观测样本未落在所选窗口内。可切换更大的时间范围查看实际返回的数据点。"
      />
      <p class="stn-trend-note">
        当前曲线来自模拟观测样本；数据稀疏时不进行插值，不代表真实历史趋势。
      </p>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import EChart from '../cockpit/EChart.vue'
import StatePanel from '../common/StatePanel.vue'
import { palette } from '../cockpit/echartsTheme.js'
import { useTheme } from '../../composables/useTheme.js'
import { variableLabel, filterByWindow, formatStamp, qualityText, formatValue } from './stationDisplay.js'

const props = defineProps({
  observations: { type: Array, default: () => [] },
  state: { type: String, default: 'loading' }, // loading | error | ok
  refreshing: { type: Boolean, default: false }
})

defineEmits(['retry'])

const { theme } = useTheme()
const windows = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' }
]
const window = ref('7d')

const variables = computed(() => {
  const seen = new Map()
  props.observations.forEach((r) => {
    if (!seen.has(r.variable_code)) seen.set(r.variable_code, { code: r.variable_code, unit: r.unit })
  })
  return [...seen.values()].map((v) => ({ ...v, label: variableLabel(v.code) }))
})

const selectedVars = ref([])
watch(
  variables,
  (vars) => {
    // 分区/观测变化后，默认选中接口实际返回的指标（≤4），不预选不存在的指标
    selectedVars.value = vars.slice(0, 4).map((v) => v.code)
  },
  { immediate: true }
)

function toggleVar(code) {
  const idx = selectedVars.value.indexOf(code)
  if (idx >= 0) {
    if (selectedVars.value.length > 1) selectedVars.value = selectedVars.value.filter((c) => c !== code)
  } else if (selectedVars.value.length < 4) {
    selectedVars.value = [...selectedVars.value, code]
  }
}

const windowRows = computed(() => filterByWindow(props.observations, window.value))

const singlePointOnly = computed(() => {
  const byVar = new Map()
  windowRows.value.forEach((r) => {
    const list = byVar.get(r.variable_code) || []
    list.push(r)
    byVar.set(r.variable_code, list)
  })
  const selected = [...byVar.entries()].filter(([code]) => selectedVars.value.includes(code))
  if (!selected.length) return false
  return selected.every(([, list]) => list.length <= 1)
})

const chartHeight = 165

const chartOption = computed(() => {
  const p = palette()
  void theme.value
  const seriesColors = [p.accent, p.ai, p.watch, p.stable]

  // 单位分组 → 最多双 Y 轴
  const unitAxis = new Map()
  const rows = windowRows.value.filter((r) => selectedVars.value.includes(r.variable_code))
  rows.forEach((r) => {
    if (!unitAxis.has(r.unit)) unitAxis.set(r.unit, Math.min(unitAxis.size, 1))
  })

  const axisName = [...unitAxis.keys()]
  const byVar = new Map()
  rows.forEach((r) => {
    const list = byVar.get(r.variable_code) || []
    list.push(r)
    byVar.set(r.variable_code, list)
  })

  const series = [...byVar.entries()].map(([code, list], i) => {
    const sorted = list.slice().sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at))
    const unit = sorted[0].unit
    return {
      name: variableLabel(code),
      type: 'line',
      yAxisIndex: unitAxis.get(unit) || 0,
      connectNulls: false,
      symbol: 'circle',
      symbolSize: sorted.length <= 1 ? 10 : 6,
      lineStyle: { width: 2, color: seriesColors[i % seriesColors.length] },
      itemStyle: { color: seriesColors[i % seriesColors.length] },
      data: sorted.map((r) => ({
        value: [Date.parse(r.observed_at), r.clean_value],
        row: r
      }))
    }
  })

  return {
    grid: { left: 44, right: axisName.length > 1 ? 52 : 20, top: 30, bottom: 26, containLabel: true },
    legend: { top: 0, textStyle: { color: p.textSoft, fontSize: 11 } },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text, fontSize: 12 },
      formatter: (params) => {
        const lines = []
        params.forEach((param) => {
          const row = param.data && param.data.row
          if (!row) return
          lines.push(
            `<b>${param.seriesName}</b>：${formatValue(row.clean_value)} ${row.unit || ''}<br/>` +
            `时间：${formatStamp(row.observed_at)}<br/>` +
            `质量：${qualityText(row.quality_status)} · 来源：${row.value_origin || '—'}<br/>` +
            `版本：${row.dataset_version || '—'}${row.is_imputed ? ' · 插补值' : ''}`
          )
        })
        return lines.join('<br/><br/>')
      }
    },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.muted, fontSize: 11, hideOverlap: true },
      splitLine: { show: false }
    },
    yAxis: axisName.map((unit, i) => ({
      type: 'value',
      name: unit,
      nameTextStyle: { color: p.muted, fontSize: 10 },
      scale: true,
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line } }
    })),
    series
  }
})
</script>

<style scoped>
.stn-trend-body {
  min-height: 200px;
}
.stn-chip-none {
  font-size: 12px;
  color: var(--text-muted);
  padding: 6px 2px;
}
</style>
