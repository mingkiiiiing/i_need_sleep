# 太湖数据清洗总结（自动生成）

生成时间: 2026-08-24 01:29:42（北京时间）

## 1. 找到了哪些数据

扫描 `data-cleaning/storage` 下数据文件并归档（复制，不删不改原文件）：
- 归档目录: `data-cleaning/storage/raw_organized/`
- 清单: `data-cleaning/storage/manifests/raw_data_inventory.csv`
- 共 4220 个文件行登记；实际归档 1314 个文件（约 16.3 GB）；重复文件用 SHA-256 识别，只保留一份；派生/中间产物目录（runs/exports/gold/releases）仅登记不复制。

**数据源清单：**

| 类别 | 数据源 | 主要内容 | 时间范围 | 状态 |
|---|---|---|---|---|
| 水质 | THQBCA-V2 1.WaterQuality.xlsx | TP/TN/DO/pH/CODMn/氨氮/硝氮/亚硝氮/磷酸盐/浮游动植物，全湖+8湖区 | 2005-02~2020-11（月度；部分年尺度） | 已清洗 |
| 水质 | MEE 地表水月报（太湖湖体，55 期 PDF+OCR） | 全湖水质评价、总氮评价、营养状态、监测点数（17 点位） | 2022-01~2026-06 | 已解析为评价文本 |
| 水质 | 国家水站批次（HJ1404 标准） | 叶绿素 a 等（S1 等） | 2026-08-18 | 仅 11 条，无历史序列 |
| 水质 | 西湖/水功能区探针（mwr_lake 等） | — | — | 仅探针 HTML，无有效数据 |
| 气象 | NASA POWER 逐小时（格点 120.3E/31.2N） | 气温/10m风速/风向/降水/短波辐射 | 2005-2025（缺 2021） | 已清洗，876,600 行 |
| 气象 | ECMWF/GFS 预报 & Open-Meteo 季节集合 | 预报场（非观测） | 2026-08-18 等 | 仅归档，未入训练表 |
| 水文 | THQBCA 3.Climate WaterLevel | 逐日平均水位(m) | 2004-01~2020-12 | 已清洗，6,156 行 |
| 水文 | 水利部水情批次(mwr_hfc) | 太湖站实时水位 | 2026-08-19~23 | 仅 6 行 |
| 水文 | tba_hydrology(太湖流域水利门户) | — | — | **失败**：HTTP 403/406，需人工申领 |
| 遥感 | Sentinel-2 CDSE 月合成 30m | B03/04/05/08/11+SCL+NDCI/MCI/FAI/NDWI | 2022-01~2026-08（56 个月） | 已建索引+全湖统计 |
| 遥感 | Sentinel-2 20m 补片 | B03/04/05 | 2022-01、2026-01 | 已登记 |
| 遥感 | CLMS LakeWaterQuality 300m v2 | 叶绿素均值/不确定度/蓝藻水华概率/质量位 | 2024-09~2026-08（10 日产品） | 已建索引+月度聚合 |
| 遥感 | THQBCA-V2 Bio-optics 年度 | FAC 浮藻覆盖/Chl-a/SDD/TSI/水生植被 | 1984~2022（年度） | 已建索引+全湖统计 |
| 遥感 | Sentinel-2 反演实验(20260802 单景) | NDCI/MCI/FAI/NDWI/Chl-a | 2026-08-02 | 已登记+全湖统计 |
| 遥感 | EarthSearch 2022 年度拼图 | 红/绿/近红外块 | 2022-05、2022-10 | 仅登记 |
| 现场样本 | Zenodo Lake Taihu 采样 | Chl-a/TSM/SDD/水温+400-900nm 光谱 | 2020-12、2022-12、2023-10（41 样） | 已清洗 |
| 静态 | Copernicus DEM GLO-30 / ESA WorldCover / HydroBASINS / HydroLAKES | 高程、坡度、土地覆盖、流域、湖界 | 静态 | 已汇总为特征 |

## 2. 清洗了什么数据

- 水质: 6811 行（THQBCA 月序列 + 55 期 MEE 评价 + 水站批次）；字段统一小写下划线；单位统一 mg/L（叶绿素 a、TP、TN、DO、CODMn、氮磷分量）。
- 气象: 876600 行；时间由 UTC 转北京时间（YYYY-MM-DD HH:MM:SS 北京）；站点 NASA_POWER_120.300_31.200。
- 水文: 6162 行；水位单位 m。
- 现场样本: 41 个水样；Chl-a µg/L→mg/L（÷1000）；SDD cm→m（保留双列）；光谱提取 rrs@490/560/665/705/842。
- 遥感索引: 880 文件行；月度全湖特征 712 行（mean/median/std/min/max/覆盖度/云量）。
- 静态特征: 1386 行（湖泊 21 + 流域 + 站点）。
- 统一长表: 891825 行；机器宽表: 914 行。

