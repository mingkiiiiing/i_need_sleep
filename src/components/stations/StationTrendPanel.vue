<template>
  <section class="stn-block stp" aria-label="站点时序分析（真实累计数据）">
    <div class="stn-sec-head">
      <h2>站点时序分析</h2>
      <div class="stp-controls">
        <div class="stp-range" role="group" aria-label="时间范围">
          <button
            v-for="r in RANGES"
            :key="r.key"
            type="button"
            class="stn-chip stn-chip--sm"
            :class="{ active: range === r.key }"
            :aria-pressed="String(range === r.key)"
            @click="range = r.key"
          >
            {{ r.label }}
          </button>
        </div>
        <button
          type="button"
          class="stn-chip stn-chip--sm"
          :class="{ active: compareMode }"
          :aria-pressed="String(compareMode)"
          data-role="trend-compare-toggle"
          @click="toggleCompare"
        >
          指标对比
        </button>
      </div>
    </div>

    <!-- 指标切换：单选（单指标模式）/ 多选最多 3 项（对比模式） -->
    <div class="stp-vars" role="group" :aria-label="compareMode ? '对比指标选择（最多 3 项）' : '趋势指标切换'">
      <button
        v-for="opt in TREND_VARIABLES"
        :key="opt.code"
        type="button"
        class="stn-chip stn-chip--sm"
        :class="{ active: isActive(opt.code) }"
        :aria-pressed="String(isActive(opt.code))"
        :data-role="`trend-var-${opt.code}`"
        @click="pickVariable(opt.code)"
      >
        <i
          v-if="compareMode && isActive(opt.code)"
          class="stp-chip-dot"
          :style="{ '--chip-c': seriesColorOf(opt.code) }"
          aria-hidden="true"
        ></i>
        {{ opt.label }}
      </button>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">趋势数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="load">重试</button>
    </div>

    <template v-else>
      <!-- 单指标模式 -->
      <template v-if="!compareMode">
        <p class="stp-title" data-role="trend-title">{{ titleText }}</p>
        <div v-if="points.length >= 2" class="stp-chart">
          <div class="stp-plotrow">
            <div
              class="stp-plotcol"
              @pointerdown="onPlotMove('main', $event)"
              @pointermove="onPlotMove('main', $event)"
              @pointerup="onPlotUp"
              @pointercancel="onPlotLeave('main')"
              @pointerleave="onPlotLeave('main')"
            >
              <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" :aria-label="`${variableLabel(variable)} 历史趋势图`">
                <defs>
                  <linearGradient :id="gradMainId" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" :style="{ stopColor: 'var(--series-c)', stopOpacity: 0.22 }" />
                    <stop offset="1" :style="{ stopColor: 'var(--series-c)', stopOpacity: 0 }" />
                  </linearGradient>
                </defs>
                <!-- 水平网格：落在取整刻度值上 -->
                <line
                  v-for="t in yTicksMain"
                  :key="`g-${t.text}`"
                  class="stp-grid"
                  x1="0"
                  :y1="t.y"
                  :x2="W"
                  :y2="t.y"
                  vector-effect="non-scaling-stroke"
                />
                <!-- 主色渐变面积：折线下方 22% → 0 透明 -->
                <path class="stp-area" :d="areaPath" :fill="`url(#${gradMainId})`" />
                <!-- Grafana 式统计参考线：只由真实序列点计算 -->
                <line
                  v-for="a in statsBase"
                  :key="`r-${a.key}`"
                  class="stp-ref"
                  :class="`stp-ref--${a.key}`"
                  x1="0"
                  :y1="a.y"
                  :x2="W"
                  :y2="a.y"
                  vector-effect="non-scaling-stroke"
                />
                <polyline class="stp-line" :points="polylinePoints" vector-effect="non-scaling-stroke" />
                <circle v-for="(p, i) in points" :key="i" class="stp-dot" :cx="p.x" :cy="p.y" r="2" />
                <!-- 悬停十字线：吸附最近真实点，不做插值 -->
                <line
                  v-if="crossXFor('main') !== null"
                  class="stp-cross"
                  :x1="crossXFor('main')"
                  y1="0"
                  :x2="crossXFor('main')"
                  :y2="H"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <!-- 统计标注文字：右内侧，等宽小字，防互相压盖 -->
              <span
                v-for="a in statLabels"
                :key="a.key"
                class="stp-ann"
                :class="{ 'stp-ann--below': a.below }"
                :style="{ top: a.top }"
                aria-hidden="true"
              >{{ a.text }}</span>
              <!-- 末点脉冲（最后一个真实观测点） -->
              <span v-if="lastPointMain" class="stp-pulse" :style="lastPointMain" aria-hidden="true"></span>
              <!-- 悬停最近点高亮 + 数值浮层 -->
              <template v-if="hoverInfo && hoverInfo.key === 'main'">
                <span class="stp-hover-dot" :style="hoverInfo.dot" aria-hidden="true"></span>
                <div class="stp-tip" :style="hoverInfo.tipStyle" aria-hidden="true">
                  <span class="stp-tip-time">{{ hoverInfo.time }}</span>
                  <span class="stp-tip-val">{{ hoverInfo.text }}</span>
                </div>
              </template>
              <!-- x 轴内部时间刻度（等分候选 + 最小间距抽稀防压盖） -->
              <div v-if="xTicks.length" class="stp-xticks" aria-hidden="true">
                <span v-for="xt in xTicks" :key="xt.t" class="stp-xtick" :style="{ left: `${xt.pct}%` }">{{ tickStamp(xt.t) }}</span>
              </div>
            </div>
            <div class="stp-yaxis" aria-hidden="true">
              <span v-for="t in yTicksMain" :key="`y-${t.text}`" class="stp-ytick" :style="{ top: t.top }">{{ t.text }}</span>
            </div>
          </div>
          <div class="stp-axis">
            <span>{{ formatStamp(points[0].t) }}</span>
            <span>仅真实累计观测 · {{ points.length }} 个快照 · {{ rangeLabel }}</span>
            <span>{{ formatStamp(points[points.length - 1].t) }}</span>
          </div>
        </div>
        <p v-else class="stn-trend-note stn-trend-note--sparse" data-role="trend-empty">
          真实观测尚在积累：{{ variableLabel(variable) }} 在该时间范围内不足两个有效时间点（当前 {{ points.length }} 个）。系统随抓取持续积累，不做模拟补点。
        </p>
      </template>

      <!-- 对比模式：小多图纵向排列，各图独立纵轴，不共用刻度 -->
      <template v-else>
        <p class="stp-title" data-role="trend-title">{{ compareTitleText }}</p>
        <p v-if="!compareVars.length" class="stn-trend-note">在上方选择 1—3 项指标进行对比。</p>
        <div v-else class="stp-multi">
          <div v-for="cv in compareCharts" :key="cv.code" class="stp-multi-item" :style="{ '--series-c': cv.color }">
            <div class="stp-multi-head">
              <span class="stp-multi-name"><i class="stp-multi-dot" aria-hidden="true"></i>{{ cv.label }}</span>
              <span class="stp-multi-latest">{{ cv.latestText }}</span>
            </div>
            <div v-if="cv.points.length >= 2" class="stp-plotrow stp-plotrow--multi">
              <div
                class="stp-plotcol"
                @pointerdown="onPlotMove(cv.code, $event)"
                @pointermove="onPlotMove(cv.code, $event)"
                @pointerup="onPlotUp"
                @pointercancel="onPlotLeave(cv.code)"
                @pointerleave="onPlotLeave(cv.code)"
              >
                <svg :viewBox="`0 0 ${W} ${MULTI_H}`" preserveAspectRatio="none" role="img" :aria-label="`${cv.label} 趋势小图`">
                  <defs>
                    <linearGradient :id="`${gradMultiId}-${cv.code}`" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0" :style="{ stopColor: 'var(--series-c)', stopOpacity: 0.1 }" />
                      <stop offset="1" :style="{ stopColor: 'var(--series-c)', stopOpacity: 0 }" />
                    </linearGradient>
                  </defs>
                  <line
                    v-for="t in cv.ticks"
                    :key="`g-${t.text}`"
                    class="stp-grid"
                    x1="0"
                    :y1="t.y"
                    :x2="W"
                    :y2="t.y"
                    vector-effect="non-scaling-stroke"
                  />
                  <path class="stp-area" :d="cv.area" :fill="`url(#${gradMultiId}-${cv.code})`" />
                  <polyline class="stp-line" :points="cv.polyline" vector-effect="non-scaling-stroke" />
                  <line
                    v-if="crossXFor(cv.code) !== null"
                    class="stp-cross"
                    :x1="crossXFor(cv.code)"
                    y1="0"
                    :x2="crossXFor(cv.code)"
                    :y2="MULTI_H"
                    vector-effect="non-scaling-stroke"
                  />
                </svg>
                <span v-if="cv.lastStyle" class="stp-pulse" :style="cv.lastStyle" aria-hidden="true"></span>
                <template v-if="hoverInfo && hoverInfo.key === cv.code">
                  <span class="stp-hover-dot" :style="hoverInfo.dot" aria-hidden="true"></span>
                  <div class="stp-tip" :style="hoverInfo.tipStyle" aria-hidden="true">
                    <span class="stp-tip-time">{{ hoverInfo.time }}</span>
                    <span class="stp-tip-val">{{ hoverInfo.text }}</span>
                  </div>
                </template>
              </div>
              <div class="stp-yaxis stp-yaxis--multi" aria-hidden="true">
                <span v-for="t in cv.ticks" :key="`y-${t.text}`" class="stp-ytick" :style="{ top: t.top }">{{ t.text }}</span>
              </div>
            </div>
            <p v-else class="stn-trend-note">该时间范围内有效点不足，不绘制。</p>
          </div>
        </div>
        <p class="stn-trend-note">对比模式为上下小多图，各指标独立纵轴；不同量纲指标不共用一条纵轴，不做标准化伪装。</p>
      </template>

      <p v-if="skipped.length" class="stn-trend-note">缺测/质控不合格快照 {{ skipped.length }} 次未参与连线，不做插值。</p>
    </template>
  </section>
