<template>
  <main class="shell">
    <section class="panel" style="padding: 26px 28px;">
      <p class="eyebrow">COCKPIT · RISK HEATMAP</p>
      <h1>{{ stageTitle }}</h1>
      <p style="max-width: 880px; margin-top: 14px;">
        基于机理 + AI 融合模型输出的藻华风险空间分布。当前档位聚焦 {{ stageLabel }}，可通过顶部播放器切换时间尺度，观察风险高值区随时间的扩散与收敛。
      </p>
    </section>

    <TimeAxisBar :stages="stages" />
    <CockpitSubTabs />

    <section class="kpi-grid">
      <article>
        <div class="kpi-label">高风险网格</div>
        <div class="kpi-value" style="color: var(--coral);">{{ summary.highCells }}</div>
        <div class="kpi-trend up">占比 {{ summary.highShare }}%</div>
      </article>
      <article>
        <div class="kpi-label">关注网格</div>
        <div class="kpi-value" style="color: var(--amber);">{{ summary.midCells }}</div>
        <div class="kpi-trend flat">占比 {{ summary.midShare }}%</div>
      </article>
      <article>
        <div class="kpi-label">稳定网格</div>
        <div class="kpi-value" style="color: var(--green);">{{ summary.lowCells }}</div>
        <div class="kpi-trend down">占比 {{ summary.lowShare }}%</div>
      </article>
      <article>
        <div class="kpi-label">预测置信度</div>
        <div class="kpi-value">{{ summary.confidence }}%</div>
        <div class="kpi-trend flat">机理与 AI 共识度</div>
      </article>
    </section>

    <div class="dashboard-layout cockpit-stage dashboard-stacked">
      <LakeMap
        :model-value="cockpit.selectedPoint"
        :point-list="mapPointList"
        :positions="{}"
        :heat-field="heatField"
        :heat-stage-key="cockpit.stageKey"
        :stage-label="stageLabel"
        title="太湖风险热力分区"
        active-tab="heatmap"
        @update:model-value="setPoint"
      />

      <aside class="panel detail-panel">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">RISK SUMMARY</p>
            <h2>{{ stageTitle }}</h2>
          </div>
          <span class="risk-badge" :class="stageRiskClass">{{ stageRiskLabel }}</span>
        </header>

        <p class="detail-summary">{{ stageSummary }}</p>

        <section class="detail-section" style="margin-top: 8px;">
          <div class="section-line">
            <h3>热点分布前五</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="factor-list">
            <div v-for="cell in topCells" :key="cell.label" class="factor-row">
              <div class="factor-meta">
                <span>{{ cell.label }}</span>
                <strong style="color: var(--coral);">{{ cell.value }}</strong>
              </div>
              <div class="factor-track">
                <div class="factor-fill" :style="{ width: cell.value + '%' }"></div>
              </div>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>各点位风险强度</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="chart-card">
            <EChart :option="barOption" />
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>机理 + AI 置信曲线</h3>
            <span>跨档位对比</span>
          </div>
          <div class="chart-card">
            <EChart :option="confidenceOption" />
          </div>
        </section>

      </aside>
    </div>
    <footer class="cockpit-foot">
      <RouterLink class="button secondary" to="/cockpit">← 返回驾驶舱</RouterLink>
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
import CockpitSubTabs from '../components/cockpit/CockpitSubTabs.vue'
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
  return flat.slice(0, 5).map((cell, i) => ({
    label: `地图热点区 #${i + 1}`,
    value: cell.value
  }))
})

const barOption = computed(() => {
  const p = palette()
  void theme.value
  const list = pointList.value.map((pt) => ({
    name: pt.short + ' ' + pt.name,
    value: summaryState.value.intensity ? summaryState.value.intensity[pt.id]?.[cockpit.stageKey] ?? 0 : 0,
    riskClass: pt.riskClass
  }))
  const barColor = (rc) => rc === 'high' ? p.alert : rc === 'mid' ? p.watch : p.stable
  return {
    grid: { left: 110, right: 24, top: 16, bottom: 28, containLabel: true },
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
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line } }
    },
    yAxis: {
      type: 'category',
      data: list.map((d) => d.name),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.textSoft, fontSize: 11 }
    },
    series: [{
      type: 'bar',
      data: list.map((d) => ({
        value: d.value,
        itemStyle: {
          color: barColor(d.riskClass),
          borderRadius: [0, 6, 6, 0]
        }
      })),
      barWidth: 14,
      label: {
        show: true,
        position: 'right',
        color: p.textSoft,
        fontSize: 11,
        formatter: '{c}'
      }
    }]
  }
})

const confidenceOption = computed(() => {
  const p = palette()
  void theme.value
  const stagesArr = stages.value.length ? stages.value : [{ key: 't1', label: '未来 1 天' }]
  return {
    grid: { left: 48, right: 24, top: 24, bottom: 28, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text }
    },
    legend: {
      data: ['机理层置信', 'AI 层置信', '综合共识'],
      textStyle: { color: p.textSoft, fontSize: 11 },
      top: 0,
      right: 8
    },
    xAxis: {
      type: 'category',
      data: stagesArr.map((s) => s.label),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.textSoft, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      min: 50,
      max: 100,
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line } }
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
/* Heatmap 页面：热力图与风险详情改为单列堆叠 */
.dashboard-stacked {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 22px;
  margin-top: 22px;
}
.dashboard-stacked > .panel,
.dashboard-stacked > aside {
  width: 100%;
}

/* 热力图高度；保持正方形之外适配宽屏 */
.heatmap-stage {
  min-height: 560px;
}
@media (min-width: 1280px) {
  .heatmap-stage { min-height: 640px; }
}

/* 详情面板内部节奏 */
.detail-panel {
  padding: 24px 26px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.detail-panel .panel-head {
  margin: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--panel-line);
}
.detail-panel .detail-summary {
  margin: 0;
  line-height: 1.7;
}

.detail-panel .section-line {
  margin-bottom: 10px;
}
.detail-panel .section-line h3 {
  margin: 0;
  font-size: 14px;
}
.detail-panel .detail-section {
  margin: 0;
  padding-top: 16px;
  border-top: 1px dashed var(--panel-line);
}

/* 顶部五热点：每行更舒展 */
.detail-panel .factor-row {
  padding: 8px 0;
}

</style>
