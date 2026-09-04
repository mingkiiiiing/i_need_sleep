// 跨页共享状态：当前时间档 + 选中点位 + 是否播放 + 倍速。
// 状态通过 hash query (?t=t7&p=northwest_hotspot) 双向同步到 URL，
// 浏览器前进后退与刷新都能还原现场。

import { reactive, watch, readonly, effectScope } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { timeStages } from '../data/points.js'

const initialStage = (() => {
  const valid = timeStages.map((s) => s.key)
  return valid.includes('t7') ? 't7' : valid[0]
})()

const initialPoint = 'northwest_hotspot'

const state = reactive({
  stageKey: initialStage,
  selectedPoint: initialPoint,
  playing: false,
  speed: 1,         // 播放倍速：1 / 2 / 4
  currentEventId: null
})

let routerRef = null
let routeRef = null
let syncScope = null

function readQuery() {
  if (!routeRef) return
  const q = routeRef.query || {}
  if (typeof q.t === 'string' && timeStages.some((s) => s.key === q.t)) {
    state.stageKey = q.t
  }
  if (typeof q.p === 'string') {
    state.selectedPoint = q.p
  }
  if (typeof q.e === 'string') {
    state.currentEventId = q.e
  }
}

function syncQuery() {
  if (!routerRef || !routeRef) return
  const next = {
    t: state.stageKey,
    p: state.selectedPoint,
    e: state.currentEventId || undefined
  }
  routerRef.replace({ query: { ...routeRef.query, ...next } })
}

let suppressWatch = false

export function bindCockpitStore(router, route) {
  routerRef = router
  routeRef = route

  if (!syncScope) {
    // detached effectScope：双向监听不挂在首个页面组件的作用域上，
    // 否则组件卸载（如驾驶舱 → 站点页）时监听被销毁，返回后 URL 不再同步。
    syncScope = effectScope(true)
    syncScope.run(() => {
      watch(
        () => ({ t: state.stageKey, p: state.selectedPoint, e: state.currentEventId }),
        () => {
          if (suppressWatch) return
          syncQuery()
        }
      )
      watch(
        () => (routeRef ? routeRef.query : null),
        () => {
          if (!routeRef) return
          const q = routeRef.query
          if (typeof q.t === 'string' && q.t !== state.stageKey && timeStages.some((s) => s.key === q.t)) {
            suppressWatch = true
            state.stageKey = q.t
            suppressWatch = false
          }
          if (typeof q.p === 'string' && q.p !== state.selectedPoint) {
            suppressWatch = true
            state.selectedPoint = q.p
            suppressWatch = false
          }
          if (typeof q.e === 'string' && q.e !== state.currentEventId) {
            suppressWatch = true
            state.currentEventId = q.e
            suppressWatch = false
          }
        }
      )
    })
  }
  // 每次组件绑定都按当前 URL 校准一次状态（直达 /stations?p=… 等场景）
  readQuery()
}

// 给组件直接用的初始化函数：必须在 setup() 内调用，拿到 router 与 route
export function useCockpitStore() {
  const router = useRouter()
  const route = useRoute()
  bindCockpitStore(router, route)
  return readonly(state)
}

// 给不需要 URL 同步的内部子组件使用（写权限）
export function cockpitState() {
  return state
}