// 入湖负荷卡纯函数 + request() 错误信封透传回归（node --test，零额外依赖）。
//
// 覆盖：
//   ① fmt          数值格式化：空态/null/非有限数输出 '—'，绝不输出 NaN；
//   ② classKey     水质类别 → 配色 key 的映射与边界（未收录类别 → unknown）；
//   ③ worstTpMean12 最差断面近12月TP均值：null 契约（mean_last12 空集返回 null）显式兜底；
//   ④ shortSource  数据来源截断；
//   ⑤ api.js request()：HTTP 非 2xx 时透传后端错误信封 message，非 JSON 错误体回退状态码。
//
// 运行：npm test  （或 node --test tests/inflowCard.test.mjs）
import test from 'node:test'
import assert from 'node:assert/strict'

import { classKey, fmt, shortSource, worstTpMean12 } from '../src/components/cockpit/inflowCardUtils.js'
import { getInflowRiversSummary } from '../src/services/api.js'

// ---------- ① fmt：数值格式化 ----------

test('fmt：null/undefined/NaN 空态一律输出 —，绝不输出 NaN', () => {
  assert.equal(fmt(null, 3), '—')
  assert.equal(fmt(undefined, 2), '—')
  assert.equal(fmt(NaN, 3), '—')
  assert.equal(fmt('not-a-number', 3), '—')
})

test('fmt：常规数值按位数定点输出（四舍五入）', () => {
  assert.equal(fmt(0.123456, 3), '0.123')
  assert.equal(fmt(0.1236, 3), '0.124')
  assert.equal(fmt(1.5, 2), '1.50')
  assert.equal(fmt(-0.042, 3), '-0.042')
})

test('fmt：0 是合法监测值而非空态，不得被当作 null 处理', () => {
  assert.equal(fmt(0, 3), '0.000')
})

test('fmt：数字字符串按数值格式化（后端偶发字符串型数值不失真）', () => {
  assert.equal(fmt('1.5', 2), '1.50')
  assert.equal(fmt('0.2567', 3), '0.257')
})

// ---------- ② classKey：水质类别 → 配色 key ----------

test('classKey：Ⅱ/Ⅲ/Ⅳ/Ⅳ 类别映射到官方通报配色 key', () => {
  assert.equal(classKey('Ⅱ'), 'excellent')
  assert.equal(classKey('Ⅲ'), 'good')
  assert.equal(classKey('Ⅳ'), 'moderate')
  assert.equal(classKey('Ⅴ'), 'poor')
})

test('classKey：未收录类别（Ⅰ/劣Ⅴ/半角罗马数字/空值）统一 unknown', () => {
  assert.equal(classKey('Ⅰ'), 'unknown')
  assert.equal(classKey('劣Ⅴ'), 'unknown')
  assert.equal(classKey('II'), 'unknown', '半角 II 不得误配全角 Ⅱ')
  assert.equal(classKey(''), 'unknown')
  assert.equal(classKey(null), 'unknown')
  assert.equal(classKey(undefined), 'unknown')
})

// ---------- ③ worstTpMean12：最差断面口径 + null 契约 ----------

test('worstTpMean12：取全部断面近12月TP均值最大值，3 位定点输出', () => {
  const sections = [
    { section: 'S1', mean_last12: { tp: 0.112, nh3n: 1.2 } },
    { section: 'S2', mean_last12: { tp: 0.2567, nh3n: 0.9 } },
    { section: 'S3', mean_last12: { tp: 0.071, nh3n: 2.4 } }
  ]
  assert.equal(worstTpMean12(sections), '0.257')
})

test('worstTpMean12：sections 为空数组 / null / undefined 时输出空态 —', () => {
  assert.equal(worstTpMean12([]), '—')
  assert.equal(worstTpMean12(null), '—')
  assert.equal(worstTpMean12(undefined), '—')
})

