# A23 蓝藻水华监测预警系统 — SQLite 数据库完整建表方案

> 版本：v1.0 | 日期：2026-08-27  
> 数据库文件：`storage/data_cleaning.db`（清洗层）+ `backend/business.db`（业务层）  
> 设计依据：`shenji-pan/后端完整修改建议`、`shenji-pan/前后端联调与示例数据统一规范`、`data-cleaning/docs/蓝藻模型数据字典`、`data-cleaning/pipeline/` 全部模块

---

## 0. 当前数据库现状

| 文件 | 位置 | 状态 |
|---|---|---|
| `imputation_validation.sqlite` | `data-cleaning/storage/reports/` | 已存在，仅含 1 张表 `imputation_validation`（18 行） |
| `data_cleaning.db` | `data-cleaning/storage/` | **设计存在但实际未生成**，管道输出全部为 CSV/Parquet |
| 后端业务库 | 无 | **未创建**，后端仅使用 JSON/CSV 演示数据 |

本方案将上述所有数据统一收敛到两个 SQLite 数据库，覆盖从原始清洗到业务预警的完整链路。

---

## 1. 数据库总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    data_cleaning.db (清洗层)                     │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐             │
│  │ 基础设施  │  │  清洗观测层  │  │  特征工程层   │             │
│  │ 4 张表   │  │  8 张表      │  │  10 张表       │             │
│  └──────────┘  └──────────────┘  └───────────────┘             │
│                                                                 │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐          │
│  │  空间对齐层   │  │  遥感资产层   │  │ 质量审计层  │          │
│  │  4 张表      │  │  3 张表       │  │  4 张表     │          │
│  └──────────────┘  └───────────────┘  └────────────┘          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    business.db (业务层)                          │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐             │
│  │ 系统配置  │  │  空间与观测  │  │  预测与解释   │             │
│  │ 3 张表   │  │  4 张表      │  │  5 张表       │             │
│  └──────────┘  └──────────────┘  └───────────────┘             │
│                                                                 │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────┐          │
│  │  预警闭环层   │  │  事件与预案   │  │ 审计与日志  │          │
│  │  6 张表      │  │  4 张表       │  │  3 张表     │          │
│  └──────────────┘  └───────────────┘  └────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

**总计：清洗层 33 张表 + 业务层 25 张表 = 58 张表**

---

## 2. data_cleaning.db — 清洗层

### 2.1 基础设施（4 张表）

```sql
-- ============================================================
-- 2.1.1 schema_version — 数据库版本管理
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at_utc  TEXT    NOT NULL,  -- ISO 8601 UTC
    description     TEXT    NOT NULL
);

-- ============================================================
-- 2.1.2 database_metadata — 键值元数据
-- ============================================================
CREATE TABLE IF NOT EXISTS database_metadata (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at_utc  TEXT
);

-- 初始化种子数据
INSERT OR IGNORE INTO database_metadata (key, value) VALUES
    ('schema_contract', 'taihu_a23'),
    ('study_area',      'Taihu Lake'),
    ('timezone',        'Asia/Shanghai'),
    ('crs',             'EPSG:4326'),
    ('data_freeze_version', '2026.08.19-v1');

-- ============================================================
-- 2.1.3 variable_dictionary — 变量字典
-- ============================================================
CREATE TABLE IF NOT EXISTS variable_dictionary (
    variable_code     TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    canonical_unit    TEXT NOT NULL,
    physical_min      REAL,
    physical_max      REAL,
    data_level        TEXT NOT NULL CHECK (data_level IN ('A','B','C','D')),
    category          TEXT NOT NULL CHECK (category IN (
                        'cyanobacteria','water_quality','meteorology',
                        'hydrology','remote_sensing','static','derived')),
    missing_policy    TEXT DEFAULT 'optional',
    description       TEXT,
    future_real_mapping TEXT  -- 未来真实数据接入时的字段映射说明
);

-- ============================================================
-- 2.1.4 unit_conversion_registry — 单位转换规则
-- ============================================================
CREATE TABLE IF NOT EXISTS unit_conversion_registry (
    from_unit     TEXT NOT NULL,
    to_unit       TEXT NOT NULL,
    multiplier    REAL NOT NULL,
    context_rule  TEXT,  -- e.g. 'precipitation_daily_accumulation'
    PRIMARY KEY (from_unit, to_unit, context_rule)
);
```

### 2.2 清洗观测层（8 张表）

```sql
-- ============================================================
-- 2.2.1 source_dataset — 数据源登记
-- ============================================================
CREATE TABLE IF NOT EXISTS source_dataset (
    source_id           TEXT PRIMARY KEY,
    source_name         TEXT NOT NULL,
    source_type         TEXT NOT NULL CHECK (source_type IN (
                            'observed','remote_sensing','forecast',
                            'experimental','simulated','static')),
    data_mode           TEXT NOT NULL CHECK (data_mode IN (
                            'observed','forecast','experimental','simulated')),
    provider_name       TEXT,
    license_tag         TEXT,
    redistribution_allowed INTEGER DEFAULT 0,
    commercial_use      INTEGER DEFAULT 0,
    temporal_coverage   TEXT,  -- e.g. '2005-01 to 2025-12'
    spatial_coverage    TEXT,
    granularity         TEXT,  -- hourly/daily/decadal/monthly
    total_records       INTEGER,
    last_ingested_at    TEXT,
    status              TEXT NOT NULL CHECK (status IN (
                            'active','deprecated','blocked_auth','pending')),
    blocker_code        TEXT,  -- e.g. 'MISSING_C3S_SEASONAL_HINDCAST'
    notes               TEXT
);

-- ============================================================
-- 2.2.2 ingest_batch — 入库批次
-- ============================================================
CREATE TABLE IF NOT EXISTS ingest_batch (
    batch_id            TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL REFERENCES source_dataset(source_id),
    status              TEXT NOT NULL CHECK (status IN (
                            'received','validating','accepted',
                            'rejected','published','superseded')),
    sha256              TEXT,
    manifest_path       TEXT,
    raw_file_count      INTEGER,
    total_rows_read     INTEGER,
    total_rows_accepted INTEGER,
    total_rows_rejected INTEGER,
    received_at_utc     TEXT NOT NULL,
    published_at_utc    TEXT,
    validation_report   TEXT,  -- JSON
    notes               TEXT
);

-- ============================================================
-- 2.2.3 water_quality_cleaned — 水质清洗数据 (6,811 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS water_quality_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id      TEXT NOT NULL,
    station_name    TEXT,
    observed_at     TEXT NOT NULL,  -- ISO 8601 Asia/Shanghai
    date            TEXT NOT NULL,
    month           TEXT NOT NULL,
    variable_code   TEXT NOT NULL,
    value           REAL,
    value_text      TEXT,
    unit            TEXT,
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    source_row      INTEGER,
    source_unit     TEXT,
    conversion_rule TEXT,
    value_origin    TEXT CHECK (value_origin IN (
                        'observed','remote_sensing','derived',
                        'imputed','proxy','static')),
    dataset_split   TEXT CHECK (dataset_split IN (
                        'train','validation','test')),
    -- 扩展审计字段
    observed_value  REAL,  -- 转换前原始值
    clean_value     REAL,  -- 转换后标准值
    is_imputed      INTEGER DEFAULT 0,
    imputation_method TEXT,
    longitude       REAL CHECK (longitude IS NULL OR longitude BETWEEN 119.5 AND 121.0),
    latitude        REAL CHECK (latitude IS NULL OR latitude BETWEEN 30.8 AND 31.7)
);

CREATE INDEX idx_wq_station_var ON water_quality_cleaned(station_id, variable_code);
CREATE INDEX idx_wq_observed_at ON water_quality_cleaned(observed_at);
CREATE INDEX idx_wq_split ON water_quality_cleaned(dataset_split);

-- ============================================================
-- 2.2.4 meteorology_cleaned — 气象清洗数据 (876,600 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS meteorology_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id      TEXT NOT NULL,  -- e.g. NASA_POWER_120.300_31.200
    station_name    TEXT,
    observed_at     TEXT NOT NULL,
    date            TEXT NOT NULL,
    month           TEXT NOT NULL,
    variable_code   TEXT NOT NULL,  -- air_temperature/wind_speed/precipitation/...
    value           REAL,
    value_text      TEXT,
    unit            TEXT,
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    source_row      INTEGER,
    source_unit     TEXT,
    conversion_rule TEXT,
    value_origin    TEXT CHECK (value_origin IN (
                        'observed','remote_sensing','derived',
                        'imputed','proxy','static')),
    longitude       REAL,
    latitude        REAL,
    is_imputed      INTEGER DEFAULT 0,
    acquisition_date TEXT
);

CREATE INDEX idx_met_station_var ON meteorology_cleaned(station_id, variable_code);
CREATE INDEX idx_met_observed_at ON meteorology_cleaned(observed_at);

-- ============================================================
-- 2.2.5 hydrology_cleaned — 水文清洗数据 (6,162 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS hydrology_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id      TEXT NOT NULL,
    station_name    TEXT,
    observed_at     TEXT NOT NULL,
    date            TEXT NOT NULL,
    month           TEXT NOT NULL,
    variable_code   TEXT NOT NULL,  -- water_level/discharge/velocity/...
    value           REAL,
    value_text      TEXT,
    unit            TEXT,
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    source_row      INTEGER,
    source_unit     TEXT,
    conversion_rule TEXT,
    value_origin    TEXT CHECK (value_origin IN (
                        'observed','remote_sensing','derived',
                        'imputed','proxy','static')),
    longitude       REAL,
    latitude        REAL,
    acquisition_date TEXT
);

CREATE INDEX idx_hydro_station_var ON hydrology_cleaned(station_id, variable_code);

-- ============================================================
-- 2.2.6 field_samples_cleaned — 野外采样数据 (41 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS field_samples_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id       TEXT,
    station_id      TEXT,
    station_name    TEXT,
    observed_at     TEXT,
    date            TEXT,
    month           TEXT,
    longitude       REAL,
    latitude        REAL,
    -- 实测指标
    chla_ug_l       REAL,  -- 叶绿素a (μg/L)
    chla_mg_l       REAL,
    tsm_mg_l        REAL,  -- 总悬浮物
    sdd_cm          REAL,  -- 透明度 (cm)
    sdd_m           REAL,
    water_temp_c    REAL,
    -- 光谱反射率
    rrs_490         REAL,
    rrs_560         REAL,
    rrs_665         REAL,
    rrs_705         REAL,
    rrs_842         REAL,
    -- 质量
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    source_row      INTEGER,
    acquisition_date TEXT
);

-- ============================================================
-- 2.2.7 static_features_cleaned — 静态特征 (1,386 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS static_features_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,  -- lake/basin/station
    entity_id       TEXT NOT NULL,
    feature_name    TEXT NOT NULL,  -- e.g. lake_area_km2, elevation_mean_m
    value           REAL,
    unit            TEXT,
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    acquisition_date TEXT
);

CREATE INDEX idx_static_entity ON static_features_cleaned(entity_type, entity_id);

-- ============================================================
-- 2.2.8 all_data_long — 统一长表 (891,825 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS all_data_long (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT,
    station_id      TEXT,
    station_name    TEXT,
    scene_id        TEXT,
    observed_at     TEXT NOT NULL,
    date            TEXT,
    month           TEXT,
    variable_code   TEXT NOT NULL,
    category        TEXT CHECK (category IN (
                        'water_quality','meteorology','hydrology',
                        'remote_sensing','static','derived')),
    clean_value     REAL,
    observed_value  REAL,
    unit            TEXT,
    value_origin    TEXT,
    quality_flag    TEXT,
    quality_note    TEXT,
    source_name     TEXT,
    source_file     TEXT,
    is_imputed      INTEGER DEFAULT 0,
    longitude       REAL,
    latitude        REAL,
    dataset_split   TEXT
);

CREATE INDEX idx_all_station_var ON all_data_long(station_id, variable_code);
CREATE INDEX idx_all_observed_at ON all_data_long(observed_at);
CREATE INDEX idx_all_category ON all_data_long(category);
```

