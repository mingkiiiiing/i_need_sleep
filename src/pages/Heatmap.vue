<template>
  <main class="page-heatmap">
    <div class="hm-body">
      <!-- ===== 标题区 ===== -->
      <header class="hm-title" aria-label="风险地图与时空推演标题与数据身份">
        <div class="hm-title-left">
          <BackLink :to="cockpitLink" label="返回驾驶舱" />
          <div class="hm-title-text">
            <p class="hm-kicker">P07 · SPATIOTEMPORAL RISK</p>
            <h1>风险地图与时空推演</h1>
          </div>
        </div>
        <div class="hm-title-right">
          <div class="hm-chips" aria-label="数据身份">
            <span class="hm-chip hm-chip--notice">SIMULATED</span>
            <span class="hm-chip">{{ predVersion }}</span>
            <span class="hm-chip">{{ runId }}</span>
            <span class="hm-chip" data-role="stage-chip">档位 <b>{{ stageShortLabel }}</b></span>
            <span class="hm-chip hm-chip--notice">simulation_only</span>
            <span class="hm-chip hm-chip--notice">非决策用途</span>
          </div>
          <div class="hm-modes" role="group" aria-label="时间模式（历史 / 当前 / 未来预演）">
            <button type="button" data-mode-btn="history" disabled aria-disabled="true">
              历史
              <small>真实历史风险帧尚未接入</small>
            </button>
            <button type="button" data-mode-btn="current" disabled aria-disabled="true">
              当前
              <small>实时风险实况层未接入</small>
            </button>
            <button type="button" data-mode-btn="future" class="active" aria-pressed="true">
              未来预演
              <small>演示推演 · 当前可用</small>
            </button>
          </div>
        </div>
      </header>

      <!-- ===== KPI ===== -->
      <section class="hm-kpis" aria-label="当前档位风险格网 KPI">
        <MetricCard
          v-for="kpi in kpis"
          :key="kpi.key"
          :data-kpi="kpi.key"
          :label="kpi.label"
          :value="kpi.value"
          :unit="kpi.unit"
          mode="simulated"
          mode-label="演示数据"
        />
      </section>

      <!-- ===== 主三栏 ===== -->
      <div class="hm-main">
        <!-- 左栏：图层 / 图例 / 能力说明 -->
        <aside class="hm-panel hm-left" aria-label="图层与图例">
          <HeatmapLayersPanel
            v-model:grid-visible="layerGrid"
            v-model:points-visible="layerPoints"
            v-model:labels-visible="layerLabels"
            v-model:basemap="basemap"
            :capabilities="capabilities"
            :caps-state="capsState"
            @retry-caps="fetchCaps"
          />
        </aside>

        <!-- 中央：风险格网地图 -->
        <section class="hm-panel hm-center" aria-label="太湖演示风险格网地图">
          <div class="hm-map-tools">
            <div class="hm-ab-modes" role="group" aria-label="地图显示场景">
              <button
                type="button"
                :aria-pressed="String(abMode === 'stage')"
                :class="{ active: abMode === 'stage' }"
                @click="abMode = 'stage'"
              >当前帧</button>
              <button
                type="button"
                :aria-pressed="String(abMode === 'a')"
                :class="{ active: abMode === 'a' }"
                @click="showAb('a')"
              >场景 A</button>
              <button
                type="button"
                :aria-pressed="String(abMode === 'b')"
                :class="{ active: abMode === 'b' }"
                @click="showAb('b')"
              >场景 B</button>
              <button
                type="button"
                :aria-pressed="String(abMode === 'diff')"
                :class="{ active: abMode === 'diff' }"
                @click="showAb('diff')"
              >差值</button>
            </div>
            <label class="hm-ab-select">
              <span>A</span>
              <select v-model="abA" data-role="ab-a" aria-label="场景 A 档位" @change="ensureAb(abA)">
                <option v-for="item in abSelectOptions" :key="item.key" :value="item.key">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label class="hm-ab-select">
              <span>B</span>
              <select v-model="abB" data-role="ab-b" aria-label="场景 B 档位" @change="ensureAb(abB)">
                <option v-for="item in abSelectOptions" :key="item.key" :value="item.key">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <span v-if="abMode !== 'stage'" class="hm-map-flag">客户端演示场景比较 · 非模型评估结论</span>
            <span v-if="tileError" class="hm-map-flag hm-map-flag--warn" role="status">
              地图瓦片加载失败
              <button type="button" class="hm-inline-btn" @click="retryTiles">重试图层</button>
            </span>
          </div>

          <div class="hm-map-wrap">
            <RiskGridMap
              ref="mapRef"
              :grid="displayGrid"
              :render-mode="abMode === 'diff' ? 'diff' : 'stage'"
              :points="mapPoints"
              :selected-cell="selectedCellId"
              :selected-point="store.selectedPoint"
              :grid-visible="layerGrid"
              :points-visible="layerPoints"
              :labels-visible="layerLabels"
              :basemap="basemap"
              @select-cell="onSelectCell"
              @select-point="store.selectedPoint = $event"
              @tile-error="onTileError"
            />
            <div v-if="mapOverlayState" class="hm-map-overlay" data-role="grid-state" :data-state="mapOverlayState">
              <StatePanel
                :state="mapOverlayState === 'same' ? 'empty' : mapOverlayState"
                :title="mapOverlayTitle"
                :description="mapOverlayDesc"
              >
                <button v-if="mapOverlayState === 'error'" type="button" class="hm-inline-btn" data-role="grid-retry" @click="retryMapOverlay">
                  重试当前档位
                </button>
              </StatePanel>
            </div>
          </div>

          <div v-if="stageKey === 't30'" class="hm-t30-banner" data-role="t30-banner" role="note">
            30—90 天正式预测能力未就绪 · 当前格网仅为固定规则模拟预演
          </div>
          <p class="hm-map-note">
            演示格网定位仅用于界面联调，不代表真实遥感像元边界。阈值：0–44 低 / 45–74 中 / 75–100 高。
          </p>
        </section>

        <!-- 右栏：当前帧研判 -->
        <aside class="hm-panel hm-right" aria-label="当前帧研判">
          <!-- 当前演示帧摘要 -->
          <section class="hm-sec" aria-label="当前演示帧摘要">
            <h3 class="hm-sec-h">当前演示帧 <span>{{ stageShortLabel }} · 演示数据</span></h3>
            <StatePanel
              v-if="frameOverlay"
              :state="frameOverlay"
              :title="frameOverlay === 'loading' ? '格网加载中…' : '格网加载失败'"
              :description="frameOverlay === 'error' ? '当前档位格网不可用，摘要暂无数据。' : ''"
            />
            <template v-else>
              <div class="hm-frame-rows">
                <div class="hm-frame-row lv-high">
                  <span><i></i>高风险格数</span>
                  <strong data-frame="high">{{ frameStats.high }}</strong>
                  <small data-frame="share-high">{{ frameStats.highShare }}%</small>
                </div>
                <div class="hm-frame-row lv-mid">
                  <span><i></i>中风险格数</span>
                  <strong data-frame="mid">{{ frameStats.mid }}</strong>
                  <small data-frame="share-mid">{{ frameStats.midShare }}%</small>
                </div>
                <div class="hm-frame-row lv-low">
                  <span><i></i>低风险格数</span>
                  <strong data-frame="low">{{ frameStats.low }}</strong>
                  <small data-frame="share-low">{{ frameStats.lowShare }}%</small>
                </div>
                <div class="hm-frame-row is-plain">
                  <span>最大 / 平均演示分数</span>
                  <strong data-frame="max-avg">{{ frameStats.max }} / {{ frameStats.avg }}</strong>
                </div>
              </div>
              <p class="hm-frame-meta" data-frame="version">{{ predVersion }} · {{ runId }} · {{ dataMode }}</p>
            </template>
          </section>

          <!-- 选中格详情 -->
          <section class="hm-sec" aria-label="选中格详情">
            <h3 class="hm-sec-h">选中格详情</h3>
            <p v-if="!selectedCellId" class="hm-empty-hint">点击地图格网或热点排行选择一格。</p>
            <template v-else-if="selectedCell">
              <dl class="hm-kv" data-role="cell-detail">
                <div><dt>格网编号</dt><dd data-cd="id">{{ selectedCell.id }}</dd></div>
                <div><dt>行 / 列</dt><dd data-cd="rowcol">第 {{ selectedCell.row + 1 }} 行 · 第 {{ selectedCell.col + 1 }} 列</dd></div>
                <div><dt>当前档位</dt><dd data-cd="stage">{{ stageShortLabel }}</dd></div>
                <div><dt>演示风险分数</dt><dd data-cd="score">{{ selectedCell.value }}</dd></div>
                <div><dt>风险等级</dt><dd data-cd="level">{{ levelText(selectedCell.level) }}（阈值 0–44 / 45–74 / 75–100）</dd></div>
                <div><dt>数据模式</dt><dd data-cd="data-mode">{{ cellProvenance.dataMode }}</dd></div>
                <div><dt>预测运行</dt><dd data-cd="run-id">{{ cellProvenance.runId }}</dd></div>
                <div><dt>使用边界</dt><dd data-cd="boundary">{{ cellProvenance.boundary }}</dd></div>
              </dl>
              <button
                type="button"
                class="hm-warn-btn"
                data-role="warn-trigger"
                :disabled="!canWarn || warnBusy"
                :aria-disabled="String(!canWarn)"
                @click="openWarning"
              >
                模拟预警
                <small v-if="!canWarn">仅高风险格（≥75）可发起</small>
              </button>
              <p v-if="warnResult" class="hm-warn-result" data-role="warn-result" role="status">
                模拟处理记录：<b>{{ warnResult.status }}</b> · 事件标识 {{ warnResult.event_id }} ·
                渠道 {{ (warnResult.channels || []).join('、') }} · {{ warnResult.data_mode }}
              </p>
            </template>
            <p v-else class="hm-empty-hint">当前档位格网不可用，无法读取该格分数。</p>
          </section>

          <!-- 热点排行 -->
          <section class="hm-sec" aria-label="热点排行">
            <h3 class="hm-sec-h">热点排行 <span>演示分数前 5</span></h3>
            <p v-if="!hotspots.length" class="hm-empty-hint">当前档位格网加载后显示。</p>
            <ol v-else class="hm-hotspots">
              <li v-for="(cell, i) in hotspots" :key="cell.id">
                <button
                  type="button"
                  class="hm-hotspot-item"
                  :class="{ active: cell.id === selectedCellId, [`lv-${cell.level}`]: true }"
                  :data-hotspot-cell="cell.id"
                  :aria-pressed="String(cell.id === selectedCellId)"
                  @click="selectedCellId = cell.id"
                >
                  <span class="hm-hs-rank">{{ i + 1 }}</span>
                  <span class="hm-hs-id">{{ cell.id }}</span>
                  <span class="hm-hs-bar"><i :style="{ width: Math.max(10, cell.value) + '%' }"></i></span>
                  <strong class="hm-hs-score">{{ cell.value }}</strong>
                  <span class="hm-hs-level">{{ levelText(cell.level) }}</span>
                </button>
              </li>
            </ol>
          </section>

          <!-- 演示分区参考 -->
          <section class="hm-sec" aria-label="演示分区参考">
            <h3 class="hm-sec-h">演示分区参考 <span>{{ stageShortLabel }} 档位</span></h3>
            <StatePanel
              v-if="zoneOverlay"
              :state="zoneOverlay === 'blocked' ? 'empty' : zoneOverlay"
              :title="zoneOverlayTitle"
              :description="zoneOverlayText"
            >
              <button v-if="zoneOverlay === 'error'" type="button" class="hm-inline-btn" @click="fetchZoneScores(stageKey, true)">重试</button>
            </StatePanel>
            <template v-else>
              <ul class="hm-zones">
                <li v-for="row in zoneRows" :key="row.id">
                  <button
                    type="button"
                    class="hm-zone-row"
                    :class="{ active: row.id === store.selectedPoint }"
                    :aria-pressed="String(row.id === store.selectedPoint)"
                    @click="store.selectedPoint = row.id"
                  >
                    <span class="hm-zone-code">{{ row.short }}</span>
                    <span class="hm-zone-name">{{ row.name }}</span>
                    <strong class="hm-zone-score" :class="`lv-${row.level}`">{{ row.score }}</strong>
                    <span class="hm-zone-level">{{ levelText(row.level) }}</span>
                  </button>
                </li>
              </ul>
            </template>
            <p class="hm-sec-note">分区分数与格网均为模拟研判视图，不代表真实站点影响范围。</p>
          </section>

          <button type="button" class="hm-export-btn" data-role="export-btn" disabled aria-disabled="true" title="导出接口尚未接入">
            导出演示帧 · 尚未接入
          </button>
        </aside>
      </div>

      <!-- ===== 时间推演轴 ===== -->
      <TimeAxisBar class="hm-dock" :stages="axisStages" variant="axis" :sub-label-map="subLabels" />

      <!-- ===== 底部图表 ===== -->
      <div class="hm-charts">
        <section class="hm-panel hm-chart-panel" aria-label="风险格数随档位变化">
          <h3 class="hm-sec-h">风险格数随档位变化 <span>已加载 {{ trendLoadedCount }}/5 档位</span></h3>
          <StatePanel
            v-if="trendState !== 'ok'"
            :state="trendState"
            :title="trendState === 'loading' ? '演示档位预加载中…' : '部分档位格网加载失败'"
            :description="trendState === 'error' ? '趋势仅统计成功加载的演示档位，失败档位不补 0。' : ''"
          >
            <button v-if="trendState === 'error'" type="button" class="hm-inline-btn" data-role="trend-retry" @click="retryTrend">重试失败档位</button>
          </StatePanel>
          <template v-else>
            <EChart :option="trendOption" :height="150" />
          </template>
          <p class="hm-sec-note">仅统计五个档位各自的 /map/risk-grid 演示格网，不使用固定数组。</p>
        </section>

        <section class="hm-panel hm-chart-panel" aria-label="A/B 差异与热点位置变化">
          <h3 class="hm-sec-h">A/B 差异与热点位置变化 <span>场景 {{ stageShort(abA) }} ↔ {{ stageShort(abB) }}</span></h3>
          <details class="hm-fold" :open="!isMobileViewport">
            <summary>A/B 差异与热点位置变化</summary>
            <div class="hm-fold-body">
              <p v-if="abA === abB" class="hm-ab-same" data-role="ab-same" role="status">两个场景相同，无差异</p>
              <StatePanel
                v-else-if="abPanelState !== 'ok'"
                :state="abPanelState"
                :title="abPanelState === 'loading' ? '场景格网加载中…' : '场景格网加载失败'"
                :description="abPanelState === 'error' ? 'A/B 比较必须基于两个成功加载的演示格网。' : ''"
              >
                <button v-if="abPanelState === 'error'" type="button" class="hm-inline-btn" @click="retryAb">重试场景格网</button>
              </StatePanel>
              <template v-else-if="abStats">
                <div class="hm-ab-stats">
                  <span data-ab="up">上升 <b>{{ abStats.up }}</b></span>
                  <span data-ab="down">下降 <b>{{ abStats.down }}</b></span>
                  <span data-ab="same">不变 <b>{{ abStats.same }}</b></span>
                  <span data-ab="max-delta">最大分数差 <b>{{ abStats.maxDelta }}</b></span>
                  <span data-ab="low-to-mid">低→中 <b>{{ abStats.transitions['low->mid'] }}</b></span>
                  <span data-ab="mid-to-high">中→高 <b>{{ abStats.transitions['mid->high'] }}</b></span>
                  <span data-ab="high-to-mid">高→中 <b>{{ abStats.transitions['high->mid'] }}</b></span>
                  <span data-ab="mid-to-low">中→低 <b>{{ abStats.transitions['mid->low'] }}</b></span>
                </div>
                <p class="hm-sec-note">客户端演示场景比较 · 非模型评估结论。仅基于两个演示格网数组做差，不计算面积、岸线或迁移速度。</p>
              </template>
              <div class="hm-track">
                <h4>热点位置变化（演示格网索引）</h4>
                <table class="hm-track-table">
                  <thead>
                    <tr><th>档位</th><th>最高分格网</th><th>最大分数</th><th>高风险格中心</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in track" :key="row.key">
                      <td>{{ row.label }}</td>
                      <td class="mono">{{ row.top.id }}</td>
                      <td>{{ row.max }}</td>
                      <td>{{ row.center ? `R${(row.center.row + 1).toFixed(1)} · C${(row.center.col + 1).toFixed(1)}` : '—' }}</td>
                    </tr>
                  </tbody>
                </table>
                <p class="hm-sec-note">仅为演示格网行列索引变化，不是真实蓝藻迁移轨迹或扩散速度。</p>
              </div>
            </div>
          </details>
        </section>
      </div>

      <footer class="hm-foot">
        <span>图层目录：{{ layersText }} · 数据模式 simulated · SIMULATED / simulation_only / 非决策用途</span>
      </footer>
    </div>

    <!-- ===== 移动端底部操作栏 ===== -->
    <Teleport to="body" :disabled="!isMobileViewport">
      <nav class="hm-mobile-bar" aria-label="移动端操作栏">
        <RouterLink class="hm-mb-btn" :to="cockpitLink">返回驾驶舱</RouterLink>
        <button ref="drawerTriggerRef" type="button" class="hm-mb-btn" data-role="layers-trigger" @click="openDrawer">图层</button>
        <button type="button" class="hm-mb-btn" data-role="play-trigger" :aria-label="store.playing ? '暂停' : '播放'" @click="togglePlay">
          {{ store.playing ? '暂停' : '播放' }}
        </button>
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
              v-model:grid-visible="layerGrid"
              v-model:points-visible="layerPoints"
              v-model:labels-visible="layerLabels"
              v-model:basemap="basemap"
              :capabilities="capabilities"
              :caps-state="capsState"
              @retry-caps="fetchCaps"
            />
          </div>
        </div>
      </div>
    </Teleport>

    <HeatmapWarningDialog
      :open="warnOpen"
      :stage-label="stageShortLabel"
      :cell-id="selectedCellId"
      :score="warnScore"
      level-text="高风险"
      :busy="warnBusy"
      :error="warnError"
      @cancel="closeWarning"
      @confirm="confirmWarning"
    />
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cockpitState, useCockpitStore } from '../stores/cockpit.js'
import {
  getForecastCapabilitiesEnvelope,
  getForecastsEnvelope,
  getMapLayersEnvelope,
  getRiskGridEnvelope,
  getSpatialEntities,
  postHandleWarningEnvelope
} from '../services/api.js'
import BackLink from '../components/common/BackLink.vue'
import MetricCard from '../components/common/MetricCard.vue'
import StatePanel from '../components/common/StatePanel.vue'
import EChart from '../components/cockpit/EChart.vue'
import TimeAxisBar from '../components/cockpit/TimeAxisBar.vue'
import { palette, tooltipTheme } from '../components/cockpit/echartsTheme.js'
import { useTheme } from '../composables/useTheme.js'
import { dataIdentity } from '../data/dataIdentity.js'
import { RISK_ORDER, RISK_TEXT, positionToCoord } from '../components/stations/stationDisplay.js'
import RiskGridMap from '../components/heatmap/RiskGridMap.vue'
import HeatmapLayersPanel from '../components/heatmap/HeatmapLayersPanel.vue'
import HeatmapWarningDialog from '../components/heatmap/HeatmapWarningDialog.vue'
import {
  STAGE_DAYS,
  STAGE_KEYS,
  buildDiffGrid,
  diffGrids,
  flattenCells,
  gridStats,
  hotspotTrack,
  sharePct,
  stageDays,
  stageShort,
  topCells
} from '../components/heatmap/gridCore.js'

