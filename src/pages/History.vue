<template>
  <main class="shell">
    <section class="panel title-card">
      <div>
        <p class="eyebrow">COCKPIT · HISTORY</p>
        <h1>历史事件回放</h1>
      </div>
      <p class="title-note">按时间倒序回放入库事件，点击事件联动档位与详情</p>
    </section>

    <section class="kpi-grid">
      <article>
        <div class="kpi-label">累计事件</div>
        <div class="kpi-value">{{ events.length }}</div>
        <div class="kpi-trend flat">近 30 天回放窗口</div>
      </article>
      <article>
        <div class="kpi-label">高危事件</div>
        <div class="kpi-value" style="color: var(--coral);">{{ counts.high }}</div>
        <div class="kpi-trend up">需要即时联动</div>
      </article>
      <article>
        <div class="kpi-label">关注事件</div>
        <div class="kpi-value" style="color: var(--amber);">{{ counts.mid }}</div>
        <div class="kpi-trend flat">滚动复核</div>
      </article>
    </section>

    <div class="history-stage">
      <aside class="panel">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">EVENT TIMELINE</p>
            <h2>事件流</h2>
          </div>
          <span style="color: var(--muted); font-size: 12px; letter-spacing: 1px;">按时间倒序</span>
        </header>
        <div class="timeline-filter">
          <label>起 <input type="date" v-model="dateStart" /></label>
          <label>止 <input type="date" v-model="dateEnd" /></label>
          <button type="button" class="filter-btn" @click="loadTimeline">查询时间轴</button>
        </div>
        <div v-if="timelineSummary" class="timeline-summary">
          <span>{{ timelineSummary.start }} ~ {{ timelineSummary.end }} 共 {{ timelineSummary.days }} 天</span>
          <span>平均叶绿素 {{ timelineSummary.avgChl }}</span>
          <span>高风险 {{ timelineSummary.highDays }} 天</span>
        </div>
        <div class="history-list">
          <article
            v-for="ev in events"
            :key="ev.id"
            :class="{ active: ev.id === cockpit.currentEventId }"
            @click="selectEvent(ev)"
          >
            <div class="history-meta">
              <span>{{ ev.time }}</span>
              <span :class="['risk-badge', severityClass(ev.severity)]" style="padding: 3px 10px; font-size: 11px;">{{ severityLabel(ev.severity) }}</span>
            </div>
            <strong>{{ ev.title }}</strong>
            <p>{{ ev.summary }}</p>
            <div class="history-meta">
              <span>点位：{{ pointName(ev.point) }}</span>
              <span>{{ stageLabelOf(ev.stageKey) }}</span>
            </div>
          </article>
        </div>
      </aside>

      <section v-if="currentEvent" class="panel history-event-card">
        <header class="panel-head">
          <div>
            <p class="panel-kicker">EVENT DETAIL</p>
            <h2>{{ currentEvent.title }}</h2>
          </div>
          <span :class="['risk-badge', severityClass(currentEvent.severity)]">{{ severityLabel(currentEvent.severity) }}</span>
        </header>

        <div class="event-meta">
          <article>
            <span>事件时间</span>
            <strong>{{ currentEvent.time }}</strong>
          </article>
          <article>
            <span>对应档位</span>
            <strong>{{ stageLabelOf(currentEvent.stageKey) }}</strong>
          </article>
          <article>
            <span>监测点位</span>
            <strong>{{ pointName(currentEvent.point) }}</strong>
          </article>
        </div>

        <!-- 推送功能暂未接入真实渠道，先隐藏（后端接口待实现）
        <div class="event-actions">
          <button type="button" class="button action-btn" :disabled="handleLoading" @click="doHandle">{{ handleLoading ? '推送中…' : '立即推送（短信+邮件）' }}</button>
          <span v-if="handleResult" class="action-result">推送成功 @ {{ handleResult.pushed_at }}</span>
        </div>
        -->

        <div class="event-body">
          <h3>事件说明</h3>
          <p>{{ currentEvent.summary }}</p>
        </div>

        <section v-if="matchedPoint" class="chart-card">
          <div class="chart-title">
            <h3>点位时序曲线</h3>
          </div>
          <EChart :option="trendOption" />
        </section>

        <section>
          <div class="section-line">
            <h3>机制 + AI 因果链</h3>
            <span>机理融合溯源</span>
          </div>
          <div class="factor-list" v-if="matchedPoint">
            <div v-for="contrib in matchedPoint.explainability" :key="contrib.driver" class="factor-row">
              <div class="factor-fill" :style="{ width: Math.round(contrib.contribution * 100) + '%' }"></div>
              <span class="factor-tag">{{ contrib.driver }} · {{ contrib.direction }}向贡献</span>
              <strong class="factor-value">{{ Math.round(contrib.contribution * 100) }}%</strong>
            </div>
          </div>
        </section>

        <section>
          <div class="section-line">
            <h3>现场影像</h3>
            <span>事件关联图位</span>
          </div>
          <div class="image-slot" data-label="事件现场影像 · 待替换为 <img>"></div>
        </section>
      </section>

      <section v-else class="panel">
        <div class="event-empty">从左侧选择一条事件，回放档位、点位与因果链。</div>
        <div class="image-slot banner" style="margin-top: 16px;" data-label="历史回放封面 · 待替换为 <img>"></div>
      </section>
    </div>
    <footer class="cockpit-foot">
      <RouterLink class="button secondary" to="/">← 返回主页</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCockpitStore, cockpitState } from '../stores/cockpit.js'
