<template>
  <main class="page-rc">
    <!-- ===== 全屏地图（observed 轨） ===== -->
    <div class="rc-map" aria-label="太湖流域国控站点实时地图">
      <LakeMap
        ref="mapRef"
        :model-value="selectedId"
        :point-list="mapPoints"
        title="太湖流域 国控站点实时监测预警"
        :show-tabs="false"
        :show-legend="false"
        points-visible
        @update:model-value="selectedId = $event"
        @tile-error="onTileError"
      />
    </div>

    <!-- ===== 顶部汇总条（四态：error/historical/abnormal/normal，升级版组件） ===== -->
    <div class="rc-top-shell">
      <TopStatusChip :summary="summary" :state="state" @retry="load(true)" />
    </div>


    <!-- ===== 右侧浮层卡片（站点详情抽屉打开时暂时让位，抽屉关闭后自动恢复） ===== -->
    <aside v-show="!drawerOpen" class="rc-cards" aria-label="全湖实时态势卡片">
      <HealthCard :summary="summary" />
      <WarnCard
        :warnings="summary?.warnings || []"
        :threshold="summary?.warning_thresholds?.light ?? 10"
        @focus="focusStationById"
      />
      <KpiCard :summary="summary" :snapshots="timeline?.snapshots || []" />
    </aside>

    <!-- ===== 点位图例（chla 筛查口径，与 realtime.chlaColor 着色一致） ===== -->
    <div class="rc-legend" aria-label="点位颜色图例">
      <span><i class="rc-lg-dot" style="background: #5fd6a4"></i>正常 &lt;10</span>
      <span><i class="rc-lg-dot" style="background: #f5b45d"></i>轻度 10–25</span>
      <span><i class="rc-lg-dot" style="background: #ef4444"></i>中度 ≥25</span>
      <span><i class="rc-lg-dot" style="background: #7d93a8"></i>未报数</span>
      <em>μg/L · 点击点位看详情</em>
    </div>
    <span v-if="tileError" class="rc-map-flag" role="status">
      地图瓦片加载失败
      <button type="button" class="rc-btn" @click="retryTiles">重试图层</button>
    </span>

    <!-- ===== 底部：真实快照回放时间轴（升级版组件，定位壳由页面提供） ===== -->
    <div
      v-if="timeline && timeline.snapshots.length"
      v-show="!drawerOpen"
      class="rc-timeline"
    >
      <ReplayTimeline
        :timeline="timeline"
        :active-snapshot-id="activeSnapshotId"
        :playing="playing"
        @select="selectSnapshot"
        @toggle-play="togglePlay"
      />
    </div>

    <!-- ===== 站点详情抽屉 / 分析面板 ===== -->
    <CockpitStationDrawer
      v-if="drawerOpen && selectedId"
      :station-id="selectedId"
      :station="drawerStation"
      @close="closeDrawer"
      @open-analysis="openAnalysis"
    />
    <CockpitAnalysisPanel
      v-if="analysisOpen"
      :open="analysisOpen"
      :initial-station-id="analysisStationId"
      @close="analysisOpen = false"
    />
  </main>
</template>

<script setup>
// 综合驾驶舱（observed 实时轨改造版）：全屏地图 + 浮层卡片。
// 所有数值来自 /api/v1/realtime/summary 的真实观测计算；健康分/预警均为透明口径的派生指标，
// 与 simulated 情景内容（时空推演页）严格分轨。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import LakeMap from '../components/cockpit/LakeMap.vue'
import HealthCard from '../components/cockpit/HealthCard.vue'
import KpiCard from '../components/cockpit/KpiCard.vue'
import WarnCard from '../components/cockpit/WarnCard.vue'
import ReplayTimeline from '../components/cockpit/ReplayTimeline.vue'
import TopStatusChip from '../components/cockpit/TopStatusChip.vue'
import CockpitStationDrawer from '../components/stations/CockpitStationDrawer.vue'
import CockpitAnalysisPanel from '../components/stations/CockpitAnalysisPanel.vue'
import {
  chlaColor,
  fetchRealtimeStations,
  fetchRealtimeSummary,
  fetchRealtimeTimeline
} from '../services/realtime.js'
import { setRealtimeUpdate, clearRealtimeUpdate } from '../stores/realtimeUpdate.js'

const summary = ref(null)
const state = ref('loading')
const selectedId = ref('')
const mapRef = ref(null)
// 点击点位 → 详情抽屉；“在分析面板中打开” → 底部大图面板
const drawerOpen = ref(false)
const analysisOpen = ref(false)
const analysisStationId = ref('')
// 真实快照回放：'' = 最新；否则为 timeline 中某个 snapshot_id
const timeline = ref(null)
const activeSnapshotId = ref('')
const playing = ref(false)
// 站点目录：为无坐标预警站（不进 markers）的抽屉提供省份/水质类等身份元数据
const stationCatalog = ref([])
let playTimer = null
let refreshTimer = null

