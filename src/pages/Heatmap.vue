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

      <!-- 数据口径披露 -->
      <p class="hm-data-note" role="note">
        主视图「实测与预测推演」：MEE 实时快照逐日回放（实测数据），未来 1-3 天 / 7-15 天 / 30-90 天为实测驱动的规则研判（正式算法接入前占位，非数值模型预报）。
        「卫星遥感年度对比」为 THQBCA-V2 年度反演产品（真实历史观测、非实时）。逐站明细见
        <RouterLink to="/stations">监测站点研判</RouterLink>。
      </p>

      <!-- ===== 主三栏 ===== -->
      <div class="hm-main">
        <!-- 左栏：图层 / 图例 / 能力说明 -->
        <aside class="hm-panel hm-left" aria-label="图层与图例">
          <HeatmapLayersPanel
            v-model:realtime-visible="layerRealtime"
            v-model:diff-enabled="rtDiff"
            v-model:polygon-enabled="rtPolygon"
            :realtime-summary="realtimeSummary"
            v-model:basemap="basemap"
          />
        </aside>

        <!-- 中央：卫星遥感地图 -->
        <section class="hm-panel hm-center" aria-label="太湖卫星遥感地图">
          <div class="hm-map-tools">
            <div class="hm-ab-modes" role="group" aria-label="页面模式切换">
              <button
                type="button"
                :aria-pressed="String(pageMode === 'timeline')"
                :class="{ active: pageMode === 'timeline' }"
                data-role="mode-timeline"
                @click="switchMode('timeline')"
              >实测与预测推演</button>
              <button
                type="button"
                :aria-pressed="String(pageMode === 'rs')"
                :class="{ active: pageMode === 'rs' }"
                data-role="mode-rs"
                @click="switchMode('rs')"
              >卫星遥感年度对比</button>
            </div>
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
              <span class="hm-map-flag">年度反演 · 非实时 · 色标全期固定</span>
            </template>
            <span v-else class="hm-map-flag">MEE 实测快照 · 未来档位为规则研判</span>
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
              :hull="warningHull"
              :basemap="basemap"
              :opacity="rsOpacity"
              :reset-token="resetToken"
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

          <!-- 时序推演控制条（推演主视图） -->
          <ForecastTimeline
            v-if="pageMode === 'timeline' && timelineStops.length"
            v-model="selectedStopId"
            :stops="timelineStops"
            :playing="ftlPlaying"
            data-role="forecast-timeline"
            @toggle-play="togglePlay"
            @refresh="refreshRealtime"
          />

          <!-- 色带图例（全期固定尺度，仅遥感模式） -->
          <div v-if="pageMode === 'rs' && activeLayer" class="hm-rs-legend" aria-label="色带图例">
            <span class="hm-rs-legend-min">{{ activeLayer.vmin }} {{ activeLayer.unit }}</span>
            <span class="hm-rs-legend-bar" :style="{ background: legendGradient }"></span>
            <span class="hm-rs-legend-max">≥ {{ activeLayer.vmax }} {{ activeLayer.unit }}</span>
          </div>
        </section>

        <!-- 右栏：推演信息（随模式切换） -->
        <aside class="hm-panel hm-right" aria-label="推演信息">
          <!-- 遥感模式：年度统计 -->
          <template v-if="pageMode === 'rs'">
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

            <!-- 对比摘要（仅对比模式） -->
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

          <!-- 推演模式：选中停靠点内容 -->
          <template v-else>
            <!-- 未来档位：水华风险研判（observed 规则研判，正式算法待接入后替换 riskAssessment.js） -->
            <section v-if="selectedStopIsFuture" class="hm-sec" aria-label="水华风险研判" data-role="risk-panel">
              <h3 class="hm-sec-h">水华风险研判 <span>{{ selectedStop?.title }} · 规则研判</span></h3>
              <template v-if="riskAssessment">
                <div class="hm-risk-level" :class="`hm-risk-level--${riskAssessment.code}`" data-role="risk-level">
                  <b>{{ riskAssessment.text }}</b>
                  <span>研判分 {{ riskAssessment.score }}/100</span>
                </div>
                <ul class="hm-risk-reasons" data-role="risk-reasons">
                  <li v-for="(r, i) in riskAssessment.reasons" :key="i">{{ r }}</li>
                </ul>
                <p class="hm-sec-note">{{ riskAssessment.caliber }}</p>
              </template>
              <StatePanel
                v-else
                state="error"
                title="观测数据不可用"
                description="研判仅由 MEE 实时观测推导，数据加载失败时不产出结论。"
              >
                <button type="button" class="hm-inline-btn" data-role="risk-retry" @click="retryRealtimeSummary">重试</button>
              </StatePanel>
            </section>

            <!-- 实测停靠点：快照摘要 -->
            <section v-else class="hm-sec" aria-label="实测快照摘要" data-role="observed-panel">
              <h3 class="hm-sec-h">实测快照 <span>{{ selectedStop?.tick }} · MEE 观测</span></h3>
              <template v-if="realtimeSummary">
                <dl class="hm-kv" data-role="observed-stats">
                  <div><dt>快照观测时间</dt><dd>{{ (realtimeSummary.latest_observed_at || '').slice(5, 16).replace('T', ' ') }}</dd></div>
                  <div><dt>活跃站点</dt><dd>{{ realtimeSummary.active_station_count ?? realtimeSummary.station_total }}</dd></div>
                  <div><dt>水质达标率（≤III 类）</dt><dd>{{ classRateText }}</dd></div>
                  <div><dt>叶绿素 a 均值</dt><dd>{{ chlaMeanText }}</dd></div>
                  <div><dt>蓝藻筛查预警</dt><dd>{{ (realtimeSummary.warnings || []).length }} 站</dd></div>
                </dl>
                <p class="hm-sec-note">地图点位即该快照实测；向右拖动时间轴查看未来档位研判。</p>
              </template>
              <StatePanel
                v-else
                state="error"
                title="观测数据不可用"
                description="实测摘要来自 MEE 实时快照，数据加载失败时不回退模拟。"
              >
                <button type="button" class="hm-inline-btn" data-role="risk-retry" @click="retryRealtimeSummary">重试</button>
              </StatePanel>
            </section>

            <p class="hm-sec-note">
              未来 1-3 天 / 7-15 天 / 30-90 天由 MEE 实测驱动的透明规则研判（riskAssessment.js）推导，正式算法接入后整体替换；
              非数值模型预报，非监管判定。
            </p>
          </template>
        </aside>
      </div>

      <footer class="hm-foot">
        <span>图层目录：{{ layersText }} · 卫星遥感年度产品（observed）· 非决策用途</span>
      </footer>
    </div>

    <!-- ===== 移动端底部操作栏 ===== -->
    <Teleport to="body" :disabled="!isMobileViewport">
      <nav class="hm-mobile-bar" aria-label="移动端操作栏">
        <RouterLink class="hm-mb-btn" :to="{ path: '/cockpit' }">返回驾驶舱</RouterLink>
        <button ref="drawerTriggerRef" type="button" class="hm-mb-btn" data-role="layers-trigger" @click="openDrawer">图层</button>
      </nav>
    </Teleport>

    <!-- ===== 移动端图层抽屉 ===== -->
    <Teleport to="body">
      <div v-if="drawerOpen" class="hm-drawer-mask" @click.self="closeDrawer">
        <div
          ref="drawerRef"
          class="hm-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="图层设置"
          @keydown="onDrawerKeydown"
        >
          <header class="hm-drawer-head">
            <h3>图层设置</h3>
            <button ref="drawerCloseRef" type="button" class="hm-drawer-close" data-role="drawer-close" aria-label="关闭图层设置" @click="closeDrawer">关闭</button>
          </header>
          <div class="hm-drawer-body">
            <HeatmapLayersPanel
              compact
              v-model:realtime-visible="layerRealtime"
              v-model:diff-enabled="rtDiff"
              v-model:polygon-enabled="rtPolygon"
              :realtime-summary="realtimeSummary"
              v-model:basemap="basemap"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getMapLayersEnvelope,
  getRsManifestEnvelope,
  rsImageUrl
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import StatePanel from '../components/common/StatePanel.vue'
import RsMap from '../components/heatmap/RsMap.vue'
import HeatmapLayersPanel from '../components/heatmap/HeatmapLayersPanel.vue'
import ForecastTimeline from '../components/heatmap/ForecastTimeline.vue'
import { chlaColor, fetchRealtimeSummary, fetchRealtimeTimeline } from '../services/realtime.js'
import { assessShortTerm, assessMidTerm, assessLongTerm } from '../components/heatmap/riskAssessment.js'

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