</template>

<script setup>
// 站点时序分析区：只画真实累计观测（observed 轨 range 查询）。
// 单指标模式保证数值与单位清晰；对比模式最多 3 项、小多图独立纵轴；
// 时间范围 24 小时 / 7 天 / 30 天 / 全部；缺测断点不插值；少于两个时间点显式说明。
// 可视化（Grafana 标注/十字线 + Tufte 极简墨水比）：
//   渐变面积 · 末点脉冲 · max/avg/min 真实点统计参考线 · 最近真实点吸附十字线 tooltip ·
//   取整刻度 y 网格与右侧等宽刻度 · x 轴刻度最小间距抽稀 · 全部动画 reduced-motion 降级。
import { computed, ref, watch } from 'vue'
import { fetchStationObservations, fmtMeasure, formatStamp, OBS_HISTORY_START, todayLocalDate, variableLabel } from '../../services/realtime.js'

const props = defineProps({
  stationId: { type: String, default: '' },
  stationName: { type: String, default: '' }
})

const TREND_VARIABLES = [
  { code: 'chlorophyll_a', label: '叶绿素 a' },
  { code: 'total_phosphorus', label: '总磷' },
  { code: 'total_nitrogen', label: '总氮' },
  { code: 'dissolved_oxygen', label: '溶解氧' },
  { code: 'water_temperature', label: '水温' }
]

