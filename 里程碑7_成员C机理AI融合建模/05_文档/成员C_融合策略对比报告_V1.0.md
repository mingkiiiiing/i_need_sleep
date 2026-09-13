# 成员C 机理-AI 融合策略对比报告 V1.0

> 本报告按《成员C_融合策略对比报告模板 V0.1》章节骨架填写，数据与结论全部来自仓库内可审计产物（路径见第十一节证据链）。报告口径遵循 2026-09-12 已生效的指标口径冻结条款 F1~F6（`backend/model_runtime_v0_3/evaluation/experiments_r1/口径冻结提案_20260912.md`）。

## 1. 报告目的

对比单一机理模型、单一 AI 模型与机理-AI 融合模型在太湖蓝藻水华预测任务中的表现，说明各方案的输入、输出、优缺点、适用条件与测试集结果；并按"融合相对最强单一数据驱动模型提升不低于 10%"的门禁规则给出如实判定。

比较基线不是简单均值模型，而是每个"任务 × 时效"下 Random Forest 与 XGBoost 中更强的一方（validation 选族，冻结规则 F3）。

## 2. 当前报告状态

| 项目 | 内容 |
| --- | --- |
| 报告版本 | V1.0（2026-09-13，首版正式填写，替代模板 V0.1 的全部"待填写"） |
| 负责人 | 成员C |
| 数据版本 | `TAIHU_CLEAN_FINAL_V1_20260831/model_dataset.parquet`（V0.3 真实监督表） |
| 代码版本 | `backend/model_runtime_v0_3`（2026-09-12 T3b 三项 bug 修复后：机理设计矩阵收缩、序数评估直通、chla 单位统一） |
| 评估协议 | frozen_split（train≤2021 / val 2022-2023 / test≥2024）与补训协议 `train_internal_time_block_cv_v1`（训练期内 60/20/20 时间分块），seed=20260907 |
| 结果状态 | 重训面板为 `retrain_draft`（修复口径，2026-09-12）；现网冻结 `gate_table.json`（2026-09-11）维持 FAIL。draft 待主控确认后全量重跑转正 |

**诚实边界（先读）**：

1. 本报告全部重训行是 draft 证据，不是冻结门禁结论；`gate_table.json` / `manifest.json` 未改动。
2. T3 标签为分位秩代理；T5/T6 标签以 `chla_station_proxy_v1` 代理为主（单位修复后锚点恢复真实量纲，代理性质不变）。
3. 1/3/7/15 天短时效映射同一 month_offset=0 监督表，按 F4.4 计为**一行独立实验**，不是四份独立证据。
4. T6-probability 与 T1-bloom 为同帧跨任务复制（同标签、同 seed、同切分），按一行独立实验计。
5. 本报告不构成"真实太湖精度"证明。

## 3. 对比方案

### 3.1 方案一：单一机理模型

| 项目 | 内容 |
| --- | --- |
| 名称 | 机理因子模型（mechanism 族） |
| 输入 | 真实水温（ERA5 湖表温度网格 + 野外实测覆盖，气温回退）、短波辐射、总磷、总氮，及机理设计矩阵 17 列（6 个 mech_* 因子 + 水质/气象/水电站原始列 + 月历正余弦 + log1p chla） |
| 输出 | 各任务目标（回归 / 概率 / 序数等级） |
| 机理结构 | 温度限制 `fT = clip((T−10)/(28−10), 0, 1)`（T≤4 或 ≥38 置 0）；光照限制 `fL = clip(I/18, 0, 1)`；Monod 磷限制 `TP/(TP+0.02)`；Monod 氮限制 `TN/(TN+0.6)`；Liebig 最小律营养限制 `fN = min(fP, fN)`；净比增长率 `r = 0.9·fT·fL·fNut − 0.16`（d⁻¹，非拟合、无泄漏，由真实观测确定性重算） |
| 学习器 | HistGradientBoosting（max_iter=150, lr=0.05, max_leaf_nodes=8, min_samples_leaf=5）在机理设计矩阵上训练；有效行 <10 时常数回退（回退态会在评估中带 `mechanism_degenerate` 标记） |
| 优点 | 结构可解释、因子可直接分解归因、外推有物理约束托底；设计矩阵构造无未来信息 |
| 缺点 | 常数（0.9/0.16/半饱和 0.02/0.6）未经同化校准；机理三因子（温度/光照/营养盐）站点集合不相交时 net_growth 恒 0 插补（L-data-03）；对复杂非线性交互表达有限 |
| 当前用途 | 机理基线 + 融合消融臂（F3.4） |
| 实现位置 | `modeling_real/target_builder.py:_mechanism_columns`、`training_real.py:_fit_mechanism` |

