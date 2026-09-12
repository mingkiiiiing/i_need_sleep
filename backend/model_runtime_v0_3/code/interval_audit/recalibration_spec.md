# 重校准执行规范（recalibration_spec）

- 版本：v1.0（离线审计稿）
- 成文日期：2026-09-12
- 作者：开发员 W3（区间审计离线任务）
- **文档性质：只写规范，本轮不执行重放。** 本文所有"现状"均为只读核实结果；
  所有"方案/验收"为执行规范，须在批准后另行实施。
- 依据材料：`artifact_run_map.md`、`reuse_conditions.md`、`width_degeneracy_report.md`
  （同目录，均由只读脚本生成，命令与时间戳见各文件）。

---

## 1. 现状（只读核实，逐条给证据）

### 1.1 逐行校准残差未持久化

- `models/*.joblib` 的 `ResidualIntervals` 只存 **4 个数值字段**：`residual_p05`、`residual_p95`、
  `calibration_n`、`coverage_target`（+method/calibration_source 字符串）。
  校准残差池本身（训练期 OOF 残差 + validation 残差的 np 数组）在
  `training_real.py` 训练函数内即用即弃，**未写盘**（已核实该文件 conformal 段代码：
  pooled → np.quantile → ResidualIntervals，无任何持久化语句）。
- `runs/<run>/uncertainty.json` 只有汇总：`calibration_n` / `calibration_source` /
  `empirical_coverage_test` / `test_n` / `residual_quantile_levels`，无逐行残差、无分位数值。
- `runs/<run>/test_predictions.csv` 只存**留出（test）段**逐行预测：
  density/biomass/chla-90d 各 117 行、chla cv T+1/3/7/15 各 132 行、bloom/probability frozen 各 40 行、
  T+30/60 cv 各 5 行；不含校准段（OOF/validation）任何行。
- 后果：**当前无法从交付包重建校准池，也无法自证 0.975/0.769 等覆盖率数字的残差来源**。
  宽度体检发现的"同任务族 T+1/3/7/15 残差分位逐位相同"（bloom/probability p05=-0.3510、
  p95=0.0000；density off0 四行同为 0.7487；biomass off0 四行同为 21.0279；chla off0 四行同为 9.9820）
  指向"残差池按任务族共享/未逐时效独立校准"，在残差不持久化的现状下无法证伪。

### 1.2 附带核实的口径事实（重放前必须知道）

