<template>
  <section class="rcc-kpi" aria-label="关键指标（全湖均值与短期趋势）">
    <div class="rcc-head">
      <h2>关键指标</h2>
      <span class="rcc-card-tag">全湖均值 · 环比上一快照</span>
    </div>

    <template v-if="summary">
      <!-- 全湖 Chl-a 快照 sparkline：仅当 snapshots 中 ≥2 个真实非空 chla_mean 时渲染（不造值） -->
      <template v-if="sparkGeom">
        <div class="rcc-spark" role="img" :aria-label="sparkAria">
          <svg viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient :id="gradId" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style="stop-color: var(--color-primary); stop-opacity: 0.34"></stop>
                <stop offset="100%" style="stop-color: var(--color-primary); stop-opacity: 0.02"></stop>
              </linearGradient>
            </defs>
            <path class="rcc-spark-area" :d="sparkGeom.area" :fill="`url(#${gradId})`"></path>
            <path class="rcc-spark-line" :d="sparkGeom.line" vector-effect="non-scaling-stroke"></path>
          </svg>
          <i
            v-for="(p, i) in sparkGeom.pts"
            :key="i"
            class="rcc-spark-dot"
            :class="{ 'rcc-spark-dot--end': i === sparkGeom.pts.length - 1 }"
            :style="{ left: p.x + '%', top: p.y + 'px' }"
          ></i>
        </div>
        <div class="rcc-spark-meta">
          <span>近 {{ sparkCount }} 次快照 · 全湖均值走势</span>
          <strong>最新 {{ sparkLatestText }} μg/L</strong>
        </div>
      </template>

      <!-- 5 行 KPI：值翻牌 + 趋势 chip -->
      <ul class="rcc-kpi-list">
        <li v-for="row in kpiRows" :key="row.code">
          <span class="rcc-kpi-dot" :style="{ background: row.dot }" aria-hidden="true"></span>
          <span class="rcc-kpi-label">{{ row.label }}</span>
          <small class="rcc-kpi-unit">{{ row.unit }}</small>
          <strong class="rcc-kpi-value">{{ row.value }}</strong>
          <span class="rcc-kpi-trend" :class="`rcc-trend--${row.chip.tone}`">
            <span aria-hidden="true">{{ row.chip.arrow }} {{ row.chip.text }}</span>
            <span class="rcc-sr-only">{{ row.chip.sr }}</span>
          </span>
        </li>
      </ul>

      <!-- 口径注记（文案逐字保持，动态填充） -->
      <p class="rcc-kpi-note">均值仅统计报数站（chla {{ chlaCount }}/{{ stationTotal }} 站），缺测不参与。</p>
    </template>

    <!-- loading 骨架（等价 stn-list-skeleton 的微光扫描条；aria-hidden） -->
    <div v-else class="rcc-skel-root" aria-hidden="true">
      <span class="rcc-skel rcc-skel--strip"></span>
      <span
        v-for="i in 5"
        :key="i"
        class="rcc-skel rcc-skel--row"
        :style="i === 5 ? { width: '64%' } : null"
      ></span>
      <span class="rcc-skel rcc-skel--note"></span>
    </div>
  </section>
</template>

<script setup>
// ============================================================
// KpiCard · 综合驾驶舱「关键指标」卡升级版（C1）
// ------------------------------------------------------------
// 数据契约（services/realtime.js · observed 轨）：
//   summary.means      = { [code]: { value, count } }
//   summary.trends     = { [code]: { direction: 'up'|'down'|'flat', delta_pct } }
//   summary.station_total
//   snapshots          = timeline.snapshots 数组（按时间序），每项含
//                        chla_mean（真实全湖叶绿素均值，可能为 null）
// 升级点：
//   1. 5 行 KPI 数值翻牌（useCountUpText：终帧严格 = 真实值，
//      reduced-motion 直落终值）；趋势 chip 照抄 trendChip 三色令牌，
//      方向箭头字符（↑/↓/→）仅装饰（aria-hidden），方向语义由 sr-only 文字承担。
//   2. 全湖 Chl-a 快照 sparkline（kepler.gl 分布条思路）：仅 ≥2 个非空
//      chla_mean 时渲染——主色渐变面积 + 折线 + 逐点小圆点 + 末端高亮点，
//      下方中性小字「近 N 次快照 · 全湖均值」（N = 实际点数）与最新值。
//   3. 卡底口径注记逐字保持，count/station_total 动态填充。
// 数据诚实：<2 个有效点整条不渲染；sparkline 只画真实非空 chla_mean。
// ============================================================
import { computed } from 'vue'
import { useCountUpText } from '../../composables/stationCountUp.js'
import { fmtMeasure, trendChip } from '../../services/realtime.js'

