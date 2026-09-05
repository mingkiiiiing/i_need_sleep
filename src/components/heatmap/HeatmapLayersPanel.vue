<template>
  <div class="hmlp">
    <section class="hmlp-sec" aria-label="图层开关">
      <h3 class="hmlp-h">图层</h3>
      <div class="hmlp-toggles" role="group" aria-label="地图图层开关">
        <button type="button" :aria-pressed="String(gridVisible)" @click="$emit('update:gridVisible', !gridVisible)">演示风险格网</button>
        <button type="button" :aria-pressed="String(pointsVisible)" @click="$emit('update:pointsVisible', !pointsVisible)">演示分区点位</button>
        <button type="button" :aria-pressed="String(labelsVisible)" @click="$emit('update:labelsVisible', !labelsVisible)">地图标签</button>
      </div>
      <div class="hmlp-basemap" role="group" aria-label="底图切换">
        <span class="hmlp-sub">底图</span>
        <button
          type="button"
          :aria-pressed="String(basemap === 'satellite')"
          @click="$emit('update:basemap', 'satellite')"
        >卫星</button>
        <button
          type="button"
          :aria-pressed="String(basemap === 'topo')"
          @click="$emit('update:basemap', 'topo')"
        >地形</button>
      </div>
    </section>

    <section class="hmlp-sec" aria-label="未接入图层">
      <h3 class="hmlp-h">未接入图层</h3>
      <ul class="hmlp-disabled">
        <li v-for="item in disabledLayers" :key="item.name">
          <button type="button" disabled aria-disabled="true">
            <span class="hmlp-dl-name">{{ item.name }}</span>
            <span class="hmlp-dl-reason">{{ item.reason }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section class="hmlp-sec" aria-label="风险等级图例">
      <details class="hmlp-legend" :open="!compact">
        <summary>风险阈值图例<span class="hmlp-legend-hint">0–44 低 · 45–74 中 · 75–100 高</span></summary>
        <div class="hmlp-legend-body">
          <div class="hmlp-legend-item"><i class="lg lg-low"></i>低风险 0–44</div>
          <div class="hmlp-legend-item"><i class="lg lg-mid"></i>中风险 45–74</div>
          <div class="hmlp-legend-item"><i class="lg lg-high"></i>高风险 75–100</div>
          <p class="hmlp-legend-note">格网分数为演示风险分数（risk_score），不是叶绿素 a 浓度。</p>
        </div>
      </details>
    </section>

    <section class="hmlp-sec" aria-label="能力说明">
      <h3 class="hmlp-h">能力说明</h3>
      <ul class="hmlp-caps">
        <li>历史风险层：<b>未接入</b></li>
        <li>当前实况层：<b>未接入</b></li>
        <li>未来风险场：<b>演示预演</b></li>
      </ul>
      <ul v-if="capabilityRows.length" class="hmlp-cap-chips">
        <li v-for="row in capabilityRows" :key="row.label">
          <span>{{ row.label }}</span>
          <code>{{ row.status }}</code>
        </li>
      </ul>
      <p v-else-if="capsState === 'loading'" class="hmlp-caps-loading">能力接口加载中…</p>
      <p v-else-if="capsState === 'error'" class="hmlp-caps-error">
        能力接口请求失败
        <button type="button" class="hmlp-inline-btn" @click="$emit('retry-caps')">重试</button>
      </p>
      <p class="hmlp-note">演示格网定位仅用于界面联调，不代表真实遥感像元边界。</p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  gridVisible: { type: Boolean, default: true },
  pointsVisible: { type: Boolean, default: true },
  labelsVisible: { type: Boolean, default: true },
  basemap: { type: String, default: 'satellite' },
  // /forecast-capabilities 返回的 capabilities 映射
  capabilities: { type: Object, default: null },
  capsState: { type: String, default: 'loading' },
  // 移动端抽屉形态：图例默认折叠
  compact: { type: Boolean, default: false }
})

defineEmits(['update:gridVisible', 'update:pointsVisible', 'update:labelsVisible', 'update:basemap', 'retry-caps'])

