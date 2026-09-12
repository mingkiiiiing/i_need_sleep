<!-- ============================================================
     SystemPulse · 首页「系统工程脉搏」数字带（系统骨架一览）
     ------------------------------------------------------------
     数据契约（全部真实，缺数据显示「—」，禁造值）：
     · props.stationTotal —— summary.station_total，全量监测站数（live）
     · props.plottable   —— summary.markers 中有坐标站数（live）
     · props.warnings    —— summary.warnings.length，蓝藻筛查预警站数（live）
     · props.state       —— 'loading' | 'ok' | 'error'（与 Home.vue rtState 同构）
       live 数字仅在 ok 态翻牌；loading 显示骨架；error 显示「—」并保持灰。
     · 固定项目事实（组件内常量，口径来源见下方注释，非 props）
     数字翻牌复用 src/composables/stationCountUp.js 的 useCountUpText：
     终帧严格等于真实文本；prefers-reduced-motion 时跳过动画直接落终值。
     ============================================================ -->
<template>
  <section class="syspulse" aria-label="系统工程脉搏">
    <!-- 小节标题 + 右侧等宽状态注（装饰性徽标对读屏隐藏，语义由 sr-only 补全） -->
    <header class="syspulse-head">
      <h2 class="syspulse-title">系统工程脉搏</h2>
      <span class="syspulse-live" :class="`is-${state}`" aria-hidden="true">
        <i class="syspulse-live-dot"></i>{{ badgeText }}
      </span>
      <span class="sr-only">{{ badgeSr }}</span>
    </header>

    <!-- 六格 stat 带：3 live + 3 固定事实；上缘 2px 主色扫描线 -->
    <div class="syspulse-band">
      <span class="syspulse-scan" aria-hidden="true"></span>

      <article
        v-for="(cell, i) in cells"
        :key="cell.key"
        class="syspulse-cell"
        :class="cell.cellClass"
        :style="{ '--cell-i': i }"
      >
        <div class="syspulse-numrow">
          <span v-if="cell.mode === 'loading'" class="syspulse-skel" aria-hidden="true"></span>
          <template v-else>
            <span class="syspulse-num" aria-hidden="true">{{ cell.text }}</span>
            <span v-if="cell.mode !== 'error'" class="syspulse-suffix" aria-hidden="true">{{ cell.suffix }}</span>
          </template>
          <span class="sr-only">{{ cell.sr }}</span>
        </div>
        <div class="syspulse-meta">
          <span class="syspulse-label">{{ cell.label }}</span>
          <span class="syspulse-caption">{{ cell.caption }}</span>
        </div>
      </article>
    </div>

    <!-- error 态说明：只描述离线事实，不补造任何数字 -->
    <p v-if="state === 'error'" class="syspulse-offline" role="status">
      实时数据离线 — 站点与预警数字暂不可用，链路恢复后自动恢复翻牌；推演时效 / 刷新周期 / 业务模块为固定指标，不受影响。
    </p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useCountUpText } from '../../composables/stationCountUp.js'

const props = defineProps({
  /** summary.station_total —— 全量监测站数（live） */
  stationTotal: { type: [Number, String], default: '—' },
  /** summary.markers 中有坐标（lat/lon 均非空）站数（live） */
  plottable: { type: [Number, String], default: '—' },
  /** summary.warnings.length —— 蓝藻筛查预警站数（live） */
  warnings: { type: [Number, String], default: '—' },
  /** 'loading' | 'ok' | 'error'，与 Home.vue 的 rtState 同构 */
  state: { type: String, default: 'loading' }
})

// ---------- 固定项目事实（非 props；口径来源注释，禁造值） ----------
// 推演时效 7 档：T+1 / T+3 / T+7 / T+15 / T+30 / T+60 / T+90。
//   口径来源：预测快照 horizon_list（src/stores/predictionSnapshot.js:
//   horizonList = payload.horizon_list），与热力图推演面板
//   src/components/heatmap/ForecastResultPanel.vue 的 HORIZONS = [1,3,7,15,30,60,90] 一致。
const HORIZON_TIERS = 7
// 实时刷新 60s：首页实时轨轮询周期。
//   口径来源：src/pages/Home.vue 的 setInterval(() => loadSummary(true), 60_000)，
//   与 src/services/realtime.js 的 CACHE_TTL_MS = 60_000 同口径。
const REFRESH_SECONDS = 60
// 业务模块 6 个：首页「核心业务入口」清单（src/pages/Home.vue entries）——
//   综合驾驶舱 / 监测站点研判 / 预警与应急预案中心 / 卫星遥感与时空推演 /
//   实时观测历史复盘 / 实时大屏。
const MODULE_COUNT = 6