const router = useRouter()
const route = useRoute()
useCockpitStore()
const store = cockpitState()

const { theme } = useTheme()

const stageKey = computed(() => store.stageKey)
const stageShortLabel = computed(() => stageShort(stageKey.value))

function levelText(level) {
  return RISK_TEXT[level] || '—'
}

const cockpitLink = computed(() => ({
  path: '/cockpit',
  query: { t: store.stageKey, p: store.selectedPoint }
}))

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

// ---------- 演示分区 ----------
const entities = ref([])
const entitiesState = ref('loading')
async function fetchEntities() {
  entitiesState.value = 'loading'
  try {
    const { data } = await getSpatialEntities()
    entities.value = Array.isArray(data) ? data : []
    entitiesState.value = 'ok'
    resolveSelection()
    fetchZoneScores(stageKey.value)
  } catch {
    entitiesState.value = 'error'
  }
}

// 非法 p 回落到风险最高的有效分区；非法 t 由 cockpit store 校验，这里显式回写 URL
function resolveSelection() {
  if (!entities.value.length) return
  if (!entities.value.some((e) => e.id === store.selectedPoint)) {
    const byRisk = entities.value
      .slice()
      .sort((a, b) => (RISK_ORDER[a.risk_hint] ?? 9) - (RISK_ORDER[b.risk_hint] ?? 9))
    store.selectedPoint = byRisk[0].id
  }
  router.replace({ query: { ...route.query, t: store.stageKey, p: store.selectedPoint } }).catch(() => {})
}

