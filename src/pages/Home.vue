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
          <RouterLink class="btn btn-ghost" to="/alerts">
            <svg class="btn-bell" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M15 8.6a5 5 0 0 0-10 0c0 5.8-2.5 7.4-2.5 7.4h15S15 14.4 15 8.6" />
              <path d="M11.3 18.9a1.7 1.7 0 0 1-2.6 0" />
              <path d="M10 3.6V2" />
            </svg>
            预警与应急预案中心
          </RouterLink>
        </div>
      </div>

      <figure class="lake-panel">
        <figcaption class="lake-head">
          <div class="lake-head-copy">
            <strong>{{ identity.lakeName }}流域 · 实时站点态势</strong>
          </div>
          <DataModeBadge mode="observed" label="实时观测" />
        </figcaption>

        <div
          class="lake-canvas"
          role="group"
          aria-label="太湖流域实时监测可视化：全画布粒子网络缓慢漂移并彼此连线，鼠标靠近时粒子散开，监测站点可点击"
          @mousemove="onCanvasMove"
          @mouseleave="onCanvasLeave"
        >
          <!-- 水体粒子基因流场 + 中央 DNA 双螺旋：纯装饰动效，对读屏隐藏 -->
          <canvas ref="flowEl" class="flow-canvas" aria-hidden="true"></canvas>

          <button
            v-for="s in stationDots"
            :key="s.id"
            type="button"
            class="stn"
            :style="{ left: s.left, top: s.top, '--rc': BAND_COLORS[s.band] }"
            :aria-label="`站点 ${s.name}，${s.tip}，点击进入站点研判`"
            @mouseenter="hoveredStation = s.id"
            @focus="hoveredStation = s.id"
            @mouseleave="hoveredStation = hoveredStation === s.id ? null : hoveredStation"
            @blur="hoveredStation = null"
            @click="goStation(s.id)"
          >
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
          </template>
          <span v-else-if="rtState === 'loading'" class="lg lg--none">正在加载实时站点…</span>
          <span v-else class="lg lg--none">
            实时站点加载失败
            <button type="button" class="rt-retry" @click="loadSummary(true)">重试</button>
          </span>
        </div>
      </figure>
    </section>

    <!-- ============ 第二屏：六个核心入口 ============ -->
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

// 湖体主视野 + 全流域大部分站点：视野 lon 119.35–121.15 / lat 30.55–31.95，
// 33/48 个可定位站点入画，湖体粒子团占画布约 40%×44%，居中
const PAD = { l: 235, r: 137, t: 199, b: 186 }
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

// 站点统计口径：有坐标站按 chla 筛查分档；warnings 与 markers 是包含关系，
// 只补无坐标的预警站，不去重会把同一站计两次
const stationStats = computed(() => {
  const s = summary.value
  const counts = { normal: 0, light: 0, moderate: 0, none: 0 }
  if (!s) return counts
  const located = new Set()
  for (const m of s.markers || []) {
    if (m.lat == null || m.lon == null) continue
    located.add(m.id)
    const band = bandOf(m.chla)
    if (band !== 'none') counts[band] += 1
  }
  for (const w of s.warnings || []) {
    if (located.has(w.station_id)) continue
    counts[w.band === 'moderate' ? 'moderate' : 'light'] += 1
  }
  counts.none = Math.max(0, (s.station_total ?? 0) - counts.normal - counts.light - counts.moderate)
  return counts
})

// 湖面上展示大部分监测点（视野内全部可定位站）：可见形态由 canvas 绘制为
// 与粒子同风格的发光节点，DOM 按钮仅作透明热区（悬停提示 / 点击下钻）
const STN_MARGIN = 18

const stationDots = computed(() => {
  const out = []
  for (const m of summary.value?.markers || []) {
    if (m.lat == null || m.lon == null) continue
    const { x, y } = projectStation(m.lon, m.lat)
    if (x < -PAD.l + STN_MARGIN || x > 520 + PAD.r - STN_MARGIN) continue
    if (y < -PAD.t + STN_MARGIN || y > 400 + PAD.b - STN_MARGIN) continue
    const band = bandOf(m.chla)
    out.push({
      id: m.id,
      name: m.name || m.id,
      band,
      vx: x,
      vy: y,
      tip: m.chla == null
        ? `${BAND_TEXT.none} · 点击进入站点研判`
        : `Chl-a ${m.chla} μg/L · ${BAND_TEXT[band]}`,
      left: `${(((x + PAD.l) / VB_W) * 100).toFixed(2)}%`,
      top: `${(((y + PAD.t) / VB_H) * 100).toFixed(2)}%`
    })
  }
  return out
})

