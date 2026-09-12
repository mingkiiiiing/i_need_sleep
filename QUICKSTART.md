# 快速开始（正式版 v1.1）

队友克隆本仓库后，**数据已随仓库附带**（小型运行数据包 + 34 个模型文件 + 遥感图层 rs_overlays 123 个），无需额外下载。三条命令跑起来：

```powershell
# 1. 一键安装（自动创建 backend/.venv + pip 依赖 + npm 依赖 + 数据校验）
python scripts/setup_a23.py

# 2. 一键启动（后端 8000 + 前端 5173，幂等：已在跑会自动复用）
powershell -ExecutionPolicy Bypass -File start-a23-dev.ps1

# 3. 打开验收
#    前端大屏：http://127.0.0.1:5173
#    API 健康：http://127.0.0.1:8000/api/health   （product_id=taihu-a23-algae-warning）
```

要求：Python >= 3.10、Node.js >= 18（npm 随附）。Windows 直接可用；其他系统用 `python3`/`npm` 等价命令。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `setup_a23.py` 报数据文件缺失 | 克隆不完整，重新 `git clone`（确认含 `企业提交材料/A23_小型运行数据包_V1.0/` 与 `backend/model_runtime_v0_3/models/`） |
| 8000 端口被占 | `powershell -ExecutionPolicy Bypass -File start-a23-dev.ps1 -BackendPort 8001`（前端代理自动跟随） |
| 首次打开页面数值为空 | 后端启动后快照预热约 1~2 分钟，稍候刷新 |
| 只想校验不安装 | `python scripts/setup_a23.py --check` |

## 版本与数据口径（v1.1）

- 门禁现状：42 行比较 = **6 PASS / 24 FAIL / 12 NA**（提升≥10% 未全达，门禁如实 FAIL 上页面）
- 区间覆盖率：留出段经验覆盖率 **97.5%**（标称 90% + 容差 2% 口径，标 `validated`）
- 模型：v0.3，34 个 joblib（`backend/model_runtime_v0_3/models/`）；数据版本 `TAIHU_CLEAN_FINAL_V1_20260831`
- 解释口径：is_shap=false（敏感性分析，非 SHAP，页面如实标注）
- 站点口径：79 站采集 → 56 有坐标 → 48 可信上图

更完整的部署细节见 `企业提交材料/A23_环境与部署说明_V1.0.docx`；启动脚本的幂等与端口说明见 `docs/部署验证_运行记录_20260912.md`。
