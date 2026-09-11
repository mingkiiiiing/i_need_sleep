<template>
  <section ref="listEl" class="stn-block slp" aria-label="实时站点列表">
    <div class="stn-sec-head">
      <h2>实时站点（{{ stations.length }}）</h2>
      <span class="stn-sec-legend" role="img" aria-label="数据状态图例：正常、延迟、过期/异常">
        <span><i class="slp-st-normal"></i>正常</span>
        <span><i class="slp-st-delayed"></i>延迟</span>
        <span><i class="slp-st-overdue"></i>过期/异常</span>
      </span>
    </div>

    <div class="slp-search stn-search-row">
      <input
        :value="search"
        type="search"
        placeholder="搜索站名 / 省份"
        aria-label="搜索站点"
        @input="$emit('update:search', $event.target.value)"
      />
      <button v-if="search" type="button" class="stn-search-clear" aria-label="清空搜索" @click="$emit('update:search', '')">×</button>
    </div>

    <div class="stn-filter" role="group" aria-label="省份筛选">
      <button
        v-for="opt in LOCATION_FILTERS"
        :key="opt.key"
        type="button"
        :class="{ active: locationFilter === opt.key }"
        :aria-pressed="String(locationFilter === opt.key)"
        @click="$emit('update:locationFilter', opt.key)"
      >
        {{ opt.label }}<small v-if="opt.key !== 'all'"> {{ locationCounts[opt.key] || 0 }}</small>
      </button>
    </div>

    <!-- S1 头部统计：口径见 statusCounts 注释；全量目录统计，不随搜索/省份筛选变化 -->
    <p
      v-if="state !== 'loading' && stations.length"
      class="slp-stats"
      title="口径：在线=最新观测≤6h 且有有效报数；延迟=观测滞后6–12h；过期=>12h 或数据异常。统计全量站点目录，不随搜索/筛选变化。"
    >
      <template v-if="filterActive">全量口径 · </template>{{ statusCounts.normal }} / {{ statusCounts.total }} 在线 · {{ statusCounts.delayed }} 延迟 · {{ statusCounts.overdue }} 过期
    </p>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 6" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">实时站点列表加载失败</p>
      <p class="sle-desc">不会回退到情景分区数据。</p>
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </div>

    <div v-else-if="!rows.length" class="stn-list-empty">
      <p class="sle-title">没有符合筛选条件的站点</p>
      <button type="button" class="stn-inline-btn" @click="$emit('reset-filters')">重置筛选</button>
    </div>

    <ul v-else class="stn-zone-list">
      <li v-for="s in rows" :key="s.id">
        <button
          type="button"
          class="stn-zone-item"
          :class="{ selected: s.id === selectedId }"
          @click="$emit('select', s.id)"
          @mouseenter="$emit('hover', s.id)"
          @mouseleave="$emit('hover', '')"
          @focus="$emit('hover', s.id)"
          @blur="$emit('hover', '')"
        >
          <span class="zi-rank">{{ s.waterLevelText }}</span>
          <span class="zi-main">
            <span class="zi-code">{{ s.province || '—' }}</span>
            <span class="zi-name">{{ s.source_station_name }}</span>
          </span>
          <span class="zi-side">
            <span class="zi-risk" :class="`lv-${s.dataStatusTone}`">
              <i class="slp-dot" :class="`slp-st-${s.dotTone}`" aria-hidden="true"></i>{{ s.dataStatusText }}
            </span>
            <span class="slp-side-row">
              <span
                v-if="s.chlaText"
                class="slp-chla"
                :style="{ '--chla-c': s.chlaColor }"
                title="最新叶绿素 a：来自实时快照 markers（有坐标上报站点），与地图着色同一口径"
              >{{ s.chlaText }}</span>
              <span class="zi-score">{{ s.available_variable_count }}/{{ s.variableTotal }}</span>
            </span>
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
// 实时站点列表：数据全部来自 observed 轨站点目录；排序“数据异常 → 严重过期 → 延迟 → 正常”，
// 不使用任何情景风险分数。位置状态筛选暴露坐标可信度（missing/suspicious 站不画地图点）。
//
// S1 视觉升级说明（数据诚实口径）：
// - 站点对象来自 fetchRealtimeStations（/spatial-entities?mode=observed&active=latest），
//   字段以 backend/app/schemas.py「MonitoringStation」/ providers.py「_station_view」为准：
//   无任何最新 chla 数值字段。集成层（Stations.vue）从 /realtime/summary 的 markers
//   取真实报数值组装 chlaById 传入；芯片只对有真实值的站渲染，缺测站不显示芯片，绝不本地造值。
// - 数据状态点三分桶与图例一致：normal=--c-stable / delayed=--c-watch /
//   severely_overdue·abnormal=--c-alert（呼吸脉冲，prefers-reduced-motion 下全静态）。
import { computed, nextTick, ref, watch } from 'vue'
import {
  STATION_STATUS_ORDER,
  STATION_STATUS_TEXT,
  chlaColor,
  stationDataStatus
} from '../../services/realtime.js'

