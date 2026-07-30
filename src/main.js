import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import '../tokens.css'
import './styles.css'

import Home from './pages/Home.vue'
import ProjectOverview from './pages/ProjectOverview.vue'
import TechRoute from './pages/TechRoute.vue'
import DemoFlow from './pages/DemoFlow.vue'
import Cockpit from './pages/Cockpit.vue'
import Stations from './pages/Stations.vue'
import Heatmap from './pages/Heatmap.vue'
import History from './pages/History.vue'

const routes = [
  { path: '/', component: Home },
  { path: '/project-overview', component: ProjectOverview },
  { path: '/tech-route', component: TechRoute },
  { path: '/demo-flow', component: DemoFlow },
  { path: '/cockpit', component: Cockpit },
  { path: '/stations', component: Stations },
  { path: '/heatmap', component: Heatmap },
  { path: '/history', component: History }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

// 退出边界保护：hash 路由 + 直接 deep link 时，浏览器后退会掉到 about:blank。
// 这里在 popstate 时如果当前没有 hash，主动压回 home，保持页面不空。
router.afterEach((to) => {
  // 防后退掉站：路由进入后多压一个 sentinel history 项
  if (window.__sentinelFor !== to.fullPath) {
    window.__sentinelFor = to.fullPath
    history.pushState({ sentinel: true, from: to.fullPath }, '', window.location.href)
  }
})

window.addEventListener('popstate', (e) => {
  if (e.state && e.state.sentinel) {
    const from = e.state.from || '/'
    history.pushState({ sentinel: true, from }, '', '#' + from)
  }
})

createApp(App).use(router).mount('#app')
