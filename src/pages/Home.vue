<template>
  <main class="shell home">
    <!-- ============ 首屏：左 5 列信息 / 右 7 列太湖实时态势（粒子流场 + 真实站点） ============ -->
    <section class="hero" aria-labelledby="home-title">
      <div class="hero-copy">
        <h1 id="home-title" class="title">
          <ScrambleText text="蓝藻水华" tag="span" />
          <ScrambleText text="监测预警" tag="span" class="title-accent" :duration="1100" />
        </h1>
        <p class="lede">
          融合多源数据、机理模型与人工智能，支持全湖态势研判、站点下钻、时空推演与历史复盘。
        </p>
        <div class="actions">
          <RouterLink class="btn btn-primary" to="/cockpit">
            进入综合驾驶舱<span class="btn-arrow" aria-hidden="true">→</span>
          </RouterLink>
          <RouterLink class="btn btn-ghost" to="/alerts">
            <svg class="btn-bell" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M15 8.6a5 5 0 0 0-10 0c0 5.8-2.5 7.4-2.5 7.4h15S15 14.4 15 8.6" />
              <path d="M11.3 18.9a1.7 1.7 0 0 1-2.6 0" />
              <path d="M10 3.6V2" />
            </svg>
            预警与应急预案中心
          </RouterLink>
        </div>
      </div>

      <figure class="lake-panel">
        <figcaption class="lake-head">
          <div class="lake-head-copy">
            <strong>{{ identity.lakeName }}流域 · 实时站点态势</strong>
          </div>
          <DataModeBadge mode="observed" label="实时观测" />
        </figcaption>

        <div
          class="lake-canvas"
          role="group"
          aria-label="太湖流域实时监测可视化：全画布粒子网络缓慢漂移并彼此连线，鼠标靠近时粒子散开，点击激发冲击波，监测站点可点击"
        >
          <!-- 全域粒子流场引擎（组件化）：轨迹/连线/星枢/斥力 + 点击冲击波/FPS 自适应/指针光尾 -->
          <FlowCanvas :stations="stationDots" :hovered-id="hoveredStation || ''" />

          <button
            v-for="s in stationDots"
            :key="s.id"
            type="button"
            class="stn"
            :style="{ left: s.left, top: s.top, '--rc': BAND_COLORS[s.band] }"
            :aria-label="`站点 ${s.name}，${s.tip}，点击进入站点研判`"
            @mouseenter="hoveredStation = s.id"
            @focus="hoveredStation = s.id"
            @mouseleave="hoveredStation = hoveredStation === s.id ? null : hoveredStation"
            @blur="hoveredStation = null"
            @click="goStation(s.id)"
          >
            <span class="stn-tip">
              <strong>{{ s.name }}</strong>
              <em>{{ s.tip }}</em>
            </span>
          </button>
        </div>

        <div class="lake-foot" aria-label="实时蓝藻筛查统计">
          <template v-if="rtState === 'ok'">
            <span class="lg lg--low">正常 × {{ stationStats.normal }}</span>
            <span class="lg lg--mid">轻度 × {{ stationStats.light }}</span>
            <span class="lg lg--high">中度 × {{ stationStats.moderate }}</span>
          </template>
          <span v-else-if="rtState === 'loading'" class="lg lg--none">正在加载实时站点…</span>
          <span v-else class="lg lg--none">
            实时站点加载失败
            <button type="button" class="rt-retry" @click="loadSummary(true)">重试</button>
          </span>
        </div>
      </figure>
    </section>

    <!-- ============ 工程脉搏：真实系统数字带 ============ -->
    <div :ref="pulseReveal.targetRef" class="home-reveal" :class="{ 'is-in': pulseReveal.visible.value }">
      <SystemPulse
        :station-total="summary?.station_total ?? '—'"
        :plottable="plottableCount"
        :warnings="summary?.warnings?.length ?? '—'"
        :state="rtState"
      />
    </div>

    <!-- ============ 第二屏：六个核心入口（聚光/磁吸/stagger 升级版） ============ -->
    <div :ref="entriesReveal.targetRef" class="home-reveal" :class="{ 'is-in': entriesReveal.visible.value }">
      <EntryGrid :entries="entries" />
    </div>

  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { dataIdentity as identity } from '../data/dataIdentity.js'