// ---------- 取值助手：缺数据显示「—」，不造值 ----------
function toText(v) {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}
function toNumber(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
  return null
}

// ---------- 数字翻牌：6 路独立 useCountUpText ----------
// live 路源：prop 文本。summary 就绪（props 从「—」变为数值）时从 0 滚起；
// 之后 60s 轮询里数值结构一致则旧值滚新值，终帧严格等于真实文本。
const stationTotalSrc = computed(() => toText(props.stationTotal))
const plottableSrc = computed(() => toText(props.plottable))
const warningsSrc = computed(() => toText(props.warnings))
const displayStation = useCountUpText(stationTotalSrc)
const displayPlottable = useCountUpText(plottableSrc)
const displayWarnings = useCountUpText(warningsSrc)
// 固定事实路源：常量文本。挂载时首次出现数值 → 按同一口径从 0 滚到目标一次。
const displayHorizon = useCountUpText(() => String(HORIZON_TIERS))
const displayRefresh = useCountUpText(() => String(REFRESH_SECONDS))
const displayModules = useCountUpText(() => String(MODULE_COUNT))

// ---------- 预警格状态色：>0 转 --c-alert 呼吸；=0 走 --c-stable 静态 ----------
const warningsNum = computed(() => toNumber(props.warnings))

// ---------- 六格视图模型 ----------
const cells = computed(() => {
  const offline = props.state === 'error'
  const loading = props.state === 'loading'
  const mode = offline ? 'error' : loading ? 'loading' : 'ok'

  // live 格：loading → 骨架；error → 「—」保持灰；ok → 翻牌文本
  const liveCell = (key, display, raw, suffix, label, caption, cellClass) => ({
    key,
    mode,
    text: mode === 'ok' ? display : '—',
    suffix,
    label,
    caption,
    cellClass,
    sr:
      mode === 'ok'
        ? `${toText(raw)} ${suffix} · ${label}`
        : mode === 'error'
          ? `${label} · 实时数据离线`
          : `正在加载 ${label}`
  })

  // 预警格：仅 ok 态且可解析为数值时启用状态色
  const wN = warningsNum.value
  const warnClass =
    mode === 'ok' && wN !== null ? (wN > 0 ? 'is-alert' : 'is-calm') : ''

  return [
    liveCell('station', displayStation.value, props.stationTotal, '座', '监测站总数', '全量实时接入', ''),
    liveCell('plottable', displayPlottable.value, props.plottable, '座', '可定位站点', '具备经纬度坐标', ''),
    liveCell('warnings', displayWarnings.value, props.warnings, '站', '蓝藻预警站', 'Chl-a 筛查命中', warnClass),
    {
      key: 'horizon',
      mode: 'fixed',
      text: displayHorizon.value,
      suffix: '档',
      label: '推演时效',
      caption: 'T+1 → T+90',
      cellClass: 'is-fixed',
      sr: `${HORIZON_TIERS} 档 · 推演时效 T+1 至 T+90`
    },
    {
      key: 'refresh',
      mode: 'fixed',
      text: displayRefresh.value,
      suffix: 's',
      label: '实时刷新周期',
      caption: '自动轮询',
      cellClass: 'is-fixed',
      sr: `${REFRESH_SECONDS} 秒 · 实时数据自动刷新`
    },
    {
      key: 'modules',
      mode: 'fixed',
      text: displayModules.value,
      suffix: '个',
      label: '核心业务模块',
      caption: '驾驶舱 → 大屏',
      cellClass: 'is-fixed',
      sr: `${MODULE_COUNT} 个 · 核心业务模块`
    }
  ]
})

// 右上角状态徽标：装饰 aria-hidden，语义由 badgeSr（sr-only）补全
const badgeText = computed(() =>
  props.state === 'error' ? 'OFFLINE' : props.state === 'loading' ? 'SYNC…' : 'LIVE · 60s'
)
const badgeSr = computed(() =>
  props.state === 'error'
    ? '实时数据离线'
    : props.state === 'loading'
      ? '正在同步实时数据'
      : '实时数据 · 每 60 秒自动刷新'
)
</script>

<style scoped>
.syspulse {
  display: grid;
  gap: 12px;
}

/* ============ 小节标题行 ============ */
.syspulse-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.syspulse-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}
.syspulse-live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--c-accent);
}
.syspulse-live.is-loading { color: var(--c-watch); }
.syspulse-live.is-error { color: var(--text-muted); }
.syspulse-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px var(--c-accent-glow);
  animation: syspulse-blink 2.2s ease-in-out infinite;
}
.syspulse-live.is-loading .syspulse-live-dot,
.syspulse-live.is-error .syspulse-live-dot { box-shadow: none; }
@keyframes syspulse-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* ============ 六格 stat 带 ============ */
.syspulse-band {
  position: relative;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}

