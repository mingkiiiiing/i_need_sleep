// 全局预测仓库（预测页唯一结果来源）。
//
// 设计目标：打开页面即有结果，只有数据更新才计算。
//   - 进入预测页读取一次 /model/v3/prediction-snapshot，服务端返回的是后台按实测快照
//     预生成的现成结果，因此首屏不需要等待模型运行；
//   - 切换时效（T+1…T+90）纯粹在内存中切换，不产生任何请求；
//   - 切换指标/实体读取对应快照，服务端同样命中预生成结果，不再运行模型；
//   - 定时轮询轻量的 /model/v3/prediction-status，只有 prediction_snapshot_id 变化
//     （实测数据或模型版本更新）才静默替换；替换期间页面继续展示旧结果，不遮挡。
//
// 并发正确性（修复"点谁都像同一套结果"）：
//   - 每个实体各自持有在途请求与 AbortController，不同站点的请求互不取消；
//   - 结果写入前校验「是否为最新一次请求」且「服务端回显 entity_id 与当前选择一致」，
//     因此快速连续切换站点时，先发的旧请求晚返回也不会覆盖新站点结果；
//   - 缓存键包含世代（prediction_snapshot_id）+ 实体 + 指标 + 模型版本，
//     实测数据或模型版本一变，整代缓存立即失效，不会把旧世代结果当新结果展示。
import { reactive } from 'vue'
import {
  getPredictionSnapshotEnvelope,
  getPredictionSnapshotStatusEnvelope
} from '../services/api.js'

const FOCUS_RESULT_KEY = {
  risk: 'probability',
  chla: 'chla',
  area: 'area',
  biomass: 'biomass',
  density: 'density'
}

// 同世代缓存上限：页面只会访问少量实体×指标组合，超出即淘汰最早的键。
const CACHE_LIMIT = 40

function emptyStatus() {
  return {
    state: 'unavailable',
    using_previous_success: false,
    last_error: null,
    pending_prediction_snapshot_id: null,
    stations: { ready: false, done: 0, total: 0 }
  }
}

export const predictionSnapshot = reactive({
  // 已应用（页面正在展示）的选择
  entityId: 'lake',
  focusMetric: 'risk',
  // 已请求（用户最新一次选择）的选择：响应回来时必须与之一致才允许写入页面
  requestedEntityId: 'lake',
  requestedMetric: 'risk',
  // 结果缓存世代：与 prediction_snapshot_id 对齐
  generation: '',
  // 结果：{ '1': {...}, '3': {...}, ... }，一次读取覆盖全部时效
  horizons: {},
  horizonList: [],
  trend: { points: [] },
  // 模型响应性诊断：哪些指标在该时效上真的随实体变化
  metricDiagnostics: {},
  entityDiagnostic: null,
  // 版本与状态：页面必须始终展示实测数据时间、预测生成时间、模型版本与结果状态
  predictionSnapshotId: '',
  sourceSnapshotId: '',
  generatedAt: '',
  modelVersion: '',
  cacheSchema: '',
  status: emptyStatus(),
  servedFromSnapshot: false,
  // 页面态：idle | loading | ok | error
  loadState: 'idle',
  loadError: '',
  lastLoadedAt: '',
  // 切换实体/指标时的轻量指示：已有结果时不进入 loading，避免整页闪回骨架
  switchPending: false
})

// 每个实体各自持有在途请求：不同站点的请求互不取消，只有同一实体的重复请求才取消。
const inFlight = new Map()
// 已取得的结果缓存，键 = `${generation}|${entity}|${metric}`
const payloadCache = new Map()

let latestToken = 0
let pollTimer = null

function rememberPayload(cacheKey, payload) {
  payloadCache.set(cacheKey, payload)
  if (payloadCache.size > CACHE_LIMIT) {
    payloadCache.delete(payloadCache.keys().next().value)
  }
}

function applyPayload(payload, entityId, focusMetric) {
  predictionSnapshot.horizons = payload.horizons || {}
  predictionSnapshot.horizonList = payload.horizon_list || []
  predictionSnapshot.trend = payload.trend || { points: [] }
  predictionSnapshot.metricDiagnostics = payload.metric_diagnostics || {}
  predictionSnapshot.predictionSnapshotId = payload.prediction_snapshot_id || ''
  predictionSnapshot.sourceSnapshotId = payload.source_snapshot_id || ''
  predictionSnapshot.generatedAt = payload.generated_at || ''
  predictionSnapshot.modelVersion = payload.model_version || ''
  predictionSnapshot.cacheSchema = payload.cache_schema || ''
  predictionSnapshot.status = { ...emptyStatus(), ...(payload.status || {}) }
  predictionSnapshot.servedFromSnapshot = Boolean(
    payload.snapshot_source && payload.snapshot_source.served_from_snapshot
  )
  predictionSnapshot.entityId = entityId
  predictionSnapshot.focusMetric = focusMetric
  predictionSnapshot.generation = payload.prediction_snapshot_id || predictionSnapshot.generation
  predictionSnapshot.lastLoadedAt = new Date().toISOString()
  predictionSnapshot.loadState = 'ok'
}

