<template>
  <section class="rcc-warn" aria-label="蓝藻筛查预警">
    <!-- 头部：标题 + 数量徽标（>0 红底呼吸脉冲；=0 中性灰「0」静态不脉冲） -->
    <header class="rcc-warn__head">
      <h2 class="rcc-warn__title">蓝藻预警</h2>
      <span v-if="hasWarnings" class="rcc-warn__badge rcc-warn__badge--alert">{{ warnings.length }}</span>
      <span v-else class="rcc-warn__badge rcc-warn__badge--zero">0</span>
    </header>

    <!-- 空态：低调盾形图标 + 原文案（阈值来自 summary.warning_thresholds.light，由父层传入） -->
    <div v-if="!hasWarnings" class="rcc-warn__empty">
      <svg
        class="rcc-warn__shield"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6l7-3z" />
        <path d="M9.2 12.2l2 2 3.6-4" />
      </svg>
      <p class="rcc-warn__empty-text">暂无报数站点超过筛查阈值（chla {{ threshold }} μg/L）</p>
    </div>

    <!-- 预警列表：chla 降序（缺值置尾）；>5 项列表内部滚动，不撑高整卡 -->
    <ul v-else class="rcc-warn__list" :class="{ 'rcc-warn__list--scroll': sortedWarnings.length > 5 }">
      <li v-for="w in sortedWarnings" :key="w.station_id">
        <button
          type="button"
          class="rcc-warn__item"
          :class="[`rcc-warn__item--${w.band === 'moderate' ? 'moderate' : 'light'}`, { 'rcc-warn__item--missing': !hasChla(w) }]"
          :aria-label="itemAria(w)"
          @click="onFocus(w)"
        >
          <!-- chla 数值：本行视觉主角（等宽大字），缺失显示「—」不造值 -->
          <span class="rcc-warn__chla">
            <strong class="rcc-warn__chla-num">{{ chlaText(w) }}</strong>
            <small v-if="hasChla(w)" class="rcc-warn__chla-unit">μg/L</small>
          </span>
          <span class="rcc-warn__meta">
            <strong class="rcc-warn__name">{{ w.station_name }}</strong>
            <small class="rcc-warn__basin">太湖流域</small>
          </span>
          <!-- 严重度 chip：沿用现卡「轻度/中度」文案与配色 -->
          <span class="rcc-warn__chip" :class="`rcc-warn__chip--${w.band === 'moderate' ? 'moderate' : 'light'}`">
            {{ w.band === 'moderate' ? '中度' : '轻度' }}
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { computed } from 'vue'

// 「蓝藻预警」升级版独立卡 —— 集成阶段由主线替换 Cockpit.vue 内联 rc-warn 结构。
// 数据契约与现卡完全一致（/realtime/summary 的 warnings），不新增语义、不造值：
//   warnings 元素 = { station_id, station_name, chla, band: 'light'|'moderate' }
//   （来源：backend/app/providers.py summary.warnings 构造处；
//     空态阈值原文案取自 summary.warning_thresholds.light，经 props.threshold 传入。）

const props = defineProps({
  /** /realtime/summary 返回的 warnings 数组 */
  warnings: { type: Array, default: () => [] },
  /** 轻度筛查阈值（summary.warning_thresholds.light），仅用于空态文案展示 */
  threshold: { type: [Number, String], default: 10 }
})

const emit = defineEmits(['focus'])

const hasWarnings = computed(() => Array.isArray(props.warnings) && props.warnings.length > 0)

// chla 是否为可用真实数值（null/undefined/NaN 均视为缺失）
function hasChla(w) {
  return w != null && w.chla != null && Number.isFinite(Number(w.chla))
}

// 排序口径：按 chla 真实值降序 —— 筛查值越大越严重，最严重站点置顶。
// chla 为 null/缺失的项不参与数值比较，恒排最后，数值位置显示「—」，绝不造值。
// 先 slice() 复制再排序，不改动父层传入的数组。
const sortedWarnings = computed(() => {
  const list = Array.isArray(props.warnings) ? props.warnings.slice() : []
  const withValue = []
  const withoutValue = []
  for (const w of list) {
    if (hasChla(w)) withValue.push(w)
    else withoutValue.push(w)
  }
  withValue.sort((a, b) => Number(b.chla) - Number(a.chla))
  return withValue.concat(withoutValue)
})

// 数值展示：只输出接口真实字段；缺失显示「—」，不追加/改写数值本身
function chlaText(w) {
  return hasChla(w) ? String(w.chla) : '—'
}

// 点击预警项 → 聚焦站点（与现卡 focusStation 口径一致：上抛 station_id）
function onFocus(w) {
  emit('focus', w?.station_id)
}

// 读屏标签：读序按「站名 → 数值 → 档位」，避免视觉上 chla 大字优先造成的信息割裂
function itemAria(w) {
  const value = hasChla(w) ? `叶绿素a ${w.chla} μg/L` : '叶绿素a 缺测'
  const level = w?.band === 'moderate' ? '中度预警' : '轻度预警'
  return `${w?.station_name || '站点'}，太湖流域，${value}，${level}`
}
</script>

