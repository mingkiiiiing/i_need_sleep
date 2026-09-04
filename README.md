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

项目分前后端两套进程，建议开两个终端窗口分别启动。

### 3.1 后端（FastAPI mock）

```bash
cd backend
# requirements.txt 已固定版本，建议使用 Python 3.12+
pip install -r requirements.txt

# 启动 mock 服务（默认端口 8000）
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

- 接口根：http://127.0.0.1:8000
- 接口文档：/docs（Swagger）、/redoc
- CORS 已配置白名单（localhost:5173 / 127.0.0.1:5173），配合 Vite 代理跨域调用

### 3.2 前端（Vue 3 + Vite）

```bash
# 1. 安装依赖
npm install

# 2. 启动开发服务（默认端口 5173）
npm run dev

# 3. 生产构建
npm run build
# 产物输出到 dist/ 目录

# 4. 本地预览构建产物
npm run preview
```

启动后控制台会输出 **Local** 与 **Network** 两个地址，局域网内其他设备可通过 Network 地址访问（如 http://192.168.x.x:5173/）。

vite.config.js 已配代理：/api/* → http://127.0.0.1:8000，前端代码统一使用 `/api/v1` 相对路径。默认必须先启动后端；后端异常会显示调用错误，不会自动切换为 mock。

### 3.3 切换数据源

是否走真实接口由环境变量 VITE_USE_MOCK 控制（见 src/services/api.js）：

```js
const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
```

- 未设置 / false（默认）：正常调 `/api/v1/*`，失败时显式报错
- true：完全不调后端，所有数据走前端 mock

强制全 mock 时，在项目根目录创建 `.env.local` 写入：

```
VITE_USE_MOCK=true
```

P0 数据均为 `SIMULATED` 演示数据；六个对象为 `demo_zone`，不是实时站点。1/3/7/15 天仅为样例接口，30 天仅为模拟预演，30—90 天正式预测不可用。详见 [INTEGRATION.md](./INTEGRATION.md)。
---

## 4. 目录速览

```
src/
├─ App.vue                       # 顶层容器，AppShell 基座 + 路由切换动效
├─ main.js                       # 入口，注册懒加载路由 / 文档标题 / 防后退哨兵
├─ styles.css                    # 全局设计系统（暗色玻璃 + 动效 + v2 基座补充）
├─ layouts/
│  └─ AppShell.vue               # 全站布局基座：侧栏 72 / 顶栏 64 / 数据身份栏 40 / 主内容
├─ components/
│  ├─ common/                     # 公共组件：AppSidebar / AppTopBar / DataContextBar / PageHeader / BackLink / MetricCard / DataModeBadge / QualityBadge / StatePanel
│  ├─ HeroShell.vue               # 通用页眉组件（带入场动效 + meta slot）
│  ├─ TimeAxisBar.vue             # 时间轴播放器（default 按钮列表 / axis 轴线两种形式）
│  ├─ CockpitSubTabs.vue          # 驾驶舱子页签切换
│  ├─ LakeMap.vue                 # 点位地图（Leaflet + 热力层）
│  ├─ EChart.vue                  # ECharts 容器
│  └─ echartsTheme.js             # ECharts 暗色主题常量
├─ pages/
│  ├─ Home.vue                   # 主页（左信息 / 右太湖演示分区缩略图 + 四核心入口 + 项目方案锚点）
│  ├─ Cockpit.vue                # 驾驶舱总览（03 / 03）
│  ├─ Stations.vue               # 监测站档位研判
│  ├─ Heatmap.vue                # 风险热力分区
│  ├─ History.vue                # 历史事件回放
│  └─ NotFound.vue               # 统一 404 页（站内来源确定性返回 / 回到首页 / 进入驾驶舱）
├─ stores/
│  ├─ cockpit.js                 # 跨页共享状态（时间档 / 选中点位）
│  └─ routeUi.js                 # 路由 UI 状态（懒加载进度 / 加载失败 / 业务来源）
├─ services/
│  ├─ api.js                     # 接口适配层
│  └─ mock.js                    # Mock 服务
└─ data/
   ├─ points.js                  # 本地数据源（6 点位 / 5 档预测 / 事件流 / 热力网格）
   └─ dataIdentity.js            # 数据身份唯一事实来源（SIMULATED / 版本 / 基准 / 边界）
```

根目录历史静态多页面前端（`project-overview.html`、`tech-route.html`、`demo-flow.html`、`cockpit.html`、`stations.html`、`heatmap.html`、`history.html`、`script.js`、`styles.css`）已于 2026-09-02 确认无引用后删除。正式前端仅保留 Vite + Vue 单页应用（根目录 `index.html` 为唯一入口）。

---

## 5. 路由速览

| 路由 | 页面 |
| --- | --- |
| `/` | 主页 |
| `/cockpit` | 驾驶舱总览 |
| `/stations` | 监测站档位研判 |
| `/heatmap` | 风险热力分区 |
| `/history` | 历史事件回放 |
| 其他任意地址 | 统一 404 页 |

正式产品只包含以上五个页面。原 `/project-overview`、`/tech-route` 独立路由已删除，项目概览内容保留在主页 `#project-overview` 锚点内。

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
