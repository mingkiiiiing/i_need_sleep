// ============================================================
// InflowCard 纯函数（组件展示逻辑，供 node --test 直接回归）
// ------------------------------------------------------------
// 从 InflowCard.vue 抽出的无副作用函数，契约与组件内注释一致：
//   fmt           数值格式化：空态/null/不可解析 → '—'，绝不输出 NaN
//   classKey      水质类别 → 徽章配色 key（官方通报配色惯例）
//   worstTpMean12 全部断面近12月TP均值最大值（最差断面口径，3 位定点）
//   shortSource   数据来源超长截断（>14 字符加省略号）
// 本模块不依赖 Vue；mean_last12 空集返回 null 的契约在此显式兜底
// （null 按缺数跳过，不参与 Max 比较、不当 0 处理）。
// ============================================================

/** 数值格式化：null/undefined/非有限数 → '—'，其余按 digits 位定点输出。 */
export function fmt(v, digits) {
  return v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(digits)
}

/**
 * 水质类别 → 官方通报配色惯例：Ⅱ 优(青) / Ⅲ 良(绿) / Ⅳ 中(黄) / Ⅴ 差(红)。
 * 未收录类别（含 null/缺测/劣Ⅴ等）统一 'unknown' 中性样式。
 */
export function classKey(wqClass) {
  return wqClass === 'Ⅱ' ? 'excellent'
    : wqClass === 'Ⅲ' ? 'good'
    : wqClass === 'Ⅳ' ? 'moderate'
    : wqClass === 'Ⅴ' ? 'poor'
    : 'unknown'
}

/**
 * 全部断面近12月TP均值的最大值（一行摘要，宁取最差断面口径）。
 * sections 为空/非数组，或所有断面的 mean_last12.tp 均缺数（null/非有限数）时输出 '—'。
 */
export function worstTpMean12(sections) {
  const values = (Array.isArray(sections) ? sections : [])
    .map((s) => s?.mean_last12?.tp)
    .filter((v) => v != null && Number.isFinite(Number(v)))
    .map((v) => Number(v))
  return values.length ? Math.max(...values).toFixed(3) : '—'
}

/** 数据来源截断：超过 14 字符截为 14 字符 + 省略号；空值返回空串。 */
export function shortSource(source) {
  const s = source || ''
  return s.length > 14 ? `${s.slice(0, 14)}…` : s
}
