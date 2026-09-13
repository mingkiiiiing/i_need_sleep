<template>
  <section class="rcc-inflow" aria-label="入湖河流负荷">
    <div class="rcc-head">
      <h2>入湖负荷</h2>
      <span v-if="inflow" class="rcc-month" :title="`数据截至 ${inflow.end_month}`">
        {{ inflow.end_month }}
      </span>
      <span v-else-if="!error" class="rcc-skel rcc-skel--pill" aria-hidden="true"></span>
    </div>

    <!-- 数据就绪：最新月 7 条入湖河流 TP / NH₃-N 与水质类别 -->
    <template v-if="inflow">
      <div class="rcc-collabels" aria-hidden="true">
        <span>入湖河流</span>
        <span>TP</span>
        <span>NH₃-N</span>
        <span>类别</span>
      </div>
      <div class="rcc-rows">
        <div v-for="sec in inflow.sections" :key="sec.section" class="rcc-row">
          <span class="rcc-name" :title="`${sec.water}（${sec.section}）· ${sec.city}`">
            {{ sec.water }}
          </span>
          <span class="rcc-val">{{ fmt(sec.latest?.tp, 3) }}</span>
          <span class="rcc-val">{{ fmt(sec.latest?.nh3n, 2) }}</span>
          <span class="rcc-badge" :class="`rcc-badge--${classKey(sec.latest?.wq_class)}`">
            {{ sec.latest?.wq_class || '—' }}
          </span>
        </div>
      </div>
      <div class="rcc-foot">
        <span>mg/L · 近12月TP均值≤{{ worstTpMean12 }} · Ⅳ类+ {{ inflow.iv_plus_count }} 月次</span>
        <em :title="inflow.source">{{ shortSource }}</em>
      </div>
    </template>

    <!-- 错误态：显式不可用 + 重试（不做静默降级） -->
    <div v-else-if="error" class="rcc-error">
      <span>入湖负荷数据不可用</span>
      <button type="button" class="rcc-retry" @click="$emit('retry')">重试</button>
    </div>

    <!-- loading 骨架（微光扫描条，aria-hidden） -->
    <div v-else class="rcc-skel-root" aria-hidden="true">
      <span v-for="i in 7" :key="i" class="rcc-skel rcc-skel--bar" :style="i === 7 ? { width: '62%' } : null"></span>
    </div>
  </section>
</template>

<script setup>
// ============================================================
// InflowCard · 综合驾驶舱「入湖负荷」卡
// ------------------------------------------------------------
// 数据契约（api.js · getInflowRiversSummary → /api/v1/inflow/rivers/summary）：
//   inflow.end_month   = 档案终点月（静态官方数据，月度节奏，无实时轨）
//   inflow.sections[]  = { section, water, city, latest: { ym, wq_class, tp, nh3n },
//                          mean_last12: { tp, nh3n }, iv_plus_count }
//   inflow.iv_plus_count / overall_class_counts（全期口径）
// 数据诚实：
//   - 全部数值为江苏省提供的官方监测记录原文，页面不做重算/改判类别；
//   - 静态档案不参与 60s 轮询，加载一次即可；失败显式错误态 + 重试。
// ============================================================
import { computed } from 'vue'
import { classKey, fmt, shortSource as shortenSource, worstTpMean12 as worstTpMean12Of } from './inflowCardUtils.js'

const props = defineProps({
  /** /api/v1/inflow/rivers/summary 数据；null 且 !error 时渲染 loading 骨架 */
  inflow: { type: Object, default: null },
  /** 拉取失败显式错误态 */
  error: { type: Boolean, default: false }
})

defineEmits(['retry'])

// 展示纯函数（fmt / classKey / worstTpMean12 / shortSource）已抽到 ./inflowCardUtils.js，
// 模板直接使用；此处仅保留依赖 props 响应性的 computed 薄封装。

