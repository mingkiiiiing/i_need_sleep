<template>
  <main class="home-workbench" :class="{ 'is-ready': ready }">
    <section class="home-hero-v2" aria-labelledby="home-title">
      <article class="home-copy home-reveal" style="--reveal-index: 0">
        <p class="home-kicker">机理与 AI 融合的地表水监测系统</p>
        <h1 id="home-title" class="home-title-v2">
          <span>蓝藻水华</span>
          <span class="home-title-accent">监测预警</span>
        </h1>
        <p class="home-lede">
          把藻类生长、水流输运等物理机理嵌入智能模型，结合多源监测数据完成早识别、早预报与早预警，形成可解释、可校正的数字孪生决策链路。
        </p>

        <div class="home-actions" aria-label="首页主要操作">
          <RouterLink class="home-action home-action-primary" to="/cockpit">
            进入数字孪生驾驶舱
            <span aria-hidden="true">↗</span>
          </RouterLink>
          <RouterLink class="home-action home-action-secondary" to="/project-overview">
            查看项目概览
          </RouterLink>
        </div>

        <dl class="home-facts" aria-label="系统关键数据">
          <div v-for="fact in facts" :key="fact.label">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
            <span>{{ fact.note }}</span>
          </div>
        </dl>
      </article>

      <figure class="lake-workbench home-reveal" style="--reveal-index: 1">
        <figcaption class="lake-workbench-head">
          <div>
            <span>LIVE TWIN / 湖体遥测</span>
            <strong>太湖监测网络</strong>
          </div>
          <span class="lake-workbench-stage">T+1 当前档位</span>
        </figcaption>

        <div class="lake-canvas" aria-label="六个湖区监测点位实时状态示意图">
          <div class="lake-grid" aria-hidden="true"></div>
          <div class="lake-shape" aria-hidden="true">
            <span class="lake-shape-core"></span>
          </div>
          <div class="lake-scan" aria-hidden="true"></div>

          <div
            v-for="point in monitorPoints"
            :key="point.code"
            class="lake-point"
            :class="`is-${point.level}`"
            :style="{ left: point.left, top: point.top }"
          >
            <span class="lake-point-dot" aria-hidden="true"></span>
            <span class="lake-point-label">
              <strong>{{ point.code }}</strong>
              <small>{{ point.name }}</small>
            </span>
          </div>

          <div class="lake-insight">
            <span>当前研判</span>
            <strong>西北湖区风险抬升</strong>
            <small>机理层与 AI 层联合输出</small>
          </div>
        </div>

        <div class="lake-workbench-foot">
          <span><i class="is-high"></i>红色预警 1</span>
          <span><i class="is-mid"></i>橙色关注 3</span>
          <span><i class="is-low"></i>绿色稳定 2</span>
        </div>
      </figure>
    </section>

    <section class="home-index home-reveal" style="--reveal-index: 2" aria-labelledby="home-index-title">
      <header class="home-index-head">
        <div>
          <p>系统入口</p>
          <h2 id="home-index-title">按任务进入，而不是按页面浏览</h2>
        </div>
        <p>从项目背景到实时研判，四个模块共同组成完整演示路径。</p>
      </header>

      <div class="home-route-grid">
        <RouterLink v-for="entry in entries" :key="entry.index" class="home-route-card" :to="entry.to">
          <span class="home-route-num">{{ entry.index }}</span>
          <span class="home-route-copy">
            <small>{{ entry.voice }}</small>
            <strong>{{ entry.title }}</strong>
            <span>{{ entry.summary }}</span>
          </span>
          <span class="home-route-meta">{{ entry.meta }}</span>
          <span class="home-route-arrow" aria-hidden="true">→</span>
        </RouterLink>
      </div>
    </section>

    <section id="project-overview" class="home-overview home-reveal" style="--reveal-index: 3" aria-labelledby="overview-title">
      <header class="home-overview-head">
        <div>
          <p class="home-overview-kicker">PROJECT OVERVIEW · 01</p>
          <h2 id="overview-title">项目概览</h2>
        </div>
        <p class="home-overview-lede">
          面向新三湖（滇池、太湖、巢湖）与老三湖（太湖、巢湖、滆湖）等重点湖库，建立机理与 AI 融合的蓝藻水华监测预警模型，输出从早识别、早预报到早预警的全链条能力。
        </p>
      </header>

      <div class="overview-meta-row">
        <div class="overview-meta-card"><span>主题</span><strong>数据与计算</strong></div>
        <div class="overview-meta-card"><span>赛题</span><strong>A23 · 应用类</strong></div>
        <div class="overview-meta-card"><span>主办</span><strong>我有一点困</strong></div>
        <div class="overview-meta-card"><span>核心</span><strong>机理 × AI 融合</strong></div>
      </div>

      <article class="overview-context">
        <p class="overview-kicker">整体背景 · CONTEXT</p>
        <h3 class="overview-h3">蓝藻水华是富营养化水体在特定水文气候条件下分发性增殖的生态灾变现象</h3>
        <p class="overview-prose">
          蓝藻水华严重威胁饮用水安全、水生态系统健康及流域经济社会的可持续发展。随着《水污染防治行动计划》深入推进及《"十四五"生态环境监测规划》明确要求在新老三湖等重点湖库开展蓝藻水华监测预警，传统"人工采样 + 实验室分析"的监测模式已难以满足"提前预警、精准防控"的管理需要。
        </p>
      </article>

      <div class="overview-split">
        <article class="overview-block">
          <p class="overview-kicker">传统路径 · CLASSICAL</p>
          <h4>水动力 - 水质 - 藻类生长耦合模型</h4>
          <p>可刻画营养盐循环、藻类生理生态过程及物理迁移规律，具备可解释性强、外推能力好的优势，但参数率定困难、计算效率低，对突发扰动响应滞后。</p>
        </article>
        <article class="overview-block">
          <p class="overview-kicker">数据驱动 · DATA-DRIVEN</p>
          <h4>深度学习 / 物理信息神经网络</h4>
          <p>能从多源异构监测数据中挖掘环境因子与藻华分发的非线性映射关系，实现短期预警与风险分级，但物理一致性约束弱、泛化性能不足。</p>
        </article>
      </div>

      <article class="overview-solution">
        <p class="overview-kicker">融合范式 · OUR ANSWER</p>
        <h3 class="overview-h3">把藻类生长动力学方程、流体水力学守恒定律等物理机理嵌入神经网络架构</h3>
        <p class="overview-prose">
          或利用 AI 对机理模型参数进行实时校正，构建兼具物理可解释性与数据自适应性的混合智能模型，依托"空 - 天 - 地 - 水"多源数据融合驱动实现蓝藻水华早识别、早预报、早预警。模型需支撑监测数据实时映射、藻华风险分级预警可视化、历史场景回溯与未来情景推演。
        </p>
      </article>

      <div class="overview-keyline">
        <span>多源数据接入</span>
        <span class="keyline-dot" aria-hidden="true"></span>
        <span>数据质量控制</span>
        <span class="keyline-dot" aria-hidden="true"></span>
        <span>机理 + AI 建模</span>
        <span class="keyline-dot" aria-hidden="true"></span>
        <span>数字孪生预警</span>
      </div>
    </section>

    <footer class="home-footer-v2 home-reveal" style="--reveal-index: 4">
      <div>
        <span>赛题 A23</span>
        <span>数据与计算 · 应用类</span>
      </div>
      <div>
        <span>承办：<strong>我有一点困</strong></span>
        <span>机理 × AI 融合范式</span>
      </div>
    </footer>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const entries = [
  {
    to: { path: '/', hash: '#project-overview' },
    index: '01',
    title: '项目概览',
    voice: 'PROJECT OVERVIEW',
    summary: '问题定义、应用场景与系统目标。',
    meta: 'WHY'
  },
  {
    to: '/tech-route',
    index: '02',
    title: '技术路线',
    voice: 'TECH ROUTE',
    summary: '机理模型、AI 校正与融合预测链路。',
    meta: 'HOW'
  },
  {
    to: '/demo-flow',
    index: '03',
    title: '演示流程',
    voice: 'DEMO FLOW',
    summary: '按讲解顺序串联系统关键能力。',
    meta: 'SHOW'
  },
  {
    to: '/cockpit',
    index: '04',
    title: '数字驾驶舱',
    voice: 'COCKPIT',
    summary: '进入站点、热力图与历史事件视图。',
    meta: 'ENTER'
  }
]

