<template>
  <main class="wallboard">
    <header class="wb-head">
      <RouterLink class="wb-back" to="/cockpit" aria-label="返回综合驾驶舱">← <span>返回驾驶舱</span></RouterLink>
      <div class="wb-title">
        <p>TAIHU ALGAE SITUATION · DEMONSTRATION BOARD</p>
        <h1>太湖蓝藻水华综合展示大屏</h1>
      </div>
      <div class="wb-identity" aria-label="数据身份与使用边界">
        <span>{{ dataIdentity.datasetVersionId }}</span>
        <strong>SIMULATED</strong>
        <span>{{ dataIdentity.asOfFull }}</span>
        <b>非决策用途</b>
      </div>
    </header>

    <div class="wb-layout">
      <aside class="wb-left" aria-label="全湖概况与风险排行">
        <section class="wb-panel wb-overview">
          <PanelTitle eyebrow="LAKE OVERVIEW" title="全湖演示概况" />
          <div class="wb-kpis">
            <article><span>覆盖分区</span><strong>{{ coverage }}</strong><small>个演示分区</small></article>
            <article><span>当前最高风险</span><strong :class="`risk-${highestRisk.className}`">{{ highestRisk.text }}</strong><small>{{ highestRisk.detail }}</small></article>
            <article><span>当前档位</span><strong>{{ stageLabel }}</strong><small>{{ capabilityLabel }}</small></article>
            <article><span>演示事件</span><strong>{{ events.length || '—' }}</strong><small>条模拟记录</small></article>
          </div>
        </section>

        <section class="wb-panel wb-rank">
          <PanelTitle eyebrow="RISK RANKING" title="分区风险排行" :meta="`${stageLabel} · 强度 0–100`" />
          <ol v-if="ranking.length" class="wb-rank-list">
            <li v-for="(row, index) in ranking" :key="row.id">
              <button type="button" :aria-current="row.id === store.selectedPoint ? 'true' : undefined" @click="store.selectedPoint = row.id">
                <span class="rank-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="rank-name"><b>{{ row.short }}</b>{{ row.name }}</span>
                <span class="rank-risk" :class="`risk-${row.riskClass}`">{{ riskText(row.riskClass) }}</span>
                <strong>{{ row.intensity }}</strong>
              </button>
            </li>
          </ol>
          <p v-else class="wb-state">{{ load.region === 'error' ? '排行加载失败' : '排行加载中…' }}</p>
        </section>

        <section class="wb-panel wb-trend">
          <PanelTitle eyebrow="HORIZON TREND" title="选中分区风险趋势" :meta="selectedPoint?.short || '—'" />
          <EChart v-if="trendOption" :option="trendOption" :height="150" />
          <p v-else class="wb-state">趋势数据加载中…</p>
        </section>
      </aside>

      <section class="wb-center" aria-label="太湖风险态势地图">
        <div class="wb-map-caption">
          <div><span>当前研判分区</span><strong>{{ selectedPoint?.name || '数据加载中' }}</strong></div>
          <div class="wb-map-tags"><span>站点</span><span>风险面</span><b>{{ stageLabel }}</b></div>
        </div>
        <LakeMap
          :model-value="store.selectedPoint"
          :point-list="mapPoints"
          :heat-field="heatField"
          :heat-stage-key="store.stageKey"
          :stage-label="`${stageLabel} · ${capabilityLabel}`"
          title="太湖全湖态势 · 演示数据"
          :show-tabs="false"
          :heat-all-layers="true"
          @update:model-value="store.selectedPoint = $event"
          @tile-error="tileError = Boolean($event)"
        />
        <p v-if="mapError" class="wb-map-message wb-map-message--error">地图业务数据加载失败，请返回驾驶舱重试。</p>
        <p v-else-if="tileError" class="wb-map-message">部分底图瓦片不可用，风险点位与业务数据不受影响。</p>
      </section>

      <aside class="wb-right" aria-label="当前分区研判与事件">
        <section class="wb-panel wb-detail">
          <PanelTitle eyebrow="ZONE SNAPSHOT" title="当前分区研判" :meta="selectedPoint?.short || '—'" />
          <template v-if="selectedPoint">
            <div class="wb-zone-head">
              <div><h2>{{ selectedPoint.name }}</h2><p>{{ selectedPoint.summary }}</p></div>
              <span :class="`risk-pill risk-${selectedPoint.riskClass || 'low'}`">{{ riskText(selectedPoint.riskClass) }}风险</span>
            </div>
            <dl class="wb-metrics">
              <div><dt>藻密度</dt><dd>{{ selectedPoint.metrics?.density || '—' }}</dd></div>
              <div><dt>叶绿素 a</dt><dd>{{ selectedPoint.metrics?.chla || '—' }}</dd></div>
              <div><dt>总磷</dt><dd>{{ selectedPoint.metrics?.phosphorus || '—' }}</dd></div>
              <div><dt>温度代理</dt><dd>{{ selectedPoint.metrics?.temp || '—' }}</dd></div>
            </dl>
          </template>
          <p v-else class="wb-state">分区数据加载中…</p>
        </section>

        <section class="wb-panel wb-factors">
          <PanelTitle eyebrow="SIMULATED DRIVERS" title="演示驱动因子" />
          <ul v-if="selectedPoint?.factors?.length">
            <li v-for="factor in selectedPoint.factors" :key="factor.name">
              <div><span>{{ factor.name }}</span><b>{{ factor.value }}%</b></div>
              <span class="factor-track"><i :style="{ width: `${Math.min(100, Number(factor.value) || 0)}%` }"></i></span>
            </li>
          </ul>
          <p class="wb-note">因子为固定规则生成的演示解释，不是已验证的模型归因。</p>
        </section>

        <section class="wb-panel wb-events">
          <PanelTitle eyebrow="DEMO EVENTS" title="近期演示事件" :meta="`${pointEvents.length} 条`" />
          <ul v-if="pointEvents.length">
            <li v-for="event in pointEvents" :key="event.id">
              <time>{{ event.time }}</time>
              <span><b>{{ event.title }}</b><small>{{ event.summary }}</small></span>
              <i :class="`risk-${event.severity || 'low'}`">{{ riskText(event.severity) }}</i>
            </li>
          </ul>
          <p v-else class="wb-state">该分区暂无演示事件</p>
        </section>

        <section class="wb-boundary" aria-label="能力边界">
          <strong>能力边界</strong>
          <span>{{ dataIdentity.claimNote }}</span>
        </section>
      </aside>
    </div>

    <footer class="wb-footer" aria-label="预测时间轴与数据说明">
      <div class="wb-source"><span>数据模式</span><b>SIMULATED</b><small>{{ dataIdentity.datasetVersionId }} / {{ dataIdentity.predictionRunId }}</small></div>
      <TimeAxisBar v-if="axisStages.length" variant="axis" :stages="axisStages" :sub-label-map="subLabelMap" />
      <p v-else class="wb-state">预测档位加载中…</p>
      <div class="wb-capability"><span>当前能力</span><b>{{ capabilityLabel }}</b><small>真实算法能力未接入</small></div>
    </footer>
  </main>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import { cockpitState, useCockpitStore } from '../stores/cockpit.js'
