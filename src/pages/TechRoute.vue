<template>
  <main class="page-tech">
    <HeroShell
      section-no="02 / 04"
      eyebrow="TECH ROUTE"
      title="技术路线"
      description="从多源数据接入到机理 + AI 融合建模，再到数字孪生预警与可视化发布，技术路线分五段递进，每一段都对应着可观测的中间产物。"
    >
      <template #meta>
        <div class="meta-card"><span class="meta-key">数据层</span><span class="meta-value">空 - 天 - 地 - 水</span></div>
        <div class="meta-card"><span class="meta-key">模型层</span><span class="meta-value">机理 + AI 融合</span></div>
        <div class="meta-card"><span class="meta-key">尺度</span><span class="meta-value">T+1 → T+30</span></div>
        <div class="meta-card"><span class="meta-key">交付</span><span class="meta-value">数字孪生平台</span></div>
      </template>

      <ol class="tech-stream">
        <li class="tech-stage" v-for="(stage, i) in stages" :key="stage.key">
          <div class="stage-rail">
            <span class="stage-num">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="stage-line"></span>
          </div>
          <div class="stage-body">
            <header>
              <p class="stage-kicker">{{ stage.scope }}</p>
              <h3>{{ stage.title }}</h3>
            </header>
            <p class="stage-text">{{ stage.text }}</p>
            <ul class="stage-bullets">
              <li v-for="b in stage.bullets" :key="b">{{ b }}</li>
            </ul>
            <div class="stage-artifacts">
              <span class="artifact-tag" v-for="a in stage.artifacts" :key="a">{{ a }}</span>
            </div>
          </div>
        </li>
      </ol>
    </HeroShell>

    <footer class="tech-foot">
      <RouterLink class="button primary" to="/demo-flow">下一节：演示流程 →</RouterLink>
      <RouterLink class="button secondary" to="/project-overview">← 返回项目概览</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'

const stages = [
  {
    key: 'data',
    scope: 'STAGE 01 · DATA',
    title: '多源监测数据融合接入',
    text: '设计数据接入适配器，支持卫星遥感、水质自动站、气象预报、水文站等多源数据的标准化接入；实现数据质量控制算法（异常检测、一致性校验、缺失值插补）。',
    bullets: [
      '遥感影像：哨兵 2 号 L2A 级产品 / MODIS',
      '水质自动站：藻密度 / 叶绿素 a / 总磷',
      '气象预报 + 水文站上游流量',
      '异常检测 · 一致性校验 · 缺失值插补'
    ],
    artifacts: ['数据接入适配器', '质量控制算法', '时空对齐']
  },
  {
    key: 'mechanism',
    scope: 'STAGE 02 · MECHANISM',
    title: '蓝藻水华机理建模',
    text: '建立藻类生长动力学基础方程（Logistic 增长、 Droop 模型或 Monod 方程），耦合水温、光照、营养盐等环境因子的限制函数；集成一维 / 二维水动力输运模型，模拟藻类空间迁移。',
    bullets: [
      'Logistic / Droop / Monod 方程',
      '水温 · 光照 · 营养盐限制函数',
      '一维 / 二维水动力输运',
      '可解释的物理参数率定'
    ],
    artifacts: ['机理方程库', '水动力模型', '参数率定工具']
  },
  {
    key: 'ai',
    scope: 'STAGE 03 · AI',
    title: 'AI 增强预测模型',
    text: '基于时序神经网络、集成学习等构建预测预警模型与风险分级模型；实现机理模型输出作为 AI 模型输入特征的松耦合融合，或 AI 对机理模型关键参数的动态校正。',
    bullets: [
      '时序神经网络 / 集成学习',
      '机理 → AI 特征级融合',
      'AI → 机理参数动态校正',
      '风险分级 + 不确定性量化'
    ],
    artifacts: ['时序预测模型', '风险分级模型', '参数自校正']
  },
  {
    key: 'explain',
    scope: 'STAGE 04 · EXPLAIN',
    title: '可解释性分析模块',
    text: '集成 SHAP / LIME 等解释工具，输出单样本预测解释；实现全局特征重要性分析与关键驱动因子识别，提供"因子 - 响应"敏感性可视化曲线。',
    bullets: [
      'SHAP / LIME 单样本解释',
      '全局特征重要性分析',
      '关键驱动因子识别',
      '因子 - 响应敏感性曲线'
    ],
    artifacts: ['SHAP / LIME 解释器', '驱动因子清单', '敏感性曲线']
  },
  {
    key: 'digital-twin',
    scope: 'STAGE 05 · TWIN',
    title: '数字孪生预警平台',
    text: '构建流域 / 溪流 / 湖库的二维 / 三维数字孪生底图，集成监测站点、水华历史分发点等空间要素；实现预测结果的空间插值与风险分区热力图生成；开放预警信息发布模块。',
    bullets: [
      '二 / 三维数字孪生底图',
      '空间插值 + 热力图生成',
      '预警信息发布模块',
      '阈值触发 · 短信 / 邮件模拟'
    ],
    artifacts: ['孪生底图', '预警发布台', '响应流程编排']
  }
]
</script>

<style scoped>
.page-tech {
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
.meta-key { font-size: 11px; letter-spacing: 2px; color: var(--muted); font-family: "Bahnschrift", "Segoe UI", sans-serif; }
.meta-value { font-size: 15px; font-weight: 700; color: var(--text); }

.tech-stream {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.tech-stage {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 24px;
  padding: 26px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  box-shadow: var(--glass-shadow), inset 0 1px 0 var(--glass-highlight);
  transition: border-color .25s ease, transform .25s ease;
}
.tech-stage:hover {
  border-color: var(--glass-border-strong);
  transform: translateX(4px);
}

.stage-rail {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  position: relative;
}
.stage-num {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 28px;
  font-weight: 800;
  color: var(--teal);
  letter-spacing: 2px;
}
.stage-line {
  flex: 1;
  width: 1px;
  background: linear-gradient(180deg, var(--teal), transparent);
  min-height: 32px;
}

.stage-body header { margin-bottom: 12px; }
.stage-kicker {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: 3px;
  color: var(--muted);
}
.stage-kicker::before {
  content: "";
  display: inline-block;
  width: 26px;
  height: 1px;
  background: var(--muted);
}
.stage-body h3 {
  margin: 0;
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: clamp(20px, 2vw, 26px);
  font-weight: 800;
  color: var(--text);
}
.stage-text {
  margin: 8px 0 14px;
  color: var(--text-soft);
  font-size: 15px;
  line-height: 1.8;
  max-width: 860px;
}
.stage-bullets {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 18px;
  margin: 0 0 14px;
  padding: 0;
  list-style: none;
}
.stage-bullets li {
  position: relative;
  padding-left: 16px;
  color: var(--text-soft);
  font-size: 13.5px;
  line-height: 1.7;
}
.stage-bullets li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0.7em;
  width: 6px;
  height: 1px;
  background: var(--teal);
}
.stage-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--panel-line);
}
.artifact-tag {
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--panel-line);
  background: var(--c-accent-soft);
  color: var(--teal);
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: 1px;
}

.tech-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--panel-line);
}

@media (max-width: 880px) {
  .page-tech { padding: 0 18px 40px; }
  .tech-stage { grid-template-columns: 64px 1fr; gap: 14px; padding: 20px; }
  .stage-num { font-size: 22px; }
  .stage-bullets { grid-template-columns: 1fr; }
}
</style>