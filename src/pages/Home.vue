<template>
  <main class="shell home">
    <!-- ============ 首屏：左 5 列信息 / 右 7 列太湖缩略态势 ============ -->
    <section class="hero" aria-labelledby="home-title">
      <div class="hero-copy">
        <p class="kicker">A23 · 地表水蓝藻水华监测预警</p>
        <h1 id="home-title" class="title">
          <span>蓝藻水华</span>
          <span class="title-accent">监测预警</span>
        </h1>
        <p class="lede">
          融合多源数据、机理模型与人工智能，支持全湖态势研判、站点下钻、时空推演与历史复盘。
        </p>
        <p class="boundary">
          <strong>{{ identity.dataModeLabel }}（{{ identity.dataMode }}）</strong>
          当前为统一演示数据联调环境，{{ identity.claimBoundary }}。
        </p>
        <div class="actions">
          <RouterLink class="btn btn-primary" to="/cockpit">
            进入综合驾驶舱<span class="btn-arrow" aria-hidden="true">→</span>
          </RouterLink>
          <RouterLink class="btn btn-ghost" :to="{ path: '/', hash: '#project-overview' }">
            查看项目方案
          </RouterLink>
        </div>
        <dl class="facts" aria-label="系统能力状态">
          <div v-for="fact in facts" :key="fact.label" class="fact">
            <dt>{{ fact.label }}</dt>
            <dd>{{ fact.value }}</dd>
            <span>{{ fact.note }}</span>
          </div>
        </dl>
      </div>

      <figure class="lake-panel">
        <figcaption class="lake-head">
          <div class="lake-head-copy">
            <strong>{{ identity.lakeName }} · 演示分区态势</strong>
            <span>{{ identity.datasetVersionId }} · 非真实站点 · 点击分区进入站点研判</span>
          </div>
          <DataModeBadge mode="simulated" :label="identity.dataMode" />
        </figcaption>

        <div class="lake-canvas" role="group" aria-label="太湖演示分区缩略态势图，六个分区可点击下钻">
          <svg class="lake-svg" viewBox="0 0 520 400" preserveAspectRatio="none" aria-hidden="true">
            <!-- 真实太湖轮廓（OSM relation 1126533，见 data/taihuOutline.js），evenodd 渲染岛屿镂空 -->
            <path class="lake-body" fill-rule="evenodd" :d="TAIHU_OUTLINE.path" />
          </svg>

          <button
            v-for="z in zones"
            :key="z.id"
            type="button"
            class="zone"
            :class="`zone--${z.riskClass}`"
            :style="{ left: z.pos.left, top: z.pos.top }"
            :aria-label="`演示分区 ${z.code} ${z.name}，${z.risk}，点击进入站点研判`"
            @click="goZone(z.id)"
          >
            <span class="zone-dot" aria-hidden="true"></span>
            <span class="zone-tip">
              <strong>{{ z.code }} {{ z.name }}</strong>
              <em>{{ z.risk }} · 点击下钻</em>
            </span>
          </button>
        </div>

        <div class="lake-foot" aria-label="分区风险统计">
          <span class="lg lg--high"><i aria-hidden="true"></i>红色预警 × {{ regionSummary.riskCounts.high }}</span>
          <span class="lg lg--mid"><i aria-hidden="true"></i>橙色关注 × {{ regionSummary.riskCounts.mid }}</span>
          <span class="lg lg--low"><i aria-hidden="true"></i>绿色稳定 × {{ regionSummary.riskCounts.low }}</span>
          <a
            class="lg-attr"
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="license noopener"
          >湖岸轮廓 © OpenStreetMap 贡献者（ODbL）</a>
        </div>
      </figure>
    </section>

    <!-- ============ 第二屏：四个核心入口 ============ -->
    <section class="entries" aria-labelledby="entries-title">
      <header class="entries-head">
        <h2 id="entries-title">核心业务入口</h2>
        <p>四个正式业务模块 · 全部使用演示数据</p>
      </header>
      <div class="entry-grid">
        <RouterLink v-for="e in entries" :key="e.no" class="entry-card" :to="e.to">
          <span class="entry-no">{{ e.no }}</span>
          <span class="entry-title">{{ e.title }}</span>
          <span class="entry-desc">{{ e.desc }}</span>
          <span class="entry-mode">{{ e.mode }}</span>
          <span class="entry-cta">进入 <i aria-hidden="true">→</i></span>
        </RouterLink>
      </div>
    </section>

    <!-- ============ 项目方案 ============ -->
    <section id="project-overview" class="overview" aria-labelledby="overview-title">
      <header class="overview-head">
        <p class="kicker">PROJECT OVERVIEW</p>
        <h2 id="overview-title">项目方案</h2>
        <p class="overview-lede">
          面向重点湖库蓝藻水华监测预警，业务链贯通数据、机理、研判与复盘；当前阶段以统一演示数据完成全链路联调。
        </p>
      </header>

      <ol class="chain" aria-label="业务链路">
        <li v-for="(step, i) in chain" :key="step" class="chain-step">
          <span class="chain-no" aria-hidden="true">{{ String(i + 1).padStart(2, '0') }}</span>{{ step }}
          <span v-if="i < chain.length - 1" class="chain-arrow" aria-hidden="true">→</span>
        </li>
      </ol>

      <div class="bounds">
        <article class="bound bound-have">
          <h3>已有</h3>
          <p>清洗数据产物 · 统一演示接口 · 页面联动基础</p>
        </article>
        <article class="bound bound-doing">
          <h3>进行中</h3>
          <p>正式机理与 AI 算法接入</p>
        </article>
        <article class="bound bound-limit">
          <h3>受限</h3>
          <p>30—90 天正式预测能力尚未建成</p>
        </article>
      </div>
    </section>

    <!-- ============ 页尾 ============ -->
    <footer class="home-foot">
      <div class="foot-brand">
        <strong>{{ identity.lakeName }} · 蓝藻水华监测预警系统</strong>
        <span>A23 · 演示联调</span>
      </div>
      <p class="foot-identity">
        数据模式 {{ identity.dataMode }} · {{ identity.datasetVersionId }} / {{ identity.predictionRunId }} · {{ identity.claimBoundary }}
      </p>
      <p class="foot-bound">{{ identity.claimNote }}</p>
    </footer>
  </main>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { pointData, regionSummary } from '../data/points.js'
