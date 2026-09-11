<template>
  <div class="fcp" :class="{ 'fcp--compact': compact }">
    <!-- 分析模式 -->
    <section class="fcp-sec" aria-label="分析模式">
      <h3 class="fcp-h">分析模式</h3>
      <div class="fcp-mode-cards" role="group" aria-label="分析模式切换">
        <button
          v-for="m in MODES"
          :key="m.key"
          type="button"
          class="fcp-mode-card"
          :class="{ active: mode === m.key }"
          :aria-pressed="String(mode === m.key)"
          :data-role="`mode-${m.key}`"
          @click="$emit('update:mode', m.key)"
        >
          <svg class="fcp-mode-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path v-for="(d, i) in m.icon" :key="i" :d="d" />
          </svg>
          <span class="fcp-mode-text">
            <span class="fcp-mode-name">{{ m.label }}</span>
            <small class="fcp-mode-hint">{{ m.hint }}</small>
          </span>
        </button>
      </div>
    </section>

    <!-- 空间范围（站点级视图仅预测推演提供） -->
    <section v-if="mode === 'forecast'" class="fcp-sec" aria-label="空间范围">
      <h3 class="fcp-h">空间范围</h3>
      <div class="fcp-seg" role="group" aria-label="空间范围切换">
        <button
          type="button"
          :class="{ active: scope === 'lake' }"
          :aria-pressed="String(scope === 'lake')"
          data-role="scope-lake"
          @click="$emit('update:scope', 'lake')"
        >全湖</button>
        <button
          type="button"
          :class="{ active: scope === 'station' }"
          :aria-pressed="String(scope === 'station')"
          data-role="scope-station"
          @click="$emit('update:scope', 'station')"
        >监测站</button>
      </div>
      <template v-if="scope === 'station'">
        <div class="fcp-stn-search stn-search-row">
          <svg class="fcp-search-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z" />
            <path d="m20 20-3.2-3.2" />
          </svg>
          <input
            :value="stationQuery"
            type="search"
            placeholder="搜索站名筛选"
            aria-label="搜索监测站"
            data-role="station-search"
            @input="$emit('update:stationQuery', $event.target.value)"
          />
        </div>
        <select
          class="fcp-stn-select"
          :value="stationId"
          aria-label="选择监测站"
          data-role="station-select"
          @change="$emit('station-select', $event.target.value)"
        >
          <option value="">选择监测站（{{ stations.length }} 站）</option>
          <option v-for="s in stationOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <p class="fcp-note">也可直接点击地图上的站点圆点。</p>
      </template>
    </section>

    <!-- 预测指标 -->
    <section v-if="mode === 'forecast'" class="fcp-sec" aria-label="预测指标">
      <h3 class="fcp-h">预测指标</h3>
      <div class="fcp-seg fcp-seg--grid" role="group" aria-label="预测指标切换">
        <button
          v-for="m in METRICS"
          :key="m.key"
          type="button"
          :class="{ active: metric === m.key }"
          :aria-pressed="String(metric === m.key)"
          :disabled="false"
          aria-disabled="false"
          :data-role="`metric-${m.key}`"
          @click="$emit('update:metric', m.key)"
        >
          {{ m.label }}
        </button>
      </div>
    </section>

    <!-- 时间尺度（预测推演模式；与时间轴一级联动） -->
    <section v-if="mode === 'forecast'" class="fcp-sec" aria-label="时间尺度">
      <h3 class="fcp-h">时间尺度</h3>
      <div class="fcp-scale-list" role="group" aria-label="预测时间尺度切换">
        <button
          v-for="s in SCALES"
          :key="s.key"
          type="button"
          class="fcp-scale-row"
          :class="{ active: scale === s.key }"
          :aria-pressed="String(scale === s.key)"
          :data-role="`scale-${s.key}`"
          @click="$emit('update:scale', s.key)"
        >
          <span class="fcp-scale-name">{{ s.label }}</span>
          <small class="fcp-scale-hint">{{ s.hint }}</small>
        </button>
      </div>
    </section>

    <!-- 图层 -->
    <section v-if="mode !== 'rs'" class="fcp-sec" aria-label="图层">
      <h3 class="fcp-h">图层</h3>
      <div class="fcp-toggles" role="group" aria-label="地图图层开关">
        <span class="fcp-sub">基础图层</span>
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': realtimeVisible }"
          :aria-pressed="String(realtimeVisible)"
          @click="$emit('update:realtimeVisible', !realtimeVisible)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">监测站点</span>
        </button>
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': diffEnabled }"
          :aria-pressed="String(diffEnabled)"
          @click="$emit('update:diffEnabled', !diffEnabled)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">站点环比变化</span>
          <small class="fcp-tgl-note">相对上一快照</small>
        </button>
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': polygonEnabled }"
          :aria-pressed="String(polygonEnabled)"
          @click="$emit('update:polygonEnabled', !polygonEnabled)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">预警范围示意</span>
          <small class="fcp-tgl-note">预警站凸包</small>
        </button>
        <span class="fcp-sub fcp-sub--div">模型图层</span>
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': fieldEnabled }"
          :aria-pressed="String(fieldEnabled)"
          data-role="model-field-toggle"
          @click="$emit('update:fieldEnabled', !fieldEnabled)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">模型空间场</span>
          <small class="fcp-tgl-note">{{ spatialSummary.covered || 0 }} 站可上图 · {{ spatialSummary.withPrediction || 0 }} 站有预测</small>
        </button>
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': boundaryEnabled }"
          :aria-pressed="String(boundaryEnabled)"
          data-role="model-boundary-toggle"
          @click="$emit('update:boundaryEnabled', !boundaryEnabled)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">相对高值区</span>
          <small class="fcp-tgl-note">站间相对排序前 35%，非预警范围</small>
        </button>
      </div>
      <div v-if="mode === 'forecast'" class="fcp-layer-status" aria-label="空间图层状态">
        <span :data-state="spatialSummary.state" data-role="prediction-coverage">预测覆盖 {{ spatialSummary.withPrediction || 0 }}/{{ spatialSummary.total || '—' }}</span>
        <span :data-state="spatialSummary.state" data-role="spatial-coverage">地图覆盖 {{ spatialSummary.covered || 0 }}/{{ spatialSummary.total || '—' }}</span>
        <span v-if="spatialSummary.notPlottable" data-role="not-plottable-note">未上图 {{ spatialSummary.notPlottable }} 站：缺少可核验坐标，仅列表查看</span>
        <span v-if="boundaryEnabled">圈定 {{ spatialSummary.highCount || 0 }} 个相对高值站</span>
      </div>
    </section>

    <!-- 月度栅格场（V0.3 连续栅格 + 20 μg/L 边界） -->
    <section v-if="mode !== 'rs'" class="fcp-sec" aria-label="月度栅格场">
      <h3 class="fcp-h">月度栅格场</h3>
      <div class="fcp-toggles" role="group" aria-label="月度栅格场开关">
        <button
          type="button"
          class="fcp-tgl"
          :class="{ 'is-on': rasterOpen }"
          :aria-pressed="String(rasterOpen)"
          data-role="raster-toggle"
          @click="$emit('update:rasterOpen', !rasterOpen)"
        >
          <span class="fcp-tgl-switch" aria-hidden="true"></span>
          <span class="fcp-tgl-name">V0.3 月度栅格场</span>
          <small class="fcp-tgl-note">{{ rasterOpen ? '收起图层' : '连续栅格 + 20 μg/L 边界' }}</small>
        </button>
      </div>
    </section>

    <!-- 底图（遥感模式） -->
    <section class="fcp-sec" aria-label="底图">
      <h3 class="fcp-h">底图</h3>
      <div class="fcp-seg" role="group" aria-label="底图切换">
        <button
          type="button"
          :class="{ active: basemap === 'satellite' }"
          :aria-pressed="String(basemap === 'satellite')"
          @click="$emit('update:basemap', 'satellite')"
        >卫星</button>
        <button
          type="button"
          :class="{ active: basemap === 'topo' }"
          :aria-pressed="String(basemap === 'topo')"
          @click="$emit('update:basemap', 'topo')"
        >地形</button>
      </div>
    </section>

    <!-- 实时观测图例（observed） -->
    <section v-if="mode !== 'rs'" class="fcp-sec" aria-label="实时观测图例">
      <details class="fcp-details" :open="!compact">
        <summary>观测图例</summary>
        <div class="fcp-details-body">
          <div class="fcp-legend-item"><i class="lg-ok"></i>正常 &lt;10</div>
          <div class="fcp-legend-item"><i class="lg-watch"></i>轻度 10–25</div>
          <div class="fcp-legend-item"><i class="lg-alert"></i>中度 ≥25</div>
          <div class="fcp-legend-item"><i class="lg-none"></i>未报数</div>
        </div>
      </details>
    </section>

    <section v-if="mode === 'forecast'" class="fcp-sec" aria-label="推演时间">
      <h3 class="fcp-h">推演时间</h3>
      <dl class="fcp-kv">
        <div><dt>预测起报</dt><dd>{{ info.issuedAt }}</dd></div>
        <div><dt>数据更新</dt><dd>{{ info.dataTime }}</dd></div>
      </dl>
    </section>
  </div>
