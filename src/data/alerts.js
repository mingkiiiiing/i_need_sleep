export const alertSeed = [
  {
    id: 'AL202505200015',
    title: '贡湖湾叶绿素a高风险',
    area: '江苏省 / 无锡市 / 滨湖区',
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
    source: '监测站 + 通感气象',
    model: '藻类风险预测模型 v2.3',
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
      name: '贡湖湾藻类水华应急预案（III级）',
      match: 92,
      target: '叶绿素a高风险、水华爆发风险',
      tasks: [
        { id: 'monitor', label: '加强监测频次（每3小时）', owner: '监测组', due: '05-20 13:00', checked: true },
        { id: 'inspect', label: '开展藻情巡查与样品采集', owner: '巡查组', due: '05-20 12:00', checked: true },
        { id: 'control', label: '投加生态控藻剂（按规范）', owner: '处置组', due: '05-20 16:00', checked: true },
        { id: 'device', label: '启动增氧设备运行', owner: '运维组', due: '05-20 14:00', checked: false },
        { id: 'public', label: '发布风险提示与科普宣传', owner: '宣传组', due: '05-20 15:00', checked: false }
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
    id: 'AL202505200014', title: '梅梁湖蓝藻水华风险', area: '江苏省 / 无锡市 / 滨湖区', point: 'central_lake', severity: 'mid', status: 'processing', time: '09:52', date: '2025-05-20', metric: '叶绿素 a', value: 44.2, unit: 'μg/L', threshold: 40.0, exceedance: 1.11, probability: 68, source: '浮标监测 + 风场', model: '藻类风险预测模型 v2.3', updatedAt: '2025-05-20 09:35', confidence: '中等', owner: '处置组', responseTime: '18分钟', factors: [{ name: '水温偏高', value: 32 }, { name: '水动力减弱', value: 24 }, { name: '营养盐累积', value: 16 }], flow: [{ label: '新预警', time: '09:52', done: true }, { label: '已确认', time: '09:58', done: true }, { label: '处理中', time: '10:08', done: true }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '梅梁湖蓝藻水华应急预案（II级）', match: 84, target: '叶绿素a关注、局地聚集风险', tasks: [{ id: 'monitor', label: '加强监测频次（每3小时）', owner: '监测组', due: '05-20 13:00', checked: true }, { id: 'inspect', label: '开展藻情巡查与样品采集', owner: '巡查组', due: '05-20 12:00', checked: true }, { id: 'device', label: '启动增氧设备运行', owner: '运维组', due: '05-20 14:00', checked: false }], updatedAt: '2025-04-18' }, records: [{ time: '2025-05-20 09:52', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值44.2 μg/L，概率68%' }, { time: '2025-05-20 10:08', node: '开始处置', content: '处置组已接单', actor: '陈晨（处置组）', note: '进入现场核验' }], audit: [{ time: '2025-05-20 10:08:12', actor: '陈晨', content: '开始处置（处置组）', result: '成功', ip: '10.0.1.19' }]
  },
  {
    id: 'AL202505200013', title: '蠡湖总磷超标风险', area: '江苏省 / 无锡市 / 滨湖区', point: 'river_inlet', severity: 'high', status: 'processing', time: '09:41', date: '2025-05-20', metric: '总磷', value: 0.112, unit: 'mg/L', threshold: 0.08, exceedance: 1.4, probability: 76, source: '入湖河口站', model: '营养盐联动预测模型 v1.8', updatedAt: '2025-05-20 09:20', confidence: '较高', owner: '处置组', responseTime: '25分钟', factors: [{ name: '上游来水增加', value: 36 }, { name: '降雨冲刷', value: 27 }, { name: '交换流减弱', value: 15 }], flow: [{ label: '新预警', time: '09:41', done: true }, { label: '已确认', time: '09:46', done: true }, { label: '处理中', time: '10:02', done: true }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '入湖河口营养盐应急预案（II级）', match: 79, target: '总磷超标、入湖负荷上升', tasks: [{ id: 'inspect', label: '开展藻情巡查与样品采集', owner: '巡查组', due: '05-20 12:00', checked: true }, { id: 'control', label: '投加生态控藻剂（按规范）', owner: '处置组', due: '05-20 16:00', checked: false }], updatedAt: '2025-04-12' }, records: [{ time: '2025-05-20 09:41', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '总磷0.112 mg/L，超过阈值' }, { time: '2025-05-20 10:02', node: '开始处置', content: '处置组已接单', actor: '陈晨（处置组）', note: '安排河口采样' }], audit: [{ time: '2025-05-20 10:02:21', actor: '陈晨', content: '开始处置（处置组）', result: '成功', ip: '10.0.1.19' }]
  },
  {
    id: 'AL202505200012', title: '长广溪水体富营养化风险', area: '江苏省 / 无锡市 / 惠山区', point: 'south_channel', severity: 'mid', status: 'assigned', time: '09:28', date: '2025-05-20', metric: '叶绿素 a', value: 36.8, unit: 'μg/L', threshold: 40.0, exceedance: 0.92, probability: 54, source: '监测站 + 水动力模型', model: '藻类风险预测模型 v2.3', updatedAt: '2025-05-20 09:12', confidence: '中等', owner: '巡查组', responseTime: '—', factors: [{ name: '水温偏高', value: 28 }, { name: '风速降低', value: 19 }, { name: '交换流减弱', value: 13 }], flow: [{ label: '新预警', time: '09:28', done: true }, { label: '已确认', time: '09:31', done: true }, { label: '处理中', time: '—', done: false }, { label: '已解决', time: '—', done: false }, { label: '已关闭', time: '—', done: false }], plan: { name: '长广溪日常巡查预案（I级）', match: 71, target: '富营养化趋势、早期聚集风险', tasks: [{ id: 'monitor', label: '加强监测频次（每3小时）', owner: '监测组', due: '05-20 13:00', checked: false }, { id: 'inspect', label: '开展藻情巡查与样品采集', owner: '巡查组', due: '05-20 12:00', checked: false }], updatedAt: '2025-04-10' }, records: [{ time: '2025-05-20 09:28', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值36.8 μg/L，概率54%' }], audit: [{ time: '2025-05-20 09:31:44', actor: '王强', content: '指派处置（巡查组）', result: '成功', ip: '10.0.1.23' }]
  },
  {
    id: 'AL202505200011', title: '绿化河道藻类聚集风险', area: '江苏省 / 无锡市 / 新吴区', point: 'southeast_station', severity: 'low', status: 'resolved', time: '08:55', date: '2025-05-20', metric: '叶绿素 a', value: 22.4, unit: 'μg/L', threshold: 40.0, exceedance: 0.56, probability: 31, source: '监测站', model: '藻类风险预测模型 v2.3', updatedAt: '2025-05-20 08:40', confidence: '较高', owner: '监测组', responseTime: '12分钟', factors: [{ name: '水温偏高', value: 18 }, { name: '历史聚集惯性', value: 12 }, { name: '风场稳定', value: 8 }], flow: [{ label: '新预警', time: '08:55', done: true }, { label: '已确认', time: '08:58', done: true }, { label: '处理中', time: '09:03', done: true }, { label: '已解决', time: '09:12', done: true }, { label: '已关闭', time: '—', done: false }], plan: { name: '绿化河道日常监测预案（I级）', match: 66, target: '低风险聚集、趋势观察', tasks: [{ id: 'monitor', label: '加强监测频次（每3小时）', owner: '监测组', due: '05-20 13:00', checked: true }], updatedAt: '2025-04-06' }, records: [{ time: '2025-05-20 08:55', node: '新预警', content: '系统自动生成预警', actor: '系统', note: '预测值22.4 μg/L，概率31%' }, { time: '2025-05-20 09:12', node: '标记已解决', content: '现场复核完成', actor: '王强（监测组）', note: '未发现明显聚集带' }], audit: [{ time: '2025-05-20 09:12:12', actor: '王强', content: '标记已解决', result: '成功', ip: '10.0.1.23' }]
  }
]

export function cloneAlerts() {
  return JSON.parse(JSON.stringify(alertSeed))
}