原型对照：里程碑7 的 `blue_algae_m7/mechanism.py` 另有一版 Logistic+Monod 加权风险指数（温度高斯核 opt=28℃/width=12℃，Monod 半饱和 P=0.05/N=0.50，风遮蔽 1/(1+w/2)，权重 0.30/0.22/0.16/0.17/0.15），作为答辩讲机理的可解释原型，未进入 V0.3 训练候选。

### 3.2 方案二：AI 模型一（Random Forest）

| 项目 | 内容 |
| --- | --- |
| 名称 | random_forest 族 |
| 输入 | 标准特征表全部模型特征（水质/气象/水动力/遥感/滞后滚动/月历） |
| 输出 | 目标预测值或风险概率；序数任务经等级编码训练 |
| 超参 | n_estimators=200, min_samples_leaf=2, class_weight="balanced_subsample" |
| 优点 | 稳健、适合小样本表格数据、可输出特征重要性、对量纲不敏感 |
| 缺点 | 外推能力有限、物理约束弱、月度样本下易向均值收缩 |
| 当前用途 | 单一 AI 基线之一（门禁主基线候选） |

### 3.3 方案三：AI 模型二（XGBoost）

| 项目 | 内容 |
| --- | --- |
| 名称 | xgboost 族 |
| 输入 | 同上标准特征表 |
| 输出 | 同上 |
| 超参 | n_estimators=200, max_depth=4, lr=0.05, tree_method="hist" |
| 优点 | 能表达复杂非线性与特征交互、正则化控过拟合 |
| 缺点 | 小样本下需调参、对标签噪声敏感 |
| 当前用途 | 单一 AI 基线之一（门禁主基线候选） |

### 3.4 方案四：级联特征融合（mechanism_feature）

| 项目 | 内容 |
| --- | --- |
| 名称 | Mechanism Cascade Fusion（机理特征级联） |
| 输入 | 原始特征 + 机理点值列 `mechanism_prediction`（序数任务按等级序号保序编码，保证拟合/推理同口径） |
| 输出 | 融合预测（AI 头输出） |
| 思路 | 机理输出作为 AI 的额外输入特征，AI 自行学习如何使用机理信息 |
| 学习器 | 二段 Random Forest |
| 优点 | 结构简单、便于解释（机理分数作为特征贡献可查）、实现代价低 |
| 缺点 | 机理信息若与原始特征冗余（合成数据已证实此现象），级联不产生增量；树模型可忽略该特征 |
| 当前用途 | 融合候选一；T5-chla 冻结协议现网当选族（旧口径） |
| 实现位置 | `training_real.py:MechanismFeatureCandidateReal / _fit_fusion("mechanism_feature")` |

### 3.5 方案五：残差融合（residual）