// SPA 内 hash 跳转（如直达 ?p=非法值）不重挂载组件：路由变化时重新校准 p
watch(() => route.fullPath, () => resolveSelection())

const mapPoints = computed(() => {
  const scores = zoneScores[stageKey.value].scores
  return entities.value
    .map((e) => {
      const fc = scores[e.id]
      return {
        id: e.id,
        short: e.short,
        name: e.display_name,
        level: fc ? fc.risk_level : (e.risk_hint || 'low'),
        coord: positionToCoord(e.position)
      }
    })
    .filter((p) => p.coord)
    .map((p) => ({ id: p.id, short: p.short, name: p.name, level: p.level, lat: p.coord.lat, lon: p.coord.lon }))
})

// ---------- 风险格网（每档位独立缓存 + 令牌防串写） ----------
function blankGrid() {
  return { state: 'idle', grid: null, raw: null, error: '' }
}
const grids = reactive({
  t1: blankGrid(),
  t3: blankGrid(),
  t7: blankGrid(),
  t15: blankGrid(),
  t30: blankGrid()
})
const gridTokens = { t1: 0, t3: 0, t7: 0, t15: 0, t30: 0 }

async function fetchGrid(key) {
  const entry = grids[key]
  const token = ++gridTokens[key]
  // 加载/失败期间不保留旧格网：禁止“旧格网 + 新档位标签”的组合展示
  entry.state = 'loading'
  entry.grid = null
  entry.raw = null
  entry.error = ''
  try {
    const { data, meta } = await getRiskGridEnvelope(stageDays(key))
    if (token !== gridTokens[key]) return
    entry.grid = Array.isArray(data.grid) ? data.grid : null
    entry.raw = { ...data, meta }
    if (entry.grid) {
      entry.state = 'ok'
    } else {
      entry.state = 'error'
      entry.error = '接口未返回格网数据'
    }
  } catch (err) {
    if (token !== gridTokens[key]) return
    entry.state = 'error'
    entry.error = err && err.message ? err.message : '风险格网请求失败'
  }
}

