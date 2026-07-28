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
        <div class="kpi-value">{{ (selectedPoint.short || dash) }}</div>
        <div class="kpi-trend down">{{ (selectedPoint.risk || dash) }}</div>
      </article>
    </section>

    <div class="dashboard-layout cockpit-stage">
      <LakeMap
        :model-value="store.selectedPoint"
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
            <h2>{{ (selectedPoint.name || dash) }}</h2>
          </div>
          <span class="risk-badge" :class="(selectedPoint.riskClass || '')">{{ (selectedPoint.risk || dash) }}</span>
        </header>

        <p class="detail-summary">{{ (selectedPoint.summary || dash) }}</p>

        <div class="metrics-grid">
          <article><span>藻细胞密度</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.density) || dash) }}</strong></article>
          <article><span>叶绿素 a</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.chla) || dash) }}</strong></article>
          <article><span>总磷</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.phosphorus) || dash) }}</strong></article>
          <article><span>水温</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.temp) || dash) }}</strong></article>
        </div>

        <section class="detail-section">
          <div class="section-line">
            <h3>{{ ((selectedPoint.forecast && selectedPoint.forecast.window && selectedPoint.forecast.window[stageIndex]) || dash) }} 预测</h3>
            <span>{{ stageLabel }}</span>
          </div>
          <div class="forecast-card">
            <strong>{{ ((selectedPoint.forecast && selectedPoint.forecast.title && selectedPoint.forecast.title[stageIndex]) || dash) }}</strong>
            <p>{{ ((selectedPoint.forecast && selectedPoint.forecast.text && selectedPoint.forecast.text[stageIndex]) || dash) }}</p>
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
            <h3>AI 分析</h3>
            <div class="tab-switch" v-if="prediction || aiLoading">
              <button type="button" :class="{ active: aiTab === 'predict' }" @click="aiTab = 'predict'">模型对比</button>
              <button type="button" :class="{ active: aiTab === 'explain' }" @click="aiTab = 'explain'">SHAP 解释</button>
            </div>
            <span v-else>{{ aiError || '切换点位自动加载' }}</span>
          </div>

          <div v-if="aiLoading" class="ai-placeholder">正在调用 /api/predict 加载模型输出…</div>
          <div v-else-if="aiError" class="ai-placeholder error">AI 加载失败：{{ aiError }}</div>
          <div v-else-if="!prediction" class="ai-placeholder">当前点位无后端 ID，暂不支持 AI 分析</div>

          <div v-else-if="aiTab === 'predict'" class="ai-panel">
            <div class="model-bars">
              <div v-for="m in modelBars" :key="m.key" class="model-bar">
                <div class="model-meta"><span>{{ m.label }}</span><strong>{{ m.value }}</strong></div>
                <div class="factor-track"><div class="factor-fill" :style="{ width: m.pct + '%' }"></div></div>
              </div>
            </div>
            <div class="model-meta-row">
              <span>融合提升：<strong>{{ prediction.model_comparison.improvement }}</strong></span>
              <span>R²：<strong>{{ prediction.evaluation.r2 }}</strong></span>
              <span>RMSE：<strong>{{ prediction.evaluation.rmse }}</strong></span>
              <span>MAE：<strong>{{ prediction.evaluation.mae }}</strong></span>
            </div>
            <div class="predict-results">
              <div v-for="r in prediction.results" :key="r.date" class="predict-day">
                <header><strong>{{ r.date }}</strong><span class="risk-badge" :class="r.risk_level === 'high' ? 'high' : r.risk_level === 'medium' ? 'mid' : 'low'">{{ r.risk_level }}</span></header>
                <ul>
                  <li v-for="m in r.metrics" :key="m.metric_code"><span>{{ m.metric_name }}</span><strong>{{ m.value }} {{ m.unit }}</strong></li>
                </ul>
              </div>
            </div>
          </div>

          <div v-else-if="aiTab === 'explain'" class="ai-panel">
            <div v-if="explanation" class="explain-intro">
              <p>{{ explanation.interpretation }}</p>
              <div class="explain-ci">
                <span>95% 置信区间：<strong>{{ explanation.confidence_interval.lower }} ~ {{ explanation.confidence_interval.upper }}</strong></span>
              </div>
            </div>
            <div class="factor-list">
              <div v-for="f in (explanation ? explanation.feature_importance : [])" :key="f.name" class="factor-row">
                <div class="factor-meta">
                  <span>{{ f.name }} · {{ f.impact === 'positive' ? '正向' : '负向' }}</span>
                  <strong>{{ f.contribution }}%</strong>
                </div>
                <div class="factor-track"><div class="factor-fill" :class="f.impact" :style="{ width: Math.min(100, Math.abs(f.contribution)) + '%' }"></div></div>
              </div>
            </div>
            <div v-if="explanation && explanation.sensitivity_curve.length" class="sensitivity">
              <header><h4>敏感度曲线</h4></header>
              <EChart :option="sensitivityOption" />
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-line">
            <h3>点位事件流</h3>
            <span>近期研判</span>
          </div>
          <div class="timeline-list">
            <div v-if="selectedPoint.timeline" v-for="[time, title, text] in selectedPoint.timeline" :key="`${time}-${title}`" class="timeline-item">
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
    <footer class="cockpit-foot">
      <RouterLink class="button secondary" to="/cockpit">← 返回驾驶舱</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCockpitStore, cockpitState } from '../stores/cockpit.js'
