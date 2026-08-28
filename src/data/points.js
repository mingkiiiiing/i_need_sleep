// 仅在本项目中作为 mock 数据源，后端接口完成后请将其替换为 services/api.js 中的真实请求。
// 数据结构保持稳定，方便直接从 mock 切到真实接口。

export const pointData = {
  northwest_hotspot: {
    id: 'northwest_hotspot',
    name: '西北热点区',
    short: 'NW-01',
    risk: '红色预警',
    riskClass: 'high',
    summary: '受高温、弱风和营养盐富集叠加影响，该区域藻类聚集扩张趋势明显，是当前重点关注的核心高风险点位。',
    coord: { lon: 120.08, lat: 31.42 },
    metrics: { density: '1.25e6 cells/L', chla: '42.8 ug/L', phosphorus: '0.091 mg/L', temp: '29.6 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['紧急封湖排查', '短期预警研判', '中期扩散预警', '长期态势推演', '30 天综合研判'],
      text: [
        '预计 24 小时内维持高密度聚集，建议立即启动巡查与封湖评估。',
        '短中期扩散概率上升，建议联动周边点位加密观测。',
        '若高温少风条件持续，热点可能向湖心方向延伸，需要关注水下分层。',
        '未来两周在营养盐补给减弱情景下风险缓慢下降，但需结合来水数据进行复核。',
        '30 天尺度上呈现“前高后稳”趋势，建议滚动更新机理模型参数。'
      ]
    },
    factors: [
      { name: '水温', value: 88, unit: '%' },
      { name: '风速', value: 76, unit: '%' },
      { name: '营养盐', value: 72, unit: '%' },
      { name: '历史聚集惯性', value: 64, unit: '%' }
    ],
    trend: [22, 28, 35, 48, 62, 71, 80, 86, 91, 88, 84, 78, 72, 66, 60, 54, 49, 45, 42, 40, 38, 37, 36, 35],
    timeline: [
      ['07-16 08:10', '系统开始记录', '近一周藻华波动数据入库，作为基线参考'],
      ['07-20 09:25', '风险缓慢上升', '藻细胞密度连续 3 日高于历史均值 18%'],
      ['07-23 10:05', '进入橙色关注窗口', '温度突破 28℃ 且风速降至 2 级以下'],
      ['07-30 10:50', '给出分时预警输出', '未来 3 天 / 7 天同步进入中、高档区间']
    ],
    explainability: [
      { driver: '水温', contribution: 0.34, direction: '正' },
      { driver: '风速', contribution: 0.21, direction: '负' },
      { driver: '总磷', contribution: 0.18, direction: '正' },
      { driver: '历史惯性', contribution: 0.12, direction: '正' }
    ]
  },
  central_lake: {
    id: 'central_lake',
    name: '湖心浮标',
    short: 'CN-02',
    risk: '橙色关注',
    riskClass: 'mid',
    summary: '湖心浮标承担连续遥测职责，是模型校准与全湖趋势研判的重要参考点位。',
    coord: { lon: 120.15, lat: 31.20 },
    metrics: { density: '8.5e5 cells/L', chla: '18.9 ug/L', phosphorus: '0.063 mg/L', temp: '28.4 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['关注聚集合并', '中位偏弱', '需持续校准', '波动上扬', '进入长期参考'],
      text: [
        '短期可能受湖面局部风向影响呈现向西北方漂移。',
        '中期趋势偏弱，建议加强与西北热点区的联动分析。',
        '长期适宜作为机理模型核心校准点，保持逐日采样。',
        '未来 15 天整体波动上扬，需关注风场扰动。',
        '30 天视角下进入长期参考区间，适合做稳定性比对。'
      ]
    },
    factors: [
      { name: '风向', value: 72, unit: '%' },
      { name: '水温', value: 68, unit: '%' },
      { name: '叶绿素 a', value: 54, unit: '%' },
      { name: '流速', value: 46, unit: '%' }
    ],
    trend: [24, 27, 29, 34, 36, 39, 41, 45, 47, 49, 51, 50, 48, 46, 44, 42, 41, 40, 39, 38, 37, 37, 36, 36],
    timeline: [
      ['07-16 08:25', '湖心浮标回传', '连续遥测数据完整，无缺测'],
      ['07-22 09:55', '趋势研判', '判定存在向西北热点区输送可能'],
      ['07-29 10:35', '联动建议', '建议结合湖面风场进行动态展示']
    ],
    explainability: [
      { driver: '风向', contribution: 0.29, direction: '正' },
      { driver: '水温', contribution: 0.24, direction: '正' },
      { driver: '流速', contribution: 0.16, direction: '正' },
      { driver: '历史惯性', contribution: 0.13, direction: '负' }
    ]
  },
  river_inlet: {
    id: 'river_inlet',
    name: '入湖河口',
    short: 'RI-03',
    risk: '橙色关注',
    riskClass: 'mid',
    summary: '入湖河口承担外源性营养盐输入监测任务，需要与上游水文数据同步分析。',
    coord: { lon: 119.96, lat: 31.32 },
    metrics: { density: '9.4e5 cells/L', chla: '24.6 ug/L', phosphorus: '0.082 mg/L', temp: '27.8 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['同步加密监测', '上游回流风险', '加强态势复核', '联动封湖评估', '长期输移参考'],
      text: [
        '建议与上游水文站点同步加密观测，捕捉脉冲式输入。',
        '短中期需评估上游回流入湖对热点的间接贡献。',
        '7 天尺度上外来输入仍是主导因子，建议联动下游点位。',
        '未来半月如果持续高输入，需开展封湖可行性评估。',
        '30 天尺度上作为外源输移参考点位保留。'
      ]
    },
    factors: [
      { name: '上游流量', value: 84, unit: '%' },
      { name: '营养盐', value: 71, unit: '%' },
      { name: '水温', value: 58, unit: '%' },
      { name: '风向', value: 49, unit: '%' }
    ],
    trend: [26, 30, 33, 38, 42, 47, 52, 56, 60, 63, 66, 65, 62, 58, 54, 50, 47, 44, 42, 40, 38, 37, 36, 35],
    timeline: [
      ['07-17 09:10', '上游流量跃升', '3 日均值较常年同期高出 22%'],
      ['07-24 10:20', '营养盐同步抬升', '总磷浓度上升触发关注阈值'],
      ['07-30 11:00', '联动研判输出', '建议加强与下游点位同步巡查']
    ],
    explainability: [
      { driver: '上游流量', contribution: 0.31, direction: '正' },
      { driver: '总磷', contribution: 0.22, direction: '正' },
      { driver: '水温', contribution: 0.15, direction: '正' },
      { driver: '历史惯性', contribution: 0.11, direction: '正' }
    ]
  },
  southeast_station: {
    id: 'southeast_station',
    name: '东南监测站',
    short: 'SE-04',
    risk: '绿色稳定',
    riskClass: 'low',
    summary: '东南站点位目前保持低风险稳定状态，是短期内的关键参照点。',
    coord: { lon: 120.28, lat: 31.05 },
    metrics: { density: '4.7e5 cells/L', chla: '11.4 ug/L', phosphorus: '0.041 mg/L', temp: '26.9 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['保持常规监测', '关注风场扰动', '维持绿区', '缓慢下降', '进入稳态参考'],
      text: [
        '短期维持当前低风险水平，无需特别响应。',
        '短中期如出现持续东南风，需关注热点区的扩散可能。',
        '7 天尺度上大概率维持绿色稳定状态。',
        '未来两周趋势缓慢下降，可作为负样本进行对照。',
        '30 天尺度上仍是稳态参考点，建议维持每周回传。'
      ]
    },
    factors: [
      { name: '风速', value: 48, unit: '%' },
      { name: '水温', value: 42, unit: '%' },
      { name: '流速', value: 36, unit: '%' },
      { name: '营养盐', value: 32, unit: '%' }
    ],
    trend: [16, 17, 18, 19, 20, 21, 21, 22, 22, 23, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10],
    timeline: [
      ['07-18 09:30', '常规巡检', '现场取样一致，水体感官正常'],
      ['07-25 10:50', '数据校准', '与浮标源数据比对一致'],
      ['07-30 11:20', '建议输出', '保持每周巡检一次即可']
    ],
    explainability: [
      { driver: '风速', contribution: 0.18, direction: '负' },
      { driver: '水温', contribution: 0.16, direction: '正' },
      { driver: '流速', contribution: 0.12, direction: '负' },
      { driver: '历史惯性', contribution: 0.10, direction: '负' }
    ]
  },
  water_intake: {
    id: 'water_intake',
    name: '取水口',
    short: 'WI-05',
    risk: '绿色稳定',
    riskClass: 'low',
    summary: '取水口当前处于安全范围，但因邻近热点扩散带，需保持联动巡查。',
    coord: { lon: 120.22, lat: 31.36 },
    metrics: { density: '5.0e5 cells/L', chla: '14.2 ug/L', phosphorus: '0.048 mg/L', temp: '27.1 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['需要邻近复检', '存在边界抬升', '重点保障点位', '风险可控', '回归常态'],
      text: [
        '建议与西北热点区联动查看风向变化。',
        '若热点外扩，取水口风险会较快上升。',
        '长期是应急预案中优先保障的关键点位。',
        '目前风险可控，但最近已出现小幅度抬升。',
        '30 天尺度上回归常态，应急资源建议滚动复盘。'
      ]
    },
    factors: [
      { name: '热点扩散', value: 66, unit: '%' },
      { name: '风向', value: 59, unit: '%' },
      { name: '流速', value: 35, unit: '%' },
      { name: '流速', value: 33, unit: '%' }
    ],
    trend: [16, 18, 19, 20, 21, 23, 24, 26, 29, 28, 26, 24, 22, 20, 18, 17, 16, 15, 14, 13, 12, 11, 11, 10],
    timeline: [
      ['07-18 08:40', '取水复检', '暂未发现明显聚集团带'],
      ['07-25 09:50', '风险比对', '与热点区联动风险已纳入监测'],
      ['07-30 10:45', '建议输出', '维持绿色状态下的重点巡查']
    ],
    explainability: [
      { driver: '热点扩散', contribution: 0.28, direction: '正' },
      { driver: '风向', contribution: 0.20, direction: '正' },
      { driver: '流速', contribution: 0.13, direction: '负' },
      { driver: '历史惯性', contribution: 0.10, direction: '正' }
    ]
  },
  south_channel: {
    id: 'south_channel',
    name: '南部通道',
    short: 'SC-06',
    risk: '橙色关注',
    riskClass: 'mid',
    summary: '南部通道承担输运连接作用，适合展示风险在湖区之间的传播路径。',
    coord: { lon: 120.12, lat: 30.96 },
    metrics: { density: '7.4e5 cells/L', chla: '17.3 ug/L', phosphorus: '0.058 mg/L', temp: '27.6 ℃' },
    forecast: {
      window: ['未来 1 天', '未来 3 天', '未来 7 天', '未来 15 天', '未来 30 天'],
      title: ['通量效应增强', '关注输运扩散', '建议保留追踪切面', '波动明显', '进入长期采样'],
      text: [
        '短期风险不高，但可能成为扩散路径。',
        '中期建议联动湖心浮标观察输运关系。',
        '长期可作为通道型机理建模示范。',
        '最近一周流速变化较大，风险曲线同步波动。',
        '30 天尺度上进入长期采样池，建议保留。'
      ]
    },
    factors: [
      { name: '流速', value: 77, unit: '%' },
      { name: '风向', value: 63, unit: '%' },
      { name: '总磷', value: 42, unit: '%' },
      { name: '水温', value: 37, unit: '%' }
    ],
    trend: [22, 25, 28, 31, 33, 35, 39, 41, 44, 46, 48, 47, 45, 42, 40, 38, 37, 36, 35, 34, 33, 32, 31, 30],
    timeline: [
      ['07-17 07:35', '水动力更新', '通道流速出现阶段性增强'],
      ['07-23 09:05', '模型预判', '判定存在中短期输运放大效应'],
      ['07-29 10:25', '建议推送', '建议保持通道切面连续观测']
    ],
    explainability: [
      { driver: '流速', contribution: 0.27, direction: '正' },
      { driver: '风向', contribution: 0.21, direction: '正' },
      { driver: '总磷', contribution: 0.14, direction: '正' },
      { driver: '水温', contribution: 0.12, direction: '正' }
    ]
  }
}