| 项目 | 内容 |
| --- | --- |
| 名称 | Residual Fusion（残差校正） |
| 输入 | 机理预测、增广特征表、真值（训练期） |
| 输出 | 机理预测 + AI 残差修正，截断回 [0,1]（概率）或 ≥0（回归） |
| 思路 | `residual = actual − mechanism_prediction`，AI 学习机理模型的系统误差；binary/probability 任务的二段改用回归器拟合连续残差（2026-09-12 修复 A：此前 classifier 拟合连续残差必然抛错，该融合族在 binary 任务从未成功过） |
| 学习器 | 二段 Random Forest（残差回归） |
| 优点 | 直接体现"AI 补偿机理不足"的叙事；机理强则残差小、融合退化为机理，结构上有保底 |
| 缺点 | 需要足够真实标签，否则残差学习不稳定；序数任务无数值残差，不注册（该族在 risk_level 上 NOT_APPLICABLE） |
| 当前用途 | 融合候选二；T3-density 冻结协议现网当选族（旧口径，T3b 已证为常数回退噪声，待重跑改判） |
| 实现位置 | `training_real.py:ResidualCandidateReal / _fit_fusion("residual")` |

### 3.6 方案六：约束加权融合（constrained_blend）

| 项目 | 内容 |
| --- | --- |
| 名称 | Constrained Weighted Blend（验证段选权约束混合） |
| 输入 | 机理预测、AI（XGBoost）预测、validation 段真值 |
| 输出 | `blend = w × mechanism + (1−w) × AI`，物理边界裁剪（概率 [0,1]、回归 ≥0；序数任务在两支路标签间按 w≥0.5 择一） |
| 思路 | 权重 w 只在 validation 段网格 {0, 0.25, 0.5, 0.75, 1.0} 上按 MSE（序数按分类错误率）选择，不接触测试集；等效于"数据驱动的机理/AI 仲裁器" |
| 优点 | 权重选择可审计并随行落盘；w 的档位本身即"该任务该时效信机理还是信 AI"的可解释信号；物理裁剪保证输出不越界 |
| 缺点 | 网格过粗、单标量权重无法表达样本级切换；validation 单类/全阴时选权依据薄弱（F3.5 `weak_selection_basis`） |
| 当前用途 | 融合候选三；T4-biomass 冻结协议现网当选族（旧口径） |
| 实现位置 | `training_real.py:ConstrainedBlendCandidateReal / _fit_fusion("constrained_blend")` |

另有一版 Stacking 原型（以机理/XGB/RF 预测为输入在校准段训元模型，V0.2 `modeling_v1` 内），仅作开发验证，不进正式冻结候选，本文不纳入对比。

### 3.7 对照基线族（不参与 10% 判定，必须同表披露，F3.3）

| 族 | 定义 | 作用 |
| --- | --- | --- |
| simple_baseline | 训练段均值/众数常数 | 检验全体模型是否跑赢"什么都不学" |
| climatology_global | 目标月份 → 训练期 actual 均值/众数查表（mo≥1 任务传入历史标签序列，无前视） | 检验是否跑赢季节循环 |
| persistence | 当月实测即预测（仅 month_offset≥1 且 chla/bloom 家族注册） | 检验中长期预测是否跑赢惰性延续 |

### 3.8 三种融合方案定性对比总表

| 维度 | 级联特征融合 | 残差融合 | 约束加权融合 |
| --- | --- | --- | --- |
| 融合位置 | 特征层（输入端） | 目标层（输出端，学误差） | 决策层（输出端，选权重） |
| 机理角色 | 供 AI 参考的信息源 | 一阶主预测 | 与 AI 平权的候选支路 |
| 数据需求 | 中（多一列特征） | 高（残差需要足够真值） | 低（只需 validation 段选权） |
| 可解释性 | 机理分数特征贡献 | 机理 + 残差修正量分解 | 单一权重 w，最直白 |
| 主要失败模式 | 机理信息与特征冗余时无增量 | 标签噪声/代理标签下残差不稳 | validation 失真时选错权重档 |
| 序数任务支持 | 支持（等级序号编码） | 不支持（无数值残差） | 支持（标签择一） |

## 4. 数据与切分

