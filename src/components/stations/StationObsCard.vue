<template>
  <section class="stn-block soc" aria-label="最新观测">
    <div class="stn-sec-head">
      <h2>最新观测</h2>
      <span class="stn-sec-tag" data-role="obs-coverage">{{ coverageText }}</span>
    </div>
    <p class="soc-sub" data-role="obs-sub">{{ stationName }} · {{ observedAtText }}</p>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row" v-for="i in 4" :key="i"></div>
    </div>

    <div v-else-if="state === 'error'" class="stn-list-empty" role="alert">
      <p class="sle-title">观测数据加载失败</p>
      <button type="button" class="stn-inline-btn" @click="$emit('retry')">重试</button>
    </div>

    <template v-else>
      <dl class="soc-grid" data-role="obs-primary">
        <div v-for="item in primaryView" :key="item.code" class="soc-cell" :class="`soc-cell--${item.tone}`">
          <dt>{{ item.label }}</dt>
          <dd>
            <strong v-if="item.status === 'ok'">{{ item.text }}</strong>
            <span v-else class="soc-miss">{{ item.status === 'qc_rejected' ? '质控不合格' : '缺测' }}</span>
            <small v-if="item.status === 'ok'">{{ item.unit }}</small>
          </dd>
        </div>
      </dl>

      <template v-if="secondaryView.length">
        <button v-if="!expanded" type="button" class="stn-inline-btn soc-expand" data-role="obs-expand" @click="expanded = true">
          展开全部 {{ secondaryView.length }} 项
        </button>
        <template v-else>
          <dl class="soc-grid" data-role="obs-secondary">
            <div v-for="item in secondaryView" :key="item.code" class="soc-cell" :class="`soc-cell--${item.tone}`">
              <dt>{{ item.label }}</dt>
              <dd>
                <strong v-if="item.status === 'ok'">{{ item.text }}</strong>
                <span v-else class="soc-miss">{{ item.status === 'qc_rejected' ? '质控不合格' : '缺测' }}</span>
                <small v-if="item.status === 'ok'">{{ item.unit }}</small>
              </dd>
            </div>
          </dl>
          <button type="button" class="stn-inline-btn soc-expand" data-role="obs-collapse" @click="expanded = false">收起</button>
        </template>
      </template>
    </template>
  </section>
</template>

<script setup>
// 最新观测卡：优先展示叶绿素 a / 水温 / 总磷 / 总氮 / 溶解氧 5 项，
// 其余 6 项默认折叠（展开全部）；缺测/质控不合格显式展示，不消失、不补值。
// 标题旁展示指标覆盖率（原独立“数据质量”卡删除后就近展示）。
import { computed, ref } from 'vue'
import { REALTIME_VARIABLES, fmtMeasure, formatStamp } from '../../services/realtime.js'

const props = defineProps({
  stationName: { type: String, default: '' },
  observedAt: { type: String, default: '' },
  rows: { type: Array, default: () => [] },
  state: { type: String, default: 'loading' },
  // 质量摘要（覆盖率）：来自 /quality 端点
  quality: { type: Object, default: null }
})

defineEmits(['retry'])

const expanded = ref(false)

const PRIMARY_CODES = ['chlorophyll_a', 'water_temperature', 'total_phosphorus', 'total_nitrogen', 'dissolved_oxygen']

const byCode = computed(() => {
  const map = {}
  props.rows.forEach((row) => { map[row.variable_code] = row })
  return map
})

function cellOf({ code, label }) {
  const row = byCode.value[code]
  const status = row ? row.observation_status : 'missing'
  return {
    code,
    label,
    status,
    text: row && row.value != null ? fmtMeasure(row.value) : '—',
    unit: row && row.unit ? row.unit : '',
    tone: status === 'ok' ? 'ok' : status === 'qc_rejected' ? 'bad' : 'miss'
  }
}

// 按上游固定顺序拆分：主指标在前，其余保持原相对顺序
const ordered = computed(() => {
  const primary = REALTIME_VARIABLES.filter((v) => PRIMARY_CODES.includes(v.code)).map(cellOf)
  const secondary = REALTIME_VARIABLES.filter((v) => !PRIMARY_CODES.includes(v.code)).map(cellOf)
  return { primary, secondary }
})
const primaryView = computed(() => ordered.value.primary)
const secondaryView = computed(() => ordered.value.secondary)

const coverageText = computed(() => {
  const cov = props.quality?.variable_coverage
  if (cov && cov.total) return `指标覆盖 ${cov.ok}/${cov.total}`
  return ''
})

const observedAtText = computed(() => (props.observedAt ? `观测 ${formatStamp(props.observedAt)}` : ''))
</script>

<style scoped>
.soc-sub {
  margin: 0 0 6px;
  font-size: 11px;
  color: var(--text-muted);
}
.soc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
  gap: 6px;
  margin: 0;
}
.soc-cell {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 6px 9px;
  min-width: 0;
}
.soc-cell dt { font-size: 10.5px; color: var(--text-muted); margin: 0 0 2px; }
.soc-cell dd { margin: 0; display: flex; align-items: baseline; gap: 4px; min-width: 0; }
.soc-cell dd strong { font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; }
.soc-cell dd small { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.soc-cell--bad { border-color: color-mix(in srgb, var(--risk-critical, #ef4444) 45%, transparent); }
.soc-cell--miss dd span { font-size: 11px; color: var(--text-muted); }
.soc-miss { color: var(--text-muted); }
.soc-expand { margin-top: 2px; justify-self: start; }
</style>