import { getEvents, getPoints, getTimeStages, handleWarning, getTimeline } from '../services/api.js'
import { palette } from '../components/cockpit/echartsTheme.js'
import { useTheme } from '../composables/useTheme.js'
import EChart from '../components/cockpit/EChart.vue'

const cockpit = useCockpitStore()
const store = cockpitState()
const { theme } = useTheme()

const events = ref([])
const stages = ref([])
const pointsState = ref({ pointData: {} })
const handleLoading = ref(false)
const handleResult = ref(null)
const dateStart = ref('2026-07-21')
const dateEnd = ref('2026-07-28')
const timelineSummary = ref(null)

const currentEvent = computed(() => events.value.find((ev) => ev.id === cockpit.currentEventId) || null)
const matchedPoint = computed(() => currentEvent.value ? pointsState.value.pointData[currentEvent.value.point] : null)

const counts = computed(() => {
  const out = { high: 0, mid: 0, low: 0 }
  events.value.forEach((ev) => { out[ev.severity]++ })
  return out
})

function severityClass(sev) {
  return sev === 'high' ? 'high' : sev === 'mid' ? 'mid' : 'low'
}

function severityLabel(sev) {
  return sev === 'high' ? '高危' : sev === 'mid' ? '关注' : '一般'
}

function pointName(pid) {
  return pointsState.value.pointData[pid]?.name || pid
}

function stageLabelOf(key) {
  const item = stages.value.find((s) => s.key === key)
  return item ? item.label : key
}

function selectEvent(ev) {
  store.currentEventId = ev.id
  store.stageKey = ev.stageKey
  store.selectedPoint = ev.point
}

async function doHandle() {
  if (!currentEvent.value) return
  handleLoading.value = true
  handleResult.value = null
  try {
    const r = await handleWarning(currentEvent.value.id)
    handleResult.value = r
  } catch (e) {
    handleResult.value = { pushed_at: '失败', error: e && e.message }
  } finally {
    handleLoading.value = false
  }
}

async function loadTimeline() {
  if (!dateStart.value || !dateEnd.value) return
  try {
    const r = await getTimeline(dateStart.value, dateEnd.value)
    const highDays = r.data.filter(d => d.risk_level === 'high').length
    const avg = (r.data.reduce((s, d) => s + d.avg_chlorophyll, 0) / r.data.length).toFixed(1)
    timelineSummary.value = {
      start: r.start_date, end: r.end_date,
      days: r.total_days, highDays, avgChl: avg
    }
  } catch (e) {
    timelineSummary.value = null
  }
}

const trendOption = computed(() => {
  const p = palette()
  void theme.value
  if (!matchedPoint.value) return { series: [] }
  const trend = matchedPoint.value.trend || []
  const yMax = Math.max(100, ...trend) + 8
  return {
    grid: { left: 36, right: 16, top: 16, bottom: 28, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.lineStrong,
      textStyle: { color: p.text }
    },
    xAxis: {
      type: 'category',
      data: trend.map((_, i) => `T-${trend.length - i}d`),
      axisLine: { lineStyle: { color: p.lineStrong } },
      axisLabel: { color: p.muted, fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      max: yMax,
      axisLine: { show: false },
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line } }
    },
    series: [{
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 3, color: p.alert },
      itemStyle: { color: p.alert },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: p.alert + '66' },
            { offset: 1, color: p.alert + '00' }
          ]
        }
      },
      data: trend
    }]
  }
})

onMounted(async () => {
  const [e, p, s] = await Promise.all([
    getEvents(),
    getPoints(),
    getTimeStages()
  ])
  events.value = e
  pointsState.value = p
  stages.value = s
  loadTimeline()
})
</script>

<style scoped>
.title-card {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 22px;
}
.title-card h1 { margin: 0; font-size: 20px; }
.title-card .eyebrow { margin-bottom: 2px; }
.title-note {
  margin: 0;
  color: var(--c-muted);
  font-size: 12px;
  white-space: nowrap;
}

/* 历史页 3 张 KPI 卡等宽填满 */
.kpi-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 18px;
}

.action-btn {
  min-height: 36px;
  font-size: 13px;
  background: linear-gradient(135deg, #22314a, #121c2e);
  border-color: rgba(255, 255, 255, 0.08);
  color: #e8eef8;
}
.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
}
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }

@media (max-width: 640px) {
  .title-card { flex-direction: column; align-items: flex-start; gap: 6px; padding: 12px 16px; }
  .title-note { white-space: normal; font-size: 11px; }
  .history-stage { grid-template-columns: 1fr; }
}

/* 机制 + AI 因果链：热力图同款长条样式 */
.factor-list { display: grid; gap: 8px; }
.factor-row {
  position: relative;
  height: 24px;
  border-radius: 12px;
  background: var(--c-line);
  overflow: hidden;
}
.factor-fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  border-radius: 12px;
  background: linear-gradient(90deg, var(--c-watch), var(--c-alert));
}
.factor-tag {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}
.factor-value {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}
</style>