// 预测仓库自动化竞速 / 串站回归测试（node --test，零额外依赖）。
//
// 覆盖审计要求的自动化场景，替代一次性浏览器脚本：
//   ① 快速切换站点：先发的旧请求晚返回，不得覆盖新站点结果；
//   ② 同一实体切换指标：旧指标在途请求被中止，不得覆盖新指标；
//   ③ 同一世代内重复读取：命中内存缓存，不重复请求；
//   ④ 快照换代：prediction_snapshot_id 变化后整代缓存失效并强制刷新；
//   ⑤ 中止请求不得把页面推入错误态；
//   ⑥ 加载失败不得清空已有结果。
//
// 运行：npm test  （或 node --test tests/）
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  __predictionStoreInternals,
  __resetPredictionStoreForTest,
  entityDiagnostic,
  intervalState,
  loadPredictionSnapshot,
  predictionSnapshot,
  refreshPredictionStatus
} from '../src/stores/predictionSnapshot.js'

const SNAPSHOT_STATUS_PATH = '/model/v3/prediction-status'
const SNAPSHOT_PATH = '/model/v3/prediction-snapshot'

let calls = []
let realFetch = null

function installFetch() {
  calls = []
  realFetch = globalThis.fetch
  globalThis.fetch = (url, options = {}) => {
    const entry = { url: String(url), options, settled: false, reject: null }
    const promise = new Promise((resolve, reject) => {
      entry.reject = reject
      entry.respond = (payload) => {
        if (entry.settled) return
        entry.settled = true
        resolve(
          new Response(JSON.stringify({ code: 200, data: payload, meta: {} }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' }
          })
        )
      }
      entry.fail = (message = 'boom') => {
        if (entry.settled) return
        entry.settled = true
        reject(new Error(message))
      }
    })
    if (options.signal) {
      options.signal.addEventListener('abort', () => {
        if (entry.settled) return
        entry.settled = true
        const error = new Error('aborted')
        error.name = 'AbortError'
        entry.reject(error)
      })
    }
    calls.push(entry)
    return promise
  }
}

function restoreFetch() {
  if (realFetch) globalThis.fetch = realFetch
}

function snapshotCalls() {
  return calls.filter((call) => call.url.includes(SNAPSHOT_PATH))
}

/** 等待条件成立（最多 50ms），用于观察异步链而非依赖固定 tick 次数。 */
async function waitFor(predicate, message) {
  for (let i = 0; i < 50; i += 1) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  assert.fail(message || '等待条件超时')
}

function statusCalls() {
  return calls.filter((call) => call.url.includes(SNAPSHOT_STATUS_PATH))
}

function payload(entityId, metric, snapshotId = 'PRED_G1', value = 1) {
  return {
    entity_id: entityId,
    focus_metric: metric,
    horizons: {
      '3': {
        entity_id: entityId,
        horizon_days: 3,
        analysis_focus: { requested_metric: metric, result_key: 'probability' },
        input_fingerprint: `${entityId}-obs`,
        observed_input_fingerprint: `${entityId}-obs`,
        transformed_model_input_fingerprint: `${entityId}-tfp-${metric}`,
        fingerprint_schema: 'dual_fingerprint_v1',
        results: {
          probability: {
            value,
            uncertainty: {
              is_prediction_interval: true,
              structural_valid: false,
              interval_degenerate: true,
              invalid_reason: '零宽退化',
              calibration_status: 'validated',
              calibration_evidence: {
                status: 'validated',
                reason: '经验覆盖率已由冻结测试集核算',
                test_n: 40,
                empirical_coverage: 0.975,
                calibration_n: 31,
                min_test_n: 15
              },
              calibration_n: 31,
              test_n: 40,
              empirical_coverage: 0.975,
              decision_usable: false,
              decision_reason: '零宽退化'
            }
          }
        }
      }
    },
    horizon_list: [3],
    trend: { points: [] },
    metric_diagnostics: {},
    prediction_snapshot_id: snapshotId,
    source_snapshot_id: 'REAL_SNAP',
    generated_at: '2026-09-10T18:00:00+08:00',
    model_version: '0.3',
    cache_schema: 'prediction_snapshot_v3',
    status: { state: 'ready', using_previous_success: false, last_error: null, stations: { ready: true, done: 2, total: 2 } },
    snapshot_source: { served_from_snapshot: true }
  }
}

test.beforeEach(() => {
  installFetch()
  __resetPredictionStoreForTest()
})

test.afterEach(() => {
  __resetPredictionStoreForTest()
  restoreFetch()
})