import { TAIHU_OUTLINE, taihuZonePos } from '../data/taihuOutline.js'
import { dataIdentity as identity } from '../data/dataIdentity.js'
import DataModeBadge from '../components/common/DataModeBadge.vue'

const router = useRouter()

// 分区编号为界面展示用简称，稳定对象 ID 仍以 points.js 为准
const CODES = {
  northwest_hotspot: 'NW-01',
  central_lake: 'CN-02',
  river_inlet: 'RI-03',
  southeast_station: 'SE-04',
  water_intake: 'WI-05',
  south_channel: 'SC-06'
}

const zones = Object.values(pointData).map((p) => ({
  ...p,
  code: CODES[p.id] || '',
  // 真实轮廓上的展示定位优先；pointPositions 供站点页等业务使用，不做改动
  pos: taihuZonePos[p.id] || { top: '50%', left: '50%' }
}))

const facts = [
  { label: '数据模式', value: identity.dataMode, note: '统一演示数据联调环境' },
  { label: '业务对象', value: '6 个演示分区', note: '非真实监测站' },
  { label: '预测能力', value: '1—15 天演示档位', note: 't1 / t3 / t7 / t15' },
  { label: '长期能力', value: '30 天仅模拟预演', note: '正式 30—90 天预测未接入' }
]