const RANGES = [
  { key: '24h', label: '24小时', hours: 24 },
  { key: '7d', label: '7天', hours: 24 * 7 },
  { key: '30d', label: '30天', hours: 24 * 30 },
  { key: 'all', label: '全部', hours: null }
]

const W = 600
const H = 150
const MULTI_H = 56
const PAD_X = 12 // 主图左右内边距（viewBox 单位）
const PAD_T = 8
const PAD_B = 8
const MULTI_PAD_X = 6
const MULTI_PAD = 6

// 对比模式系列色：全部取语义令牌（主青 / 真实观测蓝 / AI 紫），勿造新色；
// 激活指标 chip 上的色点、小多图图例点与折线共用同一令牌。
const COMPARE_COLORS = ['var(--color-primary)', 'var(--data-observed)', 'var(--c-ai)']

// 渐变 id 需组件实例唯一，避免同页多实例互相串用（script setup 体内无法放模块级计数器，用随机后缀）
const uid = Math.random().toString(36).slice(2, 8)
const gradMainId = `stp-grad-main-${uid}`
const gradMultiId = `stp-grad-multi-${uid}`

const variable = ref('chlorophyll_a')
const compareMode = ref(false)
const compareVars = ref([])
const range = ref('all')
const state = ref('loading')
const allRows = ref([])

