<template>
  <section class="stn-block sfc" aria-label="最新预测">
    <div class="stn-sec-head">
      <h2>最新预测</h2>
      <span v-if="state === 'ok'" class="stn-sec-tag">机理+AI 融合 v0.1</span>
    </div>

    <div v-if="state === 'loading'" class="stn-list-skeleton" aria-hidden="true">
      <div class="skel-row"></div>
      <div class="skel-row"></div>
    </div>

    <div v-else-if="state === 'error'" class="sfc-blocked" role="alert">
      <b>预测加载失败</b>
      <span>站点级预测服务暂时不可用，可重试。</span>
      <button type="button" class="stn-inline-btn sfc-retry" @click="load(true)">重试</button>
    </div>

    <!-- 未覆盖：该站无叶绿素a 序列，试点仅覆盖有序列站点；不以规则结果冒充模型预测 -->
    <div v-else-if="state === 'uncovered'" class="sfc-blocked" data-role="forecast-uncovered">
      <b>本站暂无模型预测</b>
      <span>{{ uncoveredReason }}</span>
      <span>站点级预测试点由 MEE 官方观测训练，仅覆盖数据窗口内有叶绿素 a 序列的站点；可前往时空推演查看基于实测的透明规则研判。</span>
    </div>

    <template v-else-if="state === 'ok' && primary">
      <div class="sfc-main" data-role="forecast-main">
        <div class="sfc-band-row">
          <span class="sfc-band" :class="`sfc-band--${primary.band}`">{{ primary.band_label }}</span>
          <span class="sfc-value">
            预测叶绿素 a <b>{{ primary.chlorophyll_a.value }}</b> μg/L
            <small>区间 {{ primary.chlorophyll_a.lower_bound }}–{{ primary.chlorophyll_a.upper_bound }}</small>
          </span>
        </div>
        <p class="sfc-meta">
          基于 {{ formatCn(originTime) }} 观测，预测 {{ formatCn(primary.target_time) }}（T+{{ primary.horizon_days }} 天）；
          风险分 <b>{{ primary.risk_score }}</b>/100（{{ primary.fusion_formula }}）
        </p>
        <p v-if="primary.band_conservative !== primary.band && primary.band_conservative !== 'none'" class="sfc-note">
          区间上界 {{ primary.chlorophyll_a.upper_bound }} μg/L，可能触及{{ bandShort(primary.band_conservative) }}档
        </p>
      </div>

      <div class="sfc-drivers" data-role="forecast-drivers">
        <span class="sfc-drivers-title">主要驱动因子（线性归因）</span>
        <ul>
          <li v-for="d in primary.drivers" :key="d.feature">
            <i :class="d.direction === 'raise' ? 'up' : 'down'">{{ d.direction === 'raise' ? '↑' : '↓' }}</i>
            {{ d.label }}
          </li>
        </ul>
      </div>

      <p class="sfc-eval" data-role="forecast-eval">
        试点评估（时间交叉验证）：平均误差 {{ evaluation.mae_ugl }} μg/L
        （持续性基线 {{ evaluation.mae_persistence_ugl }} μg/L），档位准确率 {{ Math.round(evaluation.band_accuracy * 100) }}%
      </p>

      <details class="sfc-disclosure">
        <summary>口径与模型披露</summary>
        <p v-for="(note, i) in forecast.model_card.notes" :key="i">{{ note }}</p>
        <p v-if="blockedHorizons.length">
          未开放提前期：{{ blockedHorizons.map((b) => `T+${b.horizon_days} 天（${b.detail}）`).join('；') }}。
        </p>
        <p>训练窗口 {{ formatCn(forecast.model_card.training.origin_from) }} 至 {{ formatCn(forecast.model_card.training.origin_to) }}，{{ forecast.model_card.training.n_origins }} 个样本时点。</p>
      </details>
    </template>

    <button type="button" class="stn-inline-btn sfc-goto" data-role="goto-heatmap" @click="gotoHeatmap">
      进入时空推演 →
    </button>
  </section>
</template>

<script setup>
// 最新预测卡：接入站点级机理+AI 融合预测（/realtime/stations/{id}/forecast，v0.1 试点）。
// 诚实呈现三态——覆盖站点显示模型预测+模型卡披露；无叶绿素a 序列站点显示覆盖范围说明；
// 服务异常显示错误态。档位口径与预警引擎一致（10/25 μg/L 筛查阈值）。
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, getStationForecastEnvelope } from '../../services/api.js'

const props = defineProps({
  stationId: { type: String, default: '' }
})

const router = useRouter()
const state = ref('loading')
const forecast = ref(null)
const uncoveredReason = ref('')

const primary = computed(() => forecast.value?.forecasts?.[0])
const originTime = computed(() => forecast.value?.origin_time)
const evaluation = computed(() => primary.value?.evaluation || {})
const blockedHorizons = computed(() => forecast.value?.model_card?.blocked_horizons || [])

async function load(force = false) {
  if (!props.stationId) {
    state.value = 'uncovered'
    uncoveredReason.value = '未选择站点'
    return
  }
  state.value = 'loading'
  try {
    const { data } = await getStationForecastEnvelope(props.stationId)
    forecast.value = data
    state.value = 'ok'
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      state.value = 'uncovered'
      uncoveredReason.value = error.message || ''
    } else {
      state.value = 'error'
    }
  }
}

watch(() => props.stationId, () => load(true), { immediate: true })

function formatCn(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, '0')}:00`
}

function bandShort(band) {
  return { none: '正常', light: '轻度筛查', moderate: '中度筛查' }[band] || band
}

function gotoHeatmap() {
  const query = { mode: 'forecast', scale: 'short', metric: 'risk' }
  if (props.stationId) query.station = props.stationId
  router.push({ path: '/heatmap', query })
}
</script>

<style scoped>
.sfc-blocked {
  display: grid;
  gap: 3px;
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent);
  border-radius: 10px;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--risk-medium, #f5b45d) 5%, transparent);
}
.sfc-blocked b {
  font-size: 12px;
  color: var(--risk-medium, #f5b45d);
}
.sfc-blocked span {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.sfc-retry {
  justify-self: start;
}
.sfc-main {
  display: grid;
  gap: 5px;
}
.sfc-band-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.sfc-band {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  color: #04121f;
}
.sfc-band--none { background: var(--risk-low, #22c55e); }
.sfc-band--light { background: var(--risk-medium, #facc15); }
.sfc-band--moderate { background: var(--risk-critical, #ef4444); color: #fff; }
.sfc-value {
  font-size: 12px;
  color: var(--text-secondary);
}
.sfc-value b {
  font-size: 16px;
  color: var(--text-primary);
}
.sfc-value small {
  color: var(--text-tertiary, var(--text-secondary));
}
.sfc-meta,
.sfc-note,
.sfc-eval {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.sfc-drivers-title {
  font-size: 11px;
  color: var(--text-tertiary, var(--text-secondary));
}
.sfc-drivers ul {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11px;
  color: var(--text-secondary);
}
.sfc-drivers i {
  font-style: normal;
  margin-right: 2px;
}
.sfc-drivers i.up { color: var(--risk-high, #f97316); }
.sfc-drivers i.down { color: var(--risk-low, #22c55e); }
.sfc-disclosure {
  font-size: 11px;
  color: var(--text-secondary);
}
.sfc-disclosure summary {
  cursor: pointer;
  color: var(--text-tertiary, var(--text-secondary));
}
.sfc-disclosure p {
  margin: 4px 0 0;
  line-height: 1.6;
}
.sfc-goto {
  justify-self: start;
}
</style>