export const pointPositions = {
  northwest_hotspot: { top: '24%', left: '22%' },
  river_inlet: { top: '62%', left: '12%' },
  southeast_station: { top: '72%', left: '78%' },
  central_lake: { top: '45%', left: '52%' },
  water_intake: { top: '30%', left: '84%' },
  south_channel: { top: '82%', left: '40%' }
}

export const timeStages = [
  { key: 't1', label: '未来 1 天', short: '1 天', days: 1,  index: 0 },
  { key: 't3', label: '未来 3 天', short: '3 天', days: 3,  index: 1 },
  { key: 't7', label: '未来 7 天', short: '7 天', days: 7,  index: 2 },
  { key: 't15', label: '未来 15 天', short: '15 天', days: 15, index: 3 },
  { key: 't30', label: '未来 30 天', short: '30 天', days: 30, index: 4 }
]

// 全局事件流，按时间排序，覆盖三个页面的时间轴播放器
export const eventStream = [
  { id: 'e1', time: '07-16 08:10', stageKey: 't1',  point: 'northwest_hotspot', title: '系统基线入库',     summary: '近一周藻华波动数据正式入库，建立可比对基线。',          severity: 'low' },
  { id: 'e2', time: '07-17 07:35', stageKey: 't1',  point: 'south_channel',     title: '水动力阶段性增强', summary: '南部通道流速出现 38% 阶段性抬升，存在输运放大效应。',     severity: 'mid' },
  { id: 'e3', time: '07-17 09:10', stageKey: 't1',  point: 'river_inlet',       title: '上游流量跃升',     summary: '3 日均值较常年同期高出 22%，营养盐同步上升。',           severity: 'mid' },
  { id: 'e4', time: '07-18 08:40', stageKey: 't1',  point: 'water_intake',      title: '取水口例行复检',   summary: '暂未发现明显聚集带，但与热点距离被纳入监测。',           severity: 'low' },
  { id: 'e5', time: '07-18 09:30', stageKey: 't3',  point: 'southeast_station', title: '例行巡检通过',     summary: '现场取样一致，水体感官正常，作为负样本对照。',           severity: 'low' },
  { id: 'e6', time: '07-20 09:25', stageKey: 't3',  point: 'northwest_hotspot', title: '热点缓慢上升',     summary: '藻细胞密度连续 3 日高于历史均值 18%，系统上调 0.1 档。',  severity: 'mid' },
  { id: 'e7', time: '07-22 09:55', stageKey: 't7',  point: 'central_lake',      title: '湖心趋势研判',     summary: '判定存在向西北热点区的输送可能，建议加强风向联动。',     severity: 'mid' },
  { id: 'e8', time: '07-23 10:05', stageKey: 't7',  point: 'northwest_hotspot', title: '进入橙色窗口',     summary: '水温突破 28℃ 且风速降至 2 级以下，建议加密观测。',       severity: 'high' },
  { id: 'e9', time: '07-23 09:05', stageKey: 't15', point: 'south_channel',     title: '通道模型预判',     summary: '中期视角下通道承担扩散路径职责，建议保留切面追踪。',     severity: 'mid' },
  { id: 'e10',time: '07-24 10:20', stageKey: 't7',  point: 'river_inlet',       title: '营养盐同步抬升',   summary: '总磷浓度上升触发关注阈值，进入周报闭环。',               severity: 'mid' },
  { id: 'e11',time: '07-25 09:50', stageKey: 't15', point: 'water_intake',      title: '风险比对完成',     summary: '与热点区联动风险已纳入监测清单。',                       severity: 'low' },
  { id: 'e12',time: '07-25 10:50', stageKey: 't30', point: 'southeast_station', title: '数据校准完成',     summary: '与浮标源数据比对一致，作为稳态样本保留。',               severity: 'low' },
  { id: 'e13',time: '07-29 10:25', stageKey: 't30', point: 'south_channel',     title: '通道观测建议',     summary: '建议保持通道切面连续观测，进入 30 天评估。',             severity: 'mid' },
  { id: 'e14',time: '07-29 10:35', stageKey: 't30', point: 'central_lake',      title: '湖心联动建议',     summary: '建议结合湖面风场做动态展示，作为机理模型校准点。',       severity: 'mid' },
  { id: 'e15',time: '07-30 10:50', stageKey: 't30', point: 'northwest_hotspot', title: '分时预警输出',     summary: '未来 3 天与 7 天同步进入中高档区间，需要滚动更新机理参数。',  severity: 'high' }
]

