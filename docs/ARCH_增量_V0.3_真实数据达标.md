# V0.3 增量架构设计 —— 真实数据达标（ARCH）

> 对应 PRD：`docs/PRD_增量_V0.3_真实数据达标.md`。本设计只覆盖增量，V0.2 既有能力不动。
> 设计基线勘察日期：2026-09-09。所有结论基于实际读码与实读 parquet，非推测。

---

## 0. 数据现实（决定设计的硬约束）

实读 `data-cleaning/storage/final_cleaned/TAIHU_CLEAN_FINAL_V1_20260831/tables/model_dataset.parquet`（914 行 × 71 列，键 = station_id + month）：

| 事实 | 数值 | 设计含义 |
|------|------|----------|
| dataset_split | train 882 / validation 23 / **test 9** | 冻结测试集极小，所有"测试集指标"必须附带 n 披露；门禁表 N.A. 会大量出现，属预期且诚实 |
| target_bloom | **0 行非空** | T1 bloom 无法用现成标签训练，必须走代理标签（chla ≥ 20 μg/L 阈值），provenance 标 `proxy_derived` |
| target_chla | 42 行非空 | 预构建 target 列过稀；由 target_builder 用 wq_chla 按站点做月份平移重造监督表 |
| target_tp/tn/do | 各 576 行非空 | 可直接用，但仍统一走 target_builder 重建以保证口径一致 |
| 面积/覆盖率/密度/生物量/空间 | 无真实标签 | T2-area、T3、T4、T7 默认 **N.A.**（诚实披露）；T2-coverage 可用 rs_clms fcb_prob 作代理（可选，provenance 标注） |

**结论**：V0.3"真实模型族"不是 63 个全量复刻，而是"可训练子集 + 可用性矩阵 + N.A. 如实记录"。门禁比较数由真实评估生成，不预设 189。

---

## Part A：系统设计

### 1. 实现方案与框架选型

#### 1.1 核心技术难点与对策

1. **月度标签 vs 7 个日级预测时效**：月度数据不可能产出真·1/3 日时效。采用"时效→月份偏移"映射并三档披露（见 §7 共享知识）：
   - 1/3d → 当月标签（t+0，档位 `month_granularity`）
   - 7/15d → 当月标签近似（名义"次半月"，月度粒度不可得，档位 `month_approx_half`，manifest 与前端均披露）
   - 30/60/90d → t+1/t+2/t+3 月（档位 `multi_month`；30/60/90 保留"情景推演"标注）
2. **小样本训练**：882 训练行对 RF/XGBoost 足够，但必须简化交叉验证（滚动时间窗在 17 年月度面板上仅能做 2~3 折 expanding window），融合权重校准用 validation 月（23 行）+ 时间折内校准。
3. **置信区间统计口径**：复用 `modeling_v1/uncertainty.py` 的 split-conformal 残差区间（`fit_prediction_intervals` / `interval_diagnostics` 已实现），改造点：残差分位数在"训练折外残差 + validation"上拟合，测试集（n=9）只报告经验覆盖率作为证据，**不**用 9 行拟合。P05/P95 对应 residual 分位 [0.05, 0.95]。
4. **遥感校准与连续栅格（最低成本路径）**：
   - 优先路径（本设计采用）：**rs_overlays 年度产品（43 张 30m Chla PNG，1984–2026，已带 bounds/stats）+ 站点月度值校准 → 像元级月度场**。做法：① 从年度 PNG 按固定色标反解像元 Chla 值（色标为全期固定尺度，可线性反解，误差在 manifest 披露）；② 用 field_samples 226 条与 Sentinel-2 月度产品配对拟合的仿射校准系数，叠加站点月度观测的空间回归（年度产品为基底 + 月度站点残差的 IDW 修正），生成"选定月份"的连续栅格；③ 阈值 20 μg/L 分割得水华边界 GeoJSON。产出物为预生成 PNG + GeoJSON + manifest（与现有 rs_overlays 同构，前端叠加成本≈0）。
   - 不采用：原始 MODIS/Sentinel-2 影像重处理（数据量大、周期不可控，列为后续可选路径）。
   - 诚实口径：栅格 = "年度反演产品 × 地面配对校准 × 月度站点残差修正"的半经验场，`spatial_method: "calibrated_annual_product_plus_station_residual"`；无月度站点覆盖的月份标 `未校准`，仅出年度基底。
