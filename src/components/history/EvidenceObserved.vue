<template>
  <div class="eob" data-role="evidence-observed">
    <template v-if="!evidence || evidence.available === false">
      <StatePanel
        state="empty"
        title="暂无可用的观测证据"
        :description="evidence?.reason || '该事件暂无可关联的观测证据。'"
      />
    </template>
    <template v-else>
      <div class="eob-toolbar">
        <div class="eob-indicators" role="group" aria-label="指标切换">
          <button
            v-for="ind in evidence.indicators"
            :key="ind.code"
            type="button"
            class="eob-ind"
            :class="{ 'eob-ind--on': ind.code === indicator }"
            @click="indicator = ind.code"
          >{{ ind.label }}</button>
        </div>
        <button type="button" class="eob-jump" data-role="jump-replay" @click="jumpReplay">
          跳转观测回放（{{ evidence.station_name }}）→
        </button>
      </div>

      <p class="eob-window">
        证据窗口：{{ formatBeijing(evidence.window?.start) }} ~ {{ formatBeijing(evidence.window?.end) }}（北京时间）
        · {{ evidence.window?.basis }}
        · 共 {{ evidence.coverage?.total_points ?? series.length }} 个快照，
        叶绿素a 缺测 {{ evidence.coverage?.missing_chla_points ?? 0 }} 个（缺测断开不插值）
      </p>

      <EChart :option="chartOption" :height="300" data-role="evidence-chart" />

      <div class="eob-tables">
        <section aria-label="证据节点">
          <h4>证据节点</h4>
          <table class="eob-table">
            <thead>
              <tr><th>时间（北京时间）</th><th>节点</th><th>观测值</th><th>数据快照</th></tr>
            </thead>
            <tbody>
              <tr v-for="(node, index) in evidence.nodes" :key="index" :data-role="`evidence-node-${node.type}`">
                <td class="eob-mono">{{ formatBeijing(node.at) }}</td>
                <td>{{ node.label }}</td>
                <td class="eob-mono">{{ node.value != null ? node.value : '—' }}</td>
                <td class="eob-mono">{{ node.snapshot_id || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section aria-label="缺测说明">
          <h4>缺测与口径</h4>
          <ul class="eob-notes">
            <li>阈值线为筛查口径：叶绿素a ≥{{ evidence.thresholds?.light }} 轻度 / ≥{{ evidence.thresholds?.moderate }} 中度（μg/L）。</li>
            <li>{{ evidence.coverage?.note }}</li>
            <li>抓取时间与观测时间可能不同：曲线横轴为观测时间（北京时间）。</li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
// 事件复盘 · 观测证据：围绕选中事件的前/中/后指标曲线 + 证据节点表。
// 数据来自 /history/reviews/{id} 聚合结果的 observed_evidence（后端只读组合，不复制）。
import { computed, ref } from 'vue'
import EChart from '../cockpit/EChart.vue'
import StatePanel from '../common/StatePanel.vue'
import { palette } from '../cockpit/echartsTheme.js'
import { formatBeijing } from '../../services/historyReview.js'

const props = defineProps({
  evidence: { type: Object, default: null },
  detail: { type: Object, default: null }
})

const emit = defineEmits(['jump-replay'])

const indicator = ref('chlorophyll_a')

const series = computed(() => props.evidence?.series || [])
const activeIndicator = computed(
  () => (props.evidence?.indicators || []).find((i) => i.code === indicator.value) || { label: indicator.value, unit: '' }
)

const chartOption = computed(() => {
  const p = palette()
  const rows = series.value
  const xData = rows.map((row) => formatBeijing(row.observed_at))
  const values = rows.map((row) => row.values?.[indicator.value] ?? null)
  const nodes = (props.evidence?.nodes || []).filter((node) => node.at)
  const isChla = indicator.value === 'chlorophyll_a'
  const thresholds = props.evidence?.thresholds || {}

  const markLines = nodes
    .filter((node) => node.type !== 'trigger')
    .map((node) => ({
      xAxis: formatBeijing(node.at),
      lineStyle: { color: node.type === 'unverified' ? '#8296ab' : node.type === 'recovered' ? '#5fd6a4' : '#f5b45d', type: 'dashed', width: 1 },
      label: { formatter: node.label, fontSize: 9, color: p.textSoft },
      symbol: 'none'
    }))

  const triggerNode = nodes.find((node) => node.type === 'trigger' && node.value != null)

  return {
    grid: { left: 48, right: 16, top: 28, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text, fontSize: 11 },
      valueFormatter: (v) => (v == null ? '缺测' : `${v} ${activeIndicator.value.unit || ''}`)
    },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { color: p.muted, fontSize: 9.5, interval: Math.max(0, Math.floor(xData.length / 8)) },
      axisLine: { lineStyle: { color: p.lineStrong } }
    },
    yAxis: {
      type: 'value',
      name: activeIndicator.value.unit,
      nameTextStyle: { color: p.muted, fontSize: 10 },
      axisLabel: { color: p.muted, fontSize: 10 },
      splitLine: { lineStyle: { color: p.line } }
    },
    series: [
      {
        name: activeIndicator.value.label,
        type: 'line',
        data: values,
        connectNulls: false,
        showSymbol: rows.length <= 40,
        symbolSize: 5,
        lineStyle: { color: p.accent, width: 2 },
        itemStyle: { color: p.accent },
        markLine: {
          symbol: 'none',
          silent: true,
          data: [
            ...(isChla
              ? [
                  { yAxis: thresholds.light, lineStyle: { color: '#f5b45d', type: 'dashed', width: 1 }, label: { formatter: `轻度 ${thresholds.light}`, fontSize: 9, color: '#f5b45d', position: 'insideEndTop' } },
                  { yAxis: thresholds.moderate, lineStyle: { color: '#ef4444', type: 'dashed', width: 1 }, label: { formatter: `中度 ${thresholds.moderate}`, fontSize: 9, color: '#ef4444', position: 'insideEndTop' } }
                ]
              : []),
            ...markLines
          ]
        },
        markPoint: triggerNode
          ? {
              symbol: 'circle',
              symbolSize: 9,
              itemStyle: { color: '#f5b45d', borderColor: p.surface, borderWidth: 2 },
              label: { show: false },
              data: [{ coord: [formatBeijing(triggerNode.at), triggerNode.value], name: '首次触发' }]
            }
          : undefined
      }
    ]
  }
})