| 事实 | 证据 | 对重放的影响 |
|---|---|---|
| bundle 内嵌特征为 **8 列 serving 契约**（wq_tp/tn/do/nh4_n/ph/water_temp + calendar 月正余弦），而 manifest 声明 frozen-78col v2.0 | `reuse_conditions.md` §3 | 重放特征必须按 `bundle.feature_columns`，**不得**按 manifest 78 列声明备料 |
| `selection_manifest.json` 每 run 存 `feature_sha256`（训练特征帧指纹） | runs/*/selection_manifest.json | 重放特征帧须与之对指纹，不一致即停止 |
| frozen_split（bloom/probability off0）为全局冻结拆分：train≤2021-12 / validation 2022-01..2023-12 / test≥2024-01；validation=31 行、test=40 行 | manifest.split.bounds + availability_matrix + split_of_month 实现 | 其校准池 = 训练段 OOF + **31 行 validation** 残差（声明 cal_n=212） |
| train_internal_time_block_cv_v1（density/biomass/chla/risk_level 及 T+30/60/90）的"test 段"是**训练期内部时间块的尾块**，不是全局 test：density/biomass/chla-90d test=2017-11..2020-11（≤2023-12 全在全局 train 期内），probability-90d test=2024-11..2026-03 | 42-run 实测 test_predictions.csv 月份分布 | 对这批 run，"留出段"= 内部尾块；重放校准段=其内部 validation 块。**口径以各 run run_config.protocol 为准，不得混用全局边界** |
| risk_level（序数）设计上无 conformal：bundle.intervals=None、cal_n=0、coverage=None | `width_degeneracy_report.md` §4.3 | 不在重校准范围（无数值残差可池化）；如需不确定性须另行设计（超出本规范） |
| 委托口径修正：任务书所称"校准段（validation 段，n≈117）"与实测不符——117 是回归任务**留出段**行数；validation 段行数以重建审计为准（frozen_split off0 = 31 行，availability_matrix 快照；cv 协议各 run 以 `collect_split('validation')` 审计行为准） | 本表 + §1.1 | 重放脚本必须打印 `source.last_collection_audit`，以实跑行数为准，不沿用任何书面 n |

---

## 2. 重放方案（批准后执行；本规范不执行）

### 2.1 范围

- 对象：34 个在役 artifact 中**有数值区间**的 29 个（bloom/probability/density/biomass/chla；
  5 个 risk_level 序数 artifact 排除）。
- 每个artifact 独立重放，禁止跨任务/跨时效合并残差池（这正是本轮审计发现的疑点，重放必须逐桶独立以检验它）。

### 2.2 步骤

**S1 重建任务监督帧（只读源数据）**
1. 按 `cli_real.py` train-all 的数据准备路径重建：`build_supervised_base(clean_tables_dir())`
   → `build_availability_matrix(base, labels)` → 取该 artifact 的 `(task_id, variant, month_offset, horizon_days)` 表
   → `StationMonthSource(table, feature_columns=bundle.feature_columns)`。
2. 指纹校验：重建后特征帧的 digest 与该 run `selection_manifest.json.feature_sha256` 比对；
   `data_version`/`data_sha256` 与 manifest 一致性比对。不一致→终止该 artifact 并记录，不得"带病重放"。

**S2 校准段逐行重放（两类残差分开留痕）**
1. **validation 段重放**：`frame = source.collect_split('validation')` →
   `X = bundle.preprocessor.transform(frame)` → `out = bundle.model.predict_frame(X)` →
   残差 = actual − point（binary/probability 取 `probability` 列；regression 取 `prediction` 列；
   ordinal 无此步）。逐行落盘：`(row_id, month, station_id, actual, point, residual)`。
2. **OOF 残差重算**：按 `training_real._fit_oof_residuals` 的等价流程（同 seed=20260907、
   同 expanding 折切分）重放训练段折外预测，得 OOF 逐行残差，同样落盘。
   （若实现成本过高，允许第一步先做 validation 段重放并如实标注池不完整，
   但 cal_n 对不上 212/225/234/261/16 的差额必须在报告中披露。）
3. 池化与分位：`pooled = concat(OOF, validation)` 中有限值部分 →
   `p05 = np.quantile(pooled, 0.05)`，`p95 = np.quantile(pooled, 0.95)`；
   `calibration_n_v2 = len(pooled)` 与旧 `calibration_n` 对照（应相等；不等即披露差异原因）。

**S3 产物写入（版本化，见 §4 红线 3）**
- 新文件：`runs/<run>/uncertainty_v2.json`（结构 = 旧 uncertainty.json + 
  `residual_p05_v2/residual_p95_v2/calibration_n_v2/pool_breakdown{oof_n,validation_n}/
  replay_sha256{model,feature_frame}/replayed_at/replay_cmd`）；
  逐行残差：`runs/<run>/calibration_residuals_v2.csv`。**不覆盖任何旧文件、不改 bundle。**

**S4 留出段只复核覆盖率（不动任何参数）**
- 用旧 `test_predictions.csv` 的逐行点预测 + 新分位重算
  `covered = (actual >= point + p05_v2) & (actual <= point + p95_v2)` → `empirical_coverage_v2`。
- 留出段预测值、模型、特征、选择结果**一律不改**；本步只做覆盖算术。

### 2.3 明确不做的事

- 不重训、不换特征、不调阈值/分位水平（0.05/0.95 固定）、不改 split、不删旧记录。
- risk_level 不做"硬造区间"。

---

## 3. 输入清单（实际盘点到的路径，执行时逐项核对存在性与 sha256）

| 类别 | 路径（相对 `01_我们的开发/`） | 说明 |
|---|---|---|
| 原始清洗表 | `data-cleaning/storage/final_cleaned/TAIHU_CLEAN_FINAL_V1_20260831/tables/model_dataset.parquet` | 监督底表源（`contracts_real.clean_tables_dir()`；可用 env `TAIHU_CLEAN_TABLES_DIR` 覆盖）；`manifest.data_sha256` 即此文件 sha256 |
| 同目录其余表 | 同上 `water_quality.parquet` / `labels.parquet` / `meteorology_hydrology.parquet` / `remote_sensing.parquet` / `static_features.parquet` | target_builder 标签与回填所需 |
| 已持久化中间层 | `backend/model_runtime_v0_3/supervised/features_base.parquet`（914×110，station_month 基表；train 779 / validation 79 / test 56——**基表粒度，非任务级帧**） | 仅供交叉核对，重放应走 S1 重建任务级帧 |
| 标签宽表 | `backend/model_runtime_v0_3/supervised/labels_wide.parquet`（593×9，label_chla_ug_l/label_bloom_clms 等） | 同上 |
| 遥感配对 | `backend/model_runtime_v0_3/pair_dataset/pairs.parquet`（208 行）+ `pairs_manifest.json`（pairs_sha256=7f2d85…） | chla/proxy 相关核对；本轮重放不直接消费 |
| 重建代码 | `backend/model_runtime_v0_3/code/modeling_real/{target_builder,data_real,contracts_real,training_real,cli_real}.py` | S1/S2 的实现参照；joblib 反序列化依赖 `code/` 在 `sys.path`（modeling_real 包） |
| 模型 | `backend/model_runtime_v0_3/models/*.joblib`（34 个；bundle 含 preprocessor/model/feature_columns/intervals） | 重放主体；加载前校验 manifest.sha256 |
| 运行记录 | `backend/model_runtime_v0_3/runs/<run>/{run_config,uncertainty,selection_manifest,evaluation_manifest,test_metrics_by_family}.json + test_predictions.csv` | 旧值来源与 S4 复核输入 |
| 运行环境 | `backend/.venv/Scripts/python.exe`（joblib 1.5.3 / numpy 2.5.1，已实证可加载 bundle） | 离线，不联网 |

---

## 4. 红线（执行与评审共同遵守）

1. **不在测试/留出段调参**：留出段只读、只算覆盖率；模型权重、特征集、family 选择、
   折切分、分位水平一律保持冻结。任何在留出段上"挑一个更好看的分位"的行为都是造假。
2. **细分桶最小样本量**：如做季节（月/季）或湖区（湖分区/站点类型）分桶重校准，
   每桶 `n ≥ 30` 方可出独立分位；不足 30 的桶只出全局分位并在报告披露桶 n。
   禁止对 n<30 的桶出"看起来准"的分位。
3. **版本化，不覆盖**：新记录写 `uncertainty_v2.json` / `calibration_residuals_v2.csv`；
   旧 `uncertainty.json`、`test_predictions.csv`、`models/*.joblib`、`gate_table.json` 一个字节都不改。
   v2 必须自带 `replay_cmd`、时间戳、模型与特征帧 sha256，保证可复现、可回滚（对照旧文件即可）。
4. **特征契约以 bundle 为准**：重放输入特征 = `bundle.feature_columns`（8 列）；
   manifest.feature_contract（78 列）在修正前不得作为备料依据（见 `reuse_conditions.md` §3）。
5. **协议口径不混用**：frozen_split 用全局边界，cv 协议用其内部时间块；逐 run 按
   `run_config.protocol` 分流，禁止把 2017-2020 的内部尾块当作全局 test 解读，反之亦然。
6. **代理标签口径不变**：重放标签必须与训练同源同版本（proxy 规则版本、data_version、
   data_sha256 三对齐）；任何标签重建变更都使重放无效。
7. **数字诚实**：重放后若覆盖率更差、宽度更宽，必须原样报告；重校准的目的是校准，
   不是让门禁表变绿。

---

## 5. 验收标准（重校准完成后的交付与判据）

**交付 A：留出段覆盖率报告**（逐 artifact 一行）
- 列：artifact_id / 协议 / 留出段 n / cov_before（旧 uncertainty.json）/ cov_after（v2 复核值）/
  Δcov / 是否达验收线（≥0.88=0.90−0.02）/ 备注。
- 判据：29 个可校准 artifact 中，**calibration_n_v2 与旧 cal_n 一致**（池重建成功的形式判据）；
  cov_after 达线情况逐行如实列出。不达线者进入下一轮（改校准策略而非改留出段）。
- 4 个 degenerate（T1/T6 bloom·probability T+30/60 cv，旧宽=0、cal_n=16、test_n=5）必须
  在 v2 中变为非零宽度，或给出"池子本身过小（n=16）无法支撑独立分位"的明确结论与处理建议。

**交付 B：宽度增量对比表**（逐 artifact 一行）
- 列：artifact_id / width_before（旧 p95−p05，注明量纲）/ p05_v2 / p95_v2 / width_after /
  Δwidth / Δwidth% / 同组四时效宽度是否仍逐位相同（检验"共享池"疑点是否消除）。
- 判据：重校准后，同 (task,variant,protocol,offset) 组内 T+1/3/7/15 的宽度**不再逐位相同**
  （若仍相同，必须给出解释性证据而非沉默）；量纲与方向（p05<p95≤/≥0）逐行可解释。

**共同形式要求**：A/B 两表由脚本生成（含运行命令与 UTC 时间戳），随附
`uncertainty_v2.json` / `calibration_residuals_v2.csv` 的抽样核验说明；评审按 §4 红线逐条过一遍。

---

## 6. 与本轮三份审计报告的衔接

- `artifact_run_map.md`：34 artifact ↔ 42 run 映射与 sha256 对照 —— 重放对象清单的直接来源；
  8 个 UNMAPPED run 不在本规范范围内（无模型文件，属候选 run）。
- `reuse_conditions.md`：97.5% 族复用前提（bundle 特征契约、frozen 边界、代理标签）——
  §2/§4 多条红线由此而来。
- `width_degeneracy_report.md`：42 run 体检（4 degenerate / 20 含无区分度标记 / 19 含欠覆盖标记 /
  9 无区间）—— 重放要回答的核心问题清单："逐时效独立校准后，这些异常还剩几个？"
