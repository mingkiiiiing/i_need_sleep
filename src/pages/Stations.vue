<template>
  <main class="shell">
    <section class="panel stations-intro">
      <p class="eyebrow">COCKPIT · STATIONS</p>
      <h1>监测站点档位研判</h1>
      <p>
        点击地图点位可联动右侧详情、当前档位预测与可解释因子分析。
      </p>
    </section>

    <div class="dashboard-layout cockpit-stage dashboard-stacked">
      <div class="map-with-kpi">
        <LakeMap
          :model-value="store.selectedPoint"
          :point-list="pointList"
          :positions="positions"
          :stage-label="stageLabel"
          title="湖区监测点位全景"
          @update:model-value="setPoint"
        />

        <section class="kpi-grid kpi-side">
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

          <div class="side-card point-risk-card">
            <header>
              <h4>选中点位风险</h4>
              <span class="risk-badge" :class="(selectedPoint.riskClass || '')">{{ (selectedPoint.risk || dash) }}</span>
            </header>
            <div class="point-metrics">
              <div><span>点位名称</span><strong>{{ (selectedPoint.name || dash) }}</strong></div>
              <div><span>藻细胞密度</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.density) || dash) }}</strong></div>
              <div><span>叶绿素 a</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.chla) || dash) }}</strong></div>
              <div><span>总磷</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.phosphorus) || dash) }}</strong></div>
              <div><span>水温</span><strong>{{ ((selectedPoint.metrics && selectedPoint.metrics.temp) || dash) }}</strong></div>
            </div>
            <p class="point-summary">{{ (selectedPoint.summary || dash) }}</p>
          </div>

          <div class="side-card threshold-card">
            <header>
              <h4>预警阈值状态</h4>
              <span class="threshold-count">{{ thresholdStats.alert }}/{{ thresholdRows.length }} 超阈</span>
            </header>
            <ul class="threshold-list">
              <li v-for="row in thresholdRows" :key="row.label">
                <i class="threshold-light" :class="row.level"></i>
                <div class="threshold-meta">
                  <span>{{ row.label }}</span>
                  <small>{{ row.limit }}</small>
                </div>
                <strong>{{ row.value }}</strong>
              </li>
            </ul>
          </div>
        </section>
      </div>

      <TimeAxisBar :stages="stages" variant="axis" />

      <aside class="panel detail-panel">
        <header class="panel-head detail-head">
          <div>
            <p class="panel-kicker">POINT DETAIL</p>
            <h2>{{ (selectedPoint.name || dash) }}</h2>
          </div>
        </header>

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

          <div v-if="aiLoading" class="ai-placeholder ai-loading"><span class="ai-spinner" aria-hidden="true"></span><span>正在调用 /api/predict 加载模型输出…</span></div>
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
                <header><strong>{{ r.date }}</strong><span class="risk-badge" :class="riskClassFromLevel(r.risk_level)">{{ r.risk_level }}</span></header>
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

            <div v-if="shapItems.length" class="factor-summary">
              <div class="factor-summary-stat positive">
                <span class="num">{{ shapStats.positive }}</span>
                <span class="lbl">正向影响因子</span>
              </div>
              <div class="factor-summary-stat negative">
                <span class="num">{{ shapStats.negative }}</span>
                <span class="lbl">负向影响因子</span>
              </div>
              <div class="factor-summary-stat total">
                <span class="num">{{ shapStats.total }}%</span>
                <span class="lbl">解释方差占比</span>
              </div>
            </div>

            <div class="factor-list">
              <div v-for="(f, idx) in shapItems" :key="f.name" class="factor-row" :class="f.impact">
                <div class="factor-rank">{{ idx + 1 }}</div>
                <div class="factor-main">
                  <div class="factor-head">
                    <span class="factor-name">{{ f.name }}</span>
                    <span class="factor-impact" :class="f.impact">
                      <span class="impact-dot"></span>
                      {{ f.impact === 'positive' ? '正向推动' : '负向抑制' }}
                    </span>
                  </div>
                  <div class="factor-track" :aria-label="f.contribution + '%'">
                    <div class="factor-fill" :class="f.impact" :style="{ width: f.barPct + '%' }"></div>
                  </div>
                  <div class="factor-foot">
                    <span class="factor-pct">{{ f.contribution }}%</span>
                    <span class="factor-mute">排名 #{{ idx + 1 }} / {{ shapItems.length }}</span>
                  </div>
                </div>
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
      </aside>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCockpitStore, cockpitState } from '../stores/cockpit.js'