function jumpReplay() {
  const trigger = (props.evidence?.nodes || []).find((node) => node.type === 'trigger')
  emit('jump-replay', {
    station: props.evidence?.station_id || '',
    snapshot: trigger?.snapshot_id || '',
    start: (props.evidence?.window?.start || '').slice(0, 10),
    end: (props.evidence?.window?.end || '').slice(0, 10)
  })
}
</script>

<style scoped>
.eob {
  display: grid;
  gap: 10px;
}
.eob-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.eob-indicators {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.eob-ind {
  appearance: none;
  min-height: 28px;
  padding: 2px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
}
.eob-ind--on {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
  color: var(--text-primary);
}
.eob-ind:focus-visible,
.eob-jump:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.eob-jump {
  appearance: none;
  min-height: 30px;
  padding: 2px 12px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font-size: 11.5px;
  cursor: pointer;
}
.eob-window {
  margin: 0;
  font-size: 10.5px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  line-height: 1.6;
}
.eob-tables {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: 14px;
}
.eob-tables h4 {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.eob-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.eob-table th,
.eob-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--border-subtle);
  text-align: left;
  color: var(--text-secondary);
  white-space: nowrap;
}
.eob-table th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 10px;
}
.eob-mono {
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.eob-notes {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 5px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.6;
}
@media (max-width: 1100px) {
  .eob-tables {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