### 2.3 遥感资产层（3 张表）

```sql
-- ============================================================
-- 2.3.1 remote_sensing_inventory — 遥感文件索引 (880 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS remote_sensing_inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT,
    month           TEXT,
    product         TEXT NOT NULL,  -- sentinel2_cdse_monthly_30m / clms_lwq_300m / ...
    variable        TEXT NOT NULL,
    band            TEXT,
    file_path       TEXT NOT NULL,
    crs             TEXT,
    resolution_m    REAL,
    width           INTEGER,
    height          INTEGER,
    valid_pixel_ratio REAL CHECK (valid_pixel_ratio IS NULL OR valid_pixel_ratio BETWEEN 0 AND 1),
    cloud_ratio     REAL CHECK (cloud_ratio IS NULL OR cloud_ratio BETWEEN 0 AND 1),
    quality_flag    TEXT DEFAULT 'Q00',
    notes           TEXT
);

CREATE INDEX idx_rs_product ON remote_sensing_inventory(product, variable);

-- ============================================================
-- 2.3.2 remote_sensing_monthly_cleaned — 遥感月统计 (712 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS remote_sensing_monthly_cleaned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    month           TEXT NOT NULL,
    product         TEXT NOT NULL,
    granularity     TEXT,
    variable        TEXT NOT NULL,
    mean            REAL,
    median          REAL,
    std             REAL,
    min             REAL,
    max             REAL,
    coverage_frac   REAL,
    cloud_ratio     REAL,
    n_files         INTEGER,
    quality_flag    TEXT DEFAULT 'Q00',
    quality_note    TEXT
);

-- ============================================================
-- 2.3.3 raster_asset — 栅格资产元数据（规划表，后端文档要求）
-- ============================================================
CREATE TABLE IF NOT EXISTS raster_asset (
    asset_id            TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL REFERENCES source_dataset(source_id),
    scene_id            TEXT,
    product             TEXT NOT NULL,
    band                TEXT,
    file_path           TEXT NOT NULL,
    crs                 TEXT NOT NULL DEFAULT 'EPSG:4326',
    resolution_m        REAL,
    width               INTEGER,
    height              INTEGER,
    coverage_fraction   REAL CHECK (coverage_fraction BETWEEN 0 AND 1),
    valid_pixel_fraction REAL CHECK (valid_pixel_fraction BETWEEN 0 AND 1),
    cloud_ratio         REAL,
    sha256              TEXT,
    operational_use     INTEGER DEFAULT 0,  -- 0=实验性, 1=业务可用
    calibrated_low_generalization INTEGER DEFAULT 0,
    start_time_utc      TEXT,
    end_time_utc        TEXT,
    ingested_at_utc     TEXT NOT NULL,
    quality_flag        TEXT DEFAULT 'Q00',
    notes               TEXT
);
```

### 2.4 重采样与时空对齐层（4+3 张表）

