const pointData = {
  northwest_hotspot: {
    name: "西北热点区",
    risk: "橙色预警",
    riskClass: "high",
    summary: "受高温、弱风和营养盐富集叠加影响，该区域未来 72 小时存在明显聚集扩张趋势，是当前演示的核心高风险点位。",
    metrics: {
      density: "1.86e6 cells/L",
      chla: "32.4 ug/L",
      phosphorus: "0.087 mg/L",
      temp: "29.1 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["高风险扩张", "高位震荡", "需提前压降营养盐输入", "热点已连续抬升"],
      text: [
        "建议立即提高巡测频次，并将周边取水口纳入联查。",
        "若持续高温少风，热点范围会向沿岸带延伸。",
        "长期需联合控源与生态调度，降低复发强度。",
        "近 15 天该区域风险值已由 48 提升至 72。"
      ]
    },
    factors: [
      ["水温", 84],
      ["总磷", 76],
      ["风速", 58],
      ["流速", 41]
    ],
    timeline: [
      ["08:10", "遥感反演更新", "蓝藻覆盖面积较昨日增加 12%。"],
      ["09:30", "模型输出", "融合模型判定未来 72 小时进入扩张窗口。"],
      ["10:15", "联动建议", "建议启动橙色预警巡测方案。"]
    ],
    trend: [34, 39, 43, 47, 52, 58, 63, 67, 72]
  },
  river_inlet: {
    name: "入湖河口站",
    risk: "黄色关注",
    riskClass: "mid",
    summary: "该点位主要反映上游来水扰动与营养盐输入变化，对湖区中期风险有较强前导意义。",
    metrics: {
      density: "9.7e5 cells/L",
      chla: "21.6 ug/L",
      phosphorus: "0.095 mg/L",
      temp: "27.8 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["需持续观测", "趋势抬升", "重点控源断面", "输入扰动明显"],
      text: [
        "建议维持增密采样，关注降雨后入湖负荷变化。",
        "若上游来水持续偏高，中期风险将进一步上扬。",
        "该点位适合作为长期控源成效评估参考。",
        "近两周总磷输入波动明显，是当前主要异常来源。"
      ]
    },
    factors: [
      ["总磷", 81],
      ["来水流量", 69],
      ["氨氮", 55],
      ["气温", 44]
    ],
    timeline: [
      ["07:50", "自动站上报", "入湖断面总磷数据高于周均值。"],
      ["09:20", "模型校正", "机理参数已根据来水流量完成动态修正。"],
      ["11:00", "处置建议", "建议同步核查上游支流水质。"]
    ],
    trend: [28, 31, 35, 38, 42, 46, 49, 53, 57]
  },
  southeast_station: {
    name: "东南监测站",
    risk: "蓝色稳定",
    riskClass: "low",
    summary: "该区域水动力条件较好，目前整体稳定，可作为对照点观察全湖差异。",
    metrics: {
      density: "4.2e5 cells/L",
      chla: "12.1 ug/L",
      phosphorus: "0.041 mg/L",
      temp: "26.9 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["保持稳定", "低风险波动", "可持续跟踪", "整体平稳"],
      text: [
        "短期内无明显聚集趋势，维持常规监测即可。",
        "中期受外围热点影响较小，可作为稳定基准区。",
        "长期建议继续观察季节性回升情况。",
        "该点位过去两周风险值始终处于低位。"
      ]
    },
    factors: [
      ["流速", 62],
      ["光照", 48],
      ["水温", 44],
      ["总磷", 31]
    ],
    timeline: [
      ["08:00", "例行监测", "主要指标保持在安全区间。"],
      ["09:40", "模型输出", "未来三天维持低风险状态。"],
      ["10:50", "巡检建议", "维持常规巡检节奏。"]
    ],
    trend: [18, 19, 20, 21, 22, 21, 23, 22, 24]
  },
  central_lake: {
    name: "湖心浮标",
    risk: "黄色关注",
    riskClass: "mid",
    summary: "湖心浮标承担连续观测职责，是模型校准与全湖趋势研判的重要参考点位。",
    metrics: {
      density: "8.5e5 cells/L",
      chla: "18.9 ug/L",
      phosphorus: "0.063 mg/L",
      temp: "28.4 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["关注漂移聚集", "中位偏强", "需持续校准", "波动上扬"],
      text: [
        "短期内可能受风场影响向西北方向输运。",
        "中期趋势偏强，建议加强和热点区联动分析。",
        "长期适合作为机理模型参数校准核心点。",
        "近 15 天整体波动呈温和上行。"
      ]
    },
    factors: [
      ["风向", 72],
      ["水温", 68],
      ["叶绿素 a", 54],
      ["流速", 46]
    ],
    timeline: [
      ["08:25", "浮标回传", "连续观测数据完整，无缺测。"],
      ["09:55", "趋势研判", "判定存在向热点区输运可能。"],
      ["10:35", "联动建议", "建议结合风场进行动态展示。"]
    ],
    trend: [24, 27, 29, 34, 36, 39, 41, 45, 47]
  },
  water_intake: {
    name: "取水口",
    risk: "蓝色稳定",
    riskClass: "low",
    summary: "当前取水口尚处安全范围，但因靠近热点扩张带，需要保持联动巡查。",
    metrics: {
      density: "5.0e5 cells/L",
      chla: "14.2 ug/L",
      phosphorus: "0.048 mg/L",
      temp: "27.1 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["需贴近巡查", "存在边际抬升", "重点保障点位", "风险仍可控"],
      text: [
        "建议与西北热点区联动查看风向变化。",
        "若热点外扩，取水口风险会较快上升。",
        "长期是应急预案中优先保障的关键点位。",
        "目前风险可控，但最近已有小幅抬升。"
      ]
    },
    factors: [
      ["热点扩散", 66],
      ["风向", 59],
      ["浊度", 35],
      ["流速", 33]
    ],
    timeline: [
      ["08:40", "取水巡检", "暂未发现明显聚集漂浮带。"],
      ["09:50", "风险比对", "与热点区联动风险已纳入监测。"],
      ["10:45", "建议输出", "维持蓝色状态下的重点巡查。"]
    ],
    trend: [16, 18, 19, 20, 21, 23, 24, 26, 29]
  },
  south_channel: {
    name: "南部通道",
    risk: "黄色关注",
    riskClass: "mid",
    summary: "南部通道承担输运连接作用，适合展示风险在湖区之间的传播路径。",
    metrics: {
      density: "7.4e5 cells/L",
      chla: "17.3 ug/L",
      phosphorus: "0.058 mg/L",
      temp: "27.6 C"
    },
    forecast: {
      window: ["未来 1-3 天", "未来 7-15 天", "未来 30-90 天", "未来 15 天回看"],
      title: ["通道效应增强", "关注输运扩散", "建议保留跟踪断面", "波动明显"],
      text: [
        "短期风险不高，但可能成为扩散路径。",
        "中期建议联动湖心浮标观察输运关系。",
        "长期可作为通道型场景建模示例。",
        "最近一周流速变化较大，风险曲线同步波动。"
      ]
    },
    factors: [
      ["流速", 77],
      ["风向", 63],
      ["总磷", 42],
      ["水温", 37]
    ],
    timeline: [
      ["07:35", "水动力更新", "通道流速出现阶段性增强。"],
      ["09:05", "模型预判", "判定存在中短期输运放大效应。"],
      ["10:25", "建议推送", "建议保持通道断面连续观测。"]
    ],
    trend: [22, 25, 28, 31, 33, 35, 39, 41, 44]
  }
};

