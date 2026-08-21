# 项目记忆 - 太湖双湖水质监测大屏 (i_need_sleep)

## 项目概况
- **赛事**: 服务外包大赛
- **技术栈**: Vue 3 + Vite 7 + ECharts 5 + Leaflet 1.9
- **用户职责**: 仅负责前端，不做后端/模型/数据接入
- **路由**: Hash 路由 (createWebHashHistory)，8个页面
- **数据**: mock 降级机制 (src/services/mock.js + adapters.js)

## 关键决策
- 地图从 CSS 百分比模拟改为 Leaflet 真实卫星地图 (Esri World Imagery)
- leaflet.heat 插件需要 `window.L = L` 后动态 import
- 站点坐标已有 `coord: { lon, lat }`，太湖区域约 119.18-119.41E, 31.22-31.39N

## 文件结构要点
- `src/main.js` - 路由定义 + sentinel history hack + scrollBehavior 支持 hash 锚点
- `src/App.vue` - 引入 GlobalNav 全局导航栏 + RouterView 转场动画
- `src/components/GlobalNav.vue` - 全局导航栏 (Logo + 8页面入口 + 时钟 + 主题切换)
  - "项目概览"使用 `{ path: '/', hash: '#project-overview' }` 锚点滚动到首页区块
- `src/pages/Home.vue` - 首页包含 hero + 路由卡片(2×2网格) + 项目概览区块(id=project-overview) + footer
- `src/components/cockpit/LakeMap.vue` - 卫星地图核心组件
- `src/data/points.js` - 站点/热力/事件数据
- `src/stores/cockpit.js` - 跨页状态 (stageKey, selectedPoint, playing, speed)
- `src/services/adapters.js` 第95行有乱码注释
- `src/services/mock.js` 有大量多余空行

## 已知问题
- 两套设计 token 并存 (--home-color-* 和 --teal/--coral)
- ~~无全局导航栏~~ → 已修复 (GlobalNav.vue)
- 6处 image-slot 占位符待处理
- 无 404 路由
- JS bundle 945KB (ECharts+Leaflet+Vue)，可做代码分割优化
- package.json 的 build 脚本应为 `vite build` 而非 `vite`