export function currentHorizonData(horizonDays) {
  return predictionSnapshot.horizons[String(horizonDays)] || null
}

export function focusResultKey(focusMetric) {
  return FOCUS_RESULT_KEY[focusMetric] || 'probability'
}

export function focusResult(horizonDays) {
  const data = currentHorizonData(horizonDays)
  if (!data) return null
  const key =
    (data.analysis_focus && data.analysis_focus.result_key) ||
    focusResultKey(predictionSnapshot.focusMetric)
  return (data.results || {})[key] || null
}

/** 双指纹：observed 证明"站点实测不同"，transformed 证明"模型最终输入矩阵不同"。 */
export function fingerprints(horizonDays) {
  const data = currentHorizonData(horizonDays)
  if (!data) {
    return { observed: '', transformed: '', schema: '', byTask: {}, transformedUnavailableReason: '' }
  }
  const resultKey =
    (data.analysis_focus && data.analysis_focus.result_key) ||
    focusResultKey(predictionSnapshot.focusMetric)
  const byTask = data.transformed_model_input_fingerprints || {}
  return {
    observed: data.observed_input_fingerprint || data.input_fingerprint || '',
    // 必须取当前焦点任务自己的指纹：顶层字段在旧缓存里固定为 risk 任务口径，
    // 只作兜底；合成回退/无真实 bundle 的任务没有指纹，由 unavailable reason 说明。
    transformed: byTask[resultKey] || data.transformed_model_input_fingerprint || '',
    schema: data.fingerprint_schema || '',
    byTask,
    transformedUnavailableReason: data.transformed_model_input_fingerprint_unavailable_reason || ''
  }
}

/** 三态诊断（与后端 prediction_snapshot 三态一一对应）。
 *
 * 注意：三者不可互相推导。数值不同 ≠ 模型对实体有响应 ≠ 可用于站点比较。
 * comparison_usable 由后端「来源 + 门禁 + 留出验证证据」共同决定，前端不得自行放宽。
 */
export function entityDiagnostic(horizonDays) {
  const diag = (currentHorizonData(horizonDays) || {}).entity_diagnostic
  if (!diag) return null
  return {
    numericVariation: Boolean(diag.numeric_variation ?? diag.entity_responsive),
    modelEntityResponse: Boolean(diag.model_entity_response),
    comparisonUsable: Boolean(diag.comparison_usable),
    comparisonBlockedReason: diag.comparison_blocked_reason || '',
    comparisonEvidence: diag.comparison_evidence || null,
    valueOrigin: diag.value_origin || '',
    seasonalLookupMode: diag.seasonal_lookup_mode || null,
    modelFamily: diag.model_family || '',
    modelRunId: diag.model_run_id || '',
    sampledEntities: diag.sampled_entities ?? null,
    distinctValues: diag.distinct_values ?? null,
    // 实体间极差（不是"站内极差"：统计对象是不同实体之间的取值差）
    withinEntitySpread: diag.within_entity_spread ?? null,
    constantValue: diag.constant_value ?? null,
    // 10% 提升门禁行状态（唯一来源 gate_table.json）：comparison_usable 的门禁证据
    gateStatus: diag.gate_status || '',
    gateNaReason: diag.gate_na_reason || '',
    // 产物身份：让页面直接说出"这一档用的是哪份模型文件"，不再靠拼名或猜测
    artifactId: diag.artifact_id || '',
    modelFile: diag.model_file || '',
    modelSha256: diag.model_sha256 || '',
    stationResolution: diag.station_resolution ?? null,
    // 判定依据：declared=结果自带声明；measured_station_spread=按本档实测站点离散度判定
    stationResolutionBasis: diag.station_resolution_basis || '',
    labelProvenance: diag.label_provenance || '',
    trainingProtocol: diag.training_protocol || '',
    longTermRoute: diag.long_term_route || null,
    calibrationStatus: diag.calibration_status || '',
    empiricalCoverage: diag.empirical_coverage ?? null,
    uncertaintyDecisionUsable: diag.uncertainty_decision_usable ?? null,
    testMetrics: diag.test_metrics || null
  }
}