test('worstTpMean12：mean_last12 为 null（空集契约）的断面按缺数跳过，不当 0 参与比较', () => {
  const sections = [
    { section: 'S1', mean_last12: null },
    { section: 'S2', mean_last12: { tp: 0.184, nh3n: 1.0 } },
    { section: 'S3' }
  ]
  // 若把 null 误当 0，Max(0, 0.184) 仍是 0.184 —— 关键是否参与集合不污染空态；
  // 更严格的断言：唯一有值的断面被如实呈现
  assert.equal(worstTpMean12(sections), '0.184')
})

test('worstTpMean12：全部断面 mean_last12 均为 null/缺数时输出 — 而非 0.000', () => {
  const sections = [
    { section: 'S1', mean_last12: null },
    { section: 'S2', mean_last12: { tp: null, nh3n: null } },
    { section: 'S3', mean_last12: { tp: 'n/a' } }
  ]
  assert.equal(worstTpMean12(sections), '—')
})

test('worstTpMean12：tp 为 null 的断面不得作为 0 拉低/顶替最差口径（null ≠ 0）', () => {
  const withNullOnly = [{ section: 'S1', mean_last12: { tp: null } }]
  assert.equal(worstTpMean12(withNullOnly), '—', '唯一断面 null 时必须是空态，不得输出 0.000')
})

// ---------- ④ shortSource：数据来源截断 ----------

test('shortSource：超过 14 字符截为 14 字符 + 省略号，以内不截断', () => {
  const long = '江苏省生态环境厅（2025年1-12月国考断面监测数据汇编）'
  const short = shortSource(long)
  assert.equal(short.length, 15)
  assert.ok(short.endsWith('…'))
  assert.equal(short.slice(0, 14), long.slice(0, 14))

  const within = '江苏省生态环境厅月报'
  assert.equal(shortSource(within), within)
})

test('shortSource：null/undefined/空串 均安全返回空串', () => {
  assert.equal(shortSource(null), '')
  assert.equal(shortSource(undefined), '')
  assert.equal(shortSource(''), '')
})

// ---------- ⑤ request() 错误信封透传（经 getInflowRiversSummary 触发内部 request） ----------

function jsonResponse(payload, status) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

function htmlResponse(status) {
  return new Response('<html><body>Bad Gateway</body></html>', {
    status,
    headers: { 'Content-Type': 'text/html' }
  })
}

test('request：HTTP 非 2xx 时透传后端错误信封里的 message', async () => {
  const realFetch = globalThis.fetch
  globalThis.fetch = async () =>
    jsonResponse({ code: 500, message: '入湖负荷档案服务暂不可用', data: null, meta: {} }, 500)
  try {
    await assert.rejects(
      getInflowRiversSummary(),
      /入湖负荷档案服务暂不可用/,
      '必须把后端 message 并入抛出的 Error'
    )
  } finally {
    globalThis.fetch = realFetch
  }
})

test('request：FastAPI 原生 detail（422 校验错误）同样透传', async () => {
  const realFetch = globalThis.fetch
  globalThis.fetch = async () => jsonResponse({ detail: 'Query param out of range' }, 422)
  try {
    await assert.rejects(getInflowRiversSummary(), /Query param out of range/)
  } finally {
    globalThis.fetch = realFetch
  }
})

test('request：错误体不是 JSON（网关 HTML / CORS 拦截）时回退状态码文案，不得二次抛解析异常', async () => {
  const realFetch = globalThis.fetch
  globalThis.fetch = async () => htmlResponse(502)
  try {
    await assert.rejects(getInflowRiversSummary(), /API 请求失败：502/)
  } finally {
    globalThis.fetch = realFetch
  }
})

test('request：信封无 message 字段时维持状态码兜底文案', async () => {
  const realFetch = globalThis.fetch
  globalThis.fetch = async () => jsonResponse({ code: 503, data: null, meta: {} }, 503)
  try {
    await assert.rejects(getInflowRiversSummary(), /API 请求失败：503/)
  } finally {
    globalThis.fetch = realFetch
  }
})
