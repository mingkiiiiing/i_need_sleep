# 太湖蓝藻数据大文件外部存储契约

版本：`v1.0`　研究区：太湖　适用阶段：P03-05

## 1. 目标和强制规则

栅格、GRIB、NetCDF、Parquet、SAFE、GeoTIFF、压缩包和其他大型二进制文件必须保存在文件对象目录或经授权的对象存储中。SQLite 只保存文件索引、元数据、时间/空间范围、许可状态、路径和 checksum，不保存这些文件的 BLOB 内容。

以下规则是强制门禁：

1. 大文件进入 `storage/raw/`、`storage/bronze/`、`storage/silver/`、`storage/gold/` 或经批准的对象存储前缀；禁止写入 SQLite BLOB。
2. 每个文件必须有唯一 `source_id + asset_id + checksum_sha256`，并在 `raw_assets` 登记本地路径、大小、时间范围、许可和来源。
3. 下载使用 P03-02 的 `.partial`、Range、checksum 和原子重命名流程；校验失败不得发布为正式文件。
4. 文件名不能包含 Token、密码或未脱敏查询参数；Manifest 中的 URL 必须经过 URL 脱敏。
5. 删除、覆盖或重新处理文件前，必须保留原始 checksum 和处理批次血缘；清洗结果使用新的路径和 asset_id。
6. SQLite 表只允许数值、文本、时间、JSON 文本和路径等元数据类型；核心表不允许 `BLOB` 列。

## 2. 外部目录布局

```text
storage/
├── raw/
│   ├── remote_sensing/<source_id>/<asset_id>.<ext>
│   ├── meteorology/<source_id>/<asset_id>.<grib|nc>
│   ├── authorized_waterstation/<delivery_id>/<asset_id>.<csv|xlsx|json>
│   └── archives/<source_id>/<asset_id>.<zip|rar>
├── bronze/                  # 解压/原生结构副本，仍保留原始 checksum
├── silver/                  # 标准化外部文件、COG、NetCDF 子集
├── gold/                    # Parquet 数据集和可交付衍生文件
├── manifests/               # JSON Manifest，不存大文件内容
└── databases/
    └── schema_reference.sqlite
```

实际路径可以迁移到 S3、MinIO、NAS 或对象存储，但必须在 Manifest 中记录 URI、存储提供方、区域和访问策略。SQLite 不保存二进制文件本身。

## 3. 按文件类型的保存策略

| 类型 | 外部保存位置 | SQLite 登记内容 | 禁止事项 |
|---|---|---|---|
| GeoTIFF/COG/栅格 | `storage/raw` 或 `storage/silver/rasters` | 路径、CRS、bbox、分辨率、时间、checksum、有效像元比例 | 将像元数组写成 BLOB |
| GRIB/GRIB2 | `storage/raw/meteorology` | 路径、起报时刻、步长、成员、变量、bbox、checksum | 下载整球文件后无窗口登记 |
| NetCDF/NC | `storage/raw/meteorology` 或 `storage/silver/netcdf` | 路径、变量、维度、时间范围、bbox、checksum | 将 NetCDF 内容嵌入 SQLite |
| Parquet | `storage/gold/dataset_<version>` | 路径、schema 摘要、行数、分区、checksum | 将整表二进制序列化到 BLOB |
| SAFE/压缩包 | `storage/raw/archives` | 压缩包路径、成员清单、大小、checksum、许可 | 未校验就解压覆盖原始目录 |
| CSV/XLSX/JSON | 小型文件可保留外部原文件；解析记录入标准表 | 文件路径、checksum、行数、编码、版本 | 用清洗结果覆盖原始文件 |

## 4. `raw_assets` 和 Manifest 最小字段

`storage/databases/schema_reference.sqlite` 的 `raw_assets` 表至少登记：

- `asset_id`、`source_id`、`run_id`；
- `request_url`（已脱敏）和 `local_path`/对象 URI；
- `start_time_utc`、`end_time_utc`；
- `checksum_sha256`、`size_bytes`；
- `retrieved_at_utc`；
- `license_tag`、`redistribution_allowed`、`commercial_use`。

统一 Manifest 还应记录 HTTP 状态、响应头（敏感值脱敏）、重试次数、错误信息和 `manifest_type=raw_asset`。大型文件必须能通过 `source_id + asset_id + checksum_sha256` 重建来源和版本。

## 5. 处理和发布流程

1. 下载到 `<asset>.<ext>.partial`，完成后计算 SHA-256。
2. checksum 与来源声明一致后，原子重命名为正式文件，并写入 Manifest。
3. 解压到新的 Bronze 目录，保留原始压缩包和成员清单；禁止覆盖原始目录。
4. 裁剪太湖 bbox、变量和时间窗口，输出 Silver 文件并建立父子资产关系。
5. 生成 Parquet/CSV/COG 时使用新的 `dataset_version_id`，保存 schema、行数和 checksum。
6. 只有经过许可证和再分发过滤的路径，才可进入公开交付包。

## 6. SQLite BLOB 检查

在提交数据库前执行：

```sql
SELECT m.name AS table_name, p.name AS column_name, p.type
FROM sqlite_master AS m
JOIN pragma_table_info(m.name) AS p
WHERE m.type = 'table' AND upper(p.type) = 'BLOB';
```

结果必须为空。若发现 BLOB 列，必须停止发布并将内容迁移到外部文件，再把路径和 checksum 写入 `raw_assets` 或对应索引表。

## 7. 访问、备份和授权

- 原始受限文件只读保存，访问权限按来源许可证和申请回执控制。
- 备份必须同时备份 Manifest、数据库索引和外部文件 checksum；备份恢复后重新校验 checksum。
- 受限原始文件不得上传 GitHub、公开网盘或竞赛附件；公开交付只包含获准的衍生数据和脱敏样例。
- 没有授权的文件只能保留公开元数据、入口 URL 和政策状态，不得伪造为 `authorized`。
