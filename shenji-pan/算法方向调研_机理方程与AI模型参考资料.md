# 算法方向调研：藻类生长动力学方程 + AI 模型参考资料

> 检索日期：2026-08-09
> 对应赛题：A23 · 基于机理和AI融合的地表水蓝藻水华监测预警模型设计与实现
> 定位：本报告是《项目调研_蓝藻水华监测预警类似项目检索报告.md》（8-07）的**算法方向补充**，聚焦三大挑战中的第②项（机理+AI耦合）的地基资料：
> ① 藻类生长动力学方程（Logistic/Monod/Droop）的数学形式与参数文献
> ② 机理约束/物理信息 AI 融合的论文依据（PINN、loss 约束、残差融合）
> ③ 风险等级分级标准（分类模型标签体系的权威依据）
> ④ 太湖/国内最新预测研究（2024-2026）

---

## 一、算法执行路线（三挑战怎么排）

依赖关系与执行顺序：

```
第 1 步（Sprint A）：藻类生长动力学方程 + 种子数据生成
    └─ 对应挑战②的地基，且是审查报告最高优先级动作
第 2 步（Sprint B）：机理+AI 融合（残差补偿 / 物理约束 loss）
    └─ 对应挑战②，产出 R² 提升 ≥10% 对比表（赛题硬指标）
第 3 步（Sprint C）：多源数据治理框架（质控/插补/时空对齐）
    └─ 对应挑战①，先以自研种子数据跑通流程
第 4 步（Sprint D）：多尺度集成 + SHAP + 风险等级分级
    └─ 对应挑战③，业务落地层
```

要点：**种子数据生成与方程建模同步进行**（无数据则模型无法训练）；数据治理框架后置（赛题硬指标是融合提升，需先出算法成果）。

---

## 二、藻类生长动力学方程（机理模型地基）

### 2.1 核心方程体系（可直接落地实现的数学形式）

**总框架**（简化形式，参考文献：检索报告落地建议 + 本报告 2.2 节论文）：

```
dB/dt = μmax · f(T) · f(I) · f(N) · f(P) · B − (m + r) · B − 沉降 − 捕食
```

- `B`：藻类生物量（以叶绿素a Chl-a 为替代指标，mg/m³ 或 μg/L）
- `μmax`：最大比生长速率（蓝藻通常 0.5~2.0 d⁻¹，对温度敏感）
- `m`：死亡率，`r`：呼吸/分泌率

**① 营养盐限制（Monod 方程——胞外溶解态）**

```
f(N) = N / (KN + N)          # 氮限制
f(P) = P / (KP + P)          # 磷限制
```
- `KN`、`KP` 为半饱和常数。太湖修正 Monod 研究表明：**以 TP 为自变量的模型优于以 TN 为自变量**，TP 的短期波动对藻类生长作用更直接。

**② 营养盐限制（Droop 方程——胞内营养储量，两阶段）**
- 第一步（吸收）：吸收速率随胞内磷/碳比变化，随外部溶解性活性磷增大而增大直至最大；营养储量最小的细胞吸收最快
- 第二步（生长）：生长速率由**胞内营养储量**决定（而非胞外浓度）：
  ```
  μ = μmax · (1 − Qmin / Q)
  ```
- `Q` 为胞内营养配额，`Qmin` 为最小配额。对营养盐波动大、需精细模拟的场景（如磷限制型水华）优先用 Droop；简化 MVP 用 Monod。

**③ 温度限制函数（修正 Gauss 曲线）**
```
f(T) = exp(−k1·(T − Topt)²)    # 或分段线性
```
- 蓝藻最适温度 25~30℃，且蓝藻对温度敏感、最大生长速率较低、对磷亲和性强——这解释了夏季高温 + 富磷情境下水华爆发。

**④ 光照限制（Steele 方程——含强光抑制）**
```
f(I) = (I / Iopt) · exp(1 − I / Iopt)
```
- 含自我遮蔽效应（Beer-Lambert 衰减），深水区分层模拟时用。

**⑤ 消减过程**：呼吸、分泌、死亡、沉降、浮游动物捕食（捕食滤食速率随藻密度增加呈双曲线型减少，也可用 Monod 形式表达）。