const facts = [
  { label: '监测网络', value: '6 个点位', note: '湖体四向 + 上下游' },
  { label: '预测档位', value: 'T+1 — T+30', note: '短 / 中 / 长期尺度' },
  { label: '当前态势', value: '1 处红色预警', note: '融合模型实时研判' }
]

const monitorPoints = [
  { code: 'NW-01', name: '西北热点区', level: 'high', left: '25%', top: '29%' },
  { code: 'CN-02', name: '湖心浮标', level: 'mid', left: '54%', top: '42%' },
  { code: 'RI-03', name: '入湖河口', level: 'low', left: '14%', top: '60%' },
  { code: 'SE-04', name: '东南监测站', level: 'mid', left: '72%', top: '69%' },
  { code: 'WI-05', name: '取水口', level: 'low', left: '60%', top: '78%' },
  { code: 'SC-06', name: '南部通道', level: 'mid', left: '38%', top: '83%' }
]

const ready = ref(false)

onMounted(() => {
  requestAnimationFrame(() => {
    ready.value = true
  })
})
</script>

<style scoped>
/* Hallmark · macrostructure: Workbench · theme: Midnight · tone: restrained scientific command center · anchor hue: lake teal
 * audience: competition judges and demo viewers · use: understand the project and enter the cockpit
 * enrichment: Tier-A CSS lake telemetry · nav: N9 edge-aligned · footer: Ft5 statement
 * slop: pass · honest: pass · chrome: pass · tokens: pass · responsive: pass · mobile: pass
 */