/* 顶部扫描线：2px 主色，4s 从左到右循环，低透明度 */
.syspulse-scan {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
  width: 25%;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--c-accent) 50%, transparent);
  opacity: 0.5;
  transform: translateX(-100%);
  animation: syspulse-scan 4s linear infinite;
  pointer-events: none;
}
@keyframes syspulse-scan {
  to { transform: translateX(400%); }
}

/* 格子：竖分隔线 + 中点呼吸小圆点（错峰） */
.syspulse-cell {
  position: relative;
  display: grid;
  align-content: center;
  gap: 8px;
  min-width: 0;
  padding: 20px 22px;
}
.syspulse-cell + .syspulse-cell {
  border-left: 1px solid var(--border-subtle);
}
.syspulse-cell + .syspulse-cell::after {
  content: '';
  position: absolute;
  top: 50%;
  left: -3.5px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-accent);
  box-shadow: 0 0 8px var(--c-accent-glow);
  transform: translateY(-50%);
  animation: syspulse-breathe 2.6s ease-in-out infinite;
  animation-delay: calc(var(--cell-i, 0) * -0.45s); /* 错峰呼吸 */
  pointer-events: none;
}
@keyframes syspulse-breathe {
  0%, 100% { opacity: 0.25; transform: translateY(-50%) scale(0.8); }
  50% { opacity: 0.95; transform: translateY(-50%) scale(1.15); }
}

/* ============ 数字区 ============ */
.syspulse-numrow {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-height: 32px;
}
.syspulse-num {
  font-family: var(--font-mono);
  font-size: clamp(26px, 2.1vw, 32px);
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.syspulse-suffix {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}

/* 固定事实格：主色数字（与 live 中性亮色区分「系统骨架」语义） */
.syspulse-cell.is-fixed .syspulse-num { color: var(--c-accent); }
/* 预警格状态色：>0 告警呼吸；=0 稳定静态；离线灰 */
.syspulse-cell.is-alert .syspulse-num {
  color: var(--c-alert);
  animation: syspulse-alert 1.8s ease-in-out infinite;
}
.syspulse-cell.is-calm .syspulse-num { color: var(--c-stable); }
.syspulse-cell.is-offline .syspulse-num { color: var(--text-muted); }
@keyframes syspulse-alert {
  0%, 100% { opacity: 1; text-shadow: 0 0 0 transparent; }
  50% { opacity: 0.78; text-shadow: 0 0 18px color-mix(in srgb, var(--c-alert) 40%, transparent); }
}

/* loading 骨架：脉冲占位条，宽度近似两位数版面 */
.syspulse-skel {
  align-self: center;
  width: 58px;
  height: 24px;
  border-radius: 5px;
  background: var(--surface-panel-soft);
  border: 1px solid var(--border-subtle);
  animation: syspulse-skel 1.6s ease-in-out infinite;
}
@keyframes syspulse-skel {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 0.9; }
}

/* ============ 标签区 ============ */
.syspulse-meta {
  display: grid;
  gap: 2px;
}
.syspulse-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.syspulse-caption {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--text-muted);
}

/* ============ error 说明行 ============ */
.syspulse-offline {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-muted);
}

/* ============ 响应式：6 列 → 3×2 → 2×3（行首格去掉竖分隔与圆点） ============ */
@media (max-width: 960px) {
  .syspulse-band { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .syspulse-cell:nth-child(3n + 1) { border-left: none; }
  .syspulse-cell:nth-child(3n + 1)::after { display: none; }
}
@media (max-width: 620px) {
  .syspulse-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .syspulse-cell + .syspulse-cell { border-left: 1px solid var(--border-subtle); }
  .syspulse-cell:nth-child(3n + 1)::after { display: block; }
  .syspulse-cell:nth-child(2n + 1) { border-left: none; }
  .syspulse-cell:nth-child(2n + 1)::after { display: none; }
}

/* ============ reduced-motion：扫描线静态为主色细线；呼吸/脉冲/骨架全静态 ============ */
@media (prefers-reduced-motion: reduce) {
  .syspulse-scan {
    width: 100%;
    background: var(--c-accent);
    opacity: 0.28;
    transform: none;
    animation: none;
  }
  .syspulse-cell + .syspulse-cell::after {
    animation: none;
    opacity: 0.45;
    transform: translateY(-50%);
  }
  .syspulse-live-dot { animation: none; opacity: 0.8; }
  .syspulse-cell.is-alert .syspulse-num {
    animation: none;
    opacity: 1;
    text-shadow: none;
  }
  .syspulse-skel { animation: none; opacity: 0.55; }
}

/* ============ sr-only：为装饰性动效补全读屏语义 ============ */
.sr-only {
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
</style>