5. **10% 门禁实时生成**：新 `gate.py` 在训练完成后扫描全部 run 的 `test_metrics_by_family.json`，按 (时效 × 输出类别) 生成比较明细（fusion vs max(RF, XGB)），比较数、PASS/FAIL/N.A. 全部落盘 `evaluation/gate_table.json`；后端 `acceptance()` 改为读该文件，删除硬编码 189。
6. **双包共存**：V0.3 包默认服务，V0.2 包保留为 legacy（manifest 标 `legacy: true`，API 返回 `package_generation` 字段），支持一键回退（env `TAIHU_MODEL_PACKAGE_DIR` 已支持）。

#### 1.2 框架与库选型（全部为已装依赖，零新增安装风险）

| 用途 | 选择 | 理由 |
|------|------|------|
| 训练 | sklearn 1.9.0 + xgboost 3.4.1 | 与 V0.2 包一致，joblib bundle 兼容 |
| 不确定性 | sklearn IsotonicRegression + 手写 conformal（复用 uncertainty.py） | 已有实现，PRD 指定 conformal/分位数口径 |
| 数据 | pandas 3.0.5 + pyarrow 21 | parquet 直读 |
| 栅格 IO/分割 | rasterio 1.5.1（含 `features.shapes` 多边形化，无需 shapely） | PNG→数组→阈值→GeoJSON 一条链 |
| 服务 | FastAPI 0.140（现有 envelope 机制不动） | 复用 `schemas.Envelope`、`envelope()` |
| 前端 | Vue3 + Leaflet（现有 RsMap/Heatmap 栈） | 栅格叠加走 imageOverlay + GeoJSON layer，架构不动 |

#### 1.3 架构模式

维持现有"分层服务"模式（api → service → runtime package），不做大改。增量集中在三处：
- **离线层（新增）**：`scripts/rs/`（配对、校准、栅格预生成）+ `model_runtime_v0_3/code/modeling_real/`（训练管线）
- **服务层（改造）**：`algorithm_models.py` 双包路由 + 统计区间 + 动态门禁；新增 `rs_raster.py` 栅格场服务
- **展示层（增量）**：两个新页面 + 两个组件小改，路由追加

### 2. 文件列表（相对 `01_我们的开发/`）

#### 2.1 新增（训练与数据，离线）

```
backend/model_runtime_v0_3/
  manifest.json                          # V0.3 包清单（结构见 §7）
  models/                                # 训练输出 joblib（命名 <task>-<variant>-<offset>m-s<seed>.joblib）
  code/modeling_real/__init__.py
  code/modeling_real/contracts_real.py   # 特征契约 v2、时效→月份偏移映射、可用性矩阵常量、风险分级带
  code/modeling_real/target_builder.py   # 站点-月度监督表构造（月份平移、bloom 代理、覆盖率代理）
  code/modeling_real/data_real.py        # StationMonthSource（BatchSource 协议实现，读 parquet、冻结 split）
  code/modeling_real/training_real.py    # 小样本训练循环（复用 fusion/metrics/uncertainty），bundle 落盘
  code/modeling_real/gate.py             # 10% 门禁比较表生成器（扫描 test_metrics_by_family.json）
  code/modeling_real/cli_real.py         # 训练/评估/门禁 CLI（断点续跑：按 run_id 跳过已完成）
  evaluation/gate_table.json             # 生成物：门禁比较明细
  evaluation/availability_matrix.json    # 生成物：(task, horizon) 可训练性 + 原因
  pair_dataset/pairs.parquet             # 生成物：遥感-地面配对表
  pair_dataset/pairs_manifest.json       # 配对规则与计数（规则见 §7）
scripts/rs/build_pair_dataset.py         # field_samples × S2/MODIS 配对
scripts/rs/retrieval_calibration.py      # 仿射校准 + 留出验证 + S2 两组对比选型 → calibration_manifest.json
scripts/rs/build_raster_field.py         # 年度产品 PNG → 像元场 → 月度校准 → 栅格 PNG + 边界 GeoJSON + raster_manifest.json
```

#### 2.2 新增（后端服务）

