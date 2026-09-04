// 路由级 UI 状态：懒加载进度条 + 加载失败恢复。
// 在 main.js 中 bindRouterUi(router) 一次性注册，保证首次导航也能被捕获。

import { reactive } from 'vue'

export const routeUi = reactive({
  loading: false,
  errorPath: '',
  // 最近一次成功进入的业务页面（404 页“返回上一业务页面”的确定性目标）
  lastBusinessPath: ''
})

let lastTarget = '/'

export function bindRouterUi(router) {
  router.beforeEach((to) => {
    lastTarget = to.fullPath
    // 仅当目标组件还未解析（仍为函数）时才需要异步拉取 chunk
    const comp = to.matched[to.matched.length - 1]?.components?.default
    routeUi.loading = typeof comp === 'function'
  })
  router.afterEach((to) => {
    routeUi.loading = false
    routeUi.errorPath = ''
    if (to.name !== 'not-found') {
      routeUi.lastBusinessPath = to.fullPath
    }
  })
  router.onError(() => {
    routeUi.loading = false
    routeUi.errorPath = lastTarget
  })
}