const rangeLabel = computed(() => RANGES.find((r) => r.key === range.value)?.label || '')

function seriesOf(code) {
  // 每个快照取该指标最新一行（任意状态），保留缺测/质控行供 skipped 统计
  const bySnapshot = new Map()
  allRows.value
    .filter((row) => row.variable_code === code)
    .forEach((row) => {
      const prev = bySnapshot.get(row.snapshot_id)
      if (!prev || String(row.observed_at) > String(prev.observed_at)) bySnapshot.set(row.snapshot_id, row)
    })
  return Array.from(bySnapshot.values())
    .sort((a, b) => String(a.observed_at).localeCompare(String(b.observed_at)))
}

// 时间范围过滤：以该指标最新快照为基准截取（范围只影响横轴窗口）
function inRange(series) {
  if (!series.length) return series
  const r = RANGES.find((item) => item.key === range.value)
  if (!r || r.hours == null) return series
  const latest = Date.parse(series[series.length - 1].observed_at)
  if (!Number.isFinite(latest)) return series
  const cut = latest - r.hours * 3_600_000
  return series.filter((row) => Date.parse(row.observed_at) >= cut)
}

const rangeRows = computed(() => inRange(seriesOf(variable.value)))
const series = computed(() => rangeRows.value.filter((row) => row.observation_status === 'ok' && row.value != null))
// 仅统计所选时间范围内未参与连线的快照数（缺测/质控不合格），范围外的不计
const skippedTotal = computed(() => rangeRows.value.length - series.value.length)
const skipped = computed(() => Array.from({ length: Math.max(0, skippedTotal.value) }))

// ---------- 刻度域与坐标映射（真实数值范围 → 1/2/5 步进取整刻度，网格 3-4 条） ----------
function niceDomain(min, max, target = 3) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null
  if (min === max) {
    // 常值序列：给一个小的对称带，保证可画且刻度可读
    const pad = Math.abs(min) * 0.12 || 0.5
    min -= pad
    max += pad
  }
  const mag = 10 ** Math.floor(Math.log10((max - min) / target))
  let lo = min
  let hi = max
  let step = mag
  for (const ladder of [1, 2, 5, 10, 20, 50, 100]) {
    step = ladder * mag
    lo = Math.floor(min / step) * step
    hi = Math.ceil(max / step) * step
    if ((hi - lo) / step <= 3) break
  }
  const count = Math.round((hi - lo) / step)
  const ticks = []
  for (let i = 0; i <= count; i++) ticks.push(Number((lo + i * step).toPrecision(12)))
  return { lo, hi, step, ticks }
}

function yOf(v, dom, vh, padT, padB) {
  const f = (v - dom.lo) / (dom.hi - dom.lo || 1)
  return padT + (1 - f) * (vh - padT - padB)
}

function unitOf(code) {
  const row = allRows.value.find((r) => r.variable_code === code && r.unit)
  return (row && row.unit) || ''
}

const yDomain = computed(() => {
  const vals = series.value.map((r) => Number(r.value))
  if (!vals.length) return null
  return niceDomain(Math.min(...vals), Math.max(...vals), 3)
})

const points = computed(() => {
  const dom = yDomain.value
  if (!dom) return []
  const rows = series.value
  const n = rows.length
  return rows.map((row, i) => {
    const value = Number(row.value)
    return {
      t: row.observed_at,
      value,
      x: n === 1 ? W / 2 : PAD_X + (i / (n - 1)) * (W - PAD_X * 2),
      y: yOf(value, dom, H, PAD_T, PAD_B)
    }
  })
})