**产出文件与用途**（均在 `data-cleaning/storage/cleaned/`，CSV 为 UTF-8 with BOM，Excel 打开中文不乱码；大表同时有 .parquet）：

| 文件 | 用途 | 行数 |
|---|---|---|
| water_quality_cleaned.csv | 水质观测(长表) + 类别评价 | 6811 |
| meteorology_cleaned.csv | 气象逐小时(北京时间) | 876600 |
| hydrology_cleaned.csv | 水位/流量观测 | 6162 |
| field_samples_cleaned.csv | 现场采样与实验室检测 | 41 |
| static_features_cleaned.csv | 静态空间特征(湖泊/流域/站点) | 1386 |
| remote_sensing_inventory.csv | 遥感文件索引(逐文件) | 880 |
| remote_sensing_monthly_cleaned.csv | 遥感月度全湖特征和质量 | 712 |
| all_data_long.csv | 统一长表(时间×站点×指标) | 891825 |
| model_dataset_monthly.csv | 机器学习月度宽表(带标签/拆分) | 914 |
| data_quality_report.csv | 数据质量报告 | 19 |

## 3. 字段与单位定义

| 字段 | 说明 |
|---|---|
| datetime / date / month | 北京时间；月尺度行 date 取当月 01 日 |
| station_id / station_name | TAIHU_WHOLE（全湖17-21点位均值）、TAIHU_ML/GH/ZS/CT/WT/ST/XK/ET（湖区均值）、NASA_POWER_120.300_31.200（气象格点）、TH-01（水利部太湖站）、S1（国家水站）、IN_SITU_*（现场采样点） |
| longitude / latitude | 仅现场采样与气象格点有坐标；湖区均值站点**无坐标**（数据源未提供，不做推测） |
| variable | 标准变量名：ph、do、codmn、tp、tn、po4_p、nh4_n、no3_n、no2_n、chla、tsm、sdd、water_temperature、air_temperature、wind_speed_10m、wind_direction、precipitation、shortwave_radiation、water_level、ndci、mci、fai、ndwi、chla_retrieval、fcb_prob、category_*（评价类） |
| unit | TP/TN/DO/CODMn/叶绿素a: mg/L；TSM: mg/L；水温/气温: ℃；降水: mm/hour(逐时率)→月累计用 sum；风速: m/s；辐射: W/m²；水位: m；SDD: m；rrs: sr⁻¹ |
| quality_flag | Q00 正常；Q01 时间问题；Q02 坐标问题；Q03 缺失；Q04 非数值；Q05 物理范围外；Q06 单位冲突；Q07 重复；Q09 未检出；Q10 遥感低质量/低覆盖；Q11 派生汇总；Q12 站点缺坐标；Q13 年尺度 |
| quality_note | 问题说明（不删除异常值，只标记） |
| source_name / source_file / source_url | 来源与追溯；source_url 仅 NASA POWER 有明确官网，其余为空（来源文件可查） |
| acquisition_date | 本次处理的北京时间 |
| dataset_split | train(≤2024)/validation(2025)/test(2026) |

## 4. 标签说明

- target_tp / target_tn / target_do：来自 THQBCA 月度水质（197 个月点 × 9 站，576 行有值），其中 TP 可能有单位混用（本数据集以 mg/L 为准，历史文献部分为 µg/L 需注意）。
- target_chla：仅地面实测叶绿素——水站 S1（2026-08，1 条，mg/L）+ 现场采样（41 样，42 行）；**大部分月份没有**。遥感反演 Chl-a（CLMS、THQBCA、单景实验）不是标签，只作特征（rs_*）。
- target_bloom：**无直接观测**，保留为空。可用的替代代理：THQBCA 浮游植物生物量（phyto_biomass，当前作为 wq_ 特征）、CLMS 蓝藻水华概率（rs_clms_lwq_300m_10daily_fcb_prob）；如需真正的藻华标签需人工标注(基于 CLMS FCB 概率阈值或 MEE 月报文本)。

## 5. 训练/验证/测试划分

- **训练集**（train）：882 行，2005-01 ~ 2024-12，站点 11 个；目标有值：TP 576 / TN 576 / DO 576 / Chl-a 41
- **验证集**（validation）：23 行，2025-01 ~ 2025-12，站点 2 个；目标有值：TP 0 / TN 0 / DO 0 / Chl-a 0
- **测试集**（test）：9 行，2026-01 ~ 2026-08，站点 4 个；目标有值：TP 0 / TN 0 / DO 0 / Chl-a 1

