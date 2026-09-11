<script setup>
// 全湖驱动因素 = 79 站机理净生长率分解的站间分布（箱线/中位数口径）。
//
// 为什么不是单站条形卡：全湖不是"把站点输入取均值后的虚拟站点"，其驱动因素
// 应呈现站点间分布——中位数、四分位距、限制因子构成、缺测/代理占比。
// 口径披露：机理分解是环境状态口径、与模型无关；它不是模型贡献排序（SHAP），
// 当前模型未通过站点响应验收时尤其不得宣称。
import { computed, onMounted, ref, watch } from 'vue'
import { getDriverDistributionEnvelope } from '../../services/api.js'
import { predictionSnapshot } from '../../stores/predictionSnapshot.js'

const props = defineProps({
  horizonDays: { type: Number, default: 1 }
})

const state = ref('loading')
const errorText = ref('')
const distribution = ref(null)

async function load() {
  state.value = 'loading'
  errorText.value = ''
  try {
    const { data } = await getDriverDistributionEnvelope(props.horizonDays)
    // 版本守卫：响应必须仍属于当前展示的预测世代，避免旧快照分布覆盖新快照。
    if (data.prediction_snapshot_id && predictionSnapshot.predictionSnapshotId
      && data.prediction_snapshot_id !== predictionSnapshot.predictionSnapshotId) {
      return
    }
    distribution.value = data
    state.value = 'ok'
  } catch (err) {
    state.value = 'error'
    errorText.value = err?.message || '全湖驱动分布加载失败'
  }
}

onMounted(load)
watch(() => [props.horizonDays, predictionSnapshot.predictionSnapshotId], load)

const FACTOR_META = {
  temperature: { label: '水温', unit: '℃' },
  light: { label: '光照', unit: 'W/m²' },
  phosphorus: { label: '总磷', unit: 'mg/L' },
  nitrogen: { label: '总氮', unit: 'mg/L' },
  ammonia: { label: '氨氮', unit: 'mg/L' },
  flow: { label: '流速', unit: 'm/s' }
}

const LIMITING_LABELS = {
  temperature: '温度', light: '光照', phosphorus: '磷', nitrogen: '氮',
  ammonia: '氨氮', flow: '流速'
}

function fmt(v, digits = 3) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

// 每个因素一行：P25—中位—P75 在站点值域内的位置（简易箱线，不做数值修饰）
const factorRows = computed(() => {
  const rows = distribution.value?.factors || []
  return rows
    .filter((f) => (f.n ?? 0) > 0)
    .map((f) => {
      const min = Number(f.min)
      const max = Number(f.max)
      const span = max - min
      const pct = (v) => (span > 0 ? Math.min(100, Math.max(0, ((v - min) / span) * 100)) : 50)
      return {
        key: f.key,
        label: FACTOR_META[f.key]?.label || f.label || f.key,
        unit: f.unit || FACTOR_META[f.key]?.unit || '',
        n: f.n,
        total: f.total,
        proxyCount: f.proxy_count || 0,
        median: f.median,
        p25: f.p25,
        p75: f.p75,
        min,
        max,
        p25Pct: pct(f.p25),
        medianPct: pct(f.median),
        p75Pct: pct(f.p75)
      }
    })
})

const limitingRows = computed(() => {
  const dist = distribution.value?.limiting_factor_distribution || {}
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  return Object.entries(dist).map(([key, count]) => ({
    key,
    label: LIMITING_LABELS[key] || key,
    count,
    pct: total ? Math.round((count / total) * 100) : 0
  }))
})

const netGrowth = computed(() => distribution.value?.net_growth_rate_d || null)

const zoneRows = computed(() => {
  const groups = distribution.value?.zone_groups || {}
  return Object.entries(groups).map(([code, g]) => ({
    code,
    name: g.zone_name || code,
    n: g.n,
    tp: g.phosphorus_median,
    tn: g.nitrogen_median,
    limitingLabel: LIMITING_LABELS[g.dominant_limiting_factor] || g.dominant_limiting_factor || '—'
  }))
})

const highRisk = computed(() => distribution.value?.high_risk_groups || null)
const highRiskFactors = computed(() => {
  const hr = highRisk.value
  if (!hr) return []
  const rows = (hr.factors || []).map((f) => {
    const high = Number(f.high_median)
    const rest = Number(f.rest_median)
    const max = Math.max(high || 0, rest || 0) || 1
    return {
      key: f.key,
      label: FACTOR_META[f.key]?.label || f.key,
      high: f.high_median,
      rest: f.rest_median,
      highPct: Number.isFinite(high) ? Math.max((high / max) * 50, 1.5) : 0,
      restPct: Number.isFinite(rest) ? Math.max((rest / max) * 50, 1.5) : 0
    }
  })
  return rows.filter((r) => Number.isFinite(r.high) || Number.isFinite(r.rest))
})
const meta = computed(() => ({
  nStations: distribution.value?.n_stations ?? 0,
  snapshotId: distribution.value?.prediction_snapshot_id || ''
}))

