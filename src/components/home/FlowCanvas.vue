<template>
  <canvas
    ref="flowEl"
    class="flow-canvas"
    aria-hidden="true"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerleave="onPointerLeave"
  ></canvas>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

// ---------- 组件契约 ----------
// stations: [{ id, vx, vy, band }] —— viewBox 坐标系下的站点投影（Home.vue stationDots 的输出子集）
// hoveredId: 当前悬停站点 id（悬停热区由父层 DOM 按钮维护，本组件只负责可见形态）
const props = defineProps({
  stations: { type: Array, default: () => [] },
  hoveredId: { type: String, default: '' }
})

// ---------- 全域交互式粒子网络（Canvas 2D，物理在 viewBox 空间进行） ----------
// 形态参考 particles.js 类“粒子星座”效果：粒子铺满全画布、邻近连线成类螺旋网络、
// 整体缓慢漂移，鼠标靠近时粒子迅速四散避开。
// 本组件为 Home.vue 内联引擎的组件化版本，另含三项工程升级：
//   ① 点击冲击波（波前沿径向外推粒子，多波并存）
//   ② FPS 自适应粒子预算（滚动窗口帧时统计 → 4 档降/升，data-quality 外显）
//   ③ 指针光尾（更亮更大的主色精灵短生命周期拖尾，与斥力空腔叠加）
const flowEl = ref(null)
const MAX_PARTICLES = 300 // 粒子预算上限（FPS 降档时多余粒子休眠，不绘制不步进）
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
let reducedMotion = false

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

// ---- 指针换算成 viewBox 坐标，供斥力 / 光尾 / 冲击波共用 ----
function pointerToView(e) {
  const rect = e.currentTarget.getBoundingClientRect()
  if (!rect.width || !rect.height) return null
  return {
    x: ((e.clientX - rect.left) / rect.width) * VB_W - PAD.l,
    y: ((e.clientY - rect.top) / rect.height) * VB_H - PAD.t
  }
}

// 指针光尾：pointermove 时在指针位置留下短生命周期光斑
const pointerTrail = [] // [{ x, y, t0 }]
const POINTER_TRAIL_MS = 300
const POINTER_TRAIL_MAX = 48 // 防高频 pointermove 无限堆积

function onPointerMove(e) {
  const pt = pointerToView(e)
  if (!pt) return
  mouse.x = pt.x
  mouse.y = pt.y
  mouse.active = true
  if (reducedMotion) return
  const now = performance.now()
  pointerTrail.push({ x: pt.x, y: pt.y, t0: now })
  if (pointerTrail.length > POINTER_TRAIL_MAX) pointerTrail.shift()
}
function onPointerLeave() {
  mouse.active = false
}

// ---- 点击冲击波：以点击点为圆心扩散的细光环 + 波前径向外推粒子，多波并存 ----
const waves = [] // [{ x, y, t0 }]
const WAVE_MS = 720 // 单个冲击波生命周期（600-800ms 淡出口径）
const WAVE_MAX_R = 320 // 最大扩散半径（viewBox 单位）
const WAVE_FRONT_BAND = 26 // 波前厚度：粒子距波前小于该值才被外推
const WAVE_KICK = 190 // 波前外推峰值速度（对照 REPEL_SPEED 的平方衰减口径）
const WAVES_MAX = 6 // 连续狂点保护