/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5 */

:global(html),
:global(body) {
  overflow-x: clip;
}

.home-workbench {
  min-height: 100vh;
  max-width: 1560px;
  margin-inline: auto;
  padding: var(--home-space-md) var(--home-space-lg) var(--home-space-xl);
  color: var(--home-color-ink);
  font-family: var(--home-font-body);
  overflow-x: clip;
}

.home-hero-v2 {
  display: grid;
  grid-template-columns: minmax(0, 0.88fr) minmax(0, 1.12fr);
  gap: var(--home-space-2xl);
  align-items: center;
  min-height: min(760px, calc(100vh - 88px));
  padding-block: var(--home-space-xl) var(--home-space-2xl);
}

.home-copy {
  min-width: 0;
}

.home-kicker {
  margin-bottom: var(--home-space-md);
  color: var(--home-color-accent);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  font-weight: 600;
  letter-spacing: 0.12em;
}

.home-title-v2 {
  display: grid;
  gap: var(--home-space-2xs);
  max-width: 9ch;
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: clamp(3.4rem, 7vw, 7.2rem);
  font-style: normal;
  font-weight: 760;
  letter-spacing: -0.045em;
  line-height: 0.92;
  overflow-wrap: anywhere;
}

.home-title-accent {
  color: var(--home-color-ink-soft);
}

.home-lede {
  max-width: 42rem;
  margin-top: var(--home-space-lg);
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-md);
  line-height: 1.8;
}

.home-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--home-space-sm);
  margin-top: var(--home-space-lg);
}

.home-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--home-space-xs);
  min-height: 48px;
  padding-inline: var(--home-space-md);
  border: var(--home-rule-hair) solid var(--home-color-rule-strong);
  border-radius: var(--home-radius-pill);
  font-size: var(--home-text-sm);
  font-weight: 700;
  white-space: nowrap;
  transition:
    transform var(--home-dur-short) var(--home-ease-out),
    background-color var(--home-dur-short) var(--home-ease-out),
    border-color var(--home-dur-short) var(--home-ease-out),
    color var(--home-dur-short) var(--home-ease-out),
    opacity var(--home-dur-short) var(--home-ease-out);
}

.home-action:hover {
  transform: translateY(-2px);
}

.home-action:active {
  transform: translateY(1px);
}

.home-action:focus-visible,
.home-route-card:focus-visible {
  outline: 3px solid var(--home-color-focus);
  outline-offset: 4px;
}

.home-action[aria-disabled="true"],
.home-action:disabled {
  pointer-events: none;
  opacity: 0.45;
}

.home-action[data-state="loading"] {
  cursor: wait;
  opacity: 0.72;
}