// ---------- 图层目录（追溯展示，不参与渲染决策） ----------
const layersCatalog = ref(null)
async function fetchLayers() {
  try {
    const { data } = await getMapLayersEnvelope()
    layersCatalog.value = Array.isArray(data) ? data : []
  } catch {
    layersCatalog.value = null
  }
}
const layersText = computed(() =>
  layersCatalog.value && layersCatalog.value.length
    ? layersCatalog.value.map((l) => l.id).join('、')
    : '未获取'
)

// ---------- 地图图层状态 ----------
const mapRef = ref(null)
const layerRealtime = ref(true)
const realtimeSummary = ref(null)
// 拓展图层（observed 真实数据）：历史快照 / 站点环比变化 / 预警范围凸包
const rtSnapshotId = ref('')
const rtDiff = ref(false)
const rtPolygon = ref(false)
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

function retryRealtimeSummary() {
  fetchSummaryFor(rtSnapshotId.value)
    .then((s) => { realtimeSummary.value = s })
    .catch(() => { realtimeSummary.value = null })
}

function refreshRealtime() {
  fetchRealtimeTimeline({ force: true }).then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => {})
  fetchSummaryFor(rtSnapshotId.value)
    .then((s) => { realtimeSummary.value = s })
    .catch(() => { realtimeSummary.value = null })
}

