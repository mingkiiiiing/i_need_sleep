<!-- ============================================================
  TopStatusChip · 综合驾驶舱顶部「实时汇总条」升级版独立组件
  ------------------------------------------------------------
  替换对象：src/pages/Cockpit.vue 顶部四态条件渲染的 rc-chip（L19-37）。
  集成时由主线用 <TopStatusChip :summary :state @retry /> 替换那四段。

  四态优先级（与原页面逐字同语义）：
    1. state==='error'                      → role=alert  失败 + 重试（--c-alert）
    2. summary && freshness==='historical'  → role=status 历史快照回放（--c-accent）
    3. summary && freshness!=='normal'      → role=status 数据延迟/过期警示（--c-watch）
    4. summary 正常                          → role=status 实时监测预警（--c-stable）
    5. state==='loading' 且无 summary        → 细骨架条（aria-hidden，无文字）

  升级手法：状态线性图标 / 关键数字翻牌（useCountUpText，终帧=真实值）/
  左缘 3px 状态色带 + 10% tint / 胶囊徽章（999px + panel-raised + border-subtle）/
  全动画 reduced-motion 降级。
  ============================================================ -->
<template>
  <!-- ① 加载失败：免责语义原样保留 + 重试 -->
  <div v-if="phase === 'error'" class="rts rts--error" role="alert">
    <span class="rts-icon" aria-hidden="true">
      <!-- 警告三角 -->
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 4 21.2 19.6H2.8Z" />
        <path d="M12 10v4.2" />
        <path d="M12 17.2h.01" />
      </svg>
    </span>
    <span class="rts-text">实时汇总加载失败（不会回退情景数据）</span>
    <button type="button" class="rts-btn" @click="emit('retry')">重试</button>
  </div>

  <!-- ⑤ 加载中且无数据：细骨架条（无文字，读屏跳过） -->
  <div v-else-if="phase === 'loading'" class="rts rts--loading" aria-hidden="true">
    <span class="rts-skel rts-skel--dot"></span>
    <span class="rts-skel rts-skel--bar"></span>
  </div>

  <!-- ② 历史快照回放 -->
  <div v-else-if="phase === 'historical'" class="rts rts--historical" role="status">
    <span class="rts-icon" aria-hidden="true">
      <!-- 历史时钟（逆时针箭头 + 指针） -->
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
        <path d="M3 3v5h5" />
        <path d="M12 7v5l4 2" />
      </svg>
    </span>
    <span class="rts-text">
      <strong class="rts-title">历史快照回放</strong>
      <span class="rts-dim">观测 {{ formatStamp(summary.latest_observed_at) }} · 点击时间轴最后一个刻度或刷新返回最新</span>
    </span>
  </div>

  <!-- ③ 数据延迟 / 过期（freshness 非 normal 非 historical，警示色） -->
  <div v-else-if="phase === 'abnormal'" class="rts rts--abnormal" role="status">
    <span class="rts-icon" aria-hidden="true">
      <!-- 延迟沙漏 -->
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M7 3h10" />
        <path d="M7 21h10" />
        <path d="M8 3v3c0 2.2 4 3.3 4 6s-4 3.8-4 6v3" />
        <path d="M16 3v3c0 2.2-4 3.3-4 6s4 3.8 4 6v3" />
      </svg>
    </span>
    <span class="rts-text">
      实时数据{{ FRESHNESS_TEXT[summary.freshness_status] || summary.freshness_status }}：当前展示最后成功抓取数据
      （观测 {{ formatStamp(summary.latest_observed_at) }}，滞后 {{ formatLag(summary.observed_lag_h) }}）
    </span>
  </div>

  <!-- ④ 实时正常：日期等宽加粗，达标率 / 预警站数翻牌 -->
  <div v-else class="rts rts--normal" role="status">
    <span class="rts-icon" aria-hidden="true">
      <!-- 实时脉冲波 -->
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </svg>
    </span>
    <strong class="rts-date">{{ monthDayText }}</strong>
    <span class="rts-text">
      实时监测预警：全湖以 <b class="rts-class">{{ summary.dominant_class }} 类</b>为主（<span class="rts-num">{{ compliancePctDisplay }}</span>% 达标 III 类）<span
        v-if="warnCount > 0"
        class="rts-warn"
      > · <span class="rts-num">{{ warnCountDisplay }}</span> 站蓝藻筛查预警{{ warnBrief }}</span>
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatStamp, formatLag, FRESHNESS_TEXT } from '../../services/realtime.js'
import { useCountUpText } from '../../composables/stationCountUp.js'

const props = defineProps({
  /** 页面实时汇总对象（字段见 Cockpit 契约），加载前为 null */
  summary: { type: Object, default: null },
  /** 页面汇总加载态：'loading' | 'ok' | 'error' */
  state: {
    type: String,
    default: 'loading',
    validator: (v) => ['loading', 'ok', 'error'].includes(v)
  }
})

const emit = defineEmits(['retry'])

// ---------- 四态裁决（优先级与原 Cockpit.vue L19-37 完全一致：error 最先） ----------
const phase = computed(() => {
  if (props.state === 'error') return 'error'
  if (!props.summary) return 'loading'
  if (props.summary.freshness_status === 'historical') return 'historical'
  if (props.summary.freshness_status !== 'normal') return 'abnormal'
  return 'normal'
})

