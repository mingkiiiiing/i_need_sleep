<template>
  <section class="stn-block spc" aria-label="站点档案">
    <div class="stn-sec-head">
      <h2>站点档案</h2>
      <span v-if="statusText" class="spc-status" :class="`spc-status--${statusTone}`" data-role="profile-status">{{ statusText }}</span>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 3" :key="i"></div>
    </div>

    <dl v-else class="stn-kv spc-kv" data-role="profile-kv">
      <dt>省份</dt><dd>{{ province || '—' }}</dd>
      <dt>所属流域</dt><dd>太湖流域</dd>
      <template v-if="lonLat">
        <dt>经纬度</dt>
        <dd class="stn-mono">{{ lonLat }}<small v-if="locationText" class="spc-loc" :class="{ 'spc-loc--warn': locationWarn }">{{ locationText }}</small></dd>
      </template>
      <dt>数据来源</dt><dd>MEE 国控实时快照</dd>
      <dt>最新观测</dt><dd class="stn-mono">{{ observedAtText }}</dd>
      <dt>观测滞后</dt><dd class="stn-mono">{{ lagText }}</dd>
    </dl>
  </section>
</template>

<script setup>
// 站点档案：站名/状态/省份/经纬度（含坐标可信度）/来源/最新观测时间。
// 原独立“数据质量”卡删除后，覆盖率并入「最新观测」标题、快照/QC 明细并入底部折叠抽屉。
import { computed } from 'vue'
import { LOCATION_STATUS_TEXT, formatLag, formatStamp, stationDataStatus, STATION_STATUS_TEXT } from '../../services/realtime.js'

const props = defineProps({
  station: { type: Object, default: null },
  quality: { type: Object, default: null },
  state: { type: String, default: 'loading' }
})

const statusKey = computed(() => (props.station ? stationDataStatus(props.station) : ''))
const statusText = computed(() => STATION_STATUS_TEXT[statusKey.value] || '')
const statusTone = computed(() => (statusKey.value === 'normal' ? 'ok' : statusKey.value === 'delayed' ? 'delayed' : 'bad'))

const province = computed(() => props.station?.province || '')
const lonLat = computed(() => {
  const loc = props.station?.location
  if (!loc || loc.lat == null || loc.lon == null) return ''
  return `${Number(loc.lat).toFixed(3)}°N, ${Number(loc.lon).toFixed(3)}°E`
})
const locationText = computed(() => {
  const key = props.quality?.location_status
  if (!key || key === 'metadata_only') return ''
  return LOCATION_STATUS_TEXT[key] || ''
})
const locationWarn = computed(() => props.quality?.location_status === 'suspicious')
const observedAtText = computed(() => {
  const t = props.station?.latest_observed_at
  return t ? formatStamp(t) : '—'
})
const lagText = computed(() => (props.quality?.observed_lag_h != null ? formatLag(props.quality.observed_lag_h) : '—'))
</script>

<style scoped>
.spc-status {
  font-size: 10.5px;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
}
.spc-status--ok { color: var(--risk-low, #5fd6a4); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.spc-status--delayed { color: var(--risk-medium, #f5b45d); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.spc-status--bad { color: var(--risk-critical, #ef4444); border-color: color-mix(in srgb, currentColor 45%, transparent); }
.spc-kv { margin: 0; }
.spc-loc {
  margin-left: 6px;
  font-size: 10px;
  color: var(--text-muted);
}
.spc-loc--warn { color: var(--risk-medium, #f5b45d); }
</style>