/** 兼容旧调用：当前指标在当前时效上是否至少存在数值差异；null 表示诊断尚未可用。 */
export function entityResponsiveness(horizonDays) {
  const diag = entityDiagnostic(horizonDays)
  return diag ? diag.numericVariation : null
}

/** 指标级三态诊断：该指标在所有时效上的汇总结论。 */
export function metricDiagnostic(focusMetric) {
  const key = focusResultKey(focusMetric)
  const entry = (predictionSnapshot.metricDiagnostics || {})[key]
  if (!entry) return null
  return {
    numericVariation: Boolean(entry.numeric_variation ?? entry.entity_responsive),
    modelEntityResponse: Boolean(entry.model_entity_response),
    comparisonUsable: Boolean(entry.comparison_usable),
    variationHorizons: entry.variation_horizons || [],
    responsiveHorizons: entry.responsive_horizons || [],
    comparableHorizons: entry.comparable_horizons || [],
    nonResponsiveHorizons: entry.non_responsive_horizons || [],
    blockedReasons: entry.blocked_reasons || [],
    modelFamily: entry.model_family || '',
    modelRunId: entry.model_run_id || '',
    valueOrigin: entry.value_origin || ''
  }
}

/** 兼容旧调用：指标级是否至少存在数值差异。 */
export function metricResponsiveness(focusMetric) {
  const diag = metricDiagnostic(focusMetric)
  return diag ? diag.numericVariation : null
}

/** 来源语义：把 value_origin 翻译成页面可直接使用的比较口径。 */
export function sourceSemantics(valueOrigin) {
  if (valueOrigin === 'legacy_v0_2_synthetic_fallback') {
    return {
      kind: 'synthetic',
      label: '合成情景回退（V0.2 合成数据）',
      comparableClaim: '仅情景展示，不可作为真实站点预测或站点间比较依据'
    }
  }
  if (valueOrigin === 'derived_from_chla_v0_3_risk_bands') {
    return {
      kind: 'derived',
      // 审计口径（2026-09-11）：叶绿素 a 训练标签是"真实水质驱动 + 公示代理标签"，
      // 不得称"真实标签/真实模型"——模型是真实数据训练的，标签来源必须随行披露。
      label: '由叶绿素 a 月度趋势模型（代理标签）按冻结风险带推导',
      comparableClaim: '其可比性受叶绿素 a 模型验证证据约束'
    }
  }
  if (valueOrigin === 'v0_3_real_bundle') {
    return {
      kind: 'real',
      label: 'V0.3 真实数据模型',
      comparableClaim: '可比性取决于留出验证证据与校准证据'
    }
  }
  return { kind: 'unknown', label: valueOrigin || '未知来源', comparableClaim: '来源未知，不可比较' }
}

/**
 * 区间展示口径：把后端「结构自洽 / 校准证据 / 决策可用」三层结论翻译成页面状态。
 * 后端判定结构无效（点预测越界 / 零宽退化 / 非有限值）时，页面不得画成正常区间；
 * 校准证据不足（test_n=0/1）时，页面不得表述为"校准有效区间"。
 */
export function intervalState(resultBox) {
  const uncertainty = (resultBox || {}).uncertainty
  if (!uncertainty) return { available: false, valid: false, reason: '该指标未提供预测区间' }
  const evidence = uncertainty.calibration_evidence || {}
  const structuralValid =
    uncertainty.structural_valid !== undefined
      ? Boolean(uncertainty.structural_valid)
      : uncertainty.interval_valid !== false
  return {
    available: true,
    // 兼容字段：等价于结构自洽
    valid: structuralValid,
    degenerate: Boolean(uncertainty.interval_degenerate),
    low: uncertainty.p05,
    high: uncertainty.p95,
    point: uncertainty.point_value,
    reason: uncertainty.invalid_reason || uncertainty.structural_reason || '',
    // ① 结构层
    structuralValid,
    structuralReason: uncertainty.structural_reason || '',
    // ② 校准证据层
    isPredictionInterval: uncertainty.is_prediction_interval !== false,
    intervalSemantics: uncertainty.interval_semantics || '',
    calibrationStatus: uncertainty.calibration_status || 'unavailable',
    calibrationReason: evidence.reason || '',
    calibrationN: uncertainty.calibration_n ?? evidence.calibration_n ?? null,
    testN: uncertainty.test_n ?? evidence.test_n ?? null,
    empiricalCoverage: uncertainty.empirical_coverage ?? evidence.empirical_coverage ?? null,
    minTestN: evidence.min_test_n ?? null,
    // 行级区间退化（T4-sug-02）：校准/留出段逐行零宽占比；只读透出，不参与任何判定
    rowLevelDegeneracy: uncertainty.row_level_degeneracy ?? null,
    // ③ 决策层
    decisionUsable: Boolean(uncertainty.decision_usable),
    decisionReason: uncertainty.decision_reason || ''
  }
}