const props = defineProps({
  stations: { type: Array, required: true },
  selectedId: { type: String, default: '' },
  state: { type: String, default: 'loading' },
  search: { type: String, default: '' },
  locationFilter: { type: String, default: 'all' },
  // 集成接线：实时快照 markers 的真实最新 chla（{ [stationId]: number }，缺测站不在表内）
  chlaById: { type: Object, default: () => ({}) }
})

defineEmits(['select', 'retry', 'reset-filters', 'update:search', 'update:locationFilter', 'hover'])

// 深链接/搜索后选中行可能不在可视区：选中变化时把行滚入视野（block:nearest 不打扰当前滚动）
const listEl = ref(null)
watch(() => props.selectedId, async () => {
  await nextTick()
  listEl.value?.querySelector('.stn-zone-item.selected')?.scrollIntoView({ block: 'nearest' })
})

const LOCATION_FILTERS = [
  { key: 'all', label: '全部位置' },
  { key: 'jiangsu', label: '江苏省' },
  { key: 'zhejiang', label: '浙江省' },
  { key: 'other', label: '其他省份' }
]

const locationCounts = computed(() => {
  const counts = { jiangsu: 0, zhejiang: 0, other: 0 }
  props.stations.forEach((s) => {
    const p = (s.province || '').trim()
    if (p === '江苏省') counts.jiangsu++
    else if (p === '浙江省') counts.zhejiang++
    else if (p) counts.other++
  })
  return counts
})

// 数据状态点三分桶（severely_overdue 与 abnormal 同为「过期/异常」视觉，与图例一致）
const DOT_TONE = { normal: 'normal', delayed: 'delayed', severely_overdue: 'overdue', abnormal: 'overdue' }

// 头部统计口径（数字全部由 stations 真实字段推导，与行内状态点/图例同一套分桶）：
// - 在线   = stationDataStatus() === 'normal'：有最新观测时间、≥1 项有效指标，观测滞后 ≤6h
//            （阈值来源 realtime.js stationDataStatus：≤6h 正常 / ≤12h 延迟 / >12h 严重过期）
// - 延迟   = 'delayed'：观测滞后 6–12h
// - 过期   = 'severely_overdue'（>12h）或 'abnormal'（缺最新观测时间 / 零有效指标 / 时间不可解析）
// - total  = props.stations.length：全量站点目录，不随搜索/省份筛选变化（与标题「实时站点（N）」同口径）
const statusCounts = computed(() => {
  const c = { normal: 0, delayed: 0, overdue: 0, total: props.stations.length }
  props.stations.forEach((s) => {
    const st = stationDataStatus(s)
    if (st === 'normal') c.normal++
    else if (st === 'delayed') c.delayed++
    else c.overdue++
  })
  return c
})

// 搜索/省份筛选生效时给统计行加「全量口径」前缀，避免与列表可见行数混淆
const filterActive = computed(() => Boolean(props.search.trim()) || props.locationFilter !== 'all')

const rows = computed(() => {
  const kw = props.search.trim().toLowerCase()
  return props.stations
    .filter((s) => {
      if (props.locationFilter !== 'all') {
        const p = (s.province || '').trim()
        if (props.locationFilter === 'jiangsu' && p !== '江苏省') return false
        if (props.locationFilter === 'zhejiang' && p !== '浙江省') return false
        if (props.locationFilter === 'other' && (p === '江苏省' || p === '浙江省' || !p)) return false
      }
      if (kw) {
        const haystack = `${s.source_station_name} ${s.province || ''}`.toLowerCase()
        if (!haystack.includes(kw)) return false
      }
      return true
    })
    .map((s) => {
      const status = stationDataStatus(s)
      // 最新 Chl-a 芯片：只用实时快照 markers 的真实报数值（chlaById），
      // 缺测站不渲染芯片（目录对象本身无该字段，绝不本地造值）。
      const chla = props.chlaById?.[s.id]
      const hasChla = chla != null && Number.isFinite(Number(chla))
      return {
        ...s,
        dataStatusText: STATION_STATUS_TEXT[status] || '—',
        dataStatusTone: status === 'normal' ? 'low' : status === 'delayed' ? 'mid' : 'high',
        dotTone: DOT_TONE[status] || 'overdue',
        chlaColor: hasChla ? chlaColor(Number(chla)) : 'transparent',
        chlaText: hasChla ? `${Number(chla)} μg/L` : '',
        variableTotal: s.available_variable_count + s.missing_variable_count + s.qc_rejected_variable_count,
        waterLevelText: s.latest_water_quality_level ? `类${s.latest_water_quality_level}` : '—'
      }
    })
    .sort((a, b) => {
      const diff = (STATION_STATUS_ORDER[stationDataStatus(a)] ?? 9) - (STATION_STATUS_ORDER[stationDataStatus(b)] ?? 9)
      if (diff !== 0) return diff
      return String(a.source_station_name).localeCompare(String(b.source_station_name), 'zh-Hans-CN')
    })
})
</script>

