<template>
  <main class="page-demo">
    <HeroShell
      section-no="03 / 04"
      eyebrow="DEMO FLOW"
      title="演示流程"
      description="答辩演示路径：从问题背景 → 技术路线 → 驾驶舱总览 → 监测站档位研判 → 风险热力分区 → 历史回放，最后回到主页。一条单向闭环叙事，6 个节点任选切入。"
    >
      <template #meta>
        <div class="meta-card"><span class="meta-key">演示时长</span><span class="meta-value">建议 8 ~ 12 分钟</span></div>
        <div class="meta-card"><span class="meta-key">主路线</span><span class="meta-value">6 节点单向闭环</span></div>
        <div class="meta-card"><span class="meta-key">备选切入</span><span class="meta-value">驾驶舱 / 历史回放</span></div>
        <div class="meta-card"><span class="meta-key">交付物</span><span class="meta-value">数字孪生驾驶舱</span></div>
      </template>

      <ol class="demo-path">
        <li
          v-for="(node, i) in path"
          :key="node.key"
          class="demo-node"
          :class="i === path.length - 1 ? 'last' : ''"
        >
          <div class="node-rail">
            <span class="node-num">{{ String(i + 1).padStart(2, '0') }}</span>
            <span v-if="i !== path.length - 1" class="node-line"></span>
          </div>
          <div class="node-body">
            <p class="node-kicker">{{ node.kicker }}</p>
            <h3>{{ node.title }}</h3>
            <p class="node-desc">{{ node.desc }}</p>
            <RouterLink v-if="node.to" :to="node.to" class="node-link">
              {{ node.linkLabel }} <span aria-hidden="true">→</span>
            </RouterLink>
            <span v-else class="node-link disabled">终点回到首页</span>
          </div>
        </li>
      </ol>

      <div class="demo-image-row">
        <div class="image-slot" data-label="演示现场图位 · 待替换"></div>
        <div class="image-slot" data-label="团队/产品位 · 待替换"></div>
      </div>
    </HeroShell>

    <footer class="demo-foot">
      <RouterLink class="button primary" to="/cockpit">进入驾驶舱总览 →</RouterLink>
      <RouterLink class="button secondary" to="/tech-route">← 返回技术路线</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'

const path = [
  {
    key: 'start',
    kicker: 'CH 01 · BACKGROUND',
    title: '背景与价值',
    desc: '讲清赛题、痛点与项目定位，让评审一眼看到我们要解决的问题。',
    to: '/project-overview',
    linkLabel: '查看项目概览'
  },
  {
    key: 'route',
    kicker: 'CH 02 · TECH ROUTE',
    title: '技术路线',
    desc: '分 5 阶段讲清模型如何搭建，多源数据如何融合，预警如何发布。',
    to: '/tech-route',
    linkLabel: '查看技术路线'
  },
  {
    key: 'cockpit',
    kicker: 'CH 03 · COCKPIT',
    title: '驾驶舱总览',
    desc: '作为页面索引，进入监测站 / 风险分区 / 历史回放三个并列子页。',
    to: '/cockpit',
    linkLabel: '进入驾驶舱总览'
  },
  {
    key: 'stations',
    kicker: 'CH 04 · STATIONS',
    title: '监测站档位研判',
    desc: '展示点位地图、详情卡、藻密度时序曲线与可解释因子贡献。',
    to: '/stations',
    linkLabel: '进入监测站页'
  },
  {
    key: 'heatmap',
    kicker: 'CH 05 · RISK HEATMAP',
    title: '风险热力分区',
    desc: '展示风险高值区随时间尺度的扩散 / 收敛，搭配机理 + AI 置信曲线。',
    to: '/heatmap',
    linkLabel: '进入风险热力'
  },
  {
    key: 'history',
    kicker: 'CH 06 · HISTORY',
    title: '历史事件回放',
    desc: '回放时间轴事件流，演示事件如何驱动档位、点位与因果链同步。',
    to: '/history',
    linkLabel: '进入历史回放'
  }
]
</script>

<style scoped>
.page-demo {
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

.demo-path {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
}
.demo-node {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: 28px;
  position: relative;
}
.node-rail {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
}
.node-num {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 26px;
  font-weight: 800;
  color: var(--teal);
  letter-spacing: 2px;
}
.node-line {
  flex: 1;
  width: 1px;
  margin-left: 12px;
  background: linear-gradient(180deg, var(--teal), transparent);
  min-height: 36px;
}
.node-body {
  padding: 14px 0 32px;
  border-bottom: 1px solid var(--panel-line);
}
.demo-node.last .node-body { border-bottom: none; padding-bottom: 0; }

.node-kicker {
  margin: 0 0 8px;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: 3px;
  color: var(--muted);
}
.node-body h3 {
  margin: 0 0 8px;
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: clamp(22px, 2.4vw, 30px);
  font-weight: 800;
  color: var(--text);
}
.node-desc {
  margin: 0 0 14px;
  color: var(--text-soft);
  font-size: 15px;
  line-height: 1.8;
  max-width: 760px;
}
.node-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--teal);
  background: var(--c-accent-soft);
  color: var(--teal);
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 12px;
  letter-spacing: 2px;
  text-decoration: none;
  transition: background .2s ease, color .2s ease;
}
.node-link:hover {
  background: var(--teal);
  color: var(--c-accent-ink);
}
.node-link.disabled {
  border-style: dashed;
  color: var(--muted);
  background: transparent;
}

.demo-image-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 32px;
}

.demo-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--panel-line);
}

@media (max-width: 880px) {
  .page-demo { padding: 0 18px 40px; }
  .demo-node { grid-template-columns: 64px 1fr; gap: 14px; }
  .node-num { font-size: 22px; }
  .demo-image-row { grid-template-columns: 1fr; }
}
</style>