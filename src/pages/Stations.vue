<template>
  <main class="shell">
    <section class="panel" style="padding: 26px 28px;">
      <p class="eyebrow">COCKPIT · STATIONS</p>
      <h1>监测站点档位研判</h1>
      <p style="max-width: 880px; margin-top: 14px;">
        点击地图点位可联动右侧详情、当前档位预测与可解释因子分析。底部时间轴播放器同步驱动三页系统。
      </p>
    </section>

    <TimeAxisBar :stages="stages" />

    <section class="kpi-grid">
      <article>
        <div class="kpi-label">监测点位</div>
        <div class="kpi-value">{{ summary.totalStations }} 个</div>
        <div class="kpi-trend flat">覆盖湖体四向 + 上下游</div>
      </article>
      <article>
        <div class="kpi-label">高风险</div>
        <div class="kpi-value" style="color: var(--coral);">{{ summary.riskCounts.high }} 个</div>
        <div class="kpi-trend up">当前档位风险较高</div>
      </article>
      <article>
        <div class="kpi-label">关注档位</div>
        <div class="kpi-value">{{ stageLabel }}</div>
        <div class="kpi-trend flat">可逐档切换对比</div>
      </article>
      <article>
        <div class="kpi-label">选中点位</div>
        <div class="kpi-value">{{ selectedPoint.short }}</div>
        <div class="kpi-trend down">{{ selectedPoint.risk }}</div>
      </article>
    </section>

    <div class="dashboard-layout cockpit-stage">
      <LakeMap
        :model-value="cockpit.selectedPoint"
        :point-list="pointList"
        :positions="positions"
        :stage-label="stageLabel"
        title="湖区监测点位全景"
        active-tab="stations"
        @update:model-value="setPoint"
      />

      <aside class="panel detail-panel">
        <header class="panel-head detail-head">
          <div>
            <p class="panel-kicker">POINT DETAIL</p>
            <h2>{{ selectedPoint.name }}</h2>
          </div>
          <span class="risk-badge" :class="selectedPoint.riskClass">{{ selectedPoint.risk }}</span>
        </header>

        <p class="detail-summary">{{ selectedPoint.summary }}</p>

        <div class="metrics-grid">
          <article><span>藻细胞密度</span><strong>{{ selectedPoint.metrics.density }}</strong></article>
          <article><span>叶绿素 a</span><strong>{{ selectedPoint.metrics.chla }}</strong></article>
          <article><span>总磷</span><strong>{{ selectedPoint.metrics.phosphorus }}</strong></article>
          <article><span>水温</span><strong>{{ selectedPoint.metrics.temp }}</strong></article>
        </div>

        <section class="detail-section">
          <div class="section-line">
            <h3>{{ selectedPoint.forecast.window[stageIndex] }} 预测</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="forecast-card">
            <strong>{{ selectedPoint.forecast.title[stageIndex] }}</strong>
            <p>{{ selectedPoint.forecast.text[stageIndex] }}</p>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>藻密度时序</h3>
            <span>{{ stageLabel }} 视角</span>
          </div>
          <div class="chart-card">
            <EChart :option="trendOption" />
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>驱动因子贡献</h3>
            <span>可解释性分析</span>
          </div>
          <div class="factor-list">
            <div v-for="f in selectedPoint.factors" :key="f.name" class="factor-row">
              <div class="factor-meta">
                <span>{{ f.name }}</span>
                <strong>{{ f.value }}%</strong>
              </div>
              <div class="factor-track"><div class="factor-fill" :style="{ width: `${f.value}%` }"></div></div>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>点位事件流</h3>
            <span>近期研判</span>
          </div>
          <div class="timeline-list">
            <div v-for="[time, title, text] in selectedPoint.timeline" :key="`${time}-${title}`" class="timeline-item">
              <div class="timeline-time">{{ time }}</div>
              <div>
                <strong>{{ title }}</strong>
                <p>{{ text }}</p>
              </div>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>湖区实景</h3>
            <span>现场照片位</span>
          </div>
          <div class="image-slot" data-label="点位实景图 · 待替换为 <img>"></div>
        </section>
      </aside>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCockpitStore } from '../stores/cockpit.js'
import { getPoints, getRegionSummary, getTimeStages } from '../services/api.js'
import { pointPositions } from '../data/points.js'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import EChart from '../components/cockpit/EChart.vue'

const cockpit = useCockpitStore()
const stages = ref([])
const pointsState = ref({ pointData: {}, pointPositions: {} })
const summary = ref({ totalStations: 6, riskCounts: { high: 0, mid: 0, low: 0 } })

const pointList = computed(() => Object.values(pointsState.value.pointData))
const positions = computed(() => pointsState.value.pointPositions || pointPositions)
const selectedPoint = computed(() => pointsState.value.pointData[cockpit.selectedPoint] || pointList.value[0])
const stageIndex = computed(() => stages.value.findIndex((s) => s.key === cockpit.stageKey))
const stageLabel = computed(() => {
  const item = stages.value.find((s) => s.key === cockpit.stageKey)
  return item ? item.label : ''
})

function setPoint(id) {
  cockpit.selectedPoint = id
}

const trendOption = computed(() => {
  const trend = selectedPoint.value.trend || []
  const stageKey = cockpit.stageKey
  const yMax = Math.max(100, ...trend) + 8
  return {
    grid: { left: 36, right: 16, top: 16, bottom: 28, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(8,16,28,0.92)',
      borderColor: 'rgba(34,211,197,0.4)',
      textStyle: { color: '#e6f1ff' }
    },
    xAxis: {
      type: 'category',
      data: trend.map((_, i) => `T-${trend.length - i}d`),
      axisLine: { lineStyle: { color: 'rgba(120,200,220,0.18)' } },
      axisLabel: { color: '#6f8aa3', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      max: yMax,
      axisLine: { show: false },
      axisLabel: { color: '#6f8aa3', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(120,200,220,0.08)' } }
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 3, color: '#22d3c5' },
        itemStyle: { color: '#22d3c5' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(34,211,197,0.45)' },
              { offset: 1, color: 'rgba(34,211,197,0)' }
            ]
          }
        },
        data: trend,
        markArea: {
          itemStyle: { color: 'rgba(244,192,98,0.10)' },
          data: [[
            { yAxis: 60 },
            { yAxis: yMax }
          ]]
        },
        markLine: {
          symbol: 'none',
          lineStyle: { color: '#ff7b6b', type: 'dashed' },
          data: [{ yAxis: 75, label: { color: '#ff7b6b', formatter: '预警阈值' } }]
        }
      }
    ]
  }
})

onMounted(async () => {
  const [s, p, r] = await Promise.all([
    getTimeStages(),
    getPoints(),
    getRegionSummary()
  ])
  stages.value = s
  pointsState.value = p
  summary.value = r
})
</script>