const yTicksMain = computed(() => {
  const dom = yDomain.value
  if (!dom) return []
  return dom.ticks.map((v) => {
    const y = yOf(v, dom, H, PAD_T, PAD_B)
    return { y, top: `${((y / H) * 100).toFixed(2)}%`, text: fmtMeasure(v) }
  })
})

const polylinePoints = computed(() => points.value.map((p) => `${p.x},${p.y}`).join(' '))

const areaPath = computed(() => {
  const pts = points.value
  if (pts.length < 2) return ''
  const line = pts.map((p) => `L ${p.x},${p.y}`).join(' ')
  return `M ${pts[0].x},${H} ${line} L ${pts[pts.length - 1].x},${H} Z`
})

// ---------- Grafana 式统计参考线：max/min 短虚线 + avg 点划线，只由真实点计算 ----------
const statsBase = computed(() => {
  const pts = points.value
  const dom = yDomain.value
  if (!dom || pts.length < 2) return []
  const vals = pts.map((p) => p.value)
  const sum = vals.reduce((acc, v) => acc + v, 0)
  return [
    { key: 'max', y: yOf(Math.max(...vals), dom, H, PAD_T, PAD_B) },
    { key: 'avg', y: yOf(sum / vals.length, dom, H, PAD_T, PAD_B) },
    { key: 'min', y: yOf(Math.min(...vals), dom, H, PAD_T, PAD_B) }
  ]
})

// 统计标注文字：右内侧等宽小字；渲染高度固定 150px，锚点间距 ≥9.5%（≈14px）防压盖；
// 贴顶的标注改放到线下方，避免溢出图外。
const statLabels = computed(() => {
  const pts = points.value
  const dom = yDomain.value
  if (!dom || pts.length < 2) return []
  const vals = pts.map((p) => p.value)
  const sum = vals.reduce((acc, v) => acc + v, 0)
  const items = [
    { key: 'max', v: Math.max(...vals) },
    { key: 'avg', v: sum / vals.length },
    { key: 'min', v: Math.min(...vals) }
  ]
    .map((d) => ({
      key: d.key,
      text: `${d.key} ${fmtMeasure(d.v)}`,
      yPct: (yOf(d.v, dom, H, PAD_T, PAD_B) / H) * 100,
      below: (yOf(d.v, dom, H, PAD_T, PAD_B) / H) * 100 < 12
    }))
    .sort((a, b) => a.yPct - b.yPct)
  for (let i = 1; i < items.length; i++) {
    if (items[i].yPct - items[i - 1].yPct < 9.5) items[i].yPct = items[i - 1].yPct + 9.5
  }
  return items.map((it) => ({ key: it.key, text: it.text, top: `${it.yPct.toFixed(2)}%`, below: it.below }))
})

// 末点脉冲：序列最后一个真实观测点（<2 点不画图，自然不画）
const lastPointMain = computed(() => {
  const pts = points.value
  if (pts.length < 2) return null
  const p = pts[pts.length - 1]
  return { left: `${((p.x / W) * 100).toFixed(2)}%`, top: `${((p.y / H) * 100).toFixed(2)}%` }
})

// ---------- x 轴内部时间刻度：等分候选 + 相邻最小间距贪心抽稀（MIN_TICK_GAP 教训） ----------
const MIN_TICK_GAP_PCT = 12
const xTicks = computed(() => {
  const pts = points.value
  if (pts.length < 4) return []
  const inner = pts.slice(1, -1)
  const stepIdx = Math.max(1, Math.floor(inner.length / 4))
  const picked = []
  for (let i = 0; i < inner.length; i += stepIdx) picked.push(inner[i])
  const out = []
  let last = -Infinity
  for (const p of picked) {
    const pct = (p.x / W) * 100
    if (pct < 8 || pct > 88) continue
    if (pct - last >= MIN_TICK_GAP_PCT) {
      out.push({ pct, t: p.t })
      last = pct
    }
  }
  return out
})

const xSpanHours = computed(() => {
  const pts = points.value
  if (pts.length < 2) return 0
  const a = Date.parse(pts[0].t)
  const b = Date.parse(pts[pts.length - 1].t)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0
  return (b - a) / 3_600_000
})

function tickStamp(iso) {
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return formatStamp(iso)
  return xSpanHours.value <= 26 ? `${m[4]}:${m[5]}` : `${m[2]}-${m[3]}`
}