// ---------- 页面模式：时序推演（主视图） / 卫星遥感年度对比（次级功能） ----------
const pageMode = ref('timeline')
function switchMode(mode) {
  if (pageMode.value === mode) return
  stopPlay()
  pageMode.value = mode
}

// ---------- 时序推演时间轴 ----------
// 实测段：/realtime/timeline 快照按日去重（每日取最后一帧）→ 今日；
// 未来段：三档研判（1-3/7-15/30-90 天）等距排布——是规则研判不是逐日数值预报，
// 所以轨道为离散停靠点而非连续日期刻度。正式算法交付后，未来段可换成模型输出逐日帧。
const HORIZONS = [
  { id: 'short', kind: 'short', pos: 63, tick: '短临', title: '未来 1-3 天 · 短临', from: 1, to: 3 },
  { id: 'mid', kind: 'mid', pos: 80, tick: '趋势', title: '未来 7-15 天 · 趋势', from: 7, to: 15 },
  { id: 'long', kind: 'long', pos: 96, tick: '长期', title: '未来 30-90 天 · 长期', from: 30, to: 90 }
]
const TODAY_POS = 46

function pad2(n) {
  return String(n).padStart(2, '0')
}
function fmtMD(date) {
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}
function shiftDate(baseStr, days) {
  return new Date(Number(baseStr.slice(0, 4)), Number(baseStr.slice(5, 7)) - 1, Number(baseStr.slice(8, 10)) + days)
}

const timelineStops = computed(() => {
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
      tick: isLast && isToday ? `${d.slice(5)} · 今日` : d.slice(5),
      title: isLast ? `${d.slice(5)} · ${isToday ? '今日' : '最新'}` : d.slice(5),
      sub: '实测数据',
      snapshotId: snap.snapshot_id
    })
  })
  const anchor = dates[dates.length - 1]
  if (anchor) {
    HORIZONS.forEach((h) => {
      stops.push({
        id: h.id,
        kind: h.kind,
        pos: h.pos,
        tick: h.tick,
        title: h.title,
        sub: `规则研判 ${fmtMD(shiftDate(anchor, h.from))}~${fmtMD(shiftDate(anchor, h.to))}`
      })
    })
  }
  return stops
})

const selectedStopId = ref('')
const selectedStop = computed(() => timelineStops.value.find((s) => s.id === selectedStopId.value) || null)
const selectedStopIsFuture = computed(() => ['short', 'mid', 'long'].includes(selectedStop.value?.kind))

watch(timelineStops, (stops) => {
  if (stops.length && !stops.some((s) => s.id === selectedStopId.value)) {
    const lastObserved = [...stops].reverse().find((s) => s.kind === 'today' || s.kind === 'observed')
    selectedStopId.value = (lastObserved || stops[0]).id
  }
}, { immediate: true })

// 选中停靠点 → 驱动观测快照（地图点位/右栏摘要随之更新）
watch(selectedStopId, (id) => {
  const stop = timelineStops.value.find((s) => s.id === id)
  if (!stop) return
  const target = selectedStopIsFuture.value ? '' : (stop.snapshotId || '')
  if (rtSnapshotId.value !== target) rtSnapshotId.value = target
})

