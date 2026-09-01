# TAIHU_CLEAN_FINAL_V1_20260831

太湖蓝藻水华项目全量原始数据的统一清洗发布包（唯一正式版本）。

- 运行标识 run_id：`TAIHU_CLEAN_RUN_20260831T132030+0800`
- 生成时间：2026-09-01T13:41:27+08:00
- 输入文件：11794（全部在 file_conclusions.csv 有唯一终态结论）
- 主表记录：152,780 行

## 快速开始

```python
import pandas as pd
df = pd.read_parquet("tables/taihu_clean_final_long.parquet")
df[df.provenance_type == "ground_truth"].head()
```

查询数据库：`database/taihu_clean_final.sqlite`。

## 文件终态分布

| 终态 | 文件数 |
|---|---:|
| METADATA_ONLY | 8747 |
| DUPLICATE | 1307 |
| CLEANED | 1135 |
| REJECTED | 602 |
| BLOCKED_AUTH | 2 |
| QUARANTINED | 1 |

## 目录

- `tables/` 主长表与专题表
- `database/` SQLite 查询库
- `manifests/` 清单、注册表、覆盖审计、血缘、重复、拒绝
- `quality/` 质量报告
- `docs/` 本目录
