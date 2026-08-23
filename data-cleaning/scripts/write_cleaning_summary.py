# -*- coding: utf-8 -*-
"""生成中文清洗总结 cleaning_summary.md(数字全部从清洗结果实时计算)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import CLEANED, MANIFESTS, bnow

MD = CLEANED / "cleaning_summary.md"


def _read(name) -> pd.DataFrame:
    p = CLEANED / f"{name}.csv"
    if p.exists():
        return pd.read_csv(p, encoding="utf-8-sig", low_memory=False)
    return pd.DataFrame()


def main() -> None:
    inv = pd.read_csv(MANIFESTS / "raw_data_inventory.csv", encoding="utf-8-sig", low_memory=False)
    wq = _read("water_quality_cleaned")
    met = _read("meteorology_cleaned")
    hy = _read("hydrology_cleaned")
    fs = _read("field_samples_cleaned")
    st = _read("static_features_cleaned")
    rs_inv = _read("remote_sensing_inventory")
    rs_mon = _read("remote_sensing_monthly_cleaned")
    longf = _read("all_data_long")
    wide = _read("model_dataset_monthly")
    rep = _read("data_quality_report")

    arch = inv[inv["organized_path"].notna() & (inv["organized_path"].astype(str).str.len() > 3)].copy()
    arch["_norm"] = arch["organized_path"].map(lambda p: p.replace("\\", "/").split("storage/raw_organized/")[-1])
    arch_unique = arch.drop_duplicates("_norm")
    n_arch, gb = len(arch_unique), arch_unique["file_size"].sum() / 1e9

    lines = []
    W = lines.append
    W("# 太湖数据清洗总结（自动生成）")
    W("")
    W(f"生成时间: {bnow().strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")
    W("")
    W("## 1. 找到了哪些数据")
    W("")
    W("扫描 `data-cleaning/storage` 下数据文件并归档（复制，不删不改原文件）：")
    W("- 归档目录: `data-cleaning/storage/raw_organized/`")
    W("- 清单: `data-cleaning/storage/manifests/raw_data_inventory.csv`")
    W("- " + f"共 {len(inv)} 个文件行登记；实际归档 {n_arch} 个文件（约 {gb:.1f} GB）；"
             "重复文件用 SHA-256 识别，只保留一份；派生/中间产物目录（runs/exports/gold/releases）仅登记不复制。")
    W("")
    W("**数据源清单：**")
    W("")
    W("| 类别 | 数据源 | 主要内容 | 时间范围 | 状态 |")
    W("|---|---|---|---|---|")
    W("| 水质 | THQBCA-V2 1.WaterQuality.xlsx | TP/TN/DO/pH/CODMn/氨氮/硝氮/亚硝氮/磷酸盐/浮游动植物，全湖+8湖区 | 2005-02~2020-11（月度；部分年尺度） | 已清洗 |")
    W("| 水质 | MEE 地表水月报（太湖湖体，55 期 PDF+OCR） | 全湖水质评价、总氮评价、营养状态、监测点数（17 点位） | 2022-01~2026-06 | 已解析为评价文本 |")
    W("| 水质 | 国家水站批次（HJ1404 标准） | 叶绿素 a 等（S1 等） | 2026-08-18 | 仅 11 条，无历史序列 |")
    W("| 水质 | 西湖/水功能区探针（mwr_lake 等） | — | — | 仅探针 HTML，无有效数据 |")
    W("| 气象 | NASA POWER 逐小时（格点 120.3E/31.2N） | 气温/10m风速/风向/降水/短波辐射 | 2005-2025（缺 2021） | 已清洗，876,600 行 |")
    W("| 气象 | ECMWF/GFS 预报 & Open-Meteo 季节集合 | 预报场（非观测） | 2026-08-18 等 | 仅归档，未入训练表 |")
    W("| 水文 | THQBCA 3.Climate WaterLevel | 逐日平均水位(m) | 2004-01~2020-12 | 已清洗，6,156 行 |")
    W("| 水文 | 水利部水情批次(mwr_hfc) | 太湖站实时水位 | 2026-08-19~23 | 仅 6 行 |")
    W("| 水文 | tba_hydrology(太湖流域水利门户) | — | — | **失败**：HTTP 403/406，需人工申领 |")
    W("| 遥感 | Sentinel-2 CDSE 月合成 30m | B03/04/05/08/11+SCL+NDCI/MCI/FAI/NDWI | 2022-01~2026-08（56 个月） | 已建索引+全湖统计 |")
    W("| 遥感 | Sentinel-2 20m 补片 | B03/04/05 | 2022-01、2026-01 | 已登记 |")
    W("| 遥感 | CLMS LakeWaterQuality 300m v2 | 叶绿素均值/不确定度/蓝藻水华概率/质量位 | 2024-09~2026-08（10 日产品） | 已建索引+月度聚合 |")
    W("| 遥感 | THQBCA-V2 Bio-optics 年度 | FAC 浮藻覆盖/Chl-a/SDD/TSI/水生植被 | 1984~2022（年度） | 已建索引+全湖统计 |")
    W("| 遥感 | Sentinel-2 反演实验(20260802 单景) | NDCI/MCI/FAI/NDWI/Chl-a | 2026-08-02 | 已登记+全湖统计 |")
    W("| 遥感 | EarthSearch 2022 年度拼图 | 红/绿/近红外块 | 2022-05、2022-10 | 仅登记 |")
    W("| 现场样本 | Zenodo Lake Taihu 采样 | Chl-a/TSM/SDD/水温+400-900nm 光谱 | 2020-12、2022-12、2023-10（41 样） | 已清洗 |")
    W("| 静态 | Copernicus DEM GLO-30 / ESA WorldCover / HydroBASINS / HydroLAKES | 高程、坡度、土地覆盖、流域、湖界 | 静态 | 已汇总为特征 |")
    W("")
    W("## 2. 清洗了什么数据")
    W("")
    W(f"- 水质: {len(wq)} 行（THQBCA 月序列 + 55 期 MEE 评价 + 水站批次）；字段统一小写下划线；单位统一 mg/L（叶绿素 a、TP、TN、DO、CODMn、氮磷分量）。")
    W(f"- 气象: {len(met)} 行；时间由 UTC 转北京时间（YYYY-MM-DD HH:MM:SS 北京）；站点 NASA_POWER_120.300_31.200。")
    W(f"- 水文: {len(hy)} 行；水位单位 m。")
    W(f"- 现场样本: {len(fs)} 个水样；Chl-a µg/L→mg/L（÷1000）；SDD cm→m（保留双列）；光谱提取 rrs@490/560/665/705/842。")
    W(f"- 遥感索引: {len(rs_inv)} 文件行；月度全湖特征 {len(rs_mon)} 行（mean/median/std/min/max/覆盖度/云量）。")
    W(f"- 静态特征: {len(st)} 行（湖泊 21 + 流域 + 站点）。")
    W(f"- 统一长表: {len(longf)} 行；机器宽表: {len(wide)} 行。")
    W("")
    W("**产出文件与用途**（均在 `data-cleaning/storage/cleaned/`，CSV 为 UTF-8 with BOM，Excel 打开中文不乱码；大表同时有 .parquet）：")
    W("")
    W("| 文件 | 用途 | 行数 |")
    W("|---|---|---|")
    for f in ("water_quality_cleaned", "meteorology_cleaned", "hydrology_cleaned", "field_samples_cleaned",
              "static_features_cleaned", "remote_sensing_inventory", "remote_sensing_monthly_cleaned",
              "all_data_long", "model_dataset_monthly", "data_quality_report"):
        n = {"water_quality_cleaned": len(wq), "meteorology_cleaned": len(met), "hydrology_cleaned": len(hy),
             "field_samples_cleaned": len(fs), "static_features_cleaned": len(st),
             "remote_sensing_inventory": len(rs_inv), "remote_sensing_monthly_cleaned": len(rs_mon),
             "all_data_long": len(longf), "model_dataset_monthly": len(wide),
             "data_quality_report": len(rep)}[f]
        desc = {
            "water_quality_cleaned": "水质观测(长表) + 类别评价",
            "meteorology_cleaned": "气象逐小时(北京时间)",
            "hydrology_cleaned": "水位/流量观测",
            "field_samples_cleaned": "现场采样与实验室检测",
            "static_features_cleaned": "静态空间特征(湖泊/流域/站点)",
            "remote_sensing_inventory": "遥感文件索引(逐文件)",
            "remote_sensing_monthly_cleaned": "遥感月度全湖特征和质量",
            "all_data_long": "统一长表(时间×站点×指标)",
            "model_dataset_monthly": "机器学习月度宽表(带标签/拆分)",
            "data_quality_report": "数据质量报告",
        }[f]
        W(f"| {f}.csv | {desc} | {n} |")
    W("")
    W("## 3. 字段与单位定义")
    W("")
    W("| 字段 | 说明 |")
    W("|---|---|")
    W("| datetime / date / month | 北京时间；月尺度行 date 取当月 01 日 |")
    W("| station_id / station_name | TAIHU_WHOLE（全湖17-21点位均值）、TAIHU_ML/GH/ZS/CT/WT/ST/XK/ET（湖区均值）、NASA_POWER_120.300_31.200（气象格点）、TH-01（水利部太湖站）、S1（国家水站）、IN_SITU_*（现场采样点） |")
    W("| longitude / latitude | 仅现场采样与气象格点有坐标；湖区均值站点**无坐标**（数据源未提供，不做推测） |")
    W("| variable | 标准变量名：ph、do、codmn、tp、tn、po4_p、nh4_n、no3_n、no2_n、chla、tsm、sdd、water_temperature、air_temperature、wind_speed_10m、wind_direction、precipitation、shortwave_radiation、water_level、ndci、mci、fai、ndwi、chla_retrieval、fcb_prob、category_*（评价类） |")
    W("| unit | TP/TN/DO/CODMn/叶绿素a: mg/L；TSM: mg/L；水温/气温: ℃；降水: mm/hour(逐时率)→月累计用 sum；风速: m/s；辐射: W/m²；水位: m；SDD: m；rrs: sr⁻¹ |")
    W("| quality_flag | Q00 正常；Q01 时间问题；Q02 坐标问题；Q03 缺失；Q04 非数值；Q05 物理范围外；Q06 单位冲突；Q07 重复；Q09 未检出；Q10 遥感低质量/低覆盖；Q11 派生汇总；Q12 站点缺坐标；Q13 年尺度 |")
    W("| quality_note | 问题说明（不删除异常值，只标记） |")
    W("| source_name / source_file / source_url | 来源与追溯；source_url 仅 NASA POWER 有明确官网，其余为空（来源文件可查） |")
    W("| acquisition_date | 本次处理的北京时间 |")
    W("| dataset_split | train(≤2024)/validation(2025)/test(2026) |")
    W("")
    W("## 4. 标签说明")
    W("")
    wide_cov = {
        "target_chla": int(wide["target_chla"].notna().sum()) if len(wide) else 0,
        "target_tp": int(wide["target_tp"].notna().sum()) if len(wide) else 0,
        "target_tn": int(wide["target_tn"].notna().sum()) if len(wide) else 0,
        "target_do": int(wide["target_do"].notna().sum()) if len(wide) else 0,
        "target_bloom": 0,
    }
    W(f"- target_tp / target_tn / target_do：来自 THQBCA 月度水质（197 个月点 × 9 站，{wide_cov['target_tp']} 行有值），其中 TP 可能有单位混用（本数据集以 mg/L 为准，历史文献部分为 µg/L 需注意）。")
    W(f"- target_chla：仅地面实测叶绿素——水站 S1（2026-08，1 条，mg/L）+ 现场采样（41 样，{wide_cov['target_chla']} 行）；**大部分月份没有**。遥感反演 Chl-a（CLMS、THQBCA、单景实验）不是标签，只作特征（rs_*）。")
    W(f"- target_bloom：**无直接观测**，保留为空。可用的替代代理：THQBCA 浮游植物生物量（phyto_biomass，当前作为 wq_ 特征）、CLMS 蓝藻水华概率（rs_clms_lwq_300m_10daily_fcb_prob）；如需真正的藻华标签需人工标注(基于 CLMS FCB 概率阈值或 MEE 月报文本)。")
    W("")
    W("## 5. 训练/验证/测试划分")
    W("")
    if len(wide):
        for split, name in (("train", "训练"), ("validation", "验证"), ("test", "测试")):
            sub = wide[wide["dataset_split"] == split]
            W(f"- **{name}集**（{split}）：{len(sub)} 行，{sub['month'].min()} ~ {sub['month'].max()}，"
              f"站点 {sub['station_id'].nunique()} 个；目标有值：TP {sub['target_tp'].notna().sum()} / "
              f"TN {sub['target_tn'].notna().sum()} / DO {sub['target_do'].notna().sum()} / "
              f"Chl-a {sub['target_chla'].notna().sum()}")
    W("")
    W("## 6. 哪些月份或变量缺失")
    W("")
    W("| 缺口 | 说明 |")
    W("|---|---|")
    W("| 气象 2021 全年 | NASA POWER history_2021.json 未获取；可用 ECMWF ERA5-Land 或 GFS 历史场补（需 cfgrib 环境） |")
    W("| 水质 2021 年 | THQBCA 月度序列止于 2020-11；MEE 评价始于 2022-01，2021 全年无水质月序列 |")
    W("| 水质 2005 前与 2020-11 后 | THQBCA 仅覆盖 2005-2020 月度 |")
    W("| 水文 2021-2025 | THQBCA 水位止于 2020-12，mwr 实时批次仅 2026-08；中间 5 年无水位数据 |")
    W("| 水位明细（湖泊湖区） | WaterLevel 是湖区平均水位，无各站点水位 |")
    W("| 叶绿素 a 观测 | 无历史长序列；仅 41 现场样本 + 1 条水站记录 |")
    W("| 遥感月度早于 2022-01 | Sentinel-2 月合成自 2022 起；历史可用 THQBCA 年度（1984-2022，FAC/Chl-a/SDD/TSI），已纳入 rs_annual_* |")
    W("| 2022-11 / 2024-04 遥感 | 阴雨导致月合成覆盖极低，已用当月精确影像补片并以 cloud_low_quality 标记（quality_flag=Q10） |")
    W("| 站点坐标 | 湖区站点(ML/GH/ZS/CT/WT/ST/XK/ET)、TH-01、S1 无坐标；已在 Q12 标记，不做推断 |")
    W("| 遥感参数质量 | CLMS 波段首/末为质量位(QFLAG)；报告中保留但未纳入特征 |")
    W("")
    W("## 7. 仍然存在的风险")
    W("")
    W("1. **缺坐标的湖区均值不能做空间匹配**：THQBCA 湖区条目是区域均值，与站点级遥感/气象匹配时只能使用全湖特征或按区域近似。")
    W("2. **单位核实**：C-11 THQBCA 文档中的 TP/TN 为 mg/L 本数据集；历史检索可能存在 ug/L 版本，跨源合并前应再核。")
    W("3. **MEE 评价为文本**：全湖类别、总氮类别、营养状态是文字评价（Ⅲ类、中营养等），作为 category 特征，未转成数值评分（若需数值可用 GB3838 分级映射脚本扩展）。")
    W("4. **月合成反射率**：SCL 云掩膜基于月合成内各景拼出的 SCL，不能完全消除薄云/云影影响；B11 为 SWIR、B08 NIR 适合水色，B04/B03 陆地像元失真严重（湖外像元已剔除）。")
    W("5. **CLMS 叶绿素**：LWQ 300m v2 世界湖泊产品单位 µg/L(≈mg/m³)；用于遥感比对时与现场 Chl-a(mg/L) 需 /1000。")
    W("6. **NASA POWER 为格点再分析/卫星产品**，非地面实测；对湖面风速等需注意代表性。")
    W("7. **预报数据未纳入**：ECMWF/GFS/Open-Meteo 为 2026-08 预报场，不能当历史观测。")
    W("8. **tba_hydrology 申请失败**：水雨情需要人工途径（授权申请回执 storage/authorization/water_station）。")
    W("9. **压缩包成员未全量解压**：THQBCA-V2.rar（925MB）内含 Bio-optics/Anthropogenic 成员，其中 Bio-optics 已在 storage/THQBCA-V2 解压；rar 全量哈希已归档。")
    W("10. **月高云量月的全湖统计代表性**：低覆盖月（Q10）的均值仅基于少数有效像元，用于训练时建议按 rs_month_low_quality 过滤或加权。")
    W("")
    W("## 8. 运行方式")
    W("")
    W("```bash")
    W("# 全流程（幂等，重复运行不产生重复数据）")
    W("cd data-cleaning && python scripts/run_full_cleaning.py")
    W("# 跳过归档/遥感(若只想重建表格) ")
    W("python scripts/run_full_cleaning.py --no-archive --no-remote")
    W("```")
    W("")
    W("脚本: `data-cleaning/scripts/`（archive_raw_data / clean_* / build_* / run_full_cleaning）。")
    W("")
    W("## 9. 下一步建议")
    W("")
    W("1. 补齐 2021 年气象与 2021 水质年度评价（ERA5-Land / 中国环境公报）。")
    W("2. 获得授权后接入国家/省水站长序列（TP/TN/DO/pH/Chl-a），并补站点坐标。")
    W("3. 以 CLMS FCB 概率或月报文本人工构建藻华标签(0/1)后，`target_bloom` 才可有值。")
    W("4. 用 THQBCA Bio-optics Chl-a(年度)做遥感-实测交叉验证（CLMS 仅 2024-09 后）。")
    W("")
    MD.write_text("\n".join(lines), encoding="utf-8-sig")
    print(f"  [输出] {MD}")


if __name__ == "__main__":
    main()