/**
 * 「模型评估」面板只读导出（2026-09-12 W2 新增，不改任何既有导出与行为）：
 * 返回当前焦点时效的完整模型评估诊断。
 *   - entityDiagnostic 原样透传（含 gate_status / gate_na_reason / comparison_evidence /
 *     test_metrics / calibration_status / empirical_coverage / uncertainty_decision_usable）；
 *   - 另补焦点任务 box uncertainty 的校准证据（test_n / calibration_n / 验收线 /
 *     标称覆盖率）——这些字段只挂在结果 box 上，entity_diagnostic 不含。
 * 只读聚合：不加工、不放宽、不编造字段；无数据时返回 null。
 */
export function focusEvaluation(horizonDays) {
  const data = currentHorizonData(horizonDays)
  if (!data) return null
  const diag = data.entity_diagnostic || null
  const key =
    (data.analysis_focus && data.analysis_focus.result_key) ||
    focusResultKey(predictionSnapshot.focusMetric)
  const box = (data.results || {})[key] || null
  const uncertainty = box?.uncertainty || null
  const evidence = uncertainty?.calibration_evidence || {}
  return {
    // 实体级诊断原样透传（字段名与 envelope 一致；全湖聚合口径为 null）
    entityDiagnostic: diag,
    gateStatus: diag?.gate_status ?? null,
    gateNaReason: diag?.gate_na_reason ?? null,
    comparisonEvidence: diag?.comparison_evidence ?? null,
    testMetrics: diag?.test_metrics ?? null,
    calibrationStatus: diag?.calibration_status ?? null,
    empiricalCoverage: diag?.empirical_coverage ?? null,
    uncertaintyDecisionUsable: diag?.uncertainty_decision_usable ?? null,
    // 焦点任务 box 的校准证据（entity_diagnostic 不含 test_n / 验收线，仅在 box 上）
    focusResultKey: key,
    testN: uncertainty?.test_n ?? evidence.test_n ?? null,
    calibrationN: uncertainty?.calibration_n ?? evidence.calibration_n ?? null,
    coverageAcceptanceMin:
      uncertainty?.calibration_evidence?.coverage_acceptance_min ??
      evidence.coverage_acceptance_min ??
      null,
    coverageTarget:
      uncertainty?.calibration_evidence?.coverage_target ?? evidence.coverage_target ?? null,
    coverageTolerance:
      uncertainty?.calibration_evidence?.coverage_tolerance ?? evidence.coverage_tolerance ?? null,
    boxDecisionUsable: uncertainty?.decision_usable ?? null
  }
}

/**
 * 读取预测快照。同一世代内、同一实体与指标已有结果时直接复用内存结果，不产生请求。
 */