import { getEvents, getHeatField, getPoints, getRegionSummary, getTimeStages } from '../services/api.js'
import LakeMap from '../components/cockpit/LakeMap.vue'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import EChart from '../components/cockpit/EChart.vue'
import { axisLabelTheme, axisLineTheme, palette, splitLineTheme, tooltipTheme } from '../components/cockpit/echartsTheme.js'
import { dataIdentity } from '../data/dataIdentity.js'
import { useTheme } from '../composables/useTheme.js'

const PanelTitle = defineComponent({
  props: { eyebrow: String, title: String, meta: String },
  setup: (props) => () => h('header', { class: 'wb-panel-title' }, [
    h('div', [h('p', props.eyebrow), h('h2', props.title)]),
    props.meta ? h('span', props.meta) : null
  ])
})

const STAGE_DAYS = { t1: 1, t3: 3, t7: 7, t15: 15, t30: 30 }
const CAPABILITIES = { sample_interface_only: '演示预测接口', simulation_only: '模拟预演' }
const GRID_BOUNDS = { south: 30.9, north: 31.48, west: 119.88, east: 120.38 }

useCockpitStore()
const store = cockpitState()
const { theme } = useTheme()
const stages = ref([])
const points = ref([])
const positions = ref({})
const heatField = ref({})
const events = ref([])
const region = ref(null)
const tileError = ref(false)
const load = reactive({ stages: 'loading', points: 'loading', heat: 'loading', events: 'loading', region: 'loading' })

