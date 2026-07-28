const fs = require('fs');
const p = 'src/pages/Stations.vue';
let c = fs.readFileSync(p, 'utf8');

c = c.replace(
  "import { getPoints, getRegionSummary, getTimeStages } from '../services/api.js'",
  "import { getPoints, getRegionSummary, getTimeStages, getPrediction, getExplanation } from '../services/api.js'"
);

const oldRefs = "const summary = ref({ totalStations: 6, riskCounts: { high: 0, mid: 0, low: 0 } })";
const newRefs = [
  "const summary = ref({ totalStations: 6, riskCounts: { high: 0, mid: 0, low: 0 } })",
  "const prediction = ref(null)",
  "const explanation = ref(null)",
  "const aiLoading = ref(false)",
  "const aiError = ref('')",
  "const aiTab = ref('predict')"
].join('\n');
c = c.replace(oldRefs, newRefs);

// 双向 store.selectedPoint 触发刷新
const setPointNew = [
  "function setPoint(id) {",
  "  store.selectedPoint = id",
  "  refreshAiForSelected()",
  "}"
].join('\n');
c = c.replace(/function setPoint\(id\) \{\s*store\.selectedPoint = id\s*\}/m, setPointNew);

// loadAi + refreshAiForSelected
const append = [
  "",
  "// 链式调用：选中站点 -> predict 拿 prediction_id -> explain",
  "async function loadAi(stationId) {",
  "  if (!stationId) return",
  "  aiLoading.value = true",
  "  aiError.value = ''",
  "  try {",
  "    const pred = await getPrediction(stationId)",
  "    prediction.value = pred",
  "    const fakePid = 'PRED-' + (pred.station_id || stationId) + '-' + Date.now()",
  "    const exp = await getExplanation(fakePid)",
  "    explanation.value = exp",
  "  } catch (err) {",
  "    aiError.value = err && err.message ? err.message : 'AI 调用失败'",
  "    prediction.value = null",
  "    explanation.value = null",
  "  } finally {",
  "    aiLoading.value = false",
  "  }",
  "}",
  "",
  "let _aiToken = 0",
  "async function refreshAiForSelected() {",
  "  const id = store.selectedPoint",
  "  const station = pointsState.value.pointData[id]",
  "  if (!station || !station._backendId) {",
  "    prediction.value = null",
  "    explanation.value = null",
  "    return",
  "  }",
  "  const token = ++_aiToken",
  "  await loadAi(station._backendId)",
  "  if (token !== _aiToken) return",
  "}",
  ""
].join('\n');
const anchor = "// 趋势图 trendOption computed 内 selectedPoint.value.trend 加守卫";
c = c.replace(anchor, append + anchor);

// onMounted 末尾加 refreshAiForSelected
const oldMount = "  stages.value = s\n  pointsState.value = p\n  summary.value = r\n})";
const newMount = "  stages.value = s\n  pointsState.value = p\n  summary.value = r\n  refreshAiForSelected()\n})";
c = c.replace(oldMount, newMount);

// modelBars + sensitivityOption 在 setup 末尾
const sentinel = "onMounted(async () => {";
const suffix = [
  "const modelBars = computed(() => {",
  "  if (!prediction.value || !prediction.value.model_comparison) return []",
  "  const mc = prediction.value.model_comparison",
  "  const arr = [",
  "    { key: 'm', label: '机理模型', value: mc.mechanism_model },",
  "    { key: 'a1', label: 'AI 模型 1', value: mc.ai_model_1 },",
  "    { key: 'a2', label: 'AI 模型 2', value: mc.ai_model_2 },",
  "    { key: 'f', label: '融合模型', value: mc.fusion_model }",
  "  ]",
  "  const max = Math.max(...arr.map(a => a.value), 50)",
  "  return arr.map(a => ({ ...a, pct: Math.min(100, Math.round((a.value / max) * 100)) }))",
  "})",
  "",
  "const sensitivityOption = computed(() => {",
  "  const sc = (explanation.value && explanation.value.sensitivity_curve) || []",
  "  return {",
  "    tooltip: { trigger: 'axis' },",
  "    legend: { data: sc.map(s => s.factor), textStyle: { color: '#a9bcd4' }, top: 0 },",
  "    grid: { left: 40, right: 20, top: 28, bottom: 28, containLabel: true },",
  "    xAxis: { type: 'category', data: (sc[0] && sc[0].values) || [], axisLine: { lineStyle: { color: 'rgba(120,200,220,0.18)' } }, axisLabel: { color: '#6f8aa3' } },",
  "    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: '#6f8aa3' }, splitLine: { lineStyle: { color: 'rgba(120,200,220,0.08)' } } },",
  "    series: sc.map((s, i) => ({",
  "      name: s.factor, type: 'line', smooth: true,",
  "      lineStyle: { width: 2, color: ['#22d3c5', '#a78bfa', '#ff7b6b'][i % 3] },",
  "      itemStyle: { color: ['#22d3c5', '#a78bfa', '#ff7b6b'][i % 3] },",
  "      data: s.response",
  "    }))",
  "  }",
  "})",
  ""
].join('\n');
c = c.replace(sentinel, suffix + sentinel);

fs.writeFileSync(p, c, 'utf8');
console.log('OK', fs.statSync(p).size);
