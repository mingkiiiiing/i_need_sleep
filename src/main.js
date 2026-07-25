import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
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

createApp(App).use(router).mount('#app')
