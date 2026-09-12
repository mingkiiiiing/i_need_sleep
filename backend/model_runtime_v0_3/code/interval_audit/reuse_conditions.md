# 97.5% 族复用条件表（bloom / probability frozen_split T+1..15 共 8 任务）

- 生成时间：2026-09-12 07:20:11 UTC
- 生成脚本：`code/interval_audit/build_reuse_conditions.py`（只读审计）
- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_reuse_conditions.py`

## 1. 族定义（数据驱动）

从 42 个 run 的 `uncertainty.json` 实测筛选：`empirical_coverage_test = 0.975` 且 `calibration_n = 212`
且 `test_n = 40` 且 artifact 在 manifest 在役清单内 → **命中 8 个**：
T1:bloom 与 T6:probability 的 `frozen_split` off0 h1/3/7/15。与背景口径一致（97.5% 族=8 任务，
proxy 标签，验收线 0.9−0.02=0.88 之上）。校准源声明：`train_expanding_fold_oof_plus_validation_residuals`。

## 2. 复用条件逐行核对（8 行）

| # | artifact_id（task/variant/h） | 模型文件 | sha256 | 特征契约 | 校准源 | label_provenance | 拆分协议 | 结论 |
|---|---|---|---|---|---|---|---|---|
| 1 | T1:bloom:frozen_split:off0:h1:s20260907 | T1-bloom-0m-s20260907-1d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 2 | T1:bloom:frozen_split:off0:h3:s20260907 | T1-bloom-0m-s20260907-3d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 3 | T1:bloom:frozen_split:off0:h7:s20260907 | T1-bloom-0m-s20260907-7d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 4 | T1:bloom:frozen_split:off0:h15:s20260907 | T1-bloom-0m-s20260907-15d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 5 | T6:probability:frozen_split:off0:h1:s20260907 | T6-probability-0m-s20260907-1d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 6 | T6:probability:frozen_split:off0:h3:s20260907 | T6-probability-0m-s20260907-3d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 7 | T6:probability:frozen_split:off0:h7:s20260907 | T6-probability-0m-s20260907-7d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |
| 8 | T6:probability:frozen_split:off0:h15:s20260907 | T6-probability-0m-s20260907-15d.joblib | 一致 | manifest v2.0/78col/frozen ↔ bundle 内嵌 8col | cal_n=212 数值一致 | proxy_derived | frozen_split | **PASS_WITH_CAVEATS** |

### 2.1 各行条件明细

**T1:bloom:frozen_split:off0:h1:s20260907**（run: `T1-bloom-1d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=a300f9d48720f7ef… 实算=a300f9d48720f7ef…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`a300f9d48720f7efdb6509755a81c6f8953771b55129433d662c5e6f5cd576c3`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T1:bloom:frozen_split:off0:h3:s20260907**（run: `T1-bloom-3d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=b87b47a5aa5cd3f4… 实算=b87b47a5aa5cd3f4…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`b87b47a5aa5cd3f47b9aa966fe4ff4c85a46190fba69881578b4d6efefbadbe0`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T1:bloom:frozen_split:off0:h7:s20260907**（run: `T1-bloom-7d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=146aa2ddb2632faf… 实算=146aa2ddb2632faf…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`146aa2ddb2632faff4813b3714f3e160a862e122d73fed8b0aa1b6f74d3be029`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T1:bloom:frozen_split:off0:h15:s20260907**（run: `T1-bloom-15d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=7b5c80289c7e415d… 实算=7b5c80289c7e415d…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`7b5c80289c7e415d7c50df541c899f481030b21ca757030d64a44079d11f1d33`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T6:probability:frozen_split:off0:h1:s20260907**（run: `T6-probability-1d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=cdedb2345915e81d… 实算=cdedb2345915e81d…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`cdedb2345915e81df40e35e6c41a5044dfea06b9523d5e8afef8d4ede5904466`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T6:probability:frozen_split:off0:h3:s20260907**（run: `T6-probability-3d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=078fa57399c69cfc… 实算=078fa57399c69cfc…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`078fa57399c69cfc0efdd0eb53149d508579f5188c3c91a87f2ddaa36ece218f`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T6:probability:frozen_split:off0:h7:s20260907**（run: `T6-probability-7d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=b278a65cd59d0132… 实算=b278a65cd59d0132…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`b278a65cd59d0132e9772723567ec385b7f626cf6a6167b8245036fb3d84f9cb`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

