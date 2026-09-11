<template>
  <!-- 七时效扇形图（fan chart）：折线 + 真实分位带 + 选中时效游标。
       几何（x/y 映射、短期合并组、短期/中长期分组）由父级 ForecastResultPanel
       按原同一套计算透传，本组件只负责绘制。 -->
  <div class="hfc">
    <svg viewBox="0 0 420 126" width="100%" height="126" preserveAspectRatio="none" role="img" :aria-label="ariaLabel">
      <line x1="18" y1="82" x2="402" y2="82" class="frp-trend-axis" />
      <line :x1="scenarioX" :x2="scenarioX" y1="8" y2="88" class="frp-trend-split" />
      <!-- 扇形带：只画真实存在的分位锚点；某时效缺分位 → 该处断带，绝不跨缺口连接造区间 -->
      <path v-for="(seg, i) in bandSegments" :key="`band${i}`" :d="seg" class="frp-trend-band" />
      <!-- 选中时效游标 · 竖线：transform 过渡让高亮在时效切换时平滑移动 -->
      <g v-if="activePoint" class="hfc-cursor" :style="{ transform: `translate(${activePoint.x}px, 0px)` }">
        <line x1="0" y1="8" x2="0" y2="88" class="hfc-cursor-line" />
      </g>
      <polyline v-if="lineShort" :points="lineShort" class="frp-trend-line" />
      <polyline v-if="lineScenario" :points="lineScenario" class="frp-trend-line frp-trend-line--scenario" />
      <!-- 短期四档映射同一月标签，数值按定义相同：不画成四个独立点，合并为一段同月区间 -->
      <template v-if="shortGroup">
        <rect
          :x="shortGroup.x1" :y="shortGroup.y - 5"
          :width="shortGroup.x2 - shortGroup.x1" height="10"
          rx="5" class="frp-trend-group" data-role="short-merged-group"
        ><title>{{ shortGroup.title }}</title></rect>
        <text
          :x="(shortGroup.x1 + shortGroup.x2) / 2" y="113"
          text-anchor="middle" class="frp-trend-note" data-role="short-merged-label"
        >同月短期结果 · 四档同值</text>
      </template>
      <g v-else v-for="p in shortPoints" :key="`sh${p.horizon}`">
        <circle :cx="p.x" :cy="p.y" r="4" class="frp-trend-point" :data-origin="p.originKey" :data-scenario="String(p.scenario)"><title>{{ p.title }}</title></circle>
      </g>
      <g v-for="p in scenarioPoints" :key="`sc${p.horizon}`">
        <circle :cx="p.x" :cy="p.y" r="4" class="frp-trend-point" :data-origin="p.originKey" :data-scenario="String(p.scenario)" :data-station-resolution="String(p.stationResolution)"><title>{{ p.title }}</title></circle>
        <text :x="p.x" y="113" text-anchor="middle" class="frp-trend-note" :data-resolution="String(p.stationResolution)">{{ p.shortNote }}</text>
      </g>
      <g v-for="p in points" :key="`l${p.horizon}`">
        <text :x="p.x" y="97" text-anchor="middle" class="frp-trend-label">+{{ p.horizon }}</text>
      </g>
      <!-- 选中时效游标 · 点：叠在折线与数据点之上，只是选择指示，不表达新数据点 -->
      <g v-if="activePoint" class="hfc-cursor" :style="{ transform: `translate(${activePoint.x}px, ${activePoint.y}px)` }">
        <circle r="7" class="hfc-cursor-halo" />
        <circle r="3.5" class="hfc-cursor-core" />
      </g>
      <text x="22" y="13" class="frp-trend-caption">短期</text>
      <text :x="scenarioX + 6" y="13" class="frp-trend-caption">中长期</text>
    </svg>
    <!-- 图注：仅当分位带真实渲染时显示，且只写中性事实（带的分位口径），不夸大不承诺 -->
    <p v-if="bandCaption && hasBand" class="hfc-bandnote">{{ bandCaption }}</p>
  </div>
</template>

<script setup>
// 七时效扇形图：折线下方叠加分位带（实际分位字段以父级透传为准：
// 全湖 = station_aggregate 的 P25–P75 站间分布；站点 = conformal 的 P05–P95 预测区间）。
// 数据诚实红线：
//   - intervals 中为 null 的时效代表「该时效没有真实分位数据」，该处断带（不跨缺口连线）；
//   - 全部时效都无分位 → bandSegments 为空 → 整体不渲染带，图注也不显示；
//   - 平滑只是渲染路径（Catmull-Rom → 三次贝塞尔），曲线仍精确通过每个真实分位锚点，
//     不产生任何内插出的新数值。
import { computed } from 'vue'

const props = defineProps({
  // 折线点（几何已由父级算好）：{ horizon, value, x, y, scenario, originKey, stationResolution, shortNote, title }
  points: { type: Array, default: () => [] },
  // 与 points 等长对齐的分位锚点：null = 该时效无真实分位数据（断带）；
  // 非空 = { horizon, slot, x, yLow, yHigh }（slot 为七时效槽位序号，用于连续性判定）
  intervals: { type: Array, default: () => [] },
  // 当前选中时效（画高亮竖线 + 游标点）
  activeHorizon: { type: Number, default: -1 },
  // 短期/中长期分组与折线（与父级同一几何）
  shortPoints: { type: Array, default: () => [] },
  scenarioPoints: { type: Array, default: () => [] },
  shortGroup: { type: Object, default: null },
  lineShort: { type: String, default: '' },
  lineScenario: { type: String, default: '' },
  scenarioX: { type: Number, default: 238 },
  // 事实性图注（如「带 = P25–P75（站间分布）」）；带未渲染时不显示
  bandCaption: { type: String, default: '' },
  ariaLabel: { type: String, default: '七时效趋势' }
})

