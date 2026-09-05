<template>
  <main class="page-cockpit">
    <div class="ckp-body">
      <!-- 标题区 -->
      <header class="ckp-title" aria-label="驾驶舱标题与数据身份">
        <div class="ckp-title-text">
          <p class="ckp-kicker">P01 · LAKE SITUATION COCKPIT</p>
          <h1>全湖态势综合驾驶舱</h1>
          <p class="ckp-sub">太湖流域演示分区 · 模拟数据研判视图，跨页共享档位与点位</p>
        </div>
        <div class="ckp-chips">
          <span class="ckp-chip">数据范围 <b>太湖流域 · 6 个演示分区</b></span>
          <span class="ckp-chip">数据版本 <b>{{ dataIdentity.datasetVersionId }} / {{ datasetVersion }}</b></span>
          <span class="ckp-chip">数据质量 <QualityBadge quality="pending" label="演示数据" /></span>
          <span class="ckp-chip">预测能力 <b>{{ capabilityLabel || '—' }}</b></span>
          <span class="ckp-chip ckp-chip--notice">SIMULATED · 非决策用途</span>
          <button type="button" class="ckp-reset" @click="resetFilters">恢复默认筛选</button>
        </div>
      </header>

      <!-- 左栏 · 4 张 KPI -->
      <section class="ckp-kpis" aria-label="核心指标">
        <MetricCard
          label="分区覆盖数"
          :value="kpiCoverage"
          unit="个演示分区"
          :delta="riskDistributionText"
          tone="neutral"
          as-of="太湖流域 · 演示数据"
          mode="simulated"
          mode-label="SIMULATED"
        />
        <MetricCard
          label="当前最高风险"
          :value="highestRisk.text"
          :delta="highestRisk.detail"
          :tone="highestRisk.tone"
          as-of="按当前档位强度排序"
          mode="simulated"
          mode-label="SIMULATED"
        />
        <MetricCard
          label="当前数据质量"
          :value="dataIdentity.datasetVersionId"
          :delta="`预测版本 ${datasetVersion}`"
          quality="pending"
          quality-label="演示数据"
          :as-of="kpiQualityAsOf"
          mode="simulated"
          mode-label="SIMULATED"
        />
        <MetricCard
          label="预测能力状态"
          :value="capabilityLabel || '—'"
          :delta="stageInfo ? stageInfo.label : '档位数据加载中'"
          tone="neutral"
          as-of="真实算法能力未接入"
          mode="simulated"
          mode-label="SIMULATED"
        />
        <p v-if="kpiError" class="ckp-kpi-err">
          指标数据加载失败
          <button type="button" class="ckp-inline-btn" @click="retryKpis">重试</button>
        </p>
      </section>

      <!-- 中栏 · 太湖地图 -->
      <section class="ckp-map ckp-block" aria-label="太湖全湖态势地图">
        <div class="ckp-map-tools">
          <div class="ckp-layer-toggles" role="group" aria-label="地图图层开关">
            <button type="button" :aria-pressed="String(showPoints)" @click="showPoints = !showPoints">站点</button>
            <button type="button" :aria-pressed="String(showHeat)" @click="showHeat = !showHeat">风险面</button>
            <button type="button" disabled aria-disabled="true" title="当前数据未提供">扩散轨迹</button>
          </div>
          <span v-if="mapDataLoading" class="ckp-map-flag" role="status">演示分区数据加载中…</span>
          <span class="ckp-map-flag">风险面 · 演示数据</span>
        </div>
        <div class="ckp-map-wrap">
          <LakeMap
            ref="mapRef"
            :model-value="store.selectedPoint"
            :point-list="mapPoints"
            :heat-field="heatField"
            :heat-stage-key="store.stageKey"
            :stage-label="mapStageLabel"
            title="太湖全湖态势 · 演示分区"
            :show-tabs="false"
            :points-visible="showPoints"
            :heat-visible="showHeat"
            heat-all-layers
            :reset-token="resetToken"
            @update:model-value="onMapPoint"
            @tile-error="onTileError"
          />
          <div v-if="mapDataError" class="ckp-map-overlay">
            <StatePanel state="error" title="地图数据加载失败" description="演示分区点位或风险面数据未能加载，地图底图仍可浏览。">
              <button type="button" class="ckp-inline-btn" @click="retryMapData">重试地图数据</button>
            </StatePanel>
          </div>
          <div v-else-if="tileError" class="ckp-map-flag ckp-map-flag--warn ckp-map-flag--tile" role="status">
            部分地图瓦片加载失败
            <button type="button" class="ckp-inline-btn" @click="retryTiles">重试图层</button>
          </div>
        </div>
      </section>

      <!-- 右栏 · 当前分区研判 -->
      <section class="ckp-brief ckp-block" aria-label="当前分区研判">
        <div v-if="selectedPointData" class="ckp-brief-inner">
          <header class="ckp-brief-head">
            <div>
              <p class="ckp-brief-code">{{ selectedPointData.short }}</p>
              <h2>{{ selectedPointData.name }}</h2>
            </div>
            <span class="ckp-risk-badge" :class="`lv-${selectedPointData.riskClass || 'low'}`">
              {{ selectedPointData.risk || '风险未知' }}
            </span>
          </header>

          <h3>数据概况</h3>
          <dl class="ckp-kv">
            <dt>藻密度</dt><dd>{{ selectedPointData.metrics?.density || '—' }}</dd>
            <dt>叶绿素 a</dt><dd>{{ selectedPointData.metrics?.chla || '—' }}</dd>
            <dt>总磷</dt><dd>{{ selectedPointData.metrics?.phosphorus || '—' }}</dd>
            <dt>水温</dt><dd>{{ selectedPointData.metrics?.temp || '—' }}</dd>
          </dl>

          <h3>主导因子</h3>
          <ul class="ckp-factors">
            <li v-for="f in selectedPointData.factors || []" :key="f.name">
              <span class="fk-name">{{ f.name }}</span>
              <span class="fk-track"><span class="fk-fill" :style="{ width: Math.min(100, Number(f.value) || 0) + '%' }"></span></span>
              <span class="fk-val">{{ f.value }}{{ f.unit || '%' }}</span>
            </li>
          </ul>

          <h3>建议动作 · {{ stageShort }}</h3>
          <p class="ckp-forecast">
            <strong>{{ forecast.title || '暂无建议' }}</strong>
            {{ forecast.text || '当前档位暂无演示建议输出。' }}
          </p>
        </div>
        <StatePanel
          v-else
          :state="load.points === 'error' ? 'error' : load.points === 'loading' ? 'loading' : 'empty'"
          :title="load.points === 'error' ? '分区数据加载失败' : load.points === 'loading' ? '分区数据加载中' : '未匹配到演示分区'"
          :description="load.points === 'error' ? '点位接口请求失败，可重试加载。' : ''"
        >
          <button v-if="load.points === 'error'" type="button" class="ckp-inline-btn" @click="fetchPoints">重试</button>
        </StatePanel>
        <RouterLink class="ckp-detail-btn" :to="stationsLink">查看站点详情</RouterLink>
      </section>

      <!-- 左栏 · 风险排行 -->
      <section class="ckp-ranking ckp-block" aria-label="分区风险排行">
        <header class="ckp-sec-head">
          <h2>分区风险排行</h2>
          <span class="ckp-sec-tag">{{ stageShort }} · 强度 0-100</span>
        </header>
        <ol v-if="ranking.length" class="ckp-rank-list">
          <li v-for="(row, i) in ranking" :key="row.id">
            <button
              type="button"
              class="ckp-rank-btn"
              :aria-current="row.id === store.selectedPoint ? 'true' : undefined"
              @click="selectFromRanking(row.id)"
            >
              <span class="rk-i">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="rk-code">{{ row.short }}</span>
              <span class="rk-name">{{ row.name }}</span>
              <span class="rk-level" :class="`lv-${row.riskClass}`">{{ riskShortText(row.riskClass) }}风险</span>
              <span class="rk-val">{{ row.intensity }}</span>
            </button>
          </li>
        </ol>
        <StatePanel
          v-else
          :state="load.region === 'error' ? 'error' : load.region === 'loading' ? 'loading' : 'empty'"
          :description="load.region === 'error' ? '区域汇总接口请求失败，可重试。' : ''"
        >
          <button v-if="load.region === 'error'" type="button" class="ckp-inline-btn" @click="fetchRegion">重试</button>
        </StatePanel>
      </section>

      <!-- 右栏 · 近期演示事件 -->
      <section class="ckp-events ckp-block" aria-label="近期演示事件">
        <header class="ckp-sec-head">
          <h2>近期演示事件</h2>
          <span class="ckp-sec-tag">{{ selectedPointData ? selectedPointData.name : '全部分区' }}</span>
        </header>
        <ul v-if="pointEvents.length" class="ckp-event-list">
          <li v-for="ev in pointEvents" :key="ev.id" class="ckp-event">
            <span class="ev-time">{{ ev.time }}</span>
            <span class="ev-title">{{ ev.title }}</span>
            <span class="ev-sev" :class="`sev-${ev.severity || 'low'}`">{{ severityText(ev.severity) }}风险</span>
          </li>
        </ul>
        <StatePanel
          v-else
          :state="load.events === 'error' ? 'error' : load.events === 'loading' ? 'loading' : 'empty'"
          :description="load.events === 'error' ? '事件接口请求失败，可重试。' : load.events === 'ok' ? '该分区暂无演示事件，可切换其他分区查看。' : ''"
        >
          <button v-if="load.events === 'error'" type="button" class="ckp-inline-btn" @click="fetchEvents">重试</button>
        </StatePanel>
      </section>

      <!-- 左栏 · 紧凑趋势 -->
      <section class="ckp-trend ckp-block" aria-label="选中分区风险强度趋势">
        <header class="ckp-sec-head">
          <h2>选中分区风险强度</h2>
          <span class="ckp-sec-tag">跨档位 · 演示值</span>
        </header>
        <EChart v-if="trendOption" class="ckp-trend-chart" :option="trendOption" :height="112" />
        <StatePanel
          v-else
          :state="load.region === 'error' ? 'error' : load.region === 'loading' ? 'loading' : 'empty'"
          :description="load.region === 'error' ? '区域汇总接口请求失败，可重试。' : ''"
        >
          <button v-if="load.region === 'error'" type="button" class="ckp-inline-btn" @click="fetchRegion">重试</button>
        </StatePanel>
      </section>

      <!-- 左栏 · 覆盖与质量小结 -->
      <section class="ckp-summary ckp-block" aria-label="覆盖与质量小结">
        <header class="ckp-sec-head">
          <h2>覆盖与质量小结</h2>
        </header>
        <dl class="ckp-summary-dl">
          <dt>演示分区</dt><dd>{{ region ? `${region.totalStations} / 6 已接入` : '—' }}</dd>
          <dt>风险分布</dt><dd>{{ riskDistributionText || '—' }}</dd>
          <dt>数据版本</dt><dd>{{ dataIdentity.datasetVersionId }} · 预测 {{ datasetVersion }}</dd>
          <dt>数据模式</dt><dd>SIMULATED · 非决策用途</dd>
          <dt>扩散轨迹</dt><dd>当前数据未提供</dd>
        </dl>
      </section>

      <!-- 单一主时间轴 -->
      <section class="ckp-timeline ckp-block" aria-label="预测时间轴">
        <TimeAxisBar
          v-if="stages.length"
          variant="axis"
          :stages="axisStages"
          :sub-label-map="subLabelMap"
        />
        <StatePanel
          v-else
          :state="load.stages === 'error' ? 'error' : 'loading'"
          :description="load.stages === 'error' ? '时间档位接口请求失败，可重试。' : ''"
        >
          <button v-if="load.stages === 'error'" type="button" class="ckp-inline-btn" @click="fetchStages">重试</button>
        </StatePanel>
      </section>

      <!-- 底部子页入口（移动端 Teleport 到 body，避开 route-stage 入场动画对 fixed 定位的捕获） -->
      <Teleport to="body" :disabled="!isMobileViewport">
        <nav class="ckp-entries" aria-label="驾驶舱子页入口">
          <RouterLink :to="stationsLink">进入站点诊断</RouterLink>
          <RouterLink to="/heatmap">进入风险研判</RouterLink>
          <RouterLink to="/history">进入事件复盘</RouterLink>
          <RouterLink class="ckp-wallboard-entry" to="/wallboard">打开综合展示大屏</RouterLink>
        </nav>
      </Teleport>
    </div>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { cockpitState, useCockpitStore } from '../stores/cockpit.js'
