<template>
  <main class="shell heatmap-shell">
    <section class="heatmap-header">
      <div>
        <p class="eyebrow">COCKPIT · RISK HEATMAP</p>
        <h1>太湖蓝藻风险综合驾驶舱</h1>
        <p class="heatmap-subtitle">融合机理模型与 AI 推演，追踪蓝藻风险的空间聚集、扩散与收敛。</p>
      </div>
      <div class="header-status">
        <span class="status-light"></span>
        <div>
          <strong>{{ stageLabel || '数据加载中' }}</strong>
          <small>模型在线 · 预测置信度 {{ summary.confidence }}%</small>
        </div>
        <span class="risk-badge" :class="stageRiskClass">{{ stageRiskLabel }}</span>
      </div>
    </section>

    <section class="cockpit-grid">
      <aside class="panel cockpit-rail left-rail">
        <div class="rail-heading">
          <div>
            <p class="panel-kicker">RISK OVERVIEW</p>
            <h2>区域态势</h2>
          </div>
          <span class="rail-index">01</span>
        </div>

        <div class="risk-score">
          <span class="score-label">当前研判</span>
          <strong>{{ stageRiskLabel }}</strong>
          <span class="score-caption">{{ stageLabel }}</span>
        </div>

        <div class="metric-stack">
          <div class="metric-row metric-high">
            <span><i></i>高风险网格</span>
            <strong>{{ summary.highCells }}</strong>
            <small>{{ summary.highShare }}%</small>
          </div>
          <div class="metric-row metric-mid">
            <span><i></i>关注网格</span>
            <strong>{{ summary.midCells }}</strong>
            <small>{{ summary.midShare }}%</small>
          </div>
          <div class="metric-row metric-low">
            <span><i></i>稳定网格</span>
            <strong>{{ summary.lowCells }}</strong>
            <small>{{ summary.lowShare }}%</small>
          </div>
        </div>

        <div class="rail-section">
          <div class="section-line">
            <h3>当前研判</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <p class="rail-summary">{{ stageSummary }}</p>
        </div>

        <div class="rail-section rail-note">
          <span class="note-mark">AI</span>
          <div>
            <strong>融合模型共识度</strong>
            <small>机理层与 AI 层联合校准</small>
          </div>
          <b>{{ summary.confidence }}%</b>
        </div>
      </aside>

      <LakeMap
        class="map-stage"
        :model-value="cockpit.selectedPoint"
        :point-list="mapPointList"
        :positions="{}"
        :heat-field="heatField"
        :heat-stage-key="cockpit.stageKey"
        :stage-label="stageLabel"
        title="太湖风险热力分区"
        @update:model-value="setPoint"
      />

      <aside class="panel cockpit-rail right-rail">
        <div class="rail-heading">
          <div>
            <p class="panel-kicker">ANALYSIS FEED</p>
            <h2>研判分析</h2>
          </div>
          <span class="rail-index">02</span>
        </div>

        <section class="rail-section hotspot-section">
          <div class="section-line">
            <h3>热点区域排行</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="factor-list">
            <div v-for="(cell, i) in topCells" :key="cell.label" class="factor-track">
              <div class="factor-fill" :class="{ 'is-top': i === 0 }" :style="{ width: cell.width + '%' }"></div>
              <span class="factor-tag">{{ cell.label }}</span>
              <strong class="factor-value">{{ cell.value }}</strong>
            </div>
          </div>
        </section>

        <section class="rail-section chart-section">
          <div class="section-line">
            <h3>点位风险强度</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="chart-frame">
            <EChart :option="barOption" :height="200" />
          </div>
        </section>

        <section class="rail-section chart-section confidence-section">
          <div class="section-line">
            <h3>模型置信曲线</h3>
            <span>跨档位对比</span>
          </div>
          <div class="chart-frame">
            <EChart :option="confidenceOption" :height="168" />
          </div>
        </section>
      </aside>
    </section>

    <section class="timeline-dock">
      <div class="dock-label">
        <span class="dock-index">03</span>
        <div>
          <strong>时间推演</strong>
          <small>切换预测尺度</small>
        </div>
      </div>
      <TimeAxisBar :stages="stages" variant="axis" />
    </section>
    <footer class="cockpit-foot heatmap-foot">
      <span>数据源：机理模型 + AI 融合预测 · 当前视图：{{ stageTitle }}</span>
    </footer>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCockpitStore, cockpitState } from '../stores/cockpit.js'
