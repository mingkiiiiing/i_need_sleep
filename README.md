# A23 · 蓝藻水华监测预警 · 数字孪生驾驶舱

赛题 **A23 · 基于机理和 AI 融合的地表水蓝藻水华监测预警模型设计与实现** 的前端演示项目。主办：**我有一点困**。

面向新三湖（滇池 / 太湖 / 巢湖）与老三湖（太湖 / 巢湖 / 滆湖）等重点湖库，构建机理 × AI 融合的蓝藻水华监测预警模型，并配套一套用于演示与答辩的数字孪生驾驶舱前端。

---

## 1. 技术栈

- **Vue 3** + **Vue Router 4**（hash 模式，便于纯静态部署）
- **Vite 7**（开发与构建工具）
- **ECharts 5**（按需引入，仅 line / bar / heatmap 模块）
- **CSS 原生变量** 作为设计系统，无 Tailwind / 无 UI 框架

---

## 2. 环境要求

- **Node.js ≥ 18.0.0**（推荐 20.x LTS）
- **npm ≥ 9**（随 Node 一同安装）
- 现代浏览器（Chrome / Edge / Safari 最新版）

检查本地版本：

```bash
node -v
npm -v
```

如未安装 Node，前往 [https://nodejs.org/](https://nodejs.org/) 下载 LTS 版本即可。

---

## 3. 启动步骤

```bash
# 1. 安装依赖
npm install

# 2. 启动开发服务
npm run dev
# 默认地址 http://localhost:5173

# 3. 生产构建
npm run build
# 产物输出到 dist/ 目录

# 4. 本地预览构建产物
npm run preview
```

启动后控制台会输出 **Local** 与 **Network** 两个地址，局域网内其他设备可通过 Network 地址访问（如 `http://192.168.x.x:5173/`）。

---

## 4. 目录速览

```
src/
├─ App.vue                       # 顶层容器，包裹路由切换动效
├─ main.js                       # 入口，注册路由
├─ styles.css                    # 全局设计系统（暗色玻璃 + 动效）
├─ components/
│  ├─ HeroShell.vue              # 通用页眉组件（带入场动效 + meta slot）
│  └─ cockpit/                   # 驾驶舱三件套专用组件
│     ├─ TimeAxisBar.vue         # 顶部时间轴播放器
│     ├─ LakeMap.vue             # 点位地图
│     ├─ EChart.vue              # ECharts 容器
│     └─ echartsTheme.js         # ECharts 暗色主题常量
├─ pages/
│  ├─ Home.vue                   # 主页（Marquee Hero + 右侧入口边栏）
│  ├─ ProjectOverview.vue        # 项目概览（01 / 04）
│  ├─ TechRoute.vue              # 技术路线（02 / 04）
│  ├─ DemoFlow.vue               # 演示流程（03 / 04）
│  ├─ Cockpit.vue                # 驾驶舱总览（04 / 04）
│  ├─ Stations.vue               # 监测站档位研判
│  ├─ Heatmap.vue                # 风险热力分区
│  └─ History.vue                # 历史事件回放
├─ stores/
│  └─ cockpit.js                 # 跨页共享状态
├─ services/
│  ├─ api.js                     # 接口适配层
│  └─ mock.js                    # Mock 服务
└─ data/
   └─ points.js                  # 本地数据源（6 点位 / 5 档预测 / 事件流 / 热力网格）
```

---

## 5. 路由速览

| 路由 | 页面 |
| --- | --- |
| `/` | 主页 |
| `/project-overview` | 项目概览 |
| `/tech-route` | 技术路线 |
| `/demo-flow` | 演示流程 |
| `/cockpit` | 驾驶舱总览 |
| `/stations` | 监测站档位研判 |
| `/heatmap` | 风险热力分区 |
| `/history` | 历史事件回放 |

---

## 6. 常用脚本

| 命令 | 作用 |
| --- | --- |
| `npm run dev` | 启动开发服务（默认监听 5173） |
| `npm run build` | 生产构建到 `dist/` |
| `npm run preview` | 本地预览构建产物 |

---

## 7. License
本项目是朋友们练手的