async function load(force = false) {
  if (force) state.value = 'loading'
  try {
    summary.value = await fetchRealtimeSummary({
      force,
      snapshotId: activeSnapshotId.value || undefined
    })
    state.value = 'ok'
    // 历史快照回放时不把快照时间冒充实时更新状态
    if (summary.value.is_latest) setRealtimeUpdate(summary.value)
    else clearRealtimeUpdate()
  } catch {
    summary.value = null
    state.value = 'error'
    clearRealtimeUpdate()
  }
}

async function loadTimeline(force = false) {
  try {
    timeline.value = await fetchRealtimeTimeline({ force })
  } catch {
    // 时间轴失败不打断主视图，仅隐藏回放条
    timeline.value = null
  }
}

function selectSnapshot(id) {
  if (!id || id === activeSnapshotId.value) return
  activeSnapshotId.value = id
  stopPlay()
  load()
}

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  playing.value = false
}

function togglePlay() {
  if (playing.value) {
    stopPlay()
    return
  }
  const snaps = timeline.value?.snapshots || []
  if (snaps.length < 2) return
  playing.value = true
  const step = () => {
    const ids = (timeline.value?.snapshots || []).map((s) => s.snapshot_id)
    if (!ids.length) return stopPlay()
    const at = ids.indexOf(activeSnapshotId.value)
    const next = ids[Math.min(at + 1, ids.length - 1)]
    if (next === activeSnapshotId.value || at === ids.length - 1) return stopPlay()
    activeSnapshotId.value = next
    load()
  }
  playTimer = setInterval(step, 2200)
  step()
}

onMounted(() => {
  load()
  loadTimeline()
  fetchRealtimeStations().then((list) => { stationCatalog.value = list }).catch(() => { stationCatalog.value = [] })
  refreshTimer = setInterval(async () => {
    await loadTimeline(true)
    // 历史回放时只更新可用快照列表，不把用户强制拉回最新。
    if (!activeSnapshotId.value) await load(true)
  }, 60_000)
})

onBeforeUnmount(() => {
  stopPlay()
  if (refreshTimer) clearInterval(refreshTimer)
  clearRealtimeUpdate()
})



function openAnalysis(stationId) {
  analysisStationId.value = stationId || selectedId.value
  analysisOpen.value = true
}

// 关闭抽屉同时清空选中：否则再点同一站点时 selectedId 不变，
// watch 不触发，抽屉无法重新打开
function closeDrawer() {
  drawerOpen.value = false
  selectedId.value = ''
}

let tileErrorFlag = ref(false)
const tileError = computed(() => tileErrorFlag.value)
function onTileError(v) {
  tileErrorFlag.value = v
}
function retryTiles() {
  mapRef.value?.retryTiles?.()
}



watch(selectedId, (id) => {
  if (id) drawerOpen.value = true
})





// ---------- 派生展示 ----------
// 顶部条/三卡/时间轴的派生口径已内聚到各自升级版组件（HealthCard/KpiCard/WarnCard/
// ReplayTimeline/TopStatusChip），页面只保留数据加载、播放控制与点位交互。

// WarnCard 点击预警项上抛真实 station_id：选中即打开详情抽屉（与原 focusStation 同一落点）
function focusStationById(id) {
  if (id) selectedId.value = id
}

function buildHoverCard(m) {
  // 悬停指标卡（lidantech 同款交互）：全部动态值走 textContent，防注入
  const el = document.createElement('div')
  el.className = 'rc-hover-card'
  const head = document.createElement('div')
  head.className = 'rhc-head'
  const name = document.createElement('strong')
  name.textContent = m.name || '—'
  const level = document.createElement('span')
  level.className = 'rhc-level'
  level.textContent = m.water_level ? `${m.water_level}类` : ''
  head.append(name, level)
  const grid = document.createElement('div')
  grid.className = 'rhc-grid'
  const SHOW = [
    ['chlorophyll_a', '叶绿素a', 'μg/L'],
    ['dissolved_oxygen', '溶解氧', 'mg/L'],
    ['total_phosphorus', '总磷', 'mg/L'],
    ['total_nitrogen', '总氮', 'mg/L'],
    ['ammonia_nitrogen', '氨氮', 'mg/L'],
    ['cod_mn', 'CODMn', 'mg/L']
  ]
  SHOW.forEach(([code, label, unit]) => {
    const row = document.createElement('div')
    row.className = 'rhc-item'
    const k = document.createElement('span')
    k.className = 'rhc-k'
    k.textContent = label
    const v = document.createElement('span')
    v.className = 'rhc-v'
    const metric = m.metrics ? m.metrics[code] : undefined
    const b = document.createElement('b')
    b.textContent = metric != null ? String(metric) : '--'
    const u = document.createElement('small')
    u.textContent = ` ${unit}`
    v.append(b, u)
    row.append(k, v)
    grid.append(row)
  })
  const foot = document.createElement('div')
  foot.className = 'rhc-foot'
  foot.textContent = '蓝藻：' + (m.chla == null ? '无数据' : m.chla >= 25 ? '中度预警' : m.chla >= 10 ? '轻度关注' : '正常') + ' · 点击查看详情'
  el.append(head, grid, foot)
  return el
}