import { getEvents, getHeatField, getPoints, getRegionSummary, getTimeStages } from '../services/api.js'
import LakeMap from '../components/cockpit/LakeMap.vue'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import EChart from '../components/cockpit/EChart.vue'
import MetricCard from '../components/common/MetricCard.vue'
import QualityBadge from '../components/common/QualityBadge.vue'
import StatePanel from '../components/common/StatePanel.vue'
import { axisLabelTheme, axisLineTheme, palette, splitLineTheme, tooltipTheme } from '../components/cockpit/echartsTheme.js'
import { useTheme } from '../composables/useTheme.js'
import { dataIdentity } from '../data/dataIdentity.js'

const DEFAULT_STAGE = 't7'
const DEFAULT_POINT = 'northwest_hotspot'
const STAGE_IDX = { t1: 0, t3: 1, t7: 2, t15: 3, t30: 4 }
const STAGE_DAYS = { t1: 1, t3: 3, t7: 7, t15: 15, t30: 30 }
const CAPABILITY_LABELS = {
  sample_interface_only: '演示预测接口',
  simulation_only: '模拟预演'
}

const router = useRouter()
useCockpitStore()
const store = cockpitState()
const { theme } = useTheme()

const stages = ref([])
const points = ref([])
const positions = ref({})
const heatField = ref({})
const events = ref([])
const region = ref(null)
const load = reactive({ stages: 'loading', points: 'loading', heat: 'loading', events: 'loading', region: 'loading' })

