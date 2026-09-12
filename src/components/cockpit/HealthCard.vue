<template>
  <section class="rcc-health" aria-label="湖体健康">
    <div class="rcc-head">
      <h2>湖体健康</h2>
      <span v-if="summary" class="rcc-grade" :class="`rcc-grade--${gradeKey}`">
        {{ healthGradeText(summary?.health?.grade) }}
      </span>
      <span v-else class="rcc-skel rcc-skel--pill" aria-hidden="true"></span>
    </div>

    <!-- 数据就绪：环形仪 + 分项条 + 5 个统计数 -->
    <template v-if="summary">
      <div class="rcc-body">
        <div class="rcc-gauge" role="img" :aria-label="`湖体健康分 ${summary?.health?.score ?? '—'}`">
          <svg viewBox="0 0 120 120">
            <circle class="rcc-gauge-track" cx="60" cy="60" r="52" />
            <circle
              class="rcc-gauge-value"
              :class="`rcc-gauge-value--${gradeKey}`"
              cx="60" cy="60" r="52"
              :stroke-dasharray="`${dashShown.toFixed(2)} ${(GAUGE_LEN - dashShown).toFixed(2)}`"
            />
          </svg>
          <div class="rcc-gauge-center">
            <strong>{{ scoreDisplay }}</strong>
          </div>
        </div>
        <div class="rcc-bars">
          <div v-for="bar in healthBars" :key="bar.label" class="rcc-bar-row">
            <span class="rcc-bar-label">{{ bar.label }}</span>
            <span class="rcc-bar-track"><i :style="{ width: bar.pct + '%' }"></i></span>
            <span class="rcc-bar-num">{{ bar.num }}/{{ bar.den }}</span>
          </div>
        </div>
      </div>

      <div class="rcc-stats">
        <div class="rcc-stat">
          <strong>{{ stationDisplay }}</strong><span>监测站</span>
        </div>
        <div class="rcc-stat" :class="{ 'rcc-stat--bad': warnCount > 0 }">
          <strong>{{ warnDisplay }}</strong><span>预警</span>
        </div>
        <div class="rcc-stat"><strong>{{ waterTempDisplay }}</strong><span>°C 水温</span></div>
        <div class="rcc-stat"><strong>{{ chlaMeanDisplay }}</strong><span>μg/L Chl-a</span></div>
        <div class="rcc-stat"><strong>{{ doDisplay }}</strong><span>mg/L DO</span></div>
      </div>
    </template>

    <!-- loading 骨架（等价 stn-list-skeleton 的微光扫描条；页面级类不可复用，本地等价实现） -->
    <div v-else class="rcc-skel-root" aria-hidden="true">
      <div class="rcc-skel-gaugerow">
        <span class="rcc-skel rcc-skel--ring"></span>
        <span class="rcc-skel-barcol">
          <span v-for="i in 4" :key="i" class="rcc-skel rcc-skel--bar" :style="i === 4 ? { width: '58%' } : null"></span>
        </span>
      </div>
      <div class="rcc-skel-statrow">
        <span v-for="i in 5" :key="i" class="rcc-skel rcc-skel--stat"></span>
      </div>
    </div>
  </section>
</template>

<script setup>
// ============================================================
// HealthCard · 综合驾驶舱「湖体健康」卡升级版（C1）
// ------------------------------------------------------------
// 数据契约（services/realtime.js · observed 轨）：
//   summary.health  = { grade: 'good'|'fair'|'poor', score: 0-100,
//                       subscores: { class_compliance / algae_normal / completeness:
//                                    { num, den, rate } } }
//   summary.means   = { [code]: { value, count } }
//   summary.trends  = { [code]: { direction: 'up'|'down'|'flat', delta_pct } }
//   summary.station_total / summary.warnings（数组）
// 升级点：
//   1. 环形仪扫光——值环 stroke-dasharray 0 → 目标值 700ms ease-out
//      （首次挂载起扫；score 变化时由 CSS transition 从旧值过渡），
//      环色按 grade 走风险令牌，值环加同色 drop-shadow 微辉光。
//   2. 健康分/5 个统计数翻牌（useCountUpText：reduced-motion 直落终值，
//      终帧严格等于真实值）。
//   3. 分项条宽 240ms ease 过渡（reduced-motion 关闭）。
//   4. 预警数 >0 时数值呼吸脉冲（reduced-motion 静态）。
// 数据诚实：分项条口径照抄 Cockpit.vue healthBars（含「环比持平 = |Δ|<3% 占比」）；
//   统计数口径照抄 rc-stats / fmtMean（means value toFixed(2)）。
// ============================================================
import { computed, onMounted, ref, watch } from 'vue'
import { useCountUpText } from '../../composables/stationCountUp.js'
import { healthGradeText } from '../../services/realtime.js'

