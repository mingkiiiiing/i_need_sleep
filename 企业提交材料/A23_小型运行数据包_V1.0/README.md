# A23 小型运行数据包

本数据包用于比赛评审、离线演示和接口联调。包内同时提供一份可直接被当前后端读取的实时观测目录，以及一份不参与实时链路的模拟接口样例。

## 目录

- `realtime_catalog/`：复制到 `data-cleaning/storage/silver/mee_realtime/` 后，可供实时观测接口读取。包含 `stations.json`、`snapshots.json`、`observations.parquet` 和 `status.json`。
- `simulated/`：固定演示样例，仅用于理解字段和前端联调，不会自动覆盖实时目录。
- `manifest.json`：文件清单、版本和使用边界。

## 快速接入

在项目根目录执行：

```powershell
$env:TAIHU_REALTIME_CATALOG_DIR = (Resolve-Path '.\企业提交材料\A23_小型运行数据包_V1.0\realtime_catalog')
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

然后访问 `http://127.0.0.1:8000/docs`，或打开前端页面。先调用 `/api/v1/realtime/status` 检查 `available` 和 `freshness_status`，再调用实时汇总、站点和观测接口。

## 边界

- 目录中的实时快照是随比赛源码交付的运行样本，不代表当前生产数据，也不代表永久有效的站点数量。
- `simulated/` 中的样例标记为 `simulation_only`，不得用于真实监管、告警发布或模型效果结论。
- 替换实时数据时，必须同时更新四个文件，并先写入前三个文件，最后更新 `status.json`，确保 `status.latest_snapshot_id` 与 `snapshots.json` 最后一条记录一致。
