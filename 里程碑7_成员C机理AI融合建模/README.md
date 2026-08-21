# 里程碑七：成员C机理-AI融合建模框架

## 目标

本目录服务于成员C职责：建立机理模型、两种AI模型接口、两种融合策略、模型评估、解释性、不确定性和后端统一调用格式。当前阶段等待队友补充正式数据，因此这里只交付可复跑的算法框架和样例接口，不声明真实预测精度。

## 已完成内容

- Logistic + Monod 风格机理风险指数原型。
- 两种AI接口占位：均值回归器与加权规则回归器。
- 两种融合策略：级联融合与残差融合。
- 回归、分类指标函数。
- 全局特征重要性、敏感性曲线和经验不确定性区间模板。
- `predict(station_id, forecast_scale, target_metrics)` 统一预测函数。
- 样例训练行和后端调用JSON样例生成脚本。

## 当前边界

- `claim_boundary=sample_interface_only`。
- `effect_claim_allowed=false`。
- 当前输出只用于验证成员C接口和算法链路。
- 正式数据到位前，不得写“模型精度提升10%”或类似效果声明。

## 目录

- `01_成果/member_c_modeling_framework/`：样例训练行、预测JSON和交接说明。
- `02_代码/blue_algae_m7/`：成员C算法包。
- `02_代码/run_member_c_demo.py`：生成样例成果。
- `03_测试/tests/`：单元测试。
- `05_文档/`：设计、实施计划、模型选型、数据接入要求、训练记录模板和融合策略对比模板。

## 当前准备材料

- `05_文档/成员C_模型选型报告_V0.1.md`：说明机理模型、两种AI模型、两种融合策略、评价指标、解释性和不确定性路线。
- `05_文档/成员C_数据接入要求_V0.1.md`：给数据成员的字段、标签、时间对齐和质量要求。
- `01_成果/member_c_modeling_framework/required_training_schema_V0.1.csv`：标准训练表字段模板。
- `05_文档/成员C_训练记录模板_V0.1.md`：正式训练后记录数据版本、参数、切分和指标。
- `05_文档/成员C_融合策略对比报告模板_V0.1.md`：正式训练后对比单一机理、单一AI和融合模型。

## 运行

```powershell
$env:PYTHONPATH='C:\Users\高头人\Desktop\省服务外包\里程碑7_成员C机理AI融合建模\02_代码'
& 'C:\Users\高头人\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s 'C:\Users\高头人\Desktop\省服务外包\里程碑7_成员C机理AI融合建模\03_测试\tests' -p 'test_*.py'
& 'C:\Users\高头人\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\高头人\Desktop\省服务外包\里程碑7_成员C机理AI融合建模\02_代码\run_member_c_demo.py'
```

## 队友数据到位后需要替换

1. 用正式样本表替换 `build_demo_rows()`。
2. 确认目标指标：叶绿素a、蓝藻生物量、水华面积或风险等级。
3. 确认短期、中期、长期预测的标签构造方式。
4. 使用时间顺序切分训练集和测试集。
5. 将当前AI接口内部替换为 Random Forest、XGBoost 或团队最终选型模型。
6. 基于真实测试集重新生成训练记录、参数设置、模型指标和融合策略对比报告。