.home-action[data-state="error"] {
  border-color: var(--home-color-alert);
  color: var(--home-color-alert);
}

.home-action[data-state="success"] {
  border-color: var(--home-color-stable);
  color: var(--home-color-stable);
}

.home-action-primary {
  border-color: var(--home-color-accent);
  background: var(--home-color-accent);
  color: var(--home-color-accent-ink);
}

.home-action-primary:hover {
  background: var(--home-color-accent-strong);
}

.home-action-secondary {
  background: var(--home-color-surface-soft);
  color: var(--home-color-ink);
}

.home-action-secondary:hover {
  border-color: var(--home-color-accent);
  color: var(--home-color-accent);
}

.home-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: var(--home-space-xl);
  border-top: var(--home-rule-hair) solid var(--home-color-rule);
  border-bottom: var(--home-rule-hair) solid var(--home-color-rule);
}

.home-facts > div {
  min-width: 0;
  padding: var(--home-space-sm) var(--home-space-sm) var(--home-space-sm) 0;
}

.home-facts > div + div {
  padding-left: var(--home-space-sm);
  border-left: var(--home-rule-hair) solid var(--home-color-rule);
}

.home-facts dt {
  color: var(--home-color-muted);
  font-size: var(--home-text-xs);
}

.home-facts dd {
  margin: var(--home-space-2xs) 0 0;
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: var(--home-text-lg);
  font-weight: 700;
}

.home-facts span {
  display: block;
  margin-top: var(--home-space-3xs);
  color: var(--home-color-muted);
  font-size: var(--home-text-xs);
  line-height: 1.5;
}

.lake-workbench {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin: 0;
  border: var(--home-rule-hair) solid var(--glass-border);
  border-radius: var(--home-radius-card);
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  box-shadow: var(--glass-shadow), inset 0 1px 0 var(--glass-highlight);
  overflow: clip;
}

.lake-workbench-head,
.lake-workbench-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--home-space-md);
  padding: var(--home-space-sm) var(--home-space-md);
}

.lake-workbench-head {
  border-bottom: var(--home-rule-hair) solid var(--home-color-rule);
}

.lake-workbench-head > div {
  display: grid;
  gap: var(--home-space-3xs);
}

.lake-workbench-head span,
.lake-workbench-stage {
  color: var(--home-color-muted);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.08em;
}

.lake-workbench-head strong {
  font-family: var(--home-font-display);
  font-size: var(--home-text-md);
}

.lake-workbench-stage {
  padding: var(--home-space-2xs) var(--home-space-xs);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-pill);
  color: var(--home-color-accent);
  white-space: nowrap;
}

.lake-canvas {
  position: relative;
  min-height: 510px;
  overflow: clip;
  background: var(--home-color-paper-2);
  isolation: isolate;
}

.lake-grid {
  position: absolute;
  inset: 0;
  z-index: -3;
  background-image:
    linear-gradient(var(--home-color-grid) var(--home-rule-hair), var(--home-color-transparent) var(--home-rule-hair)),
    linear-gradient(90deg, var(--home-color-grid) var(--home-rule-hair), var(--home-color-transparent) var(--home-rule-hair));
  background-size: 42px 42px;
}

.lake-shape {
  position: absolute;
  inset: 16% 12% 14% 8%;
  z-index: -2;
  border: var(--home-rule-hair) solid var(--home-color-accent-border);
  border-radius: 62% 38% 54% 46% / 44% 58% 42% 56%;
  background:
    radial-gradient(circle at 35% 28%, var(--home-color-lake-highlight), var(--home-color-transparent) 36%),
    linear-gradient(145deg, var(--home-color-lake), var(--home-color-lake-deep));
  transform: rotate(-5deg);
  box-shadow: inset 0 0 46px var(--home-color-lake-shadow);
}

.lake-shape-core {
  position: absolute;
  inset: 29% 24%;
  border: var(--home-rule-hair) solid var(--home-color-violet-border);
  border-radius: 58% 42% 62% 38% / 48% 60% 40% 52%;
  background: var(--home-color-violet-soft);
}

