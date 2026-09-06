// 全站唯一的数据身份事实来源：数据模式、数据集版本、基准时间与使用边界
// 一律从这里引用，任何页面/组件不得另行硬编码口径文案。
// 当前阶段全部展示数据均为脚本生成的情景数据，不来自真实观测或模型输出。

export const dataIdentity = Object.freeze({
  lakeName: '太湖',
  dataMode: 'SCENARIO',
  dataModeLabel: '情景数据',
  // 观察域数据集版本（后端观察类接口 meta.dataset_version）
  datasetVersionId: 'DEMO-OBS-V1',
  // 预测域数据集版本（后端预测类接口 meta.dataset_version）
  predVersionId: 'DEMO-PRED-V1',
  // 预测运行 ID（后端 meta.prediction_run_id，事件/格网/预测结果共同归属）
  predictionRunId: 'DEMO-RUN-V1',
  asOfLabel: '基准 08:00',
  asOfFull: '2026-08-24 08:00',
  claimBoundary: '非决策用途',
  // 使用边界代码（后端 meta.claim_boundary）
  claimBoundaryCode: 'simulation_only',
  claimNote:
    '本系统全部数据均为情景用情景数据，不代表任何真实监测或预测结果，不得用于任何实际决策。',
  // 「查看来源」抽屉逐条展示的口径字段
  provenance: Object.freeze([
    {
      label: '观测数据集',
      value: 'DEMO-OBS-V1',
      note: '脚本生成的情景观测序列，非卫星/浮标实测数据'
    },
    {
      label: '预测数据集',
      value: 'DEMO-PRED-V1',
      note: '规则推演生成的情景推演，非算法模型输出'
    },
    {
      label: '预测运行',
      value: 'DEMO-RUN-V1',
      note: '情景事件、风险格网与预测结果共同归属的运行编号（prediction_run_id）'
    },
    {
      label: '基准时间',
      value: '2026-08-24 08:00',
      note: '情景数据统一的生成基准时间'
    },
    {
      label: '数据载体',
      value: '后端情景接口 + 前端静态常量',
      note: '业务页经 /api/v1 调用本地 FastAPI 情景服务，首页缩略态势为前端常量；均为脚本生成的情景数据'
    },
    {
      label: '使用限制',
      value: '非决策用途',
      note: '仅用于功能情景与交互联调'
    }
  ])
})