```
backend/app/rs_raster.py                 # 栅格场服务：读 raster_manifest，返回图层/边界/校准元数据
backend/tests/test_v03_contract.py       # 契约与时效映射测试
backend/tests/test_v03_gate.py           # 门禁表生成与 API 一致性测试
backend/tests/test_v03_uncertainty.py    # conformal 区间覆盖率与元数据测试
backend/tests/test_v03_raster.py         # 栅格/边界 API 测试
```

#### 2.3 修改（后端）

```
backend/app/algorithm_models.py          # 双包路由、OBSERVED_FEATURE_MAP_V2、conformal 区间替换 64 次扰动、
                                         # acceptance() 改读 gate_table.json、spatial_field 委托 rs_raster、
                                         # input_provenance 五分类披露
backend/app/api.py                       # 新增 5 个端点（§3.2），/model/status 扩展 package_generation
```

#### 2.4 新增（前端）

```
src/pages/ComplianceBoard.vue            # 达标看板：6 项逐条状态卡 + 证据展开
src/pages/GateReport.vue                 # 门禁明细表（比较数、PASS/FAIL/N.A.、诚实声明脚注）
src/components/heatmap/RasterLayer.vue   # 栅格图层 + 水华边界矢量叠加 + 校准指标角标（Leaflet 封装）
```

#### 2.5 修改（前端）

```
src/pages/Heatmap.vue                    # 图层切换：连续栅格（新）/ 站点样点（旧，对照保留）
src/components/heatmap/ForecastResultPanel.vue   # 不确定性区改"统计校准（覆盖率 x%，n=…）"；
                                                  # 30/60/90 天固定"情景推演"横幅（读 API compliance 字段）
src/router/index.js                      # 追加 /compliance、/gate-report 路由
```

#### 2.6 文档

```
docs/ARCH_增量_V0.3_真实数据达标.md       # 本文档
docs/sequence-diagram.mermaid            # 时序图提取
docs/class-diagram.mermaid               # 类图提取
```

### 3. 数据结构和接口

#### 3.1 特征契约 v2（`feature_contract_v2_real_station_month`，字段表）

命名原则：**直接沿用清洗包真实列名**（杜绝 V0.2 合成名→真实语义的映射错误）；机理特征加 `mech_` 前缀；滞后特征 `<col>_lag{k}m / _roll3m_mean`。契约内容（列名 + sha256）冻结进 manifest，版本号 `v2.0`。

| 组 | 字段（真实列名） | 数量 | 备注 |
|----|------------------|------|------|
| 水质动态 | wq_codmn, wq_do, **wq_nh4_n**, wq_no2_n, wq_no3_n, wq_ph, wq_phyto_biomass, wq_po4_p, wq_tn, wq_tp | 10 | **氨氮 P0-1 达标点** |
| 气象 | met_air_temperature_c, met_precipitation_mm, met_wind_speed_ms, met_wind_direction_deg, **met_shortwave_radiation_wm2** | 5 | 光照/气象驱动 P0-1 |
| 水文 | hydro_water_level_m, hydro_water_level_std | 2 | |
| 遥感 | rs_clms_lwq_300m_10daily_chla_mean, rs_clms_lwq_300m_10daily_chla_uncertainty, rs_clms_lwq_300m_10daily_fcb_prob, rs_sentinel2_cdse_monthly_30m_{B03,B04,B05,B08,B11,FAI,MCI,NDCI,NDWI}, rs_sentinel2_monthly_20m_{B03,B04,B05}, rs_sentinel2_retrieval_20260802_{chlorophyll_a_experimental_ug_l,fai,mci,ndci,ndwi}, rs_month_low_quality | 20 | 低质月标记进特征 |
| 静态 | static_station_inside_lake, static_station_latitude, static_station_longitude, static_lake_area_km2, static_lake_elevation_mean_m, static_dem_valid_frac | 6 | |
| 日历 | calendar_month_sin, calendar_month_cos | 2 | 周特征删除（月度无意义） |
| 机理 | mech_temperature_factor, mech_light_factor, mech_phosphorus_factor, mech_nitrogen_factor, mech_nutrient_factor, mech_net_growth_rate_d | 6 | 由 mechanism_adapter 用真实水温/光照/营养盐重算，非合成 |
| 状态滞后 | {wq_chla, wq_tp, wq_tn, wq_do, wq_nh4_n, met_air_temperature_c, met_shortwave_radiation_wm2, hydro_water_level_m, rs_clms_lwq_300m_10daily_chla_mean} × {_lag1m, _lag2m, _roll3m_mean} | 27 | |