async function loadOne(key, call, apply) {
  load[key] = 'loading'
  try { apply(await call()); load[key] = 'ok' } catch { load[key] = 'error' }
}

onMounted(() => {
  loadOne('stages', getTimeStages, (value) => { stages.value = value || [] })
  loadOne('points', getPoints, (value) => {
    const raw = value?.pointData || value
    points.value = Array.isArray(raw) ? raw : Object.values(raw || {})
    positions.value = value?.pointPositions || {}
  })
  loadOne('heat', getHeatField, (value) => { heatField.value = value || {} })
  loadOne('events', getEvents, (value) => { events.value = value || [] })
  loadOne('region', getRegionSummary, (value) => { region.value = value || null })
})

const selectedPoint = computed(() => points.value.find((point) => point.id === store.selectedPoint) || points.value[0] || null)
const coverage = computed(() => region.value?.totalStations ?? points.value.length ?? '—')
const stageInfo = computed(() => stages.value.find((stage) => stage.key === store.stageKey))
const stageLabel = computed(() => `T+${stageInfo.value?.days || STAGE_DAYS[store.stageKey] || '—'}`)
const capabilityLabel = computed(() => CAPABILITIES[stageInfo.value?.capability_status] || (store.stageKey === 't30' ? '模拟预演' : '演示预测接口'))
const axisStages = computed(() => stages.value.map((stage) => ({ ...stage, label: `T+${stage.days}` })))
const subLabelMap = computed(() => Object.fromEntries(stages.value.map((stage) => [stage.key, CAPABILITIES[stage.capability_status] || '能力未就绪'])))
const mapError = computed(() => load.points === 'error' || load.heat === 'error')

const mapPoints = computed(() => points.value.map((point) => {
  if (point.coord) return point
  const pos = positions.value[point.id]
  const top = parseFloat(pos?.top)
  const left = parseFloat(pos?.left)
  if (!Number.isFinite(top) || !Number.isFinite(left)) return point
  return { ...point, coord: {
    lat: GRID_BOUNDS.north - (top / 100) * (GRID_BOUNDS.north - GRID_BOUNDS.south),
    lon: GRID_BOUNDS.west + (left / 100) * (GRID_BOUNDS.east - GRID_BOUNDS.west)
  } }
}))

const ranking = computed(() => points.value.map((point) => ({
  ...point,
  intensity: region.value?.intensity?.[point.id]?.[store.stageKey]
})).filter((row) => Number.isFinite(row.intensity)).sort((a, b) => b.intensity - a.intensity))

const highestRisk = computed(() => {
  const row = ranking.value[0]
  if (!row) return { text: '—', detail: '等待数据', className: 'low' }
  return { text: riskText(row.riskClass), detail: `${row.short} ${row.name}`, className: row.riskClass || 'low' }
})
const pointEvents = computed(() => events.value.filter((event) => event.point === selectedPoint.value?.id).slice(0, 4))

function riskText(value) { return { high: '高风险', mid: '中风险', low: '低风险' }[value] || '风险未知' }