**T6:probability:frozen_split:off0:h15:s20260907**（run: `T6-probability-15d-0m`，cov_test=0.9750）

- [PASS] sha256 一致：manifest=9e40e4e00c1ad982… 实算=9e40e4e00c1ad982…
- [CAVEAT] 特征契约：声明 manifest v2.0/78col/frozen vs 包内 bundle 内嵌 8col（声明与包内不一致）
- [PASS] 校准源：cal_n=212（bundle/run 数值一致）；声明=train_expanding_fold_oof_plus_validation_residuals；bundle 字段为 dataclass 默认值（字符串级口径差）
- [PASS] label_provenance：declared=observed=proxy_derived（manifest 审计 mismatch=0）；注意标签为 CLMS 代理口径
- [PASS] 拆分协议：frozen_split；边界 train≤2021-12 / val≤2023-12 / test≥2024-01；test_n=40
- sha256 全值：`9e40e4e00c1ad982baf7bd31e2c47186a6b44fa26733b86bcdd62484561ba458`；selection_manifest.feature_sha256：`7a8f53ef91734265d86155dfffad3fb8e84140eaa3ef37454b20cf132408e96d`
- bundle 内嵌特征列（8）：wq_tp, wq_tn, wq_do, wq_nh4_n, wq_ph, wq_water_temp, calendar_month_sin, calendar_month_cos

## 3. 交叉发现（影响整族复用的系统性事实）

1. **sha256 全部一致**：8 个模型文件实算 sha256 与 manifest 逐一相等，文件未被篡改/替换。
2. **特征契约声明与包内实际不一致（关键 caveat）**：manifest 声明 frozen-78col 契约（feature_contract v2.0，n_features=78，mode=frozen），
   但 8 个 bundle 内嵌 `feature_columns` 均为 **8 列 serving 契约**（wq_tp/tn/do/nh4_n/ph/water_temp + 
   calendar_month_sin/cos）。任何按 manifest.feature_contract 重建特征输入的复用方都会备错特征。
   复用必须以 **bundle 内嵌列**为准，并以 `selection_manifest.feature_sha256` 做特征帧指纹复核。
3. **校准池高度同源**：8 个任务 cal_n 同为 212、coverage 同为 0.975；且 8 个 bundle 的 residual_p05/p95 完全相同（p05=-0.350995，p95=0.000000，残差池疑似共享）。
   复用时应意识到该族区间不是逐任务独立校准的证据链（逐行残差未持久化，无法自证，见重校准规范）。
4. **标签口径**：label_provenance=proxy_derived（CLMS/阈值代理），manifest 逐行审计 mismatch=0
   （declared=observed）。复用结论仅在「代理标签口径」内成立，不能外推到实测 chla 阳性口径。
5. **拆分协议**：均为 frozen_split，边界 train≤2021-12 / validation 2022-01..2023-12 / test≥2024-01；
   test_n=40（2024-09..2026-08 CLMS 覆盖月）。复用方不得把 validation 段并入任何拟合。

## 4. 结论

- 复用条件结论分布：PASS 0 / **PASS_WITH_CAVEATS 8** / FAIL 0（共 8 行）。
- **可复用的前提**：以 bundle 内嵌 8 列特征契约为准（勿用 manifest 78 列声明）；保持 frozen_split
  拆分与代理标签口径；校准源以 runs/uncertainty.json 声明为准并知悉 bundle 内字段名为默认值。
- 唯一 FAIL 级风险是特征契约声明漂移（78 vs 8）；在 manifest 未修正前，复用方拿到的
  `feature_contract` 元数据不可直接信任。