</template>

<script setup>
// 时空推演左侧预测控制：分析模式 / 空间范围 / 预测指标 / 时间尺度 / 图层 / 月度栅格场 / 底图 / 模型信息。
// 四类核心指标由算法交付包 V0.3 提供：短临与趋势为逐站模型口径，中长期为月度趋势口径。
import { computed } from 'vue'

const props = defineProps({
  mode: { type: String, default: 'forecast' }, // replay | forecast | rs
  scope: { type: String, default: 'lake' }, // lake | station
  metric: { type: String, default: 'risk' }, // risk | chla | area | biomass
  scale: { type: String, default: 'short' }, // short | mid | long
  stations: { type: Array, default: () => [] },
  stationId: { type: String, default: '' },
  stationQuery: { type: String, default: '' },
  realtimeVisible: { type: Boolean, default: true },
  diffEnabled: { type: Boolean, default: false },
  polygonEnabled: { type: Boolean, default: false },
  fieldEnabled: { type: Boolean, default: true },
  boundaryEnabled: { type: Boolean, default: false },
  basemap: { type: String, default: 'satellite' },
  // V0.3 月度栅格场图层开关：图层属于左侧控制栏，与"模型空间场/相对高值区"同级
  rasterOpen: { type: Boolean, default: false },
  // { runStatus, modelVersion, issuedAt, dataTime }
  info: { type: Object, default: () => ({}) },
  spatialSummary: { type: Object, default: () => ({ state: 'loading', covered: 0, total: 0, highCount: 0 }) },
  compact: { type: Boolean, default: false }
})