```sql
-- ============================================================
-- 2.4.1 resampled_observations — 重采样观测 (128,224 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS resampled_observations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           TEXT NOT NULL,
    station_id          TEXT,
    scene_id            TEXT,
    observed_at         TEXT,  -- ISO 8601
    time_bucket         TEXT NOT NULL,
    forecast_reference_time TEXT,
    valid_time          TEXT,
    lead_hours          REAL,
    variable_code       TEXT NOT NULL,
    clean_value         REAL,
    observed_value      REAL,
    unit                TEXT,
    source_unit         TEXT,
    frequency           TEXT NOT NULL CHECK (frequency IN (
                            'hourly','daily','decadal','monthly','native')),
    source_granularity  TEXT NOT NULL,
    record_role         TEXT,  -- target/feature
    aggregation_method  TEXT CHECK (aggregation_method IN (
                            'sum','circular_mean','median','mean','none','none_missing_bucket')),
    n_obs               INTEGER NOT NULL DEFAULT 0,
    aggregation_coverage REAL CHECK (aggregation_coverage IS NULL OR aggregation_coverage BETWEEN 0 AND 1),
    value_origin        TEXT,
    is_imputed          INTEGER DEFAULT 0,
    observed_flag       INTEGER DEFAULT 0,
    imputation_flag     INTEGER DEFAULT 0,
    resample_status     TEXT CHECK (resample_status IN (
                            'aggregated','native_frequency',
                            'no_upsampling','missing_bucket')),
    quality_flags       TEXT,  -- JSON array
    source_file         TEXT
);

CREATE INDEX idx_resample_bucket ON resampled_observations(time_bucket, variable_code);
CREATE INDEX idx_resample_source ON resampled_observations(source_id, station_id);

-- ============================================================
-- 2.4.2 resample_gaps — 重采样间隙记录
-- ============================================================
CREATE TABLE IF NOT EXISTS resample_gaps (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id           TEXT NOT NULL,
    station_id          TEXT,
    scene_id            TEXT,
    time_bucket         TEXT NOT NULL,
    variable_code       TEXT NOT NULL,
    frequency           TEXT NOT NULL,
    missing_flag        INTEGER DEFAULT 1,
    quality_flags       TEXT,  -- JSON: ["Q01","Q22"]
    n_obs               INTEGER DEFAULT 0,
    source_row          TEXT   -- "missing_bucket:<bucket>"
);

-- ============================================================
-- 2.4.3 temporal_alignments — 时间对齐关系 (272 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS temporal_alignments (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id               TEXT,
    prediction_start        TEXT,
    spatial_id              TEXT,
    horizon                 TEXT,
    target_date             TEXT,
    target_gap_days         INTEGER,
    target_variable         TEXT,
    target_value            REAL,
    target_source_id        TEXT,
    target_sample_id        TEXT,
    -- 对齐目标
    target_source_id_full   TEXT,
    target_station_id       TEXT,
    target_scene_id         TEXT,
    target_variable_code    TEXT,
    target_time_bucket      TEXT,
    target_clean_value      REAL,
    -- 对齐特征
    feature_source_id       TEXT,
    feature_station_id      TEXT,
    feature_scene_id        TEXT,
    feature_variable_code   TEXT,
    feature_time_bucket     TEXT,
    feature_clean_value     REAL,
    -- 对齐质量
    time_gap_hours          REAL,
    time_gap_signed_hours   REAL,
    time_window_hours       REAL,
    time_match_class        TEXT CHECK (time_match_class IN (
                                'ideal_3h','regular_24h','unmatched')),
    matching_strategy       TEXT DEFAULT 'nearest',
    space_gap_m             REAL,
    target_category         TEXT,
    feature_category        TEXT,
    spatial_status          TEXT CHECK (spatial_status IN (
                                'same_station','coordinate_distance',
                                'not_available','outside_radius')),
    match_status            TEXT CHECK (match_status IN (
                                'matched_temporal_spatial','matched_temporal_only',
                                'unmatched','future_blocked')),
    alignment_reason        TEXT,
    quality_flags           TEXT,  -- JSON
    feature_precedes_target INTEGER DEFAULT 0,
    alignment_status        TEXT
);

CREATE INDEX idx_align_target ON temporal_alignments(target_source_id, target_variable_code);

-- ============================================================
-- 2.4.4 station_buffer_matches — 站点缓冲区空间匹配
-- ============================================================
CREATE TABLE IF NOT EXISTS station_buffer_matches (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    station_source_id       TEXT,
    station_id              TEXT,
    station_variable_code   TEXT,
    station_time_bucket     TEXT,
    station_clean_value     REAL,
    station_longitude       REAL,
    station_latitude        REAL,
    remote_source_id        TEXT,
    remote_scene_id         TEXT,
    remote_variable_code    TEXT,
    remote_time_bucket      TEXT,
    remote_clean_value      REAL,
    remote_longitude        REAL,
    remote_latitude         REAL,
    distance_m              REAL,
    buffer_pixels           INTEGER,
    buffer_radius_m         REAL,
    within_1px              INTEGER,
    within_2px              INTEGER,
    within_3px              INTEGER,
    spatial_match_status    TEXT CHECK (spatial_match_status IN (
                                'matched','no_remote_within_3px')),
    alignment_reason        TEXT,
    quality_flags           TEXT
);

-- ============================================================
-- 2.4.5 grid_300m_observations — 300m 网格观测
-- ============================================================
CREATE TABLE IF NOT EXISTS grid_300m_observations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    time_bucket             TEXT NOT NULL,
    variable_code           TEXT NOT NULL,
    source_id               TEXT,
    grid_id                 TEXT NOT NULL,  -- g{x}_{y}
    grid_x                  INTEGER,
    grid_y                  INTEGER,
    grid_center_longitude   REAL,
    grid_center_latitude    REAL,
    grid_size_m             REAL DEFAULT 300.0,
    n_pixels                INTEGER,
    valid_pixel_count       INTEGER,
    valid_fraction          REAL CHECK (valid_fraction BETWEEN 0 AND 1),
    value_mean              REAL,
    source_pixel_resolution_m REAL,
    source_pixel_resolutions_m TEXT,  -- JSON list
    estimated_pixel_area_km2 REAL,
    in_lake                 INTEGER,  -- 0/1/NULL
    quality_flags           TEXT
);

CREATE INDEX idx_grid_time_var ON grid_300m_observations(time_bucket, variable_code);

-- ============================================================
-- 2.4.6 lake_area_stats — 湖区面积统计
-- ============================================================
CREATE TABLE IF NOT EXISTS lake_area_stats (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    time_bucket         TEXT NOT NULL,
    variable_code       TEXT NOT NULL,
    source_id           TEXT,
    grid_size_m         REAL,
    grid_cells_total    INTEGER,
    grid_cells_in_lake  INTEGER,
    valid_grid_cells    INTEGER,
    valid_fraction      REAL,
    valid_pixel_area_km2 REAL,
    lake_area_km2       REAL,
    area_status         TEXT CHECK (area_status IN (
                            'boundary_unavailable','boundary_loaded')),
    boundary_source     TEXT
);

-- ============================================================
-- 2.4.7 c3s_seasonal_cleaned — C3S 季节性气候数据 (127,740 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS c3s_seasonal_cleaned (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id               TEXT NOT NULL,
    model_name              TEXT,  -- e.g. 'ECMWF'
    model_variant           TEXT,
    dataset_kind            TEXT,  -- forecast/hindcast/seasonal
    forecast_reference_time TEXT,
    valid_time              TEXT,
    lead_hours              REAL,
    lead_month              INTEGER,
    ensemble_member         INTEGER,
    variable_code           TEXT NOT NULL,
    source_parameter        TEXT,
    value                   REAL,
    source_value            REAL,
    unit                    TEXT,
    source_unit             TEXT,
    conversion_rule         TEXT,
    bbox_west               REAL,
    bbox_south              REAL,
    bbox_east               REAL,
    bbox_north              REAL,
    raw_path                TEXT,
    value_origin            TEXT,
    bias_correction_status  TEXT,
    is_imputed              INTEGER DEFAULT 0,
    source_file             TEXT,
    quality_flag            TEXT DEFAULT 'Q00'
);

CREATE INDEX idx_c3s_valid_time ON c3s_seasonal_cleaned(valid_time, variable_code);
```

### 2.5 特征工程层（10 张表）