function preloadTrend() {
  STAGE_KEYS.forEach((key) => {
    if (grids[key].state === 'idle') fetchGrid(key)
  })
}

const currentEntry = computed(() => grids[stageKey.value])
const currentStats = computed(() => gridStats(currentEntry.value.grid))

// ---------- 档位切换 ----------
watch(stageKey, (key, old) => {
  if (key === old) return
  warnResult.value = null
  if (grids[key].state === 'idle') fetchGrid(key)
  fetchZoneScores(key)
})

// ---------- KPI ----------
const resolutionText = computed(() => {
  const raw = currentEntry.value.raw
  const res = raw && raw.resolution
  return res && res.rows && res.columns ? `${res.rows}×${res.columns}` : '—'
})

const qualityLine = computed(() => {
  if (stageKey.value === 't30') return 'simulation_only · 30—90 天阻塞'
  if (capsState.value === 'ok') return 'simulated · 演示接口就绪'
  if (capsState.value === 'error') return 'simulated · 能力状态未知'
  return 'simulated · 能力查询中'
})

const kpis = computed(() => {
  const ok = currentEntry.value.state === 'ok'
  const stats = currentStats.value
  return [
    { key: 'grid-size', label: '格网规模', value: resolutionText.value, unit: '行×列' },
    { key: 'valid-cells', label: '有效演示格数', value: ok ? String(stats.valid) : '—', unit: '格' },
    { key: 'high-cells', label: '高风险格数', value: ok ? String(stats.high) : '—', unit: '格' },
    { key: 'max-score', label: '当前最大演示风险分数', value: ok ? String(stats.max) : '—', unit: 'risk_score' },
    { key: 'quality-status', label: '数据质量与能力状态', value: qualityLine.value, unit: '' }
  ]
})