### 2.2 关键参考文献

| 文献 | 内容 | 对本赛题的价值 |
|---|---|---|
| [Evaluation of a Modified Monod Model for Predicting Algal Dynamics in Lake Tai](http://oa.las.ac.cn/oainone/service/browseall/read1?ptype=JA&workid=JA202003190009667ZK) | 太湖修正 Monod 模型评估：以 Chl-a 为指标、TN/TP/水温为自变量；月尺度优于 3 天尺度；湖心优于湖湾；**TP 优于 TN**；温度与营养盐交互作用显著 | ⭐️ 场景 1:1，直接支撑模型设计决策与参数选择 |
| [汉江水华水文因素作用机理——基于藻类生长动力学的研究](https://yangtzebasin.whlib.ac.cn/CN/abstract/abstract8942.shtml) | 连续流反应器原理 + Monod 推导藻浓度与流速指数关系 a = m·exp(k/ν)，实测回归 m=8.9759、k=0.9054，r=0.9244 | 水文因素（流速）纳入机理的表达示例 |

### 2.3 参数参考值（蓝藻特性）

- 蓝藻：最大生长速率较低（相对绿藻/硅藻）、对温度敏感、对磷亲和性强、最大磷吸收速率高
- 硅藻：最适生长温度偏低；绿藻：不受强光抑制、生长速率较大
- 半饱和系数（附生藻类实测参考，Chl-a 计）：N 饱和 150–2450 µg NO₃-N/L，P 饱和 12–29 µg-P/L
- 参数需结合实测率定；**本赛题用自研种子数据，参数可按文献取值并注明来源**

---

## 三、机理 + AI 融合架构（挑战②的论文依据）

### 3.1 物理约束深度学习（最直接的"机理约束+AI增强"背书）

**[Physics-informed deep learning for predicting phytoplankton dynamics and hypoxia in enclosed waters（Geomate Journal, 2026, Lake Biwa 琵琶湖）](https://geomatejournal.com/geomate/article/view/5709)**

三个对照 case（这正是赛题可复制的实验设计！）：
- Case 1：纯观测数据输入（纯数据驱动）
- Case 2：加入质量平衡方程推导的机理特征作为输入（物理特征增强）
- Case 3：将物理平衡约束**直接加入 loss 函数**（硬约束）

结果：Case 2 使 LSTM 的 Chl-b 预测 RMSE 从 0.41 降到 0.35 µg/L；DO 预测误差降 15~25%；长期预测中 Case 2/3 均有显著提升（p=0.00）。结论：**物理约束对捕捉慢变生态过程（长期趋势）特别有效**。

> 论文级背书要点：赛题要求"机理约束+AI增强"，此论文提供三 case 对照的实验范式，可直接移植为融合策略对比报告（材料②）的核心章节。

### 3.2 物理机制与机器学习融合 + 多模式集合（不确定性量化）

**[融合物理机制和机器学习的湖泊叶绿素a模型及其多源数据同化（太湖流域管理局网站，2024-08 发布）](https://www.tba.gov.cn/slbthlyglj/2023nslxxhly/content/810c5372-e018-4ce1-b0d0-16b3e2e86597.html)**

- 耦合物理过程模型与深度学习（LSTM、RF、SVM）的 Chl-a 短期预报模型
- **基于贝叶斯模型平均（BMA）的湖泊藻华多模式集合预报**：提升精度同时量化预报不确定性
- 价值：与挑战③"不确定性"需求直接对应；BMA 可作为多模型集成（LSTM+XGBoost+Transformer）的融合方案备选

### 3.3 残差融合架构（已有调研覆盖，此处仅确认定位）

对标 [LeiGao2016/cyanobacterial-concentration-prediction-HybridModel](https://github.com/LeiGao2016/cyanobacterial-concentration-prediction-HybridModel)（DWT+LSTM+ARIMA+残差补偿）。赛题可行的融合分层：
1. **机理层**：动力学方程模拟基准（趋势）→ 物理趋势
2. **AI 层**：LSTM/XGBoost 预测 → 细节拟合
3. **残差层**：机理与 AI 的残差再学习 → 最终融合
4. （可选）**约束层**：物理约束 loss 或单调性约束 → 保证遵循物理规律

---

## 四、风险等级分级标准（分类模型的标签体系依据）⭐️

挑战③"风险等级分类模型"需要权威标签体系，以下是可直接采用的：

### 4.1 WHO 分级（娱乐用水，1998）

| 级别 | 蓝藻密度 | 叶绿素a（蓝藻优势时） | 说明 |
|---|---|---|---|
| 警戒级 | >200 cells/mL | — | 低数量蓝藻，持续监测 |
| 低风险 | >20,000 cells/mL | >10 μg/L | 不太可能有短期健康影响 |
| 中风险 | >100,000 cells/mL | >50 μg/L | 皮肤刺激、胃肠疾病风险 |
| 高风险 | 浮渣（scum）形成 | — | 急性中毒风险，禁止游泳 |

### 4.2 中国行业标准 HJ 1098《水华遥感与地面监测评价技术规范》（五级）

| 级别 | 藻密度 D（个/L） | 水华程度 |
|---|---|---|
| I | D < 2.0×10⁶ | 无水华 |
| II | 2.0×10⁶ ≤ D < 1.0×10⁷ | 无明显水华 |
| III | 1.0×10⁷ ≤ D < 5.0×10⁷ | 轻度水华 |
| IV | 5.0×10⁷ ≤ D < 1.0×10⁸ | 中度水华 |
| V | D ≥ 1.0×10⁸ | 重度水华 |

> 内陆湖库蓝藻水华综合定义：肉眼可见蓝藻颗粒 + 表层 Chl-a ≥ 20 μg/L + 藻密度 ≥ 1.0×10⁷ 个/L。
> 地方参考：江西省 DB36T2220-2026 亦以藻密度（<1×10⁷ 个/L）和 Chl-a（<20 μg/L）为控制阈值。

### 4.3 ⭐️ 滇池标准 DB5301/T 56—2021 —— 多时间尺度预警的权威依据

- **预警分期（与赛题三尺度高度吻合）**：
  - 年度趋势分析（时效 1 年）
  - 季度预测（30~90 天）→ 对应赛题**长期预测**
  - 短期预警（7~30 天）→ 对应赛题**趋势预测 7-15 天**
  - 应急预警（3 天内）→ 对应赛题**短期预报 1-3 天**
- 预警等级：引用 HJ 1098 藻密度五级分级
- 整体水域判定：藻密度 <2.0×10⁶ 个/L 的点位占比 >95% 判 I 级；某级点位占比 ≥75% 判该级；否则取平均值判定

### 4.4 叶绿素a 关键阈值速查

| 用途 | 阈值 |
|---|---|
| 藻类开始增殖提示 | >10 μg/L |
| 中国水华定义 | ≥20 μg/L |
| WHO 高风险 | >50 μg/L |
| 藻蓝蛋白 >5 μg/L | 蓝藻优势种群判断 |

---

## 五、太湖/国内最新预测研究（2024–2026）

| 研究 | 方法 | 与本赛题关联 |
|---|---|---|
| [STL + 小波相干 + CNN-BiLSTM 叶绿素a长期趋势预测（STOTEN 2024）](https://www.sciencedirect.com/science/article/abs/pii/S0048969724056018) | 时间序列分解（趋势/季节/残差）+ 小波时频分析 + CNN-BiLSTM；发现太湖 Chl-a 对 TP 响应迅速、对水温存在滞后 | 多时间尺度的分解思路；特征滞后处理 |
| [Attention-BiLSTM 太湖蓝藻预测（河海大学）](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002877934) | CNN 特征提取 + BiLSTM + 注意力权重 | 注意力机制 = 可解释性的雏形（驱动因子权重） |
| [HabLSTM 非平稳聚焦 LSTM（IEEE 2024，已收录调研报告）](https://ieeexplore.ieee.org/document/10560016/citations) | 非平稳特征聚焦 LSTM，太湖实测数据时空预测 | 场景 1:1 |
| [PSO-LSTM 蓝藻水华预测软件（中科院南京地理与湖泊研究所，2024 软著）](https://www.cnern.ac.cn/softDetailArticles.action?article_class_id=7&KKKKKK=1081&pageNow=4) | 粒子群优化 LSTM 超参 | 超参优化思路（答辩可提） |
| [Transformer 多时间尺度 CyanoHAB 强度预测（IEEE 2025，Lake Champlain）](https://ieeexplore.ieee.org/abstract/document/11361021/metrics) | 遥感 → 多时间尺度 Transformer 预报 + 阈值分箱分类 | 多尺度 + 分类输出的一体化设计 |
| [LSTM 对不完整时空数据适应性](https://www.semanticscholar.org/paper/LSTM-networks-provide-efficient-cyanobacterial-even-Fournier-Fernandez-Fernandez/d067645c1ad911f25be541f6597bf230d16fbb10) | 数据缺失场景下的 LSTM 鲁棒性 | 支撑"数据质量管控 + 模型"叙事 |

---

## 六、落地建议（下一步 Sprint A 直接开工）

1. **机理方程实现（mechanism.py）**：先做简化版总框架（Monod 营养盐 + 修正 Gauss 温度 + Steele 光照），参数按 2.3 节文献取值；Droop 作为增强版预留。报告注明方程参考来源（WASP/CE-QUAL 系列内置同类方程）
2. **种子数据生成**：以机理方程正演生成太湖 8 站 × 30 天逐小时 Chl-a/水温/TP/TN 序列（有剧情：夏季升温 → 水华爆发 → 预警升级），即为"机理模型基线"输出，同时是 AI 模型训练集
3. **风险等级标签**：分类模型标签直接用 **HJ 1098 五级 + WHO 阈值**，多尺度预警分期直接引用 **DB5301/T 56—2021 四档**（答辩时有据可依）
4. **融合实验设计（直接复刻琵琶湖三 case）**：纯数据 → 物理特征输入 → 物理约束 loss，输出三模型对比表（材料②的骨架）
5. **可解释性**：SHAP 全局/单样本 + Attention 权重双通道，驱动因子排序（水温/TP/氨氮/流速/光照）对齐赛题要求

---

## 附：来源链接

- 太湖修正 Monod：http://oa.las.ac.cn/oainone/service/browseall/read1?ptype=JA&workid=JA202003190009667ZK
- 汉江水华动力学：https://yangtzebasin.whlib.ac.cn/CN/abstract/abstract8942.shtml
- 琵琶湖物理约束深度学习：https://geomatejournal.com/geomate/article/view/5709
- 物理机制+ML融合+BMA（太湖流域管理局）：https://www.tba.gov.cn/slbthlyglj/2023nslxxhly/content/810c5372-e018-4ce1-b0d0-16b3e2e86597.html
- STL+CNN-BiLSTM 长期趋势（STOTEN）：https://www.sciencedirect.com/science/article/abs/pii/S0048969724056018
- Attention-BiLSTM（河海大学）：https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002877934
- HabLSTM（IEEE）：https://ieeexplore.ieee.org/document/10560016/citations
- PSO-LSTM 软著：https://www.cnern.ac.cn/softDetailArticles.action?article_class_id=7&KKKKKK=1081&pageNow=4
- Transformer 多尺度（Lake Champlain, IEEE 2025）：https://ieeexplore.ieee.org/abstract/document/11361021/metrics
- LSTM 不完整数据：https://www.semanticscholar.org/paper/LSTM-networks-provide-efficient-cyanobacterial-even-Fournier-Fernandez-Fernandez/d067645c1ad911f25be541f6597bf230d16fbb10
- HJ 1098 五级标准（藻密度分级）：https://dgj.km.gov.cn/upload/resources/file/2022/02/11/3625905.pdf
- 山仔水库预警系统案例：https://dgj.km.gov.cn/upload/resources/file/2020/08/18/3249268.pdf
- 江西饮用水源蓝藻应急防控技术指南 DB36T2220-2026：https://www.aqrzj.com/doc/418078.html