test('快速切换站点：先发的旧请求晚返回不得覆盖新站点', async () => {
  const slow = loadPredictionSnapshot('S_A', 'risk')
  const fast = loadPredictionSnapshot('S_B', 'risk')
  assert.equal(snapshotCalls().length, 2, '两个不同站点各自发起请求，互不取消')

  // 后发的 S_B 先返回
  snapshotCalls()[1].respond(payload('S_B', 'risk', 'PRED_G1', 2))
  await fast
  assert.equal(predictionSnapshot.entityId, 'S_B')

  // 先发的 S_A 晚返回：必须被丢弃
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 1))
  await slow
  assert.equal(predictionSnapshot.entityId, 'S_B', '旧请求晚返回不得回写')
  assert.equal(predictionSnapshot.horizons['3'].entity_id, 'S_B')
  assert.equal(predictionSnapshot.horizons['3'].results.probability.value, 2)
})

test('同一实体切换指标：旧指标在途请求被中止且不得回写', async () => {
  const stale = loadPredictionSnapshot('S_A', 'risk')
  const fresh = loadPredictionSnapshot('S_A', 'chla')
  assert.equal(snapshotCalls().length, 2)
  assert.equal(snapshotCalls()[0].options.signal.aborted, true, '同实体换指标必须中止旧请求')

  snapshotCalls()[1].respond(payload('S_A', 'chla', 'PRED_G1', 7))
  await fresh
  await stale
  assert.equal(predictionSnapshot.focusMetric, 'chla')
  assert.equal(predictionSnapshot.requestedMetric, 'chla')
})

test('同一世代内重复读取命中内存缓存，不重复请求', async () => {
  const first = loadPredictionSnapshot('S_A', 'risk')
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 3))
  await first
  assert.equal(snapshotCalls().length, 1)
  assert.equal(predictionSnapshot.generation, 'PRED_G1')

  await loadPredictionSnapshot('S_A', 'risk')
  assert.equal(snapshotCalls().length, 1, '同一世代同实体同指标必须命中缓存')

  const forced = loadPredictionSnapshot('S_A', 'risk', { force: true })
  assert.equal(snapshotCalls().length, 2, 'force 必须真正重新请求')
  snapshotCalls()[1].respond(payload('S_A', 'risk', 'PRED_G1', 8))
  await forced
})

test('快照换代：prediction_snapshot_id 变化后整代缓存失效并强制刷新', async () => {
  const first = loadPredictionSnapshot('S_A', 'risk')
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 3))
  await first
  assert.equal(predictionSnapshot.predictionSnapshotId, 'PRED_G1')

  const refreshing = refreshPredictionStatus()
  assert.equal(statusCalls().length, 1)
  statusCalls()[0].respond({ state: 'ready', prediction_snapshot_id: 'PRED_G2', stations: { ready: true, done: 2, total: 2 } })
  await waitFor(() => snapshotCalls().length === 2, '换代必须重新拉取结果')
  snapshotCalls()[1].respond(payload('S_A', 'risk', 'PRED_G2', 9))
  const changed = await refreshing
  assert.equal(changed, true)
  assert.equal(predictionSnapshot.predictionSnapshotId, 'PRED_G2')
  assert.equal(predictionSnapshot.horizons['3'].results.probability.value, 9)

  // 换代后旧世代缓存已清空：再次读取不再命中 G1
  await loadPredictionSnapshot('S_A', 'risk')
  assert.equal(snapshotCalls().length, 2)
})

test('状态轮询未换代时不得触发结果请求', async () => {
  const first = loadPredictionSnapshot('S_A', 'risk')
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 3))
  await first

  const refreshing = refreshPredictionStatus()
  statusCalls()[0].respond({ state: 'ready', prediction_snapshot_id: 'PRED_G1', stations: { ready: true, done: 2, total: 2 } })
  assert.equal(await refreshing, false)
  assert.equal(snapshotCalls().length, 1)
})

test('中止请求不得把页面推入错误态', async () => {
  const stale = loadPredictionSnapshot('S_A', 'risk')
  const fresh = loadPredictionSnapshot('S_A', 'biomass')
  await stale
  assert.notEqual(predictionSnapshot.loadState, 'error', '被中止的请求不得写错误态')
  snapshotCalls()[1].respond(payload('S_A', 'biomass', 'PRED_G1', 5))
  await fresh
  assert.equal(predictionSnapshot.loadState, 'ok')
})

test('加载失败保留已有结果，且不清空页面', async () => {
  const first = loadPredictionSnapshot('S_A', 'risk')
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 4))
  await first

  const failing = loadPredictionSnapshot('S_A', 'area')
  snapshotCalls()[1].fail('后端 503')
  await assert.rejects(failing)
  assert.equal(predictionSnapshot.loadState, 'ok', '已有结果时失败不得进入错误态')
  assert.equal(predictionSnapshot.horizons['3'].results.probability.value, 4, '旧结果必须保留')
})