```sql
-- ============================================================
-- 2.5.1 feature_dataset — 特征宽表 (914 行月度 / 70 行最新)
-- ============================================================
-- 说明：此表为动态宽表，列数随变量数增长。
-- 核心固定列如下，驱动变量列按 feature_<variable_code> 模式生成。
CREATE TABLE IF NOT EXISTS feature_dataset (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 样本标识
    sample_id               TEXT UNIQUE,
    station_id              TEXT,
    month                   TEXT,
    station_type            TEXT,
    -- 目标变量
    target_clean_value      REAL,
    target_variable_code    TEXT,
    target_source_id        TEXT,
    target_time_bucket      TEXT,
    target_category         TEXT,
    target_feature_row_key  TEXT,
    -- 特征计数
    feature_observed_count  INTEGER,
    feature_missing_count   INTEGER,
    future_blocked_count    INTEGER,
    -- 水质特征 (wq_*)
    wq_codmn                REAL,
    wq_do                   REAL,
    wq_nh4_n                REAL,
    wq_no2_n                REAL,
    wq_no3_n                REAL,
    wq_ph                   REAL,
    wq_phyto_biomass        REAL,
    wq_po4_p                REAL,
    wq_tn                   REAL,
    wq_tp                   REAL,
    wq_chla                 REAL,
    n_wq_obs                INTEGER,
    -- 气象特征 (met_*)
    met_air_temperature_c   REAL,
    met_precipitation_mm    REAL,
    met_wind_speed_ms       REAL,
    met_wind_direction_deg  REAL,
    met_shortwave_radiation_wm2 REAL,
    -- MEE 分类特征
    mee_tn_class            TEXT,
    mee_trophic_state       TEXT,
    mee_trophic_state_zones TEXT,
    mee_water_quality_category TEXT,
    mee_zone_status         TEXT,
    mee_monitoring_point_count INTEGER,
    -- 水文特征 (hydro_*)
    hydro_water_level_m     REAL,
    hydro_water_level_std   REAL,
    hydro_water_level_n_days INTEGER,
    -- 遥感特征 (rs_*)
    rs_clms_chla_mean       REAL,
    rs_clms_chla_uncertainty REAL,
    rs_clms_fcb_prob        REAL,
    rs_sentinel2_B03        REAL,
    rs_sentinel2_B04        REAL,
    rs_sentinel2_B05        REAL,
    rs_sentinel2_B08        REAL,
    rs_sentinel2_B11        REAL,
    rs_sentinel2_FAI        REAL,
    rs_sentinel2_MCI        REAL,
    rs_sentinel2_NDCI       REAL,
    rs_sentinel2_NDWI       REAL,
    rs_sentinel2_chla_experimental REAL,
    rs_month_low_quality    INTEGER,
    -- 静态特征
    static_station_inside_lake INTEGER,
    static_station_latitude REAL,
    static_station_longitude REAL,
    static_lake_area_km2    REAL,
    static_lake_elevation_mean_m REAL,
    static_dem_valid_frac   REAL,
    -- 标签
    target_chla             REAL,
    target_chla_source      TEXT,
    target_tp               REAL,
    target_tp_source        TEXT,
    target_tn               REAL,
    target_tn_source        TEXT,
    target_do               REAL,
    target_do_source        TEXT,
    target_bloom            INTEGER,
    target_bloom_source     TEXT,
    -- 数据集划分
    dataset_split           TEXT CHECK (dataset_split IN (
                                'train','validation','test')),
    -- 质量
    leakage_check           TEXT CHECK (leakage_check IN (
                                'passed','future_values_blocked')),
    quality_flags           TEXT,
    station_name            TEXT,
    longitude               REAL,
    latitude                REAL
);

CREATE INDEX idx_feature_station ON feature_dataset(station_id, month);
CREATE INDEX idx_feature_split ON feature_dataset(dataset_split);

-- ============================================================
-- 2.5.2 feature_quality_summary — 特征质量摘要
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_quality_summary (
    feature_name        TEXT PRIMARY KEY,
    observed_count      INTEGER,
    missing_count       INTEGER,
    future_blocked_count INTEGER,
    total_count         INTEGER,
    missing_rate        REAL,
    basis               TEXT
);

-- ============================================================
-- 2.5.3 forecast_label_dataset — 预测标签 (70 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_label_dataset (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id                   TEXT UNIQUE,
    prediction_start            TEXT,
    spatial_id                  TEXT,
    label_type                  TEXT,
    -- 1-3 天标签
    h1_3d_status                TEXT CHECK (h1_3d_status IN (
                                    'accepted','no_future_observation',
                                    'no_observation_in_window',
                                    'future_target_invalid','current_time_invalid')),
    h1_3d_target_date           TEXT,
    h1_3d_target_bloom_proxy    REAL,
    h1_3d_target_chla_ug_l      REAL,
    -- 7-15 天标签
    h7_15d_status               TEXT,
    h7_15d_target_date          TEXT,
    h7_15d_target_bloom_proxy   REAL,
    h7_15d_target_chla_ug_l     REAL,
    h7_15d_gap_days             REAL,
    -- 30-90 天标签
    h30_90d_status              TEXT,
    h30_90d_target_date         TEXT,
    h30_90d_target_bloom_proxy  REAL,
    h30_90d_target_chla_ug_l    REAL,
    h30_90d_gap_days            REAL
);

-- ============================================================
-- 2.5.4 forecast_label_summary — 标签可用性汇总
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_label_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    target_variable     TEXT,
    horizon             TEXT NOT NULL,  -- horizon_1_3d / horizon_7_15d / horizon_30_90d
    lower_days          REAL,
    upper_days          REAL,
    input_rows          INTEGER,
    accepted_rows       INTEGER,
    availability_rate   REAL,
    mean_gap_days       REAL,
    min_gap_days        REAL,
    max_gap_days        REAL,
    status_counts       TEXT,  -- JSON
    split_boundary_count INTEGER,
    overall_status      TEXT CHECK (overall_status IN ('ready','blocked_no_labels'))
);

-- ============================================================
-- 2.5.5 daily_direct_features — 日尺度直接特征
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_direct_features (
    feature_date            TEXT PRIMARY KEY,
    feature_reference_time  TEXT,
    spatial_grain           TEXT DEFAULT 'taihu_lake',
    feature_grain           TEXT DEFAULT 'lake_day'
    -- 动态列: direct_<variable>, direct_<variable>_observed_count, ...
    -- 动态列: category_<cat>_available, category_<cat>_feature_count, category_<cat>_sources
    -- 动态列: static_<column> (加权平均)
);

-- ============================================================
-- 2.5.6 daily_lag_rolling_features — 日尺度滞后/滚动特征
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_lag_rolling_features (
    feature_date            TEXT PRIMARY KEY,
    feature_reference_time  TEXT
    -- 继承 daily_direct_features 全部列，加上：
    -- 对每个 direct_<var> 列 c 和窗口 d ∈ {1,3,7,14,30,90}：
    --   c_lag_{d}d, c_rolling_mean_{d}d, c_rolling_max_{d}d,
    --   c_rolling_min_{d}d, c_rolling_std_{d}d, c_rolling_slope_{d}d,
    --   c_rolling_anomaly_{d}d, c_rolling_n_{d}d
);

-- ============================================================
-- 2.5.7 daily_mechanistic_features — 日尺度机理特征
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_mechanistic_features (
    feature_date                        TEXT PRIMARY KEY,
    feature_reference_time              TEXT,
    -- 机理模型参数
    mechanism_temperature_basis         TEXT CHECK (mechanism_temperature_basis IN (
                                            'water_temperature',
                                            'air_temperature_proxy',
                                            'unavailable')),
    mechanism_temperature_response_q10  REAL,
    mechanism_n_limitation_monod        REAL,
    mechanism_p_limitation_monod        REAL,
    mechanism_np_combined_limitation    REAL,
    mechanism_tn_tp_mass_ratio          REAL,
    mechanism_nutrient_basis_available  INTEGER DEFAULT 0,
    mechanism_light_limitation          REAL,
    mechanism_low_wind_indicator        REAL,
    mechanism_low_wind_3d_indicator     REAL,
    mechanism_antecedent_rainfall_3d    REAL,
    mechanism_antecedent_rainfall_7d    REAL,
    mechanism_water_level_change_1d     REAL,
    mechanism_hydrology_available       INTEGER DEFAULT 0,
    mechanism_onshore_wind_component    REAL,
    mechanism_onshore_wind_available    INTEGER DEFAULT 0,
    -- 物候
    mechanism_phenology_sin             REAL,
    mechanism_phenology_cos             REAL,
    -- 参数版本
    mechanism_parameter_version         TEXT DEFAULT 'taihu_mechanism_defaults_v1'
);

-- ============================================================
-- 2.5.8 daily_reliability_features — 日尺度可靠性特征
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_reliability_features (
    feature_date                            TEXT PRIMARY KEY,
    feature_reference_time                  TEXT,
    reliability_observed_input_count        INTEGER,
    reliability_available_direct_fraction   REAL,
    reliability_remote_valid_pixel_fraction REAL,
    reliability_imputed_fraction            REAL,
    reliability_calibrated_prediction_uncertainty REAL,
    reliability_missing_metadata_flags      TEXT
    -- 动态列: reliability_<variable>_age_days, reliability_<variable>_uncertainty_7d
    -- 动态列: reliability_<category>_available, reliability_<category>_source_count,
    --         reliability_<category>_proxy_flag
);

-- ============================================================
-- 2.5.9 direct_feature_lineage — 直接特征溯源
-- ============================================================
CREATE TABLE IF NOT EXISTS direct_feature_lineage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_date        TEXT NOT NULL,
    feature_name        TEXT NOT NULL,
    category            TEXT,
    availability        TEXT CHECK (availability IN ('available','unavailable')),
    source_ids          TEXT,  -- JSON
    source_files        TEXT,  -- JSON
    source_times        TEXT,  -- JSON
    source_rows         INTEGER,
    aggregation         TEXT,
    value_origin_counts TEXT,  -- JSON
    quality_flags       TEXT,  -- JSON
    reason              TEXT
);

CREATE INDEX idx_lineage_date ON direct_feature_lineage(feature_date, feature_name);

-- ============================================================
-- 2.5.10 model_dataset_monthly — 月度 ML 宽表 (914 行)
-- ============================================================
-- 与 feature_dataset 结构基本一致，增加 C3S 集合预报特征列
-- 实际使用时可直接从 feature_dataset 查询，此表为历史兼容
```

### 2.6 质量审计层（4 张表）