defineEmits([
  'update:mode', 'update:scope', 'update:metric', 'update:scale', 'update:stationQuery',
  'station-select', 'update:realtimeVisible', 'update:diffEnabled', 'update:polygonEnabled',
  'update:fieldEnabled', 'update:boundaryEnabled', 'update:basemap', 'update:rasterOpen'
])

// icon 仅为纯装饰线性图标（aria-hidden），不承载任何语义。
const MODES = [
  {
    key: 'replay',
    label: '实测回放',
    hint: 'MEE 逐日快照',
    icon: [
      'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8',
      'M3 3v5h5',
      'M12 7v5l4 2'
    ]
  },
  {
    key: 'forecast',
    label: '预测推演',
    hint: '未来 1-90 天',
    icon: [
      'M3 3v16a2 2 0 0 0 2 2h16',
      'm7 14 3.5-3.5 3 3L19 8',
      'M15 8h4v4'
    ]
  },
  {
    key: 'rs',
    label: '遥感年度对比',
    hint: 'THQBCA-V2',
    icon: [
      'M13 7 9 3 5 7l4 4',
      'm17 11 4 4-4 4-4-4',
      'm8 12 4 4 6-6-4-4Z',
      'm16 8 3-3',
      'M9 21a6 6 0 0 0-6-6'
    ]
  }
]