// ---------- 帧摘要 ----------
const predVersion = computed(
  () => (currentEntry.value.raw && currentEntry.value.raw.meta && currentEntry.value.raw.meta.dataset_version) || dataIdentity.predictionRunId
)
const runId = computed(() => (currentEntry.value.raw && currentEntry.value.raw.prediction_run_id) || '—')
const dataMode = computed(() => (currentEntry.value.raw && currentEntry.value.raw.data_mode) || 'simulated')

const frameOverlay = computed(() => overlayOf(currentEntry.value))

const frameStats = computed(() => {
  const stats = currentStats.value
  return {
    high: stats.high,
    mid: stats.mid,
    low: stats.low,
    highShare: sharePct(stats.high, stats.valid),
    midShare: sharePct(stats.mid, stats.valid),
    lowShare: sharePct(stats.low, stats.valid),
    max: stats.max == null ? '—' : stats.max,
    avg: stats.avg == null ? '—' : stats.avg.toFixed(1)
  }
})

// ---------- 选中格 ----------
const selectedCellId = ref('')
const selectedCell = computed(() => {
  if (!selectedCellId.value || currentEntry.value.state !== 'ok') return null
  return flattenCells(currentEntry.value.grid).find((c) => c.id === selectedCellId.value) || null
})
const cellProvenance = computed(() => {
  const raw = currentEntry.value.raw || {}
  return {
    dataMode: raw.data_mode || '—',
    runId: raw.prediction_run_id || '—',
    boundary: raw.claim_boundary || '—'
  }
})

function onSelectCell(payload) {
  selectedCellId.value = payload.id
}

// ---------- 模拟预警 ----------
const canWarn = computed(() => Boolean(selectedCell.value && selectedCell.value.level === 'high'))
const warnScore = computed(() => (selectedCell.value ? selectedCell.value.value : ''))
const warnOpen = ref(false)
const warnBusy = ref(false)
const warnResult = ref(null)
const warnError = ref('')
let warnReturnFocus = null

function openWarning() {
  if (!canWarn.value) return
  warnReturnFocus = document.activeElement
  warnError.value = ''
  warnOpen.value = true
}
function closeWarning() {
  warnOpen.value = false
  if (warnReturnFocus && warnReturnFocus.focus) warnReturnFocus.focus()
  warnReturnFocus = null
}
async function confirmWarning() {
  warnBusy.value = true
  warnError.value = ''
  try {
    // 演示处理接口：event_id 为页面演示格网编号，后端仅回显 simulated_dispatched，不产生真实预警
    const { data } = await postHandleWarningEnvelope(selectedCellId.value)
    warnResult.value = data
    warnOpen.value = false
    if (warnReturnFocus && warnReturnFocus.focus) warnReturnFocus.focus()
    warnReturnFocus = null
  } catch (err) {
    warnError.value = err && err.message ? err.message : '调用失败'
  } finally {
    warnBusy.value = false
  }
}
watch(selectedCellId, () => {
  warnResult.value = null
})

// ---------- 热点排行 ----------
const hotspots = computed(() => (currentEntry.value.state === 'ok' ? topCells(currentEntry.value.grid, 5) : []))