```sql
-- ============================================================
-- 2.6.1 data_quality_report — 数据质量报告 (19 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS data_quality_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name    TEXT NOT NULL,
    output_file     TEXT,
    raw_count       INTEGER,
    cleaned_rows    INTEGER,
    duplicates_removed INTEGER,
    missing_rate    REAL,
    out_of_range    INTEGER,
    time_min        TEXT,
    time_max        TEXT,
    unit_conflicts  INTEGER,
    availability    TEXT,
    status          TEXT,
    notes           TEXT
);

-- ============================================================
-- 2.6.2 imputation_validation — 插补验证 (18 行)
-- ============================================================
CREATE TABLE IF NOT EXISTS imputation_validation (
    variable_code           TEXT NOT NULL,
    mask_rate               REAL,
    method                  TEXT,
    status                  TEXT,
    masked_count            INTEGER,
    imputed_count           INTEGER,
    blocked_count           INTEGER,
    coverage                REAL,
    mae                     REAL,
    rmse                    REAL,
    series_count            INTEGER,
    complete_series_count   INTEGER,
    complete_row_count      INTEGER,
    seed                    INTEGER,
    notes                   TEXT
);

-- ============================================================
-- 2.6.3 quality_flag_registry — 质量标志字典
-- ============================================================
CREATE TABLE IF NOT EXISTS quality_flag_registry (
    flag_code       TEXT PRIMARY KEY,
    flag_name       TEXT NOT NULL,
    description     TEXT,
    stage           TEXT NOT NULL CHECK (stage IN (
                        'cleaning','unit','resample','alignment','leakage','feature')),
    severity        TEXT CHECK (severity IN ('info','warning','error','blocked'))
);

-- 初始化质量标志
INSERT OR IGNORE INTO quality_flag_registry (flag_code, flag_name, stage, severity) VALUES
    ('Q00', '正常',                  'cleaning',  'info'),
    ('Q01', '时间异常',              'cleaning',  'warning'),
    ('Q02', '坐标异常',              'cleaning',  'warning'),
    ('Q03', '缺失值',                'cleaning',  'warning'),
    ('Q04', '非数值',                'cleaning',  'error'),
    ('Q05', '超出物理范围',          'cleaning',  'error'),
    ('Q06', '单位冲突',              'unit',      'warning'),
    ('Q07', '重复记录',              'cleaning',  'warning'),
    ('Q09', '未检出',                'cleaning',  'info'),
    ('Q10', '遥感低质量/低覆盖',     'cleaning',  'warning'),
    ('Q11', '派生聚合',              'cleaning',  'info'),
    ('Q12', '站点缺少坐标',          'cleaning',  'warning'),
    ('Q13', '年度尺度',              'cleaning',  'info'),
    ('Q21', '单位转换',              'unit',      'info'),
    ('Q22', '进入规范时间桶',        'resample',  'info'),
    ('Q23', '空间信息不足/未匹配',   'alignment', 'warning'),
    ('Q24', '未来值泄漏阻断',        'leakage',   'blocked');

-- ============================================================
-- 2.6.4 clms_lwq_10daily_cleaned — CLMS 湖水质 10 日合成
-- ============================================================
CREATE TABLE IF NOT EXISTS clms_lwq_10daily_cleaned (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id                   TEXT,
    date                        TEXT,
    month                       TEXT,
    spatial_id                  TEXT,
    product_version             TEXT,
    source_id                   TEXT,
    source_file                 TEXT,
    granularity                 TEXT,
    coverage_fraction           REAL,
    valid_pixel_count           INTEGER,
    qflag_valid_fraction        REAL,
    fcb_bloom_pixel_fraction_p50 REAL,
    target_bloom_proxy          REAL,
    label_status                TEXT,
    label_type                  TEXT,
    quality_flag                TEXT DEFAULT 'Q00',
    -- Chl-a 统计
    chla_ug_l_mean              REAL,
    chla_ug_l_median            REAL,
    chla_ug_l_std               REAL,
    chla_ug_l_min               REAL,
    chla_ug_l_max               REAL,
    chla_uncertainty_mean       REAL,
    chla_uncertainty_median      REAL,
    chla_uncertainty_std        REAL,
    chla_uncertainty_min        REAL,
    chla_uncertainty_max        REAL,
    -- 浮游藻华概率
    fcb_prob_mean               REAL,
    fcb_prob_median             REAL,
    fcb_prob_std                REAL,
    fcb_prob_min                REAL,
    fcb_prob_max                REAL
);
```

---

## 3. business.db — 业务层

### 3.1 系统配置（3 张表）

```sql
-- ============================================================
-- 3.1.1 system_capabilities — 系统能力声明
-- ============================================================
CREATE TABLE IF NOT EXISTS system_capabilities (
    capability_id       TEXT PRIMARY KEY,
    capability_name     TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN (
                            'available','dataset_ready_model_pending',
                            'blocked_auth','experimental_not_operational',
                            'not_enabled','sample_interface_only')),
    description         TEXT,
    blocker_code        TEXT,
    updated_at_utc      TEXT NOT NULL
);

-- 初始化能力声明
INSERT OR IGNORE INTO system_capabilities VALUES
    ('historical_observation',       '历史观测',          'dataset_ready_model_pending', '清洗数据已就绪，待接入API', NULL, ''),
    ('short_term_forecast_1_3d',     '短期预测 1-3 天',   'dataset_ready_model_pending', '标签数据部分就绪', NULL, ''),
    ('medium_term_forecast_7_15d',   '中期预测 7-15 天',  'dataset_ready_model_pending', '26/70 标签可用', NULL, ''),
    ('long_term_forecast_30_90d',    '长期预测 30-90 天', 'blocked_auth', 'C3S 季节性后报数据已下载，正式预测待授权', 'MISSING_C3S_SEASONAL_HINDCAST', ''),
    ('satellite_chlorophyll',        '卫星叶绿素a',       'experimental_not_operational', 'R²=-0.870，仅实验用途', NULL, ''),
    ('real_time_warning_dispatch',   '真实预警发布',       'not_enabled', '未接入短信/邮件', NULL, ''),
    ('demo_warning_dispatch',        '演示预警发布',       'available', '模拟发送，不实际通知', NULL, '');

-- ============================================================
-- 3.1.2 feature_dataset_version — 特征数据集版本
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_dataset_version (
    version_id          TEXT PRIMARY KEY,
    source_snapshot     TEXT NOT NULL,
    created_at_utc      TEXT NOT NULL,
    row_count           INTEGER NOT NULL,
    feature_count       INTEGER NOT NULL,
    leakage_violations  INTEGER DEFAULT 0,
    trainable           INTEGER DEFAULT 0,
    blocker_code        TEXT,
    sha256              TEXT,
    notes               TEXT
);

-- ============================================================
-- 3.1.3 pipeline_run — 管道运行记录
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id              TEXT PRIMARY KEY,
    pipeline_name       TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN (
                            'running','succeeded','failed','cancelled')),
    started_at_utc      TEXT NOT NULL,
    finished_at_utc     TEXT,
    rows_read           INTEGER,
    rows_written        INTEGER,
    rows_rejected       INTEGER,
    dataset_version_id  TEXT REFERENCES feature_dataset_version(version_id),
    config_snapshot     TEXT,  -- JSON
    log_path            TEXT
);
```

### 3.2 空间与观测（4 张表）

```sql
-- ============================================================
-- 3.2.1 spatial_entity — 空间对象（6 个演示 + 未来真实站点）
-- ============================================================
CREATE TABLE IF NOT EXISTS spatial_entity (
    entity_id           TEXT PRIMARY KEY,
    entity_name         TEXT NOT NULL,
    entity_type         TEXT NOT NULL CHECK (entity_type IN (
                            'station','buoy','intake','river_section',
                            'lake_zone','grid','basin','lake_whole',
                            'demo_zone')),
    longitude           REAL CHECK (longitude IS NULL OR longitude BETWEEN 119.5 AND 121.0),
    latitude            REAL CHECK (latitude IS NULL OR latitude BETWEEN 30.8 AND 31.7),
    geometry_wkt        TEXT,
    lake_zone           TEXT,
    depth_m             REAL CHECK (depth_m IS NULL OR depth_m BETWEEN 0 AND 100),
    data_mode           TEXT NOT NULL DEFAULT 'simulated',
    is_operational      INTEGER DEFAULT 0,
    verified_at_utc     TEXT,
    notes               TEXT
);

-- 初始化 6 个演示分区
INSERT OR IGNORE INTO spatial_entity (entity_id, entity_name, entity_type, data_mode) VALUES
    ('DEMO-NW',      '西北热点区',   'demo_zone', 'simulated'),
    ('DEMO-INLET',   '入湖河口区',   'demo_zone', 'simulated'),
    ('DEMO-SE',      '东南对照区',   'demo_zone', 'simulated'),
    ('DEMO-CENTER',  '湖心观测区',   'demo_zone', 'simulated'),
    ('DEMO-INTAKE',  '取水口关注区', 'demo_zone', 'simulated'),
    ('DEMO-SOUTH',   '南部通道区',   'demo_zone', 'simulated');

-- ============================================================
-- 3.2.2 observation — 业务观测记录
-- ============================================================
CREATE TABLE IF NOT EXISTS observation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id           TEXT NOT NULL REFERENCES spatial_entity(entity_id),
    variable_code       TEXT NOT NULL,
    observed_at         TEXT NOT NULL,  -- ISO 8601
    observed_value      REAL,
    clean_value         REAL,
    unit                TEXT NOT NULL,
    value_origin        TEXT NOT NULL CHECK (value_origin IN (
                            'observed','remote_sensing','derived',
                            'imputed','proxy','static','simulated')),
    is_imputed          INTEGER DEFAULT 0,
    imputation_method   TEXT,
    quality_flags       TEXT,  -- JSON array
    data_mode           TEXT NOT NULL CHECK (data_mode IN (
                            'observed','forecast','experimental','simulated')),
    dataset_version_id  TEXT,
    source_id           TEXT,
    created_at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX idx_obs_entity ON observation(entity_id, observed_at);
CREATE INDEX idx_obs_var ON observation(variable_code, data_mode);

-- ============================================================
-- 3.2.3 observation_quality_alert — 数据质量告警
-- ============================================================
CREATE TABLE IF NOT EXISTS observation_quality_alert (
    alert_id            TEXT PRIMARY KEY,
    entity_id           TEXT NOT NULL REFERENCES spatial_entity(entity_id),
    variable_code       TEXT,
    alert_type          TEXT NOT NULL CHECK (alert_type IN (
                            'missing_spike','range_violation',
                            'stale_data','unit_conflict',
                            'coverage_drop','consistency_failure')),
    severity            TEXT NOT NULL CHECK (severity IN (
                            'info','warning','critical')),
    detail              TEXT,
    detected_at_utc     TEXT NOT NULL,
    resolved_at_utc     TEXT,
    resolution          TEXT
);

-- ============================================================
-- 3.2.4 spatial_entity_station_mapping — 演示分区与真实站点映射
-- ============================================================
CREATE TABLE IF NOT EXISTS spatial_entity_station_mapping (
    entity_id           TEXT NOT NULL REFERENCES spatial_entity(entity_id),
    station_id          TEXT NOT NULL,  -- e.g. TAIHU_ZS, TAIHU_XK
    mapping_status      TEXT CHECK (mapping_status IN (
                            'proposed','verified','rejected')),
    verified_at_utc     TEXT,
    notes               TEXT,
    PRIMARY KEY (entity_id, station_id)
);
```