## 6. 哪些月份或变量缺失

| 缺口 | 说明 |
|---|---|
| 气象 2021 全年 | NASA POWER history_2021.json 未获取；可用 ECMWF ERA5-Land 或 GFS 历史场补（需 cfgrib 环境） |
| 水质 2021 年 | THQBCA 月度序列止于 2020-11；MEE 评价始于 2022-01，2021 全年无水质月序列 |
| 水质 2005 前与 2020-11 后 | THQBCA 仅覆盖 2005-2020 月度 |
| 水文 2021-2025 | THQBCA 水位止于 2020-12，mwr 实时批次仅 2026-08；中间 5 年无水位数据 |
| 水位明细（湖泊湖区） | WaterLevel 是湖区平均水位，无各站点水位 |
| 叶绿素 a 观测 | 无历史长序列；仅 41 现场样本 + 1 条水站记录 |
| 遥感月度早于 2022-01 | Sentinel-2 月合成自 2022 起；历史可用 THQBCA 年度（1984-2022，FAC/Chl-a/SDD/TSI），已纳入 rs_annual_* |
| 2022-11 / 2024-04 遥感 | 阴雨导致月合成覆盖极低，已用当月精确影像补片并以 cloud_low_quality 标记（quality_flag=Q10） |
| 站点坐标 | 湖区站点(ML/GH/ZS/CT/WT/ST/XK/ET)、TH-01、S1 无坐标；已在 Q12 标记，不做推断 |
| 遥感参数质量 | CLMS 波段首/末为质量位(QFLAG)；报告中保留但未纳入特征 |

## 7. 仍然存在的风险

1. **缺坐标的湖区均值不能做空间匹配**：THQBCA 湖区条目是区域均值，与站点级遥感/气象匹配时只能使用全湖特征或按区域近似。
2. **单位核实**：C-11 THQBCA 文档中的 TP/TN 为 mg/L 本数据集；历史检索可能存在 ug/L 版本，跨源合并前应再核。
3. **MEE 评价为文本**：全湖类别、总氮类别、营养状态是文字评价（Ⅲ类、中营养等），作为 category 特征，未转成数值评分（若需数值可用 GB3838 分级映射脚本扩展）。
4. **月合成反射率**：SCL 云掩膜基于月合成内各景拼出的 SCL，不能完全消除薄云/云影影响；B11 为 SWIR、B08 NIR 适合水色，B04/B03 陆地像元失真严重（湖外像元已剔除）。
5. **CLMS 叶绿素**：LWQ 300m v2 世界湖泊产品单位 µg/L(≈mg/m³)；用于遥感比对时与现场 Chl-a(mg/L) 需 /1000。
6. **NASA POWER 为格点再分析/卫星产品**，非地面实测；对湖面风速等需注意代表性。
7. **预报数据未纳入**：ECMWF/GFS/Open-Meteo 为 2026-08 预报场，不能当历史观测。
8. **tba_hydrology 申请失败**：水雨情需要人工途径（授权申请回执 storage/authorization/water_station）。
9. **压缩包成员未全量解压**：THQBCA-V2.rar（925MB）内含 Bio-optics/Anthropogenic 成员，其中 Bio-optics 已在 storage/THQBCA-V2 解压；rar 全量哈希已归档。
10. **月高云量月的全湖统计代表性**：低覆盖月（Q10）的均值仅基于少数有效像元，用于训练时建议按 rs_month_low_quality 过滤或加权。

## 8. 运行方式

```bash
# 全流程（幂等，重复运行不产生重复数据）
cd data-cleaning && python scripts/run_full_cleaning.py
# 跳过归档/遥感(若只想重建表格) 
python scripts/run_full_cleaning.py --no-archive --no-remote
```

脚本: `data-cleaning/scripts/`（archive_raw_data / clean_* / build_* / run_full_cleaning）。

## 9. 下一步建议

1. 补齐 2021 年气象与 2021 水质年度评价（ERA5-Land / 中国环境公报）。
2. 获得授权后接入国家/省水站长序列（TP/TN/DO/pH/Chl-a），并补站点坐标。
3. 以 CLMS FCB 概率或月报文本人工构建藻华标签(0/1)后，`target_bloom` 才可有值。
4. 用 THQBCA Bio-optics Chl-a(年度)做遥感-实测交叉验证（CLMS 仅 2024-09 后）。
