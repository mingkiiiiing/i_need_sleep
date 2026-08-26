<template>
  <main class="page-cockpit">
    <HeroShell
      section-no="04 / 04"
      eyebrow="COCKPIT"
      title="驾驶舱总览"
      description="驾驶舱由 3 个并列子页组成：演示分区研判、模拟风险场与演示事件回放。当前阶段统一使用可追溯的模拟数据。"
    >
      <template #meta>
        <div class="meta-card"><span class="meta-key">子页数</span><span class="meta-value">3 个并列</span></div>
        <div class="meta-card"><span class="meta-key">时间档位</span><span class="meta-value">1 / 3 / 7 / 15 天演示；30 天预演</span></div>
        <div class="meta-card"><span class="meta-key">演示分区</span><span class="meta-value">6 个 demo_zone</span></div>
        <div class="meta-card"><span class="meta-key">数据模式</span><span class="meta-value">SIMULATED</span></div>
      </template>

      <p class="cockpit-prose">
        不再把所有 tab 塞在一页里，而是拆成三个独立子页。每个子页都有自己的侧重视角，跨页之间共享同一份时间档位与点位选择：点选档案点 → 风险分区同步高亮；事件回放时 → 监测站档位联动刷新。
      </p>

      <ol class="cockpit-stream">
        <li
          v-for="(tile, i) in tiles"
          :key="tile.to"
          class="cockpit-tile"
          :style="{ '--enter-delay': (140 + i * 110) + 'ms' }"
        >
          <RouterLink :to="tile.to" class="cockpit-link">
            <header class="tile-head">
              <span class="tile-num">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="tile-scope">{{ tile.scope }}</span>
            </header>
            <h3 class="tile-title">{{ tile.title }}</h3>
            <p class="tile-desc">{{ tile.desc }}</p>
            <ul class="tile-points">
              <li v-for="p in tile.points" :key="p">{{ p }}</li>
            </ul>
            <footer class="tile-foot">
              <span>{{ tile.cta }}</span>
              <span class="tile-arrow" aria-hidden="true">→</span>
            </footer>
          </RouterLink>
        </li>
      </ol>
    </HeroShell>

    <footer class="cockpit-foot">
      <RouterLink class="button secondary" to="/">← 返回主页</RouterLink>
    </footer>
  </main>
</template>

<script setup>
import HeroShell from '../components/HeroShell.vue'

const tiles = [
  {
    to: '/stations',
    scope: 'TAB 01 · STATIONS',
    title: '监测站档位研判',
    desc: '点位地图 + 详情卡 + 藻密度时序曲线 + 因子贡献 + 现场图位。',
    points: ['6 个点位联动', '5 档预测切换', '因子贡献 / 事件流'],
    cta: '进入监测站页'
  },
  {
    to: '/heatmap',
    scope: 'TAB 02 · RISK HEATMAP',
    title: '风险热力分区',
    desc: '19×11 网格风险分布 + 各点强度排行 + 机理 AI 置信曲线。',
    points: ['高/中/低风险分布', '点位强度排行', '机理 + AI 共识曲线'],
    cta: '进入风险分区'
  },
  {
    to: '/history',
    scope: 'TAB 03 · HISTORY',
    title: '历史事件回放',
    desc: '事件流列表 + 时间轴播放器 + 点位时序 + 因果链溯源。',
    points: ['15 条事件流', '事件联动档位', '机理 + AI 因果链'],
    cta: '进入历史回放'
  }
]
</script>

<style scoped>
.page-cockpit {
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

.cockpit-prose {
  max-width: 880px;
  margin: 0 0 32px;
  color: var(--text-soft);
  font-size: 15.5px;
  line-height: 1.85;
}
.cockpit-prose::first-letter {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 1.15em;
  color: var(--teal);
  font-weight: 800;
}

.cockpit-stream {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 32px;
}
.cockpit-tile {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity .9s ease var(--enter-delay, 0ms), transform .9s ease var(--enter-delay, 0ms);
}
.hero-body.in .cockpit-tile {
  opacity: 1;
  transform: none;
}

.cockpit-link {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 26px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  box-shadow: var(--glass-shadow), inset 0 1px 0 var(--glass-highlight);
  color: var(--text);
  text-decoration: none;
  height: 100%;
  position: relative;
  overflow: hidden;
  transition: border-color .25s ease, transform .25s ease;
}
.cockpit-link::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 0 0, var(--c-accent-soft), transparent 60%);
  pointer-events: none;
}
.cockpit-link:hover {
  border-color: var(--teal);
  transform: translateY(-4px);
}

.tile-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}
.tile-num {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 28px;
  font-weight: 800;
  color: var(--teal);
  letter-spacing: 2px;
}
.tile-scope {
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 11px;
  letter-spacing: 3px;
  color: var(--muted);
}
.tile-title {
  margin: 0;
  font-family: "Bahnschrift", "PingFang SC", sans-serif;
  font-size: 24px;
  font-weight: 800;
}
.tile-desc {
  margin: 0;
  color: var(--text-soft);
  font-size: 14px;
  line-height: 1.7;
}
.tile-points {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tile-points li {
  position: relative;
  padding-left: 14px;
  color: var(--text-soft);
  font-size: 13px;
}
.tile-points li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0.65em;
  width: 6px;
  height: 1px;
  background: var(--teal);
}
.tile-foot {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid var(--panel-line);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--text);
}
.tile-arrow {
  color: var(--teal);
  transition: transform .25s ease;
}
.cockpit-link:hover .tile-arrow { transform: translateX(6px); }

.cockpit-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--panel-line);
}

@media (max-width: 1080px) {
  .cockpit-stream { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 880px) {
  .page-cockpit { padding: 0 18px 40px; }
  .cockpit-stream { grid-template-columns: 1fr; }
}
</style>