import { fetchRealtimeSummary } from '../services/realtime.js'
import DataModeBadge from '../components/common/DataModeBadge.vue'
import FlowCanvas from '../components/home/FlowCanvas.vue'
import EntryGrid from '../components/home/EntryGrid.vue'
import SystemPulse from '../components/home/SystemPulse.vue'
import ScrambleText from '../components/home/ScrambleText.vue'
import { useReveal } from '../composables/useReveal.js'

const router = useRouter()

// ---------- 实时观测轨：全湖站点态势（与驾驶舱共用 realtime 服务与 60s 缓存） ----------
const summary = ref(null)
const rtState = ref('loading')
let refreshTimer = null

async function loadSummary(force = false) {
  if (force) rtState.value = 'loading'
  try {
    summary.value = await fetchRealtimeSummary({ force })
    rtState.value = 'ok'
  } catch {
    // 首页为着陆页：失败保持装饰性粒子动效，仅站点层降级并给出重试
    rtState.value = 'error'
  }
}

onMounted(() => {
  loadSummary()
  refreshTimer = setInterval(() => loadSummary(true), 60_000)
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

// 站点在缩略图上的投影：taihuOutline.js 的路径 bbox（viewBox 坐标）对应真实地理 bbox
// （来源 OSM relation 1126533，equirectangular，见 data/taihuOutline.js 头注）。
// 视野扩为全流域，使全部可定位站点（summary.markers）都能落在画布内。
const PATH_BBOX = { x0: 26.0, y0: 26.0, w: 359.8, h: 348.0 }
const GEO = { lon0: 119.876, dlon: 0.727, lat1: 31.549, dlat: 0.621 }
const VB_PER_LON = PATH_BBOX.w / GEO.dlon // ≈494.9 viewBox单位/度
const VB_PER_LAT = PATH_BBOX.h / GEO.dlat // ≈560.4 viewBox单位/度

function projectStation(lon, lat) {
  const x = PATH_BBOX.x0 + ((lon - GEO.lon0) / GEO.dlon) * PATH_BBOX.w
  const y = PATH_BBOX.y0 + ((GEO.lat1 - lat) / GEO.dlat) * PATH_BBOX.h
  return { x, y }
}

// 湖体主视野 + 全流域大部分站点：视野 lon 119.35–121.15 / lat 30.55–31.95，
// 33/48 个可定位站点入画，湖体粒子团占画布约 40%×44%，居中
const PAD = { l: 235, r: 137, t: 199, b: 186 }
const VB_W = 520 + PAD.l + PAD.r
const VB_H = 400 + PAD.t + PAD.b

// chla 筛查口径与驾驶舱一致（<10 正常 / 10–25 轻度 / ≥25 中度 / 未报数）
function bandOf(chla) {
  if (chla == null) return 'none'
  if (chla >= 25) return 'moderate'
  if (chla >= 10) return 'light'
  return 'normal'
}
const BAND_TEXT = { normal: '正常', light: '轻度关注', moderate: '中度预警', none: '未报数' }

// 站点统计口径：有坐标站按 chla 筛查分档；warnings 与 markers 是包含关系，
// 只补无坐标的预警站，不去重会把同一站计两次
const stationStats = computed(() => {
  const s = summary.value
  const counts = { normal: 0, light: 0, moderate: 0, none: 0 }
  if (!s) return counts
  const located = new Set()
  for (const m of s.markers || []) {
    if (m.lat == null || m.lon == null) continue
    located.add(m.id)
    const band = bandOf(m.chla)
    if (band !== 'none') counts[band] += 1
  }
  for (const w of s.warnings || []) {
    if (located.has(w.station_id)) continue
    counts[w.band === 'moderate' ? 'moderate' : 'light'] += 1
  }
  counts.none = Math.max(0, (s.station_total ?? 0) - counts.normal - counts.light - counts.moderate)
  return counts
})

// 湖面上展示大部分监测点（视野内全部可定位站）：可见形态由 canvas 绘制为
// 与粒子同风格的发光节点，DOM 按钮仅作透明热区（悬停提示 / 点击下钻）
const STN_MARGIN = 18

// 站点 band→色（热区 tip 强调色与 FlowCanvas 内部着色同口径）
const BAND_COLORS = {
  normal: '#5fd6a4',
  light: '#f5b45d',
  moderate: '#ef4444',
  none: '#7d93a8'
}

const stationDots = computed(() => {
  const out = []
  for (const m of summary.value?.markers || []) {
    if (m.lat == null || m.lon == null) continue
    const { x, y } = projectStation(m.lon, m.lat)
    if (x < -PAD.l + STN_MARGIN || x > 520 + PAD.r - STN_MARGIN) continue
    if (y < -PAD.t + STN_MARGIN || y > 400 + PAD.b - STN_MARGIN) continue
    const band = bandOf(m.chla)
    out.push({
      id: m.id,
      name: m.name || m.id,
      band,
      vx: x,
      vy: y,
      tip: m.chla == null
        ? `${BAND_TEXT.none} · 点击进入站点研判`
        : `Chl-a ${m.chla} μg/L · ${BAND_TEXT[band]}`,
      left: `${(((x + PAD.l) / VB_W) * 100).toFixed(2)}%`,
      top: `${(((y + PAD.t) / VB_H) * 100).toFixed(2)}%`
    })
  }
  return out
})

const hoveredStation = ref(null)

function goStation(id) {
  router.push({ path: '/stations', query: { p: id } })
}

// 有坐标站数（可上图）：工程脉搏 live 口径
const plottableCount = computed(
  () => (summary.value?.markers || []).filter((m) => m.lat != null && m.lon != null).length
)

// 下方区块滚动入场（进入视口一次性 reveal）
const pulseReveal = useReveal()
const entriesReveal = useReveal()

// ---------- 核心入口（顺序 = 业务动线：总览 → 站点 → 预警处置 → 分析 → 展示） ----------
const entries = [
  {
    to: '/cockpit',
    title: '综合驾驶舱',
    desc: '全湖态势总览：风险分区、情景事件流与预警信息一屏研判。'
  },
  {
    to: '/stations',
    title: '监测站点研判',
    desc: 'MEE 国控实时站点：最新观测、缺测披露、数据质量与真实趋势。'
  },
  {
    to: '/alerts',
    title: '预警与应急预案中心',
    desc: '预警事件处置工作流：确认、指派、预案匹配与模拟推送，全程留痕可复盘。'
  },
  {
    to: '/heatmap',
    title: '卫星遥感与时空推演',
    desc: 'THQBCA-V2 年度叶绿素 a / 漂浮藻类遥感影像，支持跨年对比与实时站点叠加。'
  },
  {
    to: '/history',
    title: '实时观测历史复盘',
    desc: 'MEE 实时快照历史回放：按快照查看全站观测状态、达标构成与蓝藻筛查预警。'
  },
  {
    to: '/wallboard',
    title: '实时大屏',
    desc: '全站国控断面实时状态墙：抓取链路、活跃站点与缺测率一屏总览。'
  }
]
</script>

<style scoped>
.home {
  gap: 40px;
  padding-bottom: 48px;
}

/* ============ 首屏 ============ */
.hero {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 24px;
  align-items: stretch;
  padding-top: 8px;
}

.hero-copy {
  grid-column: span 5;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 16px;
  min-width: 0;
}

.title {
  display: grid;
  gap: 2px;
  font-family: var(--font-display);
  font-size: clamp(40px, 4.6vw, 64px);
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.04;
  color: var(--text-primary);
}
.title-accent { color: var(--color-primary); }

.lede {
  max-width: 40rem;
  font-size: 15px;
  line-height: 1.85;
  color: var(--text-secondary);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 48px;
  padding: 0 22px;
  border: 1px solid transparent;
  border-radius: var(--radius-item);
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.btn:hover { transform: translateY(-2px); }
.btn:active { transform: translateY(0); }
.btn-primary {
  background: var(--color-primary);
  color: var(--color-primary-ink);
}
.btn-primary:hover { filter: brightness(1.08); }
.btn-ghost {
  border-color: var(--border-strong);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.btn-ghost:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.btn-arrow { transition: transform 0.15s ease; }
.btn-primary:hover .btn-arrow { transform: translateX(3px); }
.btn-bell { width: 16px; height: 16px; flex: none; }

/* ============ 太湖实时态势 ============ */
.lake-panel {
  grid-column: span 7;
  display: flex;
  flex-direction: column;
  margin: 0;
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}

.lake-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.lake-head-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.lake-head-copy strong {
  font-size: 14px;
  color: var(--text-primary);
}
.lake-head-copy span {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

.lake-canvas {
  position: relative;
  flex: 1;
  min-height: 400px;
  overflow: hidden;
  /* 极光底：柔和的多色浅渐变取代灰色网格 */
  background: linear-gradient(165deg, #f7fbfc 0%, #edf6f8 48%, #f0f7f2 100%);
}
/* 两团极光色斑缓慢漂移（aurora 渐变风格），给粒子网络一个柔和的舞台 */
.lake-canvas::before {
  content: '';
  position: absolute;
  inset: -22%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(34% 42% at 26% 34%, rgba(45, 183, 190, 0.17), transparent 70%),
    radial-gradient(30% 40% at 74% 62%, rgba(99, 161, 250, 0.13), transparent 70%),
    radial-gradient(26% 34% at 56% 26%, rgba(110, 231, 183, 0.15), transparent 70%);
  filter: blur(30px);
  animation: aurora-drift 26s ease-in-out infinite alternate;
}
@keyframes aurora-drift {
  0% { transform: translate3d(-2.5%, -2%, 0) scale(1); }
  50% { transform: translate3d(2%, 2%, 0) scale(1.05); }
  100% { transform: translate3d(-1.5%, 2.5%, 0) scale(1.02); }
}
@media (prefers-reduced-motion: reduce) {
  .lake-canvas::before { animation: none; }
}
/* .flow-canvas 样式随引擎迁入 FlowCanvas.vue 组件 */

/* 站点按钮：可见形态由 canvas 绘制（发光节点），按钮只是透明热区，
   负责悬停提示与点击下钻 */
.stn {
  position: absolute;
  z-index: 2;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  transform: translate(-50%, -50%);
}
.stn-tip {
  position: absolute;
  bottom: calc(100% + 2px);
  left: 50%;
  z-index: 3;
  display: grid;
  gap: 1px;
  padding: 6px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-item);
  background: var(--surface-panel-raised);
  box-shadow: var(--shadow-sm);
  white-space: nowrap;
  max-width: min(46vw, 220px);
  overflow-wrap: anywhere;
  opacity: 0;
  pointer-events: none;
  transform: translateX(-50%) translateY(2px);
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.stn:hover .stn-tip,
.stn:focus-visible .stn-tip {
  opacity: 1;
  transform: translateX(-50%);
}
.stn-tip strong {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-primary);
}
.stn-tip em {
  font-style: normal;
  font-size: 11px;
  color: var(--rc);
}

.lake-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding: 10px 16px;
  border-top: 1px solid var(--border-subtle);
}
.lg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
}
.lg i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
.lg--low, .lg--normal { color: #5fd6a4; }
.lg--mid, .lg--light { color: #f5b45d; }
.lg--high, .lg--moderate { color: #ef4444; }
.lg--none { color: #7d93a8; }
.rt-retry {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 24px;
  padding: 1px 10px;
  font-size: 11px;
  cursor: pointer;
}

/* ============ 下方区块滚动入场 ============ */
.home-reveal {
  opacity: 0;
  transform: translateY(22px);
  transition: opacity 0.56s var(--ease-out, ease-out), transform 0.56s var(--ease-out, ease-out);
}
.home-reveal.is-in {
  opacity: 1;
  transform: none;
}
@media (prefers-reduced-motion: reduce) {
  .home-reveal { opacity: 1; transform: none; transition: none; }
}

/* ============ 响应式 ============ */
@media (max-width: 1180px) {
  .hero-copy,
  .lake-panel { grid-column: span 12; }
  .hero-copy { max-width: 820px; }
}
@media (max-width: 640px) {
  .home { gap: 28px; }
  .lake-canvas { min-height: 340px; }
  .actions .btn { width: 100%; }
}
@media (hover: none) {
  .stn .stn-tip { display: none; }
}
</style>