import { getPoints, getRegionSummary, getTimeStages, getPrediction, getExplanation } from '../services/api.js'
import { pointPositions } from '../data/points.js'
import { SEVERITY_TO_CLASS } from '../services/_mapping.js'
import { palette } from '../components/cockpit/echartsTheme.js'
import { useTheme } from '../composables/useTheme.js'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import EChart from '../components/cockpit/EChart.vue'

const cockpit = useCockpitStore()
const store = cockpitState()
const { theme } = useTheme()
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

const riskClassFromLevel = (level) => SEVERITY_TO_CLASS[level] || 'low'

// 预警阈值状态：叶绿素 a / 总磷 / 水温，超阈亮红灯
const thresholdRows = computed(() => {
  const m = (selectedPoint.value && selectedPoint.value.metrics) || {}
  const chla = parseFloat(m.chla) || 0
  const tp = parseFloat(m.phosphorus) || 0
  const temp = parseFloat(m.temp) || 0
  return [
    {
      label: '叶绿素 a',
      value: m.chla || dash,
      limit: '阈值 40 ug/L',
      level: chla >= 40 ? 'high' : chla >= 25 ? 'mid' : 'low'
    },
    {
      label: '总磷',
      value: m.phosphorus || dash,
      limit: '阈值 0.10 mg/L',
      level: tp >= 0.1 ? 'high' : tp >= 0.05 ? 'mid' : 'low'
    },
    {
      label: '水温',
      value: m.temp || dash,
      limit: '阈值 30 ℃',
      level: temp >= 30 ? 'high' : temp >= 28 ? 'mid' : 'low'
    }
  ]
})

const thresholdStats = computed(() => ({
  alert: thresholdRows.value.filter((r) => r.level === 'high').length
}))

function setPoint(id) {
  store.selectedPoint = id
  prediction.value = null
  explanation.value = null
  aiError.value = ''
  aiLoading.value = true
  aiTab.value = 'predict'
  refreshAiForSelected()
}

const trendOption = computed(() => {
  const p = palette()
  void theme.value
  const trend = (selectedPoint.value && selectedPoint.value.trend) || []
  const stageKey = cockpit.stageKey
  const yMax = Math.max(100, ...trend) + 8
  return {
    grid: { left: 36, right: 16, top: 16, bottom: 28, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text }
    },
    xAxis: {
      type: 'category',
      data: trend.map((_, i) => `T-${trend.length - i}d`),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.muted, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      max: yMax,
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line } }
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 3, color: p.accent },
        itemStyle: { color: p.accent },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: p.accent + '73' },
              { offset: 1, color: p.accent + '00' }
            ]
          }
        },
        data: trend,
        markArea: {
          itemStyle: { color: p.watch + '1a' },
          data: [[
            { yAxis: 60 },
            { yAxis: yMax }
          ]]
        },
        markLine: {
          symbol: 'none',
          lineStyle: { color: p.alert, type: 'dashed' },
          data: [{ yAxis: 75, label: { color: p.alert, formatter: '预警阈值' } }]
        }
      }
    ]
  }
})