const entries = [
  {
    no: '01 · P01',
    to: '/cockpit',
    title: '综合驾驶舱',
    desc: '全湖态势总览：风险分区、演示事件流与预警信息一屏研判。',
    mode: 'SIMULATED · DEMO-OBS-V1'
  },
  {
    no: '02 · P03',
    to: '/stations',
    title: '监测站点研判',
    desc: '点位地图 + 详情卡 + 藻密度时序 + 因子贡献逐层下钻。',
    mode: 'SIMULATED · DEMO-OBS-V1'
  },
  {
    no: '03 · P07',
    to: '/heatmap',
    title: '风险地图与时空推演',
    desc: '风险热力场与 1—30 天时空档位推演，30 天仅模拟预演。',
    mode: 'SIMULATED · DEMO-PRED-V1'
  },
  {
    no: '04',
    to: '/history',
    title: '历史事件与处置复盘',
    desc: '事件链回放与处置记录复盘，沉淀研判经验。',
    mode: 'SIMULATED · 演示事件流'
  }
]

const chain = ['多源数据', '数据质量', '机理与AI预测', '风险研判', '时空预演', '历史复盘']

function goZone(id) {
  router.push({ path: '/stations', query: { p: id } })
}
</script>

<style scoped>
.home {
  gap: 40px;
  padding-bottom: 48px;
}

.kicker {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.18em;
}
.kicker::before {
  content: "";
  width: 26px;
  height: 1px;
  background: var(--color-primary);
}

/* ============ 首屏 ============ */
.hero {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 24px;
  align-items: stretch;
  padding-top: 8px;
}

.hero-copy {
  grid-column: span 5;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 16px;
  min-width: 0;
}

.title {
  display: grid;
  gap: 2px;
  font-family: var(--font-display);
  font-size: clamp(40px, 4.6vw, 64px);
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.04;
  color: var(--text-primary);
}
.title-accent { color: var(--color-primary); }

.lede {
  max-width: 40rem;
  font-size: 15px;
  line-height: 1.85;
  color: var(--text-secondary);
}

.boundary {
  padding: 10px 14px;
  border-left: 3px solid color-mix(in srgb, var(--risk-medium) 60%, transparent);
  border-radius: var(--radius-item);
  background: color-mix(in srgb, var(--risk-medium) 8%, transparent);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.boundary strong {
  margin-right: 6px;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 48px;
  padding: 0 22px;
  border: 1px solid transparent;
  border-radius: var(--radius-item);
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.btn:hover { transform: translateY(-2px); }
.btn:active { transform: translateY(0); }
.btn-primary {
  background: var(--color-primary);
  color: var(--color-primary-ink);
}
.btn-primary:hover { filter: brightness(1.08); }
.btn-ghost {
  border-color: var(--border-strong);
  background: var(--surface-panel-soft);
  color: var(--text-secondary);
}
.btn-ghost:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.btn-arrow { transition: transform 0.15s ease; }
.btn-primary:hover .btn-arrow { transform: translateX(3px); }

.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 8px 0 0;
}
.fact {
  display: grid;
  gap: 2px;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-item);
  background: var(--surface-panel-soft);
}
.fact dt {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}
.fact dd {
  margin: 0;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.fact span {
  font-size: 11.5px;
  color: var(--text-muted);
}

/* ============ 太湖缩略态势 ============ */
.lake-panel {
  grid-column: span 7;
  display: flex;
  flex-direction: column;
  margin: 0;
  min-width: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
}

.lake-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.lake-head-copy {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.lake-head-copy strong {
  font-size: 14px;
  color: var(--text-primary);
}
.lake-head-copy span {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

.lake-canvas {
  position: relative;
  flex: 1;
  min-height: 400px;
  background-image:
    linear-gradient(color-mix(in srgb, var(--border-subtle) 55%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--border-subtle) 55%, transparent) 1px, transparent 1px);
  background-size: 44px 44px;
}
.lake-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.lake-body {
  fill: color-mix(in srgb, var(--color-primary) 15%, var(--surface-page));
  stroke: var(--border-strong);
  stroke-width: 1.4;
}

/* 分区按钮：44×44 触控目标，风险色 + 文字双表达 */
.zone {
  position: absolute;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  transform: translate(-50%, -50%);
}
.zone--high { --rc: var(--risk-critical); }
.zone--mid { --rc: var(--risk-high); }
.zone--low { --rc: var(--risk-low); }
.zone-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--rc);
  border: 2px solid var(--surface-page);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--rc) 28%, transparent);
  transition: transform 0.15s ease;
}
.zone:hover .zone-dot,
.zone:focus-visible .zone-dot { transform: scale(1.25); }
.zone-tip {
  position: absolute;
  bottom: calc(100% + 2px);
  left: 50%;
  z-index: 3;
  display: grid;
  gap: 1px;
  padding: 6px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-item);
  background: var(--surface-panel-raised);
  box-shadow: var(--shadow-sm);
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transform: translateX(-50%) translateY(2px);
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.zone:hover .zone-tip,
.zone:focus-visible .zone-tip {
  opacity: 1;
  transform: translateX(-50%);
}
.zone-tip strong {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-primary);
}
.zone-tip em {
  font-style: normal;
  font-size: 11px;
  color: var(--rc);
}