import { getHeatField, getPoints, getRegionSummary, getTimeStages } from '../services/api.js'
import { palette } from '../components/cockpit/echartsTheme.js'
import { useTheme } from '../composables/useTheme.js'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import EChart from '../components/cockpit/EChart.vue'
import LakeMap from '../components/cockpit/LakeMap.vue'

const cockpit = useCockpitStore()
const cockpitMutable = cockpitState()
const { theme } = useTheme()

const stages = ref([])
const heatField = ref({})
const pointsState = ref({ pointData: {} })
const summaryState = ref({})

const pointList = computed(() => Object.values(pointsState.value.pointData))
const mapPointList = computed(() => pointList.value.map((point) => {
  const value = summaryState.value.intensity?.[point.id]?.[cockpit.stageKey] ?? 0
  return {
    ...point,
    riskClass: value >= 75 ? 'high' : value >= 45 ? 'mid' : 'low'
  }
}))

function setPoint(pointId) {
  cockpitMutable.selectedPoint = pointId
}
const currentGrid = computed(() => heatField.value[cockpit.stageKey] || [])
const stageLabel = computed(() => {
  const item = stages.value.find((s) => s.key === cockpit.stageKey)
  return item ? item.label : ''
})

const stageTitle = computed(() => {
  switch (cockpit.stageKey) {
    case 't1':  return '未来 1 天：紧急研判 / 立即响应'
    case 't3':  return '未来 3 天：短期扩散 / 周内联动'
    case 't7':  return '未来 7 天：中期研判 / 资源调度'
    case 't15': return '未来 15 天：长期推演 / 滚动校准'
    case 't30': return '未来 30 天：综合态势 / 战略复盘'
    default:    return '风险热力分布'
  }
})

const stageRiskLabel = computed(() => {
  return ['红色预警', '橙色关注', '橙色关注', '稳定参考', '稳定参考'][
    stages.value.findIndex((s) => s.key === cockpit.stageKey)
  ] || '稳定参考'
})

const stageRiskClass = computed(() => {
  const k = cockpit.stageKey
  if (k === 't1') return 'high'
  if (k === 't3' || k === 't7') return 'mid'
  return 'low'
})

const stageSummary = computed(() => {
  switch (cockpit.stageKey) {
    case 't1':
      return '西北热点聚集明显，北部入湖河口脉冲输入叠加。建议立即启动巡查与封湖评估，联动南部通道与取水口做近邻扩散研判。'
    case 't3':
      return '风险高值开始沿西北-东南方向拓展，北部河口输入仍处高位，湖心校准点出现漂移。建议加密取水口与南部通道观测频次。'
    case 't7':
      return '高风险网格在湖北侧连片，关注 7 天后是否向湖心延伸。机理层与 AI 层均提示取水口进入重点保障窗口。'
    case 't15':
      return '长期视角下高值区趋于收敛，但仍需关注营养盐持续补给情景。建议保留切面用于下一轮窗口研判。'
    case 't30':
      return '整体进入稳态参考区间。30 天尺度适合作为应急资源复盘与机理模型参数更新窗口。'
    default:
      return '切换档位查看不同时间尺度的风险分布与建议。'
  }
})