| 项目 | 内容 |
| --- | --- |
| 数据文件 | `TAIHU_CLEAN_FINAL_V1_20260831/model_dataset.parquet`（站点-月监督表，chla 单位已统一 μg/L） |
| 空间范围 | 太湖站位（含野外航次站），月粒度 |
| 目标变量 | T1 水华发生（binary，阈值 20 μg/L）/ T3 蓝藻密度（回归，分位秩代理）/ T4 生物量（回归，mae）/ T5 叶绿素 a（回归，代理标签为主）/ T6 概率（brier）/ T6 风险等级（ordinal，5 类） |
| 切分方式 | frozen_split：train≤2021 / validation 2022-2023 / test≥2024；标签全在训练期的任务以补训协议 `train_internal_time_block_cv_v1`（训练期内 60/20/20 月份时序块，无前视）为权威窗口（F4.3） |
| seed | 20260907（全部行同 seed，跨 run 禁止相减） |

各面板样本量（修复口径重训）：

| 面板 | train / val / test | test 窗口 | 备注 |
| --- | --- | --- | --- |
| T1-bloom / T6-probability（mo=0，冻结段） | 586 / 31 / 40 | 2024-09..2026-08 | 阳性 2/40；validation 全阴性（L-data-06） |
| T3-density（mo=0，时间分块） | 342 / 117 / 117 | 2017-11..2020-11 | 标签为分位秩代理 |
| T4-biomass（mo=0，时间分块） | 342 / 117 / 117 | 2017-11..2020-11 | 重尾分布 |
| T5-chla（mo=0，时间分块） | 360 / 126 / 132 | 训练期内留出块 | 代理标签（锚点 6.124 μg/L） |
| T5-chla h90（mo=3，时间分块） | — / — / 117 | 2017-08..2020-08 | climatology_history 已注入 |
| T6-risk_level（mo=0，时间分块） | — / — / 132 | 训练期内留出块 | 5 类标签（修复后 severe 类出现） |

## 5. 指标对比

主指标按 F1 冻结：T1/T6-probability = brier_score（min）；T3 = log1p_mae（min）；T4/T5 = mae（min）；T6-risk_level = macro_f1（max）。R² 只作拟合诊断不进判定。每表 uplift 均相对"validation 选出的最优单一 AI 族"（F3.1），对照基线同表披露（F3.3）。全部数字来自 T3b 修复口径重训 draft（同切分同 seed）。

### 5.1 T3-density（log1p_mae，min；基线 = RF 0.15422）

| 模型 | test log1p_mae | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 0.18186 | −17.93% | FAIL_worse_than_baseline |
| Random Forest（基线） | 0.15422 | — | BASELINE_row |
| XGBoost | 0.16077 | −4.25% | FAIL_worse_than_baseline |
| 级联特征融合 | 0.19912 | −29.12% | FAIL_worse_than_baseline |
| 残差融合 | 0.18368 | −19.11% | FAIL_worse_than_baseline |
| 约束加权融合 | 0.16077 | −4.25% | FAIL_worse_than_baseline |
| simple_baseline（对照） | 0.14950 | +3.06% | FAIL_below_10pct |
| climatology_global（对照） | 0.16393 | −6.29% | FAIL_worse_than_baseline |

注：机理族已不退化（预测唯一值 115/117），但机理-only 劣于 RF；**该面板所有 AI 族（含融合）均未跑赢训练均值常数**——分位秩代理目标 + 2005-2020 训练期分布漂移所致。

### 5.2 T4-biomass（mae，min；基线 = XGB 5.52161）

| 模型 | test mae (mg/L) | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 5.46975 | +0.94% | FAIL_below_10pct |
| Random Forest | 6.24147 | −13.04% | FAIL_worse_than_baseline |
| XGBoost（基线） | 5.52161 | — | BASELINE_row |
| 级联特征融合 | 5.60539 | −1.52% | FAIL_worse_than_baseline |
| 残差融合 | 5.64607 | −2.25% | FAIL_worse_than_baseline |
| 约束加权融合 | 5.46299 | **+1.06%（最优融合）** | FAIL_below_10pct |
| simple_baseline（对照） | 4.36091 | +21.02% | 对照行，不参与判定 |
| climatology_global（对照） | 4.37974 | +20.68% | 对照行，不参与判定 |