function onPointerDown(e) {
  if (reducedMotion) return // reduced-motion 下点击无动画
  const pt = pointerToView(e)
  if (!pt) return
  waves.push({ x: pt.x, y: pt.y, t0: performance.now() })
  if (waves.length > WAVES_MAX) waves.shift()
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

// ---- FPS 自适应粒子预算：滚动窗口（120 帧）统计平均帧时，超时降档、稳定提速升档 ----
// 档位外显在 canvas 的 data-quality 属性上（3=满档 … 0=最低档），便于工程观测
const FPS_WINDOW = 120 // 滚动统计窗口（帧）
const FPS_MIN_SAMPLES = 60 // 窗口样本不足不评估，避免冷启动误判
const FPS_EVAL_STEP = 20 // 每 20 帧评估一次
const FPS_DOWN_MS = 24 // 平均帧时 >24ms → 降一级
const FPS_UP_MS = 16 // 平均帧时 <16ms 且持续稳定 → 渐进升回
const FPS_UP_STREAK = 3 // 升档需连续 3 次评估满足 <16ms（渐进）
const FPS_UP_COOLDOWN_MS = 3000 // 两次升档之间的冷却，防抖动
const FPS_DOWN_COOLDOWN_MS = 800 // 逐级降档的最小间隔

const QUALITY_TIERS = [
  { q: 3, n: 300, link: 1.0 }, // 满档：300 粒子 / 连线距离 ×1.0
  { q: 2, n: 240, link: 0.9 }, // 240 / ×0.9
  { q: 1, n: 180, link: 0.8 }, // 180 / ×0.8
  { q: 0, n: 140, link: 0.65 } // 140 / ×0.65（粒子数与连线距离各降档）
]
let qualityLevel = 3
let activeCount = MAX_PARTICLES // 当前档位实际参与步进/绘制/连线的粒子数
let lastLevelChange = 0
let upStreak = 0
const frameTimes = new Float32Array(FPS_WINDOW)
let frameTimesLen = 0
let frameTimesIdx = 0
let evalCounter = 0

function recordFrame(ms, now) {
  frameTimes[frameTimesIdx] = ms
  frameTimesIdx = (frameTimesIdx + 1) % FPS_WINDOW
  if (frameTimesLen < FPS_WINDOW) frameTimesLen++
  if (++evalCounter >= FPS_EVAL_STEP) {
    evalCounter = 0
    evaluateQuality(now)
  }
}

function evaluateQuality(now) {
  if (frameTimesLen < FPS_MIN_SAMPLES) return
  let sum = 0
  for (let i = 0; i < frameTimesLen; i++) sum += frameTimes[i]
  const avg = sum / frameTimesLen
  if (avg > FPS_DOWN_MS) {
    // 降档立即生效（受逐级最小间隔约束，防止瞬间穿档）
    upStreak = 0
    if (qualityLevel > 0 && now - lastLevelChange > FPS_DOWN_COOLDOWN_MS) {
      setQuality(qualityLevel - 1, now)
    }
  } else if (avg < FPS_UP_MS) {
    // 升档渐进：连续多次评估都流畅才升一级
    if (
      qualityLevel < QUALITY_TIERS.length - 1 &&
      now - lastLevelChange > FPS_UP_COOLDOWN_MS &&
      ++upStreak >= FPS_UP_STREAK
    ) {
      setQuality(qualityLevel + 1, now)
      upStreak = 0
    }
  } else {
    upStreak = 0
  }
}

function setQuality(level, now) {
  const prev = activeCount
  qualityLevel = level
  activeCount = QUALITY_TIERS[level].n
  lastLevelChange = now
  upStreak = 0
  // 从休眠中唤醒的粒子重新重生，避免陈旧轨迹在画布上拉出横跨屏幕的长线
  for (let i = prev; i < activeCount; i++) respawn(particles[i])
  const el = flowEl.value
  if (el) el.dataset.quality = String(qualityLevel)
}

// 站点 / 画布共用 PAD 与 viewBox 常量（与 Home.vue 站点投影同一坐标系）
const PAD = { l: 235, r: 137, t: 199, b: 186 }
const VB_W = 520 + PAD.l + PAD.r
const VB_H = 400 + PAD.t + PAD.b

// 全域均匀重生（不再限定湖体轮廓，粒子铺满整个画布）
function respawn(p, warm = 0) {
  p.x = -PAD.l + Math.random() * VB_W
  p.y = -PAD.t + Math.random() * VB_H
  p.trail = [[p.x, p.y, performance.now()]]
  p.life = 9 + Math.random() * 9
  p.ivx = 0 // 冲击波外推的冲量速度
  p.ivy = 0
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
  // 冲击波赋予的径向冲量速度：指数衰减（甩尾清空后归零）
  if (p.ivx || p.ivy) {
    p.x += p.ivx * dt
    p.y += p.ivy * dt
    const decay = Math.exp(-4.5 * dt)
    p.ivx *= decay
    p.ivy *= decay
    if (Math.abs(p.ivx) < 2 && Math.abs(p.ivy) < 2) { p.ivx = 0; p.ivy = 0 }
  }
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
  // 冲击波波前外推：波前扫过的粒子沿径向获得外推冲量（比照 REPEL 的平方衰减），
  // 波前每个位置只经过一次，天然不会重复施力；多波并存时冲量做上限保护
  const nowMs = performance.now()
  for (const w of waves) {
    const pr = (nowMs - w.t0) / WAVE_MS
    if (pr >= 1) continue
    const r = WAVE_MAX_R * (1 - Math.pow(1 - pr, 3))
    const dx = p.x - w.x
    const dy = p.y - w.y
    const d = Math.hypot(dx, dy)
    if (d > WAVE_MAX_R || d < 0.01) continue
    if (Math.abs(d - r) > WAVE_FRONT_BAND) continue
    const falloff = Math.max(0, 1 - d / WAVE_MAX_R)
    const push = falloff * falloff * WAVE_KICK
    p.ivx += (dx / d) * push
    p.ivy += (dy / d) * push
    const im = Math.hypot(p.ivx, p.ivy)
    if (im > 420) { p.ivx = (p.ivx / im) * 420; p.ivy = (p.ivy / im) * 420 }
    if (p.trail.length > 4) p.trail.splice(0, 2) // 甩尾
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

  // 当前档位的连线判定距离（降档时随粒子数同步收缩，省掉远距两两比较）
  const linkDist = LINK_DIST * QUALITY_TIERS[qualityLevel].link

  // ---- 基因连线：邻近粒子按当前头部位置两两相连，透明度随距离衰减、
  //      随两端粒子深度增强；每个粒子最多 LINK_MAX_PER_PARTICLE 条，保持疏朗网络 ----
  // （只统计当前档位的活跃粒子；休眠粒子不绘制不参与）
  const heads = new Array(activeCount)
  for (let i = 0; i < activeCount; i++) {
    const tr = particles[i].trail
    heads[i] = tr.length ? tr[tr.length - 1] : null
  }
  const linkSegs = [[], [], [], []] // 按期望亮度分 4 档，近/深粒子连线更亮
  const linkCount = new Array(activeCount).fill(0)
  for (let i = 0; i < heads.length; i++) {
    if (!heads[i] || linkCount[i] >= LINK_MAX_PER_PARTICLE) continue
    for (let j = i + 1; j < heads.length; j++) {
      if (!heads[j] || linkCount[j] >= LINK_MAX_PER_PARTICLE) continue
      const dx = heads[i][0] - heads[j][0]
      const dy = heads[i][1] - heads[j][1]
      if (dx > linkDist || dx < -linkDist || dy > linkDist || dy < -linkDist) continue
      const d = Math.sqrt(dx * dx + dy * dy)
      if (d > linkDist) continue
      const want = (1 - d / linkDist) * (0.35 + 0.55 * Math.min(particles[i].z, particles[j].z))
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
    for (let i = 0; i < activeCount; i++) {
      const tr = particles[i].trail
      const n = tr.length
      if (n < 2) continue
      const start = Math.max(1, Math.floor(n * b.from))
      const end = Math.max(start + 1, Math.ceil(n * b.to))
      ctx.moveTo(tr[start - 1][0], tr[start - 1][1])
      for (let k = start; k < Math.min(end, n); k++) {
        ctx.lineTo(tr[k][0], tr[k][1])
      }
    }
    ctx.stroke()
  }
  // 粒子头部：径向渐变光晕精灵（白核→主题色→透明）+ 白亮小核心，随深度闪烁呼吸
  const t = performance.now() / 1000
  const sprite = glowSprite(color)
  for (let i = 0; i < activeCount; i++) {
    const p = particles[i]
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

  // ---- 指针光尾：比普通粒子大一倍的主色精灵，300ms 淡出，
  //      与斥力空腔叠加形成“指针点亮网络”的观感（reduced-motion 下关闭） ----
  if (pointerTrail.length) {
    const nowMs = performance.now()
    for (let i = pointerTrail.length - 1; i >= 0; i--) {
      const pt = pointerTrail[i]
      const age = nowMs - pt.t0
      if (age > POINTER_TRAIL_MS) { pointerTrail.splice(i, 1); continue }
      const fade = 1 - age / POINTER_TRAIL_MS
      const r = 22 * (0.6 + 0.4 * fade) // 普通粒子头部最大 ≈13.5，此处约大一倍
      ctx.globalAlpha = 0.5 * fade * fade
      ctx.drawImage(sprite, pt.x - r, pt.y - r, r * 2, r * 2)
    }
    ctx.globalAlpha = 1
  }

  drawStations(t)
  drawWaves()
}

// ---- 监测站节点：与粒子同风格的发光枢纽 ----
// 每站以细线接入最近的 2 个网络粒子（枢纽感），预警站带呼吸外环，悬停放大高亮。
// 站点坐标 / 分档读 props.stations，悬停态读 props.hoveredId（由父层热区维护）
const BAND_COLORS = {
  normal: '#5fd6a4',
  light: '#f5b45d',
  moderate: '#ef4444',
  none: '#7d93a8'
}

function drawStations(t) {
  const stns = props.stations
  if (!stns.length) return
  for (const s of stns) {
    const col = BAND_COLORS[s.band] || BAND_COLORS.none
    const hovered = props.hoveredId === s.id
    const k = hovered ? 1.3 : 1
    const sprite = glowSprite(col)

    // 接入网络：连到最近的 2 个流场粒子（先粗筛距离再取最近；只看活跃粒子）
    let n1 = null, d1 = Infinity, n2 = null, d2 = Infinity
    for (let i = 0; i < activeCount; i++) {
      const tr = particles[i].trail
      const n = tr.length
      if (!n) continue
      const px2 = tr[n - 1][0]
      const py2 = tr[n - 1][1]
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

// ---- 点击冲击波光环：半径随时间扩散的细光环（主环 + 0.7 倍内回声环），随生命周期淡出 ----
function drawWaves() {
  if (!waves.length) return
  const nowMs = performance.now()
  ctx.strokeStyle = CANVAS_INK
  for (let i = waves.length - 1; i >= 0; i--) {
    const w = waves[i]
    const pr = (nowMs - w.t0) / WAVE_MS
    if (pr >= 1) { waves.splice(i, 1); continue } // 生命周期结束移除
    const r = WAVE_MAX_R * (1 - Math.pow(1 - pr, 3)) // ease-out 扩散
    const fade = 1 - pr
    ctx.globalAlpha = 0.55 * fade * fade
    ctx.lineWidth = 1.6 * fade + 0.4
    ctx.beginPath()
    ctx.arc(w.x, w.y, r, 0, Math.PI * 2)
    ctx.stroke()
    if (pr < 0.7) {
      // 内回声环：前 70% 生命周期可见的第二圈细环
      ctx.globalAlpha = 0.28 * (1 - pr / 0.7)
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(w.x, w.y, r * 0.72, 0, Math.PI * 2)
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
  const raw = now - lastFrame
  if (raw > 1000) {
    // 标签页隐藏 / rAF 长暂停后恢复：清空统计窗口重新累计，避免陈旧样本误判档位
    frameTimesLen = 0
    evalCounter = 0
  }
  const dt = Math.min(raw / 1000 || 0, 0.05)
  lastFrame = now
  if (document.hidden) return
  recordFrame(Math.min(Math.max(raw, 1), 50), now)
  for (let i = 0; i < activeCount; i++) stepParticle(particles[i], dt)
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
  el.dataset.quality = String(qualityLevel) // 档位外显（工程可见性）

  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const warmSteps = reducedMotion ? 260 : 40 // 首帧先长出短轨迹，避免空白起步
  for (let i = 0; i < MAX_PARTICLES; i++) {
    const p = { x: 0, y: 0, life: 0, trail: [], ivx: 0, ivy: 0 }
    respawn(p, warmSteps)
    particles.push(p)
  }
  drawParticles(CANVAS_INK)
  if (reducedMotion) return // 静态帧即可，不启动动画（冲击波 / 光尾 / FPS 监测均随之关闭）
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
  // 页面卸载全清理：动画句柄之外的运行时状态一并归零
  waves.length = 0
  pointerTrail.length = 0
  particles.length = 0
  ctx = null
}

onMounted(startFlow)
onBeforeUnmount(stopFlow)
</script>

<style scoped>
/* 样式沿用 Home.vue 的 .flow-canvas：绝对定位铺满容器。
   唯一差异：pointer-events 需开启——本组件的 canvas 自身承载
   点击冲击波（pointerdown）与指针光尾（pointermove）；
   父层站点热区按钮位于 z-index: 2（画布之上），交互不受影响 */
.flow-canvas {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  pointer-events: auto;
}
</style>