const activePoint = computed(() =>
  props.points.find((p) => Number(p.horizon) === Number(props.activeHorizon)) || null
)

// ---- 分位带：连续时效段 → 平滑闭合路径 ----
// 贝塞尔控制点张力系数：越小越贴近折线；0.16 平滑而不明显偏离真实分位包络。
const SMOOTH_T = 0.16

function curveSegments(pts) {
  const segs = []
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1.x + (p2.x - p0.x) * SMOOTH_T
    const c1y = p1.y + (p2.y - p0.y) * SMOOTH_T
    const c2x = p2.x - (p3.x - p1.x) * SMOOTH_T
    const c2y = p2.y - (p3.y - p1.y) * SMOOTH_T
    segs.push(`C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`)
  }
  return segs
}

function bandPath(run) {
  if (run.length < 2) return ''
  const upper = run.map((e) => ({ x: e.x, y: e.yHigh }))
  const lower = run.slice().reverse().map((e) => ({ x: e.x, y: e.yLow }))
  const segs = [
    `M ${upper[0].x.toFixed(2)} ${upper[0].y.toFixed(2)}`,
    ...curveSegments(upper),
    `L ${lower[0].x.toFixed(2)} ${lower[0].y.toFixed(2)}`,
    ...curveSegments(lower),
    'Z'
  ]
  return segs.join(' ')
}

const bandSegments = computed(() => {
  const segs = []
  let run = []
  const flush = () => {
    const d = bandPath(run)
    if (d) segs.push(d)
    run = []
  }
  props.intervals.forEach((entry) => {
    if (!entry) {
      flush()
      return
    }
    // 时效槽位不连续（中间点缺失或该点无分位）：断带，不跨缺口连接
    if (run.length && entry.slot - run[run.length - 1].slot !== 1) flush()
    run.push(entry)
  })
  flush()
  return segs
})
const hasBand = computed(() => bandSegments.value.length > 0)
</script>

<style scoped>
/* 与父面板原内联 SVG 同源的视觉（原 ForecastResultPanel 中该 SVG 的样式随组件迁入） */
.frp-trend-axis { stroke: rgba(127, 147, 168, 0.35); stroke-width: 1; }
.frp-trend-split { stroke: var(--risk-medium, #f5b45d); stroke-width: 1; stroke-dasharray: 4 3; }
/* 扇形带：半透明主色（随主题 --color-primary 变化） */
.frp-trend-band {
  fill: color-mix(in srgb, var(--color-primary, #38bdf8) 15%, transparent);
  stroke: color-mix(in srgb, var(--color-primary, #38bdf8) 36%, transparent);
  stroke-width: 1;
}
.frp-trend-line { fill: none; stroke: var(--color-primary); stroke-width: 2; }
/* 情景推演段（T+30 起）：虚线 + 警示色，与短期真实预测在视觉上明确分口 */
.frp-trend-line--scenario {
  stroke: #e2a65a;
  stroke-dasharray: 5 4;
  stroke-opacity: 0.85;
}
.frp-trend-point { fill: #5fd6a4; stroke: var(--surface-panel); stroke-width: 1.5; }
.frp-trend-point[data-origin='cv'] { fill: #a78bfa; }
.frp-trend-point[data-origin='legacy'] { fill: var(--risk-medium, #f5b45d); }
.frp-trend-point[data-origin='derived'] { fill: #38bdf8; }
.frp-trend-point[data-origin='climatology'] { fill: #e2a65a; }
/* 合并后的短期段：一段同月区间，而不是四个看起来独立的预测点 */
.frp-trend-group {
  fill: color-mix(in srgb, #5fd6a4 22%, transparent);
  stroke: #5fd6a4;
  stroke-width: 1;
}
.frp-trend-label,
.frp-trend-caption { fill: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
.frp-trend-note { fill: var(--text-muted); font-family: var(--font-mono); font-size: 8px; }
.frp-trend-note[data-resolution='false'] { fill: #d9a55e; }
.frp-trend-note[data-resolution='true'] { fill: #57b98d; }

/* 选中时效游标：竖线 + 点，transform 过渡实现时效切换时的平滑移动（时效联动） */
.hfc-cursor { transition: transform 0.45s cubic-bezier(0.22, 0.61, 0.36, 1); }
.hfc-cursor-line { stroke: var(--color-primary); stroke-width: 1; stroke-dasharray: 2 3; opacity: 0.7; }
.hfc-cursor-halo { fill: none; stroke: var(--color-primary); stroke-width: 1.5; opacity: 0.85; }
.hfc-cursor-core { fill: var(--color-primary); stroke: var(--surface-panel); stroke-width: 1.5; }

/* 分位带图注：事实性中性小字（仅在带真实渲染时由模板显示） */
.hfc-bandnote {
  margin: 2px 0 0;
  font-family: var(--font-mono);
  font-size: 8.5px;
  line-height: 1.4;
  color: var(--text-muted);
}

@media (prefers-reduced-motion: reduce) {
  .hfc-cursor {
    transition: none;
  }
}
</style>
