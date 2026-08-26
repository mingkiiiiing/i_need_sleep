# 后端联调说明

当前是 **P0 模拟数据联调阶段**。所有接口均明确返回 `data_mode=simulated`、数据版本和 `claim_boundary=simulation_only`，不得用于真实监管、预警发布或模型效果宣传。

## 本地启动

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`。

前端默认请求 `/api/v1`，经 Vite 代理到本服务。后端失败时前端会显示错误；只有显式设置 `VITE_USE_MOCK=true` 才会使用前端 mock。

## P0 边界

- 六个驾驶舱对象均为 `demo_zone`，不是已核验真实站点；
- `DEMO-OBS-V1` 和 `DEMO-PRED-V1` 仅为固定演示样本；
- 1/3/7/15 天仅提供 `sample_interface_only` 演示接口；
- 30—90 天正式预测返回 `CAPABILITY_UNAVAILABLE`；T+30 地图仅是 `simulated_scenario` 预演；
- 解释接口仅返回 `demo_rule_contribution`，不是 SHAP；
- 模拟预警处理仅写演示响应，不发送短信、邮件或其他真实通知。

## 数据接入

P0 不提供任意 JSON records 上传，也不提供伪模型预测接口。后续将通过清洗发布物契约接入：`POST /api/v1/ingestion/releases`（待 P2 实现），并校验 manifest、哈希、schema、质量、版本与允许路径。