const disabledLayers = [
  { name: '历史水华点', reason: '未接入' },
  { name: '扩散轨迹', reason: '未提供' },
  { name: '风险多边形', reason: '当前接口为空' },
  { name: '3D 模式', reason: '本阶段不实现' }
]

const CAP_LABELS = {
  historical_observation: '历史观测',
  short_term_forecast_1_3d: '短临预测 1–3 天',
  medium_term_forecast_7_15d: '中期预测 7–15 天',
  long_term_forecast_30_90d: '长期预测 30–90 天',
  satellite_chlorophyll: '卫星叶绿素',
  real_time_warning_dispatch: '实时预警发布',
  demo_warning_dispatch: '演示预警发送'
}

const capabilityRows = computed(() => {
  if (!props.capabilities) return []
  return Object.entries(props.capabilities)
    .filter(([key]) => CAP_LABELS[key])
    .map(([key, status]) => ({ label: CAP_LABELS[key], status }))
})
</script>

<style scoped>
.hmlp {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.hmlp-sec {
  display: grid;
  gap: 8px;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--border-subtle);
}
.hmlp-sec:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.hmlp-h {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
}
.hmlp-toggles,
.hmlp-basemap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.hmlp-sub {
  align-self: center;
  font-size: 11px;
  color: var(--text-muted);
}
.hmlp-toggles button,
.hmlp-basemap button {
  appearance: none;
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
.hmlp-toggles button[aria-pressed='true'],
.hmlp-basemap button[aria-pressed='true'] {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.hmlp-toggles button:focus-visible,
.hmlp-basemap button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.hmlp-disabled {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.hmlp-disabled button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px dashed var(--border-subtle);
  border-radius: 9px;
  background: transparent;
  padding: 7px 10px;
  cursor: not-allowed;
  text-align: left;
}
.hmlp-dl-name {
  font-size: 12px;
  color: var(--text-muted);
}
.hmlp-dl-reason {
  font-size: 10.5px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  padding: 1px 7px;
  white-space: nowrap;
}

.hmlp-legend {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
}
.hmlp-legend summary {
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
.hmlp-legend summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.hmlp-legend-hint {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  font-weight: 500;
}
.hmlp-legend-body {
  display: grid;
  gap: 6px;
  padding: 2px 10px 10px;
}
.hmlp-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
.lg {
  width: 18px;
  height: 12px;
  border-radius: 3px;
  border: 1px solid rgba(255, 255, 255, 0.35);
}
.lg-low { background: rgba(47, 158, 99, 0.55); }
.lg-mid { background: rgba(234, 179, 8, 0.6); }
.lg-high { background: rgba(239, 68, 68, 0.66); }
.hmlp-legend-note {
  margin: 2px 0 0;
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-muted);
}

.hmlp-caps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 5px;
}
.hmlp-caps li {
  font-size: 12px;
  color: var(--text-secondary);
}
.hmlp-caps li b {
  color: var(--text-primary);
  font-weight: 650;
}
.hmlp-cap-chips {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.hmlp-cap-chips li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}
.hmlp-cap-chips code {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--data-simulated, #7cb8c9);
  border: 1px solid color-mix(in srgb, var(--data-simulated, #7cb8c9) 40%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
  word-break: break-all;
  text-align: right;
}
.hmlp-caps-loading,
.hmlp-caps-error {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-muted);
}
.hmlp-caps-error {
  color: var(--risk-medium, #facc15);
}
.hmlp-inline-btn {
  appearance: none;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  margin-left: 6px;
  cursor: pointer;
}
.hmlp-note {
  margin: 8px 0 0;
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--text-muted);
}

@media (max-width: 759px) {
  .hmlp-toggles button,
  .hmlp-basemap button,
  .hmlp-inline-btn {
    min-height: 44px;
  }
  .hmlp-disabled button {
    min-height: 44px;
  }
  .hmlp-legend summary {
    min-height: 44px;
  }
}
</style>
