import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import '../tokens.css'
import './styles.css'
import { initTheme } from './composables/useTheme.js'
import { bindRouterUi } from './stores/routeUi.js'

initTheme()

// 五个正式页面全部懒加载：ECharts/Leaflet 只随对应业务页 chunk 下载
const Home = () => import('./pages/Home.vue')
const Cockpit = () => import('./pages/Cockpit.vue')
const Stations = () => import('./pages/Stations.vue')
const Heatmap = () => import('./pages/Heatmap.vue')
const History = () => import('./pages/History.vue')
const Wallboard = () => import('./pages/Wallboard.vue')
const NotFound = () => import('./pages/NotFound.vue')

const routes = [
  { path: '/', name: 'home', component: Home, meta: { title: '首页' } },
  { path: '/cockpit', name: 'cockpit', component: Cockpit, meta: { title: '综合驾驶舱' } },
  { path: '/stations', name: 'stations', component: Stations, meta: { title: '监测站点研判' } },
  { path: '/heatmap', name: 'heatmap', component: Heatmap, meta: { title: '风险地图与时空推演' } },
  { path: '/history', name: 'history', component: History, meta: { title: '历史事件与复盘' } },
  { path: '/wallboard', name: 'wallboard', component: Wallboard, meta: { title: '综合展示大屏', fullscreen: true } },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFound, meta: { title: '页面未找到' } }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) {
      // 顶栏 64 + 数据身份栏 40 + 分隔线 2，再留 8px 呼吸
      return { el: to.hash, top: 114 }
    }
    return { top: 0 }
  }
})

bindRouterUi(router)

router.afterEach((to) => {
  const base = '蓝藻水华监测预警'
  document.title = to.meta && to.meta.title ? `${to.meta.title} · ${base}` : base
})

createApp(App).use(router).mount('#app')
