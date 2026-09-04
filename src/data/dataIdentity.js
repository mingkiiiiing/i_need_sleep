// 全站唯一的数据身份事实来源：数据模式、数据集版本、基准时间与使用边界
// 一律从这里引用，任何页面/组件不得另行硬编码口径文案。
// 当前阶段全部展示数据均为脚本生成的演示数据，不来自真实观测或模型输出。

export const dataIdentity = Object.freeze({
  lakeName: '太湖',
  dataMode: 'SIMULATED',
  dataModeLabel: '演示数据',
  datasetVersionId: 'DEMO-OBS-V1',
  predictionRunId: 'DEMO-PRED-V1',
  asOfLabel: '基准 08:00',
  asOfFull: '2026-08-24 08:00',
  claimBoundary: '非决策用途',
  claimNote:
    '本系统全部数据均为演示用模拟数据，不代表任何真实监测或预测结果，不得用于任何实际决策。',
  // 「查看来源」抽屉逐条展示的口径字段
  provenance: Object.freeze([
    {
      label: '观测数据集',
      value: 'DEMO-OBS-V1',
      note: '脚本生成的模拟观测序列，非卫星/浮标实测数据'
    },
    {
      label: '预测数据集',
      value: 'DEMO-PRED-V1',
      note: '规则推演生成的模拟预测，非算法模型输出'
    },
    {
      label: '基准时间',
      value: '2026-08-24 08:00',
      note: '演示数据统一的生成基准时间'
    },
    {
      label: '数据载体',
      value: '后端演示接口 + 前端静态常量',
      note: '业务页经 /api/v1 调用本地 FastAPI 演示服务，首页缩略态势为前端常量；均为脚本生成的演示数据'
    },
    {
      label: '使用限制',
      value: '非决策用途',
      note: '仅用于功能演示与交互联调'
    }
  ])
})
