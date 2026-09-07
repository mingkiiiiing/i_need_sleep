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
        <div class="hm-title-right">
          <div class="hm-id-chips" aria-label="数据身份">
            <span class="hm-chip">{{ rsIdentity.version }}</span>
            <span class="hm-chip hm-chip--observed">{{ rsIdentity.dataMode }}</span>
            <span class="hm-chip hm-chip--notice">{{ rsIdentity.boundary }}</span>
          </div>
        </div>
      </header>

      <!-- 数据口径披露：年度遥感反演产品（真实历史观测），非实时插值 -->
      <p class="hm-data-note" role="note">
        本页展示 THQBCA-V2 年度卫星遥感反演产品（叶绿素 a / 漂浮藻类覆盖率，真实历史观测、非实时）。
        MEE 实时站点的逐时观测见
        <RouterLink to="/stations">监测站点研判</RouterLink>；实时观测点位与遥感图层同图叠加（observed 轨）。
      </p>

      <!-- ===== 主三栏 ===== -->
      <div class="hm-main">
        <!-- 左栏：图层 / 图例 / 能力说明 -->
        <aside class="hm-panel hm-left" aria-label="图层与图例">
          <HeatmapLayersPanel
            v-model:realtime-visible="layerRealtime"
            v-model:snapshot-id="rtSnapshotId"
            :snapshot-list="rtTimeline"
            v-model:diff-enabled="rtDiff"
            v-model:polygon-enabled="rtPolygon"
            :realtime-summary="realtimeSummary"
            v-model:basemap="basemap"
            :capabilities="capabilities"
            :caps-state="capsState"
            @retry-caps="fetchCaps"
          />
        </aside>

        <!-- 中央：卫星遥感地图 -->
        <section class="hm-panel hm-center" aria-label="太湖卫星遥感地图">
          <div class="hm-map-tools">
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
            <span v-if="tileError" class="hm-map-flag hm-map-flag--warn" role="status">
              地图瓦片加载失败
              <button type="button" class="hm-inline-btn" @click="retryTiles">重试图层</button>
            </span>
          </div>

          <div class="hm-map-wrap">
            <RsMap
              ref="mapRef"
              :image-a="imageA"
              :image-b="imageB"
              :compare="rsCompare"
              :badge-a="badgeA"
              :badge-b="badgeB"
              :points="realtimePoints"
              :points-visible="layerRealtime"
              :hull="warningHull"
              :basemap="basemap"
              :opacity="rsOpacity"
              :reset-token="resetToken"
              @tile-error="onTileError"
            />
            <div v-if="rsOverlay" class="hm-map-overlay" data-role="rs-state" :data-state="rsOverlay">
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

          <!-- 年份滑轴 -->
          <div v-if="years.length" class="hm-rs-year">
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

          <!-- 色带图例（全期固定尺度） -->
          <div v-if="activeLayer" class="hm-rs-legend" aria-label="色带图例">
            <span class="hm-rs-legend-min">{{ activeLayer.vmin }} {{ activeLayer.unit }}</span>
            <span class="hm-rs-legend-bar" :style="{ background: legendGradient }"></span>
            <span class="hm-rs-legend-max">≥ {{ activeLayer.vmax }} {{ activeLayer.unit }}</span>
          </div>
        </section>

        <!-- 右栏：年度统计与数据来源 -->
        <aside class="hm-panel hm-right" aria-label="年度统计与数据来源">
          <!-- 年度统计 -->
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

          <!-- 数据来源 -->
          <section class="hm-sec" aria-label="数据来源">
            <h3 class="hm-sec-h">数据来源</h3>
            <dl class="hm-kv" data-role="rs-source">
              <div><dt>数据集</dt><dd>{{ rsManifest?.source_dataset || '—' }}</dd></div>
              <div><dt>产品口径</dt><dd>年度反演 · 30m</dd></div>
              <div><dt>清单生成</dt><dd>{{ rsManifest?.generated_at || '—' }}</dd></div>
              <div><dt>使用边界</dt><dd>{{ rsIdentity.boundary }}</dd></div>
            </dl>
            <p class="hm-sec-note">{{ rsManifest?.note || '年度卫星遥感反演产品：真实历史观测（非实时、非模拟）。' }}</p>
          </section>
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
              v-model:snapshot-id="rtSnapshotId"
              :snapshot-list="rtTimeline"
              v-model:diff-enabled="rtDiff"
              v-model:polygon-enabled="rtPolygon"
              :realtime-summary="realtimeSummary"
              v-model:basemap="basemap"
              :capabilities="capabilities"
              :caps-state="capsState"
              @retry-caps="fetchCaps"
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
  getForecastCapabilitiesEnvelope,
  getMapLayersEnvelope,
  getRsManifestEnvelope,
  rsImageUrl
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import StatePanel from '../components/common/StatePanel.vue'
import RsMap from '../components/heatmap/RsMap.vue'
import HeatmapLayersPanel from '../components/heatmap/HeatmapLayersPanel.vue'
import { chlaColor, fetchRealtimeSummary, fetchRealtimeTimeline } from '../services/realtime.js'

const RS_VERSION = 'THQBCA-V2-BIOOPTICS-V1'
const rsIdentity = {
  version: RS_VERSION,
  dataMode: 'observed · 年度反演',
  boundary: 'satellite_annual_retrieval_not_in_situ'
}

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

// ---------- 能力 ----------
const capabilities = ref(null)
const capsState = ref('loading')
async function fetchCaps() {
  capsState.value = 'loading'
  try {
    const { data } = await getForecastCapabilitiesEnvelope()
    capabilities.value = data && typeof data === 'object' ? data : {}
    capsState.value = 'ok'
  } catch {
    capabilities.value = null
    capsState.value = 'error'
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
      tooltip: `${m.name}（位置待核验）${m.chla != null ? ` · Chl-a ${m.chla} μg/L` : ' · Chl-a 缺测'}${deltaText}`
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
  fetchCaps()
  fetchLayers()
  fetchRsManifest()
  // 实时观测图层（observed）：失败不阻塞遥感主视图
  fetchRealtimeSummary().then((s) => { realtimeSummary.value = s }).catch(() => { realtimeSummary.value = null })
  fetchRealtimeTimeline().then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => { rtTimeline.value = [] })
  realtimeRefreshTimer = setInterval(() => {
    fetchRealtimeTimeline({ force: true }).then((t) => { rtTimeline.value = t.snapshots || [] }).catch(() => {})
    if (!rtSnapshotId.value) {
      fetchRealtimeSummary({ force: true }).then((s) => { realtimeSummary.value = s }).catch(() => {})
    }
  }, 60_000)
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
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