.lake-scan {
  position: absolute;
  inset: 0;
  z-index: -1;
  background: linear-gradient(
    180deg,
    var(--home-color-transparent) 0%,
    var(--home-color-transparent) 45%,
    var(--home-color-scan) 50%,
    var(--home-color-transparent) 55%,
    var(--home-color-transparent) 100%
  );
  transform: translateY(-100%);
  animation: home-lake-scan 5.4s linear infinite;
}

.lake-point {
  position: absolute;
  display: flex;
  align-items: center;
  gap: var(--home-space-2xs);
  transform: translate(-50%, -50%);
  color: var(--home-color-ink);
}

.lake-point-dot {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border: 2px solid var(--home-color-paper-2);
  border-radius: var(--home-radius-pill);
  background: currentColor;
  box-shadow: 0 0 0 5px color-mix(in oklch, currentColor 22%, var(--home-color-transparent));
}

.lake-point.is-high { color: var(--home-color-alert); }
.lake-point.is-mid { color: var(--home-color-watch); }
.lake-point.is-low { color: var(--home-color-stable); }

.lake-point-label {
  display: grid;
  gap: 1px;
  padding: var(--home-space-2xs) var(--home-space-xs);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-sm);
  background: var(--home-color-label);
  backdrop-filter: blur(10px);
}

.lake-point-label strong {
  color: currentColor;
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
}

.lake-point-label small {
  color: var(--home-color-ink-soft);
  font-size: 0.68rem;
  white-space: nowrap;
}

.lake-insight {
  position: absolute;
  right: var(--home-space-md);
  bottom: var(--home-space-md);
  display: grid;
  gap: var(--home-space-3xs);
  max-width: 15rem;
  padding: var(--home-space-sm);
  border: var(--home-rule-hair) solid var(--home-color-alert-border);
  border-radius: var(--home-radius-md);
  background: var(--home-color-label-strong);
  box-shadow: var(--home-shadow-small);
}

.lake-insight span,
.lake-insight small {
  color: var(--home-color-muted);
  font-size: var(--home-text-xs);
}

.lake-insight strong {
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: var(--home-text-md);
}

.lake-workbench-foot {
  flex-wrap: wrap;
  border-top: var(--home-rule-hair) solid var(--home-color-rule);
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-xs);
}

.lake-workbench-foot span {
  display: inline-flex;
  align-items: center;
  gap: var(--home-space-2xs);
}

.lake-workbench-foot i {
  width: 8px;
  height: 8px;
  border-radius: var(--home-radius-pill);
  background: currentColor;
}

.lake-workbench-foot .is-high { color: var(--home-color-alert); }
.lake-workbench-foot .is-mid { color: var(--home-color-watch); }
.lake-workbench-foot .is-low { color: var(--home-color-stable); }

.home-index {
  padding-block: var(--home-space-2xl) var(--home-space-xl);
  border-top: var(--home-rule-hair) solid var(--home-color-rule);
}

.home-index-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--home-space-sm);
  margin-bottom: var(--home-space-lg);
}

.home-index-head > div {
  min-width: 0;
}

.home-index-head > div > p {
  margin-bottom: var(--home-space-2xs);
  color: var(--home-color-accent);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.12em;
}

.home-index-head h2 {
  max-width: 16ch;
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: clamp(2rem, 4vw, 4rem);
  font-style: normal;
  line-height: 1.05;
  overflow-wrap: anywhere;
}

.home-index-head > p {
  max-width: 34rem;
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-sm);
  line-height: 1.75;
}

.home-route-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--home-space-sm);
}

.home-route-card {
  position: relative;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto 28px;
  gap: var(--home-space-sm);
  align-items: center;
  min-height: 84px;
  padding: var(--home-space-sm) var(--home-space-sm);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-md);
  transition:
    transform var(--home-dur-short) var(--home-ease-out),
    background-color var(--home-dur-short) var(--home-ease-out),
    border-color var(--home-dur-short) var(--home-ease-out),
    color var(--home-dur-short) var(--home-ease-out),
    opacity var(--home-dur-short) var(--home-ease-out);
}

.home-route-card:hover {
  transform: translateY(-3px);
  background: var(--home-color-surface-soft);
  border-color: var(--home-color-accent-border);
  box-shadow: var(--glass-shadow);
}

.home-route-card:active {
  transform: translateY(-1px);
}

