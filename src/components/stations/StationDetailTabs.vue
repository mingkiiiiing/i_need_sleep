<template>
  <section class="stn-block sdt" aria-label="站点数据明细与情景推演">
    <!-- 默认折叠：明细大表不长期占据页面宽度 -->
    <button
      type="button"
      class="sdt-toggle"
      :aria-expanded="String(open)"
      data-role="detail-toggle"
      @click="open = !open"
    >
      <span>{{ open ? '收起明细' : '查看全部指标明细' }}</span>
      <small>QC · 快照 · 情景推演</small>
      <i class="sdt-caret" :class="{ 'sdt-caret--open': open }" aria-hidden="true"></i>
    </button>

    <div v-if="open" class="sdt-content">
      <div class="sdt-tabs" role="tablist" aria-label="底部数据视图切换">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          type="button"
          role="tab"
          class="stn-tab"
          :class="{ active: activeTab === tab.key }"
          :aria-selected="String(activeTab === tab.key)"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}<small v-if="tab.tag"> {{ tab.tag }}</small>
        </button>
      </div>

    <!-- 指标明细：11 项状态一行不缺，可溯源 -->
    <div v-if="activeTab === 'detail'" class="stn-table-wrap" role="tabpanel" aria-label="指标明细">
      <table class="stn-table">
        <thead>
          <tr>
            <th>指标</th><th>数值</th><th>单位</th><th>状态</th><th>QC</th><th>观测时间</th><th>快照</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.variable_code">
            <td>{{ variableLabel(row.variable_code) }}</td>
            <td class="stn-mono">{{ row.observation_status === 'ok' || row.observation_status === 'qc_rejected' ? fmtMeasure(row.value) : '—' }}</td>
            <td>{{ row.unit || '—' }}</td>
            <td>
              <span class="sdt-status" :class="`sdt-status--${row.observation_status}`">
                {{ OBS_STATUS_TEXT[row.observation_status] || row.observation_status }}
              </span>
            </td>
            <td>{{ row.qc_status }}</td>
            <td class="stn-mono">{{ formatStamp(row.observed_at) }}</td>
            <td class="stn-mono sdt-snap">{{ row.snapshot_id.replace('mee_surface_water_realtime_', '') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 情景推演：独立标签页，惰性加载情景分区内容，绝不与实时站点合并 -->
    <div v-else class="sdt-sim" role="tabpanel" aria-label="情景推演（情景数据）">
      <p class="sdt-sim-banner">
        以下为情景推演分区内容，与上方真实站点无关；系统不会为真实站点自动生成情景推演分数。
      </p>
      <div v-if="simState === 'idle'" class="stn-list-empty">
        <p class="sle-title">情景推演未加载</p>
        <p class="sle-desc">按需加载情景分区预测（demo_zone · simulated 轨）。</p>
        <button type="button" class="stn-inline-btn" @click="loadSim">加载情景推演</button>
      </div>
      <div v-else-if="simState === 'loading'" class="stn-list-skeleton" aria-hidden="true">
        <div class="skel-row" v-for="i in 3" :key="i"></div>
      </div>
      <div v-else-if="simState === 'error'" class="stn-list-empty" role="alert">
        <p class="sle-title">情景推演加载失败</p>
        <button type="button" class="stn-inline-btn" @click="loadSim">重试</button>
      </div>
      <ul v-else class="sdt-sim-grid">
        <li v-for="item in simRows" :key="item.id" class="sdt-sim-card">
          <span class="sdt-sim-name">{{ item.short }} · {{ item.name }}</span>
          <span class="sdt-sim-score">{{ item.score ?? '—' }}</span>
          <span class="sdt-sim-tag">T+{{ horizon }}d 情景分数 · simulated</span>
        </li>
      </ul>
    </div>
    </div>
  </section>
</template>

<script setup>
// 底部折叠抽屉：指标明细（observed，全量 11 项状态）与情景推演（simulated 轨，惰性加载）。
// 默认收起，展开后才出现双标签；情景推演内容独立分区展示，不在真实站点视图自动触发预测请求。
import { computed, ref, watch } from 'vue'
import { getForecastsEnvelope, getSpatialEntities } from '../../services/api.js'
import { OBS_STATUS_TEXT, fmtMeasure, formatStamp, variableLabel } from '../../services/realtime.js'

const props = defineProps({
  rows: { type: Array, default: () => [] }
})

const TABS = [
  { key: 'detail', label: '指标明细' },
  { key: 'sim', label: '情景推演', tag: '情景数据' }
]

const open = ref(false)
const activeTab = ref('detail')
const simState = ref('idle')
const simRows = ref([])
const horizon = 3

async function loadSim() {
  simState.value = 'loading'
  try {
    const { data: entities } = await getSpatialEntities()
    const results = await Promise.all(
      entities.map((entity) => getForecastsEnvelope(entity.id, horizon).catch(() => ({ data: [] })))
    )
    simRows.value = entities.map((entity, i) => {
      const forecast = Array.isArray(results[i].data) ? results[i].data[0] : null
      return {
        id: entity.id,
        short: entity.short,
        name: entity.display_name,
        score: forecast ? forecast.risk_score : null
      }
    })
    simState.value = 'ok'
  } catch {
    simState.value = 'error'
  }
}

// 已加载过则直接展示缓存结果，不重复请求
watch(activeTab, (key) => {
  if (key === 'sim' && simState.value === 'idle') loadSim()
})
</script>

<style scoped>
.sdt-toggle {
  appearance: none;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 40px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 650;
  cursor: pointer;
  text-align: left;
}
.sdt-toggle small {
  font-size: 10px;
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text-muted);
}
.sdt-toggle:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 8px;
}
.sdt-caret {
  margin-left: auto;
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--text-muted);
  border-bottom: 2px solid var(--text-muted);
  transform: rotate(45deg);
  transition: transform 0.15s ease;
}
.sdt-caret--open {
  transform: rotate(225deg);
}
.sdt-content {
  margin-top: 8px;
}
.sdt-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  margin-bottom: 8px;
}
.stn-tab {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  min-height: 34px;
  padding: 4px 14px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.stn-tab small { font-size: 9.5px; color: var(--text-muted); }
.stn-tab.active {
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  color: var(--text-primary);
  border-color: color-mix(in srgb, var(--color-primary) 42%, transparent);
}
.sdt-status { font-size: 10.5px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border-subtle); white-space: nowrap; }
.sdt-status--ok { color: var(--risk-low, #5fd6a4); }
.sdt-status--missing, .sdt-status--parse_failed { color: var(--text-muted); }
.sdt-status--qc_rejected { color: var(--risk-critical, #ef4444); }
.sdt-snap { color: var(--text-muted); }
.sdt-sim-banner {
  margin: 0 0 8px;
  font-size: 11.5px;
  color: var(--risk-medium, #f5b45d);
  border: 1px dashed color-mix(in srgb, var(--risk-medium, #f5b45d) 50%, transparent);
  border-radius: 10px;
  padding: 6px 10px;
  line-height: 1.6;
}
.sdt-sim-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 6px;
}
.sdt-sim-card {
  display: grid;
  gap: 2px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-soft);
  padding: 8px 10px;
}
.sdt-sim-name { font-size: 12px; color: var(--text-primary); font-weight: 600; }
.sdt-sim-score { font-family: var(--font-mono); font-size: 16px; color: var(--text-secondary); }
.sdt-sim-tag { font-size: 9.5px; color: var(--text-muted); }
</style>
