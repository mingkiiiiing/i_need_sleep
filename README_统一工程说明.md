# 我们的开发（统一工程）

这里是一套完整工程，不再按“前端 / 后端 / 算法 / 数据清洗”拆成彼此独立的归档。

- 主体来自最新开发目录 `2026_sheng-fuwai-main-merge`；
- 旧开发目录 `2026_sheng-fuwai` 中主工程没有的文件，已按原相对路径补入；
- `src`、`backend`、`data-cleaning`、算法目录、配置、测试、报告和项目文档保持在同一个项目根目录；
- 大体积原始数据统一放在同级的 `02_全部原始数据`，没有混进程序目录；
- 历史计算成果、数据库、发布包、栅格资产、前端依赖和必要授权资料均已纳入；Git 提交历史保存在 `history` 中的可移植 bundle。授权资料位于 `private`，复制或分享前需谨慎处理。

本目录是整理后的唯一完整工程；旧工作目录核验后可由本汇总替代。

## GitHub 唯一工作目录

从 2026-09-01 起，本目录同时作为 `mingkiiiiing/i_need_sleep` 的唯一 Git 工作区。以后执行 `git pull`、`git commit`、`git push` 或从 GitHub 同步代码，都只能在这里进行：

`D:\Project\fuwai\项目完整汇总_2026-08-31\01_我们的开发`

GitHub 只保存程序代码、配置、测试和必要说明文档。以下内容只保留在本机，严禁提交或上传：

- `02_全部原始数据` 中的全部原始数据；
- `data-cleaning/storage` 中的清洗结果、中间产物、数据库、栅格和发布包；
- `private` 中的授权回执与凭据；
- `history` 中的 Git bundle；
- `node_modules`、`dist`、测试缓存、运行日志和过程报告；
- Parquet、SQLite、GeoTIFF、HDF、NetCDF、GRIB、RAR、ZIP 等数据或归档文件。

这些规则由根目录 `.gitignore` 强制执行。上传前仍应运行 `git status` 和敏感信息检查，不能只依赖忽略规则。