// 用于 Heatmap 的风险场网格：每个 stage 一份，0-100 风险值
export const heatField = {
  t1:  ['h00','h00','h01','h02','h03','h04','h05','h06','h07','h08','h09','h10','h11','h12','h13','h14','h15','h16','h17','h18','h19'],
  t3:  ['h00','h01','h02','h03','h04','h05','h06','h07','h08','h09','h10','h11','h12','h13','h14','h15','h16','h17','h18','h19','h20'],
  t7:  ['h00','h00','h01','h02','h03','h04','h05','h06','h07','h08','h09','h10','h11','h12','h13','h14','h15','h16','h17','h18','h19'],
  t15: ['h00','h00','h01','h02','h03','h04','h05','h06','h07','h08','h09','h10','h11','h12','h13','h14','h15','h16','h17','h18','h19'],
  t30: ['h00','h00','h01','h02','h03','h04','h05','h06','h07','h08','h09','h10','h11','h12','h13','h14','h15','h16','h17','h18','h19']
}

// Heatmap 网格坐标 (相对坐标 0-100)，用于驱动可视化几何分布
// 行 row：上下分层；列 col：左右分层；val 越大越热
export const heatGrid = (() => {
  // 80 列 x 60 行的高分辨率风险场，按 stage 给出风险值
  const stages = {}
  const presets = {
    t1:  { center: [55, 80], northwest: [82, 60], inlet: [18, 70], channel: [40, 92], intake: [88, 40], southeast: [78, 90] },
    t3:  { center: [62, 70], northwest: [85, 65], inlet: [25, 76], channel: [48, 88], intake: [82, 45], southeast: [72, 84] },
    t7:  { center: [70, 60], northwest: [80, 70], inlet: [34, 72], channel: [55, 84], intake: [72, 50], southeast: [60, 78] },
    t15: { center: [60, 55], northwest: [70, 72], inlet: [42, 60], channel: [60, 78], intake: [62, 55], southeast: [54, 70] },
    t30: { center: [50, 50], northwest: [60, 70], inlet: [50, 50], channel: [50, 64], intake: [54, 56], southeast: [48, 60] }
  }
  Object.keys(presets).forEach((stageKey) => {
    const grid = []
    const def = presets[stageKey]
    for (let row = 0; row < 60; row++) {
      const rowArr = []
      for (let col = 0; col < 80; col++) {
        const x = (col + 0.5) / 80 * 100
        const y = (row + 0.5) / 60 * 100
        let val = 0
        // 叠加多个高斯热点，体现阶段扩散
        const hotspots = [
          { cx: def.northwest[0], cy: def.northwest[1], amp: stageKey === 't1' ? 92 : stageKey === 't3' ? 84 : 70, r: stageKey === 't1' ? 14 : 18 },
          { cx: def.inlet[0],     cy: def.inlet[1],     amp: stageKey === 't1' ? 60 : stageKey === 't7' ? 78 : 60, r: stageKey === 't1' ? 12 : 16 },
          { cx: def.center[0],    cy: def.center[1],    amp: stageKey === 't1' ? 40 : stageKey === 't3' ? 60 : stageKey === 't7' ? 70 : 52, r: 20 },
          { cx: def.channel[0],   cy: def.channel[1],   amp: stageKey === 't15' ? 58 : stageKey === 't30' ? 50 : 38, r: 16 },
          { cx: def.intake[0],    cy: def.intake[1],    amp: stageKey === 't1' ? 30 : stageKey === 't7' ? 60 : 40, r: 12 },
          { cx: def.southeast[0], cy: def.southeast[1], amp: stageKey === 't30' ? 38 : 24, r: 14 }
        ]
        hotspots.forEach((h) => {
          const dx = (x - h.cx) / h.r
          const dy = (y - h.cy) / h.r
          val += h.amp * Math.exp(-(dx * dx + dy * dy) / 1.4)
        })
        rowArr.push(Math.min(100, Math.round(val)))
      }
      grid.push(rowArr)
    }
    stages[stageKey] = grid
  })
  return stages
})()

// 区域汇总统计，用于 Cockpit 顶部 KPI
export const regionSummary = {
  totalStations: 6,
  riskCounts: { high: 1, mid: 3, low: 2 },
  // 当前 stage 下各点风险强度（0-100）
  intensity: {
    northwest_hotspot: { t1: 92, t3: 84, t7: 72, t15: 60, t30: 50 },
    central_lake:      { t1: 38, t3: 48, t7: 56, t15: 62, t30: 64 },
    river_inlet:       { t1: 58, t3: 64, t7: 70, t15: 64, t30: 54 },
    southeast_station: { t1: 22, t3: 26, t7: 30, t15: 28, t30: 22 },
    water_intake:      { t1: 30, t3: 38, t7: 50, t15: 46, t30: 40 },
    south_channel:     { t1: 40, t3: 50, t7: 58, t15: 62, t30: 60 }
  }
}