const hoveredStation = ref(null)

function goStation(id) {
  router.push({ path: '/stations', query: { p: id } })
}

// ---------- 全域交互式粒子网络（Canvas 2D，物理在 viewBox 空间进行） ----------
// 形态参考 particles.js 类“粒子星座”效果：粒子铺满全画布、邻近连线成类螺旋网络、
// 整体缓慢漂移，鼠标靠近时粒子迅速四散避开
const flowEl = ref(null)
const N_PARTICLES = 300
const TRAIL_MS = 800
const SPEED = 14 // viewBox 单位/秒，整体缓慢漂移
const LINK_DIST = 72 // 粒子连线的判定距离（viewBox 单位）
const LINK_MAX_PER_PARTICLE = 4 // 每个粒子最多连线数，防止连成毛球
const REPEL_RADIUS = 100 // 鼠标斥力作用半径
const REPEL_SPEED = 260 // 鼠标斥力峰值速度，保证粒子“迅速离开”鼠标位置
const particles = []
const mouse = { x: 0, y: 0, active: false }
let rafId = 0
let intervalId = 0
let watchdogId = 0
let lastDrawAt = 0
let resizeObserver = null
let ctx = null
let lastFrame = 0
let running = false

// 画布固定为亮色底（.lake-canvas 渐变不随主题），粒子/连线用深青墨色保证亮底可读
const CANVAS_INK = '#0f8ea0'

// ---- 发光精灵：径向渐变（白核→主题色→透明），避免实心圆斑的污渍感 ----
const spriteCache = new Map()
function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec((hex || '').trim())
  if (!m) return '57, 197, 187'
  const v = parseInt(m[1], 16)
  return `${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}`
}
function glowSprite(color) {
  let sp = spriteCache.get(color)
  if (sp) return sp
  const rgb = hexToRgb(color)
  const s = document.createElement('canvas')
  s.width = s.height = 64
  const g = s.getContext('2d')
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32)
  grad.addColorStop(0, `rgba(${rgb}, 0.9)`)
  grad.addColorStop(0.3, `rgba(${rgb}, 0.32)`)
  grad.addColorStop(1, `rgba(${rgb}, 0)`)
  g.fillStyle = grad
  g.fillRect(0, 0, 64, 64)
  spriteCache.set(color, s)
  return s
}