.lake-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding: 10px 16px;
  border-top: 1px solid var(--border-subtle);
}
.lg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
}
.lg i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}
.lg--high { color: var(--risk-critical); }
.lg--mid { color: var(--risk-high); }
.lg--low { color: var(--risk-low); }
.lg-attr {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
  text-decoration: none;
  border-bottom: 1px dashed var(--border-subtle);
}
.lg-attr:hover { color: var(--color-primary); border-bottom-color: var(--color-primary); }

/* ============ 四个核心入口 ============ */
.entries {
  display: grid;
  gap: 16px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}
.entries-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.entries-head h2 {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}
.entries-head p {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.entry-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}
.entry-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel);
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.entry-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
}
.entry-card:active { transform: translateY(0); }
.entry-no {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--color-primary);
}
.entry-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
.entry-desc {
  flex: 1;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.entry-mode {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}
.entry-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-primary);
}
.entry-cta i {
  font-style: normal;
  transition: transform 0.15s ease;
}
.entry-card:hover .entry-cta i { transform: translateX(4px); }

/* ============ 项目方案 ============ */
.overview {
  display: grid;
  gap: 20px;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
  scroll-margin-top: 114px;
}
.overview-head {
  display: grid;
  gap: 8px;
}
.overview-head h2 {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}
.overview-lede {
  max-width: 60rem;
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--text-secondary);
}

.chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.chain-step {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-panel-soft);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.chain-no {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-primary);
}
.chain-arrow {
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.bounds {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.bound {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-panel-soft);
}
.bound h3 {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.14em;
}
.bound p {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}
.bound-have h3 { color: var(--color-secondary); }
.bound-doing h3 { color: var(--risk-medium); }
.bound-limit h3 { color: var(--risk-critical); }

/* ============ 页尾 ============ */
.home-foot {
  display: grid;
  gap: 6px;
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle);
}
.foot-brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
.foot-brand strong {
  font-size: 13.5px;
  color: var(--text-primary);
}
.foot-brand span {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}
.foot-identity {
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}
.foot-bound {
  max-width: 72rem;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-muted);
}

/* ============ 响应式 ============ */
@media (max-width: 1180px) {
  .hero-copy,
  .lake-panel { grid-column: span 12; }
  .hero-copy { max-width: 820px; }
  .entry-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .home { gap: 28px; }
  .facts { grid-template-columns: 1fr; }
  .lake-canvas { min-height: 340px; }
  .entry-grid { grid-template-columns: 1fr; }
  .bounds { grid-template-columns: 1fr; }
  .actions .btn { width: 100%; }
}
@media (hover: none) {
  .zone-tip {
    opacity: 1;
    transform: translateX(-50%);
  }
}
</style>