test('仅在从未取得结果时失败才进入错误态', async () => {
  const failing = loadPredictionSnapshot('S_A', 'risk')
  snapshotCalls()[0].fail('后端 503')
  await assert.rejects(failing)
  assert.equal(predictionSnapshot.loadState, 'error')
  assert.match(predictionSnapshot.loadError, /503/)
})

test('三态诊断与区间三层结论按后端原样透出，不在前端放宽', async () => {
  const first = loadPredictionSnapshot('S_A', 'risk')
  const data = payload('S_A', 'risk', 'PRED_G1', 3)
  data.horizons['3'].entity_diagnostic = {
    numeric_variation: true,
    model_entity_response: false,
    comparison_usable: false,
    comparison_blocked_reason: 'synthetic_scenario_fallback_not_comparable',
    comparison_evidence: { value_origin: 'legacy_v0_2_synthetic_fallback', min_test_rows: 15 },
    value_origin: 'legacy_v0_2_synthetic_fallback',
    model_family: 'residual',
    sampled_entities: 80,
    distinct_values: 80,
    within_entity_spread: 12.5
  }
  snapshotCalls()[0].respond(data)
  await first

  const diag = entityDiagnostic(3)
  assert.equal(diag.numericVariation, true, '合成回退确实存在数值差异')
  assert.equal(diag.modelEntityResponse, false, '合成回退不得被当作真实模型响应')
  assert.equal(diag.comparisonUsable, false, '合成回退绝不可用于站点比较')
  assert.equal(diag.comparisonBlockedReason, 'synthetic_scenario_fallback_not_comparable')

  const interval = intervalState({ uncertainty: data.horizons['3'].results.probability.uncertainty })
  assert.equal(interval.isPredictionInterval, true)
  assert.equal(interval.structuralValid, false, '零宽退化必须判为结构无效')
  assert.equal(interval.calibrationStatus, 'validated', '校准证据层独立给出')
  assert.equal(interval.decisionUsable, false, '结构无效时决策不可用')
  assert.equal(interval.testN, 40)
  assert.equal(interval.empiricalCoverage, 0.975)
})

test('test_n=1 时前端不得显示"校准有效"', async () => {
  const first = loadPredictionSnapshot('S_A', 'chla')
  const data = payload('S_A', 'chla', 'PRED_G1', 3)
  data.horizons['3'].results.probability.uncertainty = {
    is_prediction_interval: true,
    structural_valid: true,
    interval_degenerate: false,
    calibration_status: 'insufficient_test_evidence',
    calibration_evidence: {
      status: 'insufficient_test_evidence',
      reason: '冻结测试集样本过少，经验覆盖率不具统计意义（test_n=1，阈值 15）',
      test_n: 1,
      empirical_coverage: 0.0,
      calibration_n: 31,
      min_test_n: 15
    },
    calibration_n: 31,
    test_n: 1,
    empirical_coverage: 0.0,
    decision_usable: false,
    decision_reason: '冻结测试集样本过少，经验覆盖率不具统计意义（test_n=1，阈值 15）'
  }
  snapshotCalls()[0].respond(data)
  await first

  const interval = intervalState({ uncertainty: data.horizons['3'].results.probability.uncertainty })
  assert.equal(interval.structuralValid, true)
  assert.notEqual(interval.calibrationStatus, 'validated')
  assert.equal(interval.decisionUsable, false)
  assert.match(interval.calibrationReason, /样本过少/)
})

test('双指纹随实体与指标变化', async () => {
  const first = loadPredictionSnapshot('S_A', 'chla')
  snapshotCalls()[0].respond(payload('S_A', 'chla', 'PRED_G1', 3))
  await first
  const a = predictionSnapshot.horizons['3']
  assert.equal(a.observed_input_fingerprint, 'S_A-obs')
  assert.equal(a.transformed_model_input_fingerprint, 'S_A-tfp-chla')
  assert.equal(a.fingerprint_schema, 'dual_fingerprint_v1')
})

test('在途请求与缓存规模受控', async () => {
  const p1 = loadPredictionSnapshot('S_A', 'risk')
  const p2 = loadPredictionSnapshot('S_B', 'risk')
  const internals = __predictionStoreInternals()
  assert.deepEqual(internals.inFlightEntities.sort(), ['S_A', 'S_B'])
  snapshotCalls()[0].respond(payload('S_A', 'risk', 'PRED_G1', 1))
  snapshotCalls()[1].respond(payload('S_B', 'risk', 'PRED_G1', 2))
  await Promise.all([p1, p2])
  assert.equal(__predictionStoreInternals().inFlightEntities.length, 0, '请求结束后必须清空在途表')
})