.home-route-card[aria-disabled="true"] {
  pointer-events: none;
  opacity: 0.45;
}

.home-route-card[data-state="loading"] { cursor: wait; opacity: 0.72; }
.home-route-card[data-state="error"] { color: var(--home-color-alert); }
.home-route-card[data-state="success"] { color: var(--home-color-stable); }

.home-route-num {
  color: var(--home-color-muted);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-sm);
}

.home-route-copy {
  display: grid;
  gap: var(--home-space-3xs);
  min-width: 0;
}

.home-route-copy small {
  color: var(--home-color-muted);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.08em;
}

.home-route-copy strong {
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: var(--home-text-lg);
  font-weight: 700;
}

.home-route-copy > span {
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-sm);
}

.home-route-meta {
  padding: var(--home-space-2xs) var(--home-space-xs);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-pill);
  color: var(--home-color-muted);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
}

.home-route-arrow {
  color: var(--home-color-accent);
  font-size: var(--home-text-lg);
}

/* ============ 项目概览 ============ */
.home-overview {
  scroll-margin-top: 76px;
  padding-block: var(--home-space-xl) var(--home-space-lg);
  border-top: var(--home-rule-hair) solid var(--home-color-rule);
}

.home-overview-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--home-space-sm);
  margin-bottom: var(--home-space-lg);
}

.home-overview-head > div { min-width: 0; }

.home-overview-kicker {
  margin-bottom: var(--home-space-2xs);
  color: var(--home-color-accent);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.12em;
}

.home-overview-head h2 {
  max-width: 18ch;
  margin: 0;
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: clamp(1.8rem, 3.5vw, 3.2rem);
  font-weight: 760;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

.home-overview-lede {
  max-width: 48rem;
  margin: 0;
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-md);
  line-height: 1.75;
}

.overview-meta-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--home-space-sm);
  margin-bottom: var(--home-space-lg);
}

.overview-meta-card {
  display: grid;
  gap: var(--home-space-3xs);
  padding: var(--home-space-sm) var(--home-space-sm);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-md);
  background: var(--home-color-surface-soft);
}

.overview-meta-card span {
  color: var(--home-color-muted);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.08em;
}

.overview-meta-card strong {
  color: var(--home-color-ink);
  font-size: var(--home-text-sm);
  font-weight: 700;
}

.overview-context,
.overview-solution {
  margin-bottom: var(--home-space-lg);
}

.overview-context {
  padding: var(--home-space-md);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-lg);
  background: var(--home-color-surface-soft);
}

.overview-solution {
  padding: var(--home-space-md);
  border: var(--home-rule-hair) solid var(--home-color-accent-border);
  border-radius: var(--home-radius-lg);
  background:
    linear-gradient(180deg, var(--home-color-accent-soft), var(--home-color-transparent));
}

.overview-kicker {
  display: inline-flex;
  align-items: center;
  gap: var(--home-space-xs);
  margin: 0 0 var(--home-space-sm);
  color: var(--home-color-accent);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.1em;
  font-weight: 600;
}

.overview-kicker::before {
  content: "";
  display: inline-block;
  width: 28px;
  height: 1px;
  background: var(--home-color-accent);
}

.overview-h3 {
  margin: 0 0 var(--home-space-sm);
  max-width: 40ch;
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: clamp(1.15rem, 2vw, 1.6rem);
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: -0.01em;
}

.overview-prose {
  max-width: 52rem;
  margin: 0;
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-sm);
  line-height: 1.85;
  text-align: justify;
}

.overview-split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--home-space-sm);
  margin-bottom: var(--home-space-lg);
}

.overview-block {
  padding: var(--home-space-sm) var(--home-space-md);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-lg);
  background:
    linear-gradient(180deg, var(--home-color-surface-soft), var(--home-color-transparent));
  position: relative;
  overflow: hidden;
}

.overview-block::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 100% 0%, var(--home-color-accent-soft), var(--home-color-transparent) 50%);
  pointer-events: none;
}

.overview-block h4 {
  position: relative;
  margin: var(--home-space-3xs) 0 var(--home-space-2xs);
  color: var(--home-color-ink);
  font-family: var(--home-font-display);
  font-size: var(--home-text-md);
  font-weight: 700;
}