// 链式调用：选中站点 -> predict -> explain
async function loadAi(stationId, token) {
  if (!stationId) return
  aiLoading.value = true
  aiError.value = ''
  try {
    const pred = await getPrediction(stationId)
    if (token !== _aiToken) return
    prediction.value = pred
    const fakePid = 'PRED-' + (pred.station_id || stationId) + '-' + Date.now()
    const exp = await getExplanation(fakePid)
    if (token !== _aiToken) return
    explanation.value = exp
  } catch (err) {
    if (token !== _aiToken) return
    aiError.value = err && err.message ? err.message : 'AI 调用失败'
    prediction.value = null
    explanation.value = null
  } finally {
    if (token === _aiToken) aiLoading.value = false
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
  await loadAi(station._backendId, token)
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

const shapItems = computed(() => {
  const items = (explanation.value && explanation.value.feature_importance) || []
  // 按贡献绝对值排序，取前 6
  const sorted = items.slice()
    .map((f) => ({ ...f, contribution: Number(f.contribution) || 0 }))
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 6)
  const maxAbs = sorted.reduce((m, f) => Math.max(m, Math.abs(f.contribution)), 0) || 1
  return sorted.map((f) => ({
    name: f.name,
    impact: f.impact,
    contribution: f.contribution,
    barPct: Math.round((Math.abs(f.contribution) / maxAbs) * 100),
  }))
})

const shapStats = computed(() => {
  const items = shapItems.value
  const positive = items.filter((f) => f.impact === 'positive').length
  const negative = items.filter((f) => f.impact === 'negative').length
  const total = items.reduce((s, f) => s + Math.abs(f.contribution), 0)
  return { positive, negative, total: Math.round(total) }
})

const sensitivityOption = computed(() => {
  const p = palette()
  void theme.value
  const sc = (explanation.value && explanation.value.sensitivity_curve) || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: sc.map(s => s.factor), textStyle: { color: p.textSoft }, top: 0 },
    grid: { left: 40, right: 20, top: 28, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: (sc[0] && sc[0].values) || [], axisLine: { lineStyle: { color: p.lineStrong } }, axisLabel: { color: p.muted } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: p.muted }, splitLine: { lineStyle: { color: p.line } } },
    series: sc.map((s, i) => ({
      name: s.factor, type: 'line', smooth: true,
      lineStyle: { width: 2, color: [p.accent, p.ai, p.alert][i % 3] },
      itemStyle: { color: [p.accent, p.ai, p.alert][i % 3] },
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


<style scoped>
/* Stations 页面：桌面端采用单屏三域工作台，减少页面级纵向滚动 */
.stations-intro {
  padding: 16px 22px;
  display: grid;
  grid-template-columns: auto minmax(0, auto) minmax(0, 1fr);
  align-items: center;
  gap: 16px;
}
:global(.shell:has(.stations-intro)) {
  width: 100%;
  max-width: none;
  min-height: 0;
  height: calc(100vh - 60px);
  padding-left: 16px;
  padding-right: 16px;
  padding-bottom: 18px;
  overflow: hidden;
}
.stations-intro .eyebrow { margin: 0; }
.stations-intro h1 { margin: 0; font-size: clamp(22px, 2vw, 30px); }
.stations-intro > p:last-child { margin: 0; max-width: none; color: var(--c-text-soft); }

.dashboard-stacked {
  display: grid;
  grid-template-columns: minmax(190px, 0.7fr) minmax(0, 2fr) minmax(340px, 0.95fr);
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 14px;
  margin-top: 14px;
  min-height: 0;
  overflow: hidden;
  align-items: stretch;
}
.dashboard-stacked > aside { grid-column: 3; grid-row: 1; min-width: 0; min-height: 0; }
.dashboard-stacked > .time-axis {
  grid-column: 1 / -1;
  grid-row: 2;
  min-height: 92px;
  margin: 0;
}

/* 将地图和左侧指标提升为工作台的两个独立区域 */
.map-with-kpi {
  display: contents;
}
.kpi-side {
  grid-column: 1;
  grid-row: 1;
  grid-template-columns: minmax(0, 1fr);
  align-content: start;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;
}
.map-with-kpi > .map-panel {
  grid-column: 2;
  grid-row: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.map-with-kpi > .map-panel,
.map-with-kpi > .map-panel :deep(.leaflet-map-container) {
  min-height: 0 !important;
}
.map-with-kpi > .map-panel :deep(.leaflet-map-container) {
  height: auto;
  flex: 1 1 auto;
}

/* 右侧栏附加卡片 */
.side-card {
  border: 1px solid var(--c-line);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  background: var(--c-surface-soft);
}
.side-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.side-card h4 { margin: 0; font-size: 13px; }

.point-risk-card .point-metrics { display: grid; gap: 6px; }
.point-risk-card .point-metrics div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.point-risk-card .point-metrics span { color: var(--c-muted); }
.point-risk-card .point-summary {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--c-text-soft);
  border-top: 1px dashed var(--c-line);
  padding-top: 10px;
}

.threshold-card .threshold-count { font-size: 12px; color: var(--c-muted); }
.threshold-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.threshold-list li {
  display: flex;
  align-items: center;
  gap: 10px;
}
.threshold-light {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.threshold-light.low { background: var(--c-stable); box-shadow: 0 0 6px var(--c-stable); }
.threshold-light.mid { background: var(--c-watch); box-shadow: 0 0 6px var(--c-watch); }
.threshold-light.high { background: var(--c-alert); box-shadow: 0 0 8px var(--c-alert); animation: threshold-blink 1.2s ease-in-out infinite; }
@keyframes threshold-blink { 50% { opacity: 0.45; } }
.threshold-meta { display: grid; gap: 2px; min-width: 0; }
.threshold-meta span { font-size: 12px; font-weight: 600; }
.threshold-meta small { font-size: 11px; color: var(--c-muted); }
.threshold-list strong {
  margin-left: auto;
  font-size: 12px;
  white-space: nowrap;
}
@media (max-width: 1024px) {
  :global(.shell:has(.stations-intro)) { height: auto; min-height: 100vh; overflow: visible; }
  .dashboard-stacked { grid-template-columns: 210px minmax(0, 1fr); grid-template-rows: auto auto; }
  .dashboard-stacked > aside { grid-column: 1 / -1; grid-row: 3; max-height: none; overflow: visible; }
  .dashboard-stacked > .time-axis { grid-column: 1 / -1; grid-row: 2; }
  .map-with-kpi > .map-panel { grid-column: 2; }
  .kpi-side { grid-template-columns: repeat(4, minmax(0, 1fr)); max-height: none; overflow: visible; }
  .kpi-side { grid-column: 1; }
}
@media (max-width: 560px) {
  .stations-intro { grid-template-columns: 1fr; gap: 4px; padding: 16px 18px; }
  .stations-intro h1 { font-size: 24px; }
  .dashboard-stacked { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto; }
  .dashboard-stacked > aside { grid-column: 1; grid-row: auto; }
  .dashboard-stacked > .time-axis { grid-column: 1; grid-row: auto; }
  .map-with-kpi > .map-panel { grid-column: 1; grid-row: 1; }
  .kpi-side { grid-column: 1; grid-row: 2; }
  .kpi-side { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi-side .side-card { grid-column: 1 / -1; }
  .threshold-list li { flex-wrap: wrap; }
}

/* 详情面板内部：分区更有节奏 */
.detail-panel {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  max-height: 100%;
}
.detail-panel .detail-head {
  margin: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--panel-line);
}

/* 分区标题行 */
.detail-panel .section-line {
  margin-bottom: 10px;
}
.detail-panel .section-line h3 {
  margin: 0;
  font-size: 14px;
}
.detail-panel .detail-section {
  margin: 0;
  padding-top: 12px;
  border-top: 1px dashed var(--panel-line);
}

/* Desktop detail is a compact reading column; dense content scrolls inside it. */
@media (min-width: 1025px) {
  .dashboard-stacked {
    height: max(460px, min(720px, calc(100vh - 240px)));
    max-height: max(460px, min(720px, calc(100vh - 240px)));
    flex: none;
    grid-template-rows: minmax(0, 1fr) 92px;
  }
  .dashboard-stacked > aside { height: 100%; min-height: 0; overflow-y: auto; }
  .map-with-kpi > .map-panel { height: 100%; }
  .map-with-kpi > .map-panel { min-height: 0 !important; }
  .kpi-grid article { padding: 11px 12px; }
  .kpi-grid article .kpi-value { font-size: 19px; margin-top: 4px; }
  .kpi-grid article .kpi-trend { font-size: 11px; }
}

@media (max-width: 560px) {
  .kpi-side { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.ai-placeholder {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-radius: 10px;
  background: var(--c-accent-soft);
  color: var(--c-text-soft);
  font-size: 13px;
  letter-spacing: 0.02em;
}
.ai-placeholder.error {
  background: var(--c-alert-soft);
  color: var(--c-alert);
}
.ai-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--c-accent-border);
  border-top-color: var(--c-accent);
  animation: ai-spin 0.8s linear infinite;
  flex: none;
}
/* AI 分析 Tab 切换：胶囊 + 渐变 active，与 CockpitSubTabs 同风格 */
.tab-switch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: var(--c-surface-soft);
  border: 1px solid var(--panel-line);
}
.tab-switch button {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}
.tab-switch button:hover {
  color: var(--text);
  background: var(--c-surface-soft);
}
.tab-switch button.active {
  background: var(--c-accent-soft);
  color: var(--text);
  border-color: var(--c-accent-border);
  box-shadow: 0 4px 14px var(--c-accent-glow);
}

@keyframes ai-spin {
  to { transform: rotate(360deg); }
}
</style>