const timeStages = [
  { label: "T+1 天", index: 0 },
  { label: "T+3 天", index: 1 },
  { label: "T+7 天", index: 2 },
  { label: "T+15 天", index: 3 }
];

let activePoint = "northwest_hotspot";
let activeStage = 1;

const detailName = document.getElementById("detailName");
const detailRisk = document.getElementById("detailRisk");
const detailSummary = document.getElementById("detailSummary");
const metricDensity = document.getElementById("metricDensity");
const metricChla = document.getElementById("metricChla");
const metricPhosphorus = document.getElementById("metricPhosphorus");
const metricTemp = document.getElementById("metricTemp");
const forecastWindow = document.getElementById("forecastWindow");
const forecastTitle = document.getElementById("forecastTitle");
const forecastText = document.getElementById("forecastText");
const factorList = document.getElementById("factorList");
const timelineList = document.getElementById("timelineList");
const broadcastText = document.getElementById("broadcastText");
const globalRisk = document.getElementById("globalRisk");
const globalWindow = document.getElementById("globalWindow");
const timeLabel = document.getElementById("timeLabel");
const timeRange = document.getElementById("timeRange");
const mapPoints = document.querySelectorAll(".map-point");

function createBarRow(name, value) {
  const row = document.createElement("div");
  row.className = "factor-row";
  row.innerHTML = `
    <div class="factor-meta"><span>${name}</span><strong>${value}</strong></div>
    <div class="factor-track"><div class="factor-fill" style="width:${value}%"></div></div>
  `;
  return row;
}