// ---------- 对比模式小图（各自真实域 + 右侧刻度标注，更淡的渐变面积） ----------
const compareCharts = computed(() =>
  compareVars.value.map((code, si) => {
    const rows = inRange(seriesOf(code)).filter((r) => r.observation_status === 'ok' && r.value != null)
    const raw = rows.map((r) => ({ t: r.observed_at, value: Number(r.value) }))
    const vals = raw.map((p) => p.value)
    const dom = raw.length >= 2 ? niceDomain(Math.min(...vals), Math.max(...vals), 2) : null
    const n = raw.length
    const xy = raw.map((p, i) => ({
      t: p.t,
      value: p.value,
      x: n === 1 ? W / 2 : MULTI_PAD_X + (i / (n - 1)) * (W - MULTI_PAD_X * 2),
      y: dom ? yOf(p.value, dom, MULTI_H, MULTI_PAD, MULTI_PAD) : MULTI_H / 2
    }))
    const last = xy.length ? xy[xy.length - 1] : null
    const unit = unitOf(code)
    return {
      code,
      label: variableLabel(code),
      color: COMPARE_COLORS[si] || COMPARE_COLORS[0],
      unit,
      points: xy,
      polyline: xy.map((p) => `${p.x},${p.y}`).join(' '),
      area:
        xy.length >= 2
          ? `M ${xy[0].x},${MULTI_H} ${xy.map((p) => `L ${p.x},${p.y}`).join(' ')} L ${xy[xy.length - 1].x},${MULTI_H} Z`
          : '',
      ticks: dom
        ? dom.ticks.map((v) => {
            const y = yOf(v, dom, MULTI_H, MULTI_PAD, MULTI_PAD)
            return { y, top: `${((y / MULTI_H) * 100).toFixed(2)}%`, text: fmtMeasure(v) }
          })
        : [],
      lastStyle: last ? { left: `${((last.x / W) * 100).toFixed(2)}%`, top: `${((last.y / MULTI_H) * 100).toFixed(2)}%` } : null,
      latestText: last ? `${last.value}${unit ? ` ${unit}` : ''}` : '—'
    }
  })
)

const titleText = computed(() => {
  const name = props.stationName || '站点'
  return `${name} · ${variableLabel(variable.value)}历史趋势`
})
const compareTitleText = computed(() => {
  const name = props.stationName || '站点'
  const labels = compareVars.value.map((c) => variableLabel(c)).join(' / ')
  return labels ? `${name} · ${labels} 对比` : `${name} · 指标对比`
})

function isActive(code) {
  return compareMode.value ? compareVars.value.includes(code) : variable.value === code
}

// 对比模式第 n 个选中指标的系列色（与 chip 色点、小图图例一致）
function seriesColorOf(code) {
  const at = compareVars.value.indexOf(code)
  return COMPARE_COLORS[at] || COMPARE_COLORS[0]
}

function pickVariable(code) {
  if (!compareMode.value) {
    variable.value = code
    return
  }
  const at = compareVars.value.indexOf(code)
  if (at >= 0) compareVars.value.splice(at, 1)
  else if (compareVars.value.length < 3) compareVars.value.push(code)
}

function toggleCompare() {
  compareMode.value = !compareMode.value
  if (compareMode.value && !compareVars.value.length) {
    compareVars.value = [variable.value]
  }
  if (!compareMode.value) {
    variable.value = compareVars.value[0] || variable.value
    compareVars.value = []
  }
}

// ---------- 悬停十字线 + tooltip：pointer 事件（鼠标/触屏通用），最近真实点吸附，不插值 ----------
const hover = ref(null) // { key, idx, px, py, pw, ph }

function chartByKey(key) {
  if (key === 'main') {
    return {
      pts: points.value,
      label: variableLabel(variable.value),
      unit: unitOf(variable.value),
      padX: PAD_X,
      vh: H
    }
  }
  const cv = compareCharts.value.find((c) => c.code === key)
  if (!cv) return null
  return { pts: cv.points, label: cv.label, unit: cv.unit, padX: MULTI_PAD_X, vh: MULTI_H }
}