const props = defineProps({
  /** /api/v1/realtime/summary 汇总数据；null 时渲染 loading 骨架 */
  summary: { type: Object, default: null },
  /** timeline.snapshots 数组（按时间序），每项含 chla_mean（可能为 null） */
  snapshots: { type: Array, default: () => [] }
})

// 渐变 id 每实例唯一，避免同页多实例 <defs> id 冲突
const gradId = `rcc-spark-fill-${Math.random().toString(36).slice(2, 8)}`

// ---------- 5 行 KPI（defs 与点色照抄 Cockpit.vue kpiRows） ----------
const KPI_DEFS = [
  { code: 'chlorophyll_a', label: '叶绿素 a', unit: 'μg/L', dot: '#5fd6a4' },
  { code: 'dissolved_oxygen', label: '溶解氧', unit: 'mg/L', dot: '#7ec8ff' },
  { code: 'total_phosphorus', label: '总磷', unit: 'mg/L', dot: '#f5b45d' },
  { code: 'total_nitrogen', label: '总氮', unit: 'mg/L', dot: '#ff8a8a' },
  { code: 'ammonia_nitrogen', label: '氨氮', unit: 'mg/L', dot: '#b28aff' }
]

// 值口径照抄 Cockpit.vue kpiRows：means[code].value 经 fmtMeasure；缺测 '—'
const kpiSource = (code) =>
  computed(() => {
    const v = props.summary?.means?.[code]?.value
    return v != null ? fmtMeasure(v) : '—'
  })

// 每行一个翻牌（行数固定 5，setup 期静态创建，符合 composable 调用约定）
const displays = {
  chlorophyll_a: useCountUpText(kpiSource('chlorophyll_a')),
  dissolved_oxygen: useCountUpText(kpiSource('dissolved_oxygen')),
  total_phosphorus: useCountUpText(kpiSource('total_phosphorus')),
  total_nitrogen: useCountUpText(kpiSource('total_nitrogen')),
  ammonia_nitrogen: useCountUpText(kpiSource('ammonia_nitrogen'))
}

// 趋势 chip：trendChip 输出「箭头 + 数值/持平」，此处拆成装饰箭头（aria-hidden）
// 与可见文字；读屏改由 sr-only 完整语义句承担，避免「↑」被读出或语义丢失
function toChip(trend) {
  const chip = trendChip(trend)
  const arrow = chip.text.slice(0, 1) // ↑ / ↓ / →
  const rest = chip.text.slice(1).trim() // '12%' / '持平'
  const word = chip.tone === 'up' ? '上升' : chip.tone === 'down' ? '下降' : '持平'
  return {
    tone: chip.tone,
    arrow,
    text: rest,
    sr: chip.tone === 'flat' ? `较上一快照${word}` : `较上一快照${word} ${rest}`
  }
}

const kpiRows = computed(() =>
  KPI_DEFS.map(({ code, label, unit, dot }) => ({
    code,
    label,
    unit,
    dot,
    value: displays[code].value,
    chip: toChip(props.summary?.trends?.[code])
  }))
)

// ---------- 全湖 Chl-a 快照 sparkline（只取真实非空 chla_mean，按时间序） ----------
const sparkValues = computed(() => {
  const snaps = Array.isArray(props.snapshots) ? props.snapshots : []
  const vals = []
  snaps.forEach((s) => {
    const v = s?.chla_mean
    const n = Number(v)
    if (v != null && Number.isFinite(n)) vals.push(n)
  })
  return vals
})
const sparkCount = computed(() => sparkValues.value.length)