function createTimelineItem(time, title, text) {
  const row = document.createElement("div");
  row.className = "timeline-item";
  row.innerHTML = `
    <div class="timeline-time">${time}</div>
    <div>
      <strong>${title}</strong>
      <p>${text}</p>
    </div>
  `;
  return row;
}

function renderTrend(values) {
  const canvas = document.getElementById("trendCanvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(255,255,255,0.02)";
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = "rgba(16,37,29,0.08)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = 20 + ((h - 38) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(18, y);
    ctx.lineTo(w - 18, y);
    ctx.stroke();
  }

  const startX = 24;
  const endX = w - 24;
  const stepX = (endX - startX) / (values.length - 1);
  const min = Math.min(...values) - 6;
  const max = Math.max(...values) + 6;

  ctx.beginPath();
  values.forEach((value, index) => {
    const x = startX + stepX * index;
    const y = h - 24 - ((value - min) / (max - min)) * (h - 54);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });

  const gradient = ctx.createLinearGradient(0, 0, w, 0);
  gradient.addColorStop(0, "#78d9c3");
  gradient.addColorStop(0.5, "#84c98f");
  gradient.addColorStop(1, "#e86e58");
  ctx.strokeStyle = gradient;
  ctx.lineWidth = 4;
  ctx.stroke();

  ctx.lineTo(endX, h - 18);
  ctx.lineTo(startX, h - 18);
  ctx.closePath();

  const fill = ctx.createLinearGradient(0, 20, 0, h);
  fill.addColorStop(0, "rgba(15, 143, 132, 0.25)");
  fill.addColorStop(1, "rgba(15, 143, 132, 0.03)");
  ctx.fillStyle = fill;
  ctx.fill();
}

function renderPoint(pointKey) {
  const data = pointData[pointKey];
  if (!data) return;

  detailName.textContent = data.name;
  detailRisk.textContent = data.risk;
  detailRisk.className = `risk-badge ${data.riskClass}`;
  detailSummary.textContent = data.summary;
  metricDensity.textContent = data.metrics.density;
  metricChla.textContent = data.metrics.chla;
  metricPhosphorus.textContent = data.metrics.phosphorus;
  metricTemp.textContent = data.metrics.temp;
  forecastWindow.textContent = data.forecast.window[activeStage];
  forecastTitle.textContent = data.forecast.title[activeStage];
  forecastText.textContent = data.forecast.text[activeStage];
  globalRisk.textContent = data.risk;
  globalWindow.textContent = timeStages[activeStage].label;
  broadcastText.textContent = `${data.name}：${data.forecast.text[activeStage]}`;

  factorList.innerHTML = "";
  data.factors.forEach(([name, value]) => factorList.appendChild(createBarRow(name, value)));

  timelineList.innerHTML = "";
  data.timeline.forEach(([time, title, text]) => timelineList.appendChild(createTimelineItem(time, title, text)));

  renderTrend(data.trend);
}

mapPoints.forEach((point) => {
  point.addEventListener("click", () => {
    mapPoints.forEach((item) => item.classList.remove("active"));
    point.classList.add("active");
    activePoint = point.dataset.point;
    renderPoint(activePoint);
  });
});

timeRange.addEventListener("input", () => {
  activeStage = Number(timeRange.value);
  const scene = timeStages[activeStage];
  timeLabel.textContent = scene.label;
  renderPoint(activePoint);
});

renderPoint(activePoint);