### 3.3 预测与解释（5 张表）

```sql
-- ============================================================
-- 3.3.1 model_version — 模型版本
-- ============================================================
CREATE TABLE IF NOT EXISTS model_version (
    model_id            TEXT PRIMARY KEY,
    model_name          TEXT NOT NULL,
    model_type          TEXT NOT NULL CHECK (model_type IN (
                            'mechanism','ai_lstm','ai_xgboost',
                            'fusion_residual','fusion_cascade',
                            'demo_rule')),
    version_tag         TEXT NOT NULL,
    feature_dataset_id  TEXT REFERENCES feature_dataset_version(version_id),
    effect_claim_allowed INTEGER DEFAULT 0,  -- 是否允许声称精度提升
    r2_score            REAL,
    rmse                REAL,
    mae                 REAL,
    improvement_pct     REAL,  -- 融合相对基线提升百分比
    artifact_path       TEXT,
    artifact_sha256     TEXT,
    created_at_utc      TEXT NOT NULL,
    activated_at_utc    TEXT,
    status              TEXT CHECK (status IN (
                            'training','validated','active','retired')),
    notes               TEXT
);

-- ============================================================
-- 3.3.2 prediction_run — 预测运行记录
-- ============================================================
CREATE TABLE IF NOT EXISTS prediction_run (
    prediction_run_id   TEXT PRIMARY KEY,
    model_id            TEXT NOT NULL REFERENCES model_version(model_id),
    entity_id           TEXT NOT NULL REFERENCES spatial_entity(entity_id),
    feature_dataset_id  TEXT REFERENCES feature_dataset_version(version_id),
    horizon_days        INTEGER NOT NULL CHECK (horizon_days IN (1,3,7,15,30,90)),
    target_metric       TEXT NOT NULL,  -- chlorophyll_a/algae_density/bloom_area/...
    provider_type       TEXT NOT NULL CHECK (provider_type IN (
                            'algorithm','simulation')),
    claim_boundary      TEXT NOT NULL DEFAULT 'simulation_only',
    status              TEXT NOT NULL CHECK (status IN (
                            'queued','running','succeeded','failed','cancelled')),
    started_at_utc      TEXT,
    finished_at_utc     TEXT,
    request_hash        TEXT,  -- 冻结请求参数哈希
    data_hash           TEXT,  -- 冻结数据哈希
    notes               TEXT
);

CREATE INDEX idx_pred_entity ON prediction_run(entity_id, horizon_days);

-- ============================================================
-- 3.3.3 forecast_result — 预测结果
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_result (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_run_id   TEXT NOT NULL REFERENCES prediction_run(prediction_run_id),
    forecast_at         TEXT NOT NULL,  -- 预测目标时间
    risk_probability    REAL CHECK (risk_probability IS NULL OR risk_probability BETWEEN 0 AND 1),
    risk_level          TEXT CHECK (risk_level IN (
                            'low','moderate','high','critical')),
    predicted_value     REAL,
    unit                TEXT,
    bounds_lower        REAL,
    bounds_upper        REAL,
    confidence_level    REAL DEFAULT 0.95,
    quality_gate_status TEXT CHECK (quality_gate_status IN (
                            'pass','warning','fail')),
    quality_gate_decision TEXT CHECK (quality_gate_decision IN (
                            'candidate_assessment_only','approved_for_warning',
                            'rejected_insufficient')),
    claim_boundary      TEXT NOT NULL DEFAULT 'simulation_only',
    data_mode           TEXT NOT NULL DEFAULT 'simulated'
);

CREATE INDEX idx_forecast_run ON forecast_result(prediction_run_id);

-- ============================================================
-- 3.3.4 forecast_metric — 预测精度指标
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_metric (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_run_id   TEXT NOT NULL REFERENCES prediction_run(prediction_run_id),
    metric_name         TEXT NOT NULL,  -- r2/rmse/mae/improvement_pct/...
    metric_value        REAL NOT NULL,
    test_window_start   TEXT,
    test_window_end     TEXT,
    dataset_split       TEXT,
    computed_at_utc     TEXT NOT NULL
);

-- ============================================================
-- 3.3.5 explanation_contribution — 解释贡献（SHAP/规则贡献）
-- ============================================================
CREATE TABLE IF NOT EXISTS explanation_contribution (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_run_id   TEXT NOT NULL REFERENCES prediction_run(prediction_run_id),
    forecast_result_id  INTEGER REFERENCES forecast_result(id),
    feature_name        TEXT NOT NULL,
    feature_value       REAL,
    feature_unit        TEXT,
    contribution        REAL NOT NULL,
    direction           TEXT CHECK (direction IN ('positive','negative','neutral')),
    rank_order          INTEGER,
    label               TEXT,
    provenance          TEXT CHECK (provenance IN (
                            'real_shap','demo_rule_contribution')),
    explanation_type    TEXT NOT NULL DEFAULT 'demo_rule_contribution',
    identity_check_base_value REAL,
    identity_check_output_value REAL,
    identity_check_passed INTEGER
);

CREATE INDEX idx_explain_run ON explanation_contribution(prediction_run_id);
```

### 3.4 预警闭环层（6 张表）

```sql
-- ============================================================
-- 3.4.1 warning_rule — 预警规则
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_rule (
    rule_id             TEXT PRIMARY KEY,
    rule_name           TEXT NOT NULL,
    target_metric       TEXT NOT NULL,
    threshold_operator  TEXT NOT NULL CHECK (threshold_operator IN ('>=','<=','>','<','between')),
    threshold_value     REAL NOT NULL,
    threshold_value_upper REAL,  -- for 'between'
    threshold_source    TEXT NOT NULL DEFAULT 'demo_rule_v1',
    required_quality_gate TEXT CHECK (required_quality_gate IN ('pass','warning')),
    min_confidence      REAL DEFAULT 0.60,
    persistence_runs    INTEGER DEFAULT 2,  -- 连续触发次数
    dedup_key_template  TEXT,  -- e.g. '{entity_id}_{metric}_{horizon_bucket}'
    is_active           INTEGER DEFAULT 1,
    created_at_utc      TEXT NOT NULL,
    notes               TEXT
);

-- ============================================================
-- 3.4.2 warning_event — 预警事件（状态机核心表）
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_event (
    warning_id          TEXT PRIMARY KEY,
    rule_id             TEXT NOT NULL REFERENCES warning_rule(rule_id),
    prediction_run_id   TEXT REFERENCES prediction_run(prediction_run_id),
    entity_id           TEXT NOT NULL REFERENCES spatial_entity(entity_id),
    -- 状态机: candidate → pending_review → published/rejected
    --         → acknowledged → handling → resolved → closed
    --         published → cancelled (特殊)
    status              TEXT NOT NULL CHECK (status IN (
                            'candidate','pending_review','published',
                            'rejected','acknowledged','handling',
                            'resolved','closed','cancelled')),
    status_version      INTEGER DEFAULT 1,  -- 乐观锁
    -- 预警内容
    title               TEXT NOT NULL,
    risk_level          TEXT CHECK (risk_level IN (
                            'low','moderate','high','critical')),
    risk_probability    REAL,
    affected_area_km2   REAL,
    forecast_horizon_days INTEGER,
    forecast_window_start TEXT,
    forecast_window_end   TEXT,
    -- 数据来源
    data_mode           TEXT NOT NULL DEFAULT 'simulated',
    claim_boundary      TEXT NOT NULL DEFAULT 'simulation_only',
    dataset_version_id  TEXT,
    -- 时间线
    created_at_utc      TEXT NOT NULL,
    submitted_at_utc    TEXT,
    published_at_utc    TEXT,
    acknowledged_at_utc TEXT,
    handling_at_utc     TEXT,
    resolved_at_utc     TEXT,
    closed_at_utc       TEXT,
    cancelled_at_utc    TEXT,
    -- 操作人
    created_by          TEXT,
    submitted_by        TEXT,
    published_by        TEXT,
    acknowledged_by     TEXT,
    handling_by         TEXT,
    resolved_by         TEXT,
    closed_by           TEXT,
    -- 关闭原因
    close_reason        TEXT CHECK (close_reason IN (
                            'resolved','false_positive','expired','superseded')),
    close_explanation   TEXT,
    -- 去重
    dedup_key           TEXT UNIQUE,
    notes               TEXT
);

CREATE INDEX idx_warning_status ON warning_event(status);
CREATE INDEX idx_warning_entity ON warning_event(entity_id, created_at_utc);
CREATE INDEX idx_warning_dedup ON warning_event(dedup_key);

-- ============================================================
-- 3.4.3 warning_evidence — 预警证据
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_evidence (
    evidence_id         TEXT PRIMARY KEY,
    warning_id          TEXT NOT NULL REFERENCES warning_event(warning_id),
    prediction_run_id   TEXT REFERENCES prediction_run(prediction_run_id),
    forecast_result_id  INTEGER REFERENCES forecast_result(id),
    evidence_type       TEXT NOT NULL CHECK (evidence_type IN (
                            'prediction_threshold','quality_alert',
                            'spatial_pattern','temporal_persistence',
                            'manual_annotation')),
    evidence_summary    TEXT NOT NULL,
    evidence_detail     TEXT,  -- JSON
    metric_name         TEXT,
    metric_value        REAL,
    metric_unit         TEXT,
    threshold_value     REAL,
    created_at_utc      TEXT NOT NULL
);

CREATE INDEX idx_evidence_warning ON warning_evidence(warning_id);

-- ============================================================
-- 3.4.4 warning_action_log — 预警操作日志
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_action_log (
    log_id              TEXT PRIMARY KEY,
    warning_id          TEXT NOT NULL REFERENCES warning_event(warning_id),
    action              TEXT NOT NULL CHECK (action IN (
                            'created','submitted','published','rejected',
                            'acknowledged','handling_started',
                            'plan_applied','dispatched','resolved',
                            'closed','cancelled','reopened')),
    from_status         TEXT,
    to_status           TEXT NOT NULL,
    operator_id         TEXT,
    operator_role       TEXT CHECK (operator_role IN (
                            'viewer','analyst','admin')),
    request_id          TEXT,
    detail              TEXT,  -- JSON
    created_at_utc      TEXT NOT NULL
);

CREATE INDEX idx_action_warning ON warning_action_log(warning_id, created_at_utc);

-- ============================================================
-- 3.4.5 warning_dispatch — 预警发送记录
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_dispatch (
    dispatch_id         TEXT PRIMARY KEY,
    warning_id          TEXT NOT NULL REFERENCES warning_event(warning_id),
    channel             TEXT NOT NULL CHECK (channel IN (
                            'platform_simulation','sms','email',
                            'webhook','platform')),
    recipient           TEXT,
    template_id         TEXT,
    payload             TEXT,  -- JSON: 发送内容
    simulated           INTEGER NOT NULL DEFAULT 1,
    dispatch_status     TEXT CHECK (dispatch_status IN (
                            'queued','sent','delivered','failed')),
    sent_at_utc         TEXT,
    delivered_at_utc    TEXT,
    error_message       TEXT,
    created_at_utc      TEXT NOT NULL
);

-- ============================================================
-- 3.4.6 simulation_run — 模拟预演运行
-- ============================================================
CREATE TABLE IF NOT EXISTS simulation_run (
    simulation_id       TEXT PRIMARY KEY,
    base_prediction_id  TEXT REFERENCES prediction_run(prediction_run_id),
    scenario_name       TEXT NOT NULL,
    assumptions         TEXT NOT NULL,  -- JSON: 模拟假设
    layer_type          TEXT NOT NULL DEFAULT 'simulated_scenario',
    operational_use     INTEGER DEFAULT 0,
    status              TEXT CHECK (status IN (
                            'running','completed','failed')),
    created_at_utc      TEXT NOT NULL,
    finished_at_utc     TEXT,
    notes               TEXT
);
```

