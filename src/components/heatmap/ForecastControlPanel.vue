<template>
  <div class="fcp">
    <!-- 分析模式 -->
    <section class="fcp-sec" aria-label="分析模式">
      <h3 class="fcp-h">分析模式</h3>
      <div class="fcp-modes" role="group" aria-label="分析模式切换">
        <button
          v-for="m in MODES"
          :key="m.key"
          type="button"
          :class="{ active: mode === m.key }"
          :aria-pressed="String(mode === m.key)"
          :data-role="`mode-${m.key}`"
          @click="$emit('update:mode', m.key)"
        >
          {{ m.label }}<small>{{ m.hint }}</small>
        </button>
      </div>
    </section>

    <!-- 空间范围（站点级视图仅预测推演提供） -->
    <section v-if="mode === 'forecast'" class="fcp-sec" aria-label="空间范围">
      <h3 class="fcp-h">空间范围</h3>
      <div class="fcp-modes" role="group" aria-label="空间范围切换">
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
      <div class="fcp-modes" role="group" aria-label="预测指标切换">
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
      <div class="fcp-modes" role="group" aria-label="预测时间尺度切换">
        <button
          v-for="s in SCALES"
          :key="s.key"
          type="button"
          :class="{ active: scale === s.key }"
          :aria-pressed="String(scale === s.key)"
          :data-role="`scale-${s.key}`"
          @click="$emit('update:scale', s.key)"
        >
          {{ s.label }}<small>{{ s.hint }}</small>
        </button>
      </div>
    </section>

    <!-- 图层 -->
    <section v-if="mode !== 'rs'" class="fcp-sec" aria-label="图层">
      <h3 class="fcp-h">图层</h3>
      <div class="fcp-modes" role="group" aria-label="地图图层开关">
        <button
          type="button"
          :class="{ active: realtimeVisible }"
          :aria-pressed="String(realtimeVisible)"
          @click="$emit('update:realtimeVisible', !realtimeVisible)"
        >监测站点</button>
        <button
          type="button"
          :class="{ active: diffEnabled }"
          :aria-pressed="String(diffEnabled)"
          @click="$emit('update:diffEnabled', !diffEnabled)"
        >站点环比变化<small>相对上一快照</small></button>
        <button
          type="button"
          :class="{ active: polygonEnabled }"
          :aria-pressed="String(polygonEnabled)"
          @click="$emit('update:polygonEnabled', !polygonEnabled)"
        >预警范围示意<small>预警站凸包</small></button>
        <button
          type="button"
          :class="{ active: fieldEnabled }"
          :aria-pressed="String(fieldEnabled)"
          data-role="model-field-toggle"
          @click="$emit('update:fieldEnabled', !fieldEnabled)"
        >模型空间场<small>{{ spatialSummary.covered || 0 }} 站可上图 · {{ spatialSummary.withPrediction || 0 }} 站有预测</small></button>
        <button
          type="button"
          :class="{ active: boundaryEnabled }"
          :aria-pressed="String(boundaryEnabled)"
          data-role="model-boundary-toggle"
          @click="$emit('update:boundaryEnabled', !boundaryEnabled)"
        >相对高值区<small>站间相对排序前 35%，非预警范围</small></button>
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
      <div class="fcp-modes" role="group" aria-label="月度栅格场开关">
        <button
          type="button"
          :class="{ active: rasterOpen }"
          :aria-pressed="String(rasterOpen)"
          data-role="raster-toggle"
          @click="$emit('update:rasterOpen', !rasterOpen)"
        >V0.3 月度栅格场<small>{{ rasterOpen ? '收起图层' : '连续栅格 + 20 μg/L 边界' }}</small></button>
      </div>
    </section>

    <!-- 底图（遥感模式） -->
    <section class="fcp-sec" aria-label="底图">
      <h3 class="fcp-h">底图</h3>
      <div class="fcp-modes" role="group" aria-label="底图切换">
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
          <div class="fcp-legend-item"><i style="background:#5fd6a4"></i>正常 &lt;10</div>
          <div class="fcp-legend-item"><i style="background:#f5b45d"></i>轻度 10–25</div>
          <div class="fcp-legend-item"><i style="background:#ef4444"></i>中度 ≥25</div>
          <div class="fcp-legend-item"><i style="background:#7d93a8"></i>未报数</div>
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

const MODES = [
  { key: 'replay', label: '实测回放', hint: 'MEE 逐日快照' },
  { key: 'forecast', label: '预测推演', hint: '未来 1-90 天' },
  { key: 'rs', label: '遥感年度对比', hint: 'THQBCA-V2' }
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
  gap: 14px;
}
.fcp-sec {
  display: grid;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--border-subtle);
}
.fcp-sec:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.fcp-layer-status {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.fcp-layer-status span {
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 2px 8px;
  color: var(--text-secondary);
  font-size: 10px;
}
.fcp-layer-status span[data-state='ok']::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 50%;
  background: #5fd6a4;
}
.fcp-h {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
}
.fcp-modes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.fcp-modes button {
  appearance: none;
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease, border-color 0.15s ease;
}
.fcp-modes button small {
  font-size: 9.5px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  font-weight: 500;
}
.fcp-modes button.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.fcp-modes button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.fcp-modes button:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}
.fcp-btn--blocked {
  border-style: dashed;
}
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
.fcp-stn-search input {
  width: 100%;
  min-height: 34px;
  padding: 6px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
}
.fcp-stn-search input:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.fcp-stn-select {
  width: 100%;
  min-height: 34px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 12.5px;
  padding: 4px 8px;
}
.fcp-stn-select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.fcp-details {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
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
  min-height: 36px;
}
.fcp-details summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.fcp-details summary span {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  font-weight: 500;
}
.fcp-details-body {
  display: grid;
  gap: 6px;
  padding: 2px 10px 10px;
}
.fcp-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.fcp-legend-item i {
  width: 18px;
  height: 12px;
  border-radius: 3px;
  border: 1px solid rgba(255, 255, 255, 0.35);
}

.fcp-kv {
  margin: 0;
  display: grid;
  gap: 4px;
}
.fcp-kv > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
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

@media (max-width: 759px) {
  .fcp-modes button,
  .fcp-stn-search input,
  .fcp-stn-select,
  .fcp-details summary {
    min-height: 44px;
  }
}
</style>