const props = defineProps({
  /** /api/v1/realtime/summary 汇总数据；null 时渲染 loading 骨架 */
  summary: { type: Object, default: null }
})

// —— 环形仪（与现卡同构：viewBox 120 / r=52）——
const GAUGE_LEN = 2 * Math.PI * 52

const gaugeTarget = computed(() => {
  const s = Number(props.summary?.health?.score)
  if (!Number.isFinite(s)) return 0
  return (Math.max(0, Math.min(100, s)) / 100) * GAUGE_LEN
})

// 扫光：首次挂载从 0 → 目标值；此后 gaugeTarget 变化（score 变化）时直接赋新值，
// 由 CSS transition 从旧弧长过渡到新弧长。reduced-motion 下 transition 已禁用，
// 赋值即直落终值。
const dashShown = ref(0)
onMounted(() => {
  requestAnimationFrame(() => { dashShown.value = gaugeTarget.value })
})
watch(gaugeTarget, (v) => { dashShown.value = v })

// —— 头部 grade 徽章：文字用真实 grade 换算（缺失时 healthGradeText 给 '—'），
//    色阶 class 仅为视觉映射（good 缺省 = 风险低绿）——
const gradeKey = computed(() => {
  const g = props.summary?.health?.grade
  return g === 'fair' || g === 'poor' ? g : 'good'
})

// —— 健康分翻牌（'—' 非数值时 composable 自动直落，不做假动画）——
const scoreDisplay = useCountUpText(
  computed(() => {
    const s = props.summary?.health?.score
    return s == null ? '—' : String(s)
  })
)

// —— 分项条：口径照抄 Cockpit.vue healthBars ——
const healthBars = computed(() => {
  const sub = props.summary?.health?.subscores || {}
  const rows = []
  const rate = (v) => (v == null ? 0 : Math.round(v * 100))
  if (sub.class_compliance) rows.push({ label: '达标率', ...sub.class_compliance, pct: rate(sub.class_compliance.rate) })
  if (sub.algae_normal) rows.push({ label: '蓝藻正常', ...sub.algae_normal, pct: rate(sub.algae_normal.rate) })
  // 短期趋势：5 项关键指标中环比持平（|Δ|<3%）占比
  const trends = Object.values(props.summary?.trends || {})
  const flat = trends.filter((t) => t.direction === 'flat').length
  if (trends.length) rows.push({ label: '环比持平', num: flat, den: trends.length, pct: Math.round((flat / trends.length) * 100) })
  if (sub.completeness) rows.push({ label: '数据完整度', ...sub.completeness, pct: rate(sub.completeness.rate) })
  return rows
})

// —— 5 个统计数（口径照抄 Cockpit.vue rc-stats / fmtMean：means value toFixed(2)）——
const warnCount = computed(() => props.summary?.warnings?.length || 0)

const stationDisplay = useCountUpText(computed(() => String(props.summary?.station_total ?? '—')))
const warnDisplay = useCountUpText(computed(() => String(props.summary?.warnings?.length ?? '—')))

const meanText = (code) =>
  computed(() => {
    const v = props.summary?.means?.[code]?.value
    return v == null ? '—' : Number(v).toFixed(2)
  })
const waterTempDisplay = useCountUpText(meanText('water_temperature'))
const chlaMeanDisplay = useCountUpText(meanText('chlorophyll_a'))
const doDisplay = useCountUpText(meanText('dissolved_oxygen'))
</script>