// ---------- 分区参考 ----------
function blankZones() {
  return { state: 'idle', scores: {} }
}
const zoneScores = reactive({
  t1: blankZones(),
  t3: blankZones(),
  t7: blankZones(),
  t15: blankZones(),
  t30: blankZones()
})
const zoneTokens = { t1: 0, t3: 0, t7: 0, t15: 0, t30: 0 }

async function fetchZoneScores(key, force = false) {
  const entry = zoneScores[key]
  if (key === 't30') {
    // 后端规则：horizon_days>15 返回 CAPABILITY_UNAVAILABLE；不发起注定失败的请求，直接呈现阻塞
    entry.state = 'blocked'
    entry.scores = {}
    return
  }
  if (!entities.value.length) return
  if (!force && (entry.state === 'ok' || entry.state === 'loading')) return
  const token = ++zoneTokens[key]
  entry.state = 'loading'
  entry.scores = {}
  try {
    const results = await Promise.all(entities.value.map((e) => getForecastsEnvelope(e.id, stageDays(key))))
    if (token !== zoneTokens[key]) return
    const map = {}
    results.forEach(({ data }) => {
      const fc = Array.isArray(data) ? data[0] : null
      if (fc && fc.spatial_entity_id) map[fc.spatial_entity_id] = fc
    })
    entry.scores = map
    entry.state = 'ok'
  } catch {
    if (token !== zoneTokens[key]) return
    entry.scores = {}
    entry.state = 'error'
  }
}

const zoneOverlay = computed(() => {
  if (entitiesState.value === 'loading') return 'loading'
  if (entitiesState.value === 'error') return 'error'
  const s = zoneScores[stageKey.value].state
  if (s === 'loading' || s === 'idle') return 'loading'
  if (s === 'error') return 'error'
  if (s === 'blocked') return 'blocked'
  return null
})
const zoneOverlayTitle = computed(() => {
  if (zoneOverlay.value === 'blocked') return '该档位无分区预测'
  if (zoneOverlay.value === 'error') return '分区预测加载失败'
  return '分区预测加载中…'
})
const zoneOverlayText = computed(() => {
  if (entitiesState.value === 'error') return '演示分区接口请求失败。'
  if (zoneScores[stageKey.value].state === 'blocked') {
    return '预测接口对该档位返回能力阻塞（CAPABILITY_UNAVAILABLE）：30—90 天预测尚未就绪，不提供分区预测分数。'
  }
  return ''
})

const zoneRows = computed(() => {
  const scores = zoneScores[stageKey.value].scores
  return entities.value.map((e) => {
    const fc = scores[e.id]
    const score = fc ? fc.risk_score : null
    return {
      id: e.id,
      short: e.short,
      name: e.display_name,
      score: score == null ? '—' : score,
      level: fc ? fc.risk_level : 'low'
    }
  })
})

// ---------- 地图图层状态 ----------
const mapRef = ref(null)
const layerGrid = ref(true)
const layerPoints = ref(true)
const layerLabels = ref(true)
const basemap = ref('satellite')
const tileError = ref(false)

function onTileError(v) {
  tileError.value = v
}
function retryTiles() {
  mapRef.value && mapRef.value.retryTiles && mapRef.value.retryTiles()
}

// ---------- A/B 场景比较 ----------
const abA = ref('t3')
const abB = ref('t15')
const abMode = ref('stage')

const abSelectOptions = STAGE_KEYS.map((key) => ({ key, label: stageShort(key) }))

function ensureAb(key) {
  if (grids[key] && grids[key].state === 'idle') fetchGrid(key)
}

function showAb(mode) {
  abMode.value = mode
  if (mode === 'a') ensureAb(abA.value)
  if (mode === 'b') ensureAb(abB.value)
  if (mode === 'diff') {
    ensureAb(abA.value)
    ensureAb(abB.value)
  }
}

const abDiff = computed(() => {
  if (abA.value === abB.value) return null
  const a = grids[abA.value]
  const b = grids[abB.value]
  if (a.state !== 'ok' || b.state !== 'ok') return null
  return buildDiffGrid(a.grid, b.grid)
})

const displayGrid = computed(() => {
  if (abMode.value === 'a') return grids[abA.value].grid
  if (abMode.value === 'b') return grids[abB.value].grid
  if (abMode.value === 'diff') return abDiff.value
  return currentEntry.value.grid
})

const abStats = computed(() => {
  if (abA.value === abB.value) return null
  const a = grids[abA.value]
  const b = grids[abB.value]
  if (a.state !== 'ok' || b.state !== 'ok') return null
  return diffGrids(a.grid, b.grid)
})

const abPanelState = computed(() => {
  if (abA.value === abB.value) return 'ok'
  const states = [grids[abA.value].state, grids[abB.value].state]
  if (states.includes('error')) return 'error'
  if (states.some((s) => s !== 'ok')) return 'loading'
  return 'ok'
})

function retryAb() {
  ;[abA.value, abB.value].forEach((key) => {
    if (grids[key].state === 'error') fetchGrid(key)
  })
}

// ---------- 地图覆盖层（随显示源走，而非固定当前档位） ----------
function overlayOf(entry) {
  if (!entry) return null
  if (entry.state === 'loading' || entry.state === 'idle') return 'loading'
  if (entry.state === 'error') return 'error'
  return null
}

const mapOverlayState = computed(() => {
  const mode = abMode.value
  if (mode === 'a') return overlayOf(grids[abA.value])
  if (mode === 'b') return overlayOf(grids[abB.value])
  if (mode === 'diff') {
    if (abA.value === abB.value) return 'same'
    const states = [grids[abA.value].state, grids[abB.value].state]
    if (states.includes('error')) return 'error'
    if (states.some((s) => s !== 'ok')) return 'loading'
    return abDiff.value ? null : 'error'
  }
  return overlayOf(currentEntry.value)
})

