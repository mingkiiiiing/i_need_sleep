# artifact ↔ run 目录映射核对表（34 在役 artifact × 42 run 目录）

- 生成时间：2026-09-12 18:28:02 UTC
- 生成脚本：`code/interval_audit/build_artifact_run_map.py`（只读审计，无写回）
- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_artifact_run_map.py`

## 1. 映射规则（写入报告，全程零猜测）

1. **权威键**：`runs/<dir>/run_config.json` 的 `artifact_id` 与 `manifest.json` `models[].artifact_id`
   **精确字符串相等**（如 `T1:bloom:frozen_split:off0:h15:s20260907`）。判定只认这个键。
2. **命名交叉校验**（非权威）：run 目录命名 = `{task_id}-{variant}-{horizon_days}d-{month_offset}m`，
   protocol=`train_internal_time_block_cv_v1` 时追加 `-cv` 后缀，`frozen_split` 无后缀。
   manifest 的 `run_id`（如 `T1-bloom-0m-s20260907`）是训练期命名（含 seed），与 run 目录名不是同一命名空间，
   仅作背景说明。
3. **对不上即 UNMAPPED**：run 目录的 artifact_id 不在 manifest → 标 UNMAPPED；
   artifact 找不到 run 目录 → 该行 run_dir 标 `UNMAPPED(no run dir)`。不做模糊匹配。

## 2. 汇总

| 指标 | 数值 |
|---|---|
| manifest 在役 artifact | 34 |
| run 目录总数 | 42 |
| artifact→run 目录映射成功 | 34/34 |
| 命名规则交叉校验通过 | 34/34 |
| 模型文件存在且 sha256=manifest.sha256 | 34/34 |
| bundle↔uncertainty：calibration_n / coverage_target 数值相等 | 34/34 |
| bundle↔uncertainty：calibration_source 字符串不一致 | 29/34 |
| bundle↔uncertainty：risk_level 结构性一致（intervals=None ↔ cal_n=0） | 5/34 |
| bundle↔uncertainty：数值/结构级失配 | 0/34 |
| 无主 run 目录（UNMAPPED，反向） | 8 |

## 3. 34 行映射明细

完整字段见 `artifact_run_map.csv`（UTF-8-SIG）。下表为关键列：

| artifact_id | model file | task/variant/h | label_provenance | run 目录 | cov_test | cal 状态 | unc↔bundle |
|---|---|---|---|---|---|---|---|
| T1:bloom:frozen_split:off0:h15:s20260907 | T1-bloom-0m-s20260907-15d.joblib | T1/bloom/T+15 | proxy_derived | T1-bloom-15d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T1:bloom:frozen_split:off0:h1:s20260907 | T1-bloom-0m-s20260907-1d.joblib | T1/bloom/T+1 | proxy_derived | T1-bloom-1d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T1:bloom:frozen_split:off0:h3:s20260907 | T1-bloom-0m-s20260907-3d.joblib | T1/bloom/T+3 | proxy_derived | T1-bloom-3d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T1:bloom:frozen_split:off0:h7:s20260907 | T1-bloom-0m-s20260907-7d.joblib | T1/bloom/T+7 | proxy_derived | T1-bloom-7d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T1:bloom:train_internal_time_block_cv_v1:off1:h30:s20260907 | T1-bloom-1m-s20260907-30d.joblib | T1/bloom/T+30 | proxy_derived | T1-bloom-30d-1m-cv | 1.0000 | calibrated(cal_n=16) | inconsistency(string) |
| T1:bloom:train_internal_time_block_cv_v1:off2:h60:s20260907 | T1-bloom-2m-s20260907-60d.joblib | T1/bloom/T+60 | proxy_derived | T1-bloom-60d-2m-cv | 1.0000 | calibrated(cal_n=16) | inconsistency(string) |
| T1:bloom:train_internal_time_block_cv_v1:off3:h90:s20260907 | T1-bloom-3m-s20260907-90d.joblib | T1/bloom/T+90 | proxy_derived | T1-bloom-90d-3m-cv | 1.0000 | calibrated(cal_n=261) | inconsistency(string) |
| T3:density:train_internal_time_block_cv_v1:off0:h15:s20260907 | T3-density-0m-s20260907-15d.joblib | T3/density/T+15 | proxy_derived | T3-density-15d-0m-cv | 0.7094 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T3:density:train_internal_time_block_cv_v1:off0:h1:s20260907 | T3-density-0m-s20260907-1d.joblib | T3/density/T+1 | proxy_derived | T3-density-1d-0m-cv | 0.7094 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T3:density:train_internal_time_block_cv_v1:off0:h3:s20260907 | T3-density-0m-s20260907-3d.joblib | T3/density/T+3 | proxy_derived | T3-density-3d-0m-cv | 0.7094 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T3:density:train_internal_time_block_cv_v1:off0:h7:s20260907 | T3-density-0m-s20260907-7d.joblib | T3/density/T+7 | proxy_derived | T3-density-7d-0m-cv | 0.7094 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T3:density:train_internal_time_block_cv_v1:off3:h90:s20260907 | T3-density-3m-s20260907-90d.joblib | T3/density/T+90 | proxy_derived | T3-density-90d-3m-cv | 0.7949 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T4:biomass:train_internal_time_block_cv_v1:off0:h15:s20260907 | T4-biomass-0m-s20260907-15d.joblib | T4/biomass/T+15 | ground_truth | T4-biomass-15d-0m-cv | 0.7863 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T4:biomass:train_internal_time_block_cv_v1:off0:h1:s20260907 | T4-biomass-0m-s20260907-1d.joblib | T4/biomass/T+1 | ground_truth | T4-biomass-1d-0m-cv | 0.7863 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T4:biomass:train_internal_time_block_cv_v1:off0:h3:s20260907 | T4-biomass-0m-s20260907-3d.joblib | T4/biomass/T+3 | ground_truth | T4-biomass-3d-0m-cv | 0.7863 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T4:biomass:train_internal_time_block_cv_v1:off0:h7:s20260907 | T4-biomass-0m-s20260907-7d.joblib | T4/biomass/T+7 | ground_truth | T4-biomass-7d-0m-cv | 0.7863 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T4:biomass:train_internal_time_block_cv_v1:off3:h90:s20260907 | T4-biomass-3m-s20260907-90d.joblib | T4/biomass/T+90 | ground_truth | T4-biomass-90d-3m-cv | 0.8120 (<0.88 验收线) | calibrated(cal_n=225) | inconsistency(string) |
| T5:chla:train_internal_time_block_cv_v1:off0:h15:s20260907 | T5-chla-0m-s20260907-15d.joblib | T5/chla/T+15 | mixed(chla_station_proxy_v1|ground_truth) | T5-chla-15d-0m-cv | 0.8712 (<0.88 验收线) | calibrated(cal_n=234) | inconsistency(string) |
| T5:chla:train_internal_time_block_cv_v1:off0:h1:s20260907 | T5-chla-0m-s20260907-1d.joblib | T5/chla/T+1 | mixed(chla_station_proxy_v1|ground_truth) | T5-chla-1d-0m-cv | 0.8712 (<0.88 验收线) | calibrated(cal_n=234) | inconsistency(string) |
| T5:chla:train_internal_time_block_cv_v1:off0:h3:s20260907 | T5-chla-0m-s20260907-3d.joblib | T5/chla/T+3 | mixed(chla_station_proxy_v1|ground_truth) | T5-chla-3d-0m-cv | 0.8712 (<0.88 验收线) | calibrated(cal_n=234) | inconsistency(string) |
| T5:chla:train_internal_time_block_cv_v1:off0:h7:s20260907 | T5-chla-0m-s20260907-7d.joblib | T5/chla/T+7 | mixed(chla_station_proxy_v1|ground_truth) | T5-chla-7d-0m-cv | 0.8712 (<0.88 验收线) | calibrated(cal_n=234) | inconsistency(string) |
| T5:chla:train_internal_time_block_cv_v1:off3:h90:s20260907 | T5-chla-3m-s20260907-90d.joblib | T5/chla/T+90 | chla_station_proxy_v1 | T5-chla-90d-3m-cv | 0.8889 | calibrated(cal_n=225) | inconsistency(string) |
| T6:probability:frozen_split:off0:h15:s20260907 | T6-probability-0m-s20260907-15d.joblib | T6/probability/T+15 | proxy_derived | T6-probability-15d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T6:probability:frozen_split:off0:h1:s20260907 | T6-probability-0m-s20260907-1d.joblib | T6/probability/T+1 | proxy_derived | T6-probability-1d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T6:probability:frozen_split:off0:h3:s20260907 | T6-probability-0m-s20260907-3d.joblib | T6/probability/T+3 | proxy_derived | T6-probability-3d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T6:probability:frozen_split:off0:h7:s20260907 | T6-probability-0m-s20260907-7d.joblib | T6/probability/T+7 | proxy_derived | T6-probability-7d-0m | 0.9500 | calibrated(cal_n=212) | inconsistency(string) |
| T6:probability:train_internal_time_block_cv_v1:off1:h30:s20260907 | T6-probability-1m-s20260907-30d.joblib | T6/probability/T+30 | proxy_derived | T6-probability-30d-1m-cv | 1.0000 | calibrated(cal_n=16) | inconsistency(string) |
| T6:probability:train_internal_time_block_cv_v1:off2:h60:s20260907 | T6-probability-2m-s20260907-60d.joblib | T6/probability/T+60 | proxy_derived | T6-probability-60d-2m-cv | 1.0000 | calibrated(cal_n=16) | inconsistency(string) |
| T6:probability:train_internal_time_block_cv_v1:off3:h90:s20260907 | T6-probability-3m-s20260907-90d.joblib | T6/probability/T+90 | proxy_derived | T6-probability-90d-3m-cv | 1.0000 | calibrated(cal_n=261) | inconsistency(string) |
| T6:risk_level:train_internal_time_block_cv_v1:off0:h15:s20260907 | T6-risk_level-0m-s20260907-15d.joblib | T6/risk_level/T+15 | mixed(chla_station_proxy_v1|ground_truth) | T6-risk_level-15d-0m-cv | NA | not_calibrated(cal_n=0) | consistent(structural) |
| T6:risk_level:train_internal_time_block_cv_v1:off0:h1:s20260907 | T6-risk_level-0m-s20260907-1d.joblib | T6/risk_level/T+1 | mixed(chla_station_proxy_v1|ground_truth) | T6-risk_level-1d-0m-cv | NA | not_calibrated(cal_n=0) | consistent(structural) |
| T6:risk_level:train_internal_time_block_cv_v1:off0:h3:s20260907 | T6-risk_level-0m-s20260907-3d.joblib | T6/risk_level/T+3 | mixed(chla_station_proxy_v1|ground_truth) | T6-risk_level-3d-0m-cv | NA | not_calibrated(cal_n=0) | consistent(structural) |
| T6:risk_level:train_internal_time_block_cv_v1:off0:h7:s20260907 | T6-risk_level-0m-s20260907-7d.joblib | T6/risk_level/T+7 | mixed(chla_station_proxy_v1|ground_truth) | T6-risk_level-7d-0m-cv | NA | not_calibrated(cal_n=0) | consistent(structural) |
| T6:risk_level:train_internal_time_block_cv_v1:off3:h90:s20260907 | T6-risk_level-3m-s20260907-90d.joblib | T6/risk_level/T+90 | chla_station_proxy_v1 | T6-risk_level-90d-3m-cv | NA | not_calibrated(cal_n=0) | consistent(structural) |

## 4. bundle.intervals（joblib 只读抽取）与 uncertainty.json 对照

`ResidualIntervals` 字段：`residual_p05` / `residual_p95`（区间 = 点预测 ± 残差分位，
宽度 = p95−p05，相对量纲=目标标签量纲：bloom/probability=概率，density/biomass/chla=原值）。
uncertainty.json **不含** p05/p95 数值，仅含汇总（calibration_n / calibration_source / coverage）。

对照结论（分档如实报告）：

- **数值级：calibration_n / coverage_target 在 34/34 个可用 bundle 上
  与 runs/uncertainty.json 完全相等，无任何数值失配。** 其中：
  - 5 个 risk_level（序数）bundle 为**结构性一致**：bundle.intervals=None，与 run 侧
    cal_n=0 / coverage=None 两侧互相印证「无校准区间」；
  - 29 个存在**字符串级不一致**：`intervals.calibration_source` 全部是 dataclass 默认值
    `train_fold_out_of_fold_plus_validation`，而 runs/uncertainty.json 与 manifest 声明为
    `train_expanding_fold_oof_plus_validation_residuals`（bundle 侧 `ResidualIntervals` 默认字段
    未随训练结果覆写）。不影响数值，但同一事实在包内有两个名字，建议后续版本统一。
- **数值/结构级失配 0/34**：无。

不一致逐行清单：

- T1:bloom:frozen_split:off0:h15:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:frozen_split:off0:h1:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:frozen_split:off0:h3:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:frozen_split:off0:h7:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:train_internal_time_block_cv_v1:off1:h30:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:train_internal_time_block_cv_v1:off2:h60:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T1:bloom:train_internal_time_block_cv_v1:off3:h90:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T3:density:train_internal_time_block_cv_v1:off0:h15:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T3:density:train_internal_time_block_cv_v1:off0:h1:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T3:density:train_internal_time_block_cv_v1:off0:h3:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T3:density:train_internal_time_block_cv_v1:off0:h7:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T3:density:train_internal_time_block_cv_v1:off3:h90:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T4:biomass:train_internal_time_block_cv_v1:off0:h15:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T4:biomass:train_internal_time_block_cv_v1:off0:h1:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T4:biomass:train_internal_time_block_cv_v1:off0:h3:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T4:biomass:train_internal_time_block_cv_v1:off0:h7:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T4:biomass:train_internal_time_block_cv_v1:off3:h90:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T5:chla:train_internal_time_block_cv_v1:off0:h15:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T5:chla:train_internal_time_block_cv_v1:off0:h1:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T5:chla:train_internal_time_block_cv_v1:off0:h3:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T5:chla:train_internal_time_block_cv_v1:off0:h7:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T5:chla:train_internal_time_block_cv_v1:off3:h90:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:frozen_split:off0:h15:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:frozen_split:off0:h1:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:frozen_split:off0:h3:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:frozen_split:off0:h7:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:train_internal_time_block_cv_v1:off1:h30:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:train_internal_time_block_cv_v1:off2:h60:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'
- T6:probability:train_internal_time_block_cv_v1:off3:h90:s20260907: calibration_source bundle='train_fold_out_of_fold_plus_validation' vs run='train_expanding_fold_oof_plus_validation_residuals'

## 5. UNMAPPED run 目录（反向核对，8 个）

以下 run 目录的 `run_config.artifact_id` 不在 manifest.models（34）中 → 无模型文件对应，
如实标 UNMAPPED。明细见 `artifact_run_map_unmapped.csv`：

| run 目录 | run_config.artifact_id | protocol | test_n | cov_test |
|---|---|---|---|---|
| T5-chla-15d-0m | T5:chla:frozen_split:off0:h15:s20260907 | frozen_split | 1 | 0.0000 |
| T5-chla-1d-0m | T5:chla:frozen_split:off0:h1:s20260907 | frozen_split | 1 | 0.0000 |
| T5-chla-3d-0m | T5:chla:frozen_split:off0:h3:s20260907 | frozen_split | 1 | 0.0000 |
| T5-chla-7d-0m | T5:chla:frozen_split:off0:h7:s20260907 | frozen_split | 1 | 0.0000 |
| T6-risk_level-15d-0m | T6:risk_level:frozen_split:off0:h15:s20260907 | frozen_split | 1 | NA |
| T6-risk_level-1d-0m | T6:risk_level:frozen_split:off0:h1:s20260907 | frozen_split | 1 | NA |
| T6-risk_level-3d-0m | T6:risk_level:frozen_split:off0:h3:s20260907 | frozen_split | 1 | NA |
| T6-risk_level-7d-0m | T6:risk_level:frozen_split:off0:h7:s20260907 | frozen_split | 1 | NA |

## 6. 结论

- 34/34 在役 artifact 均能以精确 artifact_id 找到唯一 run 目录与唯一模型文件；
  命名交叉校验 34/34 通过（规则可复述）。
- 模型文件 sha256 与 manifest 一致：34/34。
- bundle↔uncertainty：数值级全部一致；唯一的系统性不一致是 calibration_source 字符串
  （bundle=dataclass 默认值 vs run=声明值），属文档口径问题，见第 4 节。
- 42−34=8 个 run 目录 UNMAPPED（T5-chla 与 T6-risk_level 的 frozen_split T+1/3/7/15 共 8 个，
  门禁表亦无对应行——它们是候选 run，未入役）。对不上的如实标注，未做任何猜测式映射。