const summary = computed(() => {
  if (!currentGrid.value.length) {
    return { highCells: 0, midCells: 0, lowCells: 0, highShare: 0, midShare: 0, lowShare: 0, confidence: 0 }
  }
  let high = 0, mid = 0, low = 0
  currentGrid.value.forEach((row) => row.forEach((v) => {
    if (v >= 75) high++
    else if (v >= 45) mid++
    else low++
  }))
  const total = high + mid + low || 1
  return {
    highCells: high,
    midCells: mid,
    lowCells: low,
    highShare: Math.round((high / total) * 100),
    midShare:  Math.round((mid  / total) * 100),
    lowShare:  Math.round((low  / total) * 100),
    confidence: ['t1', 't3', 't7', 't15', 't30'].includes(cockpit.stageKey)
      ? ({ t1: 86, t3: 82, t7: 78, t15: 71, t30: 68 }[cockpit.stageKey])
      : 0
  }
})

const topCells = computed(() => {
  if (!currentGrid.value.length) return []
  const flat = []
  currentGrid.value.forEach((row, r) => row.forEach((v, c) => {
    flat.push({ row: r, col: c, value: v })
  }))
  flat.sort((a, b) => b.value - a.value)
  const list = flat.slice(0, 5)
  const max = list[0]?.value || 100
  return list.map((cell, i) => ({
    label: `地图热点区 #${i + 1}`,
    value: cell.value,
    width: Math.max(8, Math.round((cell.value / max) * 100))
  }))
})

const barOption = computed(() => {
  const p = palette()
  void theme.value
  const list = pointList.value.map((pt) => ({
    name: pt.name,
    value: summaryState.value.intensity ? summaryState.value.intensity[pt.id]?.[cockpit.stageKey] ?? 0 : 0,
    riskClass: pt.riskClass
  }))
  const barColor = (rc) => rc === 'high' ? p.alert : rc === 'mid' ? p.watch : p.stable
  return {
    grid: { left: 0, right: 0, top: 8, bottom: 20, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text }
    },
    xAxis: {
      type: 'value',
      max: 100,
      show: false,
      axisLine: { show: false },
      axisLabel: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'category',
      data: list.map((d) => d.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { show: false }
    },
    series: [
      {
        name: '强度底条',
        type: 'bar',
        data: list.map(() => 100),
        barWidth: 24,
        barCategoryGap: 8,
        barGap: '-100%',
        itemStyle: { color: p.line, borderRadius: 12 }
      },
      {
        name: '点位风险强度',
        type: 'bar',
        data: list.map((d) => ({
          value: d.value,
          itemStyle: {
            color: barColor(d.riskClass),
            borderRadius: 8
          }
        })),
        barWidth: 24,
        barCategoryGap: 8,
        label: {
          show: true,
          position: 'inside',
          overflow: 'truncate',
          formatter: (params) => `{name|${list[params.dataIndex].name}}{div| }{value|${params.value}}`,
          rich: {
            name: {
              color: '#fff',
              fontSize: 11,
              fontWeight: 600,
              flex: 1,
              align: 'left',
              textShadowBlur: 4,
              textShadowColor: 'rgba(0, 0, 0, 0.4)'
            },
            div: {
              color: 'rgba(255, 255, 255, 0.7)',
              fontSize: 11,
              borderLeftWidth: 1,
              borderLeftColor: 'rgba(255, 255, 255, 0.45)',
              borderLeftType: 'solid',
              height: 12,
              width: 1,
              lineHeight: 12,
              align: 'center',
              padding: [0, 0, 0, 10]
            },
            value: {
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              align: 'right',
              padding: [0, 10, 0, 0],
              textShadowBlur: 4,
              textShadowColor: 'rgba(0, 0, 0, 0.4)'
            }
          }
        }
      }
    ]
  }
})

