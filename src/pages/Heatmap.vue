<template>
  <main class="page-heatmap">
    <div class="hm-body">
      <!-- ===== 标题区 ===== -->
      <header class="hm-title" aria-label="卫星遥感与时空推演标题">
        <div class="hm-title-left">
          <BackLink :to="{ path: '/cockpit' }" label="返回驾驶舱" />
          <div class="hm-title-text">
            <h1>卫星遥感与时空推演</h1>
          </div>
        </div>
      </header>

      <!-- 上一成功版本横幅：新预测未就绪时如实披露，绝不清空页面 -->
      <div
        v-if="usingPreviousVersion"
        class="hm-prev-banner"
        data-role="previous-version-banner"
        role="status"
      >
        <b>{{ predictionSnapshot.status.state === 'failed' ? '新预测生成失败' : '正在生成新预测' }}</b>
        <span>
          实测数据或模型版本已更新；当前页面继续展示上一成功预测版本（{{ predictionSnapshot.generatedAt ? `生成于 ${formatStamp(predictionSnapshot.generatedAt)}` : '时间未知' }}）。
          {{ predictionSnapshot.status.last_error ? `失败原因：${predictionSnapshot.status.last_error}` : '生成完成后自动切换。' }}
        </span>
      </div>

      <!-- ===== 主三栏 ===== -->
      <div class="hm-main">
        <!-- 左栏：预测控制 -->
        <aside class="hm-panel hm-left" aria-label="预测控制">
          <ForecastControlPanel
            v-model:mode="pageMode"
            :scope="scopeChoice"
            @update:scope="setScope"
            v-model:metric="metric"
            v-model:scale="scale"
            v-model:station-query="stationQuery"
            v-model:realtime-visible="layerRealtime"
            v-model:diff-enabled="rtDiff"
            v-model:polygon-enabled="rtPolygon"
            v-model:field-enabled="modelFieldEnabled"
            v-model:boundary-enabled="modelBoundaryEnabled"
            v-model:basemap="basemap"
            :stations="stationOptions"
            :station-id="selectedStationId"
            :info="modelInfo"
            :spatial-summary="spatialLayerSummary"
            v-model:raster-open="rasterOpen"
            @station-select="selectStation"
          />
        </aside>

        <!-- 中央：推演地图 -->
        <section class="hm-panel hm-center" aria-label="太湖推演地图">
          <div class="hm-map-tools">
            <template v-if="pageMode === 'rs'">
              <div class="hm-ab-modes" role="group" aria-label="遥感图层切换">
                <button
                  v-for="layer in rsLayers"
                  :key="layer.id"
                  type="button"
                  :aria-pressed="String(rsLayerId === layer.id)"
                  :class="{ active: rsLayerId === layer.id }"
                  @click="selectLayer(layer.id)"
                >{{ layer.name }}</button>
              </div>
              <label class="hm-ab-select">
                <span>年份 A</span>
                <select v-model.number="yearA" data-role="rs-year-a" aria-label="影像 A 年份">
                  <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
                </select>
              </label>
              <template v-if="rsCompare">
                <label class="hm-ab-select">
                  <span>年份 B</span>
                  <select v-model.number="yearB" data-role="rs-year-b" aria-label="影像 B 年份">
                    <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
                  </select>
                </label>
              </template>
              <div class="hm-ab-modes" role="group" aria-label="对比模式">
                <button
                  type="button"
                  :aria-pressed="String(!rsCompare)"
                  :class="{ active: !rsCompare }"
                  @click="rsCompare = false"
                >单年</button>
                <button
                  type="button"
                  :aria-pressed="String(rsCompare)"
                  :class="{ active: rsCompare }"
                  data-role="rs-compare-toggle"
                  @click="rsCompare = true"
                >对比模式</button>
              </div>
            </template>
            <span v-if="tileError" class="hm-map-flag hm-map-flag--warn" role="status">
              地图瓦片加载失败
              <button type="button" class="hm-inline-btn" @click="retryTiles">重试图层</button>
            </span>
          </div>

          <div class="hm-map-wrap">
            <RsMap
              ref="mapRef"
              :image-a="pageMode === 'rs' ? imageA : null"
              :image-b="pageMode === 'rs' ? imageB : null"
              :compare="pageMode === 'rs' && rsCompare"
              :badge-a="pageMode === 'rs' ? badgeA : ''"
              :badge-b="pageMode === 'rs' ? badgeB : ''"
              :points="realtimePoints"
              :points-visible="layerRealtime"
              :field-points="modelSpatialPoints"
              :field-visible="pageMode === 'forecast' && modelFieldEnabled"
              :field-boundary="modelSpatialBoundary"
              :boundary-visible="pageMode === 'forecast' && modelBoundaryEnabled"
              :hull="warningHull"
              :basemap="basemap"
              :opacity="rsOpacity"
              :active-id="pageMode === 'forecast' && scope === 'station' ? selectedStationId : ''"
              :reset-token="resetToken"
              @point-click="onPointClick"
              @tile-error="onTileError"
            />
            <div v-if="pageMode === 'rs' && rsOverlay" class="hm-map-overlay" data-role="rs-state" :data-state="rsOverlay">
              <StatePanel
                :state="rsOverlay"
                :title="rsOverlay === 'loading' ? '遥感图层加载中…' : '遥感图层加载失败'"
                :description="rsOverlay === 'error' ? rsError || '清单接口请求失败。' : ''"
              >
                <button v-if="rsOverlay === 'error'" type="button" class="hm-inline-btn" data-role="rs-retry" @click="fetchRsManifest">
                  重试
                </button>
              </StatePanel>
            </div>
            <!-- V0.3 月度栅格场浮动面板（P0-4 证据：连续栅格 + 20 μg/L 边界） -->
            <div v-if="rasterOpen" class="hm-raster-panel" data-role="raster-panel">
              <RasterLayer
                :horizon-days="selectedHorizon"
                :run-id="modelForecast?.prediction_run_id || ''"
                closable
                @close="rasterOpen = false"
              />
            </div>
          </div>

          <!-- 年份滑轴（仅遥感模式） -->
          <div v-if="pageMode === 'rs' && years.length" class="hm-rs-year">
            <span class="hm-rs-year-label">{{ activeLayerName }} · <b>{{ yearA ?? '—' }}</b></span>
            <input
              v-if="years.length > 1"
              class="hm-rs-slider"
              type="range"
              :min="0"
              :max="years.length - 1"
              step="1"
              :value="yearIndexA"
              data-role="rs-year-slider"
              aria-label="年份滑轴"
              @input="onSlideYear"
            />
            <span class="hm-rs-year-range">{{ years[0] }}—{{ years[years.length - 1] }}</span>
          </div>

          <!-- 色带图例（全期固定尺度，仅遥感模式） -->
          <div v-if="pageMode === 'rs' && activeLayer" class="hm-rs-legend" aria-label="色带图例">
            <span class="hm-rs-legend-min">{{ activeLayer.vmin }} {{ activeLayer.unit }}</span>
            <span class="hm-rs-legend-bar" :style="{ background: legendGradient }"></span>
            <span class="hm-rs-legend-max">≥ {{ activeLayer.vmax }} {{ activeLayer.unit }}</span>
          </div>

          <!-- 预测时间轴（实测回放 / 预测推演） -->
          <ForecastTimeline
            v-if="pageMode !== 'rs' && timelineStops.length"
            v-model="selectedStopId"
            :stops="timelineStops"
            :playing="ftlPlaying"
            :show-scales="pageMode === 'forecast'"
            :scales="timelineScales"
            :speed-ms="playInterval"
            :stop-values="timelineStopValues"
            data-role="forecast-timeline"
            @toggle-play="togglePlay"
            @refresh="refreshRealtime"
            @select-scale="selectScale"
            @speed-change="onSpeedChange"
          />
        </section>

        <!-- 右栏：预测结果 / 实测摘要 / 年度统计 -->
        <aside class="hm-panel hm-right" aria-label="推演结果">
        <!-- 站点预测范围标签：主视图只给「范围性质」四态，门禁细节移入结果面板评估详情 -->
        <div
          v-if="pageMode === 'forecast' && modelState === 'ok'"
          class="hm-status-tag"
          data-role="prediction-status-tag"
        >
          <RangeBadge :kind="rangeBadgeKind" :evidence="rangeBadgeEvidence" />
        </div>

          <!-- 预测推演：三标签结果面板 -->
          <ForecastResultPanel
            v-if="pageMode === 'forecast'"
            :scope="scope"
            :station-name="selectedStationName"
            :stop="selectedStop"
            :metric="metric"
            :assessment="riskAssessment"
            :station-assessment="stationAssessment"
            :station-rows="stationRows"
            :inputs="lakeInputs"
            :diff-enabled="rtDiff"
            :diff-summary="diffSummary"
            :diff-rows="stationDiffRows"
            :diff-base-time="diffBaseTimeText"
            :summary-loading="summaryState === 'loading'"
            :model-forecast="modelForecast"
            :model-state="modelState"
            :model-error="modelError"
            :v3-forecast="modelSource === 'v3' ? modelForecast : null"
            :horizon-forecasts="horizonForecasts"
            :aggregate="modelForecast?.station_aggregate || null"
            :horizon-days="selectedHorizon"
            @back-to-lake="clearStation"
            @retry="retryRealtimeSummary"
            @retry-model="retryModelForecast"
          />

          <!-- 实测回放：快照摘要 -->
          <template v-else-if="pageMode === 'replay'">
            <section class="hm-sec" aria-label="实测快照摘要" data-role="observed-panel">
              <h3 class="hm-sec-h">实测快照 <span>{{ selectedStop?.tick }} · MEE 观测</span></h3>
              <StatePanel
                v-if="!realtimeSummary && summaryState === 'loading'"
                state="loading"
                title="正在获取 MEE 实时观测…"
                description="站点点位已按监测站目录显示；观测数值就绪后自动着色。"
              />
              <template v-else-if="realtimeSummary">
                <dl class="hm-kv" data-role="observed-stats">
                  <div><dt>快照观测时间</dt><dd>{{ (realtimeSummary.latest_observed_at || '').slice(5, 16).replace('T', ' ') }}</dd></div>
                  <div><dt>活跃站点</dt><dd>{{ realtimeSummary.active_station_count ?? realtimeSummary.station_total }}</dd></div>
                  <div><dt>水质达标率（≤III 类）</dt><dd>{{ classRateText }}</dd></div>
                  <div><dt>叶绿素 a 均值</dt><dd>{{ chlaMeanText }}</dd></div>
                  <div><dt>蓝藻筛查预警</dt><dd>{{ (realtimeSummary.warnings || []).length }} 站</dd></div>
                </dl>

                <!-- 站点环比变化摘要：图层开启时给整体升降统计与变化最大的站点 -->
                <div v-if="rtDiff" class="hm-diff" data-role="diff-summary">
                  <h4 class="hm-sec-h">环比变化摘要 <span>相对上一快照 {{ diffBaseTimeText }}</span></h4>
                  <p class="hm-diff-counts" data-role="diff-counts">
                    <b class="hm-diff-up">↑ 上升 {{ diffSummary.up }} 站</b>
                    <b class="hm-diff-down">↓ 下降 {{ diffSummary.down }} 站</b>
                    <span>持平/缺测 {{ diffSummary.flat }} 站</span>
                  </p>
                  <template v-if="diffSummary.top.length">
                    <p class="hm-diff-lead">变化最大的站点（地图上红=升、绿=降）：</p>
                    <ul class="hm-diff-list" data-role="diff-top">
                      <li v-for="r in diffSummary.top" :key="r.id">
                        <i :class="r.delta > 0 ? 'hm-diff-dot--up' : 'hm-diff-dot--down'" aria-hidden="true"></i>
                        <span class="hm-diff-name">{{ r.name }}</span>
                        <span class="hm-diff-delta" :class="r.delta > 0 ? 'hm-diff-up' : 'hm-diff-down'">
                          {{ r.delta > 0 ? '+' : '' }}{{ r.delta }} μg/L
                        </span>
                      </li>
                    </ul>
                  </template>
                  <p v-else class="hm-sec-note">相邻两快照暂无可对比的叶绿素 a 报数，暂无升降可标。</p>
                </div>
                <p v-else class="hm-sec-note" data-role="diff-hint">开启左侧「站点环比变化」图层，可对比上一快照各站升降（红=升、绿=降）。</p>
              </template>
              <StatePanel
                v-else
                state="error"
                title="观测数据暂不可用"
                description="已自动重试多次仍失败；实测摘要来自 MEE 实时快照，不回退模拟。地图站点点位保持显示。"
              >
                <button type="button" class="hm-inline-btn" data-role="risk-retry" @click="retryRealtimeSummary">重试</button>
              </StatePanel>
            </section>
          </template>

          <!-- 遥感对比：年度统计 -->
          <template v-else>
            <section class="hm-sec" aria-label="年度统计">
              <h3 class="hm-sec-h">年度统计 <span>{{ activeLayerName }} · {{ yearA ?? '—' }}</span></h3>
              <StatePanel
                v-if="rsOverlay"
                :state="rsOverlay"
                :title="rsOverlay === 'loading' ? '遥感清单加载中…' : '遥感清单加载失败'"
                :description="rsOverlay === 'error' ? '年度统计依赖 /rs/manifest 清单。' : ''"
              />
              <template v-else-if="yearEntry">
                <dl class="hm-kv" data-role="rs-stats">
                  <div><dt>均值</dt><dd>{{ yearEntry.stats.mean }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>p95</dt><dd>{{ yearEntry.stats.p95 }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>最大</dt><dd>{{ yearEntry.stats.max }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>最小</dt><dd>{{ yearEntry.stats.min }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>有效像元</dt><dd>{{ yearEntry.stats.valid_pct }}%</dd></div>
                </dl>
                <p class="hm-sec-note">反演统计为全湖像元口径，不等于站点实测；用于年代际空间格局研判。</p>
              </template>
            </section>

            <section v-if="rsCompare" class="hm-sec" aria-label="年份对比摘要">
              <h3 class="hm-sec-h">对比摘要 <span>{{ yearA ?? '—' }} ↔ {{ yearB ?? '—' }}</span></h3>
              <p v-if="yearA === yearB" class="hm-empty-hint" data-role="rs-cmp-same">两个年份相同，无对比。</p>
              <template v-else-if="yearEntry && compareEntry">
                <dl class="hm-kv" data-role="rs-cmp">
                  <div><dt>均值 {{ yearA }}</dt><dd>{{ yearEntry.stats.mean }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>均值 {{ yearB }}</dt><dd>{{ compareEntry.stats.mean }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>Δ均值（B−A）</dt><dd>{{ deltaMean }} {{ activeLayer.unit }}</dd></div>
                  <div><dt>p95 {{ yearA }}</dt><dd>{{ yearEntry.stats.p95 }}</dd></div>
                  <div><dt>p95 {{ yearB }}</dt><dd>{{ compareEntry.stats.p95 }}</dd></div>
                  <div><dt>Δp95（B−A）</dt><dd>{{ deltaP95 }} {{ activeLayer.unit }}</dd></div>
                </dl>
                <p class="hm-sec-note">同尺度色标下左右分屏目视对比（拖动分割线）；此处仅列统计差，不做差值图。</p>
              </template>
            </section>
          </template>
        </aside>
      </div>
    </div>

    <!-- ===== 移动端底部操作栏 ===== -->
    <Teleport to="body" :disabled="!isMobileViewport">
      <nav class="hm-mobile-bar" aria-label="移动端操作栏">
        <RouterLink class="hm-mb-btn" :to="{ path: '/cockpit' }">返回驾驶舱</RouterLink>
        <button ref="drawerTriggerRef" type="button" class="hm-mb-btn" data-role="layers-trigger" @click="openDrawer">预测控制</button>
      </nav>
    </Teleport>

    <!-- ===== 移动端预测控制抽屉 ===== -->
    <Teleport to="body">
      <div v-if="drawerOpen" class="hm-drawer-mask" @click.self="closeDrawer">
        <div
          ref="drawerRef"
          class="hm-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="预测控制"
          @keydown="onDrawerKeydown"
        >
          <header class="hm-drawer-head">
            <h3>预测控制</h3>
            <button ref="drawerCloseRef" type="button" class="hm-drawer-close" data-role="drawer-close" aria-label="关闭预测控制" @click="closeDrawer">关闭</button>
          </header>
          <div class="hm-drawer-body">
            <ForecastControlPanel
              compact
              v-model:mode="pageMode"
              :scope="scopeChoice"
              @update:scope="setScope"
              v-model:metric="metric"
              v-model:scale="scale"
              v-model:station-query="stationQuery"
              v-model:realtime-visible="layerRealtime"
              v-model:diff-enabled="rtDiff"
              v-model:polygon-enabled="rtPolygon"
              v-model:basemap="basemap"
              :stations="stationOptions"
              :station-id="selectedStationId"
              :info="modelInfo"
              @station-select="selectStation"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getAlgorithmModelStatusEnvelope,
  getPredictionStationFieldEnvelope,
  getAlgorithmV3StatusEnvelope,
  getRsManifestEnvelope,
  rsImageUrl
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import StatePanel from '../components/common/StatePanel.vue'
import RsMap from '../components/heatmap/RsMap.vue'
import RasterLayer from '../components/heatmap/RasterLayer.vue'
import ForecastControlPanel from '../components/heatmap/ForecastControlPanel.vue'
import ForecastResultPanel from '../components/heatmap/ForecastResultPanel.vue'
import ForecastTimeline from '../components/heatmap/ForecastTimeline.vue'
import RangeBadge from '../components/heatmap/RangeBadge.vue'
import { chlaColor, fetchRealtimeStations, fetchRealtimeSummary, fetchRealtimeTimeline, fetchStationObservations, fmtMeasure, formatStamp, stationMapPoints } from '../services/realtime.js'
import { currentHorizonData, entityDiagnostic, focusResult, intervalState, loadPredictionSnapshot, predictionSnapshot, refreshPredictionStatus } from '../stores/predictionSnapshot.js'
import { assessShortTerm, assessMidTerm, assessLongTerm, assessStationFactors } from '../components/heatmap/riskAssessment.js'

const route = useRoute()
const router = useRouter()

// ---------- 卫星遥感图层（/rs/manifest + 静态 PNG） ----------
const rsManifest = ref(null)
const rsState = ref('loading')
const rsError = ref('')
const rsLayerId = ref('chla')
const rsCompare = ref(false)
const yearA = ref(null)
const yearB = ref(null)
const rsOpacity = ref(0.85)

const rsLayers = computed(() => rsManifest.value?.layers || [])
const activeLayer = computed(() => rsLayers.value.find((l) => l.id === rsLayerId.value) || null)
const activeLayerName = computed(() => activeLayer.value?.name || '')
const years = computed(() => (activeLayer.value ? activeLayer.value.years.map((y) => y.year) : []))

const yearEntry = computed(() =>
  activeLayer.value && yearA.value != null
    ? activeLayer.value.years.find((y) => y.year === yearA.value) || null
    : null
)
const compareEntry = computed(() =>
  activeLayer.value && yearB.value != null
    ? activeLayer.value.years.find((y) => y.year === yearB.value) || null
    : null
)

const deltaMean = computed(() => {
  if (!yearEntry.value || !compareEntry.value) return '—'
  const d = compareEntry.value.stats.mean - yearEntry.value.stats.mean
  return `${d > 0 ? '+' : ''}${d.toFixed(2)}`
})
const deltaP95 = computed(() => {
  if (!yearEntry.value || !compareEntry.value) return '—'
  const d = compareEntry.value.stats.p95 - yearEntry.value.stats.p95
  return `${d > 0 ? '+' : ''}${d.toFixed(2)}`
})

const yearIndexA = computed(() => {
  const at = years.value.indexOf(yearA.value)
  return at < 0 ? years.value.length - 1 : at
})
function onSlideYear(event) {
  const year = years.value[Number(event.target.value)]
  if (year != null) yearA.value = year
}

const imageA = computed(() => {
  const entry = yearEntry.value
  return entry ? { url: rsImageUrl(entry.png), bounds: entry.bounds } : null
})
const imageB = computed(() => {
  const entry = compareEntry.value
  return entry ? { url: rsImageUrl(entry.png), bounds: entry.bounds } : null
})
const badgeA = computed(() => (yearA.value != null ? `A · ${yearA.value}` : 'A'))
const badgeB = computed(() => (yearB.value != null ? `B · ${yearB.value}` : 'B'))

const legendGradient = computed(() => {
  const stops = activeLayer.value?.legend_stops || []
  if (!stops.length) return 'none'
  return `linear-gradient(to right, ${stops.map(([t, c]) => `${c} ${Math.round(t * 100)}%`).join(', ')})`
})

const rsOverlay = computed(() => (rsState.value === 'loading' ? 'loading' : rsState.value === 'error' ? 'error' : null))

function selectLayer(id) {
  if (id === rsLayerId.value) return
  rsLayerId.value = id
  const layer = rsLayers.value.find((l) => l.id === id)
  if (layer) {
    yearA.value = layer.years[layer.years.length - 1].year
    yearB.value = layer.years[Math.max(0, layer.years.length - 6)].year
  }
}

async function fetchRsManifest() {
  rsState.value = 'loading'
  rsError.value = ''
  try {
    const { data } = await getRsManifestEnvelope()
    rsManifest.value = data
    rsState.value = 'ok'
    const layer = data.layers.find((l) => l.id === rsLayerId.value) || data.layers[0]
    if (layer) {
      rsLayerId.value = layer.id
      if (!layer.years.some((y) => y.year === yearA.value)) {
        yearA.value = layer.years[layer.years.length - 1].year
      }
      if (!layer.years.some((y) => y.year === yearB.value)) {
        yearB.value = layer.years[Math.max(0, layer.years.length - 6)].year
      }
    }
  } catch (err) {
    rsManifest.value = null
    rsState.value = 'error'
    rsError.value = err && err.message ? err.message : '遥感清单请求失败'
  }
}

// ---------- 地图图层状态 ----------
const mapRef = ref(null)
const layerRealtime = ref(true)
const realtimeSummary = ref(null)
// 拓展图层（observed 真实数据）：历史快照 / 站点环比变化 / 预警范围凸包
const rtSnapshotId = ref('')
const rtDiff = ref(false)
const rtPolygon = ref(false)
const modelFieldEnabled = ref(true)
const modelBoundaryEnabled = ref(false)
const rtTimeline = ref([])
const prevSummary = ref(null)
const basemap = ref('satellite')
const tileError = ref(false)
const resetToken = ref(0)
let realtimeRefreshTimer = null

function onTileError(v) {
  tileError.value = v
}
function retryTiles() {
  mapRef.value && mapRef.value.retryTiles && mapRef.value.retryTiles()
}

function fetchSummaryFor(snapshotId) {
  return fetchRealtimeSummary({ snapshotId: snapshotId || undefined })
}

// 观测汇总加载：失败自动重试（5s × 5 次）；重试期间地图用站点目录灰点兜底，
// 右栏显示“正在获取”，全部失败才进入错误态。
const summaryState = ref('loading') // loading | ok | error
let summaryAttempt = 0
let summaryRetryTimer = null

function loadSummary(snapshotId) {
  summaryState.value = 'loading'
  fetchSummaryFor(snapshotId)
    .then((s) => {
      realtimeSummary.value = s
      summaryState.value = 'ok'
      summaryAttempt = 0
      if (summaryRetryTimer) {
        clearTimeout(summaryRetryTimer)
        summaryRetryTimer = null
      }
    })
    .catch(() => {
      realtimeSummary.value = null
      if (summaryAttempt < 5) {
        summaryAttempt += 1
        if (summaryRetryTimer) clearTimeout(summaryRetryTimer)
        summaryRetryTimer = setTimeout(() => loadSummary(rtSnapshotId.value || ''), 5000)
      } else {
        summaryState.value = 'error'
      }
    })
}

function retryRealtimeSummary() {
  summaryAttempt = 0
  if (summaryRetryTimer) {
    clearTimeout(summaryRetryTimer)
    summaryRetryTimer = null
  }
  loadSummary(rtSnapshotId.value || '')
}

function refreshRealtime() {
  fetchRealtimeTimeline({ force: true }).then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => {})
  // 定时静默刷新：失败保留现有数据，不打断页面
  fetchSummaryFor(rtSnapshotId.value)
    .then((s) => {
      realtimeSummary.value = s
      summaryState.value = 'ok'
      summaryAttempt = 0
    })
    .catch(() => {})
  // 预测结果不再随实时刷新重跑：只比对轻量状态接口里的快照 ID，
  // 实测数据或模型版本真的变了才静默替换（见 predictionSnapshot store）。
  refreshPredictionStatus()
    .then((replaced) => {
      if (replaced) {
        applySnapshotHorizon()
        loadHorizonEvidence()
      }
    })
    .catch(() => {})
}

// ---------- 页面模式：实测回放 / 预测推演（主视图） / 遥感年度对比 ----------
// URL 恢复：mode / scale / metric / station / stop
const VALID_MODES = ['replay', 'forecast', 'rs']
const VALID_SCALES = ['short', 'mid', 'long']
const VALID_METRICS = ['risk', 'chla', 'area', 'biomass']

const pageMode = ref('forecast')
const scale = ref('short')
const metric = ref('risk')
const selectedStationId = ref('')
const stationQuery = ref('')
// 左侧空间范围选择（监测站按钮展开选择器；实际站点视图由选中站点驱动）
const scopeChoice = ref('lake')
const scope = computed(() => (selectedStationId.value ? 'station' : 'lake'))

function setScope(v) {
  scopeChoice.value = v === 'station' ? 'station' : 'lake'
  if (v !== 'station') selectedStationId.value = ''
}

// ---------- URL 状态同步（刷新 / 深链 / 前进后退 / 手工改 hash 都生效） ----------
// 两个方向：
//   URL → 页面态：applyQuery() 在任何 hash 变化（含浏览器前进后退、手工编辑地址栏、
//                 站外深链）时把查询参数写回页面态；
//   页面态 → URL：选择变化时写回查询参数。仅「选择身份」(mode/scale/metric/station)
//                 变化才 push（这样前进后退可以在站点之间走），只换停靠点时 replace
//                 （避免时间轴播放把历史记录刷爆）。
// routeSyncGuard 用于阻断回环：URL → 态 的同步过程中不得再触发 态 → URL 的回写。
const SELECTION_KEYS = ['mode', 'scale', 'metric', 'station']
let routeSyncGuard = false

function selectionSignature(q) {
  return SELECTION_KEYS.map((key) => `${key}=${(q && q[key]) ?? ''}`).join('&')
}

function querySignature(q) {
  return [...SELECTION_KEYS, 'stop'].map((key) => `${key}=${(q && q[key]) ?? ''}`).join('&')
}

function applyQuery(q) {
  routeSyncGuard = true
  try {
    if (VALID_MODES.includes(q.mode)) pageMode.value = q.mode
    if (VALID_SCALES.includes(q.scale)) scale.value = q.scale
    if (VALID_METRICS.includes(q.metric)) metric.value = q.metric
    if (typeof q.station === 'string' && q.station) {
      selectedStationId.value = q.station
      scopeChoice.value = 'station'
    } else if (selectedStationId.value) {
      // 深链/后退到不含 station 的地址：必须回到全湖，否则 URL 与视图不一致
      selectedStationId.value = ''
      scopeChoice.value = 'lake'
    }
    if (typeof q.stop === 'string' && q.stop) {
      // 停靠点尚未构建时先挂起，由 timelineStops watcher 落地
      if (timelineStops.value.some((s) => s.id === q.stop)) selectedStopId.value = q.stop
      else pendingStopId.value = q.stop
    } else {
      pendingStopId.value = ''
    }
  } finally {
    nextTick(() => {
      routeSyncGuard = false
    })
  }
}
const pendingStopId = ref('')

watch(
  () => route.fullPath,
  () => {
    if (routeSyncGuard) return
    if (querySignature(route.query) === querySignature(currentQuery())) return
    applyQuery(route.query)
  }
)

// 模式切换（左侧面板 v-model）：停止回放；当前停靠点在新模式不存在时
// 由 timelineStops watcher 兜底重选
watch(pageMode, () => stopPlay())

// ---------- 站点目录（左侧搜索 + 站点视图名称） ----------
const stationCatalog = ref([])
const stationOptions = computed(() =>
  stationCatalog.value.map((s) => ({ id: s.id, name: s.source_station_name }))
)
const selectedStationName = computed(() => {
  const found = stationCatalog.value.find((s) => s.id === selectedStationId.value)
  return found ? found.source_station_name : selectedStationId.value
})

function selectStation(id) {
  if (!id || id === selectedStationId.value) return
  selectedStationId.value = id
  scopeChoice.value = 'station'
  stopPlay()
}

function clearStation() {
  selectedStationId.value = ''
  scopeChoice.value = 'lake'
}

function onPointClick(id) {
  // 站点视图仅预测推演模式提供；回放/遥感点击不改变分析对象
  if (pageMode.value !== 'forecast') return
  selectStation(id)
}

// 站点视图数据：最新观测行（驱动因素/总览的站点输入）
const stationRows = ref([])
let stationRowsToken = 0
watch(selectedStationId, async (id) => {
  const token = ++stationRowsToken
  stationRows.value = []
  if (!id) return
  try {
    const rows = await fetchStationObservations(id, { window: 'latest' })
    if (token === stationRowsToken) stationRows.value = rows
  } catch {
    if (token === stationRowsToken) stationRows.value = []
  }
}, { immediate: true })

// ---------- 预测时间轴 ----------
// 实测段：/realtime/timeline 快照按日去重（每日取最后一帧）→ 今日；
// 预测段：短临/趋势/中长期三个尺度档下的具体时刻（T+1…T+90），
// 相邻时刻共享该档位的规则研判结论（透明规则，非逐日数值预报）。
const SCALES = [
  { id: 'short', label: '短临', hint: '1-3 天', from: 1, to: 3, days: [1, 3], pos: { 1: 48, 3: 57 } },
  { id: 'mid', label: '趋势', hint: '7-15 天', from: 7, to: 15, days: [7, 15], pos: { 7: 64, 15: 74 } },
  { id: 'long', label: '中长期', hint: '月度 30/60/90 天', from: 30, to: 90, days: [30, 60, 90], pos: { 30: 80, 60: 87, 90: 94 } }
]
const TODAY_POS = 42

function pad2(n) {
  return String(n).padStart(2, '0')
}
function fmtMD(date) {
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}
function shiftDate(baseStr, days) {
  return new Date(Number(baseStr.slice(0, 4)), Number(baseStr.slice(5, 7)) - 1, Number(baseStr.slice(8, 10)) + days)
}

const observedStops = computed(() => {
  const snaps = rtTimeline.value || []
  const byDate = new Map()
  snaps.forEach((s) => {
    const d = String(s.latest_observed_at || '').slice(0, 10)
    if (!d) return
    const prev = byDate.get(d)
    if (!prev || String(s.latest_observed_at) > String(prev.latest_observed_at)) byDate.set(d, s)
  })
  const dates = [...byDate.keys()].sort()
  const stops = []
  dates.forEach((d, i) => {
    const isLast = i === dates.length - 1
    const snap = byDate.get(d)
    const nowDate = new Date()
    const isToday = d === `${nowDate.getFullYear()}-${pad2(nowDate.getMonth() + 1)}-${pad2(nowDate.getDate())}`
    stops.push({
      id: `d-${d}`,
      kind: isLast ? 'today' : 'observed',
      pos: dates.length === 1 ? TODAY_POS : 3 + (i / (dates.length - 1)) * (TODAY_POS - 3),
      // 刻度文案保持短小，避免与未来段 T+n 刻度交叠；完整日期见悬停/右栏
      tick: isLast && isToday ? '今日' : d.slice(5),
      title: isLast ? `${d.slice(5)} · ${isToday ? '今日' : '最新'}` : d.slice(5),
      snapshotId: snap.snapshot_id,
      // 时间轴下方数值分布条的真实观测输入（缺测为 null，不造值）
      chlaMean: snap.chla_mean != null ? Number(snap.chla_mean) : null
    })
  })
  return stops
})

const anchorDate = computed(() => {
  const stops = observedStops.value
  if (!stops.length) return ''
  return stops[stops.length - 1].id.replace(/^d-/, '')
})

const timelineStops = computed(() => {
  const stops = observedStops.value.slice()
  if (pageMode.value !== 'forecast') return stops
  const anchor = anchorDate.value
  if (!anchor) return stops
  SCALES.forEach((sc) => {
    sc.days.forEach((n) => {
      const date = shiftDate(anchor, n)
      stops.push({
        id: `t${n}`,
        kind: sc.id,
        scale: sc.id,
        pos: sc.pos[n],
        // 刻度只标 +n；完整 “T+n · 尺度 · 预测日期” 见右侧状态与结果面板
        tick: `+${n}`,
        title: `未来 T+${n} · ${sc.label}`,
        sub: `预测 ${fmtMD(date)} · ${sc.label}`
      })
    })
  })
  return stops
})

const timelineScales = computed(() =>
  SCALES.map((sc) => ({ id: sc.id, label: sc.label, hint: sc.hint, first: `t${sc.days[0]}`, last: `t${sc.days[sc.days.length - 1]}` }))
)

// 时间轴数值分布条（kepler.gl 式）：每个停靠点一根细条，高度=该时刻真实数值的相对高低。
// 观测段用快照 chla 均值；未来段用同一份预测快照的全湖聚合中位数（station_aggregate）。
// 指标映射：risk→probability、chla→chla、biomass→biomass；area 无聚合口径→无值。
// 观测段只有叶绿素 a 有真实观测均值，其余指标不与预测值混标；缺值停靠点不出条，
// 整条无值时组件自动隐藏，绝不造占位值。
const AGGREGATE_KEY_BY_METRIC = { risk: 'probability', chla: 'chla', biomass: 'biomass' }
const timelineStopValues = computed(() => {
  if (pageMode.value === 'rs') return []
  const aggKey = AGGREGATE_KEY_BY_METRIC[metric.value] || ''
  const rows = []
  timelineStops.value.forEach((stop) => {
    if (stop.kind === 'observed' || stop.kind === 'today') {
      if (aggKey === 'chla' && stop.chlaMean != null) rows.push({ id: stop.id, value: stop.chlaMean })
      return
    }
    const m = String(stop.id || '').match(/^t(\d+)$/)
    if (!m || !aggKey) return
    const stats = predictionSnapshot.horizons?.[m[1]]?.station_aggregate?.metrics?.[aggKey]
    if (stats && stats.median != null) rows.push({ id: stop.id, value: Number(stats.median) })
  })
  return rows
})

const selectedStopId = ref('')
const selectedStop = computed(() => timelineStops.value.find((s) => s.id === selectedStopId.value) || null)
const selectedStopIsFuture = computed(() => ['short', 'mid', 'long'].includes(selectedStop.value?.kind))
const selectedHorizon = computed(() => {
  const match = String(selectedStopId.value || '').match(/^t(1|3|7|15|30|60|90)$/)
  return match ? Number(match[1]) : 1
})

// ---------- 算法模型链路：V0.3 真实数据包为主，V0.2 合成包 legacy 回退 ----------
const modelForecast = ref(null)
const modelStatus = ref(null)
const modelStatusV3 = ref(null)
// v3 = 真实数据包主链路；v0_2_legacy_fallback = V0.3 不可用时的对照回退
const modelSource = ref('v3')
const modelState = ref('loading')
const modelError = ref('')
const spatialField = ref(null)
const spatialState = ref('loading')
const rasterOpen = ref(false)
const horizonForecasts = ref([])
let modelRequestToken = 0
let spatialRequestToken = 0
let horizonRequestToken = 0
let horizonEvidenceKey = ''

// 预测结果来自全局仓库：一次读取快照覆盖全部时效，切换时效只在内存中切换。
// 只有实测数据/模型版本变化（prediction_snapshot_id 改变）才由后端重新推理。
function applySnapshotHorizon() {
  const data = currentHorizonData(selectedHorizon.value)
  if (data) {
    modelForecast.value = data
    modelSource.value = 'v3'
    modelState.value = 'ok'
    modelError.value = ''
  } else {
    modelForecast.value = null
    modelState.value = 'error'
    modelError.value = '预测快照未覆盖当前时效'
  }
}

// 审计合同：读取接口不存在任何回落推理路径。快照未就绪时进入 pending 态，
// 由短周期重试 + prediction-status 轮询在快照就绪后自动恢复。
let pendingRetryTimer = null
function clearPendingRetry() {
  if (pendingRetryTimer) {
    clearTimeout(pendingRetryTimer)
    pendingRetryTimer = null
  }
}

async function loadModelForecast() {
  if (pageMode.value !== 'forecast') return
  const token = ++modelRequestToken
  const entityId = selectedStationId.value || 'lake'
  clearPendingRetry()
  // 已有结果时切换指标不闪回 loading，避免整页重新等待。
  if (modelState.value !== 'ok') modelState.value = 'loading'
  modelError.value = ''
  try {
    await loadPredictionSnapshot(entityId, metric.value)
    if (token !== modelRequestToken) return
    applySnapshotHorizon()
    loadHorizonEvidence()
  } catch (err) {
    // 快照未就绪（409 PREDICTION_SNAPSHOT_NOT_READY）→ 诚实等待；其余→错误态。
    if (token !== modelRequestToken) return
    modelForecast.value = null
    const pending = err?.code === 'PREDICTION_SNAPSHOT_NOT_READY'
    modelState.value = pending ? 'pending' : 'error'
    modelError.value = err?.message || '预测快照未就绪'
    if (pending) {
      pendingRetryTimer = setTimeout(() => {
        if (token === modelRequestToken) loadModelForecast()
      }, 10000)
    }
  }
}

function retryModelForecast() {
  loadModelForecast()
  loadSpatialField()
}

async function loadSpatialField() {
  if (pageMode.value !== 'forecast') return
  const token = ++spatialRequestToken
  // 水华面积是全湖遥感反演口径，不存在站点空间场；不发请求也不报错。
  if (metric.value === 'area') {
    spatialField.value = null
    spatialState.value = 'ok'
    return
  }
  spatialState.value = 'loading'
  try {
    // 站点场直接来自预测快照：与右侧结果面板同一 prediction_snapshot_id，
    // 覆盖分母统一为快照站点层总数（动态：目录站-当轮缺测站），缺坐标站逐站给出排除原因。
    const { data } = await getPredictionStationFieldEnvelope(selectedHorizon.value, metric.value)
    if (token !== spatialRequestToken) return
    spatialField.value = data
    spatialState.value = 'ok'
  } catch {
    if (token !== spatialRequestToken) return
    spatialField.value = null
    spatialState.value = 'error'
  }
}

// 七个时效的结果本来就装在同一份预测快照里：直接按序取用，
// 既不逐个请求接口（原实现串行请求 7 次、合计约 28s），也不产生任何模型运行。
function loadHorizonEvidence() {
  if (pageMode.value !== 'forecast') return
  const entityId = selectedStationId.value || 'lake'
  horizonEvidenceKey = `${entityId}|${metric.value}`
  horizonForecasts.value = predictionSnapshot.horizonList
    .map((horizon) => predictionSnapshot.horizons[String(horizon)])
    .filter(Boolean)
}

// 站点/指标/模式变化才需要重新读取快照（服务端命中预生成结果，不运行模型）。
watch([pageMode, selectedStationId, metric], async () => {
  // 先取预测主响应，再以其 prediction_run_id 请求空间场，保证两端共享同一次运行 ID
  await loadModelForecast()
  loadSpatialField()
})

// 时效切换：七个时效的结果已在同一份快照内，纯内存切换，不产生请求。
watch(selectedHorizon, () => {
  if (pageMode.value !== 'forecast') return
  applySnapshotHorizon()
  loadSpatialField()
})

function firstStopOfScale(scaleId) {
  return timelineStops.value.find((s) => s.scale === scaleId) || null
}

function selectScale(scaleId) {
  if (!VALID_SCALES.includes(scaleId)) return
  scale.value = scaleId
  const target = firstStopOfScale(scaleId)
  if (target) selectedStopId.value = target.id
}

watch(timelineStops, (stops) => {
  if (!stops.length) return
  const exists = stops.some((s) => s.id === selectedStopId.value)
  if (exists) return
  if (pendingStopId.value && stops.some((s) => s.id === pendingStopId.value)) {
    selectedStopId.value = pendingStopId.value
    pendingStopId.value = ''
    return
  }
  if (pageMode.value === 'forecast') {
    const target = firstStopOfScale(scale.value)
    if (target) {
      selectedStopId.value = target.id
      return
    }
  }
  const lastObserved = [...stops].reverse().find((s) => s.kind === 'today' || s.kind === 'observed')
  selectedStopId.value = (lastObserved || stops[0]).id
}, { immediate: true })

// 左侧时间尺度切换：预测模式下跳到该档首个时刻
watch(scale, (sc) => {
  if (pageMode.value !== 'forecast') return
  const target = firstStopOfScale(sc)
  if (target && selectedStopId.value !== target.id) selectedStopId.value = target.id
})

// 选中停靠点 → 驱动观测快照（地图点位/右栏摘要随之更新）；未来时刻保持最新实测底图
watch([selectedStopId, pageMode], () => {
  const stop = selectedStop.value
  if (!stop || pageMode.value !== 'replay') {
    if (pageMode.value === 'forecast') {
      // 预测模式下地图点位保持最新实测快照
      if (rtSnapshotId.value !== '') rtSnapshotId.value = ''
    }
    return
  }
  const target = stop.snapshotId || ''
  if (rtSnapshotId.value !== target) rtSnapshotId.value = target
}, { immediate: true })

// ---------- URL 状态同步（刷新后恢复分析位置） ----------
function currentQuery() {
  const query = {
    mode: pageMode.value,
    scale: scale.value,
    metric: metric.value
  }
  if (selectedStationId.value) query.station = selectedStationId.value
  if (selectedStopId.value && pageMode.value !== 'rs') query.stop = selectedStopId.value
  return query
}

watch([pageMode, scale, metric, selectedStationId, selectedStopId], () => {
  if (routeSyncGuard) return
  const query = currentQuery()
  if (querySignature(query) === querySignature(route.query)) return
  // 选择身份变化 → push（前进后退可回到上一个站点/指标）；仅换停靠点 → replace
  const selectionChanged = selectionSignature(query) !== selectionSignature(route.query)
  const navigate = selectionChanged ? router.push : router.replace
  navigate.call(router, { query }).catch(() => {})
})

// 播放：沿停靠点推进，到末端自动停；速度档由时间轴组件回传（0.5×=3600ms … 4×=450ms）
const ftlPlaying = ref(false)
const playInterval = ref(1800)
let ftlTimer = null
function stepPlay() {
  const stops = timelineStops.value
  const at = stops.findIndex((s) => s.id === selectedStopId.value)
  if (at < 0 || at >= stops.length - 1) {
    stopPlay()
    return
  }
  selectedStopId.value = stops[at + 1].id
}
function onSpeedChange(ms) {
  const next = Number(ms)
  if (!Number.isFinite(next) || next <= 0) return
  playInterval.value = next
  if (ftlPlaying.value) {
    if (ftlTimer) clearInterval(ftlTimer)
    ftlTimer = setInterval(stepPlay, playInterval.value)
  }
}
function togglePlay() {
  if (ftlPlaying.value) {
    stopPlay()
    return
  }
  if (timelineStops.value.length < 2) return
  ftlPlaying.value = true
  ftlTimer = setInterval(stepPlay, playInterval.value)
}
function stopPlay() {
  ftlPlaying.value = false
  if (ftlTimer) {
    clearInterval(ftlTimer)
    ftlTimer = null
  }
}

// ---------- 水华风险研判（临时规则，见 riskAssessment.js）——由时间轴选中档位驱动 ----------
const riskAssessment = computed(() => {
  if (!realtimeSummary.value || pageMode.value !== 'forecast') return null
  const kind = selectedStop.value?.kind
  if (kind === 'mid') return assessMidTerm(realtimeSummary.value)
  if (kind === 'long') return assessLongTerm(realtimeSummary.value, rsManifest.value)
  if (kind === 'short') return assessShortTerm(realtimeSummary.value)
  // 选中实测停靠点时也给出短临研判，避免站点/总览空窗
  return assessShortTerm(realtimeSummary.value)
})

// 站点级规则研判（站点最新实测逐项计分，透明阈值）
const stationAssessment = computed(() => {
  if (scope.value !== 'station' || !stationRows.value.length) return null
  return assessStationFactors(stationRows.value)
})

// 全湖指标输入文本（结果总览使用）
const lakeInputs = computed(() => {
  const s = realtimeSummary.value
  const chla = s?.means?.chlorophyll_a?.value
  const temp = s?.means?.water_temperature?.value
  const tp = s?.means?.total_phosphorus?.value
  const tn = s?.means?.total_nitrogen?.value
  const trend = s?.trends?.chlorophyll_a
  const trendText = trend?.direction === 'up'
    ? `↑ +${trend.delta_pct}%`
    : trend?.direction === 'down' ? `↓ ${trend.delta_pct}%` : ''
  return {
    chlaText: chla != null ? `${fmtMeasure(chla)} μg/L` : '—',
    chlaValue: chla != null ? Number(chla) : null,
    chlaTrend: trendText,
    tempText: temp != null ? `${fmtMeasure(temp)} ℃` : '—',
    nutrientText: tp != null ? `${fmtMeasure(tp)} / ${tn != null ? fmtMeasure(tn) : '—'} mg/L` : '—'
  }
})

// 模型与运行信息（左侧控制面板底部）
// 上一成功版本横幅：新预测未就绪（更新中/失败）时页面必须如实披露，绝不清空
const usingPreviousVersion = computed(() =>
  Boolean(predictionSnapshot.predictionSnapshotId) && Boolean(predictionSnapshot.status?.using_previous_success)
)
const modelInfo = computed(() => ({
  runStatus: modelState.value === 'ok'
    ? (modelSource.value === 'v3' ? 'V0.3 真实数据模型已接入 · 推演' : 'V0.2 legacy 对照 · 情景推演')
    : '模型状态检查中',
  modelVersion: modelStatusV3.value?.status === 'ready'
    ? `算法交付包 V0.3（真实数据 · ${modelStatusV3.value.model_count} 模型）`
    : (modelStatus.value?.status === 'ready' ? '算法交付包 V0.2（63 模型）' : '算法交付包 V0.2'),
  issuedAt: modelForecast.value?.issued_at ? formatStamp(modelForecast.value.issued_at) : '—',
  dataTime: modelForecast.value?.scope?.observed_at ? formatStamp(modelForecast.value.scope.observed_at) : '—'
}))

// ---------- 站点预测范围标签（范围性质四态） ----------
// 主视图只给「范围性质」：预测/参考/情景/暂无，按后端区间证据判定；
// 门禁（融合增益 10%）细节不在主视图出现，由结果面板的评估详情承载。
const focusDiagnostic = computed(() => entityDiagnostic(selectedHorizon.value))
// 焦点任务结果框与区间状态：intervalState 把后端「结构自洽 / 校准证据 / 决策可用」
// 三层结论翻译成页面口径（见 stores/predictionSnapshot.js）。
const focusResultBox = computed(() => focusResult(selectedHorizon.value))
const focusInterval = computed(() => intervalState(focusResultBox.value))

// risk 指标的等级范围由源区间（叶绿素 a 预测区间）映射到冻结风险带得到；源区间未达
// 决策可用时后端不给等级范围、只给 band_range_blocked（取数路径与
// ForecastResultPanel 的 bandRangeBlocked 一致）。此时主视图没有范围可展示，
// 必须落「暂无范围」，不得表述成「参考范围」。
const riskBandRangeBlocked = computed(() => {
  if (predictionSnapshot.focusMetric !== 'risk') return null
  const sibling = currentHorizonData(selectedHorizon.value)?.results?.risk_level
  if (!sibling) return null
  if (focusResultBox.value?.uncertainty?.band_range) return null
  if (sibling.uncertainty?.band_range) return null
  return sibling.band_range_blocked || null
})

const rangeBadgeKind = computed(() => {
  const box = focusResultBox.value
  const st = focusInterval.value
  // ① 无结果框，或该任务未提供预测区间
  if (!box || !st.available) return 'none'
  // ② risk 等级范围被后端阻断：无范围可展示，不得伪装成「参考范围」
  if (riskBandRangeBlocked.value) return 'none'
  // ③ 非预测区间（情景口径）
  if (st.isPredictionInterval === false) return 'scenario'
  // 退化区间（P05=P95）不构成可用范围
  if (st.degenerate) return 'none'
  // ④ 结构自洽且后端判定决策可用（decisionUsable 为真实判定值，前端不放宽）
  if (st.valid && st.decisionUsable) return 'forecast'
  // ⑤ 结构自洽但未达决策可用：区间可看，只作参考
  if (st.valid && !st.decisionUsable) return 'reference'
  // ⑥ 其余（结构不自洽等）
  return 'none'
})

// 来源披露：逐字保留原状态句的来源部分（季节气候态基线 / 全湖常量模型 / 逐站模型
// + 留出集精度摘要 + 模型文件），仅去掉「融合增益…门禁…」子句——门禁细节由结果
// 面板的评估详情承载。
const sourceDisclosureText = computed(() => {
  const diag = focusDiagnostic.value
  if (!diag) return ''
  if (diag.valueOrigin === 'legacy_v0_2_synthetic_fallback') {
    return '合成情景口径，不可作真实站点预测'
  }
  // 中长期（T+30 起）逐档说清来源：季节气候态基线不含站点分辨，逐站模型才可做站间比较。
  // 2026-09-11：不再统称"逐站模型·已验证"——T+30/60 是无站点分辨的季节基线，
  // T+90 才有逐站模型，且必须连留出集精度一起说，否则"已验证"就是夸大。
  if (selectedHorizon.value < 30) return ''
  if (diag.valueOrigin === 'seasonal_climatology_baseline') {
    const route = diag?.longTermRoute
    const rejected = route?.model_rejected
      ? '（该时效原模型留出样本不足，已按路由规则降级）'
      : ''
    const fallback = diag?.seasonalLookupMode === 'global_fallback'
      ? '（目标月无同期样本，使用全期均值基线）'
      : ''
    return `季节气候态基线：按月给出历史同期值，全湖同值、不含站点分辨${fallback}${rejected}`
  }
  const metrics = diag?.testMetrics || {}
  const parts = []
  if (metrics.mae != null) parts.push(`MAE=${Number(metrics.mae).toFixed(3)}`)
  if (metrics.r2 != null) parts.push(`R²=${Number(metrics.r2).toFixed(3)}`)
  if (metrics.n != null) parts.push(`n=${metrics.n}`)
  const metricText = parts.length ? `，留出集 ${parts.join(' · ')}` : ''
  const fileText = diag?.modelFile ? ` · ${diag.modelFile}` : ''
  // 2026-09-12 复审整改：T+90 只有逐站响应的指标可称"逐站模型"；概率/生物量/密度
  // 在补训中选中 climatology_global 全局常量模型，对站点输入无响应，不得沿用该措辞。
  if (diag && (diag.modelEntityResponse === false || diag.numericVariation === false)) {
    return `中长期 · 全湖常量模型（读模型文件但无站点响应），不做站间比较${fileText}`
  }
  // 门禁状态（PASS/FAIL/NA）的表述整体移入结果面板评估详情，这里只披露来源与留出集精度。
  return `中长期月度趋势：逐站模型${metricText}${fileText}`
})

// 悬浮证据（title）：区间三层证据 + 来源披露。只陈述事实（校准状态 / 经验覆盖率 /
// 样本量），不声称"已验证/达标"——能否用于决策由 kind 按 st.decisionUsable 真实判定。
const rangeBadgeEvidence = computed(() => {
  const st = focusInterval.value
  const parts = []
  if (st.available) {
    parts.push(
      `校准状态 ${st.calibrationStatus}`,
      `经验覆盖率 ${st.empiricalCoverage != null ? (st.empiricalCoverage * 100).toFixed(1) + '%' : '—'}`,
      `测试样本 n=${st.testN ?? '—'}`,
      `校准样本 n=${st.calibrationN ?? '—'}`
    )
  }
  const disclosure = sourceDisclosureText.value
  if (disclosure) parts.push(disclosure)
  return parts.join('；')
})

// 实测快照摘要数值
const classRateText = computed(() => {
  const rate = realtimeSummary.value?.class_iii_rate
  return rate != null ? `${Math.round(rate * 100)}%` : '—'
})
const chlaMeanText = computed(() => {
  const v = realtimeSummary.value?.means?.chlorophyll_a?.value
  if (v != null) return `${v} μg/L`
  const sid = realtimeSummary.value?.selected_snapshot_id
  const snap = (rtTimeline.value || []).find((s) => s.snapshot_id === sid)
  return snap && snap.chla_mean != null ? `${snap.chla_mean} μg/L` : '—'
})

// 选中快照 → 展示该快照点位（失败自动重试）；环比开启时并联前一快照
watch(rtSnapshotId, async (id, old) => {
  loadSummary(id)
  if (rtDiff.value) {
    const snaps = rtTimeline.value || []
    const at = snaps.findIndex((s) => s.snapshot_id === (id || (rtTimeline.value?.latest_snapshot_id || '')))
    const prevId = at > 0 ? snaps[at - 1].snapshot_id : ''
    try {
      prevSummary.value = prevId ? await fetchSummaryFor(prevId) : null
    } catch {
      prevSummary.value = null
    }
  }
})

watch([rtDiff, rtTimeline], async ([on]) => {
  if (!on) {
    prevSummary.value = null
    return
  }
  const snaps = rtTimeline.value || []
  const currentId = rtSnapshotId.value || snaps[snaps.length - 1]?.snapshot_id
  const at = snaps.findIndex((s) => s.snapshot_id === currentId)
  const prevId = at > 0 ? snaps[at - 1].snapshot_id : ''
  try {
    prevSummary.value = prevId ? await fetchSummaryFor(prevId) : null
  } catch {
    prevSummary.value = null
  }
})

// 站点环比变化（chla Δ，相对上一快照）
const chlaDeltaByStation = computed(() => {
  const delta = {}
  if (!rtDiff.value || !prevSummary.value) return delta
  const prevChla = {}
  ;(prevSummary.value.markers || []).forEach((m) => { prevChla[m.id] = m.chla })
  ;(realtimeSummary.value?.markers || []).forEach((m) => {
    const prev = prevChla[m.id]
    if (prev == null || m.chla == null) return
    const d = Number((m.chla - prev).toFixed(2))
    if (Math.abs(d) < 0.05) return
    delta[m.id] = d
  })
  return delta
})

// 环比变化摘要：升降站数统计 + |Δ| 最大的前 3 站（右侧实测快照卡展示）
const diffSummary = computed(() => {
  const markers = realtimeSummary.value?.markers || []
  const rows = []
  markers.forEach((m) => {
    const d = chlaDeltaByStation.value[m.id]
    if (d == null) return
    rows.push({ id: m.id, name: m.name, delta: d })
  })
  rows.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  const up = rows.filter((r) => r.delta > 0).length
  return {
    up,
    down: rows.length - up,
    flat: markers.length - rows.length,
    top: rows.slice(0, 3)
  }
})

// 完整站点环比：同时保留上期/本期值，让结果面板能画出真正的站点变化图。
const stationDiffRows = computed(() => {
  if (!rtDiff.value || !prevSummary.value) return []
  const previous = new Map((prevSummary.value.markers || []).map((m) => [m.id, m]))
  return (realtimeSummary.value?.markers || []).map((current) => {
    const before = previous.get(current.id)
    const prev = Number(before?.chla)
    const next = Number(current?.chla)
    const comparable = before?.chla != null && current?.chla != null && Number.isFinite(prev) && Number.isFinite(next)
    const delta = comparable ? Number((next - prev).toFixed(2)) : null
    return {
      id: current.id,
      name: current.name,
      previous: comparable ? prev : null,
      current: comparable ? next : null,
      delta,
      status: !comparable ? 'missing' : Math.abs(delta) < 0.05 ? 'flat' : delta > 0 ? 'up' : 'down'
    }
  })
})

const diffBaseTimeText = computed(() => {
  const t = prevSummary.value?.latest_observed_at
  if (!t) return '上一快照'
  const m = String(t).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '上一快照'
})

// 预警范围凸包（Andrew monotone chain，lon/lat 平面近似；结果为 [[lat,lon],...] 首尾不闭合）
function convexHull(points) {
  if (points.length < 3) return []
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const lower = []
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper = []
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  upper.pop()
  lower.pop()
  return lower.concat(upper).map(([lon, lat]) => [lat, lon])
}

const warningHull = computed(() => {
  if (!rtPolygon.value) return []
  const pts = (realtimeSummary.value?.warnings || [])
    .filter((w) => w.lon != null && w.lat != null)
    .map((w) => [w.lon, w.lat])
  return convexHull(pts)
})

const MODEL_METRIC_LABELS = { risk: '风险概率', chla: '叶绿素 a', area: '水华面积', biomass: '蓝藻生物量' }
const modelSpatialPoints = computed(() => {
  if (spatialState.value !== 'ok' || !spatialField.value) return []
  const unit = spatialField.value.unit || ''
  const fmtVal = (v) => (metric.value === 'risk'
    ? `${(Number(v) * 100).toFixed(1)}%`
    : `${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 3 })} ${unit}`)
  const points = (spatialField.value.points || []).map((point) => ({
    id: point.entity_id,
    name: point.name,
    lon: point.lon,
    lat: point.lat,
    value: point.value,
    tooltip: `${point.name} · T+${spatialField.value.horizon_days} ${MODEL_METRIC_LABELS[metric.value] || metric.value} ${fmtVal(point.value)}`
  }))
  if (!points.length) return points
  // 站间归一化仅用于"相对高值前 35%"的相对排序标记；它不是预警范围，
  // 数值是否可用于站点比较由快照 comparison_usable 口径在治理页披露。
  const values = points.map((p) => Number(p.value))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  const withNorm = points.map((p) => ({ ...p, normalized: span > 0 ? (Number(p.value) - min) / span : 0 }))
  const sorted = withNorm.slice().sort((a, b) => b.normalized - a.normalized)
  const cutoffIndex = Math.max(2, Math.ceil(sorted.length * 0.35) - 1)
  const cutoff = Number(sorted[Math.min(cutoffIndex, sorted.length - 1)].normalized)
  return withNorm.map((point) => ({ ...point, high: point.normalized >= cutoff }))
})
const modelSpatialBoundary = computed(() => {
  // 相对高值可能分散在多个湖区，不再用一个巨大凸包把中间低值水域误圈入。
  return []
})

const spatialLayerSummary = computed(() => {
  // 覆盖口径统一到快照：total=快照站点层总数（动态），covered=可上图站，
  // withPrediction=有预测值站（含缺坐标不可上图的站）。
  const coverage = spatialField.value?.coverage || null
  return {
    state: spatialState.value,
    covered: coverage?.plottable ?? modelSpatialPoints.value.length,
    total: coverage?.total ?? 0,
    withPrediction: coverage?.with_prediction ?? 0,
    // 未上图 = 有预测但缺可核验坐标的站（仅列表查看）；与"缺预测"分开统计
    notPlottable: Math.max((coverage?.with_prediction ?? 0) - (coverage?.plottable ?? 0), 0),
    highCount: modelSpatialPoints.value.length ? Math.max(3, Math.ceil(modelSpatialPoints.value.length * 0.35)) : 0
  }
})

// 实时观测点位（observed 轨）：与遥感影像同图叠加，颜色按 chla 筛查口径；
// 环比开启时，有升降变化的点放大突出（红升/绿降）。
// 汇总未就绪时用站点目录真实坐标画灰色兜底点（不造数值），数据到达后自动替换。
const realtimePoints = computed(() => {
  const markers = realtimeSummary.value?.markers || []
  if (markers.length) {
    return markers.map((m) => {
      const delta = chlaDeltaByStation.value[m.id]
      const color = delta != null ? (delta > 0 ? '#ef4444' : '#5fd6a4') : chlaColor(m.chla)
      const deltaText = delta != null ? ` · 环比 ${delta > 0 ? '+' : ''}${delta} μg/L` : ''
      return {
        id: m.id,
        short: '',
        name: '',
        hideLabel: true,
        color,
        emphasized: delta != null,
        coord: { lat: m.lat, lon: m.lon },
        tooltip: `${m.name}${m.chla != null ? ` · Chl-a ${m.chla} μg/L` : ' · Chl-a 缺测'}${deltaText}`
      }
    })
  }
  return stationMapPoints(stationCatalog.value).map((p) => ({
    id: p.id,
    short: '',
    name: '',
    hideLabel: true,
    color: '#7d93a8',
    coord: p.coord,
    tooltip: `${p.name} · 观测数据加载中…`
  }))
})

// ---------- 移动端抽屉 ----------
const drawerOpen = ref(false)
const drawerTriggerRef = ref(null)
const drawerRef = ref(null)
const drawerCloseRef = ref(null)
let drawerReturnFocus = null

function openDrawer() {
  drawerReturnFocus = drawerTriggerRef.value || document.activeElement
  drawerOpen.value = true
  nextTick(() => drawerCloseRef.value && drawerCloseRef.value.focus())
}
function closeDrawer() {
  drawerOpen.value = false
  if (drawerReturnFocus && drawerReturnFocus.focus) drawerReturnFocus.focus()
  drawerReturnFocus = null
}
function onDrawerKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    closeDrawer()
    return
  }
  if (e.key !== 'Tab') return
  const focusables = Array.from(
    drawerRef.value.querySelectorAll('button, select, [href], summary, input')
  ).filter((el) => !el.disabled && el.offsetParent !== null)
  if (!focusables.length) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const activeEl = document.activeElement
  if (e.shiftKey && (activeEl === first || activeEl === drawerRef.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && activeEl === last) {
    e.preventDefault()
    first.focus()
  }
}

watch([drawerOpen], ([d]) => {
  document.body.style.overflow = d ? 'hidden' : ''
})

// ≤960px 时移动端底栏 Teleport 到 body，避开 route-stage 入场动画对 fixed 定位的捕获
const mobileMq = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(max-width: 960px)')
  : null
const isMobileViewport = ref(Boolean(mobileMq && mobileMq.matches))
function onMobileMqChange(e) {
  isMobileViewport.value = e.matches
}

onMounted(() => {
  applyQuery(route.query)
  fetchRsManifest()
  // 实时观测图层（observed）：失败自动重试，不阻塞主视图
  loadSummary(rtSnapshotId.value || '')
  getAlgorithmModelStatusEnvelope().then(({ data }) => { modelStatus.value = data }).catch(() => { modelStatus.value = null })
  getAlgorithmV3StatusEnvelope().then(({ data }) => { modelStatusV3.value = data }).catch(() => { modelStatusV3.value = null })
  fetchRealtimeTimeline().then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => { rtTimeline.value = [] })
  fetchRealtimeStations().then((list) => { stationCatalog.value = list }).catch(() => { stationCatalog.value = [] })
  // 首次进入必须把预生成快照写入页面态；仅预取仓库不会触发非 immediate 的 watch。
  loadModelForecast().then(loadSpatialField).catch(() => {})
  realtimeRefreshTimer = setInterval(refreshRealtime, 60_000)
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  stopPlay()
  clearPendingRetry()
  if (realtimeRefreshTimer) clearInterval(realtimeRefreshTimer)
  if (summaryRetryTimer) clearTimeout(summaryRetryTimer)
  mobileMq?.removeEventListener('change', onMobileMqChange)
})
</script>

<style scoped>
.page-heatmap {
  max-width: 1760px;
  margin: 0 auto;
  padding: 8px 20px 12px;
  min-height: 100vh;
}
.hm-body {
  display: grid;
  gap: 6px;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'title'
    'prevbanner'
    'hmain';
  align-items: start;
  min-width: 0;
}

/* ---------- 上一成功版本横幅 ---------- */
.hm-prev-banner {
  grid-area: prevbanner;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  margin-top: 8px;
  padding: 8px 14px;
  border: 1px solid rgba(226, 166, 90, 0.45);
  border-radius: 10px;
  background: rgba(226, 166, 90, 0.12);
  font-size: 12px;
  color: var(--text-primary);
}
.hm-prev-banner b {
  font-size: 12px;
  color: #e2a65a;
  white-space: nowrap;
}
.hm-prev-banner span {
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-all;
}

/* ---------- 标题区 ---------- */
.hm-title {
  grid-area: title;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 16px;
  padding: 6px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.hm-title-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.hm-title h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(18px, 1.8vw, 24px);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}

/* ---------- 主三栏 ---------- */
.hm-main {
  grid-area: hmain;
  display: grid;
  grid-template-columns: minmax(224px, 17fr) minmax(0, 56fr) minmax(390px, 27fr);
  grid-template-areas: 'hleft hcenter hright';
  gap: 6px;
  align-items: start;
  min-width: 0;
}
.hm-panel {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  min-width: 0;
}
.hm-left {
  grid-area: hleft;
  padding: 10px 12px;
  max-height: calc(100vh - 96px);
  overflow-y: auto;
}
.hm-center {
  grid-area: hcenter;
  padding: 8px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.hm-right {
  grid-area: hright;
  padding: 10px 12px;
  max-height: calc(100vh - 96px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hm-sec {
  display: grid;
  gap: 7px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--border-subtle);
}
.hm-sec:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}
.hm-sec-h {
  margin: 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.hm-sec-h span {
  font-size: 10px;
  font-weight: 500;
  font-family: var(--font-mono);
  color: var(--text-muted);
  white-space: nowrap;
}
.hm-sec-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}
.hm-empty-hint {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

/* ---------- 地图 ---------- */
.hm-map-tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 30px;
}
.hm-ab-modes {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
}
.hm-ab-modes button {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
}
.hm-ab-modes button.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.hm-ab-modes button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-ab-select {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.hm-ab-select select {
  min-height: 28px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12px;
  padding: 2px 6px;
}
.hm-map-flag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: 999px;
  padding: 3px 9px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.hm-map-flag--warn {
  color: var(--risk-medium, #facc15);
  border-color: color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent);
}
.hm-inline-btn {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 2px 10px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.hm-inline-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-map-wrap {
  position: relative;
  min-width: 0;
}
.hm-map-wrap :deep(.hm-map) {
  height: clamp(420px, 60vh, 780px);
}
.hm-map-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: color-mix(in srgb, var(--surface-panel, rgba(9, 28, 48, 0.88)) 72%, transparent);
  border-radius: 14px;
  z-index: 500;
}

/* V0.3 月度栅格场：标题切换按钮 + 地图上方浮动面板 */
/* 站点预测范围标签：外框容器保留（data-role=prediction-status-tag）；
   颜色语义已移入 RangeBadge 四态（--c-stable / --c-watch / --c-ai / --text-muted） */
.hm-status-tag {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: rgba(127, 147, 168, 0.08);
  font-size: 12px;
}

.hm-raster-toggle {
  margin-left: 12px;
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.hm-raster-toggle:hover { color: var(--text-primary); }
.hm-raster-toggle[aria-pressed='true'] {
  background: var(--color-primary);
  color: var(--color-primary-ink);
  border-color: transparent;
}
.hm-raster-panel {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 600;
  width: min(520px, calc(100% - 24px));
  max-height: calc(100% - 24px);
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel, rgba(9, 28, 48, 0.94));
  box-shadow: 0 18px 60px rgba(2, 8, 18, 0.55);
}

/* ---------- 年份滑轴与色带 ---------- */
.hm-rs-year {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 2px 0;
}
.hm-rs-year-label {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.hm-rs-year-label b {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--text-primary);
}
.hm-rs-slider {
  flex: 1;
  min-width: 0;
  accent-color: var(--color-primary);
  height: 22px;
  cursor: pointer;
}
.hm-rs-year-range {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hm-rs-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 2px;
}
.hm-rs-legend-min,
.hm-rs-legend-max {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hm-rs-legend-bar {
  flex: 1;
  height: 9px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
}

/* ---------- 键值对（实测快照 / 年度统计） ---------- */
.hm-kv {
  margin: 0;
  display: grid;
  gap: 4px;
}
.hm-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.hm-kv dt {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hm-kv dd {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  text-align: right;
  word-break: break-all;
}

/* ---------- 站点环比变化摘要（实测回放右栏） ---------- */
.hm-diff {
  display: grid;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
}
.hm-diff-counts {
  margin: 0;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11.5px;
}
.hm-diff-counts > span {
  font-size: 10.5px;
  color: var(--text-muted);
}
.hm-diff-up { color: var(--risk-critical, #ef4444); }
.hm-diff-down { color: var(--risk-low, #5fd6a4); }
.hm-diff-lead {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-muted);
}
.hm-diff-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.hm-diff-list li {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
}
.hm-diff-list i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 5px currentColor;
}
.hm-diff-dot--up { background: #ef4444; color: #ef4444; }
.hm-diff-dot--down { background: #5fd6a4; color: #5fd6a4; }
.hm-diff-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hm-diff-delta {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}

/* ---------- 移动端底栏与抽屉 ---------- */
.hm-mobile-bar {
  display: none;
}
.hm-drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 1600;
  display: flex;
  align-items: flex-end;
  background: rgba(2, 8, 18, 0.55);
  backdrop-filter: blur(3px);
}
.hm-drawer {
  width: 100%;
  max-height: 72vh;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-subtle);
  border-radius: 16px 16px 0 0;
  background: var(--surface-panel-raised, rgba(14, 40, 66, 0.96));
  padding-bottom: calc(6px + env(safe-area-inset-bottom, 0px));
}
.hm-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.hm-drawer-head h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.hm-drawer-close {
  appearance: none;
  min-height: 44px;
  min-width: 64px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.hm-drawer-close:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-drawer-body {
  overflow-y: auto;
  padding: 12px 14px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 1280px) {
  .hm-main {
    grid-template-columns: minmax(205px, 0.7fr) minmax(0, 1.55fr) minmax(390px, 1.25fr);
    grid-template-areas: 'hleft hcenter hright';
  }
  .hm-right {
    grid-area: hright;
    max-height: calc(100vh - 96px);
    overflow-y: auto;
  }
}
@media (max-width: 960px) {
  .page-heatmap {
    padding: 8px 12px calc(84px + env(safe-area-inset-bottom, 0px));
  }
  /* 移动端触摸目标：Leaflet 默认缩放按钮 30×30，提到 44×44；署名链接同步 ≥44px */
  .hm-map-wrap :deep(.leaflet-control-zoom a) {
    width: 44px;
    height: 44px;
    line-height: 44px;
  }
  .hm-map-wrap :deep(.leaflet-control-attribution a) {
    display: inline-block;
    min-height: 44px;
    line-height: 44px;
    padding: 0 4px;
  }
  .hm-body {
    grid-template-areas:
      'title'
      'prevbanner'
      'hcenter'
      'hright'
      'hleft';
  }
  .hm-main {
    display: contents;
  }
  .hm-left {
    grid-area: hleft;
    max-height: none;
    overflow: visible;
  }
  .hm-center { grid-area: hcenter; }
  .hm-right {
    grid-area: hright;
    max-height: none;
    overflow: visible;
  }

  .hm-mobile-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1500;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
    background: var(--surface-panel-strong, rgba(10, 20, 34, 0.96));
    border-top: 1px solid var(--border-subtle);
    backdrop-filter: blur(10px);
  }
  .hm-mb-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 8px 10px;
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-item, 8px);
    background: var(--surface-panel-soft);
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .hm-mb-btn:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }

  /* 触摸目标 ≥44×44 */
  .hm-ab-modes button,
  .hm-ab-select select,
  .hm-inline-btn {
    min-height: 44px;
  }
  .hm-map-wrap :deep(.hm-map) {
    height: clamp(340px, 52vh, 560px);
  }
}
</style>

<style>
/* P07 页面级全局补充：reduced-motion 下关闭入场与装饰动画（不动 styles.css） */
@media (prefers-reduced-motion: reduce) {
  .route-stage > .page-heatmap {
    animation: none !important;
  }
  .page-heatmap *,
  .page-heatmap *::before,
  .page-heatmap *::after {
    transition: none !important;
  }
}
</style>
