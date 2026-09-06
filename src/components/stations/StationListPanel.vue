<template>
  <section class="stn-block slp" aria-label="实时站点列表">
    <div class="stn-sec-head">
      <h2>实时站点（{{ stations.length }}）</h2>
      <span class="stn-sec-tag">排序：数据异常 → 严重过期 → 延迟 → 正常</span>
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

    <div class="stn-filter" role="group" aria-label="数据状态筛选">
      <button
        v-for="opt in STATUS_FILTERS"
        :key="opt.key"
        type="button"
        :class="{ active: filter === opt.key }"
        :aria-pressed="String(filter === opt.key)"
        @click="$emit('update:filter', opt.key)"
      >
        {{ opt.label }}<small v-if="opt.key !== 'all'"> {{ statusCounts[opt.key] || 0 }}</small>
      </button>
    </div>

    <div class="stn-filter" role="group" aria-label="位置状态筛选">
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
        >
          <span class="zi-rank">{{ s.waterLevelText }}</span>
          <span class="zi-main">
            <span class="zi-code">{{ s.province || '—' }} · {{ s.location.locationStatusText }}</span>
            <span class="zi-name">{{ s.source_station_name }}</span>
          </span>
          <span class="zi-side">
            <span class="zi-risk" :class="`lv-${s.dataStatusTone}`">{{ s.dataStatusText }}</span>
            <span class="zi-score">{{ s.available_variable_count }}/{{ s.variableTotal }}</span>
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
// 实时站点列表：数据全部来自 observed 轨站点目录；排序“数据异常 → 严重过期 → 延迟 → 正常”，
// 不使用任何情景风险分数。位置状态筛选暴露坐标可信度（missing/suspicious 站不画地图点）。
import { computed } from 'vue'
import {
  LOCATION_STATUS_TEXT,
  STATION_STATUS_ORDER,
  STATION_STATUS_TEXT,
  stationDataStatus
} from '../../services/realtime.js'

const props = defineProps({
  stations: { type: Array, required: true },
  selectedId: { type: String, default: '' },
  state: { type: String, default: 'loading' },
  search: { type: String, default: '' },
  filter: { type: String, default: 'all' },
  locationFilter: { type: String, default: 'all' }
})

defineEmits(['select', 'retry', 'reset-filters', 'update:search', 'update:filter', 'update:locationFilter'])

const STATUS_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'abnormal', label: '数据异常' },
  { key: 'severely_overdue', label: '严重过期' },
  { key: 'delayed', label: '延迟' },
  { key: 'normal', label: '正常' }
]

const LOCATION_FILTERS = [
  { key: 'all', label: '全部位置' },
  { key: 'verified', label: '已核验' },
  { key: 'metadata_only', label: '待核验' },
  { key: 'suspicious', label: '坐标可疑' },
  { key: 'missing', label: '无坐标' }
]

const statusCounts = computed(() => {
  const counts = {}
  props.stations.forEach((s) => {
    const key = stationDataStatus(s)
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const locationCounts = computed(() => {
  const counts = {}
  props.stations.forEach((s) => {
    const key = (s.location && s.location.location_status) || 'missing'
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const rows = computed(() => {
  const kw = props.search.trim().toLowerCase()
  return props.stations
    .filter((s) => {
      if (props.filter !== 'all' && stationDataStatus(s) !== props.filter) return false
      const loc = (s.location && s.location.location_status) || 'missing'
      if (props.locationFilter !== 'all' && loc !== props.locationFilter) return false
      if (kw) {
        const haystack = `${s.source_station_name} ${s.province || ''}`.toLowerCase()
        if (!haystack.includes(kw)) return false
      }
      return true
    })
    .map((s) => ({
      ...s,
      dataStatusText: STATION_STATUS_TEXT[stationDataStatus(s)] || '—',
      dataStatusTone: stationDataStatus(s) === 'normal' ? 'low' : stationDataStatus(s) === 'delayed' ? 'mid' : 'high',
      locationStatusText: LOCATION_STATUS_TEXT[(s.location && s.location.location_status)] || '无坐标',
      variableTotal: s.available_variable_count + s.missing_variable_count + s.qc_rejected_variable_count,
      waterLevelText: s.latest_water_quality_level ? `类${s.latest_water_quality_level}` : '—'
    }))
    .sort((a, b) => {
      const diff = (STATION_STATUS_ORDER[stationDataStatus(a)] ?? 9) - (STATION_STATUS_ORDER[stationDataStatus(b)] ?? 9)
      if (diff !== 0) return diff
      return String(a.source_station_name).localeCompare(String(b.source_station_name), 'zh-Hans-CN')
    })
})
</script>

<style scoped>
.slp { display: flex; flex-direction: column; gap: 4px; min-height: 0; }
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
.stn-zone-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
  overflow-y: auto;
  max-height: min(52vh, 560px);
  padding-right: 2px;
}
</style>
