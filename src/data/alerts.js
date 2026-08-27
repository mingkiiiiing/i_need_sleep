export const alertSeed = [
  {
    id: 'AL202505200015',
    title: '贡湖湾叶绿素 a 高风险',
    area: '太湖 / 贡湖湾 / 西北热点区',
    point: 'northwest_hotspot',
    severity: 'high',
    status: 'new',
    time: '10:15',
    date: '2025-05-20',
    metric: '叶绿素 a',
    value: 58.7,
    unit: 'μg/L',
    threshold: 40.0,
    exceedance: 1.47,
    probability: 82,
    trend: [39.8, 41.2, 43.6, 46.1, 49.8, 54.3, 58.7],
    source: '贡湖湾监测站 + 湖面风场',
    model: '太湖蓝藻风险预测模型 v2.3',
    updatedAt: '2025-05-20 09:50',
    confidence: '较高',
    owner: '未指派',
    responseTime: '—',
    factors: [
      { name: '水温偏高', value: 38 },
      { name: '总磷浓度偏高', value: 28 },
      { name: '风速降低', value: 18 }
    ],
    flow: [
      { label: '新预警', time: '10:15', done: true },
      { label: '已确认', time: '—', done: false },
      { label: '处理中', time: '—', done: false },
      { label: '已解决', time: '—', done: false },
      { label: '已关闭', time: '—', done: false }
    ],
    plan: {
      name: '贡湖湾蓝藻水华应急预案（III级）',
      match: 92,
      target: '叶绿素 a 高风险、蓝藻水华聚集风险',
      tasks: [
        { id: 'monitor', label: '贡湖湾加密监测（每3小时）', owner: '监测组', due: '05-20 13:00', checked: true },
        { id: 'inspect', label: '采集西北热点区藻情样品', owner: '巡查组', due: '05-20 12:00', checked: true },
        { id: 'control', label: '评估生态控藻措施（按规范）', owner: '处置组', due: '05-20 16:00', checked: true },
        { id: 'device', label: '核查贡湖湾增氧设备状态', owner: '运维组', due: '05-20 14:00', checked: false },
        { id: 'public', label: '发布贡湖湾风险提示', owner: '宣传组', due: '05-20 15:00', checked: false }
      ],
      updatedAt: '2025-04-18'
    },
    records: [
      { time: '2025-05-20 10:15', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值58.7 μg/L，概率82%' },
      { time: '2025-05-20 10:17', node: '预警确认', content: '预警已确认', actor: '王强（监测组）', note: '已核实监测数据' },
      { time: '2025-05-20 10:20', node: '指派处置', content: '已指派给处置组', actor: '李明（管理员）', note: '要求尽快制定处置方案' }
    ],
    audit: [
      { time: '2025-05-20 10:17:32', actor: '王强', content: '确认预警（AL202505200015）', result: '成功', ip: '10.0.1.23' },
      { time: '2025-05-20 10:20:45', actor: '李明', content: '指派处置（处置组）', result: '成功', ip: '10.0.1.15' },
      { time: '2025-05-20 10:21:03', actor: '张敏', content: '查看预案详情', result: '成功', ip: '10.0.1.28' }
    ]
  },
  {
    id: 'AL202505200014', title: '梅梁湖叶绿素 a 关注', area: '太湖 / 梅梁湖 / 湖心浮标', point: 'central_lake', severity: 'mid', status: 'processing', time: '09:52', date: '2025-05-20', metric: '叶绿素 a', value: 44.2, unit: 'μg/L', threshold: 40.0, exceedance: 1.11, probability: 68, trend: [35.1, 36.4, 37.8, 39.2, 40.8, 42.5, 44.2], source: '湖心浮标 + 湖面风场', model: '太湖蓝藻风险预测模型 v2.3', updatedAt: '2025-05-20 09:35', confidence: '中等', owner: '处置组', responseTime: '18分钟', factors: [{ name: '水温偏高', value: 32 }, { name: '水动力减弱', value: 24 }, { name: '营养盐累积', value: 16 }], flow: [{ label: '新预警', time: '09:52', done: true }, { label: '已确认', time: '09:58', done: true }, { label: '处理中', time: '10:08', done: true }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '梅梁湖蓝藻巡测应急预案（II级）', match: 84, target: '叶绿素 a 关注、湖心局地聚集风险', tasks: [{ id: 'monitor', label: '梅梁湖浮标加密采样（每3小时）', owner: '监测组', due: '05-20 13:00', checked: true }, { id: 'inspect', label: '复核湖心风场与藻情', owner: '巡查组', due: '05-20 12:00', checked: true }, { id: 'device', label: '核查湖心应急设备状态', owner: '运维组', due: '05-20 14:00', checked: false }], updatedAt: '2025-04-18' }, records: [{ time: '2025-05-20 09:52', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值44.2 μg/L，概率68%' }, { time: '2025-05-20 10:08', node: '开始处置', content: '处置组已接单', actor: '陈晨（处置组）', note: '进入湖心现场核验' }], audit: [{ time: '2025-05-20 10:08:12', actor: '陈晨', content: '开始处置（处置组）', result: '成功', ip: '10.0.1.19' }]
  },
  {
    id: 'AL202505200013', title: '蠡湖入湖总磷超标', area: '太湖 / 蠡湖 / 入湖河口', point: 'river_inlet', severity: 'high', status: 'processing', time: '09:41', date: '2025-05-20', metric: '总磷', value: 0.112, unit: 'mg/L', threshold: 0.08, exceedance: 1.4, probability: 76, trend: [0.071, 0.075, 0.079, 0.084, 0.091, 0.101, 0.112], source: '蠡湖入湖河口站', model: '太湖营养盐联动模型 v1.8', updatedAt: '2025-05-20 09:20', confidence: '较高', owner: '处置组', responseTime: '25分钟', factors: [{ name: '上游来水增加', value: 36 }, { name: '降雨冲刷', value: 27 }, { name: '交换流减弱', value: 15 }], flow: [{ label: '新预警', time: '09:41', done: true }, { label: '已确认', time: '09:46', done: true }, { label: '处理中', time: '10:02', done: true }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '蠡湖入湖营养盐应急预案（II级）', match: 79, target: '总磷超标、入湖负荷上升与藻类响应', tasks: [{ id: 'inspect', label: '开展入湖河口采样复核', owner: '巡查组', due: '05-20 12:00', checked: true }, { id: 'control', label: '核查上游来水与控源措施', owner: '处置组', due: '05-20 16:00', checked: false }], updatedAt: '2025-04-12' }, records: [{ time: '2025-05-20 09:41', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '总磷0.112 mg/L，超过阈值' }, { time: '2025-05-20 10:02', node: '开始处置', content: '处置组已接单', actor: '陈晨（处置组）', note: '安排入湖河口采样' }], audit: [{ time: '2025-05-20 10:02:21', actor: '陈晨', content: '开始处置（处置组）', result: '成功', ip: '10.0.1.19' }]
  },
  {
    id: 'AL202505200012', title: '长广溪叶绿素 a 早期聚集', area: '太湖 / 长广溪 / 南部通道', point: 'south_channel', severity: 'mid', status: 'assigned', time: '09:28', date: '2025-05-20', metric: '叶绿素 a', value: 36.8, unit: 'μg/L', threshold: 40.0, exceedance: 0.92, probability: 54, trend: [29.3, 30.1, 31.4, 32.6, 33.8, 35.2, 36.8], source: '长广溪监测站 + 水动力模型', model: '太湖蓝藻风险预测模型 v2.3', updatedAt: '2025-05-20 09:12', confidence: '中等', owner: '巡查组', responseTime: '—', factors: [{ name: '水温偏高', value: 28 }, { name: '风速降低', value: 19 }, { name: '交换流减弱', value: 13 }], flow: [{ label: '新预警', time: '09:28', done: true }, { label: '已确认', time: '09:31', done: true }, { label: '处理中', time: '—', done: false }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '长广溪早期聚集巡查预案（I级）', match: 71, target: '叶绿素 a 早期聚集、通道输运趋势', tasks: [{ id: 'monitor', label: '长广溪加密监测（每3小时）', owner: '监测组', due: '05-20 13:00', checked: false }, { id: 'inspect', label: '巡查南部通道藻情带', owner: '巡查组', due: '05-20 12:00', checked: false }], updatedAt: '2025-04-10' }, records: [{ time: '2025-05-20 09:28', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值36.8 μg/L，概率54%' }], audit: [{ time: '2025-05-20 09:31:44', actor: '王强', content: '指派处置（巡查组）', result: '成功', ip: '10.0.1.23' }]
  },
  {
    id: 'AL202505200011', title: '东太湖叶绿素 a 稳定', area: '太湖 / 东太湖 / 东南监测站', point: 'southeast_station', severity: 'low', status: 'resolved', time: '08:55', date: '2025-05-20', metric: '叶绿素 a', value: 22.4, unit: 'μg/L', threshold: 40.0, exceedance: 0.56, probability: 31, trend: [27.6, 26.8, 25.9, 24.8, 24.1, 23.2, 22.4], source: '东太湖监测站', model: '太湖蓝藻风险预测模型 v2.3', updatedAt: '2025-05-20 08:40', confidence: '较高', owner: '监测组', responseTime: '12分钟', factors: [{ name: '水温偏高', value: 18 }, { name: '历史聚集惯性', value: 12 }, { name: '风场稳定', value: 8 }], flow: [{ label: '新预警', time: '08:55', done: true }, { label: '已确认', time: '08:58', done: true }, { label: '处理中', time: '09:03', done: true }, { label: '已解决', time: '09:12', done: true }, { label: '已关闭', time: '—', done: false }], plan: { name: '东太湖常规监测预案（I级）', match: 66, target: '低风险聚集、趋势观察与取水安全', tasks: [{ id: 'monitor', label: '保持东太湖例行监测', owner: '监测组', due: '05-20 13:00', checked: true }], updatedAt: '2025-04-06' }, records: [{ time: '2025-05-20 08:55', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值22.4 μg/L，概率31%' }, { time: '2025-05-20 09:12', node: '标记已解决', content: '现场复核完成', actor: '王强（监测组）', note: '东太湖未发现明显聚集带' }], audit: [{ time: '2025-05-20 09:12:12', actor: '王强', content: '标记已解决', result: '成功', ip: '10.0.1.23' }]
  }
]

export function cloneAlerts() {
  return JSON.parse(JSON.stringify(alertSeed))
}
