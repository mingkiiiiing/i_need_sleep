<template>
  <main class="shell home">
    <!-- ============ 首屏：左 5 列信息 / 右 7 列太湖实时态势（粒子流场 + 真实站点） ============ -->
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
            <strong>{{ identity.lakeName }}流域 · 实时站点态势</strong>
            <span>{{ heroSub }}</span>
          </div>
          <DataModeBadge mode="observed" label="实时观测" />
        </figcaption>

        <div class="lake-canvas" role="group" aria-label="太湖湖体粒子基因动效：粒子流动并动态连线成网络，预警站点高亮可点击">
          <!-- 真实太湖轮廓（OSM relation 1126533，见 data/taihuOutline.js），evenodd 渲染岛屿镂空。
               viewBox 以负值外扩至全流域范围（-PAD.l, -PAD.t），路径坐标原样使用，
               与粒子画布、站点投影共用同一坐标系 -->
          <svg class="lake-svg" :viewBox="`-${PAD.l} -${PAD.t} ${VB_W} ${VB_H}`" preserveAspectRatio="none" aria-hidden="true">
            <path class="lake-body" fill-rule="evenodd" :d="TAIHU_OUTLINE.path" />
          </svg>

          <!-- 水体粒子基因流场：纯装饰动效，对读屏隐藏 -->
          <canvas ref="flowEl" class="flow-canvas" aria-hidden="true"></canvas>

          <button
            v-for="s in warnDots"
            :key="s.id"
            type="button"
            class="stn"
            :class="`stn--${s.band}`"
            :style="{ left: s.left, top: s.top }"
            :aria-label="`预警站点 ${s.name}，${s.tip}，点击进入站点研判`"
            @click="goStation(s.id)"
          >
            <span class="stn-dot" aria-hidden="true"></span>
            <span class="stn-tip">
              <strong>{{ s.name }}</strong>
              <em>{{ s.tip }}</em>
            </span>
          </button>
        </div>

        <div class="lake-foot" aria-label="实时蓝藻筛查统计">
          <template v-if="rtState === 'ok'">
            <span class="lg lg--low">正常 × {{ stationStats.normal }}</span>
            <span class="lg lg--mid">轻度 × {{ stationStats.light }}</span>
            <span class="lg lg--high">中度 × {{ stationStats.moderate }}</span>
            <span class="lg lg--none">未报数 × {{ stationStats.none }}</span>
          </template>
          <span v-else-if="rtState === 'loading'" class="lg lg--none">正在加载实时站点…</span>
          <span v-else class="lg lg--none">
            实时站点加载失败
            <button type="button" class="rt-retry" @click="loadSummary(true)">重试</button>
          </span>
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { TAIHU_OUTLINE } from '../data/taihuOutline.js'
import { dataIdentity as identity } from '../data/dataIdentity.js'
import { fetchRealtimeSummary } from '../services/realtime.js'
import DataModeBadge from '../components/common/DataModeBadge.vue'

const router = useRouter()

// ---------- 实时观测轨：全湖站点态势（与驾驶舱共用 realtime 服务与 60s 缓存） ----------
const summary = ref(null)
const rtState = ref('loading')
let refreshTimer = null

async function loadSummary(force = false) {
  if (force) rtState.value = 'loading'
  try {
    summary.value = await fetchRealtimeSummary({ force })
    rtState.value = 'ok'
  } catch {
    // 首页为着陆页：失败保持装饰性粒子动效，仅站点层降级并给出重试
    rtState.value = 'error'
  }
}