const METRICS = [
  { key: 'risk', label: '风险等级' },
  { key: 'chla', label: '叶绿素 a' },
  { key: 'area', label: '水华面积' },
  { key: 'biomass', label: '蓝藻生物量' }
]

const SCALES = [
  { key: 'short', label: '短临', hint: '未来 1-3 天' },
  { key: 'mid', label: '趋势', hint: '未来 7-15 天' },
  { key: 'long', label: '中长期', hint: '月度 30/60/90 天' }
]

const stationOptions = computed(() => {
  const kw = props.stationQuery.trim().toLowerCase()
  const list = kw
    ? props.stations.filter((s) => s.name.toLowerCase().includes(kw))
    : props.stations
  return list.slice(0, 200)
})
</script>

<style scoped>
.fcp {
  display: flex;
  flex-direction: column;
  gap: 16px;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--border-subtle) 70%, var(--text-muted)) transparent;
}
.fcp-sec {
  display: grid;
  gap: 10px;
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--border-subtle);
}
.fcp-sec:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

/* —— 分组标题：小字 + 主色刻度 —— */
.fcp-h {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
}
.fcp-h::before {
  content: '';
  flex: none;
  width: 3px;
  height: 10px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--color-primary) 62%, transparent);
}
.fcp-sub {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--text-muted);
}
.fcp-sub--div {
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-subtle);
}

/* ============ 1. 分析模式三段大卡 ============ */
.fcp-mode-cards {
  display: grid;
  gap: 8px;
}
.fcp-mode-card {
  position: relative;
  appearance: none;
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 52px;
  text-align: left;
  padding: 8px 12px 8px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 10px);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  overflow: hidden;
}
.fcp-mode-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--color-primary);
  opacity: 0;
}
/* 图标为圆角芯片式容器：底卡衬托 + 描边，选中时转主色系（纯装饰） */
.fcp-mode-ico {
  box-sizing: border-box;
  flex: none;
  width: 34px;
  height: 34px;
  padding: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  background: color-mix(in srgb, var(--text-muted) 12%, transparent);
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--text-secondary);
}
.fcp-mode-text {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.fcp-mode-name {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-secondary);
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fcp-mode-hint {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fcp-mode-card.active {
  border-color: color-mix(in srgb, var(--color-primary) 52%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  /* 顶部 1px 主色微光，玻璃卡片的“受光”暗示 */
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--color-primary) 22%, transparent);
}
.fcp-mode-card.active::before {
  opacity: 1;
}
.fcp-mode-card.active .fcp-mode-ico {
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
  background: color-mix(in srgb, var(--color-primary) 16%, transparent);
  color: var(--color-primary);
}
.fcp-mode-card.active .fcp-mode-name {
  color: var(--text-primary);
}
.fcp-mode-card:focus-visible,
.fcp-seg button:focus-visible,
.fcp-scale-row:focus-visible,
.fcp-tgl:focus-visible,
.fcp-details summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ============ 2. 单选分段（空间范围 / 指标 / 底图） ============ */
.fcp-seg {
  display: flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 10px);
  background: var(--surface-panel-soft);
}
.fcp-seg button {
  appearance: none;
  flex: 1;
  min-width: 0;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
  cursor: pointer;
}
.fcp-seg button.active {
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
  color: var(--color-primary);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-primary) 40%, transparent);
}
.fcp-seg--grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

/* ============ 3. 时间尺度选项行 ============ */
.fcp-scale-list {
  display: grid;
  gap: 6px;
}
.fcp-scale-row {
  appearance: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-height: 36px;
  padding: 6px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 8px);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}