const trendOption = computed(() => {
  if (!selectedPoint.value || !region.value?.intensity) return null
  void theme.value
  const keys = stages.value.map((stage) => stage.key)
  const data = keys.map((key) => region.value.intensity[selectedPoint.value.id]?.[key] ?? null)
  const pal = palette()
  return {
    animation: false,
    grid: { left: 8, right: 12, top: 20, bottom: 6, containLabel: true },
    tooltip: { trigger: 'axis', ...tooltipTheme() },
    xAxis: { type: 'category', data: keys.map((key) => `T+${STAGE_DAYS[key]}`), axisLabel: axisLabelTheme(), axisLine: axisLineTheme() },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: axisLabelTheme(), splitLine: splitLineTheme() },
    series: [{ type: 'line', data, smooth: true, symbolSize: 6, lineStyle: { color: pal.accent, width: 3 }, itemStyle: { color: pal.accent }, areaStyle: { color: 'rgba(31, 222, 190, .12)' } }]
  }
})
</script>

<style scoped>
.wallboard { min-height: 100vh; color: #dffbff; background: radial-gradient(circle at 50% 32%, rgba(10, 86, 105, .22), transparent 38%), #030c18; overflow: hidden; }
.wb-head { height: 88px; display: grid; grid-template-columns: 280px 1fr 410px; align-items: center; padding: 0 24px; border-bottom: 1px solid rgba(58, 220, 234, .22); background: linear-gradient(180deg, rgba(5, 27, 45, .98), rgba(3, 15, 27, .9)); }
.wb-title { text-align: center; }
.wb-title p, .wb-panel-title p { margin: 0 0 3px; color: #52d9e7; font: 600 10px/1.2 var(--font-mono); letter-spacing: .18em; }
.wb-title h1 { margin: 0; font-size: clamp(22px, 1.7vw, 32px); letter-spacing: .16em; text-shadow: 0 0 22px rgba(41, 219, 232, .28); }
.wb-back { justify-self: start; display: inline-flex; gap: 8px; align-items: center; min-height: 44px; padding: 0 14px; border: 1px solid rgba(73, 202, 219, .3); border-radius: 8px; color: #a9dce4; text-decoration: none; }
.wb-back:hover { border-color: #4ee1e9; color: #fff; }
.wb-identity { justify-self: end; display: grid; grid-template-columns: auto auto; gap: 5px 12px; text-align: right; font: 11px/1.2 var(--font-mono); color: #87b9c4; }
.wb-identity strong { color: #35e2bc; letter-spacing: .12em; }.wb-identity b { color: #ffcf6b; }
.wb-layout { height: calc(100vh - 218px); min-height: 620px; display: grid; grid-template-columns: minmax(280px, 17vw) minmax(560px, 1fr) minmax(300px, 19vw); gap: 12px; padding: 12px 16px; }
.wb-left, .wb-right { min-height: 0; display: grid; gap: 10px; }
.wb-left { grid-template-rows: auto minmax(210px, 1fr) 205px; }.wb-right { grid-template-rows: auto auto minmax(150px, 1fr) auto; }
.wb-panel { min-height: 0; padding: 13px; border: 1px solid rgba(44, 183, 205, .2); border-radius: 8px; background: linear-gradient(145deg, rgba(8, 31, 48, .94), rgba(5, 19, 33, .92)); box-shadow: inset 0 1px rgba(115, 232, 240, .04); overflow: hidden; }
.wb-panel-title { display: flex; align-items: end; justify-content: space-between; gap: 8px; padding-bottom: 9px; margin-bottom: 10px; border-bottom: 1px solid rgba(69, 198, 215, .14); }
.wb-panel-title h2 { margin: 0; font-size: 15px; }.wb-panel-title > span { color: #719ca7; font: 10px/1.2 var(--font-mono); }
.wb-kpis { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }.wb-kpis article { padding: 9px; border: 1px solid rgba(68, 179, 200, .13); background: rgba(7, 39, 55, .52); }.wb-kpis span, .wb-kpis small { display: block; color: #7da9b3; font-size: 10px; }.wb-kpis strong { display: block; margin: 5px 0 2px; color: #e6fcff; font: 700 20px/1 var(--font-mono); }
.risk-high { color: #ff6978 !important; }.risk-mid { color: #ffc35f !important; }.risk-low { color: #42e0b5 !important; }
.wb-rank-list, .wb-factors ul, .wb-events ul { padding: 0; margin: 0; list-style: none; }.wb-rank-list { display: grid; gap: 5px; }.wb-rank-list button { width: 100%; min-height: 42px; display: grid; grid-template-columns: 25px 1fr 50px 30px; align-items: center; gap: 7px; padding: 5px 7px; border: 1px solid transparent; border-radius: 5px; color: #aacbd2; background: rgba(14, 49, 63, .48); text-align: left; cursor: pointer; }.wb-rank-list button:hover, .wb-rank-list button[aria-current="true"] { border-color: rgba(55, 220, 226, .46); background: rgba(15, 76, 88, .56); }.rank-index { color: #577e88; font: 11px var(--font-mono); }.rank-name { display: flex; flex-direction: column; min-width: 0; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.rank-name b { color: #e1f9fc; font: 600 11px var(--font-mono); }.rank-risk { font-size: 10px; }.wb-rank-list button > strong { text-align: right; color: #eafcff; font: 700 15px var(--font-mono); }
.wb-center { position: relative; min-width: 0; min-height: 0; border: 1px solid rgba(48, 211, 226, .25); border-radius: 10px; background: #071727; overflow: hidden; }.wb-map-caption { position: absolute; z-index: 500; top: 16px; left: 18px; right: 18px; display: flex; justify-content: space-between; pointer-events: none; }.wb-map-caption > div { padding: 9px 12px; border: 1px solid rgba(78, 222, 231, .26); border-radius: 7px; background: rgba(3, 20, 31, .82); backdrop-filter: blur(7px); }.wb-map-caption span { color: #79adb7; font-size: 10px; }.wb-map-caption strong { display: block; margin-top: 2px; font-size: 16px; }.wb-map-tags { display: flex; align-items: center; gap: 9px; }.wb-map-tags b { color: #4ee2e7; font: 700 13px var(--font-mono); }
.wb-center :deep(.map-panel) { height: 100%; min-height: 0; padding: 0; border: 0; border-radius: 0; }.wb-center :deep(.panel-head) { display: none; }.wb-center :deep(.leaflet-map-container) { height: calc(100% - 38px) !important; min-height: 0 !important; border-radius: 0; }.wb-center :deep(.map-footer) { height: 38px; padding: 0 14px; background: rgba(3, 16, 27, .98); }
.wb-map-message { position: absolute; z-index: 600; left: 50%; bottom: 50px; transform: translateX(-50%); margin: 0; padding: 8px 12px; border: 1px solid #d39a43; background: rgba(38, 29, 12, .9); color: #ffdd98; font-size: 11px; }.wb-map-message--error { border-color: #ef5f70; color: #ffc0c7; }
.wb-zone-head { display: flex; justify-content: space-between; gap: 10px; }.wb-zone-head h2 { margin: 0 0 5px; font-size: 18px; }.wb-zone-head p { margin: 0; color: #789fa9; font-size: 10px; line-height: 1.45; }.risk-pill { align-self: start; white-space: nowrap; padding: 6px 8px; border: 1px solid currentColor; border-radius: 20px; font-size: 10px; }
.wb-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin: 12px 0 0; }.wb-metrics div { padding: 8px; background: rgba(10, 48, 63, .55); }.wb-metrics dt { color: #719ba5; font-size: 9px; }.wb-metrics dd { margin: 4px 0 0; color: #dffaff; font: 600 11px/1.25 var(--font-mono); overflow-wrap: anywhere; }
.wb-factors li { margin: 9px 0; }.wb-factors li > div { display: flex; justify-content: space-between; color: #a8cbd2; font-size: 10px; }.wb-factors li b { color: #dffcff; font: 11px var(--font-mono); }.factor-track { display: block; height: 4px; margin-top: 5px; border-radius: 4px; background: rgba(81, 139, 151, .18); }.factor-track i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #19bba8, #44dce9); }.wb-note { margin: 9px 0 0; color: #668d96; font-size: 9px; line-height: 1.45; }
.wb-events ul { display: grid; gap: 6px; }.wb-events li { display: grid; grid-template-columns: 64px 1fr 32px; gap: 7px; align-items: center; padding: 7px; background: rgba(11, 45, 59, .52); }.wb-events time { color: #71a2ac; font: 9px var(--font-mono); }.wb-events span { min-width: 0; }.wb-events b, .wb-events small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.wb-events b { color: #dff8fb; font-size: 10px; }.wb-events small { margin-top: 2px; color: #71949c; font-size: 9px; }.wb-events i { font-size: 9px; font-style: normal; }
.wb-boundary { display: grid; grid-template-columns: auto 1fr; gap: 10px; padding: 9px 11px; border: 1px solid rgba(237, 181, 81, .28); background: rgba(52, 36, 13, .28); color: #d2b775; font-size: 9px; line-height: 1.4; }.wb-boundary strong { color: #ffd479; white-space: nowrap; }
.wb-footer { height: 130px; display: grid; grid-template-columns: 240px 1fr 240px; align-items: center; gap: 14px; padding: 0 18px; border-top: 1px solid rgba(54, 210, 225, .22); background: rgba(3, 15, 27, .98); }.wb-footer :deep(.time-axis) { margin: 0; border: 0; background: transparent; }.wb-source, .wb-capability { display: flex; flex-direction: column; gap: 3px; }.wb-source span, .wb-capability span { color: #69929c; font-size: 10px; }.wb-source b { color: #37dbb8; }.wb-capability { text-align: right; }.wb-capability b { color: #53ddeb; }.wb-source small, .wb-capability small { color: #739aa3; font: 9px var(--font-mono); }.wb-state { margin: 16px 0; color: #759aa3; text-align: center; font-size: 11px; }
.wallboard :focus-visible { outline: 2px solid #56e7ef; outline-offset: 2px; }
@media (max-width: 1250px) { .wallboard { overflow: auto; }.wb-head { grid-template-columns: 180px 1fr 290px; }.wb-layout { height: auto; min-height: calc(100vh - 218px); grid-template-columns: 280px minmax(580px, 1fr); }.wb-center, .wb-center :deep(.map-panel) { height: 620px; }.wb-right { grid-column: 1 / -1; grid-template-columns: 1.2fr 1fr 1.1fr; grid-template-rows: auto auto; }.wb-boundary { grid-column: 1 / -1; }.wb-footer { position: sticky; bottom: 0; z-index: 800; } }
@media (max-width: 760px) { .wallboard { overflow: auto; }.wb-head { height: auto; min-height: 126px; grid-template-columns: auto 1fr; gap: 8px; padding: 12px; }.wb-title { grid-column: 1 / -1; grid-row: 1; }.wb-title p { display: none; }.wb-title h1 { font-size: 19px; letter-spacing: .08em; }.wb-back { grid-column: 1; grid-row: 2; }.wb-back span { display: none; }.wb-identity { grid-column: 2; grid-row: 2; font-size: 9px; }.wb-layout { display: flex; flex-direction: column; height: auto; min-height: 0; padding: 8px; }.wb-left, .wb-right { display: contents; }.wb-overview { order: 1; }.wb-center, .wb-center :deep(.map-panel) { order: 2; height: 520px; min-height: 520px; }.wb-detail { order: 3; }.wb-rank { order: 4; }.wb-trend { order: 5; }.wb-factors { order: 6; }.wb-events { order: 7; }.wb-boundary { order: 8; }.wb-footer { position: static; height: auto; min-height: 250px; grid-template-columns: 1fr; padding: 14px; }.wb-footer :deep(.time-axis) { order: -1; }.wb-source, .wb-capability { text-align: left; }.wb-map-caption { top: 10px; left: 10px; right: 10px; }.wb-map-tags { display: none !important; } }
@media (prefers-reduced-motion: reduce) { .wallboard *, .wallboard *::before, .wallboard *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
</style>