.overview-block p {
  position: relative;
  margin: 0;
  color: var(--home-color-ink-soft);
  font-size: var(--home-text-sm);
  line-height: 1.75;
}

.overview-keyline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--home-space-sm);
  margin-top: var(--home-space-sm);
  font-family: var(--home-font-mono);
  font-size: var(--home-text-xs);
  letter-spacing: 0.06em;
  color: var(--home-color-ink);
}

.overview-keyline > span:not(.keyline-dot) {
  padding: var(--home-space-2xs) var(--home-space-sm);
  border: var(--home-rule-hair) solid var(--home-color-rule);
  border-radius: var(--home-radius-pill);
  background: var(--home-color-surface-soft);
}

.keyline-dot {
  width: 4px;
  height: 4px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--home-color-muted);
}

.home-footer-v2 {
  display: flex;
  justify-content: space-between;
  gap: var(--home-space-lg);
  padding-top: var(--home-space-md);
  border-top: var(--home-rule-hair) solid var(--home-color-rule);
  color: var(--home-color-muted);
  font-size: var(--home-text-xs);
}

.home-footer-v2 > div {
  display: flex;
  flex-wrap: wrap;
  gap: var(--home-space-md);
}

.home-footer-v2 strong {
  color: var(--home-color-ink);
}

.home-reveal {
  opacity: 0;
  transform: translateY(14px);
  transition:
    opacity var(--home-dur-reveal) var(--home-ease-out),
    transform var(--home-dur-reveal) var(--home-ease-out);
  transition-delay: calc(var(--reveal-index, 0) * 90ms);
}

.is-ready .home-reveal {
  opacity: 1;
  transform: none;
}

@keyframes home-lake-scan {
  from { transform: translateY(-100%); }
  to { transform: translateY(100%); }
}

@media (max-width: 1120px) {
  .home-hero-v2 {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .home-copy {
    max-width: 820px;
  }

  .home-hero-v2 > * {
    min-width: 0;
  }

  .lake-canvas {
    min-height: 540px;
  }
}

@media (max-width: 768px) {
  .home-workbench {
    padding: var(--home-space-sm) var(--home-space-sm) var(--home-space-lg);
  }

  .home-footer-v2 {
    align-items: flex-start;
    flex-direction: column;
  }

  .home-hero-v2 {
    gap: var(--home-space-xl);
    padding-block: var(--home-space-lg) var(--home-space-xl);
  }

  .home-title-v2 {
    font-size: clamp(3rem, 16vw, 5.2rem);
  }

  .home-facts {
    grid-template-columns: 1fr;
  }

  .home-facts > div,
  .home-facts > div + div {
    padding: var(--home-space-sm) 0;
    border-left: 0;
  }

  .home-facts > div + div {
    border-top: var(--home-rule-hair) solid var(--home-color-rule);
  }

  .lake-canvas {
    min-height: 500px;
  }

  .lake-point-label small {
    display: none;
  }

  .lake-workbench-stage {
    white-space: normal;
  }

  .home-route-grid {
    grid-template-columns: 1fr;
  }

  .home-route-card {
    grid-template-columns: 44px minmax(0, 1fr) 28px;
  }

  .home-route-meta {
    display: none;
  }

  .overview-meta-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-split {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .home-actions {
    display: grid;
  }

  .home-action {
    width: 100%;
  }

  .lake-workbench-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .lake-canvas {
    min-height: 460px;
  }

  .lake-point {
    gap: var(--home-space-3xs);
  }

  .lake-point-label {
    padding: var(--home-space-3xs) var(--home-space-2xs);
  }

  .lake-insight {
    right: var(--home-space-xs);
    left: var(--home-space-xs);
    bottom: var(--home-space-xs);
    max-width: none;
  }

  .home-route-card {
    grid-template-columns: 36px minmax(0, 1fr) 24px;
    min-height: 76px;
    padding-inline: var(--home-space-2xs);
  }

  .home-route-copy strong {
    font-size: var(--home-text-md);
  }

  .overview-meta-row {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .home-reveal,
  .home-action,
  .home-route-card {
    transition-duration: 50ms;
  }

  .home-reveal {
    transform: none;
  }

  .lake-scan {
    animation: none;
  }
}
</style>