注：重尾分布下全体 AI 族不敌均值/季节基线；按 F3.3，融合增益不得对外表述为机理融合增益。

### 5.3 T1-bloom / T6-probability（brier_score，min；冻结测试段 40 行，阳性 2/40；基线 = XGB 0.04945）

| 模型 | test brier | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 0.04755 | +3.83% | FAIL_below_10pct |
| Random Forest | 0.04850 | +1.91% | FAIL_below_10pct |
| XGBoost（基线） | 0.04945 | — | BASELINE_row |
| 级联特征融合 | 0.04936 | +0.18% | FAIL_below_10pct |
| 残差融合 | 0.04755 | **+3.83%（最优融合）** | FAIL_below_10pct |
| 约束加权融合 | 0.04945 | 0.00% | FAIL_below_10pct |
| simple_baseline（对照） | 0.07882 | −59.39% | FAIL_worse_than_baseline |
| climatology_global（对照） | 0.08282 | −67.49% | FAIL_worse_than_baseline |

注：唯一使用 2024+ 冻结测试段的短时效面板。机理-only 与残差融合同值（残差二阶段学到的修正近零），二者优于 XGB 但 +3.83% < 10%。整面板附 `weak_selection_basis`（validation 31 行全阴性）与 `weak_event_support`（阳性 2 < 5）双弱标记。T6-probability 与本表同帧逐位同值，按一行独立实验计。

### 5.4 T5-chla（mae，min；基线 = RF 5.49109）

| 模型 | test mae (μg/L) | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 6.28271 | −14.42% | FAIL_worse_than_baseline |
| Random Forest（基线） | 5.49109 | — | BASELINE_row |
| XGBoost | 5.24623 | +4.46% | FAIL_below_10pct |
| 级联特征融合 | 6.97383 | −27.00% | FAIL_worse_than_baseline |
| 残差融合 | 6.56727 | −19.60% | FAIL_worse_than_baseline |
| 约束加权融合 | 5.44469 | **+0.84%（最优融合）** | FAIL_below_10pct |
| simple_baseline（对照） | 8.00965 | −45.87% | FAIL_worse_than_baseline |
| climatology_global（对照） | 7.36696 | −34.16% | FAIL_worse_than_baseline |

注：单位修复后标签均值 14.45 μg/L（真实量纲），代理性质不变。机理族劣势与 L-data-03（机理三因子站点不相交、net_growth 恒 0 插补）直接相关。

### 5.5 T5-chla h90 / mo=3（mae，min；基线 = XGB 6.09553）

| 模型 | test mae (μg/L) | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 6.25697 | −2.65% | FAIL_worse_than_baseline |
| Random Forest | 5.97509 | +1.98% | FAIL_below_10pct |
| XGBoost（基线） | 6.09553 | — | BASELINE_row |
| 级联特征融合 | 6.17984 | −1.38% | FAIL_worse_than_baseline |
| 残差融合 | 6.24131 | −2.39% | FAIL_worse_than_baseline |
| 约束加权融合 | 6.00711 | **+1.45%（最优融合）** | FAIL_below_10pct |
| simple_baseline（对照） | 7.66250 | −25.71% | FAIL_worse_than_baseline |
| climatology_global（对照） | 6.71615 | −10.18% | FAIL_worse_than_baseline |

注：climatology_history 注入后气候态是真实季节查表（唯一值数 4），不再是退化基线；此面板全体 AI 族跑赢了季节基线，但融合增益仍不足 10%。

### 5.6 T6-risk_level（macro_f1，max；基线 = RF 0.29569；test 132 行、5 类）

