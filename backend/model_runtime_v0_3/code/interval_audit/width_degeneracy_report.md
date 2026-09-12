# 区间宽度体检报告（42 run 全量）

- 生成时间：2026-09-12 07:20:20 UTC
- 生成脚本：`code/interval_audit/build_width_degeneracy.py`（只读审计）
- 运行命令：`cd backend && .venv/Scripts/python.exe model_runtime_v0_3/code/interval_audit/build_width_degeneracy.py`

## 1. 口径与判定规则

- **宽度** = bundle.intervals 的 `residual_p95 − residual_p05`（joblib 只读抽取；
  uncertainty.json 未持久化分位数值）。区间 = 点预测 + [p05, p95]。
- **量纲**（相对量纲，逐 variant 披露）：bloom=概率(0-1)；probability=概率(0-1)；density=原值(密度)；biomass=原值(生物量)；chla=原值(μg/L)；risk_level=序数标签(无区间)。
- **actual 分布**：runs/<dir>/test_predictions.csv 的 actual 列（数值解析，NaN 剔除），
  报 Q1/中位/Q3/IQR（numpy 线性插值分位）。
- **判定规则**：
  - `degenerate`：宽度 = 0；
  - `wide`：宽度 > 3 × IQR(actual)（二分类 actual∈{0,1} 时 IQR 常为 0，规则按字面触发，
    标注 `wide(binary_iqr0)` 并注明量纲退化，不粉饰也不误读）；
  - `no_discrimination`：同 (task,variant,protocol) 组内各 horizon 宽度完全相同
    （逐位相等，非零正值，组内 ≥2 个）——区间宽度不随时效分化；
  - `weak_evidence`：coverage = 100% 且 test_n < 10（证据不足）；
  - `undercover`：coverage < 0.88（验收线 = coverage_target 0.90 − 容差 0.02）；
  - `no_interval`（如实扩展类）：区间不存在——risk_level 序数任务 bundle.intervals=None，
    或 run 目录 UNMAPPED 无模型文件。无宽度可检时不得硬套 healthy。
- **主结论优先级**：degenerate > wide > no_discrimination > undercover > weak_evidence >
  no_interval > healthy；所有触发项同时写入 flags 列（CSV）与本报告 flags 栏，不做遮蔽。

## 2. 汇总

| 主结论 | 数量 | 说明 |
|---|---|---|
| wide | 5 | 宽度 > 3×IQR(actual) |
| wide(binary_iqr0) | 10 | 同上，且因二分类 IQR=0 触发（量纲退化，见 4.2） |
| degenerate | 4 | 宽度 = 0 |
| no_discrimination | 8 | 组内各 horizon 宽度完全相同 |
| undercover | 6 | coverage < 0.88 |
| no_interval | 9 | risk_level 无区间 / run UNMAPPED 无模型 |

异常/需关注 run 合计：**42/42**（healthy 除外）。明细：