const shortSource = computed(() => shortenSource(props.inflow?.source))

// 全部断面近12月TP均值的最大值（一行摘要，宁取最差断面口径）；
// mean_last12 为 null 的断面按缺数跳过（空态 '—'），详见 inflowCardUtils.js
const worstTpMean12 = computed(() => worstTpMean12Of(props.inflow?.sections))
</script>

<style scoped>
/* —— 视觉容器：与浮层卡一致（14px 圆角 / raised 面板 / 1px 细边）—— */
.rcc-inflow {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel-raised);
  padding: 12px 14px;
}
.rcc-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.rcc-head h2 { margin: 0; font-size: 14px; color: var(--text-primary); }
.rcc-month {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
  padding: 2px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
}

/* —— 列标签 + 7 行数据 —— */
.rcc-collabels {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44px 48px 30px;
  gap: 6px;
  padding: 0 6px 4px;
  font-size: 9px;
  color: var(--text-muted);
}
.rcc-collabels span:not(:first-child) { text-align: right; }
.rcc-rows { display: grid; gap: 3px; }
.rcc-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 44px 48px 30px;
  gap: 6px;
  align-items: center;
  padding: 2px 6px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--text-muted) 6%, transparent);
}
.rcc-name {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rcc-val {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
  text-align: right;
  white-space: nowrap;
}
.rcc-badge {
  justify-self: end;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1;
  padding: 3px 0;
  width: 26px;
  text-align: center;
  border-radius: 6px;
  border: 1px solid transparent;
}
.rcc-badge--excellent { color: var(--color-primary, #22d3ee); border-color: color-mix(in srgb, var(--color-primary) 40%, transparent); background: var(--color-primary-soft, rgba(34, 211, 238, 0.14)); }
.rcc-badge--good { color: var(--risk-low, #22c55e); border-color: color-mix(in srgb, var(--risk-low) 40%, transparent); background: color-mix(in srgb, var(--risk-low) 12%, transparent); }
.rcc-badge--moderate { color: var(--risk-medium, #facc15); border-color: color-mix(in srgb, var(--risk-medium) 40%, transparent); background: color-mix(in srgb, var(--risk-medium) 12%, transparent); }
.rcc-badge--poor { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, var(--risk-critical) 40%, transparent); background: color-mix(in srgb, var(--risk-critical) 12%, transparent); }
.rcc-badge--unknown { color: var(--text-muted); border-color: var(--border-subtle); }

/* —— 底部口径行 —— */
.rcc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px solid var(--border-subtle);
}
.rcc-foot span { font-size: 9.5px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rcc-foot em { font-style: normal; font-size: 9.5px; color: var(--text-muted); white-space: nowrap; }

/* —— 错误态 —— */
.rcc-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 2px 2px;
  font-size: 11px;
  color: var(--risk-critical, #ef4444);
}
.rcc-retry {
  font-size: 10.5px;
  color: var(--text-primary);
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  padding: 3px 10px;
  cursor: pointer;
}
.rcc-retry:hover { background: color-mix(in srgb, var(--color-primary) 12%, transparent); }

/* —— loading 骨架（微光扫描条）—— */
.rcc-skel-root { display: grid; gap: 6px; }
.rcc-skel--bar { display: block; height: 18px; border-radius: 7px; }
.rcc-skel--pill { display: block; width: 76px; height: 18px; border-radius: 999px; }
.rcc-skel {
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--text-muted) 12%, transparent),
    color-mix(in srgb, var(--text-muted) 22%, transparent),
    color-mix(in srgb, var(--text-muted) 12%, transparent));
  background-size: 200% 100%;
  animation: rcc-inflow-scan 1.4s ease-in-out infinite;
}
@keyframes rcc-inflow-scan {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* —— reduced-motion：骨架直落静态 —— */
@media (prefers-reduced-motion: reduce) {
  .rcc-skel { animation: none; }
}
</style>