// viewBox「0 0 100 26」+ preserveAspectRatio="none"：横向铺满卡片、纵向 1:1
// （SVG 高固定 26px），折线用 non-scaling-stroke 保持线宽；数据点小圆点改用
// 绝对定位 HTML 元素（top 即 SVG y 坐标的像素映射），避免横向拉伸把圆点压成椭圆。
const SPARK_TOP = 3
const SPARK_BOTTOM = 23
const sparkGeom = computed(() => {
  const vals = sparkValues.value
  if (vals.length < 2) return null // <2 个有效点：整条不渲染，不造值
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min
  const yOf = (v) =>
    span === 0 ? (SPARK_TOP + SPARK_BOTTOM) / 2 : SPARK_BOTTOM - ((v - min) / span) * (SPARK_BOTTOM - SPARK_TOP)
  const pts = vals.map((v, i) => ({ x: (i / (vals.length - 1)) * 100, y: yOf(v) }))
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(' ')
  const area = `${line} L100 26 L0 26 Z`
  return { pts, line, area }
})

const sparkLatestText = computed(() => {
  const vals = sparkValues.value
  return vals.length ? fmtMeasure(vals[vals.length - 1]) : '—'
})
const sparkAria = computed(
  () => `全湖叶绿素 a 均值近 ${sparkCount.value} 次快照走势，最新 ${sparkLatestText.value} μg/L`
)

// ---------- 口径注记（文案逐字保持，动态填充） ----------
const chlaCount = computed(() => props.summary?.means?.chlorophyll_a?.count ?? 0)
const stationTotal = computed(() => props.summary?.station_total ?? '—')
</script>

<style scoped>
/* —— 视觉容器：与现浮层卡一致（14px 圆角 / raised 面板 / 1px 细边）—— */
.rcc-kpi {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel-raised);
  padding: 12px 14px;
}
.rcc-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.rcc-head h2 { margin: 0; font-size: 14px; color: var(--text-primary); }
.rcc-card-tag { font-size: 10.5px; color: var(--text-muted); }

/* —— Chl-a 快照 sparkline —— */
.rcc-spark { position: relative; height: 26px; margin: 2px 0 6px; }
.rcc-spark svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.rcc-spark-area { stroke: none; }
.rcc-spark-line {
  fill: none;
  stroke: var(--color-primary);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.rcc-spark-dot {
  position: absolute;
  width: 5px;
  height: 5px;
  margin: -2.5px 0 0 -2.5px;
  border-radius: 999px;
  background: var(--color-primary);
}
.rcc-spark-dot--end {
  width: 7px;
  height: 7px;
  margin: -3.5px 0 0 -3.5px;
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--color-primary) 24%, transparent),
    0 0 8px color-mix(in srgb, var(--color-primary) 55%, transparent);
}
.rcc-spark-meta { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin: 0 0 8px; }
.rcc-spark-meta span { font-size: 10px; color: var(--text-muted); }
.rcc-spark-meta strong { font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); }

/* —— 5 行 KPI —— */
.rcc-kpi-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.rcc-kpi-list li { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto auto; align-items: center; gap: 8px; }
.rcc-kpi-dot { width: 8px; height: 8px; border-radius: 999px; }
.rcc-kpi-label { font-size: 12.5px; color: var(--text-primary); }
.rcc-kpi-unit { font-size: 10px; color: var(--text-muted); }
.rcc-kpi-value { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); justify-self: end; }
.rcc-kpi-trend { font-family: var(--font-mono); font-size: 11px; justify-self: end; white-space: nowrap; text-align: right; }
.rcc-trend--up { color: var(--risk-critical, #ef4444); }
.rcc-trend--down { color: var(--risk-low, #22c55e); }
.rcc-trend--flat { color: var(--text-muted); }
.rcc-kpi-note { margin: 8px 0 0; font-size: 10px; color: var(--text-muted); line-height: 1.6; }

/* —— 读屏专用（方向语义文字） —— */
.rcc-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

/* —— loading 骨架（微光扫描条，aria-hidden）—— */
.rcc-skel-root { display: grid; gap: 8px; }
.rcc-skel--strip { display: block; height: 26px; border-radius: 8px; }
.rcc-skel--row { display: block; height: 16px; border-radius: 6px; }
.rcc-skel--note { display: block; height: 12px; width: 72%; border-radius: 6px; }
.rcc-skel {
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--text-muted) 12%, transparent),
    color-mix(in srgb, var(--text-muted) 22%, transparent),
    color-mix(in srgb, var(--text-muted) 12%, transparent));
  background-size: 200% 100%;
  animation: rcc-skel-scan 1.4s ease-in-out infinite;
}
@keyframes rcc-skel-scan {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* —— reduced-motion：骨架停止扫描（组件内其余元素本就无动画） —— */
@media (prefers-reduced-motion: reduce) {
  .rcc-skel { animation: none; }
}
</style>