const showPoints = ref(true)
const showHeat = ref(true)
const resetToken = ref(0)
const tileError = ref(false)
const mapRef = ref(null)

// ≤759px 时底部入口 Teleport 到 body，避开页面入场动画父级对 fixed 定位的捕获
const mobileMq = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 759px)')
  : null
const isMobileViewport = ref(Boolean(mobileMq && mobileMq.matches))
function onMobileMqChange(e) {
  isMobileViewport.value = e.matches
}
onMounted(() => {
  mobileMq?.addEventListener('change', onMobileMqChange)
})
onBeforeUnmount(() => {
  mobileMq?.removeEventListener('change', onMobileMqChange)
})

const prefersReducedMotion = typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches

async function fetchStages() {
  load.stages = 'loading'
  try {
    stages.value = await getTimeStages()
    load.stages = 'ok'
  } catch (e) {
    load.stages = 'error'
  }
}

async function fetchPoints() {
  load.points = 'loading'
  try {
    const data = await getPoints()
    // 接口返回 { pointData: {...}, pointPositions: {...} }；mock 直接返回点位映射，两种结构都兼容
    const raw = data && data.pointData ? data.pointData : data
    points.value = Array.isArray(raw) ? raw : Object.values(raw || {})
    positions.value = (data && data.pointPositions) || {}
    load.points = 'ok'
  } catch (e) {
    load.points = 'error'
  }
}

