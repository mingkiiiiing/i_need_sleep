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
        <!-- 主值为浓度 μg/L（非 0-1 概率），按口径走大数字版式，不画环形仪 -->
        <div class="sfc-hero" :class="`sfc-hero--${primary.band}`">
          <span class="sfc-band" :class="`sfc-band--${primary.band}`">{{ primary.band_label }}</span>
          <span class="sfc-hero-label">预测叶绿素 a</span>
          <span class="sfc-hero-value">
            <b>{{ primary.chlorophyll_a.value }}</b>
            <i>μg/L</i>
          </span>
          <small class="sfc-hero-range">区间 {{ primary.chlorophyll_a.lower_bound }}–{{ primary.chlorophyll_a.upper_bound }}</small>
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
          <li v-for="d in primary.drivers" :key="d.feature" class="sfc-driver">
            <span class="sfc-driver-line">
              <i :class="d.direction === 'raise' ? 'up' : 'down'">{{ d.direction === 'raise' ? '↑' : '↓' }}</i>
              <span class="sfc-driver-label">{{ d.label }}</span>
              <span class="sfc-driver-val">{{ fmtContrib(d.contribution_log) }}</span>
            </span>
            <span class="sfc-driver-track" aria-hidden="true">
              <i class="sfc-driver-bar" :class="d.direction === 'raise' ? 'up' : 'down'" :style="{ width: driverBarWidth(d) }"></i>
            </span>
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
      <span>进入时空推演</span>
      <i class="sfc-goto-arrow" aria-hidden="true">→</i>
    </button>
  </section>
</template>

<script setup>
// 最新预测卡：接入站点级机理+AI 融合预测（/realtime/stations/{id}/forecast，v0.1 试点）。
// 诚实呈现三态——覆盖站点显示模型预测+模型卡披露；无叶绿素a 序列站点显示覆盖范围说明；
// 服务异常显示错误态。档位口径与预警引擎一致（10/25 μg/L 筛查阈值）。
// 视觉口径：主值为叶绿素 a 浓度（μg/L），非 0-1 概率 → 大数字版式，不画环形仪、不做归一化；
// 驱动条宽度按本组 drivers 的 |contribution_log| 相对最大值缩放（真实线性归因值，同结果面板做法）。
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

// 驱动条：组内相对最大 |contribution_log| 作为显示比例尺，只缩放不造数
const maxDriverContrib = computed(() =>
  (primary.value?.drivers || []).reduce((m, d) => {
    const v = Number(d.contribution_log)
    return Number.isFinite(v) ? Math.max(m, Math.abs(v)) : m
  }, 0)
)

function driverBarWidth(d) {
  const v = Number(d.contribution_log)
  if (!Number.isFinite(v) || maxDriverContrib.value <= 0) return '0%'
  return `${Math.min(100, (Math.abs(v) / maxDriverContrib.value) * 100).toFixed(1)}%`
}

function fmtContrib(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${n > 0 ? '+' : ''}${n}`
}

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
  gap: 8px;
}

/* ---- 主值：大数字版式（非概率主值不画环），左侧档位语义色竖条承色 ---- */
.sfc-hero {
  display: grid;
  gap: 4px;
  justify-items: start;
  padding: 8px 12px;
  border-left: 3px solid var(--risk-medium, #facc15);
  border-radius: 0 var(--radius-sm, 10px) var(--radius-sm, 10px) 0;
  background: color-mix(in srgb, var(--risk-medium, #facc15) 6%, transparent);
}
.sfc-hero--none {
  border-left-color: var(--risk-low, #22c55e);
  background: color-mix(in srgb, var(--risk-low, #22c55e) 6%, transparent);
}
.sfc-hero--light {
  border-left-color: var(--risk-medium, #facc15);
  background: color-mix(in srgb, var(--risk-medium, #facc15) 6%, transparent);
}
.sfc-hero--moderate {
  border-left-color: var(--risk-critical, #ef4444);
  background: color-mix(in srgb, var(--risk-critical, #ef4444) 6%, transparent);
}
.sfc-band {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-pill, 999px);
  color: #04121f;
}
.sfc-band--none { background: var(--risk-low, #22c55e); }
.sfc-band--light { background: var(--risk-medium, #facc15); }
.sfc-band--moderate { background: var(--risk-critical, #ef4444); color: #fff; }
.sfc-hero-label {
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}
.sfc-hero-value {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}
.sfc-hero-value b {
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: 0.01em;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.sfc-hero-value i {
  font-style: normal;
  font-size: 11px;
  color: var(--text-secondary);
}
.sfc-hero-range {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-tertiary, var(--text-secondary));
}
.sfc-meta,
.sfc-note {
  margin: 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* ---- 驱动因子：令牌化条形 + 240ms 宽度过渡 + 数值右对齐等宽 ---- */
.sfc-drivers-title {
  display: block;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--text-tertiary, var(--text-secondary));
}
.sfc-drivers ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
  font-size: 11px;
  color: var(--text-secondary);
}
.sfc-driver {
  display: grid;
  gap: 4px;
}
.sfc-driver-line {
  display: flex;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
}
.sfc-driver-line > i {
  font-style: normal;
  flex: none;
}
.sfc-driver-line > i.up { color: var(--risk-high, #f97316); }
.sfc-driver-line > i.down { color: var(--risk-low, #22c55e); }
.sfc-driver-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.sfc-driver-val {
  flex: none;
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
}
.sfc-driver-track {
  display: block;
  height: 4px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-subtle) 30%, transparent);
  overflow: hidden;
}
.sfc-driver-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 240ms ease;
}
.sfc-driver-bar.up { background: var(--risk-high, #f97316); }
.sfc-driver-bar.down { background: var(--risk-low, #22c55e); }

/* ---- 评估注记：左侧 2px 语义色竖条 + 浅底分层 ---- */
.sfc-eval {
  margin: 0;
  padding: 8px 10px;
  border-left: 2px solid var(--c-watch, var(--risk-medium, #f5b45d));
  border-radius: 0 8px 8px 0;
  background: color-mix(in srgb, var(--c-watch, var(--risk-medium, #f5b45d)) 7%, transparent);
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-secondary);
}
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

/* ---- 跳转按钮：主色描边 + 箭头图标，≥44px 触达 ---- */
.stn-inline-btn.sfc-goto {
  justify-self: start;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, transparent);
  border-radius: var(--radius-pill, 999px);
  background: transparent;
  color: var(--color-primary);
  transition: background-color 160ms ease, border-color 160ms ease;
}
.stn-inline-btn.sfc-goto:hover {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  border-color: var(--color-primary);
  filter: none;
}
.sfc-goto-arrow {
  font-style: normal;
  transition: transform 160ms ease;
}
.stn-inline-btn.sfc-goto:hover .sfc-goto-arrow {
  transform: translateX(2px);
}

@media (prefers-reduced-motion: reduce) {
  .sfc-driver-bar,
  .stn-inline-btn.sfc-goto,
  .sfc-goto-arrow {
    transition: none;
  }
  .stn-inline-btn.sfc-goto:hover .sfc-goto-arrow {
    transform: none;
  }
}
</style>