function snapIdx(pts, dataX, padX) {
  const n = pts.length
  if (n < 2) return -1
  const f = ((dataX - padX) / (W - padX * 2)) * (n - 1)
  return Math.min(n - 1, Math.max(0, Math.round(f)))
}

function onPlotMove(key, e) {
  const chart = chartByKey(key)
  if (!chart || chart.pts.length < 2) return
  const rect = e.currentTarget.getBoundingClientRect()
  if (!rect.width) return
  const px = e.clientX - rect.left
  const py = e.clientY - rect.top
  const idx = snapIdx(chart.pts, (px / rect.width) * W, chart.padX)
  if (idx < 0) return
  hover.value = { key, idx, px, py, pw: rect.width, ph: rect.height }
}

function onPlotLeave(key) {
  if (hover.value && hover.value.key === key) hover.value = null
}

function onPlotUp(e) {
  // 触屏/笔：抬手即收起；鼠标悬停走 pointerleave
  if (e.pointerType !== 'mouse') hover.value = null
}

function crossXFor(key) {
  const hv = hover.value
  if (!hv || hv.key !== key) return null
  const chart = chartByKey(key)
  if (!chart || hv.idx >= chart.pts.length) return null
  return chart.pts[hv.idx].x
}

const hoverInfo = computed(() => {
  const hv = hover.value
  if (!hv) return null
  const chart = chartByKey(hv.key)
  if (!chart || hv.idx >= chart.pts.length) return null
  const p = chart.pts[hv.idx]
  const xPct = (hv.px / hv.pw) * 100
  const yPct = (hv.py / hv.ph) * 100
  // 浮层跟随指针，贴右缘向左翻转、贴顶向下翻转
  const tx = xPct > 62 ? 'calc(-100% - 12px)' : '12px'
  const ty = yPct < 26 ? '12px' : '-50%'
  return {
    key: hv.key,
    dot: { left: `${((p.x / W) * 100).toFixed(2)}%`, top: `${((p.y / chart.vh) * 100).toFixed(2)}%` },
    tipStyle: { left: `${xPct.toFixed(2)}%`, top: `${yPct.toFixed(2)}%`, transform: `translate(${tx}, ${ty})` },
    time: formatStamp(p.t),
    text: `${chart.label} ${fmtMeasure(p.value)}${chart.unit ? ` ${chart.unit}` : ''}`
  }
})

async function load() {
  if (!props.stationId) return
  state.value = 'loading'
  allRows.value = []
  try {
    // 全量快照回看：起始日取历史窗口起点，end 用本地当天（toISOString 是 UTC，凌晨会差一天）
    allRows.value = await fetchStationObservations(props.stationId, {
      window: 'range',
      start: OBS_HISTORY_START,
      end: todayLocalDate()
    })
    // 默认选第一个有可用观测的指标（上游 chla/藻密度缺测普遍，固定默认会频繁空图）
    const hasOk = new Set(
      allRows.value.filter((r) => r.observation_status === 'ok' && r.value != null).map((r) => r.variable_code)
    )
    if (!compareMode.value && !hasOk.has(variable.value)) {
      const firstOk = TREND_VARIABLES.find((v) => hasOk.has(v.code))
      if (firstOk) variable.value = firstOk.code
    }
    state.value = 'ok'
  } catch {
    state.value = 'error'
  }
}

watch(() => props.stationId, load, { immediate: true })
</script>

<style scoped>
.stp { display: flex; flex-direction: column; gap: 5px; }
.stp-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.stp-range { display: inline-flex; gap: 4px; }
.stp-vars { display: flex; flex-wrap: wrap; gap: 4px; }
.stp-title {
  margin: 2px 0 0;
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text-primary);
}

/* 对比模式选中 chip 的系列色点（与折线/图例同令牌） */
.stp-chip-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 5px;
  background: var(--chip-c, var(--color-primary));
}

