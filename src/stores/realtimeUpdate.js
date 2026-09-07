// 跨页共享：综合驾驶舱实时数据的更新时间与新鲜度状态。
// 综合驾驶舱加载 /api/v1/realtime/summary 成功后写入，
// 全局顶栏（AppTopBar）在太阳按钮旁读取展示；离开驾驶舱或加载失败时清空。
import { reactive } from 'vue'

export const realtimeUpdate = reactive({
  latestObservedAt: '', // ISO 字符串，如 '2026-09-07T14:00:00+08:00'
  freshnessStatus: ''   // 'normal' | 'stale' | 'historical' | ''
})

export function setRealtimeUpdate(summary) {
  if (summary && summary.latest_observed_at) {
    realtimeUpdate.latestObservedAt = summary.latest_observed_at
    realtimeUpdate.freshnessStatus = summary.freshness_status || ''
  } else {
    clearRealtimeUpdate()
  }
}

export function clearRealtimeUpdate() {
  realtimeUpdate.latestObservedAt = ''
  realtimeUpdate.freshnessStatus = ''
}
