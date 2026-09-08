<template>
  <main class="page-history">
    <div class="his-body">
      <!-- ===== 标题区：三视图切换 ===== -->
      <header class="his-title" aria-label="历史复盘">
        <div class="his-title-left">
          <BackLink :to="cockpitLink" label="返回驾驶舱" />
          <div class="his-title-text">
            <h1>历史复盘</h1>
            <nav class="his-views" role="tablist" aria-label="复盘视图">
              <button
                v-for="v in VIEWS"
                :key="v.key"
                type="button"
                role="tab"
                class="his-view-tab"
                :class="{ 'his-view-tab--on': view === v.key }"
                :aria-selected="String(view === v.key)"
                :data-role="`view-tab-${v.key}`"
                @click="switchView(v.key)"
              >{{ v.label }}</button>
            </nav>
          </div>
        </div>
        <div class="his-title-right">
          <button
            type="button"
            class="his-export"
            data-role="export-report"
            :disabled="!canExport"
            :title="canExport ? '导出当前事件的复盘报告（Markdown）' : '在事件复盘中选择事件后可导出'"
            @click="exportReport"
          >导出复盘报告</button>
        </div>
      </header>

      <!-- ===== 三个主视图 ===== -->
      <EventReviewView
        v-if="view === 'review'"
        ref="reviewViewRef"
        @ready="(ok) => (canExport = ok)"
      />
      <ObservationReplayView v-else-if="view === 'replay'" />
      <PredictionEvalView v-else />
    </div>
  </main>
</template>

<script setup>
// 历史复盘页：事件复盘（默认，事件为主键的证据链）｜观测回放（快照地图回放）｜预测评估（能力状态）。
// 视图与关键参数写入 URL：view=review&event=<event_id>；view=replay&start&end&snapshot&station。
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BackLink from '../components/common/BackLink.vue'
import EventReviewView from '../components/history/EventReviewView.vue'
import ObservationReplayView from '../components/history/ObservationReplayView.vue'
import PredictionEvalView from '../components/history/PredictionEvalView.vue'

const VIEWS = [
  { key: 'review', label: '事件复盘' },
  { key: 'replay', label: '观测回放' },
  { key: 'evaluation', label: '预测评估' }
]

const route = useRoute()
const router = useRouter()

const cockpitLink = '/cockpit'

const VALID_VIEWS = new Set(VIEWS.map((v) => v.key))
const view = computed(() =>
  VALID_VIEWS.has(route.query.view) ? route.query.view : 'review'
)

function switchView(key) {
  if (key === view.value) return
  const query = { view: key }
  // 切换视图时保留各自的上下文参数由子视图维护；此处仅写入 view
  router.replace({ query }).catch(() => {})
}

// ---------- 导出复盘报告（事件复盘视图提供数据） ----------
const reviewViewRef = ref(null)
const canExport = ref(false)

function exportReport() {
  reviewViewRef.value?.exportReport?.()
}

watch(view, () => {
  canExport.value = false
})
</script>

<style scoped>
.page-history {
  max-width: 1760px;
  margin: 0 auto;
  padding: 8px 20px 12px;
  min-height: 100vh;
}
.his-body {
  display: grid;
  gap: 6px;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  min-width: 0;
}

/* ---------- 标题区 ---------- */
.his-title {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px 16px;
  padding: 10px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}
.his-title-left {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
}
.his-title-text h1 {
  margin: 1px 0 4px;
  font-family: var(--font-display);
  font-size: clamp(18px, 1.8vw, 24px);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}
.his-views {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.his-view-tab {
  appearance: none;
  min-height: 32px;
  padding: 3px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.his-view-tab:hover {
  color: var(--text-primary);
}
.his-view-tab--on {
  border-color: color-mix(in srgb, var(--color-primary) 60%, transparent);
  background: color-mix(in srgb, var(--color-primary) 13%, transparent);
  color: var(--text-primary);
}
.his-view-tab:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.his-title-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  min-width: 0;
}
.his-export {
  appearance: none;
  min-height: 32px;
  padding: 3px 16px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 55%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--color-primary) 12%, transparent);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.his-export:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.his-export:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

/* ---------- 响应式 ---------- */
@media (max-width: 960px) {
  .page-history {
    padding: 8px 12px 16px;
  }
  .his-title-right {
    align-items: flex-start;
  }
}
</style>

<style>
/* P06 页面级全局补充：reduced-motion 下关闭入场与装饰动画（不动 styles.css） */
@media (prefers-reduced-motion: reduce) {
  .route-stage > .page-history {
    animation: none !important;
  }
  .page-history *,
  .page-history *::before,
  .page-history *::after {
    transition: none !important;
  }
}
</style>