- `T1-bloom-15d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T1-bloom-1d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T1-bloom-30d-1m-cv` → **degenerate**（flags: degenerate|weak_evidence；cov=1.0000, test_n=5, width=0.0000, IQR=0.0000）
- `T1-bloom-3d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T1-bloom-60d-2m-cv` → **degenerate**（flags: degenerate|weak_evidence；cov=1.0000, test_n=5, width=0.0000, IQR=0.0000）
- `T1-bloom-7d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T1-bloom-90d-3m-cv` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)；cov=1.0000, test_n=28, width=0.1181, IQR=0.0000）
- `T3-density-15d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.7692, test_n=117, width=0.7487, IQR=0.4653）
- `T3-density-1d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.7692, test_n=117, width=0.7487, IQR=0.4653）
- `T3-density-3d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.7692, test_n=117, width=0.7487, IQR=0.4653）
- `T3-density-7d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.7692, test_n=117, width=0.7487, IQR=0.4653）
- `T3-density-90d-3m-cv` → **undercover**（flags: undercover；cov=0.7949, test_n=117, width=0.7309, IQR=0.4653）
- `T4-biomass-15d-0m-cv` → **wide**（flags: wide|no_discrimination|undercover；cov=0.7436, test_n=117, width=21.0279, IQR=5.4852）
- `T4-biomass-1d-0m-cv` → **wide**（flags: wide|no_discrimination|undercover；cov=0.7436, test_n=117, width=21.0279, IQR=5.4852）
- `T4-biomass-3d-0m-cv` → **wide**（flags: wide|no_discrimination|undercover；cov=0.7436, test_n=117, width=21.0279, IQR=5.4852）
- `T4-biomass-7d-0m-cv` → **wide**（flags: wide|no_discrimination|undercover；cov=0.7436, test_n=117, width=21.0279, IQR=5.4852）
- `T4-biomass-90d-3m-cv` → **wide**（flags: wide|undercover；cov=0.8120, test_n=117, width=24.4547, IQR=5.4852）
- `T5-chla-15d-0m` → **undercover**（flags: undercover；cov=0.0000, test_n=1, width=NA, IQR=0.0000）
- `T5-chla-15d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.8030, test_n=132, width=9.9820, IQR=5.0406）
- `T5-chla-1d-0m` → **undercover**（flags: undercover；cov=0.0000, test_n=1, width=NA, IQR=0.0000）
- `T5-chla-1d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.8030, test_n=132, width=9.9820, IQR=5.0406）
- `T5-chla-3d-0m` → **undercover**（flags: undercover；cov=0.0000, test_n=1, width=NA, IQR=0.0000）
- `T5-chla-3d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.8030, test_n=132, width=9.9820, IQR=5.0406）
- `T5-chla-7d-0m` → **undercover**（flags: undercover；cov=0.0000, test_n=1, width=NA, IQR=0.0000）
- `T5-chla-7d-0m-cv` → **no_discrimination**（flags: no_discrimination|undercover；cov=0.8030, test_n=132, width=9.9820, IQR=5.0406）
- `T5-chla-90d-3m-cv` → **undercover**（flags: undercover；cov=0.8547, test_n=117, width=11.1668, IQR=6.6658）
- `T6-probability-15d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T6-probability-1d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T6-probability-30d-1m-cv` → **degenerate**（flags: degenerate|weak_evidence；cov=1.0000, test_n=5, width=0.0000, IQR=0.0000）
- `T6-probability-3d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T6-probability-60d-2m-cv` → **degenerate**（flags: degenerate|weak_evidence；cov=1.0000, test_n=5, width=0.0000, IQR=0.0000）
- `T6-probability-7d-0m` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)|no_discrimination；cov=0.9750, test_n=40, width=0.3510, IQR=0.0000）
- `T6-probability-90d-3m-cv` → **wide(binary_iqr0)**（flags: wide(binary_iqr0)；cov=1.0000, test_n=28, width=0.1181, IQR=0.0000）
- `T6-risk_level-15d-0m` → **no_interval**（flags: -；cov=NA, test_n=1, width=NA）
- `T6-risk_level-15d-0m-cv` → **no_interval**（flags: -；cov=NA, test_n=132, width=NA）
- `T6-risk_level-1d-0m` → **no_interval**（flags: -；cov=NA, test_n=1, width=NA）
- `T6-risk_level-1d-0m-cv` → **no_interval**（flags: -；cov=NA, test_n=132, width=NA）
- `T6-risk_level-3d-0m` → **no_interval**（flags: -；cov=NA, test_n=1, width=NA）
- `T6-risk_level-3d-0m-cv` → **no_interval**（flags: -；cov=NA, test_n=132, width=NA）
- `T6-risk_level-7d-0m` → **no_interval**（flags: -；cov=NA, test_n=1, width=NA）
- `T6-risk_level-7d-0m-cv` → **no_interval**（flags: -；cov=NA, test_n=132, width=NA）
- `T6-risk_level-90d-3m-cv` → **no_interval**（flags: -；cov=NA, test_n=117, width=NA）

## 3. 逐 run 明细（42 行）

机读版：`width_degeneracy.csv`。列含义见第 1 节。

| run 目录 | task/var/T+ | 协议 | test_n | cov | 宽度(量纲) | actual Q1/中位/Q3 | IQR | flags | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| T1-bloom-15d-0m | T1/bloom/T+15 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T1-bloom-1d-0m | T1/bloom/T+1 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T1-bloom-30d-1m-cv | T1/bloom/T+30 | cv | 5 | 1.0000 | 0.0000 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | degenerate|weak_evidence | **degenerate** |
| T1-bloom-3d-0m | T1/bloom/T+3 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T1-bloom-60d-2m-cv | T1/bloom/T+60 | cv | 5 | 1.0000 | 0.0000 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | degenerate|weak_evidence | **degenerate** |
| T1-bloom-7d-0m | T1/bloom/T+7 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T1-bloom-90d-3m-cv | T1/bloom/T+90 | cv | 28 | 1.0000 | 0.1181 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0) | **wide(binary_iqr0)** |
| T3-density-15d-0m-cv | T3/density/T+15 | cv | 117 | 0.7692 | 0.7487 (原值(密度)) | 0.318/0.519/0.783 | 0.465 | no_discrimination|undercover | **no_discrimination** |
| T3-density-1d-0m-cv | T3/density/T+1 | cv | 117 | 0.7692 | 0.7487 (原值(密度)) | 0.318/0.519/0.783 | 0.465 | no_discrimination|undercover | **no_discrimination** |
| T3-density-3d-0m-cv | T3/density/T+3 | cv | 117 | 0.7692 | 0.7487 (原值(密度)) | 0.318/0.519/0.783 | 0.465 | no_discrimination|undercover | **no_discrimination** |
| T3-density-7d-0m-cv | T3/density/T+7 | cv | 117 | 0.7692 | 0.7487 (原值(密度)) | 0.318/0.519/0.783 | 0.465 | no_discrimination|undercover | **no_discrimination** |
| T3-density-90d-3m-cv | T3/density/T+90 | cv | 117 | 0.7949 | 0.7309 (原值(密度)) | 0.318/0.519/0.783 | 0.465 | undercover | **undercover** |
| T4-biomass-15d-0m-cv | T4/biomass/T+15 | cv | 117 | 0.7436 | 21.0279 (原值(生物量)) | 1.214/2.804/6.699 | 5.485 | wide|no_discrimination|undercover | **wide** |
| T4-biomass-1d-0m-cv | T4/biomass/T+1 | cv | 117 | 0.7436 | 21.0279 (原值(生物量)) | 1.214/2.804/6.699 | 5.485 | wide|no_discrimination|undercover | **wide** |
| T4-biomass-3d-0m-cv | T4/biomass/T+3 | cv | 117 | 0.7436 | 21.0279 (原值(生物量)) | 1.214/2.804/6.699 | 5.485 | wide|no_discrimination|undercover | **wide** |
| T4-biomass-7d-0m-cv | T4/biomass/T+7 | cv | 117 | 0.7436 | 21.0279 (原值(生物量)) | 1.214/2.804/6.699 | 5.485 | wide|no_discrimination|undercover | **wide** |
| T4-biomass-90d-3m-cv | T4/biomass/T+90 | cv | 117 | 0.8120 | 24.4547 (原值(生物量)) | 1.214/2.804/6.699 | 5.485 | wide|undercover | **wide** |
| T5-chla-15d-0m | T5/chla/T+15 | frozen | 1 | 0.0000 | NA (原值(μg/L)) | 0.030/0.030/0.030 | 0.000 | undercover | **undercover** |
| T5-chla-15d-0m-cv | T5/chla/T+15 | cv | 132 | 0.8030 | 9.9820 (原值(μg/L)) | 3.065/5.115/8.106 | 5.041 | no_discrimination|undercover | **no_discrimination** |
| T5-chla-1d-0m | T5/chla/T+1 | frozen | 1 | 0.0000 | NA (原值(μg/L)) | 0.030/0.030/0.030 | 0.000 | undercover | **undercover** |
| T5-chla-1d-0m-cv | T5/chla/T+1 | cv | 132 | 0.8030 | 9.9820 (原值(μg/L)) | 3.065/5.115/8.106 | 5.041 | no_discrimination|undercover | **no_discrimination** |
| T5-chla-3d-0m | T5/chla/T+3 | frozen | 1 | 0.0000 | NA (原值(μg/L)) | 0.030/0.030/0.030 | 0.000 | undercover | **undercover** |
| T5-chla-3d-0m-cv | T5/chla/T+3 | cv | 132 | 0.8030 | 9.9820 (原值(μg/L)) | 3.065/5.115/8.106 | 5.041 | no_discrimination|undercover | **no_discrimination** |
| T5-chla-7d-0m | T5/chla/T+7 | frozen | 1 | 0.0000 | NA (原值(μg/L)) | 0.030/0.030/0.030 | 0.000 | undercover | **undercover** |
| T5-chla-7d-0m-cv | T5/chla/T+7 | cv | 132 | 0.8030 | 9.9820 (原值(μg/L)) | 3.065/5.115/8.106 | 5.041 | no_discrimination|undercover | **no_discrimination** |
| T5-chla-90d-3m-cv | T5/chla/T+90 | cv | 117 | 0.8547 | 11.1668 (原值(μg/L)) | 3.413/5.921/10.079 | 6.666 | undercover | **undercover** |
| T6-probability-15d-0m | T6/probability/T+15 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T6-probability-1d-0m | T6/probability/T+1 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T6-probability-30d-1m-cv | T6/probability/T+30 | cv | 5 | 1.0000 | 0.0000 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | degenerate|weak_evidence | **degenerate** |
| T6-probability-3d-0m | T6/probability/T+3 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T6-probability-60d-2m-cv | T6/probability/T+60 | cv | 5 | 1.0000 | 0.0000 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | degenerate|weak_evidence | **degenerate** |
| T6-probability-7d-0m | T6/probability/T+7 | frozen | 40 | 0.9750 | 0.3510 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0)|no_discrimination | **wide(binary_iqr0)** |
| T6-probability-90d-3m-cv | T6/probability/T+90 | cv | 28 | 1.0000 | 0.1181 (概率(0-1)) | 0.00/0.00/0.00 | 0.00 | wide(binary_iqr0) | **wide(binary_iqr0)** |
| T6-risk_level-15d-0m | T6/risk_level/T+15 | frozen | 1 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-15d-0m-cv | T6/risk_level/T+15 | cv | 132 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-1d-0m | T6/risk_level/T+1 | frozen | 1 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-1d-0m-cv | T6/risk_level/T+1 | cv | 132 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-3d-0m | T6/risk_level/T+3 | frozen | 1 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-3d-0m-cv | T6/risk_level/T+3 | cv | 132 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-7d-0m | T6/risk_level/T+7 | frozen | 1 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-7d-0m-cv | T6/risk_level/T+7 | cv | 132 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |
| T6-risk_level-90d-3m-cv | T6/risk_level/T+90 | cv | 117 | NA | NA (序数标签(无区间)) | NA | NA | - | **no_interval** |

## 4. 交叉发现

### 4.1 校准池共享痕迹（无区分度的根因指向）

- 20 个 run 命中 `no_discrimination`，涉及 5 个 (task,variant,protocol,offset) 组：
  T1/bloom/frozen/off0 四行同为 0.3510；T3/density/cv/off0 四行同为 0.7487；T4/biomass/cv/off0 四行同为 21.0279；T5/chla/cv/off0 四行同为 9.9820；T6/probability/frozen/off0 四行同为 0.3510。同组各 horizon（T+1/3/7/15）宽度逐位相同——
  与复用条件报告第 3 节「8 个 bloom/probability bundle residual_p05/p95 完全相同
  （p05=-0.3510, p95=0.0000）」互为印证：**残差池疑似按任务族共享，而非逐时效独立校准**。
  在逐行校准残差未持久化的现状下（见重校准规范），这一点无法自证清白。

### 4.2 二分类 wide 判定的量纲说明

- bloom/probability 的 actual∈{0,1}，test 段阳性极少（如 T1-bloom 40 行仅 1 例阳性），
  IQR=0 → 3×IQR=0 → 任何正宽度都按字面触发 wide。这类行的 `wide(binary_iqr0)` 标注
  **不构成「区间过宽」的实质指控**，但揭示了另一个实质问题：残差池以 0 附近的负残差为主
  （p95=0.0 意味着 95% 分位残差 ≤0），区间几乎只向单侧张开，这与其 0.975 的高覆盖互为因果。
- 回归任务（density/biomass/chla）的 wide 判定在原值量纲上有效，请看逐行 IQR 数值。

### 4.3 no_interval 的两类来源

- **T6-risk_level（序数）5 个 cv run**：预测为风险带字符串标签，无数值残差可池化
  （training_real.py 对 ordinal 显式跳过 conformal），bundle.intervals=None、cal_n=0、coverage=None。
  这是设计使然，但门禁表相应行为 NA；**该任务族没有任何区间/覆盖率证据**。
- **8 个 UNMAPPED frozen run**（T5-chla 与 T6-risk_level 的 T+1/3/7/15）：无模型文件，
  无从抽取区间；其中 T5-chla 4 个 run 的 cov=0.0（test_n=1）。
