# -*- coding: utf-8 -*-
"""K2 公共装载层：只读复用 K1 的残差池与训练代码快照，构造校准段/测试段的逐行元数据。

红线遵守：
  - 只读：K1 残差池 CSV / 模型 run 记录 / `_replay_pkg` 训练当时代码快照（commit 73be6e7）。
  - 只用 K1 的 `_replay_pkg/modeling_real/`，绝不用工作区现码（K1-03 版本漂移）。
  - 本模块只做装载与元数据拼接，不做任何模型拟合、不改任何产物。
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]          # backend/
CALW = ROOT / "calibration_work"                     # K1 产物目录
PKG = ROOT / "model_runtime_v0_3"
REPLAY_PKG = CALW / "_replay_pkg"
ZONES_JSON = ROOT / "app" / "data" / "mee_station_zones.json"

sys.path.insert(0, str(PKG / "code"))
sys.path.insert(0, str(REPLAY_PKG))

# K2 只在 T5-chla 的 T+1 / T+90 两个 K1 已重建的槽位上工作（与 K1 交付一致）
CASES = {
    "T+1": {
        "tag": "T+1",
        "stem": "residual_pool_T5-chla_T+1_mo0",
        "run_dir": "T5-chla-1d-0m-cv",
        "model_file": "T5-chla-0m-s20260907-1d.joblib",
        "horizon": 1,
        "offset": 0,
        "split_key": "month",
        "selected_family": "mechanism_feature",
        "bundle_p05": -5.576590119861105,
        "bundle_p95": 4.405360984880952,
        "bundle_calibration_n": 234,
        "test_n": 132,
    },
    "T+90": {
        "tag": "T+90",
        "stem": "residual_pool_T5-chla_T+90_mo3",
        "run_dir": "T5-chla-90d-3m-cv",
        "model_file": "T5-chla-3m-s20260907-90d.joblib",
        "horizon": 90,
        "offset": 3,
        "split_key": "target_month",
        "selected_family": "random_forest",
        "bundle_p05": -3.95219869722222,
        "bundle_p95": 7.214580163795102,
        "bundle_calibration_n": 225,
        "test_n": 117,
    },
}

SEASON_BY_MONTH = {2: "冬(2月)", 5: "春(5月)", 8: "夏(8月)", 11: "秋(11月)"}

# 太湖八个惯用分区站 = 分区代码本身；TAIHU_WHOLE=全湖；IN_SITU_GROUP/S1=野外
WHOLE_STATIONS = {"TAIHU_WHOLE"}
FIELD_STATIONS = {"IN_SITU_GROUP", "S1"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def zone_names() -> dict:
    """TAIHU_XX 分区代码 → 中文分区名（来自 serving 侧公开分区映射，只读）。"""
    try:
        raw = json.loads(ZONES_JSON.read_text(encoding="utf-8"))
        return {code: meta["name"] for code, meta in raw.get("zones", {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def zone_of(station: str) -> str:
    if station in WHOLE_STATIONS:
        return "全湖"
    if station in FIELD_STATIONS:
        return "野外"
    return station  # 八个分区站代码即分区


def season_of(month: str) -> str:
    return SEASON_BY_MONTH.get(int(str(month)[5:7]), "其他")


def build_supervised_table(offset: int) -> pd.DataFrame:
    """用 `_replay_pkg`（训练当时代码）重建监督底表，用于取测试段逐行元数据。"""
    from modeling_real.contracts_real import TASK_SPECS_REAL, SERVING_FEATURE_COLUMNS_V2, \
        SERVING_LAGGED_TARGET_FEATURES
    from modeling_real.target_builder import build_supervised_base, build_supervised_table as _bst

    spec = next(s for s in TASK_SPECS_REAL if s.task_id == "T5" and s.variant == "chla")
    base, labels = build_supervised_base()
    table = _bst(base, labels, spec, offset)
    feature_columns = tuple(c for c in SERVING_FEATURE_COLUMNS_V2 if c in table.columns)
    if offset >= 1:
        extra = SERVING_LAGGED_TARGET_FEATURES.get(spec.label_family, ())
        feature_columns = tuple(dict.fromkeys((*feature_columns, *(c for c in extra if c in table.columns))))
    return table, feature_columns


def cv_split_bounds(table: pd.DataFrame, split_key: str) -> dict:
    """复刻 cli_real_cv._train_cv_run 的 60/20/20 时间分块边界（只读计算）。"""
    from modeling_real.cli_real_cv import CV_BLOCK_TRAIN_FRACTION, CV_BLOCK_VALIDATION_FRACTION
    months = sorted(table[split_key].unique())
    train_end = months[max(int(len(months) * CV_BLOCK_TRAIN_FRACTION) - 1, 0)]
    validation_end = months[
        max(int(len(months) * (CV_BLOCK_TRAIN_FRACTION + CV_BLOCK_VALIDATION_FRACTION)) - 1, 0)
    ]
    test_start = months[months.index(validation_end) + 1] if months.index(validation_end) + 1 < len(months) else None
    return {
        "n_months": len(months),
        "train_max_month": train_end,
        "validation_max_month": validation_end,
        "test_min_month": test_start,
    }


def load_residual_pool(case_key: str) -> pd.DataFrame:
    """读 K1 残差池 CSV（OOF + validation 逐行），补 season/zone 列。"""
    df = pd.read_csv(CALW / f"{CASES[case_key]['stem']}.csv", encoding="utf-8-sig")
    df["target_month"] = df["target_month"].astype(str)
    df["month"] = df["month"].astype(str)
    df["season"] = df["target_month"].map(season_of)
    df["zone"] = df["station_id"].map(zone_of)
    df["pool"] = "校准段"
    return df


def load_test_predictions(case_key: str, table: pd.DataFrame) -> pd.DataFrame:
    """读模型 run 的 test_predictions.csv，按 row_id 补 station/provenance/季节/湖区。

    注意：test_predictions.csv 无 station_id，必须用监督底表按 row_id 补全；
    row_id 在监督表内唯一（K1 schema 声明；本函数会断言）。
    """
    cfg = CASES[case_key]
    run = pd.read_csv(PKG / "runs" / cfg["run_dir"] / "test_predictions.csv")
    run["month"] = run["month"].astype(str)
    meta_cols = ["row_id", "station_id", "target_month", "actual_provenance", "actual"]
    meta = table[meta_cols].drop_duplicates("row_id").set_index("row_id")
    assert table["row_id"].is_unique, "row_id 在监督表内不唯一，元数据拼接不安全"
    miss = sorted(set(run["row_id"]) - set(meta.index))
    if miss:
        raise AssertionError(f"test row_id 无法在监督表定位: {miss[:5]} (n={len(miss)})")
    out = run.join(meta.drop(columns=["actual"]), on="row_id", how="left")
    # actual 以 test_predictions 为准（模型记录口径），仅做一致性校验
    chk = np.max(np.abs(out["actual"].to_numpy(float) - meta.loc[out["row_id"], "actual"].to_numpy(float)))
    out.attrs["actual_vs_supervised_max_abs_diff"] = float(chk)
    out["target_month"] = out["target_month"].astype(str)
    out["season"] = out["target_month"].map(season_of)
    out["zone"] = out["station_id"].map(zone_of)
    out["residual"] = out["actual"].astype(float) - out["prediction"].astype(float)
    out["pool"] = "测试段"
    return out, chk


def write_json(payload: dict, path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