.fcp-scale-name {
  font-size: 12px;
  font-weight: 650;
}
.fcp-scale-hint {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  text-align: right;
}
.fcp-scale-row.active {
  border-color: color-mix(in srgb, var(--color-primary) 48%, transparent);
  background: color-mix(in srgb, var(--color-primary) 9%, transparent);
}
.fcp-scale-row.active .fcp-scale-name {
  color: var(--text-primary);
}
.fcp-scale-row.active .fcp-scale-hint {
  color: var(--color-primary);
}

/* ============ 4. 图层开关行（自制 switch） ============ */
.fcp-toggles {
  display: grid;
  gap: 2px;
}
.fcp-tgl {
  appearance: none;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 44px;
  padding: 6px 8px;
  border: none;
  border-radius: var(--radius-item, 8px);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}
.fcp-tgl-switch {
  flex: none;
  position: relative;
  width: 32px;
  height: 18px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--text-muted) 28%, transparent);
}
.fcp-tgl-switch::after {
  content: '';
  position: absolute;
  top: 1px;
  left: 1px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-secondary);
}
.fcp-tgl-name {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.fcp-tgl-note {
  flex: none;
  max-width: 46%;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  text-align: right;
  line-height: 1.35;
}
.fcp-tgl.is-on .fcp-tgl-name {
  color: var(--text-primary);
}
.fcp-tgl.is-on .fcp-tgl-switch {
  border-color: color-mix(in srgb, var(--color-primary) 55%, transparent);
  background: color-mix(in srgb, var(--color-primary) 30%, transparent);
}
.fcp-tgl.is-on .fcp-tgl-switch::after {
  transform: translateX(14px);
  background: var(--color-primary);
}

/* —— 图层覆盖状态徽标 —— */
.fcp-layer-status {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.fcp-layer-status span {
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 2px 9px;
  background: color-mix(in srgb, var(--surface-panel-soft) 70%, transparent);
  color: var(--text-secondary);
  font-size: 10px;
  line-height: 1.5;
}
.fcp-layer-status span[data-state='ok']::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 50%;
  background: var(--c-stable, #5fd6a4);
}

/* ============ 5. 站点搜索与选择 ============ */
.fcp-note {
  margin: 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-muted);
}
.fcp-note a {
  color: var(--color-primary);
}
.fcp-stn-search {
  position: relative;
  display: flex;
}
.fcp-search-ico {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  color: var(--text-muted);
  pointer-events: none;
}
.fcp-stn-search input {
  width: 100%;
  min-height: 38px;
  padding: 7px 12px 7px 33px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 8px);
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
}
.fcp-stn-search input::placeholder {
  color: var(--text-muted);
}
.fcp-stn-search input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 32%, transparent);
}
.fcp-stn-select {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item, 8px);
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  padding: 6px 10px;
  cursor: pointer;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--border-subtle) 70%, var(--text-muted)) transparent;
}
.fcp-stn-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary) 32%, transparent);
}

/* —— 8px 细滚动条（thumb 走 --border-subtle 系） —— */
.fcp-stn-select::-webkit-scrollbar,
.fcp-details-body::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.fcp-stn-select::-webkit-scrollbar-track,
.fcp-details-body::-webkit-scrollbar-track {
  background: transparent;
}
.fcp-stn-select::-webkit-scrollbar-thumb,
.fcp-details-body::-webkit-scrollbar-thumb {
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: padding-box;
  background-color: color-mix(in srgb, var(--border-subtle) 75%, var(--text-muted));
}