// 播放：沿停靠点推进，到末端自动停
const ftlPlaying = ref(false)
let ftlTimer = null
function togglePlay() {
  if (ftlPlaying.value) {
    stopPlay()
    return
  }
  if (timelineStops.value.length < 2) return
  ftlPlaying.value = true
  ftlTimer = setInterval(() => {
    const stops = timelineStops.value
    const at = stops.findIndex((s) => s.id === selectedStopId.value)
    if (at < 0 || at >= stops.length - 1) {
      stopPlay()
      return
    }
    selectedStopId.value = stops[at + 1].id
  }, 1800)
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
  if (!realtimeSummary.value) return null
  const kind = selectedStop.value?.kind
  if (kind === 'mid') return assessMidTerm(realtimeSummary.value)
  if (kind === 'long') return assessLongTerm(realtimeSummary.value, rsManifest.value)
  return assessShortTerm(realtimeSummary.value)
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

// 选中快照 → 展示该快照点位；环比开启时并联前一快照
watch(rtSnapshotId, async (id, old) => {
  try {
    realtimeSummary.value = await fetchSummaryFor(id)
  } catch {
    realtimeSummary.value = null
  }
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

// 实时观测点位（observed 轨）：与遥感影像同图叠加，颜色按 chla 筛查口径
const realtimePoints = computed(() =>
  (realtimeSummary.value?.markers || []).map((m) => {
    const delta = chlaDeltaByStation.value[m.id]
    const color = delta != null ? (delta > 0 ? '#ff6b6b' : '#5fd6a4') : chlaColor(m.chla)
    const deltaText = delta != null ? ` · 环比 ${delta > 0 ? '+' : ''}${delta} μg/L` : ''
    return {
      id: m.id,
      short: '',
      name: '',
      hideLabel: true,
      color,
      coord: { lat: m.lat, lon: m.lon },
      tooltip: `${m.name}${m.chla != null ? ` · Chl-a ${m.chla} μg/L` : ' · Chl-a 缺测'}${deltaText}`
    }
  })
)

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
  fetchLayers()
  fetchRsManifest()
  // 实时观测图层（observed）：失败不阻塞遥感主视图
  fetchRealtimeSummary().then((s) => { realtimeSummary.value = s }).catch(() => { realtimeSummary.value = null })
  fetchRealtimeTimeline().then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => { rtTimeline.value = [] })
  realtimeRefreshTimer = setInterval(refreshRealtime, 60_000)
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  stopPlay()
  if (realtimeRefreshTimer) clearInterval(realtimeRefreshTimer)
  mobileMq?.removeEventListener('change', onMobileMqChange)
})
</script>

<style scoped>
.hm-data-note {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 45%, transparent);
  border-radius: var(--radius-panel);
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 6%, var(--surface-panel));
  padding: 8px 14px;
}
.hm-data-note a { color: var(--color-primary); }
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
    'hmain'
    'foot';
  align-items: start;
  min-width: 0;
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
.hm-title-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  min-width: 0;
}
.hm-id-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  justify-content: flex-end;
}
.hm-chip {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 2px 9px;
  white-space: nowrap;
}
.hm-chip--observed {
  color: var(--data-observed, #5fd6a4);
  border-color: color-mix(in srgb, var(--data-observed, #5fd6a4) 45%, transparent);
}
.hm-chip--notice {
  color: var(--text-muted);
  border-style: dashed;
}

/* ---------- 主三栏 ---------- */
.hm-main {
  grid-area: hmain;
  display: grid;
  grid-template-columns: minmax(206px, 15fr) minmax(0, 70fr) minmax(240px, 15fr);
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
  max-height: 520px;
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
  max-height: 520px;
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
.hm-map-wrap {
  position: relative;
  min-width: 0;
}
.hm-map-wrap :deep(.hm-map) {
  height: clamp(420px, 62vh, 820px);
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

/* ---------- 键值对 ---------- */
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

/* ---------- 水华风险研判 ---------- */
.hm-risk-level {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
}
.hm-risk-level b {
  font-size: 14px;
}
.hm-risk-level span {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}
.hm-risk-level--high {
  border-color: color-mix(in srgb, #ff6b6b 55%, transparent);
  background: color-mix(in srgb, #ff6b6b 10%, transparent);
}
.hm-risk-level--high b { color: #ff6b6b; }
.hm-risk-level--mid {
  border-color: color-mix(in srgb, #f5b45d 55%, transparent);
  background: color-mix(in srgb, #f5b45d 10%, transparent);
}
.hm-risk-level--mid b { color: #f5b45d; }
.hm-risk-level--low {
  border-color: color-mix(in srgb, #5fd6a4 55%, transparent);
  background: color-mix(in srgb, #5fd6a4 10%, transparent);
}
.hm-risk-level--low b { color: #5fd6a4; }
.hm-risk-reasons {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.hm-risk-reasons li {
  position: relative;
  padding-left: 12px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}
.hm-risk-reasons li::before {
  content: '·';
  position: absolute;
  left: 2px;
  color: var(--text-muted);
}

/* ---------- 页脚 ---------- */
.hm-foot {
  grid-area: foot;
  display: flex;
  justify-content: center;
  padding: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  text-align: center;
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
    grid-template-columns: minmax(190px, 22fr) minmax(0, 78fr);
    grid-template-areas: 'hcenter hright';
  }
  .hm-left {
    display: none;
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
      'hcenter'
      'hright'
      'foot';
  }
  .hm-main {
    display: contents;
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