### 3.5 事件与预案（4 张表）

```sql
-- ============================================================
-- 3.5.1 event — 业务事件
-- ============================================================
CREATE TABLE IF NOT EXISTS event (
    event_id            TEXT PRIMARY KEY,
    event_type          TEXT NOT NULL CHECK (event_type IN (
                            'data_ingest','data_quality','model_run',
                            'prediction','warning_created',
                            'warning_published','warning_closed',
                            'simulation','plan_activated','system')),
    title               TEXT NOT NULL,
    summary             TEXT,
    severity            TEXT CHECK (severity IN (
                            'info','warning','critical')),
    entity_id           TEXT REFERENCES spatial_entity(entity_id),
    warning_id          TEXT REFERENCES warning_event(warning_id),
    prediction_run_id   TEXT REFERENCES prediction_run(prediction_run_id),
    data_mode           TEXT NOT NULL DEFAULT 'simulated',
    occurred_at_utc     TEXT NOT NULL,
    created_at_utc      TEXT NOT NULL
);

CREATE INDEX idx_event_type ON event(event_type, occurred_at_utc);

-- ============================================================
-- 3.5.2 emergency_plan — 应急预案
-- ============================================================
CREATE TABLE IF NOT EXISTS emergency_plan (
    plan_id             TEXT PRIMARY KEY,
    plan_code           TEXT NOT NULL UNIQUE,
    plan_name           TEXT NOT NULL,
    plan_level          TEXT NOT NULL CHECK (plan_level IN (
                            'I','II','III','IV')),
    plan_type           TEXT NOT NULL CHECK (plan_type IN (
                            'intensified_monitoring',  -- 重点湖湾加密监测
                            'intake_protection',       -- 取水口联动保护
                            'post_rainfall_patrol',    -- 强降雨后河口巡查
                            'custom')),
    description         TEXT,
    trigger_conditions  TEXT,  -- JSON
    measures            TEXT,  -- JSON: [{code, title, required, default_owner_role}]
    is_active           INTEGER DEFAULT 1,
    created_at_utc      TEXT NOT NULL
);

-- 初始化 3 个演示预案
INSERT OR IGNORE INTO emergency_plan (plan_id, plan_code, plan_name, plan_level, plan_type, description) VALUES
    ('PLAN-001', 'KEY_BAY_MONITOR',  '重点湖湾加密监测',   'III', 'intensified_monitoring', '对西北热点区等重点湖湾加密监测频次，由常规月度调整为每周'),
    ('PLAN-002', 'INTAKE_PROTECT',   '取水口联动保护',     'II',  'intake_protection',       '启动取水口联动保护机制，加强水质监控，通知水厂做好应急准备'),
    ('PLAN-003', 'RAINFALL_PATROL',  '强降雨后河口巡查',   'III', 'post_rainfall_patrol',    '强降雨后 48 小时内对入湖河口开展加密巡查，关注面源污染输入');

-- ============================================================
-- 3.5.3 warning_plan_match — 预警-预案匹配
-- ============================================================
CREATE TABLE IF NOT EXISTS warning_plan_match (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    warning_id          TEXT NOT NULL REFERENCES warning_event(warning_id),
    plan_id             TEXT NOT NULL REFERENCES emergency_plan(plan_id),
    match_score         REAL CHECK (match_score BETWEEN 0 AND 1),
    match_reasons       TEXT,  -- JSON
    applied             INTEGER DEFAULT 0,
    applied_at_utc      TEXT,
    applied_by          TEXT
);

-- ============================================================
-- 3.5.4 plan_action_checklist — 预案行动清单
-- ============================================================
CREATE TABLE IF NOT EXISTS plan_action_checklist (
    action_id           TEXT PRIMARY KEY,
    warning_id          TEXT NOT NULL REFERENCES warning_event(warning_id),
    plan_id             TEXT NOT NULL REFERENCES emergency_plan(plan_id),
    measure_code        TEXT NOT NULL,
    measure_title       TEXT NOT NULL,
    required            INTEGER DEFAULT 0,
    owner_role          TEXT,
    assigned_to         TEXT,
    completed           INTEGER DEFAULT 0,
    completed_at_utc    TEXT,
    completed_by        TEXT,
    notes               TEXT
);
```

### 3.6 审计与日志（3 张表）

```sql
-- ============================================================
-- 3.6.1 audit_log — 全局审计日志
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    log_id              TEXT PRIMARY KEY,
    table_name          TEXT NOT NULL,
    record_id           TEXT NOT NULL,
    action              TEXT NOT NULL CHECK (action IN (
                            'INSERT','UPDATE','DELETE')),
    old_values          TEXT,  -- JSON
    new_values          TEXT,  -- JSON
    operator_id         TEXT,
    operator_role       TEXT,
    request_id          TEXT,
    created_at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX idx_audit_table ON audit_log(table_name, created_at_utc);

-- ============================================================
-- 3.6.2 user_role — 用户角色（最小演示身份）
-- ============================================================
CREATE TABLE IF NOT EXISTS user_role (
    user_id             TEXT PRIMARY KEY,
    username            TEXT NOT NULL UNIQUE,
    role                TEXT NOT NULL CHECK (role IN ('viewer','analyst','admin')),
    display_name        TEXT,
    is_active           INTEGER DEFAULT 1,
    created_at_utc      TEXT NOT NULL
);

-- ============================================================
-- 3.6.3 request_log — API 请求日志
-- ============================================================
CREATE TABLE IF NOT EXISTS request_log (
    request_id          TEXT PRIMARY KEY,
    method              TEXT NOT NULL,
    path                TEXT NOT NULL,
    status_code         INTEGER NOT NULL,
    data_mode           TEXT,
    response_time_ms    INTEGER,
    user_id             TEXT,
    error_code          TEXT,
    created_at_utc      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX idx_request_path ON request_log(path, created_at_utc);
```