// 数据口径披露：哪些因子没有站间差异，必须明说，不能包装成空间差异驱动。
// 2026-09-11 起温度取本站 MEE 实测水温（逐站），不再是统一气象代理——
// 这条披露必须跟着数据走，否则会把真实存在的站间差异说成"没有差异"。
const LAKE_WIDE_REASON = {
  light: '单一气象网格值（全湖同一格点），物理上不构成站间差异',
  air_temperature: '单一气象网格值（全湖同一格点），物理上不构成站间差异'
}
const dataNotes = computed(() => {
  const rows = distribution.value?.factors || []
  const notes = []
  for (const f of rows) {
    const label = FACTOR_META[f.key]?.label || f.label || f.key
    const total = f.total || 0
    const proxy = f.proxy_count || 0
    if ((f.n ?? 0) === 0) {
      notes.push({ key: f.key, text: `${label}：当前缺少有效数据，不作空间差异驱动展示` })
      continue
    }
    if (total > 0 && proxy === total) {
      notes.push({
        key: f.key,
        text: `${label}：${LAKE_WIDE_REASON[f.key] || `全部站点为代理输入（${proxy}/${total} 站）`}`
      })
      continue
    }
    if (Number.isFinite(Number(f.min)) && Number(f.min) === Number(f.max)) {
      notes.push({ key: f.key, text: `${label}：站间取值相同（统一或低空间分辨率输入）` })
    }
  }
  return notes
})
</script>

<template>
  <section class="ldd" data-role="lake-driver-distribution">
    <div class="ldd-head">
      <div>
        <b>全湖驱动因素 · 79 站分布</b>
        <span>环境状态口径（机理分解），非模型贡献排序</span>
      </div>
      <span class="ldd-n" data-role="ldd-coverage">n={{ meta.nStations }}</span>
    </div>

    <StatePanel v-if="state === 'loading'" state="loading" title="正在汇总 79 站驱动因素…" description="读取当前预测快照的站间机理分解分布。" />
    <StatePanel v-else-if="state === 'error'" state="error" title="全湖驱动分布不可用" :description="errorText">
      <button type="button" class="ldd-retry" @click="load">重试</button>
    </StatePanel>

    <template v-else>
      <div v-for="f in factorRows" :key="f.key" class="ldd-row" data-role="ldd-factor">
        <div class="ldd-row-label">
          <span>{{ f.label }}</span>
          <small v-if="f.proxyCount">{{ f.proxyCount }}/{{ f.total }} 站为代理值</small>
        </div>
        <div class="ldd-box-track" :title="`P25 ${fmt(f.p25)} — 中位 ${fmt(f.median)} — P75 ${fmt(f.p75)} ${f.unit}`">
          <i class="ldd-box" :style="{ left: `${f.p25Pct}%`, width: `${Math.max(f.p75Pct - f.p25Pct, 2)}%` }"></i>
          <i class="ldd-median" :style="{ left: `${f.medianPct}%` }"></i>
        </div>
        <div class="ldd-row-val">
          <b>{{ fmt(f.median) }}</b>
          <small>[{{ fmt(f.p25) }}, {{ fmt(f.p75) }}]</small>
        </div>
      </div>

      <div v-if="limitingRows.length" class="ldd-limiting" data-role="ldd-limiting">
        <span class="ldd-sub">限制因子构成</span>
        <div class="ldd-limiting-row">
          <template v-for="row in limitingRows" :key="row.key">
            <i class="ldd-limiting-seg" :style="{ width: `${row.pct}%` }" :title="`${row.label} ${row.count} 站`"></i>
          </template>
        </div>
        <div class="ldd-limiting-legend">
          <span v-for="row in limitingRows" :key="row.key">{{ row.label }} {{ row.count }} 站（{{ row.pct }}%）</span>
        </div>
      </div>

      <div v-if="zoneRows.length" class="ldd-zones" data-role="ldd-zones">
        <span class="ldd-sub">湖区分组（公示最近质心归属，缺坐标站不参与）</span>
        <div class="ldd-zone-table">
          <div class="ldd-zone-row ldd-zone-head">
            <span>湖区</span><span>站数</span><span>总磷中位</span><span>总氮中位</span><span>主限制因子</span>
          </div>
          <div v-for="z in zoneRows" :key="z.code" class="ldd-zone-row">
            <span>{{ z.name }}</span>
            <span>{{ z.n }}</span>
            <span>{{ fmt(z.tp) }}</span>
            <span>{{ fmt(z.tn) }}</span>
            <span>{{ z.limitingLabel }}</span>
          </div>
        </div>
      </div>

      <div v-if="highRisk" class="ldd-highrisk" data-role="ldd-highrisk">
        <span class="ldd-sub">高风险站 vs 其他站 · {{ highRisk.split_rule }}（{{ highRisk.high_n }}/{{ highRisk.rest_n }} 站）</span>
        <div v-for="f in highRiskFactors" :key="f.key" class="ldd-duo">
          <span class="ldd-duo-label">{{ f.label }}</span>
          <div class="ldd-duo-bar">
            <i class="ldd-duo-high" :style="{ width: f.highPct + '%' }"></i>
            <i class="ldd-duo-rest" :style="{ width: f.restPct + '%' }"></i>
          </div>
          <small>{{ fmt(f.high) }} vs {{ fmt(f.rest) }}</small>
        </div>
        <small class="ldd-note">分组按预测 chla 排序，仅站间相对比较；橙=高风险组，灰=其他站。</small>
      </div>

      <div v-if="netGrowth" class="ldd-net" data-role="ldd-net">
        <span class="ldd-sub">净生长率 d⁻¹（79 站分布）</span>
        <b>中位 {{ fmt(netGrowth.median, 3) }}</b>
        <small>[{{ fmt(netGrowth.p25, 3) }}, {{ fmt(netGrowth.p75, 3) }}] · 范围 {{ fmt(netGrowth.min, 3) }}—{{ fmt(netGrowth.max, 3) }}</small>
      </div>

      <div v-if="dataNotes.length" class="ldd-data-notes" data-role="ldd-data-notes">
        <span class="ldd-sub">数据口径</span>
        <ul>
          <li v-for="n in dataNotes" :key="n.key">{{ n.text }}</li>
        </ul>
      </div>

      <p class="ldd-note">全湖汇总 = 站间分布（中位数/四分位）；不是"均值虚拟站点"的单一输出。</p>
    </template>
  </section>
