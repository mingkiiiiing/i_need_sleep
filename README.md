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

### 3.3 数据源说明

前端只连接后端：所有页面统一请求 `/api/v1/*`，不存在 mock 数据源或数据源切换开关（历史 mock 配置与 mock 服务文件已于第九任务清理删除）。后端不可达时页面进入各自的错误态并提供重试，不会静默切换数据。

系统现有 MEE 实时观测、旧模拟演示与算法推演三条隔离链路。算法主链路为**交付包 V0.3 真实数据模型**（`/api/v1/model/v3/*`，20 个 bundle = 12 冻结划分 + 8 补训 CV 协议，含 conformal 区间、动态质量门与逐任务来源标注），覆盖 1/3/7/15/30/60/90 天和 9 个任务；legacy V0.2 合成包（63 模型，`synthetic_development_only`）保留作对照与回退。30/60/90 天为情景推演口径。统一指标口径见 [企业提交材料/算法组提交材料_V0.1/12_命题条款对照与统一指标口径_V0.1.md](./企业提交材料/算法组提交材料_V0.1/12_命题条款对照与统一指标口径_V0.1.md)，链路细节见 [INTEGRATION.md](./INTEGRATION.md)。
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
│  ├─ common/                     # 公共组件：AppSidebar / AppTopBar / DataContextBar / BackLink / MetricCard / DataModeBadge / QualityBadge / StatePanel
│  ├─ cockpit/                    # 驾驶舱组件：TimeAxisBar（时间轴播放器）/ LakeMap（点位地图 + 热力层）/ EChart 容器 / echartsTheme
│  ├─ heatmap/                    # 热力页组件：图层面板 / 风险格网地图 / 预警弹窗 / gridCore
│  ├─ history/                    # 历史页组件：事件列表 / 详情 / 筛选 / 回放 / 预案 + historyCore
│  └─ stations/                   # 站点页组件：分页签 / 分区面板 / stationDisplay
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
│  └─ api.js                     # 接口适配层（统一信封 + meta；前端只连接后端，无 mock）
└─ data/
   ├─ points.js                  # 前端静态演示数据（首页缩略态势回退 / 驾驶舱档位）
   ├─ taihuOutline.js            # 太湖真实轮廓（OSM relation 1126533）
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