| 模型 | test macro_f1 | 相对基线 uplift | F5 状态 |
| --- | ---: | ---: | --- |
| 单一机理模型 | 0.19882 | −32.76% | FAIL_worse_than_baseline |
| Random Forest（基线） | 0.29569 | — | BASELINE_row |
| XGBoost | 0.26538 | −10.25% | FAIL_worse_than_baseline |
| 级联特征融合 | 0.26221 | −11.32% | FAIL_worse_than_baseline |
| 约束加权融合 | 0.26538 | −10.25%（最优融合） | FAIL_worse_than_baseline |
| simple_baseline（对照） | 0.12211 | −58.70% | FAIL_worse_than_baseline |
| climatology_global（对照） | 0.19420 | −34.32% | FAIL_worse_than_baseline |

注：序数评估修复后 macro_f1 从幻影 0.0 恢复为真实区分力（RF 0.296 vs 常数 0.122、气候态 0.194）。残差融合在此任务不适用（无数值残差）。融合族均未超过 RF。

### 5.7 V0.2 合成路线对照（历史，2026-09-10 冻结）

V0.2 算法交付包在合成数据上以同三门禁规则全量对比 189 行：**0 PASS / 175 FAIL / 14 NA**。结构性结论：T7 空间任务上机理单体被选中、面积加权 IoU 高于纯 AI（机理结构价值最明显的任务族）；其余任务融合最优值与纯 AI 接近但不形成 10% 提升，根因是合成生成器含随机门控与机理信息冗余。据此另做的"机理主导合成环境"验证（11 号文档）中门禁真实判出 **33/35 PASS（94.3%）**——证明融合架构与门禁机制在"环境存在只有机理能递推的信息"时能产生并如实判定 ≥10% 增益；该结论仅限合成环境，不得表述为真实太湖达标。

## 6. 融合提升计算与门禁结论

### 6.1 冻结公式（F2）

```text
min 方向指标（brier / mae / log1p_mae）：uplift = (baseline − model) / baseline   # 下降为正
max 方向指标（macro_f1）：            uplift = (model − baseline) / baseline     # 上升为正
PASS 判定：uplift ≥ 0.10 且 n_test ≥ 15 且测试段类别支持满足 F4
```

基线 = 同 run、同切分、同 seed、同一冻结评估帧上 validation 主指标最优的单一数据驱动族（RF/XGB 较优者，平 tie 取注册序首）。

### 6.2 现网冻结门禁（gate_table.json，2026-09-11）

| 项 | 数值 |
| --- | --- |
| 比较行 | 42（任务 × 时效 × 融合族） |
| 可评估 | 30 |
| PASS / FAIL / NA | 6 / 24 / 12 |
| 总体状态 | **FAIL**（PASS 比例 20% < 90% 门槛） |

### 6.3 修复口径重验（T3b draft，2026-09-12）

**修复后没有任何（任务 × 变体）的融合族达到 uplift ≥ 10%。** 融合相对最优单一 AI 的增益区间为 **−29.12% ~ +3.83%**：

| 面板 | 最优融合 | uplift | gap（距 10%） |
| --- | --- | ---: | ---: |
| T3-density mo0 | —（全部为负） | −4.25%（CB） | — |
| T4-biomass mo0 | constrained_blend | +1.06% | 8.94 pp |
| T1-bloom mo0（冻结段） | residual | +3.83% | 6.17 pp |
| T6-probability mo0（冻结段） | residual（与 T1 同帧） | +3.83% | 6.17 pp |
| T5-chla mo0 | constrained_blend | +0.84% | 9.16 pp |
| T5-chla h90 | constrained_blend | +1.45% | 8.55 pp |
| T6-risk_level mo0 | constrained_blend | −10.25% | — |

注（T3-density mo0 行）：该面板 CB 最优权重 w=0，退化为纯 AI 支路（与 XGB 逐位同值 0.16077），严格而言此面板无融合增益。