const confidenceOption = computed(() => {
  const p = palette()
  void theme.value
  const stagesArr = stages.value.length ? stages.value : [{ key: 't1', label: '未来 1 天' }]
  return {
    grid: { left: 40, right: 16, top: 26, bottom: 20, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text }
    },
    legend: {
      data: ['机理层置信', 'AI 层置信', '综合共识'],
      textStyle: { color: p.textSoft, fontSize: 10 },
      top: 0,
      right: 4
    },
    xAxis: {
      type: 'category',
      data: stagesArr.map((s) => s.label),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.textSoft, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 10 },
      splitLine: { lineStyle: { color: p.line } },
      scale: true,
      min: (v) => Math.floor(v.min - 3),
      max: (v) => Math.ceil(v.max + 3)
    },
    series: [
      {
        name: '机理层置信',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, color: p.accent },
        itemStyle: { color: p.accent },
        data: [94, 90, 86, 82, 78]
      },
      {
        name: 'AI 层置信',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, color: p.ai },
        itemStyle: { color: p.ai },
        data: [78, 80, 82, 80, 76]
      },
      {
        name: '综合共识',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 3, color: p.alert },
        itemStyle: { color: p.alert },
        data: [86, 85, 84, 81, 77]
      }
    ]
  }
})

onMounted(async () => {
  const [s, h, p, r] = await Promise.all([
    getTimeStages(),
    getHeatField(),
    getPoints(),
    getRegionSummary()
  ])
  stages.value = s
  heatField.value = h
  pointsState.value = p
  summaryState.value = r
})
</script>
<style scoped>
.heatmap-shell { max-width: 1680px; }
.heatmap-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 10px 2px 22px;
  border-bottom: 1px solid var(--c-line);
}
.heatmap-header h1 { margin: 5px 0 0; font-size: clamp(24px, 3vw, 42px); }
.heatmap-subtitle { margin: 10px 0 0; color: var(--c-muted); }
.header-status { display: flex; align-items: center; gap: 12px; min-width: 275px; padding: 12px 14px; border: 1px solid var(--c-line); background: var(--glass-bg); }
.header-status > div { display: grid; gap: 3px; flex: 1; }
.header-status strong { font-size: 13px; }
.header-status small { color: var(--c-muted); font-size: 12px; }
.status-light { width: 8px; height: 8px; border-radius: 50%; background: var(--c-stable); box-shadow: 0 0 0 4px color-mix(in srgb, var(--c-stable) 16%, transparent); }
.cockpit-grid { display: grid; grid-template-columns: 238px minmax(560px, 1fr) 312px; gap: 14px; align-items: stretch; margin-top: 14px; }
.cockpit-rail { min-width: 0; padding: 18px 16px; overflow: hidden; }
.rail-heading { display: flex; justify-content: space-between; gap: 10px; padding-bottom: 14px; border-bottom: 1px solid var(--c-line); }
.rail-heading h2 { margin: 4px 0 0; font-size: 18px; }
.rail-index, .dock-index { color: var(--c-accent); font-family: var(--font-display); font-size: 11px; letter-spacing: .12em; }
.risk-score { display: grid; gap: 5px; padding: 18px 0; border-bottom: 1px solid var(--c-line); }
.score-label, .score-caption { color: var(--c-muted); font-size: 12px; }
.risk-score strong { color: var(--c-alert); font-family: var(--font-display); font-size: 26px; }
.metric-stack { padding: 8px 0; border-bottom: 1px solid var(--c-line); }
.metric-row { display: grid; grid-template-columns: 1fr auto 34px; align-items: center; gap: 6px; padding: 10px 0; }
.metric-row span { display: flex; align-items: center; gap: 7px; font-size: 12px; }
.metric-row i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.metric-row strong { font-family: var(--font-display); font-size: 18px; }
.metric-row small { color: var(--c-muted); text-align: right; font-size: 11px; }
.metric-high { color: var(--c-alert); }.metric-mid { color: var(--c-watch); }.metric-low { color: var(--c-stable); }
.rail-section { padding-top: 16px; }
.section-line { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.section-line h3 { margin: 0; font-size: 13px; }.section-line span { color: var(--c-muted); font-size: 11px; white-space: nowrap; }
.rail-summary { margin: 0; color: var(--c-text-soft); font-size: 12px; line-height: 1.75; }
.rail-note { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 9px; margin-top: 15px; padding: 12px 0 0; border-top: 1px dashed var(--c-line); }
.note-mark { display: grid; place-items: center; width: 27px; height: 27px; border: 1px solid var(--c-accent); color: var(--c-accent); font: 11px var(--font-display); }
.rail-note div { display: grid; gap: 3px; }.rail-note strong { font-size: 12px; }.rail-note small { color: var(--c-muted); font-size: 11px; }.rail-note b { color: var(--c-accent); font: 16px var(--font-display); }
.map-stage { min-width: 0; }.map-stage :deep(.map-panel) { min-height: 720px; height: 100%; }
.right-rail { padding-bottom: 10px; }.hotspot-section { padding-bottom: 4px; }
.factor-list { display: grid; gap: 8px; }
.factor-track { position: relative; height: 24px; border-radius: 12px; background: var(--c-line); overflow: hidden; }
.factor-fill { position: absolute; left: 0; top: 0; height: 100%; border-radius: 12px; background: linear-gradient(90deg, var(--c-watch), var(--c-alert)); }
.factor-fill.is-top { background: linear-gradient(90deg, var(--c-alert), #ffb3a6); box-shadow: 0 0 8px var(--c-alert-soft); }
.factor-tag { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); z-index: 2; font-size: 12px; font-weight: 600; color: #fff; text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35); }
.factor-value { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); z-index: 2; color: #fff; font: 12px var(--font-display); text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35); }
.chart-section { border-top: 1px dashed var(--c-line); }.chart-frame { height: 200px; }
.left-rail .confidence-section { padding-top: 14px; }
.left-rail .confidence-section .chart-frame { height: 168px; }
.timeline-dock { display: grid; grid-template-columns: 130px minmax(0, 1fr); align-items: center; gap: 16px; margin-top: 14px; padding: 12px 14px 12px 16px; border: 1px solid var(--c-line); background: var(--glass-bg); }.timeline-dock :deep(.time-axis-bar) { margin: 0; border: 0; padding: 0; }.dock-label { display: flex; align-items: center; gap: 10px; }.dock-label div { display: grid; gap: 3px; }.dock-label strong { font-size: 12px; }.dock-label small { color: var(--c-muted); font-size: 11px; }.heatmap-foot { justify-content: center; color: var(--c-muted); font-size: 11px; }

@media (max-width: 1180px) { .cockpit-grid { grid-template-columns: 210px minmax(450px, 1fr); }.right-rail { grid-column: 1 / -1; display: grid; grid-template-columns: 180px 1fr 1fr; gap: 18px; }.right-rail .rail-heading { grid-row: span 2; }.right-rail .rail-section { padding-top: 0; }.right-rail .hotspot-section { grid-column: 1; grid-row: span 2; }.right-rail .chart-section { grid-column: 2 / -1; border-top: 0; border-left: 1px dashed var(--c-line); padding-left: 18px; } }
@media (max-width: 760px) { .heatmap-header { display: grid; align-items: start; }.header-status { min-width: 0; }.cockpit-grid { display: flex; flex-direction: column; }.map-stage { order: -1; }.map-stage :deep(.map-panel) { min-height: 560px; }.left-rail, .right-rail { display: block; }.right-rail .rail-heading, .right-rail .rail-section { padding-top: 16px; }.right-rail .chart-section { border-top: 1px dashed var(--c-line); border-left: 0; padding-left: 0; }.timeline-dock { grid-template-columns: 1fr; }.timeline-dock :deep(.time-axis-bar) { grid-column: 1; grid-row: 2; }.dock-label { grid-column: 1; } }
@media (max-width: 640px) {
  .heatmap-header { gap: 14px; padding-bottom: 16px; }
  .header-status { padding: 10px 12px; }
  .heatmap-subtitle { font-size: 12px; }
  .map-stage :deep(.map-panel) { min-height: 420px; }
  .timeline-dock { padding: 10px 12px; }
}

</style>