合计 78 字段。训练/推理共用同一 `contracts_real.FEATURE_COLUMNS_V2`；推理侧 `OBSERVED_FEATURE_MAP_V2` 把 MEE 实时 5 字段 + 月度上下文（站内最近月 wq/met/rs 记录）写入 raw frame，其余仍由冻结预处理器插补并在 `input_provenance` 披露。

#### 3.2 API 增量（响应均为现有 `Envelope{code,data,message}`，要点）

| 端点 | 方法 | 请求要点 | 响应 data 要点 |
|------|------|----------|----------------|
| `/model/status`（改） | GET | — | 新增 `package_generation: "v0_3"`、`legacy_package`（V0.2 概要 + `legacy: true`）、`availability_matrix`（可训练/N.A. 摘要）、`claim_boundary: "real_data_monthly_station_v0_3"` |
| `/model/predictions`（改） | GET | horizon_days, entity_id, focus_metric（不变） | results[].uncertainty 变为 `{method:"split_conformal_residual_quantiles", p05, p95, is_calibrated_confidence_interval: true, coverage:{target:0.9, calibration_n, empirical_coverage_test, test_n}}`；30/60/90 各 result 带 `compliance: {label:"情景推演", locked:true}`；`input_provenance` 五分类 + 各字段插补来源 |
| `/model/acceptance`（改） | GET | — | `comparison_rows/pass/fail/not_applicable` 全部来自 gate_table.json 动态统计；`evidence` 指向 `/model/acceptance/detail` |
| `/model/acceptance/detail`（新） | GET | — | `rows[]: {task_id, variant, horizon_days, target, n_test, primary_metric, fusion_value, best_single_family, best_single_value, uplift, status: PASS/FAIL/NA, na_reason}`；`honesty_note` 固定脚注文本 |
| `/model/calibration/coverage`（新） | GET | — | `items[]: {task_id, horizon_days, coverage_target, empirical_coverage, calibration_n, test_n}`（看板覆盖率图数据） |
| `/model/spatial-field`（改） | GET | horizon_days, metric, `layer=raster\|station`（默认 raster，缺数据自动回退 station 并标注） | `layer:"raster"` 时：`{png_url, bounds, vmin, vmax, issued_month, calibration:{pair_count, r2, rmse, status:"calibrated"\|"annual_base_only"}, boundary:{geojson_url, threshold_ug_l: 20, area_km2}, spatial_method, claim_boundary}` |
| `/rs/retrieval/validation`（新） | GET | — | `{split:"holdout", pairs:[{retrieved, reference, station_id, month, sensor}], metrics:{r2, rmse, mae, n}, s2_group_choice, manifest_ref}` |
| `/acceptance/overview`（新） | GET | — | `items[6]: {id:"P0-1..P0-6", title, status:"达标"\|"未达标"\|"部分达标", evidence:[{label, href}]}`（达标看板数据源） |

#### 3.3 manifest 结构（V0.3 包）

```json
{
  "version": "0.3",
  "package_generation": "v0_3",
  "claim_boundary": "real_data_monthly_station_v0_3",
  "data_version": "TAIHU_CLEAN_FINAL_V1_20260831/model_dataset.parquet",
  "data_sha256": "<parquet 摘要>",
  "feature_contract": {"version": "v2.0", "n_features": 78, "sha256": "<列名清单摘要>"},
  "horizon_month_map": {"1": 0, "3": 0, "7": 0, "15": 0, "30": 1, "60": 2, "90": 3},
  "horizon_granularity_tier": {"1":"month_granularity","3":"month_granularity","7":"month_approx_half","15":"month_approx_half","30":"multi_month","60":"multi_month","90":"multi_month"},
  "scenario_horizons": [30, 60, 90],
  "split": {"train": 882, "validation": 23, "test": 9, "frozen_by": "model_dataset.dataset_split"},
  "models": [{"run_id": "T5-chla-30d", "file": "...", "selected_family": "constrained_blend",
              "test_metrics": {...}, "uncertainty": {"method":"split_conformal", "calibration_n": 23, "empirical_coverage_test": 0.88, "test_n": 9}}],
  "availability_matrix": [{"task_id":"T1","horizon_days":30,"trainable":true,"label_provenance":"proxy_derived_chla_threshold_20"},
                           {"task_id":"T3","horizon_days":30,"trainable":false,"reason":"no_real_label"}],
  "bloom_threshold_ug_l": 20, "risk_bands_ug_l": {"none":10,"low":20,"medium":30,"high":50,"severe":">=50"},
  "legacy": {"v0_2_package": "model_runtime_v0_2", "note": "保留作对照与回退"}
}
```