const mapOverlayTitle = computed(() => {
  if (mapOverlayState.value === 'loading') return '演示风险格网加载中…'
  if (mapOverlayState.value === 'same') return '两个场景相同，无差异'
  return '演示风险格网加载失败'
})
const mapOverlayDesc = computed(() => {
  if (mapOverlayState.value === 'loading') return '正在请求 /map/risk-grid 演示接口。'
  if (mapOverlayState.value === 'same') return '请选择两个不同档位进行演示场景比较。'
  const entry = abMode.value === 'a' ? grids[abA.value] : abMode.value === 'b' ? grids[abB.value] : currentEntry.value
  return (entry && entry.error) || '接口请求失败，不展示旧档位格网。'
})

function retryMapOverlay() {
  const mode = abMode.value
  if (mode === 'a') return fetchGrid(abA.value)
  if (mode === 'b') return fetchGrid(abB.value)
  if (mode === 'diff') return retryAb()
  return fetchGrid(stageKey.value)
}

// ---------- 趋势（五个档位） ----------
const trendLoadedCount = computed(() => STAGE_KEYS.filter((k) => grids[k].state === 'ok').length)
const trendState = computed(() => {
  const states = STAGE_KEYS.map((k) => grids[k].state)
  if (states.includes('error')) return 'error'
  if (states.some((s) => s !== 'ok')) return 'loading'
  return 'ok'
})

function retryTrend() {
  STAGE_KEYS.forEach((k) => {
    if (grids[k].state === 'error') fetchGrid(k)
  })
}

const trendOption = computed(() => {
  void theme.value
  const p = palette()
  const rows = STAGE_KEYS
    .filter((k) => grids[k].state === 'ok')
    .map((k) => ({ label: stageShort(k), stats: gridStats(grids[k].grid) }))
  return {
    grid: { left: 34, right: 10, top: 26, bottom: 22, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...tooltipTheme() },
    legend: {
      data: ['高风险格数', '中风险格数', '低风险格数'],
      textStyle: { color: p.textSoft, fontSize: 10 },
      top: 0,
      right: 4
    },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.label),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.textSoft, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 10 },
      splitLine: { lineStyle: { color: p.line } },
      minInterval: 1
    },
    series: [
      { name: '高风险格数', type: 'bar', stack: 'risk', barWidth: 22, itemStyle: { color: p.alert }, data: rows.map((r) => r.stats.high) },
      { name: '中风险格数', type: 'bar', stack: 'risk', barWidth: 22, itemStyle: { color: p.watch }, data: rows.map((r) => r.stats.mid) },
      { name: '低风险格数', type: 'bar', stack: 'risk', barWidth: 22, itemStyle: { color: p.stable }, data: rows.map((r) => r.stats.low) }
    ]
  }
})

// ---------- 热点轨迹 ----------
const track = computed(() =>
  hotspotTrack(STAGE_KEYS.map((k) => ({ key: k, state: grids[k].state, grid: grids[k].grid })))
)

// ---------- 时间轴 ----------
const axisStages = STAGE_KEYS.map((key) => ({
  key,
  label: stageShort(key),
  short: stageShort(key),
  days: STAGE_DAYS[key]
}))
const subLabels = {
  t1: '演示预测',
  t3: '演示预测',
  t7: '演示预测',
  t15: '演示预测',
  t30: '模拟预演'
}

function togglePlay() {
  store.playing = !store.playing
}

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

