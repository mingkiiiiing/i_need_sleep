# 数据核验来源与复核笔记

核验日期：2026-08-25（Asia/Shanghai）

## 原始材料

- 用户转交的算法说明：`模型数据不足与补交说明_V0.1.md`。
- 用户转交的截图：`ef3d4cb8c27b8f9d47d3f2b7d0fd3a6d.png`。
- 当前合并项目：`D:\Project\fuwai\2026_sheng-fuwai-main-merge`。
- 同级旧项目：`D:\Project\fuwai\2026_sheng-fuwai`。
- 赛题原文：`A23.md`。
- 成员 C 数据契约：`里程碑7_成员C机理AI融合建模/05_文档/成员C_数据接入要求_V0.1.md`。

## 复核的数据文件

- `data-cleaning/storage/cleaned/model_dataset_monthly.csv`
- `data-cleaning/storage/cleaned/water_quality_cleaned.csv`
- `data-cleaning/storage/cleaned/field_samples_cleaned.csv`
- `data-cleaning/storage/cleaned/meteorology_cleaned.parquet`
- `data-cleaning/storage/cleaned/hydrology_cleaned.csv`
- `data-cleaning/storage/cleaned/remote_sensing_monthly_cleaned.csv`
- 同级旧项目 `data-cleaning/storage/runs/taihu_wp3_20260818_07/stages/labels/forecast_label_summary.csv`
- 同级旧项目同一批次的 `feature_dataset.csv`、`forecast_label_dataset.csv`、`temporal_alignments.csv`、`resampled_observations.csv`

## 可复核数字

- `model_dataset_monthly.csv`：914 行、71 列、13 个站点/空间对象，月份范围 2005-01 至 2026-08。
- 标签非空数：TP 576、TN 576、DO 576、Chl-a 42、bloom 0。`target_bloom` 是空值，不是数值 0。
- TP/TN/DO 的 576 条记录均为 2005-02 至 2020-11、9 个湖区/全湖对象；日期实际集中在每年 2/5/8/11 月，不是日尺度。
- Chl-a 42 条只落在 4 个日期/月份批次：2020-12-22（10 个现场样本）、2022-12-13（13 个）、2023-10-17（18 个）、2026-08-18（1 个水站记录）。
- 水温不是“整个项目完全没有”：现场样本有 41 条，日期同前三个现场采样日；但没有连续水温时序，且月度模型表没有可用于短临起报的连续水温特征。
- 旧项目最新批次的 `forecast_label_summary.csv`：1–3 天 0/576，7–15 天 0/576，30–90 天 144/576（25%）；目标是 `phytoplankton_biomass` 代理，不是经核验的水华标签。
- 当前合并目录没有四类中间/正式产物，但旧项目多轮批次中存在；当前 `.gitignore` 明确忽略 `storage/runs/`、`storage/exports/`、`storage/databases/`、`storage/releases/`，因此属于交付/合并遗漏，不等同于管线从未生成。
- CLMS 月表的 `chla_mean`、`chla_uncertainty`、`fcb_prob` 三列在 2024-09 至 2026-08 完全相同；`fcb_prob` 的 40 个入模非空值全部大于 1。代码中 `build_remote_sensing.py` 对每个波段循环时重复使用整幅多波段数组，且 65535 填充值未被当前阈值过滤，因此这些 CLMS 特征现状不可用于训练或标签证据。
- Sentinel-2 月度特征覆盖 2022-01 至 2026-08；这是遥感特征，不是地面真值。

## 日期方案的推导

- 推荐补交统一窗口为 2022-01-01 至 2026-08-24：与现有 Sentinel-2 月度覆盖起点对齐，包含 2022–2025 四个完整年度和 2026 年截至核验日前的测试期。
- 为构造 90 天历史滞后，特征前置期向前延伸到 2021-10-03。
- 若真实标签截止 2026-08-24，要求完整未来窗口时，最后可用预测起点分别为：1–3 天至 2026-08-21；7–15 天至 2026-08-09；30–90 天至 2026-05-26。
- 推荐时间切分：训练起点 2022-01-01 至 2024-12-31；验证起点 2025-01-01 至 2025-12-31；测试起点 2026-01-01 至各时域最后可用起点。所有特征必须只使用起报时刻及之前的数据。

## 图表说明

- 所在章节：算法说明逐项核验。
- 分析问题：现有目标和三个未来窗口分别有多少可用样本。
- 图表类型：单序列分类柱状图；横轴为数据项，纵轴为可用行数。
- 支持结论：TP 低频标签数量不等于水华短临标签；水华、1–3 天和 7–15 天可用样本均为 0。
- 配色：单一蓝色根色，不使用冗余图例；精确日期与验收条件仍由表格承载。
