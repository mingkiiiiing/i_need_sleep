const fs = require('fs');
const p = 'src/pages/Stations.vue';
let c = fs.readFileSync(p, 'utf8');

// the anchor '// 趋势图 trendOption computed 内 selectedPoint.value.trend 加守卫' was overwritten earlier;
// instead, inject loadAi/refreshAi immediately after the trendOption computed closing
const anchor = 'const trendOption = computed(() => {';
if (!c.includes(anchor)) { console.log('NO ANCHOR'); process.exit(1); }

// find the matching closing '})' of trendOption
const startIdx = c.indexOf(anchor);
// walk to balance braces
let depth = 0, i = startIdx, endIdx = -1;
let inStr = null, inComment = false, inLineComment = false, inTpl = 0;
for (; i < c.length; i++) {
  const ch = c[i], prev = c[i-1], next = c[i+1];
  if (inLineComment) { if (ch === '\n') inLineComment = false; continue; }
  if (inComment) { if (prev === '*' && ch === '/') inComment = false; continue; }
  if (inTpl > 0) {
    if (ch === '`') inTpl--;
    else if (prev !== '\\' && ch === '$' && next === '{') { depth++; inTpl++; }
    continue;
  }
  if (inStr) {
    if (ch === inStr && prev !== '\\') inStr = null;
    continue;
  }
  if (ch === '/' && next === '/') { inLineComment = true; continue; }
  if (ch === '/' && next === '*') { inComment = true; i++; continue; }
  if (ch === '"' || ch === "'") { inStr = ch; continue; }
  if (ch === '`') { inTpl++; continue; }
  if (ch === '{') depth++;
  else if (ch === '}') { depth--; if (depth === 0) { endIdx = i + 1; break; } }
}

if (endIdx === -1) { console.log('NO END'); process.exit(1); }

// insert AFTER the endIdx (which points to the closing '}' + maybe ')' etc)
// we want to add loadAi/refreshAi right after the full `const trendOption = computed(...)` ends
// find the ')' that closes the computed()
let j = endIdx;
while (j < c.length && c[j] !== '\n') j++;
const insertionPoint = j; // newline position

const insert = [
  '',
  '// 链式调用：选中站点 -> predict -> explain',
  'async function loadAi(stationId) {',
  '  if (!stationId) return',
  '  aiLoading.value = true',
  '  aiError.value = \u0027\u0027',
  '  try {',
  '    const pred = await getPrediction(stationId)',
  '    prediction.value = pred',
  '    const fakePid = \u0027PRED-\u0027 + (pred.station_id || stationId) + \u0027-\u0027 + Date.now()',
  '    const exp = await getExplanation(fakePid)',
  '    explanation.value = exp',
  '  } catch (err) {',
  '    aiError.value = err && err.message ? err.message : \u0027AI 调用失败\u0027',
  '    prediction.value = null',
  '    explanation.value = null',
  '  } finally {',
  '    aiLoading.value = false',
  '  }',
  '}',
  '',
  'let _aiToken = 0',
  'async function refreshAiForSelected() {',
  '  const id = store.selectedPoint',
  '  const station = pointsState.value.pointData[id]',
  '  if (!station || !station._backendId) {',
  '    prediction.value = null',
  '    explanation.value = null',
  '    return',
  '  }',
  '  const token = ++_aiToken',
  '  await loadAi(station._backendId)',
  '  if (token !== _aiToken) return',
  '}',
  ''
].join('\n');

c = c.slice(0, insertionPoint) + insert + c.slice(insertionPoint);
fs.writeFileSync(p, c, 'utf8');
console.log('OK', fs.statSync(p).size);