旧 gate_table 的 6 条 PASS（T3 residual h1/3/7/15 四条 + T3/T4 h90 两条）在修复口径重验下**全部不复现**：mo0 四条系机理常数回退下的向均值收缩噪声；T3/T4 h90 已补跑反证（融合族 −19.4% / +3.34%）。即修复后真实口径为 **0 达标**，与 serving 公示的"0/8 可评估 PASS、门禁 FAIL"一致。

按模板第 6 节注意事项自查：本报告全部提升基于真实（含代理标签）测试段计算，无训练集数字、无样例数据；对照组指标过低（T4 全体 AI 不敌常数）与样本过少（T1 阳性 2）处均已声明结果不稳定。

## 7. 可解释性对比

| 模型 | 是否可解释 | 解释方法 | 主要驱动因子 | 说明 |
| --- | --- | --- | --- | --- |
| 机理模型 | 是 | 机理分量分解（fT/fL/fP/fN/min 营养/net_growth） | 温度、光照、磷、氮 | 直接来自模型结构，可逐站逐月分解 |
| Random Forest | 是 | 特征重要性（impurity） | 待逐任务落盘 | 树模型内置 |
| XGBoost | 是 | gain 特征重要性 | 待逐任务落盘 | 树模型内置 |
| 级联特征融合 | 是 | 机理分数特征贡献 + AI 特征重要性 | 机理列与原始特征并列 | 机理分数贡献可直接从重要性表读出 |
| 残差融合 | 部分 | 机理分量 + 残差修正量分解 | 机理项为主，残差项为补偿 | 解释"AI 修正了机理多少" |
| 约束加权融合 | 是 | 单一权重 w + 两侧分量 | w 档位即机理/AI 信任度 | 最直白；w 随行落盘可审计 |

边界披露：SHAP 未产出（`is_shap=False` 硬编码）；运行时解释接口当前返回规则贡献演示（`demo_rule_contribution`），不是 SHAP 值。对外表述一律用"特征重要性/机理分量"，不得写 SHAP。

## 8. 不确定性对比

| 模型 | 不确定性方法 | 输出 | 说明 |
| --- | --- | --- | --- |
| 全族共用（serving 契约） | split-conformal 残差分位数（P05/P95，目标覆盖 90%） | 预测区间 | 校准源 = train 折外 OOF（时间递增 2 折）+ validation 残差池化；冻结测试集只报告经验覆盖率，不参与拟合 |
| 机理模型 | 同上（按当选族落盘） | 区间 | 机理为序数任务时无数值残差，不适用 |
| RF / XGB | 同上 | 区间 | 树分布近似未启用，统一走 conformal |
| 各融合族 | 同上 | 区间 | 区间挂在"validation 当选族"上随 bundle 落盘（`uncertainty.json`：method / calibration_n / empirical_coverage_test） |

边界披露：序数任务（风险等级）无 conformal 区间；输入扰动情景分布（V0.2 情景推演页）不是经真实残差校准的置信区间，两者不得混称。

## 9. 结论

按模板 9.2 节口径如实声明：**当前测试条件下，融合模型未稳定优于单一模型。**

