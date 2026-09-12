# 校准审计（K4：审查证据固化与覆盖率复算工具）

- 日期：2026-09-12
- 负责人：K4
- 写区：`backend/trust_audit/`（本轮仅新增，未改任何原件/台账/看板/模型）
- 只读对象：`不确定性专项审查_20260912/`、`model_runtime_v0_3/{models,runs,manifest}`、`backend/calibration_work/`
- 约束遵守：未 git commit/push/tag；未改台账与看板；未改审查证据原件、K1 产物、模型、serving、训练代码。

---

## 1. 本轮审查证据文件（路径与用途）

审查证据根：`D:\Project\fuwai\项目完整汇总_2026-08-31\不确定性专项审查_20260912\`（**只读原件，勿改**）。

| 文件 | 用途 | 关键内容 |
| --- | --- | --- |
| `audit.py` | 审查执行脚本：拉 API 快照 + 用模型内嵌分位数复算六组覆盖率并写 `evidence.json` | 引 `model_runtime_v0_3/code`；读 `interval_audit/artifact_run_map.csv`；对六组读 `runs/*/test_predictions.csv` |
| `evidence.json` | **审查主证据**：快照状态 + 70 行 API 响应 + 六组独立复算 | `recomputed`：六组 variant/horizon/run/n/covered/coverage/serving_clipped_coverage/recorded/residual_p05/p95/sha256；`rows`：全湖与拖山站 7 时效各指标的 value/p05/p95/status(undercovered)/test_n/coverage/usable |
| `lake.json` | 全湖（entity_id=`lake`）`prediction-snapshot` 原始 API 响应 | horizons 1/3/7/15/30/60/90 的 results、acceptance、trend、metric_diagnostics；`prediction_snapshot_id` |
| `mee-b80df03e.json` | 拖山站点（entity_id=`mee-b80df03e`）同款原始 API 响应 | 同上，供站点级抽查与前端显示核对 |
| `sources.json` | 审查结论的数据源登记（schemaVersion 1） | coverage-recomputed 查询：范围、caveats（覆盖率为评估段统计非站点独立校准证据）、六行结果表（80.30/85.47/76.92/79.49/74.36/81.20%） |
| `audit.ipynb` | `audit.py` 生成的可检查伴生 notebook（代码同 audit.py 主体） | 只读复核用，重跑仅写审查目录内 |
| `审查结论与解决方案.md` | 审查结论与整改方案（背景，不改） | 欠覆盖事实、K1/K2/K3 分工依据 |

### 复算工具新增产物（本区，可改）

| 文件 | 用途 |
| --- | --- |
| `backend/trust_audit/interval_coverage_recheck.py` | **六组覆盖率独立复算工具**（只读模型文件 + 测试预测，不重训） |
| `backend/trust_audit/interval_coverage_recheck_20260912.json` | 复算结果：六组对账 + 逐行测试段明细（340KB） |

---

## 2. 复跑命令（一条命令）

在 `backend` 目录下，用项目 venv：

```bash
cd "/d/Project/fuwai/项目完整汇总_2026-08-31/01_我们的开发/backend"
.venv/Scripts/python.exe trust_audit/interval_coverage_recheck.py
```

- 自定义输出：`... interval_coverage_recheck.py --out <path.json>`
- 退出码：`0` = 六组全部与审查一致；`2` = 存在不一致或产物缺口（便于自动化判读）。
- 依赖：仅 venv 内 `joblib/numpy/pandas/scikit-learn`（本机实测 python 3.13.9 / numpy 2.5.1 / pandas 3.0.5 / sklearn 1.9.0）。
- 实测耗时：**约 7.5 秒**（2026-09-12 两次独立复跑：一次约 5–7 秒、一次 7.5 秒，`time` 实测 real 0m7.504s；6 个 bundle 反序列化 + 6 张测试表，共 717 行）。
- 复跑记录：2026-09-12 末次复跑退出码 `0`，stdout 打印"六组复算与审查 evidence.json 完全一致（覆盖率/覆盖数/样本数/分位数/模型 sha256）"，输出 JSON 的 `summary.all_reconcile_pass = true`、`gaps_count = 0`。
- **不重新训练、不 import 训练代码做重放**，仅 `sys.path` 引入 `model_runtime_v0_3/code` 供 joblib 反序列化 bundle 类定义；因此规避 K1 记录的训练代码版本漂移。

复算口径 = 审查同款：`区间 = prediction + bundle.residual_p05/p95`；serving 物理裁剪（下界 `max(.,0)`；density 有界输出上界 `min(.,1)`）。

---

## 3. 校准证据 schema 草案（供 K1 与后续对齐）

目标：统一"校准段（生成分位数）"与"测试段（核算覆盖率）"两类逐行证据，使后续任何校准产物可直接与本工具/审查对账。

### 3.1 逐行字段（必需）

| 字段 | 类型 | 含义 | 本工具测试段取值 | K1 残差池取值 |
| --- | --- | --- | --- | --- |
| `sample_id` | str | 行唯一标识 | `test_predictions.csv` 的 `row_id` | `row_id`（监督底表行号） |
| `time` | str `YYYY-MM` | 样本时间 | `month`（输入月） | `month` + `target_month`（被预测月） |
| `space_unit` | str | 空间单元 | 测试表未含，需 join `features_base.parquet` 的 station 列 | `station_id`（站点/全湖实体） |
| `prediction` | float | 点预测 | `prediction` 列 | `prediction` |
| `actual` | float | 实际/标签值 | `actual` 列 | `actual` |
| `residual` | float | `actual - prediction` | 已含（本工具 `residual`） | `residual` |
| `fold_id` / `fold_role` | str | 折号与折中角色 | 测试块（无折号，记 `test`） | `fold_id`（OOF late 折 / CV 校准块）、`fold_role`、`in_fit_months` |
| `source` | str | 样本来源段 | `test`（测试段） | `oof` \| `validation`（严格分开） |
| `model_sha256` | str | 模型身份锚点 | 已含（bundle 文件 sha256） | `model_sha256` |
| `label_source` | str | 标签来源/口径 | `label_provenance`（chla T+1 混合、T+90 全代理；density/biomass 取自映射表） | `actual_provenance`（`ground_truth` \| `chla_station_proxy_v1`） |
| `run_id` / `protocol` | str | run 与评估协议 | `run_dir`、`artifact_id`、bundle `split_protocol` | `run_id`、`protocol` |

### 3.2 分组/汇总字段（必需）

`metric`（chla|density|biomass）、`horizon_days`、`calibration_n`、`residual_p05`、`residual_p95`、`n_test`、`covered`、`coverage`、`coverage_target`（0.90）、`acceptance_line`（0.88 = 0.90−0.02 容差）、`serving_clip_rule`。

### 3.3 本工具 JSON 已落地的实际字段（可与草案映射）

`interval_coverage_recheck_20260912.json` → `cases[]`：

- 身份/身份锚点：`artifact_id / run_dir / model_file / model_sha256 / test_predictions_sha256 / bundle_type`
- 分位数/口径：`residual_p05 / residual_p95 / residual_width / calibration_n / uncertainty_meta_* / serving_upper_clip`
- 覆盖率：`n_test / covered_raw / covered_serving_clipped / coverage_raw / coverage_serving_clipped / coverage_raw_pct / coverage_probability_col`
- 对账：`reconciliation{covered_match,n_match,coverage_match,serving_clipped_match,p05_match,p95_match,sha256_match,all_match}`
- 逐行：`rows[]{sample_id,month,prediction,actual,residual,lower_raw,upper_raw,lower_serving,upper_serving,covered_raw,covered_serving}`

> 草案与现状的已知差异：① 测试段 `space_unit` 未落（测试表无站点列，需 join 底层 parquet）；② `fold_id` 测试段记 `test`；③ `density/biomass` 的 `label_source` 取自 `artifact_run_map.csv`（bundle `uncertainty_meta` 未带该字段，工具已用 `label_provenance_source` 标注来源）。

---

## 4. 与 K1 产物（`backend/calibration_work/`）的对应关系

K1 负责"校准段证据重建"（生成分位数的残差池逐行重建）；K4 负责"覆盖率复算固化"（测试段逐行核算）。两者**互补且不重叠**，均只读模型文件。

| 维度 | K4（本区 trust_audit/） | K1（calibration_work/） |
| --- | --- | --- |
| 覆盖组 | 六组（chla/density/biomass × T+1/T+90） | 仅 chla T+1/T+90 |
| 样本段 | **测试段**（`runs/*/test_predictions.csv`，717 行） | **校准段**（OOF + validation 残差池，chla T+1=234、T+90=225 行） |
| 产出 | `interval_coverage_recheck_20260912.json`（对账 + 逐行测试明细） | `residual_pool_T5-chla_T+{1,90}_mo{0,3}.{csv,json}`、`rebuild_summary.json`、`reconcile_*.json`、`pool_analysis.json` |
| 用途 | 固化六组覆盖率事实、与审查 evidence 对账 | 重建分位数来源池、验证 OOF 未见性、供 K2 假设检验 |
| 交集（chla 两组） | 复算 106/132=80.30%、100/117=85.47% | 复算 106/132=80.30%、100/117=85.47%（`coverage_recheck.json`） |
| 模型身份 | 六组文件 sha256（与 evidence.json 比对，全一致） | 同源 chla 两模型 sha256（`model_identity.json`） |

对应结论：
- **数字完全一致**：K4 六组复算与审查 `evidence.json` 逐项相等（覆盖率/覆盖数/n/分位数/sha256），其中 chla 两组同时与 K1 `coverage_recheck.json` 相等——三方（审查、K1、K4）交叉印证。
- **证据链闭环**：K1 证明"分位数来自训练期 OOF+validation 池"（校准段，`pool_*`）；K4 证明"该分位数在测试段只覆盖 74–85%"（测试段，`rows[]`）。合起来支撑台账 A 组"真实欠覆盖、非汇总口径错"。
- **schema 对齐建议**：K1 `residual_pool_schema.json` 已定义 `row_id/station_id/month/target_month/source/prediction/actual/residual/actual_provenance/model_sha256/run_id/protocol`；建议后续新增校准产物直接采用 §3 草案，使 `source` 增加 `test`、`fold_role` 覆盖测试段，即可让校准段与测试段同表对账。
- **可扩展缺口**：K1 报告 §10.3 指出 density/biomass 四组尚未重建残差池（脚本已参数化）；本 K4 工具已覆盖四组**覆盖率**复算，但对应的**残差池逐行证据仍缺**（见 §5 缺口 g-01）。

---

## 5. 缺口与如实说明

| 编号 | 缺口 | 说明 |
| --- | --- | --- |
| g-01 | density/biomass 四组无逐行残差池 | K1 仅重建 chla T+1/T+90 的 OOF+validation 池；K4 覆盖率可复算（数字齐全），但"分位数如何从池中产生"的四组逐行证据仍待补（K1 脚本参数化可扩展，但需先核对该四组训练代码版本，K1 报告 §7 已发现版本漂移） |
| g-02 | 测试段无空间单元列 | `test_predictions.csv` 仅 `prediction/probability/actual/month/row_id`，无站点/湖区列；schema §3.1 的 `space_unit` 需 join `supervised/features_base.parquet` 才能补齐 |
| g-03 | density/biomass 标签口径标注不一致 | bundle `uncertainty_meta` 未带 `label_provenance`，工具回退取 `artifact_run_map.csv`：density=`proxy_derived`、biomass=`ground_truth`；而 T4 报告称 biomass 目标无实测来源列（proxy 契约）。二者存在口径冲突，建议由主控裁定统一标注（工具已用 `label_provenance_source` 如实标出来源） |
| g-04 | 覆盖率测试段非冻结段 | 六组覆盖率均在**训练期内留出块**（117/132 模型测试段）核算，非 2024+ 冻结段独立样本；冻结段区间证据仍缺口（与 K1 §10.5 一致） |
| g-05 | 代理标签口径 | chla T+1 校准段混合、T+90 全代理；density/biomass 为代理契约——区间语义应继续按 `proxy_derived` 披露，不得宣称实测真值覆盖达标 |
| g-06 | probability 列口径 | 六个测试表均含 `probability` 列，本工具额外给出 `coverage_probability_col`（探测用，非主口径）；六组两口径覆盖率恰好相同，未发现 prediction/probability 数值分叉 |

**无法复算的组：无。** 六组模型文件与测试预测产物齐全，均已成功复算；`summary.gaps_count = 0`。

---

## 6. 建议入台账条目（供主控转录，本轮不自行改台账）

| 建议编号 | 明细 | 证据 | 建议状态 |
| --- | --- | --- | --- |
| K4-01 | 六组覆盖率独立复算工具固化：一条命令可复跑，结果与审查 `evidence.json` 六组**全部一致**（含分位数与模型 sha256），与 K1 chla 两组亦一致 | `interval_coverage_recheck.py`、`interval_coverage_recheck_20260912.json` | 待验证（与 A 组 L-cal-01..06 一致） |
| K4-02 | 审查证据文件用途已登记，复跑命令与 schema 草案落 `README_校准审计.md`，供 K1/后续校准对齐 | 本 README §1–§4 | 备忘 |
| K4-03 | density/biomass 四组残差池逐行证据仍缺（g-01），覆盖率可算但分位数来源池未重建 | K1 报告 §10.3、本 README §5 | 新增待验证（K1 扩展） |
| K4-04 | density/biomass 标签口径标注冲突：映射表 biomass=`ground_truth` vs T4 报告 proxy 契约（g-03） | `artifact_run_map.csv`、`T4_解释与不确定性审计报告_20260912.md` | 新增待验证（待主控裁定） |
| K4-05 | 六组覆盖率测试段均为训练期留出块、非冻结段（g-04/g-05），区间语义须按代理口径披露 | 本 README §5、K1 §10.5 | 待验证（与既有条目一致） |

---

## 附：本工具未做的事（遵守纪律）

- 未改 `不确定性专项审查_20260912/` 原件、未改 K1 `calibration_work/` 产物、未改模型/serving/训练代码、未改台账与看板。
- 未 git commit/push/tag。
- 未重新训练、未重放训练管线、未用测试残差改任何分位数；仅只读模型内嵌分位数与已保存的测试预测。
- 未宣称校准达标；六组欠覆盖事实不变。