async function fetchHeat() {
  load.heat = 'loading'
  try {
    heatField.value = await getHeatField()
    load.heat = 'ok'
  } catch (e) {
    load.heat = 'error'
  }
}

async function fetchEvents() {
  load.events = 'loading'
  try {
    events.value = await getEvents()
    load.events = 'ok'
  } catch (e) {
    load.events = 'error'
  }
}

async function fetchRegion() {
  load.region = 'loading'
  try {
    region.value = await getRegionSummary()
    load.region = 'ok'
  } catch (e) {
    load.region = 'error'
  }
}

onMounted(() => {
  fetchStages()
  fetchPoints()
  fetchHeat()
  fetchEvents()
  fetchRegion()
})

// ---------- 档位与选中分区 ----------
const stageInfo = computed(() => stages.value.find((s) => s.key === store.stageKey) || null)
const stageShort = computed(() => {
  if (stageInfo.value && stageInfo.value.days) return `T+${stageInfo.value.days}`
  const d = STAGE_DAYS[store.stageKey]
  return d ? `T+${d}` : '—'
})
const capabilityLabel = computed(() => {
  if (stageInfo.value && stageInfo.value.capability_status) {
    return CAPABILITY_LABELS[stageInfo.value.capability_status] || '能力未就绪'
  }
  if (store.stageKey === 't30') return CAPABILITY_LABELS.simulation_only
  return ''
})
const subLabelMap = computed(() => {
  const map = {}
  stages.value.forEach((s) => {
    map[s.key] = CAPABILITY_LABELS[s.capability_status] || '演示预测接口'
  })
  return map
})
const axisStages = computed(() => stages.value.map((s) => ({
  key: s.key,
  label: `T+${s.days}`,
  short: s.short,
  days: s.days,
  index: s.index
})))

const selectedPointData = computed(() => points.value.find((p) => p.id === store.selectedPoint) || null)
const datasetVersion = computed(() =>
  selectedPointData.value?.datasetVersion || points.value[0]?.datasetVersion || dataIdentity.predictionRunId
)

// 演示分区无经纬度字段：用后端 pointPositions 百分比映射到太湖范围（与 LakeMap 热力网格同边界）
const GRID_BOUNDS = { south: 30.9, north: 31.48, west: 119.88, east: 120.38 }
const mapPoints = computed(() => points.value.map((p) => {
  if (p.coord) return p
  const pos = positions.value[p.id]
  if (!pos) return p
  const top = parseFloat(pos.top)
  const left = parseFloat(pos.left)
  if (!Number.isFinite(top) || !Number.isFinite(left)) return p
  return {
    ...p,
    coord: {
      lat: GRID_BOUNDS.north - (top / 100) * (GRID_BOUNDS.north - GRID_BOUNDS.south),
      lon: GRID_BOUNDS.west + (left / 100) * (GRID_BOUNDS.east - GRID_BOUNDS.west)
    }
  }
}))

const fIdx = computed(() => STAGE_IDX[store.stageKey] ?? 2)
const forecast = computed(() => {
  const fc = selectedPointData.value?.forecast
  if (!fc || !Array.isArray(fc.window)) return { title: '', text: '' }
  const i = Math.min(fIdx.value, (fc.title || []).length - 1)
  if (i < 0) return { title: '', text: '' }
  return { title: fc.title[i] || '', text: fc.text[i] || '', window: fc.window[i] || '' }
})

// ---------- 排行 / KPI ----------
const ranking = computed(() => {
  if (!region.value || !region.value.intensity) return []
  return points.value
    .map((p) => ({
      id: p.id,
      short: p.short,
      name: p.name,
      riskClass: p.riskClass || 'low',
      intensity: region.value.intensity[p.id]?.[store.stageKey] ?? null
    }))
    .filter((r) => r.intensity !== null)
    .sort((a, b) => b.intensity - a.intensity)
})

const kpiCoverage = computed(() => {
  if (region.value && region.value.totalStations != null) return String(region.value.totalStations)
  if (points.value.length) return String(points.value.length)
  return '—'
})