<style scoped>
.slp { display: flex; flex-direction: column; gap: 4px; min-height: 0; }
.stn-sec-legend {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.stn-sec-legend i {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  display: inline-block;
  margin-right: 4px;
  vertical-align: -1px;
}
.slp-search { position: relative; display: flex; }
.slp-search input {
  width: 100%;
  min-height: 38px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 13px;
}
.slp-search input:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.slp .stn-filter { margin-bottom: 6px; }
/* 列表铺满所在列（与地图+趋势等高），内部滚动 */
.stn-zone-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
  overflow-y: auto;
  flex: 1;
  min-height: 120px;
  align-content: start;
  padding-right: 2px;
}

/* ===== S1 视觉升级（Grafana 阈值配色 × 站点状态灯 × 选中辉光） ===== */

/* --- 头部统计行：等宽 11px muted，数字来自 statusCounts 真实统计 --- */
.slp-stats {
  margin: 0 0 2px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* --- 数据状态点：三分桶配色（图例与行内同源）；仅行内「过期/异常」呼吸脉冲 --- */
.slp-st-normal { background: var(--c-stable, #5fd6a4); }
.slp-st-delayed { background: var(--c-watch, #f5b45d); }
.slp-st-overdue { background: var(--c-alert, #ef4444); }
.slp-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  margin-right: 4px;
  vertical-align: -1px;
}
/* 呼吸脉冲（2.4s 循环）只在行内状态点上；reduced-motion 下不声明动画即全静态 */
@media (prefers-reduced-motion: no-preference) {
  .zi-risk .slp-st-overdue { animation: slp-breathe 2.4s ease-in-out infinite; }
}
@keyframes slp-breathe {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c-alert, #ef4444) 42%, transparent); opacity: 1; }
  50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--c-alert, #ef4444) 0%, transparent); opacity: 0.55; }
}

/* --- 行交互：200ms 过渡 + hover 边框亮化/轻微上浮（上浮属位移，reduced-motion 下关闭） ---
   .slp 前缀提高特异性以稳定覆盖 Stations.vue 共享 stn-* 同名规则（不改共享文件） */
.slp .stn-zone-item {
  transition:
    border-color 0.2s ease,
    background-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}
.slp .stn-zone-item:hover {
  border-color: color-mix(in srgb, var(--c-accent) 45%, transparent);
}
@media (prefers-reduced-motion: no-preference) {
  .slp .stn-zone-item:hover { transform: translateY(-1px); }
}

/* --- 选中行：左缘 3px 主色条 + 主色 10% 底 + 主色外辉光（25% / blur 14px） --- */
.slp .stn-zone-item.selected {
  border-color: color-mix(in srgb, var(--c-accent) 55%, transparent);
  background: color-mix(in srgb, var(--c-accent) 10%, transparent);
  box-shadow:
    inset 3px 0 0 0 var(--c-accent),
    0 0 0 1px color-mix(in srgb, var(--c-accent) 22%, transparent),
    0 4px 14px color-mix(in srgb, var(--c-accent) 25%, transparent);
}

/* --- 行内排版：右列右对齐；分数等宽 + 表格数字对齐 --- */
.slp-side-row {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  min-width: 0;
}
.slp .zi-score { font-variant-numeric: tabular-nums; }

/* --- 最新 Chl-a 值芯片：chlaColor() 语义色 14% 底（同地图口径）；缺值为中性灰占位 --- */
.slp-chla {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--chla-c, #7d93a8) 32%, transparent);
  background: color-mix(in srgb, var(--chla-c, #7d93a8) 14%, transparent);
  color: var(--chla-c, #7d93a8);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}
</style>