1. **机理支路退化已修复，但"机理信息恢复"≠"10% 提升达成"。** 修复后（设计矩阵有效行 0/576→576/576、chla 单位统一、序数评估直通）全部重训面板显示：融合相对最优单一 AI 的增益在 −29.12% ~ +3.83% 区间，无一达到 10% 门禁；最优融合族也只是在 T1/T6p 上与机理-only 打平（残差修正近零）。
2. **归因（按消融证据，非推测）**：(a) 样本饥饿——月粒度监督表数百行，测试段阳性仅 2（T1）；(b) 标签代理——T3 分位秩、T5/T6 代理标签占主导，融合学到的"机理误差"以代理误差为主；(c) 机理因子数据缺口——温度/光照/营养盐三因子站点集合不相交，net_growth 恒 0 插补（L-data-03）；(d) validation 全阴性（L-data-06）导致选族与选权依据薄弱；(e) 短时效四档映射同一月度实验（L-data-01），有效证据密度低于表面行数。
3. **机理的结构价值在两处有实证**：V0.2 空间任务（T7）机理单体测试面积加权 IoU 高于纯 AI；机理主导合成环境门禁 33/35 PASS。即融合架构本身有效，当前瓶颈是真实标签与机理驱动数据，不是融合设计。
4. **方案横向结论**：小样本+代理标签下，约束加权融合最稳（三面板最优融合、权重可审计、退化优雅）；残差融合在 binary/probability 修复后可用且在冻结段与机理-only 并列最优，但其价值依赖真值密度；级联特征融合在机理信息与原始特征冗余时最易无增益（T3/T5 上最差）。
5. 下一步应优先补充数据与校准机理参数（真实日尺度配对标签、机理三因子补数、机理常数同化校准），而不是直接扩大模型复杂度。

## 10. 下一步

1. 主控确认 T3b draft 后，以修复后代码全量重跑 42 runs，`gate.py` 重新生成 gate_table（夜间批量，2~4 小时），本报告第 5/6 节同步转正。
2. 落实 T1 审计切分（事件级 row_id 归并），全部 retrain 加 `--split-source`，消除同源多行与事件泄漏双风险。
3. 数据缺口清单跟踪（保持阻断，如实列缺）：L-data-01 日尺度真实目标缺失；L-data-03 机理三因子站点不相交；L-data-04 CLMS 三列同值；L-data-06 validation 全阴性；L-data-08 日尺度真实配对（MEE 实时仅 8 天）。
4. 机理常数（μ_max=0.9、损失 0.16、半饱和 0.02/0.6）用真实标签做同化校准后重跑消融，检验 F3.4 消融臂。
5. 江苏入湖河流 7 断面 × 56 月特征已接入数据资产层，挂接 model_dataset 后重训（本轮未参与）。
6. 可解释性：逐任务落盘特征重要性表；SHAP 是否启用单列决策，未启用前统一口径为特征重要性。

## 11. 证据链（可审计路径）

| 内容 | 路径 |
| --- | --- |
| V0.3 融合实现（三族 + 机理 + AI + 基线） | `backend/model_runtime_v0_3/code/modeling_real/training_real.py` |
| 机理因子构造（公式） | `backend/model_runtime_v0_3/code/modeling_real/target_builder.py:_mechanism_columns` |
| 现网冻结门禁表 | `backend/model_runtime_v0_3/evaluation/gate_table.json`（2026-09-11） |
| 修复与重训报告（本报告数字主源） | `backend/model_runtime_v0_3/evaluation/experiments_r1/T3b_修复与重训报告_20260912.md` |
| 口径冻结条款 F1~F6 | `backend/model_runtime_v0_3/evaluation/experiments_r1/口径冻结提案_20260912.md` |
| 重训 draft 面板 JSON | `backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_*_20260912.json` |
| V0.2 合成路线对比（历史） | `企业提交材料/算法组提交材料_V0.1/06_融合策略对比分析_V0.1.md` |
| 合成环境门禁 PASS 边界 | `企业提交材料/算法组提交材料_V0.1/11_合成环境机理融合增益验证_V0.1.md` |
| serving 门禁公示 | `GET /api/v1/model/acceptance`（V0.2，0/189）、`GET /api/v1/model/v3/acceptance`（V0.3 真实口径，0/8 可评估） |
| 机理原型（Logistic+Monod） | `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/mechanism.py` |

注：`chla_proxy_params.json` 内 anchor.chla_mean_ug_l=3.0651 为 2026-09-11 单位修复前落盘值；本报告锚点 6.124 为修复后口径，演变记录见 T3b 报告 §4。