.stp-chart { display: grid; gap: 4px; }
.stp-plotrow { display: flex; align-items: flex-start; gap: 6px; --series-c: var(--color-primary); }
.stp-plotcol {
  flex: 1;
  min-width: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  cursor: crosshair;
  /* 触屏：横向拖动用于查看十字线，纵向仍可滚动页面 */
  touch-action: pan-y;
}
.stp-plotcol svg { width: 100%; height: 150px; display: block; }
.stp-yaxis { position: relative; flex: none; width: 56px; height: 150px; }
.stp-ytick {
  position: absolute;
  right: 0;
  transform: translateY(-50%);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.1;
  color: var(--text-muted);
  white-space: nowrap;
}

.stp-grid { stroke: color-mix(in srgb, var(--border-subtle) 40%, transparent); stroke-width: 1; pointer-events: none; }
.stp-area { stroke: none; pointer-events: none; }
.stp-line { fill: none; stroke: var(--series-c, var(--color-primary)); stroke-width: 2; }
.stp-dot { fill: var(--series-c, var(--color-primary)); }
.stp-ref { stroke: color-mix(in srgb, var(--text-secondary) 42%, transparent); stroke-width: 1; pointer-events: none; }
.stp-ref--max,
.stp-ref--min { stroke-dasharray: 5 4; }
.stp-ref--avg { stroke-dasharray: 8 3 2 3; }
.stp-cross { stroke: color-mix(in srgb, var(--text-secondary) 60%, transparent); stroke-width: 1; pointer-events: none; }

/* 统计标注文字：图右内侧，等宽 10px，微底衬保证三主题可读 */
.stp-ann {
  position: absolute;
  right: 4px;
  transform: translateY(calc(-100% - 2px));
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.2;
  color: var(--text-muted);
  background: color-mix(in srgb, var(--surface-panel-raised) 80%, transparent);
  padding: 1px 4px;
  border-radius: 4px;
  white-space: nowrap;
  pointer-events: none;
  z-index: 2;
}
.stp-ann--below { transform: translateY(3px); }

/* 末点脉冲：外圈扩散 2.2s 循环（reduced-motion 降级为静态外圈） */
.stp-pulse {
  position: absolute;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--series-c, var(--color-primary));
  box-shadow: 0 0 6px var(--series-c, var(--color-primary));
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 2;
}
.stp-pulse::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  border: 2px solid var(--series-c, var(--color-primary));
  animation: stp-ring 2.2s ease-out infinite;
}
@keyframes stp-ring {
  0% { transform: scale(0.9); opacity: 0.8; }
  70%, 100% { transform: scale(3); opacity: 0; }
}

/* 悬停最近真实点高亮 + 数值浮层 */
.stp-hover-dot {
  position: absolute;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--series-c, var(--color-primary));
  border: 2px solid var(--surface-page);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--series-c, var(--color-primary)) 30%, transparent);
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 3;
}
.stp-tip {
  position: absolute;
  z-index: 6;
  display: grid;
  gap: 1px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 5px 8px;
  box-shadow: var(--shadow-sm);
  white-space: nowrap;
  pointer-events: none;
}
.stp-tip-time { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
.stp-tip-val { font-family: var(--font-mono); font-size: 11.5px; color: var(--text-primary); }

.stp-xticks { position: relative; height: 13px; margin-top: 2px; }
.stp-xtick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.2;
  color: var(--text-muted);
  white-space: nowrap;
}

.stp-axis {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

.stp-multi { display: grid; gap: 8px; }
.stp-multi-item {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 6px 8px;
  display: grid;
  gap: 3px;
}
.stp-multi-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.stp-multi-name { font-size: 11.5px; font-weight: 650; color: var(--text-secondary); }
.stp-multi-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 3px;
  margin-right: 5px;
  background: var(--series-c, var(--color-primary));
}
.stp-multi-latest { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); }
.stp-plotrow--multi .stp-plotcol svg { height: 56px; }
.stp-yaxis--multi { height: 56px; }
.stp-plotrow--multi .stp-pulse { width: 5px; height: 5px; box-shadow: none; }
.stp-plotrow--multi .stp-pulse::after { border-width: 1.5px; }

/* reduced-motion：脉冲降级为静态实心点 + 静态外圈，无任何循环动画 */
@media (prefers-reduced-motion: reduce) {
  .stp-pulse::after {
    animation: none;
    transform: scale(1.8);
    opacity: 0.35;
  }
}
</style>
