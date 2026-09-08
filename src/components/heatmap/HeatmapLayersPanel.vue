<template>
  <div class="hmlp">
    <section class="hmlp-sec" aria-label="图层开关">
      <h3 class="hmlp-h">图层</h3>
      <div class="hmlp-toggles" role="group" aria-label="地图图层开关">
        <button
          type="button"
          class="hmlp-rt-toggle"
          :class="{ 'hmlp-rt-toggle--on': realtimeVisible }"
          :aria-pressed="String(realtimeVisible)"
          @click="$emit('update:realtimeVisible', !realtimeVisible)"
        >实时观测点位（observed）</button>
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

    <section class="hmlp-sec" aria-label="拓展图层（observed 真实数据）">
      <h3 class="hmlp-h">拓展图层 <span class="hmlp-legend-hint">observed 真实数据</span></h3>
      <div class="hmlp-extend">
        <button
          type="button"
          class="hmlp-ext-toggle"
          :class="{ 'hmlp-ext-toggle--on': diffEnabled }"
          :aria-pressed="String(diffEnabled)"
          @click="$emit('update:diffEnabled', !diffEnabled)"
        >
          站点环比变化<span class="hmlp-ext-hint">相对上一快照</span>
        </button>
        <button
          type="button"
          class="hmlp-ext-toggle"
          :class="{ 'hmlp-ext-toggle--on': polygonEnabled }"
          :aria-pressed="String(polygonEnabled)"
          @click="$emit('update:polygonEnabled', !polygonEnabled)"
        >
          预警范围示意<span class="hmlp-ext-hint">预警站凸包</span>
        </button>
        <p class="hmlp-legend-note">
          环比变化：红=叶绿素 a 上升、绿=下降、灰=持平/缺测；预警范围为筛查预警站点的凸包示意（非模型风险场）。
        </p>
      </div>
    </section>

    <section class="hmlp-sec" aria-label="实时观测图例">
      <details class="hmlp-legend" :open="!compact">
        <summary>实时观测图例<span class="hmlp-legend-hint">observed · chla 筛查 μg/L</span></summary>
        <div class="hmlp-legend-body">
          <div class="hmlp-legend-item"><i class="lg" style="background:#5fd6a4"></i>正常 &lt;10</div>
          <div class="hmlp-legend-item"><i class="lg" style="background:#f5b45d"></i>轻度 10–25</div>
          <div class="hmlp-legend-item"><i class="lg" style="background:#ff6b6b"></i>中度 ≥25</div>
          <div class="hmlp-legend-item"><i class="lg" style="background:#7d93a8"></i>未报数</div>
          <p class="hmlp-legend-note">
            站点来自 MEE 国控实时快照（官方观测未经跨源验证）；阈值为筛查口径非监管判定。
          </p>
        </div>
      </details>
    </section>

    <section class="hmlp-sec" aria-label="实时观测实况（observed）">
      <h3 class="hmlp-h">实时观测实况 <span class="hmlp-legend-hint">observed · 非模拟</span></h3>
      <template v-if="realtimeSummary">
        <ul class="hmlp-caps">
          <li>活跃站点：<b>{{ realtimeSummary.active_station_count ?? realtimeSummary.station_total }}</b></li>
          <li>水质达标率（≤III 类）：<b>{{ realtimeSummary.class_iii_rate != null ? (realtimeSummary.class_iii_rate * 100).toFixed(0) + '%' : '—' }}</b></li>
          <li>蓝藻筛查预警：<b :style="realtimeSummary.warnings?.length ? 'color: var(--risk-critical,#ff6b6b)' : ''">{{ realtimeSummary.warnings?.length ?? 0 }} 站</b></li>
          <li>最新观测：<b>{{ (realtimeSummary.latest_observed_at || '').slice(5, 16).replace('T', ' ') || '—' }}</b></li>
        </ul>
        <p class="hmlp-legend-note">完整逐站观测见「监测站点」页；时间回放见「综合驾驶舱」。</p>
      </template>
      <ul v-else class="hmlp-caps">
        <li>实时观测数据加载失败或不可用（不回退模拟）。</li>
      </ul>
    </section>

    <section class="hmlp-sec" aria-label="能力说明">
      <h3 class="hmlp-h">能力说明</h3>
      <ul class="hmlp-caps">
        <li>历史遥感层：<b>已接入（THQBCA-V2 年度反演）</b></li>
        <li>当前实况层：<b>站点观测点位已接入（observed）</b></li>
      </ul>
    </section>
  </div>
</template>

<script setup>
defineProps({
  realtimeVisible: { type: Boolean, default: true },
  diffEnabled: { type: Boolean, default: false },
  polygonEnabled: { type: Boolean, default: false },
  // 实时观测汇总（/realtime/summary）：驱动实况统计卡
  realtimeSummary: { type: Object, default: null },
  basemap: { type: String, default: 'satellite' },
  // 移动端抽屉形态：图例默认折叠
  compact: { type: Boolean, default: false }
})

defineEmits(['update:realtimeVisible', 'update:diffEnabled', 'update:polygonEnabled', 'update:basemap'])
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

@media (max-width: 759px) {
  .hmlp-toggles button,
  .hmlp-basemap button {
    min-height: 44px;
  }
  .hmlp-legend summary {
    min-height: 44px;
  }
}
.hmlp-extend { display: grid; gap: 6px; }
.hmlp-ext-toggle {
  appearance: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 34px;
  padding: 4px 12px;
  border-radius: 999px;
  cursor: pointer;
}
.hmlp-ext-toggle--on {
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 50%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
}
.hmlp-ext-hint { font-size: 9.5px; color: var(--text-muted); font-weight: 500; }
</style>