onMounted(() => {
  loadSummary()
  refreshTimer = setInterval(() => loadSummary(true), 60_000)
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

const rtVersion = computed(() => summary.value?.dataset_version || 'MEE-RT-V1')

// 站点在缩略图上的投影：taihuOutline.js 的路径 bbox（viewBox 坐标）对应真实地理 bbox
// （来源 OSM relation 1126533，equirectangular，见 data/taihuOutline.js 头注）。
// 视野扩为全流域，使全部可定位站点（summary.markers）都能落在画布内。
const PATH_BBOX = { x0: 26.0, y0: 26.0, w: 359.8, h: 348.0 }
const GEO = { lon0: 119.876, dlon: 0.727, lat1: 31.549, dlat: 0.621 }
const VB_PER_LON = PATH_BBOX.w / GEO.dlon // ≈494.9 viewBox单位/度
const VB_PER_LAT = PATH_BBOX.h / GEO.dlat // ≈560.4 viewBox单位/度

function projectStation(lon, lat) {
  const x = PATH_BBOX.x0 + ((lon - GEO.lon0) / GEO.dlon) * PATH_BBOX.w
  const y = PATH_BBOX.y0 + ((GEO.lat1 - lat) / GEO.dlat) * PATH_BBOX.h
  return { x, y }
}

// 湖体主视野：画布四周仅留少量呼吸边距，让太湖成为绝对主体
const PAD = { l: 64, r: 64, t: 64, b: 64 }
const VB_W = 520 + PAD.l + PAD.r
const VB_H = 400 + PAD.t + PAD.b

// chla 筛查口径与驾驶舱一致（<10 正常 / 10–25 轻度 / ≥25 中度 / 未报数）
function bandOf(chla) {
  if (chla == null) return 'none'
  if (chla >= 25) return 'moderate'
  if (chla >= 10) return 'light'
  return 'normal'
}
const BAND_TEXT = { normal: '正常', light: '轻度关注', moderate: '中度预警', none: '未报数' }

// 站点统计口径：对全部 79 站按 chla 筛查分档——预警数以 summary.warnings 为准
// （含未入库坐标的预警站），正常数来自有坐标 marker，其余计为未报数
const stationStats = computed(() => {
  const s = summary.value
  const counts = { normal: 0, light: 0, moderate: 0, none: 0 }
  if (!s) return counts
  for (const m of s.markers || []) {
    if (m.lat == null || m.lon == null) continue
    const band = bandOf(m.chla)
    if (band !== 'none') counts[band] += 1
  }
  for (const w of s.warnings || []) {
    counts[w.band === 'moderate' ? 'moderate' : 'light'] += 1
  }
  counts.none = Math.max(0, (s.station_total ?? 0) - counts.normal - counts.light - counts.moderate)
  return counts
})

// 湖面上只保留蓝藻筛查预警站（通常 0–3 个），避免满屏圆点喧宾夺主
const warnDots = computed(() => {
  const out = []
  for (const m of summary.value?.markers || []) {
    if (m.lat == null || m.lon == null) continue
    const band = bandOf(m.chla)
    if (band !== 'light' && band !== 'moderate') continue
    const { x, y } = projectStation(m.lon, m.lat)
    out.push({
      id: m.id,
      name: m.name || m.id,
      band,
      tip: `Chl-a ${m.chla} μg/L · ${BAND_TEXT[band]}`,
      left: `${(((x + PAD.l) / VB_W) * 100).toFixed(2)}%`,
      top: `${(((y + PAD.t) / VB_H) * 100).toFixed(2)}%`
    })
  }
  return out
})

function goStation(id) {
  router.push({ path: '/stations', query: { p: id } })
}

// 首屏副标题：如实披露“已定位/总数”口径（79 站中 31 站注册无坐标、8 站坐标可疑未入库 markers）
const heroSub = computed(() => {
  if (rtState.value === 'ok') {
    const total = summary.value?.station_total
    const mapped = (summary.value?.markers || []).filter((m) => m.lat != null && m.lon != null).length
    const warns = stationStats.value.light + stationStats.value.moderate
    return `${rtVersion.value} · 国控站点已定位 ${mapped}/${total ?? '—'} · 蓝藻筛查预警 ${warns} 站`
  }
  if (rtState.value === 'loading') return `${rtVersion.value} · 正在加载实时站点…`
  return `${rtVersion.value} · 实时站点加载失败 · 可在图例区重试`
})

// ---------- 湖体粒子流场（Canvas 2D，物理在 520×400 viewBox 空间进行） ----------
const flowEl = ref(null)
const N_PARTICLES = 110
const TRAIL_MS = 1100
const SPEED = 40 // viewBox 单位/秒
const LINK_DIST = 66 // 粒子“基因连线”的判定距离（viewBox 单位）
const LINK_MAX_PER_PARTICLE = 4 // 每个粒子最多连线数，防止连成毛球
const particles = []
let rafId = 0
let intervalId = 0
let watchdogId = 0
let lastDrawAt = 0
let resizeObserver = null
let ctx = null
let lakePath = null
let lastFrame = 0
let running = false

// 主题色只读一次（主题切换后下次进入页面生效，装饰动效可接受）
function themePrimary() {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim()
  return v || '#39c5bb'
}

function resizeCanvas() {
  const el = flowEl.value
  if (!el || !ctx) return
  const dpr = window.devicePixelRatio || 1
  const w = el.clientWidth
  const h = el.clientHeight
  if (!w || !h) return
  el.width = Math.round(w * dpr)
  el.height = Math.round(h * dpr)
}

// viewBox(520×400) → 画布（外扩 PAD 后拉伸铺满），与 SVG 同一坐标系
function applyViewTransform() {
  const el = flowEl.value
  const dpr = window.devicePixelRatio || 1
  const sx = (el.clientWidth * dpr) / VB_W
  const sy = (el.clientHeight * dpr) / VB_H
  ctx.setTransform(sx, 0, 0, sy, PAD.l * sx, PAD.t * sy)
}

function insideLake(x, y) {
  ctx.save()
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  // evenodd 与 SVG fill-rule 一致，保证岛屿镂空处不生成粒子
  const ok = ctx.isPointInPath(lakePath, x, y, 'evenodd')
  ctx.restore()
  return ok
}

function respawn(p, warm = 0) {
  let x = 260, y = 200
  for (let i = 0; i < 80; i++) {
    x = Math.random() * 520
    y = Math.random() * 400
    if (insideLake(x, y)) break
  }
  p.x = x
  p.y = y
  p.trail = [[x, y, performance.now()]]
  // 寿命短于贯穿全湖所需时间：重生点近似均匀，避免粒子被主流“搬运”到下风口造成密度不均
  p.life = 3 + Math.random() * 4
  // 预热：静态帧（reduced-motion）下让轨迹先长出来
  for (let i = 0; i < warm; i++) stepParticle(p, 1 / 30)
}

// 时间缓变的流向场：以平缓的东向主流为主，叠加长波摆动，粒子拉出丝滑的“湖流”
function flowAngle(x, y, t) {
  return (
    -0.12 +
    Math.sin(y * 0.011 + t * 0.28) * 0.5 +
    Math.sin(x * 0.007 - t * 0.2 + y * 0.005) * 0.34
  )
}

function stepParticle(p, dt) {
  const t = performance.now() / 1000
  const ang = flowAngle(p.x, p.y, t)
  p.x += Math.cos(ang) * SPEED * dt
  p.y += Math.sin(ang) * SPEED * dt
  p.life -= dt
  const now = performance.now()
  p.trail.push([p.x, p.y, now])
  while (p.trail.length && (now - p.trail[0][2] > TRAIL_MS || p.trail.length > 70)) {
    p.trail.shift()
  }
  if (p.life <= 0 || !insideLake(p.x, p.y)) respawn(p)
}

function drawParticles(color) {
  applyViewTransform()
  ctx.clearRect(-PAD.l, -PAD.t, VB_W, VB_H)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  // ---- 基因连线：邻近粒子按当前头部位置两两相连，透明度随距离衰减，
  //      每个粒子最多 LINK_MAX_PER_PARTICLE 条，保持“基因链”般的疏朗网络 ----
  const heads = particles.map((p) => (p.trail.length ? p.trail[p.trail.length - 1] : null))
  const linkSegs = [[], [], [], []] // 按距离由近到远分 4 档，近线更亮
  const linkCount = new Array(particles.length).fill(0)
  for (let i = 0; i < heads.length; i++) {
    if (!heads[i] || linkCount[i] >= LINK_MAX_PER_PARTICLE) continue
    for (let j = i + 1; j < heads.length; j++) {
      if (!heads[j] || linkCount[j] >= LINK_MAX_PER_PARTICLE) continue
      const dx = heads[i][0] - heads[j][0]
      const dy = heads[i][1] - heads[j][1]
      if (dx > LINK_DIST || dx < -LINK_DIST || dy > LINK_DIST || dy < -LINK_DIST) continue
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d > LINK_DIST) continue
      linkSegs[Math.min(3, Math.floor((d / LINK_DIST) * 4))].push(heads[i], heads[j])
      linkCount[i]++
      linkCount[j]++
      if (linkCount[i] >= LINK_MAX_PER_PARTICLE) break
    }
  }
  const LINK_ALPHAS = [0.5, 0.32, 0.17, 0.08]
  ctx.strokeStyle = color
  ctx.lineWidth = 1.15
  for (let b = 0; b < 4; b++) {
    if (!linkSegs[b].length) continue
    ctx.globalAlpha = LINK_ALPHAS[b]
    ctx.beginPath()
    for (let k = 0; k < linkSegs[b].length; k += 2) {
      ctx.moveTo(linkSegs[b][k][0], linkSegs[b][k][1])
      ctx.lineTo(linkSegs[b][k + 1][0], linkSegs[b][k + 1][1])
    }
    ctx.stroke()
  }
  ctx.globalAlpha = 1

  // ---- 轨迹：按新旧分三档透明度批量描边，避免逐段 stroke 的开销 ----
  const buckets = [
    { from: 0, to: 1 / 3, alpha: 0.1, width: 1.2 },
    { from: 1 / 3, to: 2 / 3, alpha: 0.22, width: 1.5 },
    { from: 2 / 3, to: 1, alpha: 0.45, width: 1.85 }
  ]
  for (const b of buckets) {
    ctx.strokeStyle = color
    ctx.globalAlpha = b.alpha
    ctx.lineWidth = b.width
    ctx.beginPath()
    for (const p of particles) {
      const n = p.trail.length
      if (n < 2) continue
      const start = Math.max(1, Math.floor(n * b.from))
      const end = Math.max(start + 1, Math.ceil(n * b.to))
      ctx.moveTo(p.trail[start - 1][0], p.trail[start - 1][1])
      for (let i = start; i < Math.min(end, n); i++) {
        ctx.lineTo(p.trail[i][0], p.trail[i][1])
      }
    }
    ctx.stroke()
  }
  // 粒子头部亮点
  ctx.globalAlpha = 0.75
  ctx.fillStyle = color
  for (const p of particles) {
    const n = p.trail.length
    if (!n) continue
    ctx.beginPath()
    ctx.arc(p.trail[n - 1][0], p.trail[n - 1][1], 1.5, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1
}

function frame(now) {
  if (!running) return
  const dt = Math.min((now - lastFrame) / 1000 || 0, 0.05)
  lastFrame = now
  if (document.hidden) return
  for (const p of particles) stepParticle(p, dt)
  drawParticles(themePrimary())
  lastDrawAt = performance.now()
}

function tick(now) {
  if (!running) return
  // rAF 正常流动时，停掉定时器退化路径，避免双倍速率
  if (intervalId) {
    clearInterval(intervalId)
    intervalId = 0
  }
  frame(now)
  rafId = requestAnimationFrame(tick)
}

function startFlow() {
  const el = flowEl.value
  if (!el) return
  ctx = el.getContext('2d')
  lakePath = new Path2D(TAIHU_OUTLINE.path)
  resizeCanvas()
  resizeObserver = new ResizeObserver(resizeCanvas)
  resizeObserver.observe(el)

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const warmSteps = reduced ? 260 : 40 // 首帧先长出短轨迹，避免空白起步
  for (let i = 0; i < N_PARTICLES; i++) {
    const p = { x: 0, y: 0, life: 0, trail: [] }
    respawn(p, warmSteps)
    particles.push(p)
  }
  drawParticles(themePrimary())
  if (reduced) return // 静态帧即可，不启动动画
  running = true
  lastFrame = performance.now()
  lastDrawAt = performance.now()
  rafId = requestAnimationFrame(tick)
  // 某些嵌入式 WebView 的 rAF 只在首帧派发甚至完全不派发：周期检查，
  // 超过 1.5s 没有实际绘制就切换为定时器驱动；rAF 恢复后 tick() 会收回定时器
  watchdogId = setInterval(() => {
    if (running && !intervalId && performance.now() - lastDrawAt > 1500) {
      intervalId = setInterval(() => frame(performance.now()), 33)
    }
  }, 1000)
}

function stopFlow() {
  running = false
  if (rafId) cancelAnimationFrame(rafId)
  if (intervalId) clearInterval(intervalId)
  if (watchdogId) clearInterval(watchdogId)
  if (resizeObserver) resizeObserver.disconnect()
}

onMounted(startFlow)
onBeforeUnmount(stopFlow)

// ---------- 核心入口 ----------
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

/* ============ 太湖实时态势 ============ */
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
  overflow: hidden;
  background-image:
    linear-gradient(color-mix(in srgb, var(--border-subtle) 55%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--border-subtle) 55%, transparent) 1px, transparent 1px);
  background-size: 44px 44px;
}
.lake-svg,
.flow-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.flow-canvas { pointer-events: none; }
.lake-body {
  fill: color-mix(in srgb, var(--color-primary) 15%, var(--surface-page));
  stroke: var(--border-strong);
  stroke-width: 1.4;
}

/* 站点按钮：风险色圆点 + 悬停文字，同驾驶舱 chla 筛查口径 */
.stn {
  position: absolute;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  transform: translate(-50%, -50%);
}
.stn--normal { --rc: #5fd6a4; }
.stn--light { --rc: #f5b45d; }
.stn--moderate { --rc: #ff6b6b; }
.stn--none { --rc: #7d93a8; }
.stn-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--rc);
  border: 2px solid var(--surface-page);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--rc) 30%, transparent);
  transition: transform 0.15s ease;
}
.stn:hover .stn-dot,
.stn:focus-visible .stn-dot { transform: scale(1.3); }
.stn-tip {
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
  max-width: min(46vw, 220px);
  overflow-wrap: anywhere;
  opacity: 0;
  pointer-events: none;
  transform: translateX(-50%) translateY(2px);
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.stn:hover .stn-tip,
.stn:focus-visible .stn-tip {
  opacity: 1;
  transform: translateX(-50%);
}
.stn-tip strong {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-primary);
}
.stn-tip em {
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
.lg--low, .lg--normal { color: #5fd6a4; }
.lg--mid, .lg--light { color: #f5b45d; }
.lg--high, .lg--moderate { color: #ff6b6b; }
.lg--none { color: #7d93a8; }
.rt-retry {
  appearance: none;
  border: 1px solid color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--text-primary);
  border-radius: 999px;
  min-height: 24px;
  padding: 1px 10px;
  font-size: 11px;
  cursor: pointer;
}
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
  .stn .stn-tip { display: none; }
}
</style>