<style scoped>
/* —— 视觉容器：与现浮层卡一致（14px 圆角 / raised 面板 / 1px 细边）—— */
.rcc-health {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel-raised);
  padding: 12px 14px;
}
.rcc-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.rcc-head h2 { margin: 0; font-size: 14px; color: var(--text-primary); }
.rcc-grade {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  color: var(--risk-low, #22c55e);
}
.rcc-grade--fair { color: var(--risk-medium, #facc15); }
.rcc-grade--poor { color: var(--risk-critical, #ef4444); }

/* —— 环形仪 —— */
.rcc-body { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 12px; align-items: center; }
.rcc-gauge { position: relative; width: 108px; height: 108px; }
.rcc-gauge svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.rcc-gauge-track,
.rcc-gauge-value { fill: none; stroke-width: 10; stroke-linecap: round; }
.rcc-gauge-track { stroke: var(--border-subtle); }
.rcc-gauge-value {
  stroke: var(--risk-low, #22c55e);
  /* 升级：0 → 目标值 700ms ease-out 扫光（首挂起扫 / 变化时从旧值过渡） */
  transition: stroke-dasharray 700ms cubic-bezier(0.16, 1, 0.3, 1);
}
.rcc-gauge-value--good { stroke: var(--risk-low, #22c55e); filter: drop-shadow(0 0 3px var(--risk-low, #22c55e)); }
.rcc-gauge-value--fair { stroke: var(--risk-medium, #facc15); filter: drop-shadow(0 0 3px var(--risk-medium, #facc15)); }
.rcc-gauge-value--poor { stroke: var(--risk-critical, #ef4444); filter: drop-shadow(0 0 3px var(--risk-critical, #ef4444)); }
.rcc-gauge-center { position: absolute; inset: 0; display: grid; place-items: center; }
.rcc-gauge-center strong { font-family: var(--font-mono); font-size: 26px; color: var(--text-primary); }

/* —— 分项条 —— */
.rcc-bars { display: grid; gap: 7px; min-width: 0; }
.rcc-bar-row { display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.rcc-bar-label { font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
.rcc-bar-track { height: 5px; border-radius: 999px; background: var(--border-subtle); overflow: hidden; display: block; }
.rcc-bar-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--color-primary);
  transition: width 240ms ease;
}
.rcc-bar-num {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
  text-align: right;
  justify-self: end;
}

/* —— 5 个统计数 —— */
.rcc-stats {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px solid var(--border-subtle);
}
.rcc-stat { display: grid; gap: 1px; justify-items: center; min-width: 0; }
.rcc-stat strong { font-family: var(--font-mono); font-size: 15px; color: var(--text-primary); }
.rcc-stat span { font-size: 9.5px; color: var(--text-muted); white-space: nowrap; }
.rcc-stat--bad strong { color: var(--risk-critical, #ef4444); }

/* 预警数 >0 时的呼吸脉冲 */
@media (prefers-reduced-motion: no-preference) {
  .rcc-stat--bad strong { animation: rcc-breath 1.8s ease-in-out infinite; }
}
@keyframes rcc-breath {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

/* —— loading 骨架（微光扫描条，aria-hidden）—— */
.rcc-skel-root { display: grid; gap: 10px; }
.rcc-skel-gaugerow { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 12px; align-items: center; }
.rcc-skel--ring { display: block; width: 108px; height: 108px; border-radius: 999px; }
.rcc-skel-barcol { display: grid; gap: 10px; }
.rcc-skel--bar { display: block; height: 8px; border-radius: 6px; }
.rcc-skel-statrow {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  padding-top: 9px;
  border-top: 1px solid var(--border-subtle);
}
.rcc-skel--stat { display: block; width: 48px; height: 22px; border-radius: 6px; }
.rcc-skel--pill { display: block; width: 76px; height: 18px; border-radius: 999px; }
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

/* —— reduced-motion：关闭全部动效，环值/条宽/脉冲/骨架直落静态 —— */
@media (prefers-reduced-motion: reduce) {
  .rcc-gauge-value { transition: none; }
  .rcc-bar-track i { transition: none; }
  .rcc-stat--bad strong { animation: none; }
  .rcc-skel { animation: none; }
}
</style>