// 鼠标位置换算成 viewBox 坐标，供斥力计算
function onCanvasMove(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  mouse.x = ((e.clientX - rect.left) / rect.width) * VB_W - PAD.l
  mouse.y = ((e.clientY - rect.top) / rect.height) * VB_H - PAD.t
  mouse.active = true
}
function onCanvasLeave() {
  mouse.active = false
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

// viewBox(520×400) → 画布（外扩 PAD 后拉伸铺满），与站点投影共用同一坐标系
function applyViewTransform() {
  const el = flowEl.value
  const dpr = window.devicePixelRatio || 1
  const sx = (el.clientWidth * dpr) / VB_W
  const sy = (el.clientHeight * dpr) / VB_H
  ctx.setTransform(sx, 0, 0, sy, PAD.l * sx, PAD.t * sy)
  // 记录纵横比修正系数，供涡旋流场换算正圆轨道
  if (sx > 0) FLOW_K = sy / sx
}

// 全域均匀重生（不再限定湖体轮廓，粒子铺满整个画布）
function respawn(p, warm = 0) {
  p.x = -PAD.l + Math.random() * VB_W
  p.y = -PAD.t + Math.random() * VB_H
  p.trail = [[p.x, p.y, performance.now()]]
  p.life = 9 + Math.random() * 9
  // 深度（视差）与闪烁参数：远粒子更小更淡更慢，营造空间层次
  p.z = 0.35 + Math.random() * 0.65
  p.tw = 0.5 + Math.random() * 1.2
  p.ph = Math.random() * Math.PI * 2
  // 预热：静态帧（reduced-motion）下让轨迹先长出来
  for (let i = 0; i < warm; i++) stepParticle(p, 1 / 30)
}

// 类螺旋流场：绕画布中心的缓速涡旋（切向）叠加长波摆动，
// 连线随运动呈现出缓慢旋转的螺旋状结构
const FLOW_CX = -PAD.l + VB_W / 2
const FLOW_CY = -PAD.t + VB_H / 2
let FLOW_K = 0.6 // 纵横比修正系数（随画布实际尺寸更新），保证涡旋在屏幕上是正圆
const _v = { x: 0, y: 0 }
function flowVec(x, y, t) {
  const dx = x - FLOW_CX
  const dy = (y - FLOW_CY) * FLOW_K
  let vx = -dy
  let vy = dx / FLOW_K
  const norm = Math.hypot(vx, vy) || 1
  vx = vx / norm + Math.sin(y * 0.01 + t * 0.22) * 0.5
  vy = vy / norm + Math.sin(x * 0.007 - t * 0.16 + y * 0.004) * 0.35
  const m = Math.hypot(vx, vy) || 1
  _v.x = vx / m
  _v.y = vy / m
  return _v
}

function stepParticle(p, dt) {
  const t = performance.now() / 1000
  const v = flowVec(p.x, p.y, t)
  const sz = 0.45 + 0.75 * p.z // 深度视差：近粒子漂移更快
  p.x += v.x * SPEED * sz * dt
  p.y += v.y * SPEED * sz * dt
  // 鼠标斥力：作用半径内的粒子沿远离方向迅速弹开（平方衰减，越近推得越快），
  // 同时甩掉旧轨迹，让鼠标位置立刻空出一块干净的“空腔”
  if (mouse.active) {
    const dx = p.x - mouse.x
    const dy = p.y - mouse.y
    const d2 = dx * dx + dy * dy
    if (d2 < REPEL_RADIUS * REPEL_RADIUS && d2 > 0.01) {
      const d = Math.sqrt(d2)
      const falloff = 1 - d / REPEL_RADIUS
      const push = falloff * falloff * REPEL_SPEED * dt
      p.x += (dx / d) * push
      p.y += (dy / d) * push
      if (p.trail.length > 4) p.trail.splice(0, 2)
    }
  }
  p.life -= dt
  const now = performance.now()
  p.trail.push([p.x, p.y, now])
  while (p.trail.length && (now - p.trail[0][2] > TRAIL_MS || p.trail.length > 36)) {
    p.trail.shift()
  }
  // 边界环绕：从对侧进入（清空轨迹，避免跨屏拉出长线）
  let wrapped = false
  if (p.x < -PAD.l) { p.x += VB_W; wrapped = true }
  else if (p.x > 520 + PAD.r) { p.x -= VB_W; wrapped = true }
  if (p.y < -PAD.t) { p.y += VB_H; wrapped = true }
  else if (p.y > 400 + PAD.b) { p.y -= VB_H; wrapped = true }
  if (wrapped) p.trail = [[p.x, p.y, now]]
  else if (p.life <= 0) respawn(p)
}

function drawParticles(color) {
  applyViewTransform()
  ctx.clearRect(-PAD.l, -PAD.t, VB_W, VB_H)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  // ---- 基因连线：邻近粒子按当前头部位置两两相连，透明度随距离衰减、
  //      随两端粒子深度增强；每个粒子最多 LINK_MAX_PER_PARTICLE 条，保持疏朗网络 ----
  const heads = particles.map((p) => (p.trail.length ? p.trail[p.trail.length - 1] : null))
  const linkSegs = [[], [], [], []] // 按期望亮度分 4 档，近/深粒子连线更亮
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
  const want = (1 - d / LINK_DIST) * (0.35 + 0.55 * Math.min(particles[i].z, particles[j].z))
      linkSegs[want > 0.46 ? 0 : want > 0.3 ? 1 : want > 0.16 ? 2 : 3].push(heads[i], heads[j])
      linkCount[i]++
      linkCount[j]++
      if (linkCount[i] >= LINK_MAX_PER_PARTICLE) break
    }
  }
  const LINK_ALPHAS = [0.62, 0.45, 0.28, 0.13]
  ctx.strokeStyle = color
  // 双层描边：宽而淡的底层做柔化，窄而亮的表层保持清晰
  for (let b = 0; b < 4; b++) {
    if (!linkSegs[b].length) continue
    ctx.beginPath()
    for (let k = 0; k < linkSegs[b].length; k += 2) {
      ctx.moveTo(linkSegs[b][k][0], linkSegs[b][k][1])
      ctx.lineTo(linkSegs[b][k + 1][0], linkSegs[b][k + 1][1])
    }
    ctx.globalAlpha = LINK_ALPHAS[b] * 0.3
    ctx.lineWidth = 2.6
    ctx.stroke()
    ctx.globalAlpha = LINK_ALPHAS[b]
    ctx.lineWidth = 0.9
    ctx.stroke()
  }
  ctx.globalAlpha = 1

  // ---- 轨迹：按新旧分三档透明度批量描边，避免逐段 stroke 的开销 ----
  const buckets = [
    { from: 0, to: 1 / 3, alpha: 0.07, width: 1.0 },
    { from: 1 / 3, to: 2 / 3, alpha: 0.16, width: 1.25 },
    { from: 2 / 3, to: 1, alpha: 0.34, width: 1.5 }
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
  // 粒子头部：径向渐变光晕精灵（白核→主题色→透明）+ 白亮小核心，随深度闪烁呼吸
  const t = performance.now() / 1000
  const sprite = glowSprite(color)
  for (const p of particles) {
    const n = p.trail.length
    if (!n) continue
    const hx = p.trail[n - 1][0]
    const hy = p.trail[n - 1][1]
    const tw = 0.72 + 0.28 * Math.sin(t * p.tw + p.ph)
    const r = 5 + 8.5 * p.z
    ctx.globalAlpha = (0.4 + 0.5 * p.z) * tw
    ctx.drawImage(sprite, hx - r, hy - r, r * 2, r * 2)
    ctx.globalAlpha = Math.min(1, (0.5 + 0.5 * p.z) * tw)
    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(hx, hy, 0.7 + 1.1 * p.z, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  drawStations(t)
}

// ---- 监测站节点：与粒子同风格的发光枢纽 ----
// 每站以细线接入最近的 2 个网络粒子（枢纽感），预警站带呼吸外环，悬停放大高亮
const BAND_COLORS = {
  normal: '#5fd6a4',
  light: '#f5b45d',
  moderate: '#ef4444',
  none: '#7d93a8'
}

function drawStations(t) {
  const stns = stationDots.value
  if (!stns.length) return
  for (const s of stns) {
    const col = BAND_COLORS[s.band] || BAND_COLORS.none
    const hovered = hoveredStation.value === s.id
    const k = hovered ? 1.3 : 1
    const sprite = glowSprite(col)

    // 接入网络：连到最近的 2 个流场粒子（先粗筛距离再取最近）
    let n1 = null, d1 = Infinity, n2 = null, d2 = Infinity
    for (const p of particles) {
      const n = p.trail.length
      if (!n) continue
      const px2 = p.trail[n - 1][0]
      const py2 = p.trail[n - 1][1]
      const dd = Math.hypot(px2 - s.vx, py2 - s.vy)
      if (dd < d1) { n2 = n1; d2 = d1; n1 = [px2, py2]; d1 = dd }
      else if (dd < d2) { n2 = [px2, py2]; d2 = dd }
    }
    ctx.strokeStyle = col
    ctx.lineWidth = 0.6
    ctx.globalAlpha = hovered ? 0.35 : 0.16
    for (const pt of [n1, n2]) {
      if (!pt || pt[0] === undefined) continue
      ctx.beginPath()
      ctx.moveTo(s.vx, s.vy)
      ctx.lineTo(pt[0], pt[1])
      ctx.stroke()
    }

    // 星星节点：彩光晕 + 四角星缓慢旋转 + 轻微呼吸 + 白色小核心
    const gr = (hovered ? 19 : 15) * k
    ctx.globalAlpha = hovered ? 0.85 : 0.6
    ctx.drawImage(sprite, s.vx - gr, s.vy - gr, gr * 2, gr * 2)
    const breathe = 0.92 + 0.08 * Math.sin(t * 1.6 + s.vy * 0.05)
    const R = 6.5 * k * breathe
    const rot = t * 0.5 + s.vx * 0.02
    starPath(s.vx, s.vy, R, R * 0.42, rot)
    ctx.globalAlpha = hovered ? 1 : 0.92
    ctx.fillStyle = col
    ctx.fill()
    ctx.globalAlpha = 0.95
    ctx.fillStyle = '#ffffff'
    ctx.beginPath()
    ctx.arc(s.vx, s.vy, 1.5 * k, 0, Math.PI * 2)
    ctx.fill()

    // 预警呼吸外环
    if (s.band === 'light' || s.band === 'moderate') {
      const pulseT = (Math.sin(t * 2.4 + s.vx * 0.05) + 1) / 2
      ctx.globalAlpha = (hovered ? 0.55 : 0.35) * (1 - pulseT)
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(s.vx, s.vy, (6 + 5.5 * pulseT) * k, 0, Math.PI * 2)
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
}

// 四角星（sparkle）路径：外半径 R、内半径 r、旋转 rot
function starPath(x, y, R, r, rot) {
  ctx.beginPath()
  for (let i = 0; i < 8; i++) {
    const rad = i % 2 === 0 ? R : r
    const a = rot + (i * Math.PI) / 4
    const px = x + Math.sin(a) * rad
    const py = y - Math.cos(a) * rad
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
  }
  ctx.closePath()
}

function frame(now) {
  if (!running) return
  const dt = Math.min((now - lastFrame) / 1000 || 0, 0.05)
  lastFrame = now
  if (document.hidden) return
  for (const p of particles) stepParticle(p, dt)
  drawParticles(CANVAS_INK)
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
  drawParticles(CANVAS_INK)
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

// ---------- 核心入口（顺序 = 业务动线：总览 → 站点 → 预警处置 → 分析 → 展示） ----------
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
    to: '/alerts',
    title: '预警与应急预案中心',
    desc: '预警事件处置工作流：确认、指派、预案匹配与模拟推送，全程留痕可复盘。'
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
  },
  {
    to: '/wallboard',
    title: '实时大屏',
    desc: '全站国控断面实时状态墙：抓取链路、活跃站点与缺测率一屏总览。'
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
.btn-bell { width: 16px; height: 16px; flex: none; }

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
  /* 极光底：柔和的多色浅渐变取代灰色网格 */
  background: linear-gradient(165deg, #f7fbfc 0%, #edf6f8 48%, #f0f7f2 100%);
}
/* 两团极光色斑缓慢漂移（aurora 渐变风格），给粒子网络一个柔和的舞台 */
.lake-canvas::before {
  content: '';
  position: absolute;
  inset: -22%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(34% 42% at 26% 34%, rgba(45, 183, 190, 0.17), transparent 70%),
    radial-gradient(30% 40% at 74% 62%, rgba(99, 161, 250, 0.13), transparent 70%),
    radial-gradient(26% 34% at 56% 26%, rgba(110, 231, 183, 0.15), transparent 70%);
  filter: blur(30px);
  animation: aurora-drift 26s ease-in-out infinite alternate;
}
@keyframes aurora-drift {
  0% { transform: translate3d(-2.5%, -2%, 0) scale(1); }
  50% { transform: translate3d(2%, 2%, 0) scale(1.05); }
  100% { transform: translate3d(-1.5%, 2.5%, 0) scale(1.02); }
}
@media (prefers-reduced-motion: reduce) {
  .lake-canvas::before { animation: none; }
}
.flow-canvas {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

/* 站点按钮：可见形态由 canvas 绘制（发光节点），按钮只是透明热区，
   负责悬停提示与点击下钻 */
.stn {
  position: absolute;
  z-index: 2;
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
.lg--high, .lg--moderate { color: #ef4444; }
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

/* ============ 六个核心入口 ============ */
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