const mapPoints = computed(() =>
  (summary.value?.markers || []).map((m) => ({
    id: m.id,
    // 与监测站点页一致：点位旁显示站点名标签
    short: m.name || '',
    name: m.name || '',
    color: chlaColor(m.chla),
    coord: { lat: m.lat, lon: m.lon },
    tooltipNode: buildHoverCard(m)
  }))
)

const drawerStation = computed(() => {
  const id = selectedId.value
  if (!id) return null
  // ① 有坐标站：实时快照 markers（含 province/lat/lon/water_level/metrics）
  const m = (summary.value?.markers || []).find((x) => x.id === id)
  if (m) return m
  // ② 无坐标站（不进 markers，但预警可能命中）：回退站点目录取身份元数据
  const c = stationCatalog.value.find((s) => s.id === id)
  if (c) {
    return {
      id: c.id,
      name: c.source_station_name,
      province: c.province || null,
      basin: '太湖流域',
      lat: c.location?.lat ?? null,
      lon: c.location?.lon ?? null,
      water_level: c.latest_water_level ?? null
    }
  }
  // ③ 目录也未就绪时用预警项兜底身份（省份/坐标确实缺失，如实显示 —）
  const w = (summary.value?.warnings || []).find((x) => x.station_id === id)
  if (w) {
    return {
      id: w.station_id,
      name: w.station_name,
      province: null,
      basin: '太湖流域',
      lat: w.lat ?? null,
      lon: w.lon ?? null,
      water_level: null
    }
  }
  return null
})
</script>

<style scoped>
.page-rc {
  position: relative;
  height: calc(100vh - 96px);
  min-height: 560px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  overflow: hidden;
  background: var(--surface-panel);
}
.rc-map { position: absolute; inset: 0; }
.rc-map :deep(.map-panel) { height: 100%; border: none; background: transparent; }
.rc-map :deep(.leaflet-map-container) { height: 100%; }

/* 顶部汇总条定位壳（胶囊外观与四态渲染在 TopStatusChip 组件内） */
.rc-top-shell {
  position: absolute;
  z-index: 900;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  max-width: min(92%, 860px);
}
.rc-btn {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 30px;
  padding: 2px 12px;
  cursor: pointer;
}

/* 右侧卡片列 */
.rc-cards {
  position: absolute;
  z-index: 900;
  top: 14px;
  right: 14px;
  bottom: 44px;
  width: 368px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  padding-left: 2px;
}

/* 点位图例（chla 筛查口径） */
.rc-legend {
  position: absolute;
  z-index: 900;
  left: 14px;
  /* 需避开 Leaflet 左上角缩放控件（header 37px + 控件高约 61px + 边距，底约 144px） */
  top: 158px;
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-raised);
  font-size: 11px;
  color: var(--text-secondary);
}
.rc-legend em { font-style: normal; color: var(--text-muted); font-size: 10px; }
.rc-lg-dot { width: 9px; height: 9px; border-radius: 999px; display: inline-block; margin-right: 4px; vertical-align: -1px; }

/* 瓦片加载失败提示：避开左上角缩放控件，置于图例上方 */
.rc-map-flag {
  position: absolute;
  z-index: 900;
  left: 14px;
  top: 122px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #facc15) 55%, transparent);
  background: var(--surface-panel-raised);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--risk-medium, #facc15);
}

/* 底部真实快照回放时间轴 */
.rc-timeline {
  position: absolute;
  z-index: 900;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  width: min(680px, 46%);
  padding: 8px 14px;
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-raised);
}

@media (max-width: 1100px) {
  .page-rc { height: auto; min-height: 0; display: flex; flex-direction: column; gap: 10px; padding: 10px; }
  .rc-map { position: relative; inset: auto; height: 340px; flex: none; }
  .rc-top-shell { position: relative; top: auto; left: auto; transform: none; max-width: none; order: -1; }
  .rc-legend { position: static; order: -1; align-self: flex-start; }
  .rc-cards { position: relative; inset: auto; width: 100%; overflow: visible; }
  .rc-timeline { position: relative; bottom: auto; left: auto; transform: none; width: 100%; }
  }
</style>

<style>
/* ===== 驾驶舱悬停指标卡（Leaflet tooltip 宿主，需全局作用域） ===== */
.leaflet-tooltip.rc-tip-host {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 0;
}
.leaflet-tooltip.rc-tip-host::before { display: none; }
.rc-hover-card {
  width: 248px;
  background: var(--surface-panel-raised, #fff);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  padding: 10px 12px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.2);
  color: var(--text-primary);
}
.rhc-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
.rhc-head strong { font-size: 14px; }
.rhc-level {
  font-size: 10.5px;
  color: var(--risk-low, #22c55e);
  border: 1px solid color-mix(in srgb, var(--risk-low, #22c55e) 45%, transparent);
  padding: 1px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.rhc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 14px; }
.rhc-item { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.rhc-k { color: var(--text-muted); font-size: 11px; }
.rhc-v { white-space: nowrap; }
.rhc-v b { font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; }
.rhc-v small { color: var(--text-muted); font-size: 9.5px; }
.rhc-foot { margin-top: 7px; padding-top: 6px; border-top: 1px solid var(--border-subtle); color: var(--text-muted); font-size: 10.5px; }
</style>