### 4. 程序调用流程（时序图）

见 `docs/sequence-diagram.mermaid`（两条主线：真实模型族训练+门禁；推理+统计区间+栅格场）。

### 5. 类图

见 `docs/class-diagram.mermaid`。

### 8. 待明确事项（Assumptions & Open Questions）

1. **7/15d 映射口径**：本设计取"当月标签近似"（月度数据无半月粒度）。若主理人希望 7/15d 用 t+1 月，仅改 `horizon_month_map` 常量，管线无需变更。**请主理人确认。**
2. **bloom 代理阈值**：target_bloom 0 行，设计采用 chla ≥ 20 μg/L（PRD 裁定 3 的同一阈值，口径一致）作二值代理，provenance 标 `proxy_derived`。若不可接受则 T1 全部 N.A.。
3. **PNG 色标反解误差**：rs_overlays 为 PNG 年度产品，色标→值的反解存在量化误差（8-bit 色带）。设计已在 raster_manifest 要求披露 `colorbar_inversion_note`；若主理人认为不可接受，唯一替代是原始影像重处理（成本高，建议后续版本）。
4. **测试集 n=9 的统计披露**：所有门禁 PASS/FAIL 行将带 n_test；n<10 的行建议在看板加"样本量提示"角标（本设计已列入 GateReport）。
5. **T2-coverage 代理标签**（fcb_prob ≥ 0.5 面积比）默认不启用，列为 P1 可选实验；启用与否由 T02 实验结果（验证集表现）决定。

---

## Part B：任务分解

### 6. 依赖包（无新增安装；均已在环境中验证存在）

```
# Python（后端/离线）
- pandas==3.0.5, numpy==2.3.5, pyarrow==21        # 数据
- scikit-learn==1.9.0                              # RF / conformal / isotonic
- xgboost==3.4.1                                   # XGB
- joblib, scipy                                    # bundle 与统计
- rasterio==1.5.1                                  # PNG→数组、阈值多边形化
- fastapi==0.140, httpx, pytest==8.4.2             # 服务与测试
- pyyaml                                           # 策略文件（已在用）
# 前端：零新增（Vue3 + Leaflet + 现有组件栈）
```

### 7. 任务列表（按依赖排序，≤5 个）