watch([warnOpen, drawerOpen], ([w, d]) => {
  document.body.style.overflow = w || d ? 'hidden' : ''
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
  fetchEntities()
  // 当前档位优先，随后预加载其余档位供趋势与 A/B 使用
  fetchGrid(stageKey.value).then(() => preloadTrend())
  mobileMq?.addEventListener('change', onMobileMqChange)
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
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
    'kpis'
    'hmain'
    'dock'
    'charts'
    'foot';
  align-items: start;
  min-width: 0;
}

/* ---------- 标题区 ---------- */
.hm-title {
  grid-area: title;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px 16px;
  padding: 6px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.hm-title-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}
.hm-kicker {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.22em;
  color: var(--color-primary);
}
.hm-title h1 {
  margin: 1px 0 0;
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
.hm-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}
.hm-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  font-size: 10.5px;
  font-family: var(--font-mono);
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  white-space: nowrap;
}
.hm-chip b { color: var(--text-primary); font-weight: 600; }
.hm-chip--notice {
  border-color: color-mix(in srgb, var(--data-simulated, #7cb8c9) 45%, transparent);
  color: var(--data-simulated, #7cb8c9);
}
.hm-modes {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
}
.hm-modes button {
  appearance: none;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-height: 40px;
  padding: 3px 14px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.hm-modes button small {
  font-size: 8.5px;
  font-weight: 500;
  color: var(--text-muted);
  letter-spacing: 0.03em;
}
.hm-modes button:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}
.hm-modes button.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.hm-modes button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- KPI ---------- */
.hm-kpis {
  grid-area: kpis;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

/* ---------- 主三栏 ---------- */
.hm-main {
  grid-area: hmain;
  display: grid;
  grid-template-columns: minmax(218px, 19fr) minmax(0, 62fr) minmax(252px, 19fr);
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
  max-height: 420px;
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
  max-height: 420px;
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
.mono { font-family: var(--font-mono); }

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
  height: clamp(250px, 29vh, 320px);
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
.hm-t30-banner {
  border: 1px solid color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent);
  background: color-mix(in srgb, var(--risk-medium, #facc15) 10%, transparent);
  color: var(--text-primary);
  border-radius: 9px;
  padding: 6px 10px;
  font-size: 11.5px;
  font-weight: 600;
}
.hm-map-note {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}

/* ---------- 帧摘要 ---------- */
.hm-frame-rows {
  display: grid;
  gap: 4px;
}
.hm-frame-row {
  display: grid;
  grid-template-columns: 1fr auto 40px;
  align-items: center;
  gap: 6px;
  padding: 5px 0;
}
.hm-frame-row span {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-secondary);
}
.hm-frame-row i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.hm-frame-row strong {
  font-family: var(--font-mono);
  font-size: 15px;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.hm-frame-row small {
  color: var(--text-muted);
  font-size: 10px;
  text-align: right;
  font-family: var(--font-mono);
}
.hm-frame-row.is-plain {
  display: flex;
  justify-content: space-between;
}
.lv-high { color: var(--risk-critical, #ef4444); }
.lv-mid { color: var(--risk-medium, #facc15); }
.lv-low { color: var(--risk-low, #22c55e); }
.hm-frame-meta {
  margin: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

/* ---------- 选中格详情 ---------- */
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
.hm-warn-btn {
  appearance: none;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-height: 40px;
  padding: 6px 14px;
  border: 1px solid color-mix(in srgb, var(--risk-critical, #ef4444) 55%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--risk-critical, #ef4444) 10%, transparent);
  color: var(--risk-critical, #ef4444);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  justify-self: start;
}
.hm-warn-btn small {
  font-size: 9px;
  font-weight: 500;
  color: var(--text-muted);
}
.hm-warn-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.hm-warn-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-warn-result {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  padding: 6px 8px;
}
.hm-warn-result b {
  color: var(--text-primary);
  font-family: var(--font-mono);
}

/* ---------- 热点排行 ---------- */
.hm-hotspots {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.hm-hotspot-item {
  width: 100%;
  display: grid;
  grid-template-columns: 18px 52px 1fr 34px auto;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 3px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  text-align: left;
}
.hm-hotspot-item.active {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.hm-hotspot-item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-hs-rank {
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.hm-hs-id {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.hm-hs-bar {
  height: 6px;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}
.hm-hs-bar i {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.hm-hotspot-item.lv-high .hm-hs-bar i { background: var(--risk-critical, #ef4444); }
.hm-hotspot-item.lv-mid .hm-hs-bar i { background: var(--risk-medium, #facc15); }
.hm-hotspot-item.lv-low .hm-hs-bar i { background: var(--risk-low, #22c55e); }
.hm-hs-score {
  font-family: var(--font-mono);
  color: var(--text-primary);
  text-align: right;
}
.hm-hs-level {
  font-size: 9.5px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* ---------- 分区参考 ---------- */
.hm-zones {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.hm-zone-row {
  width: 100%;
  display: grid;
  grid-template-columns: 44px 1fr 32px auto;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 3px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
  text-align: left;
}
.hm-zone-row.active {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
}
.hm-zone-row:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-zone-code {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.hm-zone-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hm-zone-score {
  font-family: var(--font-mono);
  text-align: right;
}
.hm-zone-level {
  font-size: 9.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.hm-export-btn {
  appearance: none;
  min-height: 40px;
  border: 1px dashed var(--border-subtle);
  border-radius: 9px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: not-allowed;
}
.hm-export-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 时间轴 ---------- */
.hm-dock {
  grid-area: dock;
}
.hm-dock :deep(.play-btn) {
  min-width: 40px;
  min-height: 40px;
}
.hm-dock :deep(.axis-node) {
  min-height: 44px;
}

/* ---------- 底部图表 ---------- */
.hm-charts {
  grid-area: charts;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.hm-chart-panel {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hm-ab-same {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  padding: 8px 10px;
}
.hm-ab-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.hm-ab-stats span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--surface-panel-soft);
}
.hm-ab-stats b {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.hm-track h4 {
  margin: 0 0 5px;
  font-size: 11.5px;
  color: var(--text-secondary);
}
.hm-track-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 10.5px;
}
.hm-track-table th,
.hm-track-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
}
.hm-track-table th {
  color: var(--text-muted);
  font-weight: 600;
}
.hm-track-table td.mono {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.hm-fold summary {
  min-height: 32px;
  display: flex;
  align-items: center;
  font-size: 12px;
  font-weight: 650;
  color: var(--text-secondary);
  cursor: pointer;
}
.hm-fold summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hm-fold-body {
  display: grid;
  gap: 10px;
  padding-top: 8px;
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
    grid-template-columns: minmax(200px, 26fr) minmax(0, 74fr);
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
  .hm-body {
    grid-template-areas:
      'title'
      'kpis'
      'hcenter'
      'dock'
      'hright'
      'charts'
      'foot';
  }
  .hm-main {
    display: contents;
  }
  .hm-center { grid-area: hcenter; }
  .hm-right { grid-area: hright; }
  .hm-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .hm-kpis [data-kpi='quality-status'] {
    display: none;
  }
  .hm-right {
    max-height: none;
    overflow: visible;
  }
  .hm-charts {
    grid-template-columns: minmax(0, 1fr);
  }

  .hm-mobile-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1500;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
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
  .hm-chip,
  .hm-ab-modes button,
  .hm-ab-select select,
  .hm-inline-btn,
  .hm-warn-btn,
  .hm-hotspot-item,
  .hm-zone-row,
  .hm-export-btn,
  .hm-fold summary,
  .hm-modes button {
    min-height: 44px;
  }
  .hm-dock :deep(.play-btn),
  .hm-dock :deep(.axis-node) {
    min-width: 44px;
    min-height: 44px;
  }
  .hm-map-wrap :deep(.hm-map) {
    height: 300px;
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
