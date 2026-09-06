# 存储契约（storage contract）

状态：生效中（2026-09-06 补记成文；`tests/test_storage_contract.py` 为机器可判定契约）

本文件约束 `data-cleaning/storage/` 的存储形态：**一切大二进制以文件形式落盘并由 manifest 登记，表格式存储中禁止 BLOB。**

## 1. 目录职责

| 目录 | 内容 | 写入规则 |
|---|---|---|
| `raw/` | 上游原始字节快照（不可变） | 只增不改；同名存在即跳过；每次写入附 `*.manifest.json` sidecar |
| `manifests/` | 资产 manifest、采集状态、变更留痕 | 只增；`registry_changes.jsonl` 追加式 |
| `silver/` | 清洗后的中间层（如 `geo/taihu_boundary.gpkg`） | 可再生，来源须有 manifest |
| `final_cleaned/`、`releases/` | 发布表（Parquet/CSV） | 由 pipeline 生成，schema 校验通过方可发布 |
| `runs/` | data_factory 运行工件 | 按 dataset 组织 |
| `quarantine/` | 隔离区 | 只进不出；禁止回流 raw/ 或参与清洗 |
| `exports/` | 审计与导出产物（如 `source_field_mapping_audit.csv`） | 由 scripts 生成 |

## 2. 大文件处理（栅格与二进制）

- **栅格**（GeoTIFF/COG）、气象**GRIB**、**NetCDF**、HDF5 等大文件一律作为独立文件存放在 `raw/<source_id>/`（或任务指定的 raw_assets 目录），**不得内嵌进任何表**。
- 每个大文件对应一条 `raw_assets` 记录 / asset manifest，至少包含：`request_url`、`local_path`、`retrieved_at_utc`、`http_status`、`checksum_sha256`、`size_bytes`、`license`、`retries`、`status`（参照 `pipeline/provenance.py::build_asset_manifest`）。
- 断点续传产物 `.partial` 不算完成资产；校验和校验失败不得落盘为正式资产。

## 3. 禁止 BLOB

- 表格式存储（Parquet/CSV/SQLite schema_reference 及一切 `final_cleaned`、`releases` 表）**不得包含 BLOB 列**；二进制一律以外部文件 + 索引字段（`local_path`、`checksum_sha256`、`size_bytes`）引用。
- `tests/test_storage_contract.py::test_reference_schema_has_no_blob_columns_and_has_external_file_index` 对 schema_reference 库做机器校验：BLOB 列查询**结果必须为空**，且 `raw_assets` 表必须携带 `local_path` / `checksum_sha256` / `size_bytes`。
- data_factory 输出契约（`data_factory/contracts/schema.py`）同样只允许标量列。

## 4. 校验和与不可变性

- 原始快照落盘后不再修改；需要重抓时写新时间戳文件，旧文件保留。
- 任何资产的完整性以 `checksum_sha256`（SHA-256）为准；隔离、审计、发布复核均须复算校验和（如 `storage/quarantine/*/quarantine_manifest.json`）。
- manifest 与数据文件成对存在；发现孤儿数据文件或孤儿 manifest 视为契约违规，进入隔离/整改流程。