const riskDistributionText = computed(() => {
  const rc = region.value?.riskCounts
  if (!rc) return ''
  return `高 ${rc.high || 0} · 中 ${rc.mid || 0} · 低 ${rc.low || 0}`
})

const highestRisk = computed(() => {
  if (!region.value || !region.value.riskCounts) return { text: '—', detail: '', tone: 'neutral' }
  const rc = region.value.riskCounts
  let cls = null
  if ((rc.high || 0) > 0) cls = 'high'
  else if ((rc.mid || 0) > 0) cls = 'mid'
  else if ((rc.low || 0) > 0) cls = 'low'
  if (!cls) return { text: '—', detail: '', tone: 'neutral' }
  const names = { high: '高风险', mid: '中风险', low: '低风险' }
  const tones = { high: 'bad', mid: 'warn', low: 'good' }
  const top = ranking.value.find((r) => r.riskClass === cls)
  return {
    text: names[cls],
    detail: top ? `${top.short} ${top.name}` : `${rc[cls]} 个分区`,
    tone: tones[cls]
  }
})

const kpiError = computed(() => load.points === 'error' || load.region === 'error' || load.stages === 'error')

const kpiQualityAsOf = computed(() => `${dataIdentity.asOfLabel} · ${dataIdentity.claimBoundary}`)

function retryKpis() {
  fetchStages()
  fetchPoints()
  fetchRegion()
}

function riskShortText(cls) {
  return { high: '高', mid: '中', low: '低' }[cls] || '低'
}

function severityText(sev) {
  return { high: '高', mid: '中', low: '低' }[sev] || '低'
}

const pointEvents = computed(() =>
  events.value.filter((e) => e.point === store.selectedPoint).slice(0, 5)
)

// ---------- 趋势图 ----------
const trendOption = computed(() => {
  if (!region.value || !region.value.intensity || !selectedPointData.value) return null
  void theme.value // 主题切换时重算配色
  const keys = stages.value.length
    ? stages.value.map((s) => s.key)
    : ['t1', 't3', 't7', 't15', 't30']
  const labels = keys.map((k) => `T+${STAGE_DAYS[k] || '?'}`)
  const data = keys.map((k) => region.value.intensity[selectedPointData.value.id]?.[k] ?? null)
  if (data.every((v) => v === null)) return null
  const pal = palette()
  const curIdx = keys.indexOf(store.stageKey)
  return {
    animation: !prefersReducedMotion,
    grid: { left: 34, right: 12, top: 16, bottom: 24, containLabel: true },
    tooltip: { trigger: 'axis', ...tooltipTheme() },
    xAxis: { type: 'category', data: labels, axisLabel: axisLabelTheme(), axisLine: axisLineTheme() },
    yAxis: { type: 'value', max: 100, splitLine: splitLineTheme(), axisLabel: axisLabelTheme() },
    series: [{
      type: 'line',
      data,
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { color: pal.accent, width: 2 },
      itemStyle: { color: pal.accent },
      areaStyle: { color: hexToRgba(pal.accent, 0.14) },
      markLine: curIdx >= 0 ? {
        silent: true,
        symbol: 'none',
        label: { formatter: '当前档位', color: pal.alert, fontSize: 10, position: 'insideEndTop' },
        lineStyle: { color: pal.alert, type: 'dashed' },
        data: [{ xAxis: curIdx }]
      } : undefined
    }]
  }
})

