# -*- coding: utf-8 -*-
"""公共工具库：路径、编码、时间、缺失值、数值、单位、质量标记、CSV/Parquet 输出。

所有清洗脚本共用此模块，保证字段、单位、时间、质量标记口径一致。
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------- 路径 -----------------------------
ROOT = Path(__file__).resolve().parents[1]                      # data-cleaning/
STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
CLEANED = STORAGE / "cleaned"
ARCHIVE = STORAGE / "raw_organized"
MANIFESTS = STORAGE / "manifests"
RELEASE_TABLES = STORAGE / "releases" / "taihu_public_v1" / "tables"

CACHE_DIR = CLEANED / ".cache"
_CACHE_PATH = CACHE_DIR / "pipeline_cache.json"

CLEANED.mkdir(parents=True, exist_ok=True)
MANIFESTS.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 北京时间
BEIJING = timezone(timedelta(hours=8))

def bnow() -> datetime:
    """北京时间当前时间（用于 acquisition_date 等）。"""
    return datetime.now(timezone.utc).astimezone(BEIJING)

# ----------------------------- 编码与读取 -----------------------------
_ENCODING_ORDER = ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16", "latin-1")

def read_text(path, encoding: str | None = None) -> tuple[str, str]:
    """读取文本，自动探测编码。返回 (text, 使用编码)。"""
    p = Path(path)
    raw = p.read_bytes()
    if encoding:
        return raw.decode(encoding), encoding
    for enc in _ENCODING_ORDER:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1"), "latin-1(自动降级)"

def read_table(path) -> tuple[pd.DataFrame, str]:
    """以自动探测编码读取 CSV/Delimited 文本。返回 (df, encoding)。"""
    text, enc = read_text(path)
    df = pd.read_csv(io.StringIO(text))
    return df, enc

# ----------------------------- 缺失值 -----------------------------
# 需要识别为缺失的典型文本值（全半角、大小写、两侧空白、常见的 "--"、"/" 等）
MISSING_TOKENS = {
    "", "--", "-", "—", "––", "—", "／", "/", "\\", "\\N",
    "无", "未检出", "无数据", "不具备", "未检测", "缺测", "缺",
    "N/A", "n/a", "na", "NA", "nan", "NaN", "NAN", "null", "NULL", "None",
    "no data", "NO DATA", "not available", "空", "空白", "无值", "秒",
}

def is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    if isinstance(v, str):
        return v.strip() in MISSING_TOKENS or v.strip().casefold() in {"n/a", "na", "nan", "null", "none"}
    return False

def to_number(v) -> float:
    """转换为数值；无法识别缺失则返回 NaN。"""
    if is_missing(v):
        return float("nan")
    if isinstance(v, (int, float)):
        v = np.float64(v)
        return float(v) if np.isfinite(v) else float("nan")
    s = str(v).strip().replace(",", "").replace("　", " ").replace("→", "").replace("->", "")
    if s in MISSING_TOKENS:
        return float("nan")
    s = s.rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")

def is_usable_number(v) -> bool:
    return not np.isnan(to_number(v))

# ----------------------------- 时间 -----------------------------
_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
    "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y%m%dT%H%M%S",
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y%m%d", "%Y%m", "%Y-%m", "%Y",
    "%Y_%m_%d %H:%M", "%Y_%m_%d %H:%M:%S", "%Y%m%d%H%M",
]

def coerce_datetime(v):
    """尽力解析为 pandas Timestamp；带时区的时间统一为北京时间。失败返回 NaT。"""
    if v is None or is_missing(v):
        return pd.NaT
    if isinstance(v, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(v)
        return _to_beijing(ts)
    if isinstance(v, (int, float)):  # excel 序列号等
        if 20000 <= float(v) < 60000:  # Excel 序列(1900起)
            try:
                return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))
            except (ValueError, OverflowError):
                return pd.NaT
        return pd.NaT
    s = str(v).strip()
    for fmt in _DT_FORMATS:
        try:
            return _to_beijing(pd.Timestamp(pd.to_datetime(s, format=fmt)))
        except (ValueError, TypeError):
            continue
    try:
        return _to_beijing(pd.Timestamp(pd.to_datetime(s)))
    except (ValueError, TypeError, OverflowError):
        return pd.NaT

def _to_beijing(ts: pd.Timestamp) -> pd.Timestamp:
    """统一到北京时间（东八区）；UTC 时间 +8h，无时区的时间视为北京时间保留。"""
    if ts.tzinfo is not None:
        ts = ts.tz_convert(BEIJING).tz_localize(None)
    return ts

def month_of(ts) -> str:
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m")

def date_of(ts) -> str:
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d")

def datetime_of(ts) -> str:
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

# ----------------------------- 单位 -----------------------------
def normalize_unit(u) -> str:
    if is_missing(u):
        return ""
    s = str(u).strip().replace(" ", "").replace("·", "/").lower()
    s = s.replace("μg/l", "mg/l").replace("µg/l", "mg/l")  # 仅作规范化,不做换算
    return s

# 变量统一编码表: (category, 别名集合) -> 标准 variable_code
_VARIABLE_ALIASES = {
    # 水质
    "ph": "ph",
    "codmn": "codmn", "cod_mn": "codmn", "高锰酸盐指数": "codmn",
    "do": "do", "dissolved_oxygen": "do", "溶解氧": "do",
    "tp": "tp", "total_phosphorus": "tp", "总磷": "tp",
    "po4_p": "po4_p", "po4-p": "po4_p", "磷酸盐": "po4_p", "po4p": "po4_p",
    "tn": "tn", "total_nitrogen": "tn", "总氮": "tn",
    "nh4_n": "nh4_n", "nh4-n": "nh4_n", "氨氮": "nh4_n", "nh4n": "nh4_n",
    "no3_n": "no3_n", "no3-n": "no3_n", "硝态氮": "no3_n", "no3n": "no3_n",
    "no2_n": "no2_n", "no2-n": "no2_n", "亚硝态氮": "no2_n", "no2n": "no2_n",
    "chla": "chla", "chlorophyll_a": "chla", "叶绿素a": "chla", "叶绿素a浓度": "chla",
    "tsm": "tsm", "total_suspended_matter": "tsm", "悬浮物": "tsm",
    "sdd": "sdd", "secchi_depth": "sdd", "透明度": "sdd", "secchi_disk_depth": "sdd",
    "water_temperature": "water_temperature", "水温": "water_temperature", "temp": "water_temperature",
    "phyto_biomass": "phyto_biomass", "浮游植物生物量": "phyto_biomass",
    "phyto_number": "phyto_number", "浮游植物丰度": "phyto_number",
    "zoo_biomass": "zoo_biomass", "浮游动物生物量": "zoo_biomass",
    "zoo_number": "zoo_number", "浮游动物丰度": "zoo_number",
    # 气象
    "t2m": "air_temperature", "air_temperature": "air_temperature", "temp2m": "air_temperature", "气温": "air_temperature",
    "ws2m": "wind_speed_10m_adj", "ws10m": "wind_speed_10m", "wind_speed": "wind_speed", "风速": "wind_speed",
    "wd2m": "wind_direction", "wd10m": "wind_direction", "wind_direction": "wind_direction",
    "prectotcorr": "precipitation", "precipitation": "precipitation", "pr": "precipitation", "降水": "precipitation",
    "allsky_sfc_sw_dwn": "shortwave_radiation", "sw_dwn": "shortwave_radiation", "辐射": "shortwave_radiation",
    "ratm": "air_pressure", "air_pressure": "air_pressure",
    # 水文
    "water_level": "water_level", "水位": "water_level", "wl": "water_level", "depth": "water_depth",
    "water_depth": "water_depth",
    # 遥感
    "ndci": "ndci", "mci": "mci", "fai": "fai", "ndwi": "ndwi",
    "chla_mean": "chla_retrieval", "chlamean": "chla_retrieval", "chla_retrieval": "chla_retrieval",
    "chla_unc": "chla_retrieval_uncertainty", "chlaunc": "chla_retrieval_uncertainty",
    "fcb_prob": "fcb_prob", "fcbprob": "fcb_prob",
    "qflag": "qflag", "cloud_ratio": "cloud_ratio", "valid_pixel_ratio": "valid_pixel_ratio",
    "b03": "b03", "b04": "b04", "b05": "b05", "b08": "b08", "b11": "b11",
    # 静态
    "elevation": "elevation_m", "dem": "elevation_m",
}

def map_variable(src: str) -> str:
    """把来源参数名映射到标准 variable_code；无法映射时保留原串(小写)。"""
    key = str(src).strip().lower()
    key = key.replace(" ", "_").replace("-", "_").replace("/", "_").replace("(", "").replace(")", "")
    if key in _VARIABLE_ALIASES:
        return _VARIABLE_ALIASES[key]
    # 形如 "(mg/L)" 的单位头尾剥掉后不含字母下划线数字之外的字符 → 直接映射
    return key if key else "unknown_variable"

# ----------------------------- 质量标记 -----------------------------
# 规则: 每类问题一个代码；可用逗号分隔多个。0 表示没有问题。
Q_FLAGS = {
    "Q00": 0,  # 0 = 通过/正常
    "Q01": 1,  # 时间不可解析或超范围
    "Q02": 1,  # 坐标缺失或超出太湖合理范围(118.5-121.5E, 29.5-32.5N)
    "Q03": 1,  # 数值缺失
    "Q04": 1,  # 数值非数字
    "Q05": 1,  # 物理不合理范围（绝对值超物理界）
    "Q06": 1,  # 单位冲突/单位缺失
    "Q07": 1,  # 完全重复行（已去重）
    "Q08": 1,  # 同站同时同源重复观测冲突
    "Q09": 1,  # 低于检出水平(未检出标记)
    "Q10": 1,  # 遥感低云量质量/低覆盖
    "Q11": 1,  # 来源描述数据而非直接观测（派生聚合）
    "Q12": 1,  # 站点无坐标等元数据缺失
    "Q13": 1,  # 数据为年度/季度聚合尺度（非月度）
}

QUALITY_MEANING = {
    "Q00": "正常",
    "Q01": "时间无法解析或超出合理范围",
    "Q02": "坐标缺失或超出太湖合理范围",
    "Q03": "数值缺失",
    "Q04": "数值为非数字字符",
    "Q05": "数值超出该变量物理合理性范围",
    "Q06": "单位冲突或缺失",
    "Q07": "完全重复行（已去重）",
    "Q08": "相同站点相同时间的重复观测不一致",
    "Q09": "低于检出水平（未检出）",
    "Q10": "遥感影像低云量质量或低覆盖",
    "Q11": "派生数据（非直接观测）",
    "Q12": "站点缺少坐标等元数据",
    "Q13": "年度或季度聚合尺度，非月尺度",
}

def flag_join(flags) -> str:
    if not flags:
        return "Q00"
    if isinstance(flags, str):
        flags = [flags]
    cleaned = [f for f in flags if f and f != "Q00"]
    return ",".join(sorted(set(cleaned))) if cleaned else "Q00"

def flag_note(flag_code: str) -> str:
    if not flag_code or flag_code == "Q00":
        return ""
    return ";".join(QUALITY_MEANING.get(f, f) for f in flag_code.split(","))

# ----------------------------- 物理合理范围 -----------------------------
# variable_code -> (下限, 上限)。仅用于识别显式异常（标注 Q05），不删除。
PHYSICAL_RANGES = {
    "ph": (0.0, 14.0),
    "do": (0.0, 25.0),
    "codmn": (0.0, 150.0),
    "tp": (0.0, 50.0),
    "po4_p": (0.0, 30.0),
    "tn": (0.0, 100.0),
    "nh4_n": (0.0, 60.0),
    "no3_n": (0.0, 50.0),
    "no2_n": (0.0, 20.0),
    "chla": (0.0, 10000.0),          # µg/L 判界, mg/L 时需乘 1000以下
    "tsm": (0.0, 5000.0),
    "sdd": (0.0, 500.0),
    "water_temperature": (-20.0, 60.0),
    "air_temperature": (-60.0, 60.0),
    "precipitation": (0.0, 2000.0),
    "wind_speed": (0.0, 100.0),
    "shortwave_radiation": (0.0, 2000.0),
    "water_level": (-200.0, 300.0),
    "water_depth": (0.0, 30.0),
    "ndci": (-2.0, 2.0),
    "mci": (-5.0, 5.0),
    "fai": (-5.0, 5.0),
    "ndwi": (-2.0, 2.0),
}

TAIHU_BBOX = dict(lon_min=118.5, lon_max=121.5, lat_min=29.5, lat_max=32.5)

# ----------------------------- 输出 -----------------------------
def write_csv(df: pd.DataFrame, path: Path, index: bool = False) -> Path:
    """UTF-8 with BOM 输出，确保 Excel 打开中文不乱码。"""
    df.to_csv(path, index=index, encoding="utf-8-sig")
    return path

def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    df.to_parquet(path, index=False)
    return path

def write_dataset(df: pd.DataFrame, name: str, also_parquet: bool = True):
    """同时写 CSV(带BOM) 与 Parquet 到 cleaned 目录。返回 csv 路径。"""
    csv_path = write_csv(df, CLEANED / f"{name}.csv")
    if also_parquet:
        try:
            write_parquet(df, CLEANED / f"{name}.parquet")
        except Exception:  # pyarrow 异常不阻断流程
            pass
    return csv_path

def brief(df: pd.DataFrame) -> str:
    return f"{df.shape[0]} rows x {df.shape[1]} cols"

# ----------------------------- 哈希与缓存 -----------------------------
def file_sha256(path, chunk: int = 1 << 20, quick: bool = False) -> str:
    """文件哈希；quick=True 时只读前 1MB+尾 64KB（加速大文件, 归档按全量哈希）。"""
    p = Path(path)
    h = hashlib.sha256()
    if quick and p.stat().st_size > 8_000_000:
        with open(p, "rb") as f:
            h.update(f.read(chunk))
            f.seek(-65536, 2)
            h.update(f.read())
        return h.hexdigest()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()

def load_cache() -> dict:
    if _CACHE_PATH.exists():
        import json
        with open(_CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}

def save_cache(cache: dict) -> None:
    import json
    with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
