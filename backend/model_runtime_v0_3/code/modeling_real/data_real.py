"""StationMonthSource（BatchSource 协议实现）+ 训练期中位数预处理器 + bundle 数据类。

自包含实现（不依赖 modeling_v1），避免跨包导入脆弱性；median 插补 + 显式缺失标记
与 V0.2 语义一致。全部数值字段带默认值与显式类型。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

import joblib
import numpy as np
import pandas as pd

from .contracts_real import CLAIM_BOUNDARY_V3, DATA_VERSION_V3


def _missing_column_name(column: str) -> str:
    return column if column.endswith("_missing") else f"{column}_missing"


@dataclass(frozen=True)
class RealPreprocessor:
    """训练集拟合的中位数插补器 + 缺失指示列（输出 = 特征 + 缺失标记）。"""

    feature_columns: tuple[str, ...]
    medians: dict[str, float]
    missing_columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    imputed_ratio: dict[str, float] = field(default_factory=dict)
    fit_split: str = "train"

    @classmethod
    def fit(cls, frame: pd.DataFrame, feature_columns: Sequence[str]) -> "RealPreprocessor":
        columns = tuple(feature_columns)
        work = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
        medians = {
            name: float(work[name].median()) if work[name].notna().any() else 0.0
            for name in columns
        }
        imputed_ratio = {
            name: float(work[name].isna().mean()) for name in columns
        }
        missing_columns = tuple(_missing_column_name(name) for name in columns)
        output_columns = tuple(dict.fromkeys((*columns, *missing_columns)))
        return cls(
            feature_columns=columns,
            medians=medians,
            missing_columns=missing_columns,
            output_columns=output_columns,
            imputed_ratio=imputed_ratio,
        )

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [name for name in self.feature_columns if name not in frame.columns]
        if missing:
            raise ValueError(f"input frame missing feature columns: {missing}")
        values = {
            name: pd.to_numeric(frame[name], errors="coerce")
            for name in self.feature_columns
        }
        base = pd.DataFrame(values, index=frame.index)
        flags = {
            _missing_column_name(name): base[name].isna().astype("int8")
            for name in self.feature_columns
        }
        for name in self.feature_columns:
            base[name] = base[name].fillna(self.medians.get(name, 0.0))
        result = pd.concat([base, pd.DataFrame(flags, index=frame.index)], axis=1)
        return result.loc[:, list(self.output_columns)].reset_index(drop=True)


class StationMonthSource:
    """BatchSource 协议实现：按冻结 split 供给特征帧 + actual。"""

    def __init__(self, supervised: pd.DataFrame, feature_columns: Sequence[str]):
        self.base = supervised.reset_index(drop=True)
        self.schema_columns = tuple(self.base.columns)
        self.feature_columns = tuple(feature_columns)
        self.last_collection_audit: dict = {}

    def collect_split(self, split: str, feature_columns: Sequence[str] | None = None) -> pd.DataFrame:
        columns = list(feature_columns or self.feature_columns)
        if split not in {"train", "validation", "test"}:
            raise ValueError(f"split must be train/validation/test: {split!r}")
        frame = self.base.loc[self.base["dataset_split_frozen"] == split]
        frame = frame.dropna(subset=["actual"])
        months = pd.to_datetime(frame["month"] + "-01")
        self.last_collection_audit = {
            "split": split,
            "rows": int(len(frame)),
            "month_start": str(frame["month"].min()) if len(frame) else None,
            "month_end": str(frame["month"].max()) if len(frame) else None,
            "station_count": int(frame["station_id"].nunique()) if len(frame) else 0,
            "actual_nonfinite_dropped": int(
                (~np.isfinite(pd.to_numeric(frame["actual"], errors="coerce"))).sum()
            ),
        }
        if not len(frame):
            return pd.DataFrame(columns=[*columns, "actual"])
        out = frame.loc[:, list(dict.fromkeys((*columns, "actual", "month", "row_id")))].copy()
        out["month_order"] = months
        return out.sort_values("month_order", kind="mergesort").reset_index(drop=True)

    def iter_batches(self, split: str, columns: Sequence[str]) -> Iterator[pd.DataFrame]:
        yield self.collect_split(split, columns)


@dataclass
class ResidualIntervals:
    """split-conformal 残差区间：P05/P95 = 点预测 + 残差分位数。"""

    residual_p05: float
    residual_p95: float
    method: str = "split_conformal_residual_quantiles"
    coverage_target: float = 0.90
    calibration_n: int = 0
    calibration_source: str = "train_fold_out_of_fold_plus_validation"

    def apply(self, prediction: np.ndarray) -> pd.DataFrame:
        point = np.asarray(prediction, dtype=float)
        p05 = point + self.residual_p05
        p95 = point + self.residual_p95
        return pd.DataFrame({"p05": p05, "p95": p95})


@dataclass
class ModelBundleV3:
    """V0.3 推理 bundle：候选模型 + 冻结预处理器 + conformal 区间 + 元数据。"""

    run_id: str
    task_id: str
    variant: str
    target: str
    horizon_days: int
    month_offset: int
    granularity_tier: str
    problem_type: str
    primary_metric: str
    model: object
    preprocessor: RealPreprocessor
    feature_columns: tuple[str, ...]
    intervals: ResidualIntervals | None
    decision_threshold: float | None
    uncertainty_meta: dict
    selected_family: str
    validation_value: float | None
    test_metrics: dict
    data_version: str = DATA_VERSION_V3
    claim_boundary: str = CLAIM_BOUNDARY_V3
    seed: int = 0
    created_at: str = ""

    def predict_point(self, frame: pd.DataFrame) -> pd.DataFrame:
        features = self.preprocessor.transform(frame)
        return self.model.predict_frame(features)


def save_bundle(bundle: ModelBundleV3, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not bundle.created_at:
        bundle.created_at = datetime.now(timezone.utc).isoformat()
    path = out / f"{bundle.run_id}.joblib"
    joblib.dump(bundle, path)
    return path


def load_bundle(path: str | Path) -> ModelBundleV3:
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundleV3):
        raise ValueError(f"bundle at {path} is not a ModelBundleV3")
    return bundle


def frame_digest(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    values = pd.util.hash_pandas_object(
        frame.loc[:, sorted(frame.columns)], index=False
    )
    return hashlib.sha256(values.to_numpy(np.uint64).tobytes()).hexdigest()