<style scoped>
/* ===== 容器：与现 rc-card 一致（14px 圆角 / raised 面 / 1px subtle 边） ===== */
.rcc-warn {
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-panel-raised);
  padding: 12px 14px;
}

.rcc-warn__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.rcc-warn__title {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}

/* ===== 数量徽标：>0 红底呼吸脉冲（2.4s）；=0 中性灰静态 ===== */
.rcc-warn__badge {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--radius-pill, 999px);
  display: inline-grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
}
.rcc-warn__badge--alert {
  background: var(--risk-critical, #ef4444);
  color: #fff;
}
.rcc-warn__badge--zero {
  background: var(--surface-panel-soft);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
}
@media (prefers-reduced-motion: no-preference) {
  .rcc-warn__badge--alert {
    animation: rcc-warn-pulse 2.4s var(--ease-in-out, ease-in-out) infinite;
  }
}
@keyframes rcc-warn-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--risk-critical, #ef4444) 45%, transparent);
  }
  50% {
    box-shadow: 0 0 0 6px color-mix(in srgb, var(--risk-critical, #ef4444) 0%, transparent);
  }
}

/* ===== 空态 ===== */
.rcc-warn__empty {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.rcc-warn__shield {
  width: 28px;
  height: 28px;
  flex: none;
  margin-top: 1px;
  color: var(--text-muted);
  opacity: 0.75;
}
.rcc-warn__empty-text {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* ===== 列表 ===== */
.rcc-warn__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
/* >5 项：列表内部滚动（约 232px ≈ 5 行），不撑高整卡；细化 8px 滚动条 */
.rcc-warn__list--scroll {
  max-height: 232px;
  overflow-y: auto;
  padding-right: 2px;
  scrollbar-width: thin;
  scrollbar-color: var(--border-subtle) transparent;
}
.rcc-warn__list--scroll::-webkit-scrollbar {
  width: 8px;
}
.rcc-warn__list--scroll::-webkit-scrollbar-track {
  background: transparent;
}
.rcc-warn__list--scroll::-webkit-scrollbar-thumb {
  background: var(--border-subtle);
  border-radius: var(--radius-pill, 999px);
}
.rcc-warn__list--scroll::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}

/* ===== 预警项 ===== */
.rcc-warn__item {
  position: relative;
  overflow: hidden; /* 左缘 3px 色条随圆角裁切 */
  width: 100%;
  min-height: 44px; /* 触摸目标下限 */
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 13px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--dur-short, 180ms) var(--ease-out, ease-out);
}
.rcc-warn__item:hover {
  border-color: color-mix(in srgb, var(--color-primary, #22d3ee) 45%, transparent);
}
.rcc-warn__item:focus-visible {
  outline: 2px solid var(--color-primary, #22d3ee);
  outline-offset: 2px;
}
/* hover 上浮 1px 仅在允许动效时启用（reduced-motion 只保留边框亮化） */
@media (prefers-reduced-motion: no-preference) {
  .rcc-warn__item {
    transition:
      transform var(--dur-short, 180ms) var(--ease-out, ease-out),
      border-color var(--dur-short, 180ms) var(--ease-out, ease-out);
  }
  .rcc-warn__item:hover {
    transform: translateY(-1px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .rcc-warn__badge--alert {
    animation: none;
  }
  .rcc-warn__item,
  .rcc-warn__item:hover {
    transform: none;
  }
}

/* 左缘 3px 严重度色条：light=琥珀 / moderate=珊瑚红（与现卡 rc-band 同源 token） */
.rcc-warn__item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--risk-medium, #facc15);
}
.rcc-warn__item--moderate::before {
  background: var(--risk-critical, #ef4444);
}

/* chla 数值：本行视觉主角（等宽大字）；缺失时中性灰「—」 */
.rcc-warn__chla {
  display: grid;
  justify-items: start;
  line-height: 1.15;
}
.rcc-warn__chla-num {
  font-family: var(--font-mono);
  font-size: 19px;
  font-weight: 700;
  color: var(--risk-medium, #facc15);
  font-variant-numeric: tabular-nums;
}
.rcc-warn__item--moderate .rcc-warn__chla-num {
  color: var(--risk-critical, #ef4444);
}
.rcc-warn__item--missing .rcc-warn__chla-num {
  color: var(--text-muted);
}
.rcc-warn__chla-unit {
  font-size: 10px;
  color: var(--text-muted);
}

/* 站名 / 流域小字 */
.rcc-warn__meta {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.rcc-warn__name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rcc-warn__basin {
  font-size: 10.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 严重度 chip：沿用现卡「轻度/中度」文案与配色 */
.rcc-warn__chip {
  font-size: 10.5px;
  padding: 2px 9px;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
}
.rcc-warn__chip--light {
  color: var(--risk-medium, #facc15);
  border-color: color-mix(in srgb, var(--risk-medium, #facc15) 50%, transparent);
}
.rcc-warn__chip--moderate {
  color: var(--risk-critical, #ef4444);
  border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 50%, transparent);
}
</style>