| ID | 任务名 | Source Files | 依赖 | 优先级 | 预估产出物 |
|----|--------|--------------|------|--------|-----------|
| **T01** | **基础设施：契约 v2 + 监督表构造 + 配对数据集** | `modeling_real/__init__.py`、`contracts_real.py`、`target_builder.py`、`data_real.py`、`scripts/rs/build_pair_dataset.py`、`backend/tests/test_v03_contract.py` | 无 | P0 | 特征契约 v2 冻结文件（78 字段 sha256）、时效映射、可用性矩阵常量；914 行面板→各 (task,horizon) 监督表（含 bloom 代理与风险分级带）；`pairs.parquet` + `pairs_manifest.json`（S2 当月 / MODIS ±3d / 同站最近湖内，五分类 provenance）；契约与时效映射单测通过 |
| **T02** | **训练管线 + 遥感校准 + 门禁生成** | `training_real.py`、`gate.py`、`cli_real.py`、`scripts/rs/retrieval_calibration.py`、`scripts/rs/build_raster_field.py`、`model_runtime_v0_3/manifest.json`、`evaluation/*`、`pair_dataset/` 产物消费 | T01 | P0 | 可训练子集全部 joblib bundle（含 conformal 校准器随 bundle 保存）；`test_metrics_by_family.json` × N；`gate_table.json`（比较数/PASS/FAIL/N.A. 实时生成）；`calibration_manifest.json`（S2 两组择优、留出集 R²/RMSE）；栅格 PNG + 边界 GeoJSON + `raster_manifest.json`；断点续跑 CLI |
| **T03** | **后端服务接入** | `algorithm_models.py`（改）、`api.py`（改）、`rs_raster.py`（新）、`backend/tests/test_v03_gate.py`、`test_v03_uncertainty.py`、`test_v03_raster.py` | T02 | P0 | V0.3 包默认服务 + legacy 回退；5 个新端点 + 3 个改造端点全部可用；统计区间替换 64 次扰动（`is_calibrated_confidence_interval: true` + 覆盖率元数据）；acceptance 动态化（删除 189 硬编码）；合规标注字段锁定；pytest 通过且不回退清洗包 303 项基线 |
| **T04** | **前端增量** | `ComplianceBoard.vue`、`GateReport.vue`、`RasterLayer.vue`、`Heatmap.vue`（改）、`ForecastResultPanel.vue`（改）、`router/index.js`（改） | T03 | P1 | 达标看板（6 卡 + 证据展开）；门禁明细表（含 n<10 样本量提示 + 诚实脚注）；栅格/边界图层与旧样点图层切换 + 校准指标角标；不确定性区"统计校准（覆盖率 x%）"；30/60/90 情景推演横幅（读 API 字段，前端不硬编码可删文案） |
| **T05** | **验收聚合与集成收尾** | `api.py`（/acceptance/overview 聚合逻辑）、`backend/tests/test_v03_overview.py`、`docs/sequence-diagram.mermaid`、`docs/class-diagram.mermaid`、Git tag `v0.3` | T03, T04 | P1 | 6 项达标总览接口与证据链接联通；全量 pytest 通过；门禁结论以真实评估为唯一来源复核；代码/数据产物提交并打 tag |

> 依赖图：T01 → T02 → T03 →（T04、T05）；T05 依赖 T04 仅因验收页联通性检查。

### 8. 共享知识（跨文件约定，工程师必读）

1. **Envelope**：所有 API 响应沿用 `{code, data, message}` envelope（`schemas.Envelope`），不得引入新响应格式。
2. **Provenance 五分类**（沿用清洗包规范）：`observed / derived / proxy_derived / imputed / remote_retrieval`。bloom 代理标签 = `proxy_derived`；栅格值 = `remote_retrieval`（反演值永不成为 observed truth）。
3. **诚实边界字段**（API 必带、前端必显、代码不可移除）：`claim_boundary`、`compliance.label="情景推演"`（仅 30/60/90）、`uncertainty.coverage`（含 n）、门禁 `honesty_note`。
4. **时效粒度三档**：`month_granularity`(1/3d)、`month_approx_half`(7/15d，近似披露)、`multi_month`(30/60/90d)。manifest 的 `horizon_granularity_tier` 是唯一口径来源，前端从 API 读，不本地硬编码。
5. **配对容差规则**（写死在 `pairs_manifest.json`）：Sentinel-2 月度产品 ↔ 地面采样**当月**记录（天然 ±15 天内）；MODIS 日产品 ↔ **±3 天**内最近过境；空间容差 = 同站点或最近湖内位置（≤1 km）；每条配对记录 `pair_rule_version`。
6. **水华边界阈值**：固定 20 μg/L（等价反演值），manifest 披露，不做分位数自适应。
7. **门禁唯一来源**：`evaluation/gate_table.json` 由 `gate.py` 从真实评估产物生成，任何代码不得包含比较数常量；FAIL 时如实输出 + 差距分析，不阻断交付。
8. **run_id 约定**：`{task}-{variant}-{offset}m-s{seed}`（offset 为月份偏移，区别于 V0.2 的 `{h}d`）；bundle 文件名同 run_id。
9. **日期/时间**：一律 ISO 8601 UTC（`month` 字段存 `YYYY-MM`）。
10. **双包回退**：env `TAIHU_MODEL_PACKAGE_DIR` 指向 v0_2 即回退 legacy；V0.3 异常时 status 降级并在 `package_generation` 标注。