/* ============ 6. 观测图例（details） ============ */
.fcp-details {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm, 10px);
  background: var(--surface-panel-soft);
}
.fcp-details summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  color: var(--text-secondary);
  min-height: 40px;
  list-style: none;
}
.fcp-details summary::-webkit-details-marker {
  display: none;
}
.fcp-details summary::after {
  content: '';
  flex: none;
  width: 7px;
  height: 7px;
  margin-left: auto;
  border-right: 1.5px solid var(--text-muted);
  border-bottom: 1.5px solid var(--text-muted);
  transform: translateY(-2px) rotate(45deg);
}
.fcp-details[open] summary::after {
  transform: translateY(-1px) rotate(225deg);
}
.fcp-details-body {
  display: grid;
  gap: 7px;
  padding: 2px 12px 12px;
}
.fcp-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.fcp-legend-item i {
  flex: none;
  width: 18px;
  height: 12px;
  border-radius: 3px;
  border: 1px solid color-mix(in srgb, var(--text-primary) 28%, transparent);
}
.fcp-legend-item .lg-ok {
  background: var(--c-stable, #5fd6a4);
}
.fcp-legend-item .lg-watch {
  background: var(--c-watch, #f5b45d);
}
.fcp-legend-item .lg-alert {
  background: var(--risk-critical, #ef4444);
}
.fcp-legend-item .lg-none {
  background: color-mix(in srgb, var(--text-muted) 62%, transparent);
}

/* ============ 7. 推演时间键值 ============ */
.fcp-kv {
  margin: 0;
  display: grid;
  gap: 6px;
}
.fcp-kv > div {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  padding: 5px 9px;
  border-radius: var(--radius-item, 8px);
  background: color-mix(in srgb, var(--surface-panel-soft) 70%, transparent);
}
.fcp-kv dt {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}
.fcp-kv dd {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-primary);
  font-family: var(--font-mono);
  text-align: right;
  word-break: break-all;
}
.fcp-warn {
  color: var(--risk-medium, #f5b45d);
}

/* ============ compact（移动端抽屉复用） ============ */
.fcp--compact {
  gap: 14px;
}
.fcp--compact .fcp-mode-card {
  gap: 9px;
  min-height: 48px;
  padding: 7px 10px 7px 13px;
}
.fcp--compact .fcp-mode-ico {
  width: 30px;
  height: 30px;
  padding: 5px;
  border-radius: 8px;
}
.fcp--compact .fcp-sec {
  gap: 9px;
  padding-bottom: 12px;
}

/* ============ hover / 过渡：仅 reduced-motion: no-preference 下启用 ============ */
@media (prefers-reduced-motion: no-preference) {
  .fcp-mode-card,
  .fcp-seg button,
  .fcp-scale-row,
  .fcp-tgl,
  .fcp-tgl-switch,
  .fcp-tgl-switch::after,
  .fcp-stn-search input,
  .fcp-stn-select,
  .fcp-details,
  .fcp-details summary,
  .fcp-layer-status span,
  .fcp-kv > div {
    transition: background-color 180ms var(--ease-out, ease-out),
      border-color 180ms var(--ease-out, ease-out),
      color 180ms var(--ease-out, ease-out),
      box-shadow 180ms var(--ease-out, ease-out);
  }
  .fcp-mode-card::before {
    transition: opacity 180ms var(--ease-out, ease-out);
  }
  .fcp-mode-card:hover:not(.active) {
    border-color: color-mix(in srgb, var(--color-primary) 30%, transparent);
    background: color-mix(in srgb, var(--color-primary) 5%, transparent);
  }
  .fcp-seg button:hover:not(.active) {
    color: var(--text-primary);
    background: color-mix(in srgb, var(--color-primary) 6%, transparent);
  }
  .fcp-scale-row:hover:not(.active) {
    border-color: color-mix(in srgb, var(--color-primary) 30%, transparent);
    background: color-mix(in srgb, var(--color-primary) 5%, transparent);
  }
  .fcp-tgl:hover {
    background: color-mix(in srgb, var(--color-primary) 6%, transparent);
  }
  .fcp-stn-search input:hover:not(:focus),
  .fcp-stn-select:hover:not(:focus) {
    border-color: color-mix(in srgb, var(--color-primary) 36%, transparent);
  }
  .fcp-details summary:hover {
    color: var(--text-primary);
  }
}

/* ============ 移动端触摸目标 ≥44px ============ */
@media (max-width: 759px) {
  .fcp-seg button,
  .fcp-scale-row,
  .fcp-stn-search input,
  .fcp-stn-select,
  .fcp-details summary {
    min-height: 44px;
  }
}
</style>
