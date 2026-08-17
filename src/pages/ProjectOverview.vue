<template>
  <main class="page-narrative">
    <HeroShell
      section-no="01 / 04"
      eyebrow="PROJECT OVERVIEW"
      title="项目概览"
      description="面向新三湖（滇池、太湖、巢湖）与老三湖（太湖、巢湖、滆湖）等重点湖库，建立机理与 AI 融合的蓝藻水华监测预警模型，输出从早识别、早预报到早预警的全链条能力。"
    >
      <template #meta>
        <div class="meta-card">
          <span class="meta-key">主题</span>
          <span class="meta-value">数据与计算</span>
        </div>
        <div class="meta-card">
          <span class="meta-key">赛题</span>
          <span class="meta-value">A23 · 应用类</span>
        </div>
        <div class="meta-card">
          <span class="meta-key">主办</span>
          <span class="meta-value">我有一点困</span>
        </div>
        <div class="meta-card">
          <span class="meta-key">核心</span>
          <span class="meta-value">机理 × AI 融合</span>
        </div>
      </template>

      <div class="narrative-section">
        <p class="narrative-kicker">整体背景 · CONTEXT</p>
        <h2 class="narrative-h2">
          蓝藻水华是富营养化水体在特定水文气候条件下<br />分发性增殖的生态灾变现象
        </h2>
        <p class="narrative-prose">
          蓝藻水华严重威胁饮用水安全、水生态系统健康及流域经济社会的可持续发展。
          随着《水污染防治行动计划》深入推进及《"十四五"生态环境监测规划》明确要求在新老三湖等重点湖库开展蓝藻水华监测预警，传统"人工采样 + 实验室分析"的监测模式已难以满足"提前预警、精准防控"的管理需要。
        </p>
      </div>

      <div class="narrative-split">
        <article class="narrative-block">
          <p class="narrative-kicker">传统路径 · CLASSICAL</p>
          <h3>水动力 - 水质 - 藻类生长耦合模型</h3>
          <p>
            可刻画营养盐循环、藻类生理生态过程及物理迁移规律，具备可解释性强、外推能力好的优势，但参数率定困难、计算效率低，对突发扰动响应滞后。
          </p>
        </article>
        <article class="narrative-block">
          <p class="narrative-kicker">数据驱动 · DATA-DRIVEN</p>
          <h3>深度学习 / 物理信息神经网络</h3>
          <p>
            能从多源异构监测数据中挖掘环境因子与藻华分发的非线性映射关系，实现短期预警与风险分级，但物理一致性约束弱、泛化性能不足。
          </p>
        </article>
      </div>

      <div class="narrative-section narrative-solution">
        <p class="narrative-kicker">融合范式 · OUR ANSWER</p>
        <h2 class="narrative-h2">
          把藻类生长动力学方程、流体水力学守恒定律等物理机理<br />嵌入神经网络架构
        </h2>
        <p class="narrative-prose">
          或利用 AI 对机理模型参数进行实时校正，构建兼具物理可解释性与数据自适应性的混合智能模型，依托"空 - 天 - 地 - 水"多源数据融合驱动实现蓝藻水华早识别、早预报、早预警。
          模型需支撑监测数据实时映射、藻华风险分级预警可视化、历史场景回溯与未来情景推演。
        </p>
      </div>

      <div class="narrative-keyline">
        <span>多源数据接入</span><span class="keyline-dot"></span>
        <span>数据质量控制</span><span class="keyline-dot"></span>
        <span>机理 + AI 建模</span><span class="keyline-dot"></span>
        <span>数字孪生预警</span>
      </div>

      <div class="narrative-image-row">
        <div class="image-slot tall" data-label="湖区现场照片位 · 准备后期插入"></div>
        <div class="image-slot tall" data-label="团队合影 / 现场调研位 · 准备后期插入"></div>
      </div>
    </HeroShell>

    <footer class="narrative-foot">
      <RouterLink class="button primary" to="/tech-route">下一节：技术路线 →</RouterLink>
      <RouterLink class="button secondary" to="/">返回主页</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'
</script>

<style scoped>
.page-narrative {
  max-width: 1480px;
  margin: 0 auto;
  padding: 0 36px 60px;
}

.meta-card {
  padding: 14px 18px;
  border-radius: var(--radius-md);
  border: 1px solid var(--panel-line);
  background: var(--c-surface-soft);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.meta-key {
  font-size: 11px;
  letter-spacing: 2px;
  color: var(--muted);
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
}
.meta-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.narrative-section { margin: 28px 0; }
.narrative-kicker {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin: 0 0 14px;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: 4px;
  color: var(--teal);
  font-weight: 700;
}
.narrative-kicker::before {
  content: "";
  display: inline-block;
  width: 36px;
  height: 1px;
  background: var(--teal);
}
.narrative-h2 {
  margin: 0 0 14px;
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: clamp(24px, 2.6vw, 36px);
  font-weight: 800;
  line-height: 1.2;
  color: var(--text);
  letter-spacing: -0.01em;
}
.narrative-prose {
  max-width: 880px;
  margin: 0;
  color: var(--text-soft);
  font-size: 15.5px;
  line-height: 1.85;
  text-align: justify;
  text-justify: inter-character;
}
.narrative-prose::first-letter {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 1.15em;
  color: var(--teal);
  font-weight: 800;
}

.narrative-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin: 32px 0;
}
.narrative-block {
  padding: 24px 26px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--panel-line);
  background:
    linear-gradient(180deg, var(--c-accent-soft), transparent);
  position: relative;
  overflow: hidden;
}
.narrative-block::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 100% 0%, var(--c-accent-soft), transparent 50%);
  pointer-events: none;
}
.narrative-block h3 {
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: 22px;
  font-weight: 800;
  margin: 8px 0 12px;
  color: var(--text);
}
.narrative-block p {
  margin: 0;
  color: var(--text-soft);
  font-size: 14.5px;
  line-height: 1.8;
}

.narrative-solution {
  padding: 32px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--panel-line);
  background:
    linear-gradient(180deg, var(--c-accent-soft), transparent);
  margin: 32px 0;
}

.narrative-keyline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin: 18px 0 12px;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 13px;
  letter-spacing: 2px;
  color: var(--text);
}
.narrative-keyline > span:not(.keyline-dot) {
  padding: 6px 14px;
  border: 1px solid var(--panel-line);
  border-radius: 999px;
  background: var(--c-surface-soft);
}
.keyline-dot {
  width: 4px; height: 4px; border-radius: 50%; background: var(--muted);
}

.narrative-image-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 32px;
}

.narrative-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--panel-line);
}

@media (max-width: 880px) {
  .page-narrative { padding: 0 18px 40px; }
  .narrative-split, .narrative-image-row { grid-template-columns: 1fr; }
}
</style>