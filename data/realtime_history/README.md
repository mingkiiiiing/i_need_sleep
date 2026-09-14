# realtime_history —— 实时采集历史（随仓库分发的冻结档案）

本目录是 `data-cleaning/storage/silver/mee_realtime`（本机实时采集 silver 目录）在
**2026-09-14 15:00 (UTC+8)** 时点的冻结副本，四件套结构与 silver 完全一致：

| 文件 | 内容 |
| --- | --- |
| `stations.json` | 79 个 MEE 国控站点目录与坐标 |
| `snapshots.json` | 全部成功采集快照索引（滚动累积） |
| `observations.parquet` | 观测明细（站点 × 时点 × 指标） |
| `status.json` | 采集状态与 `as_of`（数据终点，**不外推**） |

## 后端如何使用它

`backend/app/providers.py` 的默认目录解析顺序：

1. 环境变量 `TAIHU_REALTIME_CATALOG_DIR`（显式指定优先）；
2. 本机实时采集目录 `data-cleaning/storage/silver/mee_realtime`（存在采集任务时，
   始终优先用它，页面展示最新实测）；
3. **本目录（冻结档案）**——队友克隆后即有实时轨数据，开箱即用；
4. 两处都缺失 → 实时轨如实报 `unavailable`（绝不回退模拟数据）。

冻结档案的 `freshness_status` 会随时间如实过期（数据时点见 `status.json` 的
`as_of`），这是诚实披露而非缺陷；接上采集任务后自动切回最新实测。

## 如何更新冻结档案

在开发机上把 silver 四件套重新复制到本目录并提交即可（采集状态以复制时刻为准）。