import { getPoints, getRegionSummary, getTimeStages, getPrediction, getExplanation } from '../services/api.js'
import { pointPositions } from '../data/points.js'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import EChart from '../components/cockpit/EChart.vue'

const cockpit = useCockpitStore()
const store = cockpitState()
const dash = '—'
const stages = ref([])
const pointsState = ref({ pointData: {}, pointPositions: {} })
const summary = ref({ totalStations: 6, riskCounts: { high: 0, mid: 0, low: 0 } })
const prediction = ref(null)
const explanation = ref(null)
const aiLoading = ref(false)
const aiError = ref('')
const aiTab = ref('predict')

const pointList = computed(() => Object.values(pointsState.value.pointData))
const positions = computed(() => pointsState.value.pointPositions || pointPositions)
const selectedPoint = computed(() => pointsState.value.pointData[store.selectedPoint] || pointList.value[0] || {})
const stageIndex = computed(() => stages.value.findIndex((s) => s.key === cockpit.stageKey))
const stageLabel = computed(() => {
  const item = stages.value.find((s) => s.key === cockpit.stageKey)
  return item ? item.label : ''
})

function setPoint(id) {
  store.selectedPoint = id
  refreshAiForSelected()
}

const trendOption = computed(() => {
  const trend = (selectedPoint.value && selectedPoint.value.trend) || []
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


// 链式调用：选中站点 -> predict -> explain
async function loadAi(stationId) {
  if (!stationId) return
  aiLoading.value = true
  aiError.value = ''
  try {
    const pred = await getPrediction(stationId)
    prediction.value = pred
    const fakePid = 'PRED-' + (pred.station_id || stationId) + '-' + Date.now()
    const exp = await getExplanation(fakePid)
    explanation.value = exp
  } catch (err) {
    aiError.value = err && err.message ? err.message : 'AI 调用失败'
    prediction.value = null
    explanation.value = null
  } finally {
    aiLoading.value = false
  }
}

let _aiToken = 0
async function refreshAiForSelected() {
  const id = store.selectedPoint
  const station = pointsState.value.pointData[id]
  if (!station || !station._backendId) {
    prediction.value = null
    explanation.value = null
    return
  }
  const token = ++_aiToken
  await loadAi(station._backendId)
  if (token !== _aiToken) return
}

const modelBars = computed(() => {
  if (!prediction.value || !prediction.value.model_comparison) return []
  const mc = prediction.value.model_comparison
  const arr = [
    { key: 'm', label: '机理模型', value: mc.mechanism_model },
    { key: 'a1', label: 'AI 模型 1', value: mc.ai_model_1 },
    { key: 'a2', label: 'AI 模型 2', value: mc.ai_model_2 },
    { key: 'f', label: '融合模型', value: mc.fusion_model }
  ]
  const max = Math.max(...arr.map(a => a.value), 50)
  return arr.map(a => ({ ...a, pct: Math.min(100, Math.round((a.value / max) * 100)) }))
})

const sensitivityOption = computed(() => {
  const sc = (explanation.value && explanation.value.sensitivity_curve) || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: sc.map(s => s.factor), textStyle: { color: '#a9bcd4' }, top: 0 },
    grid: { left: 40, right: 20, top: 28, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: (sc[0] && sc[0].values) || [], axisLine: { lineStyle: { color: 'rgba(120,200,220,0.18)' } }, axisLabel: { color: '#6f8aa3' } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: '#6f8aa3' }, splitLine: { lineStyle: { color: 'rgba(120,200,220,0.08)' } } },
    series: sc.map((s, i) => ({
      name: s.factor, type: 'line', smooth: true,
      lineStyle: { width: 2, color: ['#22d3c5', '#a78bfa', '#ff7b6b'][i % 3] },
      itemStyle: { color: ['#22d3c5', '#a78bfa', '#ff7b6b'][i % 3] },
      data: s.response
    }))
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
  refreshAiForSelected()
})
</script>