// 历史文件清理（2026-09-13，台账 L-t5-04）：
// 本文件原为"全情景数据"时代的全站数据身份常量（dataMode=SCENARIO、DEMO-OBS-V1、
// DEMO-PRED-V1、DEMO-RUN-V1、asOf/claimBoundary/provenance 等全部为情景口径）。
// 该口径已与当前真实数据版本不符，且经全仓 grep 确认除 lakeName 外无任何页面/测试消费，
// 误导性旧口径字段已整段删除。
// 现仅保留仍被 src/pages/Home.vue 引用的湖名常量。
// 数据身份口径（数据集版本、数据模式、使用边界等）以后端接口 meta 与页面实际
// 数据身份标签为准，前端不得再硬编码全站口径文案。
// @deprecated 新代码请勿在本文件追加任何口径字段；湖名如需新引用点请另建常量模块。

export const lakeName = '太湖'

// 兼容旧导入路径（src/pages/Home.vue: import { dataIdentity as identity }）：
// 仅保留 lakeName，其余字段已随旧"全情景数据"口径一并移除。
export const dataIdentity = Object.freeze({ lakeName })