---

## 4. 视图（可选，方便查询）

```sql
-- ============================================================
-- 4.1 演示分区观测概览
-- ============================================================
CREATE VIEW IF NOT EXISTS v_demo_zone_overview AS
SELECT
    se.entity_id,
    se.entity_name,
    se.entity_type,
    o.variable_code,
    o.clean_value,
    o.unit,
    o.value_origin,
    o.data_mode,
    o.observed_at
FROM spatial_entity se
LEFT JOIN observation o ON se.entity_id = o.entity_id
WHERE se.entity_type = 'demo_zone';

-- ============================================================
-- 4.2 预警状态机全景
-- ============================================================
CREATE VIEW IF NOT EXISTS v_warning_timeline AS
SELECT
    we.warning_id,
    we.title,
    we.status,
    we.risk_level,
    we.entity_id,
    se.entity_name,
    we.data_mode,
    we.claim_boundary,
    we.created_at_utc,
    we.published_at_utc,
    we.closed_at_utc,
    wal.action,
    wal.from_status,
    wal.to_status,
    wal.created_at_utc AS action_at
FROM warning_event we
JOIN spatial_entity se ON we.entity_id = se.entity_id
LEFT JOIN warning_action_log wal ON we.warning_id = wal.warning_id
ORDER BY we.created_at_utc DESC, wal.created_at_utc;

-- ============================================================
-- 4.3 数据能力矩阵
-- ============================================================
CREATE VIEW IF NOT EXISTS v_capability_matrix AS
SELECT
    capability_id,
    capability_name,
    status,
    description,
    blocker_code
FROM system_capabilities
ORDER BY capability_id;
```

---

## 5. 数据流关系图

```
原始数据源                    清洗层 (data_cleaning.db)              业务层 (business.db)
─────────                    ─────────────────────────              ────────────────────
                                                                    
THQBCA 水质 ──────┐                                               
NASA POWER 气象 ──┤                                               
Sentinel-2 遥感 ──┤   ┌─────────────────┐                         
C3S 季节性气候 ───┤   │ source_dataset   │                         
CLMS 湖水质 ──────┤   │ ingest_batch     │                         
NOAA GFS ─────────┤   │ variable_dict    │                         
野外采样 ─────────┤   └────────┬────────┘                         
静态特征 ─────────┘            │                                  
                               ▼                                  
                    ┌─────────────────────┐                       
                    │ water_quality_cleaned│──────┐               
                    │ meteorology_cleaned  │──────┤               
                    │ hydrology_cleaned    │──────┤               
                    │ field_samples_cleaned│──────┤               
                    │ static_features      │──────┤               
                    │ remote_sensing_*     │──────┤               
                    │ c3s_seasonal_cleaned │──────┤               
                    │ clms_lwq_10daily     │──────┤               
                    │ all_data_long        │──────┤               
                    └──────────┬──────────┘      │               
                               │                  │               
                               ▼                  │               
                    ┌─────────────────────┐      │               
                    │ resampled_observations│     │               
                    │ temporal_alignments  │      │               
                    │ grid_300m_*          │      │               
                    │ station_buffer_*     │      │               
                    └──────────┬──────────┘      │               
                               │                  │               
                               ▼                  │               
                    ┌─────────────────────┐      │               
                    │ feature_dataset      │◄─────┘               
                    │ daily_direct_features│                      
                    │ daily_lag_rolling    │                      
                    │ daily_mechanistic    │                      
                    │ daily_reliability    │                      
                    │ forecast_label_*     │                      
                    └──────────┬──────────┘                      
                               │                                  
                               ▼                                  
              ┌──────────────────────────────────┐               
              │ feature_dataset_version           │──────────┐    
              └──────────────────────────────────┘           │    
                                                             ▼    
                                              ┌────────────────────┐
                                              │ model_version       │
                                              │ prediction_run      │
                                              │ forecast_result     │
                                              │ explanation_*       │
                                              └─────────┬──────────┘
                                                        │          
                                                        ▼          
                                              ┌────────────────────┐
                                              │ warning_rule        │
                                              │ warning_event       │
                                              │ warning_evidence    │
                                              │ warning_action_log  │
                                              │ warning_dispatch    │
                                              │ emergency_plan      │
                                              │ plan_action_*       │
                                              └────────────────────┘
```

---

## 6. 质量标志完整字典

| 代码 | 名称 | 阶段 | 严重度 |
|---|---|---|---|
| Q00 | 正常 | 清洗 | info |
| Q01 | 时间异常 | 清洗 | warning |
| Q02 | 坐标异常 | 清洗 | warning |
| Q03 | 缺失值 | 清洗 | warning |
| Q04 | 非数值 | 清洗 | error |
| Q05 | 超出物理范围 | 清洗 | error |
| Q06 | 单位冲突 | 单位 | warning |
| Q07 | 重复记录 | 清洗 | warning |
| Q09 | 未检出 | 清洗 | info |
| Q10 | 遥感低质量/低覆盖 | 清洗 | warning |
| Q11 | 派生聚合 | 清洗 | info |
| Q12 | 站点缺少坐标 | 清洗 | warning |
| Q13 | 年度尺度 | 清洗 | info |
| Q21 | 单位转换 | 单位 | info |
| Q22 | 进入规范时间桶 | 重采样 | info |
| Q23 | 空间信息不足/未匹配 | 对齐 | warning |
| Q24 | 未来值泄漏阻断 | 泄漏 | blocked |

---

## 7. 枚举值速查

### data_mode（数据模式）
`observed` | `forecast` | `experimental` | `simulated`

### value_origin（值来源）
`observed` | `remote_sensing` | `derived` | `imputed` | `proxy` | `static`

### entity_type（空间对象类型）
`station` | `buoy` | `intake` | `river_section` | `lake_zone` | `grid` | `basin` | `lake_whole` | `demo_zone`

### warning status（预警状态机）
`candidate` → `pending_review` → `published` | `rejected` → `acknowledged` → `handling` → `resolved` → `closed`
特殊：`published` → `cancelled`

### capability status（能力状态）
`available` | `dataset_ready_model_pending` | `blocked_auth` | `experimental_not_operational` | `not_enabled` | `sample_interface_only`

### dataset_split（数据集划分）
`train`（≤2024）| `validation`（2025）| `test`（2026）

### horizon（预测时效）
`horizon_1_3d` | `horizon_7_15d` | `horizon_30_90d`

---

## 8. 索引汇总

清洗层关键索引已在各表 CREATE INDEX 中定义。业务层关键索引：

```sql
-- 观测查询优化
CREATE INDEX IF NOT EXISTS idx_obs_entity_time ON observation(entity_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_obs_mode ON observation(data_mode, variable_code);

-- 预警查询优化
CREATE INDEX IF NOT EXISTS idx_warning_status_time ON warning_event(status, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_warning_entity_time ON warning_event(entity_id, created_at_utc DESC);

-- 审计查询优化
CREATE INDEX IF NOT EXISTS idx_audit_table_time ON audit_log(table_name, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_request_path_time ON request_log(path, created_at_utc DESC);
```

---

## 9. 当前数据量统计

| 表 | 行数 | 来源 |
|---|---|---|
| water_quality_cleaned | 6,811 | CSV |
| meteorology_cleaned | 876,600 | CSV |
| hydrology_cleaned | 6,162 | CSV |
| field_samples_cleaned | 41 | CSV |
| static_features_cleaned | 1,386 | CSV |
| remote_sensing_inventory | 880 | CSV |
| remote_sensing_monthly_cleaned | 712 | CSV |
| all_data_long | 891,825 | CSV |
| c3s_seasonal_cleaned | 127,740 | CSV |
| clms_lwq_10daily_cleaned | ~70 | CSV |
| resampled_observations | 128,224 | Parquet |
| feature_dataset | 914 + 70 | Parquet |
| forecast_label_dataset | 70 | Parquet |
| temporal_alignments | 272 | Parquet |
| imputation_validation | 18 | SQLite |
| data_quality_report | 19 | CSV |
| **清洗层合计** | **~2,041,794** | |

---

## 10. 下一步实施路径

1. **创建 data_cleaning.db**：编写 Python 脚本，将现有 CSV/Parquet 数据导入上述表结构
2. **创建 business.db**：初始化业务层表，导入 6 个演示分区和 3 个演示预案
3. **后端接入**：将 `SimulatedProvider` 替换为从 `data_cleaning.db` 读取的 `CleanedObservationProvider`
4. **迁移管理**：使用 `schema_migrations.py` 的事务迁移机制管理表结构变更
5. **测试验证**：编写 SQL 查询验证数据完整性，与现有 278 项管道测试交叉核对

---

> 文档结束。此方案覆盖从原始数据清洗到业务预警闭环的全部 58 张表，字段定义与现有清洗数据、后端规划文档、数据字典完全对齐。
