<template>
  <main class="shell home">
    <!-- ============ 首屏：左 5 列信息 / 右 7 列太湖缩略态势 ============ -->
    <section class="hero" aria-labelledby="home-title">
      <div class="hero-copy">
        <h1 id="home-title" class="title">
          <span>蓝藻水华</span>
          <span class="title-accent">监测预警</span>
        </h1>
        <p class="lede">
          融合多源数据、机理模型与人工智能，支持全湖态势研判、站点下钻、时空推演与历史复盘。
        </p>
        <div class="actions">
          <RouterLink class="btn btn-primary" to="/cockpit">
            进入综合驾驶舱<span class="btn-arrow" aria-hidden="true">→</span>
          </RouterLink>
        </div>
      </div>

      <figure class="lake-panel">
        <figcaption class="lake-head">
          <div class="lake-head-copy">
            <strong>{{ identity.lakeName }} · 情景分区态势</strong>
            <span>{{ apiObsVersion }} · 非真实站点 · 点击分区进入站点研判</span>
          </div>
          <DataModeBadge mode="simulated" :label="identity.dataMode" />
        </figcaption>

        <div class="lake-canvas" role="group" aria-label="太湖情景分区缩略态势图，六个分区可点击下钻">
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
            :aria-label="`情景分区 ${z.code} ${z.name}，${z.risk}，点击进入站点研判`"
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
          <span class="lg lg--high"><i aria-hidden="true"></i>红色预警 × {{ zoneRiskCounts.high }}</span>
          <span class="lg lg--mid"><i aria-hidden="true"></i>橙色关注 × {{ zoneRiskCounts.mid }}</span>
          <span class="lg lg--low"><i aria-hidden="true"></i>绿色稳定 × {{ zoneRiskCounts.low }}</span>
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
      </header>
      <div class="entry-grid">
        <RouterLink v-for="e in entries" :key="e.to" class="entry-card" :to="e.to">
          <span class="entry-title">{{ e.title }}</span>
          <span class="entry-desc">{{ e.desc }}</span>
          <span class="entry-cta">进入 <i aria-hidden="true">→</i></span>
        </RouterLink>
      </div>
    </section>

  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { pointData, regionSummary } from '../data/points.js'
import { TAIHU_OUTLINE, taihuZonePos } from '../data/taihuOutline.js'
import { dataIdentity as identity } from '../data/dataIdentity.js'
import { getSystemCapabilitiesEnvelope, getSpatialEntities } from '../services/api.js'
import DataModeBadge from '../components/common/DataModeBadge.vue'

const router = useRouter()

// ---------- 后端契约接入：数据集摘要 meta 与情景分区（观察类） ----------
// meta 优先驱动身份展示，事实源 dataIdentity 仅作请求失败/首帧前的明确 fallback。
const sysMeta = ref(null) // 最近一次成功响应的 meta（六键）
const entities = ref([])

async function loadCapabilities() {
  try {
    const [capsRes, zoneRes] = await Promise.all([
      getSystemCapabilitiesEnvelope(),
      getSpatialEntities('demo_zone')
    ])
    entities.value = Array.isArray(zoneRes.data) ? zoneRes.data : []
    // 统一以能力接口的 meta 为首页身份口径（观察类响应 meta 一致）
    sysMeta.value = capsRes.meta && Object.keys(capsRes.meta).length ? capsRes.meta : null
  } catch {
    // 静默失败：分区回退静态常量，身份字段回退 dataIdentity
  }
}
onMounted(loadCapabilities)

// ---------- meta 优先的身份展示（fallback = 事实源） ----------
const apiObsVersion = computed(() => sysMeta.value?.dataset_version || identity.datasetVersionId)

// 分区编号为界面展示用简称，稳定对象 ID 仍以接口/points.js 为准
const CODES = {
  northwest_hotspot: 'NW-01',
  central_lake: 'CN-02',
  river_inlet: 'RI-03',
  southeast_station: 'SE-04',
  water_intake: 'WI-05',
  south_channel: 'SC-06'
}

// 湖面分区：接口分区优先（位置/风险/名称来自后端），失败或为空时回退静态常量
const apiZones = computed(() => entities.value.map((e) => ({
  id: e.id,
  code: e.short || CODES[e.id] || '',
  name: e.display_name || '',
  riskClass: e.risk_hint || 'low',
  risk: { high: '红色预警', mid: '橙色关注', low: '绿色稳定' }[e.risk_hint] || '绿色稳定',
  pos: { top: e.position?.top || '50%', left: e.position?.left || '50%' }
})))
const staticZones = Object.values(pointData).map((p) => ({
  ...p,
  code: CODES[p.id] || '',
  // 真实轮廓上的展示定位优先；pointPositions 供站点页等业务使用，不做改动
  pos: taihuZonePos[p.id] || { top: '50%', left: '50%' }
}))
const zones = computed(() => (apiZones.value.length ? apiZones.value : staticZones))

// 分区风险统计：接口 risk_hint 优先，回退静态 regionSummary
const zoneRiskCounts = computed(() => {
  if (!apiZones.value.length) return regionSummary.riskCounts
  const counts = { high: 0, mid: 0, low: 0 }
  for (const z of apiZones.value) counts[z.riskClass] = (counts[z.riskClass] || 0) + 1
  return counts
})

const entries = [
  {
    to: '/cockpit',
    title: '综合驾驶舱',
    desc: '全湖态势总览：风险分区、情景事件流与预警信息一屏研判。'
  },
  {
    to: '/stations',
    title: '监测站点研判',
    desc: 'MEE 国控实时站点：最新观测、缺测披露、数据质量与真实趋势。'
  },
  {
    to: '/wallboard',
    title: '实时大屏',
    desc: '全站国控断面实时状态墙：抓取链路、活跃站点与缺测率一屏总览。'
  },
  {
    to: '/heatmap',
    title: '卫星遥感与时空推演',
    desc: 'THQBCA-V2 年度叶绿素 a / 漂浮藻类遥感影像，支持跨年对比与实时站点叠加。'
  },
  {
    to: '/history',
    title: '实时观测历史复盘',
    desc: 'MEE 实时快照历史回放：按快照查看全站观测状态、达标构成与蓝藻筛查预警。'
  }
]

function goZone(id) {
  router.push({ path: '/stations', query: { p: id } })
}
</script>

<style scoped>
.home {
  gap: 40px;
  padding-bottom: 48px;
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
  white-space: normal;
  /* 触靠右/左边缘的分区提示不越出画布（390px 小屏亦不产生横向溢出） */
  max-width: min(46vw, 200px);
  overflow-wrap: anywhere;
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
/* 小屏触摸目标：署名链接点击区提到 ≥44px 高 */
@media (max-width: 640px) {
  .lg-attr {
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    padding: 0 6px;
  }
}

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

/* ============ 响应式 ============ */
@media (max-width: 1180px) {
  .hero-copy,
  .lake-panel { grid-column: span 12; }
  .hero-copy { max-width: 820px; }
  .entry-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .home { gap: 28px; }
  .lake-canvas { min-height: 340px; }
  .entry-grid { grid-template-columns: 1fr; }
  .actions .btn { width: 100%; }
}
@media (hover: none) {
  .zone-tip {
    opacity: 1;
    transform: translateX(-50%);
  }
}
</style>
