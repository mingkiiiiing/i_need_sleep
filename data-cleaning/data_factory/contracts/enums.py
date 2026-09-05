"""枚举与任务定义 (设计 §9 数据契约)."""

from __future__ import annotations

from enum import Enum

HORIZONS: tuple[int, ...] = (1, 3, 7, 15, 30)

TASK_METRICS: dict[str, str] = {
    "T1": "bloom_label",
    "T2": "bloom_area",
    "T3": "blue_algae_density",
    "T4": "blue_algae_biomass",
    "T5": "chlorophyll_a",
    "T6": "risk_level",
    "T7": "spatial_extent",
}

TASK_UNITS: dict[str, str] = {
    "T1": "0/1",
    "T2": "km2",
    "T3": "10^4 cells/L",
    "T4": "mg/L",
    "T5": "ug/L",
    "T6": "level",
    "T7": "0/1",
}

# 成员 C 训练 schema 的 target_metric 枚举 (required_training_schema_V0.1.csv；
# 2026-09-05 接口收尾：T3 blue_algae_density / T7 spatial_extent 经契约评审正式接收)
MEMBER_C_METRICS = {
    "chlorophyll_a",
    "bloom_area",
    "blue_algae_biomass",
    "bloom_label",
    "risk_level",
    "blue_algae_density",
    "spatial_extent",
}

LAKE_ZONE_CODES: dict[str, str] = {
    "TAIHU_ML": "梅梁湾",
    "TAIHU_ZS": "竺山湖",
    "TAIHU_GH": "贡湖",
    "TAIHU_XK": "胥湖",
    "TAIHU_ET": "东太湖",
    "TAIHU_CT": "湖心区",
    "TAIHU_WT": "西部沿岸",
    "TAIHU_ST": "南部沿岸",
    "TAIHU_WHOLE": "全湖",
}


class ValueType(str, Enum):
    OBSERVED = "observed"
    DERIVED = "derived"
    PROXY = "proxy"
    FORECAST_INPUT = "forecast_input"
    SIMULATED = "simulated"
    METADATA_ONLY = "metadata_only"


class LabelStatus(str, Enum):
    OBSERVED_POSITIVE = "observed_positive"
    OBSERVED_NEGATIVE = "observed_negative"
    UNKNOWN = "unknown"
    SIMULATION_POSITIVE = "simulation_positive"
    SIMULATION_NEGATIVE = "simulation_negative"
    # 仿真观测层导出的观测标签（源观测 is_synthetic=true 时使用，DG-003 身份不可逆）
    SIMULATION_OBSERVED_POSITIVE = "simulation_observed_positive"
    SIMULATION_OBSERVED_NEGATIVE = "simulation_observed_negative"
    MEASURED_VALUE = "measured_value"


class Track(str, Enum):
    SIM_V1 = "SIM-V1"
    HYBRID_V1 = "HYBRID-V1"
    REAL_V1 = "REAL-V1"


class MissingReason(str, Enum):
    NOT_SAMPLED = "not_sampled"
    BELOW_DETECTION = "below_detection"
    CLOUD_COVER = "cloud_cover"
    NO_PASS = "no_pass"
    API_UNAVAILABLE = "api_unavailable"
    STALE = "stale"


class QualityFlag(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