export async function loadPredictionSnapshot(entityId, focusMetric, { force = false } = {}) {
  const entity = entityId || 'lake'
  const metric = focusMetric || 'risk'
  predictionSnapshot.requestedEntityId = entity
  predictionSnapshot.requestedMetric = metric

  const cacheKey = `${predictionSnapshot.generation}|${entity}|${metric}`
  if (!force && payloadCache.has(cacheKey)) {
    applyPayload(payloadCache.get(cacheKey), entity, metric)
    return predictionSnapshot
  }
  const pending = inFlight.get(entity)
  if (pending) {
    // 同一实体的同一指标且已在途：复用，不重复请求。
    if (pending.metric === metric && !force) return pending.promise
    // 同一实体换了指标或强制刷新：中止旧请求，避免旧指标结果覆盖新指标。
    pending.controller.abort()
    inFlight.delete(entity)
  }

  const token = ++latestToken
  const controller = new AbortController()
  const alreadyHasResult = predictionSnapshot.loadState === 'ok'
  if (!alreadyHasResult) predictionSnapshot.loadState = 'loading'
  predictionSnapshot.switchPending = alreadyHasResult
  predictionSnapshot.loadError = ''

  const promise = (async () => {
    try {
      const { data } = await getPredictionSnapshotEnvelope(entity, metric, {
        signal: controller.signal
      })
      // 三重写入守卫：① 必须是最新一次请求；② 服务端回显实体必须等于当前选择；
      // ③ 服务端回显指标必须等于当前选择。任一不满足即丢弃，杜绝切换后数据串站。
      if (token !== latestToken) return predictionSnapshot
      if (data.entity_id && data.entity_id !== predictionSnapshot.requestedEntityId) return predictionSnapshot
      if (data.focus_metric && data.focus_metric !== predictionSnapshot.requestedMetric) return predictionSnapshot
      // 按「本次结果所属世代」入缓存，而不是按请求发出时的世代：
      // 否则首屏那次加载会写进 `${''}|...` 键，之后 generation 已更新，同一世代内永远命不中。
      rememberPayload(
        `${data.prediction_snapshot_id || predictionSnapshot.generation}|${entity}|${metric}`,
        data
      )
      applyPayload(data, entity, metric)
      return predictionSnapshot
    } catch (error) {
      if (error && error.name === 'AbortError') return predictionSnapshot
      // 失败保留已有结果，只有从未取得任何结果时才进入错误态。
      if (token === latestToken && !predictionSnapshot.horizonList.length) {
        predictionSnapshot.loadState = 'error'
        predictionSnapshot.loadError = error?.message || '预测结果加载失败'
      }
      throw error
    } finally {
      const current = inFlight.get(entity)
      if (current && current.token === token) inFlight.delete(entity)
      if (token === latestToken) predictionSnapshot.switchPending = false
    }
  })()

  inFlight.set(entity, { controller, promise, token, metric })
  return promise
}

function updateStatus(data) {
  predictionSnapshot.status = {
    ...emptyStatus(),
    state: data.state,
    using_previous_success: data.using_previous_success,
    last_error: data.last_error,
    pending_prediction_snapshot_id: data.pending_prediction_snapshot_id,
    stations: data.stations || emptyStatus().stations
  }
}

/**
 * 轮询轻量状态：仅当 prediction_snapshot_id 变化才静默下载新结果。
 * 返回 true 表示发生了替换。
 */
export async function refreshPredictionStatus() {
  const { data } = await getPredictionSnapshotStatusEnvelope()
  const changed =
    Boolean(data.prediction_snapshot_id) &&
    data.prediction_snapshot_id !== predictionSnapshot.predictionSnapshotId
  if (!changed) {
    updateStatus(data)
    return false
  }
  // 世代已变：整代缓存立即失效，避免把旧世代的站点结果当成新结果返回。
  payloadCache.clear()
  try {
    await loadPredictionSnapshot(
      predictionSnapshot.requestedEntityId,
      predictionSnapshot.requestedMetric,
      { force: true }
    )
  } catch {
    // 静默失败：保留旧结果，下轮轮询重试。
  }
  return true
}

export function startPredictionPolling(intervalMs = 60000) {
  stopPredictionPolling()
  pollTimer = setInterval(() => {
    refreshPredictionStatus().catch(() => {})
  }, intervalMs)
}

export function stopPredictionPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * 仅供自动化测试使用：把仓库与在途请求重置到初始态。
 * 生产代码不得调用（浏览器端没有调用点）。
 */
export function __resetPredictionStoreForTest() {
  stopPredictionPolling()
  payloadCache.clear()
  for (const pending of inFlight.values()) pending.controller.abort()
  inFlight.clear()
  latestToken = 0
  predictionSnapshot.entityId = 'lake'
  predictionSnapshot.focusMetric = 'risk'
  predictionSnapshot.requestedEntityId = 'lake'
  predictionSnapshot.requestedMetric = 'risk'
  predictionSnapshot.generation = ''
  predictionSnapshot.horizons = {}
  predictionSnapshot.horizonList = []
  predictionSnapshot.trend = { points: [] }
  predictionSnapshot.metricDiagnostics = {}
  predictionSnapshot.entityDiagnostic = null
  predictionSnapshot.predictionSnapshotId = ''
  predictionSnapshot.sourceSnapshotId = ''
  predictionSnapshot.generatedAt = ''
  predictionSnapshot.modelVersion = ''
  predictionSnapshot.cacheSchema = ''
  predictionSnapshot.status = emptyStatus()
  predictionSnapshot.servedFromSnapshot = false
  predictionSnapshot.loadState = 'idle'
  predictionSnapshot.loadError = ''
  predictionSnapshot.lastLoadedAt = ''
  predictionSnapshot.switchPending = false
}

/** 仅供自动化测试使用：当前缓存与在途请求规模。 */
export function __predictionStoreInternals() {
  return { cacheSize: payloadCache.size, inFlightEntities: [...inFlight.keys()] }
}