function hexToRgba(color, alpha) {
  if (typeof color === 'string' && /^#[0-9a-fA-F]{6}$/.test(color)) {
    const r = parseInt(color.slice(1, 3), 16)
    const g = parseInt(color.slice(3, 5), 16)
    const b = parseInt(color.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
  }
  return color
}

// ---------- 地图 ----------
const mapDataLoading = computed(() => load.points === 'loading')
const mapDataError = computed(() => load.points === 'error' || load.heat === 'error')
const mapStageLabel = computed(() => {
  const cap = capabilityLabel.value
  return cap ? `${stageShort.value} · ${cap}` : stageShort.value
})

// 地图点击序列必须独立记录：默认点位（如 NW-01）本身已处于选中态，
// 不能用 selectedPoint 充当“已点击过一次”的依据，否则首次点击就会下钻。
const MAP_RECLICK_WINDOW_MS = 5000
let lastMapClick = { id: null, at: 0 }

function onMapPoint(id) {
  const now = Date.now()
  if (lastMapClick.id === id && now - lastMapClick.at <= MAP_RECLICK_WINDOW_MS) {
    // 时间窗内第二次点击同一分区 → 下钻站点诊断；随后清空序列
    lastMapClick = { id: null, at: 0 }
    router.push(stationsLink.value)
    return
  }
  lastMapClick = { id, at: now }
  store.selectedPoint = id
}

function selectFromRanking(id) {
  store.selectedPoint = id
}

function onTileError(hasError) {
  tileError.value = Boolean(hasError)
}

function retryTiles() {
  mapRef.value?.retryTiles()
}

function retryMapData() {
  fetchPoints()
  fetchHeat()
}

const stationsLink = computed(() => ({
  path: '/stations',
  query: { t: store.stageKey, p: store.selectedPoint }
}))

function resetFilters() {
  store.playing = false
  store.speed = 1
  store.currentEventId = null
  store.stageKey = DEFAULT_STAGE
  store.selectedPoint = DEFAULT_POINT
  lastMapClick = { id: null, at: 0 }
  showPoints.value = true
  showHeat.value = true
  resetToken.value += 1
  // 等点位/风险面可见性 props 更新后，再复位基础图层与默认视野
  nextTick(() => mapRef.value?.resetMapState())
}
</script>

<style scoped>
.page-cockpit {
  max-width: 1720px;
  margin: 0 auto;
  padding: 22px 32px 44px;
}

.ckp-body {
  display: grid;
  gap: 14px;
  grid-template-columns: minmax(310px, 22fr) minmax(0, 56fr) minmax(310px, 22fr);
  /* ≥1440 专用：研判跨 kpis+rank 两行、演示事件跨 trend+summary 两行，
     左右两栏行高对齐，保证 1080 高度内标题/KPI/地图/时间轴/入口同屏 */
  grid-template-areas:
    'title title title'
    'kpis map brief'
    'rank map brief'
    'trend map events'
    'summary map events'
    'timeline timeline timeline'
    'entries entries entries';
  align-items: start;
}

/* ---------- 标题区 ---------- */
.ckp-title {
  grid-area: title;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px 18px;
  padding: 18px 22px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.ckp-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.22em;
  color: var(--color-primary);
}
.ckp-title h1 {
  margin: 4px 0 2px;
  font-family: var(--font-display);
  font-size: clamp(20px, 2.2vw, 28px);
  font-weight: 700;
  color: var(--text-primary);
}
.ckp-sub {
  font-size: 12.5px;
  color: var(--text-secondary);
}
.ckp-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.ckp-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.ckp-chip b {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-weight: 600;
}
.ckp-chip--notice {
  border-color: color-mix(in srgb, var(--data-simulated, #f5b45d) 45%, transparent);
  color: var(--data-simulated, #f5b45d);
}
.ckp-reset {
  padding: 8px 14px;
  min-height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: transparent;
  color: var(--text-primary);
  font-size: 12.5px;
  cursor: pointer;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.ckp-reset:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* ---------- 区块通用 ---------- */
.ckp-block {
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.ckp-block h2,
.ckp-sec-head h2 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text-primary);
}
.ckp-block h3 {
  margin: 14px 0 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}
.ckp-sec-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.ckp-sec-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* ---------- KPI ---------- */
.ckp-kpis {
  grid-area: kpis;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  align-content: start;
}
.ckp-kpis :deep(.mc-num) {
  font-size: 18px;
}
.ckp-kpis :deep(.mc-foot) {
  flex-wrap: wrap;
  row-gap: 2px;
}
.ckp-kpis :deep(.mc-asof) {
  white-space: normal;
  line-height: 1.5;
}
.ckp-kpi-err {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 12px;
  color: var(--risk-critical);
}

/* ---------- 地图 ---------- */
.ckp-map {
  grid-area: map;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ckp-map-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.ckp-layer-toggles {
  display: inline-flex;
  gap: 6px;
}
.ckp-layer-toggles button {
  padding: 7px 13px;
  min-height: 34px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.ckp-layer-toggles button[aria-pressed='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.ckp-layer-toggles button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.ckp-map-wrap {
  position: relative;
  flex: 1;
  display: flex;
  min-height: 0;
}
.ckp-map-wrap > :first-child {
  flex: 1;
}
.ckp-map :deep(.map-panel) {
  min-height: 0;
}
.ckp-map :deep(.leaflet-map-container) {
  min-height: 500px;
}
.ckp-map-flag {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.ckp-map-flag--warn {
  color: var(--risk-medium);
}
.ckp-map-flag--tile {
  position: absolute;
  left: 12px;
  bottom: 46px;
  z-index: 1100;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--risk-medium) 45%, transparent);
  border-radius: 10px;
  background: var(--surface-panel);
}
.ckp-map-overlay {
  position: absolute;
  inset: 0;
  z-index: 1150;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: color-mix(in srgb, var(--surface-panel) 78%, transparent);
  backdrop-filter: blur(4px);
}
.ckp-inline-btn {
  padding: 6px 12px;
  min-height: 30px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}
.ckp-inline-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* ---------- 右栏 · 分区研判 ---------- */
.ckp-brief {
  grid-area: brief;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ckp-brief-inner {
  display: flex;
  flex-direction: column;
}
.ckp-brief-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.ckp-brief-code {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--text-muted);
}
.ckp-brief-head h2 {
  margin: 2px 0 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.ckp-risk-badge {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid currentColor;
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.lv-high { color: var(--risk-critical); }
.lv-mid { color: var(--risk-medium); }
.lv-low { color: var(--risk-low); }
.ckp-risk-badge.lv-high { background: color-mix(in srgb, var(--risk-critical) 12%, transparent); }
.ckp-risk-badge.lv-mid { background: color-mix(in srgb, var(--risk-medium) 12%, transparent); }
.ckp-risk-badge.lv-low { background: color-mix(in srgb, var(--risk-low) 12%, transparent); }

.ckp-kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 14px;
  margin: 0;
  font-size: 12.5px;
}
.ckp-kv dt {
  color: var(--text-muted);
}
.ckp-kv dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.ckp-factors {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.ckp-factors li {
  display: grid;
  grid-template-columns: 64px 1fr 44px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.fk-name {
  color: var(--text-secondary);
}
.fk-track {
  height: 6px;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}
.fk-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--color-primary);
}
.fk-val {
  font-family: var(--font-mono);
  color: var(--text-primary);
  text-align: right;
}

.ckp-forecast {
  margin: 0;
  padding: 10px 12px;
  border-left: 2px solid var(--color-primary);
  border-radius: 0 10px 10px 0;
  background: var(--surface-panel-soft);
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--text-secondary);
}
.ckp-forecast strong {
  display: block;
  margin-bottom: 3px;
  color: var(--text-primary);
}

.ckp-detail-btn {
  margin-top: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 16px;
  min-height: 40px;
  border: 1px solid var(--color-primary);
  border-radius: 10px;
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transition: background 0.18s ease;
}
.ckp-detail-btn:hover {
  background: color-mix(in srgb, var(--color-primary) 20%, transparent);
}

/* ---------- 排行 ---------- */
.ckp-ranking {
  grid-area: rank;
}
.ckp-rank-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ckp-rank-btn {
  width: 100%;
  display: grid;
  grid-template-columns: 24px 46px minmax(0, 1fr) auto 32px;
  align-items: center;
  gap: 8px;
  padding: 7px 9px;
  min-height: 38px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.ckp-rank-btn:hover {
  border-color: var(--border-subtle);
  color: var(--text-primary);
}
.ckp-rank-btn[aria-current='true'] {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
}
.rk-i {
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.rk-code {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.rk-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rk-level {
  padding: 2px 8px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 10.5px;
  white-space: nowrap;
}
.rk-val {
  font-family: var(--font-mono);
  color: var(--text-primary);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* ---------- 事件 ---------- */
.ckp-events {
  grid-area: events;
}
.ckp-event-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ckp-event {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  font-size: 12px;
}
.ev-time {
  font-family: var(--font-mono);
  color: var(--text-muted);
  white-space: nowrap;
}
.ev-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.ev-sev {
  padding: 2px 8px;
  border: 1px solid currentColor;
  border-radius: 999px;
  font-size: 10.5px;
  white-space: nowrap;
}
.sev-high { color: var(--risk-critical); }
.sev-mid { color: var(--risk-medium); }
.sev-low { color: var(--risk-low); }

/* ---------- 趋势 / 小结 ---------- */
.ckp-trend { grid-area: trend; }
.ckp-summary { grid-area: summary; }
.ckp-summary-dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 14px;
  margin: 0;
  font-size: 12.5px;
}
.ckp-summary-dl dt {
  color: var(--text-muted);
  white-space: nowrap;
}
.ckp-summary-dl dd {
  margin: 0;
  color: var(--text-primary);
}

/* ---------- 时间轴 / 入口 ---------- */
.ckp-timeline { grid-area: timeline; }
.ckp-entries {
  grid-area: entries;
  display: flex;
  gap: 12px;
}
.ckp-entries a {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 16px;
  min-height: 44px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  color: var(--text-primary);
  font-size: 13px;
  text-decoration: none;
  transition: border-color 0.18s ease, color 0.18s ease;
}
.ckp-entries a:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.ckp-body :focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* ---------- ≥1440：1920×1080 一屏总览 ----------
   压缩标题区 / KPI / 各区块高度，地图随左右栏总高撑满中栏，
   使标题、核心 KPI、地图、主时间轴与底部入口都在 1080 高度内可见 */
@media (min-width: 1440px) {
  .page-cockpit {
    padding: 10px 32px 16px;
  }
  .ckp-body {
    gap: 8px;
  }
  .ckp-map {
    align-self: stretch;
  }

  .ckp-title {
    padding: 8px 14px;
    gap: 6px 14px;
  }
  .ckp-kicker {
    font-size: 10px;
  }
  .ckp-title h1 {
    margin: 2px 0 0;
    font-size: 18px;
  }
  .ckp-sub {
    display: none;
  }
  .ckp-chip {
    padding: 3px 9px;
    font-size: 10.5px;
  }
  .ckp-reset {
    padding: 6px 12px;
    min-height: 32px;
    font-size: 11.5px;
  }

  .ckp-kpis {
    gap: 8px;
  }
  .ckp-kpis :deep(.metric-card) {
    padding: 8px 10px;
    gap: 4px;
  }
  .ckp-kpis :deep(.mc-num) {
    font-size: 18px;
  }
  .ckp-kpis :deep(.mc-delta) {
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ckp-kpis :deep(.mc-foot) {
    display: none;
  }

  .ckp-ranking,
  .ckp-trend,
  .ckp-summary,
  .ckp-brief,
  .ckp-events {
    padding: 8px 12px;
  }
  .ckp-sec-head {
    margin-bottom: 4px;
  }
  .ckp-rank-list {
    gap: 4px;
  }
  .ckp-rank-btn {
    min-height: 26px;
    padding: 2px 8px;
    gap: 6px;
    font-size: 11.5px;
  }
  .ckp-trend-chart {
    height: 96px !important;
  }
  .ckp-block h3 {
    margin: 8px 0 5px;
    font-size: 11px;
  }
  .ckp-kv {
    font-size: 11.5px;
    gap: 4px 12px;
  }
  .ckp-factors {
    gap: 5px;
  }
  .ckp-factors li {
    font-size: 11.5px;
  }
  .ckp-forecast {
    padding: 8px 10px;
    font-size: 11.5px;
    line-height: 1.6;
  }
  .ckp-detail-btn {
    margin-top: 8px;
    min-height: 32px;
    padding: 6px 14px;
    font-size: 12.5px;
  }
  .ckp-event-list {
    gap: 5px;
  }
  .ckp-event {
    padding: 6px 8px;
    font-size: 11.5px;
  }
  .ckp-summary-dl {
    font-size: 11.5px;
    gap: 3px 12px;
  }
  .ckp-timeline {
    padding: 6px 10px;
  }
  .ckp-timeline :deep(.time-axis.axis-mode) {
    padding: 8px 14px;
    gap: 10px;
  }
  .ckp-entries a {
    min-height: 36px;
  }
}

@media (min-width: 1600px) {
  .ckp-summary-dl {
    grid-template-columns: auto 1fr auto 1fr;
  }
}

/* ---------- 1180–1439：地图优先，右栏下移 ---------- */
@media (max-width: 1439px) {
  .ckp-body {
    grid-template-columns: minmax(280px, 30fr) minmax(0, 70fr);
    grid-template-areas:
      'title title'
      'kpis map'
      'rank map'
      'trend map'
      'summary map'
      'brief brief'
      'events events'
      'timeline timeline'
      'entries entries';
  }
  .ckp-brief-inner {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 4px 26px;
  }
}

/* ---------- 760–1179：单列，时间轴在事件之后 ---------- */
@media (max-width: 1179px) {
  .page-cockpit {
    padding: 18px 18px 36px;
  }
  .ckp-body {
    grid-template-columns: 1fr;
    grid-template-areas:
      'title'
      'map'
      'kpis'
      'rank'
      'brief'
      'events'
      'timeline'
      'trend'
      'summary'
      'entries';
  }
  .ckp-kpis {
    grid-template-columns: repeat(2, 1fr);
  }
  .ckp-map :deep(.leaflet-map-container) {
    min-height: 440px;
  }
}

/* ---------- ≤759：移动端（390 基准） ---------- */
@media (max-width: 759px) {
  .page-cockpit {
    padding: 14px 14px calc(78px + env(safe-area-inset-bottom));
  }
  .ckp-body {
    gap: 12px;
    /* 移动端信息顺序：标题（含能力摘要）→ 地图 → 其余 KPI / 研判 */
    grid-template-areas:
      'title'
      'map'
      'kpis'
      'timeline'
      'brief'
      'rank'
      'events'
      'trend'
      'summary';
  }
  .ckp-kpis {
    grid-template-columns: 1fr 1fr;
  }
  .ckp-map :deep(.leaflet-map-container) {
    min-height: 360px;
    height: 420px;
  }
  .ckp-title {
    padding: 14px 16px;
  }
  .ckp-entries {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1200;
    gap: 8px;
    padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
    border-top: 1px solid var(--border-subtle);
    background: var(--surface-panel);
    backdrop-filter: blur(10px);
  }
  .ckp-entries a {
    min-height: 44px;
    padding: 8px;
  }

  /* 移动端触摸目标 ≥44px（WCAG 2.5.5） */
  .ckp-reset {
    min-height: 44px;
    padding: 10px 16px;
  }
  .ckp-layer-toggles button {
    min-height: 44px;
  }
  .ckp-inline-btn {
    min-height: 44px;
  }
  .ckp-rank-btn {
    min-height: 44px;
  }
  .ckp-detail-btn {
    min-height: 44px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ckp-reset,
  .ckp-layer-toggles button,
  .ckp-rank-btn,
  .ckp-entries a,
  .ckp-detail-btn {
    transition: none;
  }
}
</style>
