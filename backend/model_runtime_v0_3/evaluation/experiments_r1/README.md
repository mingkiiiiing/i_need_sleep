# experiments_r1 —— T3a 消融脚手架与口径冻结（实验子目录）

T3a 阶段产物（2026-09-12）。全部内容为**实验草案（draft）**：只读既有产物与运行时包，不改 `gate_table.json`、`manifest.json`、serving 契约、前端；最终门禁状态以 T3b 冻结评估后 `gate.py` 重新生成的 gate_table 为准。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `口径冻结提案_20260912.md` | 主指标/提升公式/比较基线/测试窗口的冻结提案（F1~F6），含现行 uplift 定义调研、24 条 FAIL 比较对象逐条梳理、结构性诊断（机理支路退化、T6 序数评估 bug、同源复用、双窗口并存）。**待主控确认入台账后生效。** |
| `ablation_runner.py` | 同切分消融 runner：offline / selftest / retrain 三模式，行结构对齐 gate_table 字段，输出统一 JSON |
| `dryrun/ablation_offline_20260912.json` | offline dry-run：42 个 run 全量离线复算（320 行），gate 交叉核对 84/84 复现，机理退化甄别 42/42，同源复用甄别 8 组 |
| `dryrun/ablation_selftest_20260912.json` | selftest dry-run：合成小样例（12 站×48 月，明确标注 synthetic）走 retrain 同一代码路径，回归+序数两面板，验证链路与序数标签修复 |
| `dryrun/ablation_retrain_smoke_T3.json` | retrain 冒烟：T3-density h1 真实监督表 + 内部时间分块（60/20/20），8 族同切分同 seed 复算 |

## 用法（工程根目录执行）

```bash
# 1) 离线复算既有产物（不重训练；--only 可只扫子集，如 --only T3-density）
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py offline

# 2) 合成样例自检（链路验证，非证据）
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py selftest

# 3) 重训练消融（T3b 用；split-source 为 T1 审计切分 JSON，见下）
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T3 --variant density --horizons 1,3,7,15 \
    [--split-source backend/evaluation/audits/split_map_T3.json] [--seed 20260907] \
    [--families mechanism,random_forest,xgboost,mechanism_feature,residual] \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T3_draft.json
```

### 输出行结构（对齐 gate_table 字段 + 消融扩展）

每行 = 一个 (run × 消融族) 的同帧评估：`task_id / variant / horizon_days / month_offset / target / primary_metric / metric_direction / n_test / run_id / data_version / training_protocol`（gate 原字段）+ `ablation_family / family_role / test_value / baseline_family / baseline_value / uplift_vs_best_single / status_vs_threshold / test_window / test_positives / mechanism_degenerate_run`。

`uplift_vs_best_single` 严格按冻结公式：min 指标 `(baseline−model)/baseline`，max 指标 `(model−baseline)/baseline`；基线为 0 → None（不机械算百分比）。基线 = validation 选出的最优单一 AI 族（与 gate.py 同规则，平 tie 取注册序首）。

`status_vs_threshold` 是**消融行候选状态**（`PASS_candidate / FAIL_below_10pct / FAIL_worse_than_baseline / INDETERMINATE_baseline_zero_or_not_computable / NA_test_n_below_15 / BASELINE_row / ERROR_family_failed`），不是最终门禁状态。

## 关键 dry-run 结论（详见口径冻结提案第二、三节）

1. **gate_table 可完全复算**：42 run × 融合/单一两行 = 84 行交叉核对全部复现（rel_tol=1e-12），门禁数字无硬编码、可审计。
2. **机理支路全线退化**：42/42 run 中 mechanism 族与 simple_baseline（训练均值常数）同帧指标精确同值——三类融合族融合的是常数，现网全部融合 uplift 属噪声级；且 retrain 冒烟证明当前代码+数据下 T3 机理支路仍退化（`wq_phyto_biomass` 剔除列致设计矩阵行有效性全灭 + 面板机理列全 0/全 NaN）。
3. **T6 序数全零是评估 bug**：序数字符串标签被 `pd.to_numeric` 强转成 NaN → 幻影类 'nan' → 全族 macro_f1=0 → simple_baseline 平 tie 当选。runner 的 retrain 路径已按修复口径实现，selftest 中同路径 RF macro_f1=0.919。
4. **同源复用**：8 个 (task, variant, month_offset=0, protocol) 组的 h1/3/7/15 全部是同一实验多行引用（T3/T4/T5-cv 组仅差 1e-17 级浮点抖动，已按 12 位有效数字归一判定）；T6-probability 与 T1-bloom 为同实验跨任务复制。

## 与 T1 的衔接点（数据就绪后接哪里）

1. **切分覆盖**：T1 交付"样本ID—切分归属"清单后，转成 `{"row_id_to_split": {"<row_id>": "train|validation|test"}}` JSON，经 `--split-source` 注入 retrain 模式（未覆盖行会被剔除并显式告警，不会静默混入）。未提供 split-source 且冻结表 validation 不足时，runner 回退到与 `cli_real_cv` 同口径的内部时间分块（60/20/20，块界随行落盘）。
2. **事件级切分**：T1 事件审计若要求"同一水华事件不跨 train/test"，只需在 split-source 里按事件归并 row_id，runner 无需改动。
3. **真实日尺度目标**：T1 若能构造真实 T+1/3/7/15 配对标签，产生新的监督表后，retrain 模式按 horizon 重建表即可（`HORIZON_MAP_V3` 之外的日尺度时效需先扩 contracts，T3b 与主控确认后做）。
4. **机理面板修复**：提案 4.1 列出的全 0/全 NaN 机理列清单应交给 T1 数据审计核对原始数据（是数据缺失还是构建缺陷），修复后重跑 retrain，`mechanism_degenerate_run` 标志会自动反映机理支路是否恢复信息量。

## T3b 执行清单（T1 交付 + 口径入台账后）

```bash
# 0) 口径确认：主控把 口径冻结提案_20260912.md F1~F6 写入台账；本目录只读
# 1) 离线复算基线（重跑一次作为 T3b 前对照证据）
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py offline \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_offline_pre_T3b.json
# 2) 修机理支路与序数评估（在 modeling_real 内，T3b 范围）：面板机理列补数据 +
#    _fit_mechanism 行有效性门按可用列判定 + evaluate 路径序数标签直通
# 3) T1 split-source 就位后，逐任务重训消融（夜间跑，避开压测与 MEE 整点采集）
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T1 --variant bloom --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T1_draft.json
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T3 --variant density --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T3_draft.json
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T4 --variant biomass --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T4_draft.json
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T5 --variant chla --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T5_draft.json
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T6 --variant probability --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T6p_draft.json
python backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_runner.py retrain \
    --task T6 --variant risk_level --horizons 1,3,7,15 --split-source <T1切分JSON> \
    --out backend/model_runtime_v0_3/evaluation/experiments_r1/ablation_retrain_T6r_draft.json
# 4) 90 天长时效（month_offset=3，需 climatology_history，沿用 cli_real_cv 口径补齐后同法）
# 5) 全部 draft 通过主控审查后，才用 gate.py 重新生成 gate_table.json（冻结评估），并更新 manifest
```

## 纪律

- 不伪造结果：`evidence_source` 字段逐行标注来源（`runs_artifact_offline / retrain_draft / synthetic_selftest`），synthetic 一律不是证据。
- 口径冻结后不换公式/基线/窗口；draft 状态的行不得直接引用为门禁结论。
- 实验大文件不入 git（沿用现有 .gitignore 口径）；本目录只保留 JSON 摘要与脚本。