</template>

<style scoped>
.ldd { display: flex; flex-direction: column; gap: 10px; }
.ldd-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.ldd-head b { font-size: 13px; }
.ldd-head span { display: block; font-size: 11px; color: var(--ink-3, #7d93a8); }
.ldd-n { font-size: 11px; color: var(--ink-3, #7d93a8); white-space: nowrap; }
.ldd-retry { border: 1px solid rgba(127,147,168,0.4); background: transparent; color: inherit; border-radius: 6px; padding: 2px 10px; cursor: pointer; font-size: 12px; }
.ldd-row { display: grid; grid-template-columns: 92px 1fr 96px; align-items: center; gap: 8px; }
.ldd-row-label span { font-size: 12px; font-weight: 600; }
.ldd-row-label small { display: block; font-size: 10px; color: #d08b3c; }
.ldd-box-track { position: relative; height: 14px; border-radius: 7px; background: rgba(127,147,168,0.14); overflow: hidden; }
.ldd-box { position: absolute; top: 2px; bottom: 2px; background: rgba(64,186,180,0.35); border-radius: 4px; }
.ldd-median { position: absolute; top: 0; bottom: 0; width: 2px; background: #2aa8a0; }
.ldd-row-val { text-align: right; }
.ldd-row-val b { font-size: 12px; }
.ldd-row-val small { display: block; font-size: 10px; color: var(--ink-3, #7d93a8); }
.ldd-sub { font-size: 11px; color: var(--ink-3, #7d93a8); }
.ldd-limiting { display: flex; flex-direction: column; gap: 4px; }
.ldd-limiting-row { display: flex; height: 10px; border-radius: 5px; overflow: hidden; }
.ldd-limiting-seg { background: #2aa8a0; }
.ldd-limiting-seg:nth-child(2n) { background: #d08b3c; }
.ldd-limiting-seg:nth-child(3n) { background: #7d93a8; }
.ldd-limiting-legend { display: flex; flex-wrap: wrap; gap: 8px; font-size: 10px; color: var(--ink-3, #7d93a8); }
.ldd-net { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ldd-net b { font-size: 13px; }
.ldd-net small { font-size: 10px; color: var(--ink-3, #7d93a8); }
.ldd-note { font-size: 10px; color: var(--ink-3, #7d93a8); margin: 0; }
.ldd-data-notes {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px dashed var(--border-subtle, rgba(127, 147, 168, 0.4));
  border-radius: 8px;
}
.ldd-data-notes ul {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 2px;
}
.ldd-data-notes li {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary, #9fb3c8);
}
.ldd-zones, .ldd-highrisk { display: flex; flex-direction: column; gap: 5px; }
.ldd-zone-table { display: flex; flex-direction: column; gap: 2px; font-size: 11px; }
.ldd-zone-row { display: grid; grid-template-columns: 64px 32px 1fr 1fr 76px; gap: 6px; }
.ldd-zone-head { color: var(--ink-3, #7d93a8); font-size: 10px; }
.ldd-duo { display: grid; grid-template-columns: 64px 1fr 96px; gap: 8px; align-items: center; font-size: 11px; }
.ldd-duo-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: rgba(127,147,168,0.14); }
.ldd-duo-high { background: #d08b3c; }
.ldd-duo-rest { background: #7d93a8; }
.ldd-duo small { font-size: 10px; color: var(--ink-3, #7d93a8); text-align: right; }
</style>
