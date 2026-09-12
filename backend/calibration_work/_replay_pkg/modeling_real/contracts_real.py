"""V0.3 真实数据特征契约、时效映射与任务规格（冻结口径）。

契约版本 v2.0：78 个真实列名字段；月度标签粒度；时效→月份偏移映射；
按时间冻结划分（train≤2021 / validation 2022-2023 / test≥2024）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# ---------- 数据版本与声明边界 ----------
DATA_VERSION_V3 = "TAIHU_CLEAN_FINAL_V1_20260831/model_dataset.parquet"
CLAIM_BOUNDARY_V3 = "real_data_monthly_station_v0_3"
PACKAGE_GENERATION = "v0_3"
DEFAULT_SEED_V3 = 20260907
HORIZONS_V3: tuple[int, ...] = (1, 3, 7, 15, 30, 60, 90)
BLOOM_THRESHOLD_UG_L = 20.0
RISK_BANDS_UG_L: dict[str, tuple[float, float]] = {
    "none": (0.0, 10.0),
    "low": (10.0, 20.0),
    "medium": (20.0, 30.0),
    "high": (30.0, 50.0),
    "severe": (50.0, float("inf")),
}
RISK_CLASSES_V3 = tuple(RISK_BANDS_UG_L)
# 门禁可评估的最小冻结测试行数（主理人裁定：测试集 <15 行标 NOT_APPLICABLE）
GATE_MIN_TEST_ROWS = 15
SPLIT_BOUNDS = {"train_max": "2021-12", "validation_max": "2023-12"}

# ---------- 第二轮代理目标口径（诚实披露） ----------
# model_dataset 的 fcb 列为 0-1 概率的 1e4 缩放（实证：长表 0-1 口径值 ×1e4 = frame 值）
FCB_PROB_SCALE_FACTOR = 10000.0
# 蓝藻水华阳性阈值：CLMS FCB 湖面月均概率 ≥0.5（与逐景像素阈值 0.5 同口径的不同聚合层级）
FCB_BLOOM_PROB_THRESHOLD = 0.5
# 目标同源特征剔除（防同月泄漏）：目标直接由这些特征列构造，训练时必须剔除当月值
TARGET_SOURCE_FEATURE_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "biomass": ("wq_phyto_biomass",),
    "density": ("wq_phyto_biomass",),
    "coverage": ("rs_clms_lwq_300m_10daily_fcb_prob",),
}


def feature_columns_for_task(label_family: str) -> tuple[str, ...]:
    """任务级特征列：契约 v2 剔除目标同源特征（滞后/滚动列不受影响，均为历史月）。"""
    excluded = set(TARGET_SOURCE_FEATURE_EXCLUSIONS.get(label_family, ()))
    return tuple(name for name in FEATURE_COLUMNS_V2 if name not in excluded)

# ---------- 特征契约 v2（78 字段，真实列名） ----------
WATER_QUALITY_V2: tuple[str, ...] = (
    "wq_codmn", "wq_do", "wq_nh4_n", "wq_no2_n", "wq_no3_n",
    "wq_ph", "wq_phyto_biomass", "wq_po4_p", "wq_tn", "wq_tp",
)
METEOROLOGY_V2: tuple[str, ...] = (
    "met_air_temperature_c", "met_precipitation_mm", "met_wind_speed_ms",
    "met_wind_direction_deg", "met_shortwave_radiation_wm2",
)
HYDROLOGY_V2: tuple[str, ...] = ("hydro_water_level_m", "hydro_water_level_std")
REMOTE_SENSING_V2: tuple[str, ...] = (
    "rs_clms_lwq_300m_10daily_chla_mean",
    "rs_clms_lwq_300m_10daily_chla_uncertainty",
    "rs_clms_lwq_300m_10daily_fcb_prob",
    "rs_sentinel2_cdse_monthly_30m_B03",
    "rs_sentinel2_cdse_monthly_30m_B04",
    "rs_sentinel2_cdse_monthly_30m_B05",
    "rs_sentinel2_cdse_monthly_30m_B08",
    "rs_sentinel2_cdse_monthly_30m_B11",
    "rs_sentinel2_cdse_monthly_30m_FAI",
    "rs_sentinel2_cdse_monthly_30m_MCI",
    "rs_sentinel2_cdse_monthly_30m_NDCI",
    "rs_sentinel2_cdse_monthly_30m_NDWI",
    "rs_sentinel2_monthly_20m_B03",
    "rs_sentinel2_monthly_20m_B04",
    "rs_sentinel2_monthly_20m_B05",
    "rs_sentinel2_retrieval_20260802_chlorophyll_a_experimental_ug_l",
    "rs_sentinel2_retrieval_20260802_fai",
    "rs_sentinel2_retrieval_20260802_mci",
    "rs_sentinel2_retrieval_20260802_ndci",
    "rs_sentinel2_retrieval_20260802_ndwi",
)
STATIC_V2: tuple[str, ...] = (
    "static_station_inside_lake", "static_station_latitude",
    "static_station_longitude", "static_lake_area_km2",
    "static_lake_elevation_mean_m", "static_dem_valid_frac",
)
CALENDAR_V2: tuple[str, ...] = ("calendar_month_sin", "calendar_month_cos")
MECHANISM_V2: tuple[str, ...] = (
    "mech_temperature_factor", "mech_light_factor", "mech_phosphorus_factor",
    "mech_nitrogen_factor", "mech_nutrient_factor", "mech_net_growth_rate_d",
)
LAG_STATE_BASE_V2: tuple[str, ...] = (
    "wq_chla", "wq_tp", "wq_tn", "wq_do", "wq_nh4_n",
    "met_air_temperature_c", "met_shortwave_radiation_wm2",
    "hydro_water_level_m", "rs_clms_lwq_300m_10daily_chla_mean",
)


def lag_state_columns_v2() -> tuple[str, ...]:
    names: list[str] = []
    for base in LAG_STATE_BASE_V2:
        names.extend((f"{base}_lag1m", f"{base}_lag2m", f"{base}_roll3m_mean"))
    return tuple(names)


FEATURE_COLUMNS_V2: tuple[str, ...] = tuple(dict.fromkeys((
    *WATER_QUALITY_V2, *METEOROLOGY_V2, *HYDROLOGY_V2, *REMOTE_SENSING_V2,
    *STATIC_V2, *CALENDAR_V2, *MECHANISM_V2, *lag_state_columns_v2(),
)))
assert len(FEATURE_COLUMNS_V2) == 78, f"feature contract v2 must hold 78 fields, got {len(FEATURE_COLUMNS_V2)}"


# ---------- 推理可信（serving-faithful）特征子契约（2026-09-11） ----------
# 服务对象是 MEE 79 站：推理时逐站可变的输入只有站点实测水质与日历。其余特征
# （滞后/遥感/气象/水文/机理/静态）在推理时为 TAIHU_WHOLE 上下文常量或中位数
# 插补——用它们训练出的模型在服务时对站点输入无响应（实测教训：80 实体
# transformed 指纹互不相同、输出却完全同值）。本子契约只含「训练面板真实变化
# ∩ 推理时逐站可得」的特征。注意 wq_chla 不在冻结 78 列契约中（仅其滞后列在内，
# 防同月同源泄漏），因此它不出现在任何监督表里，训练交集自然为 7 列。
# 2026-09-11 对齐：wq_water_temp 入约（训练面板=ERA5 湖表温度网格月均/野外实测，
# 推理=MEE 本站实测水温），驱动展示与模型输入同源；wq_chla 仅对 month_offset≥1
# 任务入约（目标月在未来，当月实测为历史量，无同月泄漏），由训练管线按时效追加。
SERVING_OBSERVED_WQ_V2: tuple[str, ...] = (
    "wq_tp", "wq_tn", "wq_do", "wq_nh4_n", "wq_ph", "wq_water_temp",
)
SERVING_CALENDAR_V2: tuple[str, ...] = CALENDAR_V2
SERVING_FEATURE_COLUMNS_V2: tuple[str, ...] = tuple(dict.fromkeys((
    *SERVING_OBSERVED_WQ_V2, *SERVING_CALENDAR_V2,
)))
assert len(SERVING_FEATURE_COLUMNS_V2) == 8

# month_offset≥1 任务追加的历史观测特征（当月实测相对目标月为过去量，无泄漏）
SERVING_LAGGED_TARGET_FEATURES: dict[str, tuple[str, ...]] = {
    "chla": ("wq_chla",),
    "bloom": ("wq_chla",),
}

FEATURE_CONTRACT_FROZEN = "v2.0-78col-frozen"
FEATURE_CONTRACT_SERVING = "v2.1-serving-8col"


def serving_feature_columns_for_task(label_family: str) -> tuple[str, ...]:
    """serving 子契约的任务级特征列：同样剔除目标同源特征。"""
    excluded = set(TARGET_SOURCE_FEATURE_EXCLUSIONS.get(label_family, ()))
    return tuple(name for name in SERVING_FEATURE_COLUMNS_V2 if name not in excluded)


def feature_contract_sha256() -> str:
    payload = json.dumps(list(FEATURE_COLUMNS_V2), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureContractV2:
    version: str = "v2.0"
    n_features: int = 78
    sha256: str = feature_contract_sha256()
    water_quality: tuple[str, ...] = WATER_QUALITY_V2
    meteorology: tuple[str, ...] = METEOROLOGY_V2
    hydrology: tuple[str, ...] = HYDROLOGY_V2
    remote_sensing: tuple[str, ...] = REMOTE_SENSING_V2
    static: tuple[str, ...] = STATIC_V2
    calendar: tuple[str, ...] = CALENDAR_V2
    mechanism: tuple[str, ...] = MECHANISM_V2
    lag_state: tuple[str, ...] = lag_state_columns_v2()

    def validate_no_forbidden_columns(self, cols) -> None:
        forbidden_prefixes = ("target_", "latent_", "simulation_", "label_")
        forbidden_exact = {"dataset_split", "station_id", "month", "station_name", "row_id"}
        bad = [
            c for c in cols
            if str(c).startswith(forbidden_prefixes) or str(c) in forbidden_exact
        ]
        if bad:
            raise ValueError(f"forbidden feature columns: {sorted(bad)}")

    def require_real_columns(self, available) -> None:
        missing = [c for c in FEATURE_COLUMNS_V2 if c not in set(available)]
        if missing:
            raise ValueError(f"contract columns missing from source data: {missing}")


# ---------- 时效→月份偏移（主理人裁定 1） ----------
HORIZON_MONTH_MAP_V3: dict[int, int] = {1: 0, 3: 0, 7: 0, 15: 0, 30: 1, 60: 2, 90: 3}
HORIZON_GRANULARITY_TIER_V3: dict[int, str] = {
    1: "month_granularity", 3: "month_granularity",
    7: "month_approx_half", 15: "month_approx_half",
    30: "multi_month", 60: "multi_month", 90: "multi_month",
}
SCENARIO_HORIZONS_V3: tuple[int, ...] = (30, 60, 90)


@dataclass(frozen=True)
class HorizonMap:
    month_map: dict[int, int] = None  # type: ignore[assignment]
    granularity_tier: dict[int, str] = None  # type: ignore[assignment]
    scenario_horizons: tuple[int, ...] = SCENARIO_HORIZONS_V3

    def __post_init__(self) -> None:
        object.__setattr__(self, "month_map", dict(HORIZON_MONTH_MAP_V3))
        object.__setattr__(self, "granularity_tier", dict(HORIZON_GRANULARITY_TIER_V3))

    def month_offset(self, horizon_days: int) -> int:
        if int(horizon_days) not in self.month_map:
            raise ValueError(f"unsupported forecast horizon: {horizon_days}")
        return self.month_map[int(horizon_days)]

    def tier(self, horizon_days: int) -> str:
        if int(horizon_days) not in self.granularity_tier:
            raise ValueError(f"unsupported forecast horizon: {horizon_days}")
        return self.granularity_tier[int(horizon_days)]


HORIZON_MAP_V3 = HorizonMap()


# ---------- 标签来源口径（2026-09-11 修正） ----------
# 声明口径（spec.label_provenance）只表达「该任务允许出现哪些标签来源」；
# 真正落盘的权威口径是监督表逐行的 actual_provenance 汇总（见 target_builder.provenance_summary）。
# 此前把 T5-chla 一律声明为 ground_truth 是错的：T5 的 567 行 T+90 监督标签全部来自
# chla_station_proxy_v1 代理，声明与事实不符，会一路传到风险等级与季节基线的披露文本。
PROVENANCE_GROUND_TRUTH = "ground_truth"
PROVENANCE_PROXY_DERIVED = "proxy_derived"
# 混合来源任务的声明口径：具体以逐行 actual_provenance 汇总为准，禁止统一写成 ground_truth。
PROVENANCE_GROUND_TRUTH_OR_PROXY = "ground_truth_or_proxy"


# ---------- 任务规格（真实标签映射） ----------
@dataclass(frozen=True)
class TaskSpecReal:
    task_id: str
    variant: str
    label_family: str  # chla | bloom | none
    problem_type: str  # binary | regression | probability | ordinal | none
    primary_metric: str
    label_provenance: str  # ground_truth | proxy_derived | ground_truth_or_proxy | none
    label_columns: tuple[str, ...] = ()


TASK_SPECS_REAL: tuple[TaskSpecReal, ...] = (
    TaskSpecReal("T1", "bloom", "bloom", "binary", "brier_score", "proxy_derived"),
    TaskSpecReal("T2", "coverage", "coverage", "regression", "mae", "proxy_derived", ("label_coverage_fcb_prob",)),
    TaskSpecReal("T3", "density", "density", "regression", "log1p_mae", "proxy_derived", ("label_density_rank_proxy",)),
    TaskSpecReal("T4", "biomass", "biomass", "regression", "mae", "ground_truth", ("label_phyto_biomass_mg_l",)),
    # T5-chla：地面实测 chla 仅 4 个航次月（42 行），其余靠 chla_station_proxy_v1 代理回填；
    # 两来源并存 → 声明为混合，逐行 actual_provenance 才是权威口径。
    TaskSpecReal("T5", "chla", "chla", "regression", "mae", "ground_truth_or_proxy"),
    # 风险等级由 T5 叶绿素值经冻结风险带推导，来源继承 T5（同样混合），不是独立标签。
    TaskSpecReal("T6", "risk_level", "chla", "ordinal", "macro_f1", "ground_truth_or_proxy"),
    TaskSpecReal("T6", "probability", "bloom", "probability", "brier_score", "proxy_derived"),
    TaskSpecReal("T7", "spatial", "none", "none", "area_weighted_iou", "none"),
)

TASK_LABELS_ZH: dict[str, str] = {
    "T1": "水华发生", "T2": "水华面积/覆盖率", "T3": "蓝藻密度",
    "T4": "蓝藻生物量", "T5": "叶绿素 a", "T6": "风险等级/概率", "T7": "空间范围",
}


def task_spec_real(task_id: str, variant: str) -> TaskSpecReal:
    for spec in TASK_SPECS_REAL:
        if spec.task_id == task_id and spec.variant == variant:
            return spec
    raise ValueError(f"unknown task/variant: {task_id}/{variant}")


def run_id_real(task_id: str, variant: str, month_offset: int, seed: int, protocol_tag: str = "") -> str:
    """run_id = 任务产物身份。

    protocol_tag（2026-09-11 加）：同一 (task, variant, month_offset) 在冻结划分协议与
    训练期内时间分块协议下会各产出一份评估记录。两者此前共用同一 run_id，导致门禁表
    无法区分记录归属、后写的评估覆盖先写的语义。补训协议记为 "cv"，与冻结划分互不混淆；
    模型产物槽位文件名仍由 horizon 决定（见 data_real.save_bundle filename），不随标记变化。
    """
    base = f"{task_id}-{variant}-{month_offset}m-s{seed}"
    return f"{base}-{protocol_tag}" if protocol_tag else base


def artifact_id_real(
    task_id: str, variant: str, month_offset: int, horizon_days: int, seed: int,
    protocol: str = "frozen_split",
) -> str:
    """模型产物的唯一身份（2026-09-11 新增）。

    为什么必须有它：run_id 只含 (task, variant, month_offset, seed, protocol)，不含时效——
    T5-chla-0m-s20260907-cv 同时对应 T+1/3/7/15 四份不同模型文件，无法唯一定位产物；
    而接口原先又用 run_id 自己去拼文件名，就拼出了不存在的
    "T5-chla-0m-s20260907-cv-1d.joblib"（真实文件是 T5-chla-0m-s20260907-1d.joblib）。

    artifact_id 至少包含 task / variant / protocol / month_offset / horizon / seed。
    交付包里由 manifest 的 models[].artifact_id 落盘，运行层只读取、不再拼接。
    """
    return (
        f"{task_id}:{variant}:{protocol}:off{int(month_offset)}:h{int(horizon_days)}:s{int(seed)}"
    )


def protocol_of_run(protocol_tag: str) -> str:
    """协议标记 → 协议 ID（与 run_config.split_protocol.protocol_id 同构）。"""
    return "train_internal_time_block_cv_v1" if protocol_tag else "frozen_split"


# ---------- 路径约定 ----------
def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def clean_tables_dir() -> Path:
    import os
    override = os.environ.get("TAIHU_CLEAN_TABLES_DIR", "").strip()
    if override:
        return Path(override)
    return project_root() / "data-cleaning" / "storage" / "final_cleaned" / "TAIHU_CLEAN_FINAL_V1_20260831" / "tables"


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def split_of_month(month: str) -> str:
    if month <= SPLIT_BOUNDS["train_max"]:
        return "train"
    if month <= SPLIT_BOUNDS["validation_max"]:
        return "validation"
    return "test"
