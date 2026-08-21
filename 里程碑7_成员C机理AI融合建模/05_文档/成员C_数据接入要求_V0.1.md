# 成员C数据接入要求 V0.1

## 1. 用途

本文档用于成员C向数据成员提出训练数据需求。数据到位后，成员C将基于该数据完成机理模型、两种AI模型、两种融合策略、模型评估、解释性分析和不确定性分析。

## 2. 最小可训练数据粒度

推荐数据粒度：

```text
一行 = 一个站点/网格/区域 在 一个日期 上的一条训练样本
```

可接受空间对象：

- `station_id`：站点。
- `grid_id`：空间网格。
- `region_id`：湖区或管理分区。

三者至少提供一个。不要在同一份训练表中混用多个空间粒度，除非额外提供映射关系。

## 3. 必需字段

| 字段 | 类型 | 是否必需 | 说明 |
| --- | --- | --- | --- |
| `date` | date | 是 | 样本日期，格式建议 YYYY-MM-DD |
| `sample_id` | string | 是 | 唯一样本ID，可由日期和空间ID拼接 |
| `spatial_id` | string | 是 | 站点、网格或区域ID |
| `spatial_type` | enum | 是 | `station`、`grid` 或 `region` |
| `target_metric` | enum | 是 | 预测目标，例如 `chlorophyll_a`、`bloom_area`、`bloom_label` |
| `target_value` | number/string | 是 | 目标真实值或标签 |
| `target_unit` | string | 是 | 目标单位 |
| `label_status` | enum | 是 | `observed_positive`、`observed_negative`、`measured_value`、`unknown` |
| `source_type` | string | 是 | 数据来源类型，如水质、气象、遥感、水文 |
| `quality_flag` | enum | 是 | `pass`、`warning`、`fail` |

## 4. 推荐特征字段

| 字段 | 含义 | 单位 | 作用 |
| --- | --- | --- | --- |
| `water_temperature_C` | 水温 | C | 机理模型关键输入 |
| `air_temperature_C` | 气温 | C | 替代或辅助温度特征 |
| `total_phosphorus_mg_L` | 总磷 | mg/L | 营养盐限制 |
| `total_nitrogen_mg_L` | 总氮 | mg/L | 营养盐限制 |
| `ammonia_nitrogen_mg_L` | 氨氮 | mg/L | 水质驱动因子 |
| `dissolved_oxygen_mg_L` | 溶解氧 | mg/L | 水质状态 |
| `ph` | pH | 无量纲 | 水质状态 |
| `solar_radiation_MJ_m2_day` | 太阳辐射 | MJ/m2/day | 光照条件 |
| `wind_speed_m_s` | 风速 | m/s | 水华聚集或扩散 |
| `rainfall_mm_day` | 降雨 | mm/day | 水文气象扰动 |
| `relative_humidity_pct` | 相对湿度 | % | 气象辅助特征 |
| `water_level_m` | 水位 | m | 水文条件 |
| `flow_speed_m_s` | 流速 | m/s | 水动力条件 |
| `chlorophyll_a_ug_L` | 叶绿素a | ug/L | 藻类状态或目标 |
| `bloom_area_km2` | 水华面积 | km2 | 水华空间目标 |
| `blue_algae_biomass_mg_L` | 蓝藻生物量 | mg/L | 藻类状态或目标 |
| `fai` | FAI指数 | 无量纲 | 遥感反演特征 |
| `ndci` | NDCI指数 | 无量纲 | 遥感反演特征 |

## 5. 标签要求

### 5.1 可以作为正样本的情况

- 有明确水华观测记录。
- 水华多边形与样本空间单元相交。
- 叶绿素a或藻密度超过经过团队确认的阈值。
- 风险等级由真实观测或可信业务规则生成。

### 5.2 可以作为负样本的情况

必须有观测覆盖证据，才能作为负样本。例如：

- 当日有完整遥感或巡测覆盖，且确认无水华。
- 站点实测指标低于阈值，且质量标记为可信。
- 业务记录明确为无风险或无水华。

### 5.3 不能作为负样本的情况

- 某天没有文件。
- 某区域没有被观测到。
- 数据缺失。
- 标签状态是 `unknown`。

这些情况不能写成 0，只能保留为 `unknown` 或从训练样本中排除。

## 6. 时间对齐要求

成员C训练模型时需要预测未来，因此特征和标签必须明确时间关系。

推荐规则：

```text
使用 T 日及之前的特征，预测 T+1、T+7、T+30 等未来标签
```

禁止：

- 使用预测目标当天之后的数据。
- 使用未来标签构造当前特征。
- 在随机切分中把未来样本泄漏到训练集。

训练/测试切分建议：

- 按时间顺序切分。
- 较早时间作为训练集。
- 较晚时间作为测试集。
- 不使用随机打散作为主评估方式。

## 7. 交付给成员C的文件建议

建议成员B最终给成员C以下文件：

1. `model_training_samples_V0.1.csv`
2. `model_feature_dictionary_V0.1.csv`
3. `model_label_dictionary_V0.1.csv`
4. `data_quality_report_V0.1.json`
5. `source_traceability_V0.1.csv`
6. `known_limitations_V0.1.md`

## 8. 成员C接收数据后的验收

收到数据后，成员C先做以下检查：

1. 字段是否齐全。
2. 日期是否可解析。
3. 空间ID是否稳定。
4. 单位是否明确。
5. 是否有正样本。
6. 是否有可信负样本。
7. 是否存在 unknown 标签。
8. 特征日期和标签日期是否有交集。
9. 是否能按时间顺序切分。
10. 是否存在明显数据泄漏风险。

只有这些检查通过后，才进入正式训练。

## 9. 当前最小可接受版本

如果完整数据暂时无法一次到位，成员C可以先接收一个最小版本：

- 至少 100 行样本。
- 至少 2 类数据源。
- 至少 1 个预测目标。
- 至少 1 个空间粒度。
- 至少包含正样本和可信负样本。
- 至少包含日期、空间ID、目标值和 5 个以上特征。

如果没有可信负样本，则只能做接口验证或描述性分析，不能做正式分类模型效果声明。