// ---------- 文案派生（照抄原页计算口径，语义不改） ----------
// 原 Cockpit.vue L350-353：{M月D日}（无数据时为空，不强造日期）
const monthDayText = computed(() => {
  const m = String(props.summary?.latest_observed_at || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${Number(m[2])}月${Number(m[3])}日` : ''
})

// 原 Cockpit.vue L364-366：class_iii_rate(0-1) → 整数百分比，缺失保持 '—'
const compliancePctText = computed(() =>
  props.summary?.class_iii_rate != null ? String(Math.round(props.summary.class_iii_rate * 100)) : '—'
)
// 翻牌：summary null→有数据首次渲染从 0 滚到真实值；终帧严格等于真实文本；
// reduced-motion / 非有限值 / 无数值时直落终值（composable 内建保证）
const compliancePctDisplay = useCountUpText(compliancePctText)

// 原 Cockpit.vue L35：仅 warnings.length > 0 时显示预警片段
const warnCount = computed(() => props.summary?.warnings?.length ?? 0)
const warnCountText = computed(() => String(warnCount.value))
const warnCountDisplay = useCountUpText(warnCountText)

// 原 Cockpit.vue L368-373：前两站站名 + 超 2 站补「 等」
const warnBrief = computed(() => {
  const list = props.summary?.warnings || []
  if (!list.length) return ''
  const names = list.slice(0, 2).map((w) => w.station_name).join('、')
  return `（${names}${list.length > 2 ? ' 等' : ''}）`
})
</script>

<style scoped>
/* ---------- 状态 → 令牌色 ---------- */
.rts--error { --rts-color: var(--c-alert); }
.rts--abnormal { --rts-color: var(--c-watch); }
.rts--historical { --rts-color: var(--c-accent); }
.rts--normal { --rts-color: var(--c-stable); }
.rts--loading { --rts-color: var(--c-accent); }

/* ---------- 胶囊徽章基底（与页面浮层体系一致） ---------- */
.rts {
  --rts-color: var(--c-accent);
  position: relative;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 7px 16px 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  /* 状态 tint 10% 混入面板底 + 左缘 3px 状态色带（inset 阴影贴合胶囊圆角） */
  background: color-mix(in srgb, var(--rts-color) 10%, var(--surface-panel-raised));
  box-shadow: inset 3px 0 0 0 var(--rts-color);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
  /* max-width / overflow 由集成壳控制，组件内允许正常换行 */
  white-space: normal;
  max-width: 100%;
  animation: rts-in 0.24s ease-out;
}
@keyframes rts-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

/* ---------- 图标（色随状态令牌） ---------- */
.rts-icon {
  display: inline-flex;
  flex: none;
  color: var(--rts-color);
}
.rts-icon svg {
  width: 16px;
  height: 16px;
  display: block;
}

/* ---------- 文本 ---------- */
.rts-text { min-width: 0; }
.rts-title { color: var(--c-accent); }
.rts-dim { color: color-mix(in srgb, var(--text-primary) 78%, transparent); }

/* ③ 警示态整行警示色（原 rc-chip--error 口径升级为令牌色） */
.rts--error,
.rts--abnormal {
  color: var(--rts-color);
}

/* ④ 日期：等宽加粗；水质类别：主色；数字：等宽数位防滚动抖动 */
.rts-date {
  font-family: var(--font-mono);
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex: none;
}
.rts-class { color: var(--color-primary); }
.rts-num { font-variant-numeric: tabular-nums; }
.rts-warn {
  color: var(--c-alert);
  font-weight: 700;
}

/* ---------- 重试按钮（沿用原文案「重试」，语义不弱化） ---------- */
.rts-btn {
  appearance: none;
  flex: none;
  border: 1px solid color-mix(in srgb, var(--c-accent) 45%, transparent);
  background: color-mix(in srgb, var(--c-accent) 10%, transparent);
  color: var(--text-primary);
  font: inherit;
  border-radius: 999px;
  min-height: 26px;
  padding: 2px 12px;
  cursor: pointer;
}
.rts-btn:hover { background: color-mix(in srgb, var(--c-accent) 18%, transparent); }
.rts-btn:focus-visible { outline: 2px solid var(--c-accent); outline-offset: 2px; }

/* ---------- ⑤ loading 骨架条（无文字） ---------- */
.rts--loading {
  min-height: 34px;
}
.rts-skel {
  display: inline-block;
  border-radius: 999px;
  background-color: color-mix(in srgb, var(--text-primary) 10%, transparent);
  background-image: linear-gradient(
    100deg,
    transparent 30%,
    color-mix(in srgb, var(--text-primary) 9%, transparent) 50%,
    transparent 70%
  );
  background-size: 200% 100%;
  animation: rts-shimmer 1.4s linear infinite;
}
.rts-skel--dot { width: 16px; height: 16px; flex: none; }
.rts-skel--bar { width: min(320px, 46vw); height: 10px; }
@keyframes rts-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* ---------- reduced-motion：入场 / 微光 / 翻牌全部直落 ---------- */
@media (prefers-reduced-motion: reduce) {
  .rts,
  .rts-skel {
    animation: none;
  }
}
</style>
