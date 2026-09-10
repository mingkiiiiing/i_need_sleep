"""V0.3 小样本训练管线：RF / XGBoost / 机理 / 三类融合 × 可训练任务 × 7 时效。

- 候选在 validation 上按主指标选择（frozen split：train≤2021 / val 2022-2023 / test≥2024）；
- 置信区间：split-conformal 残差分位数（train 折外 OOF + validation 残差池化，P05/P95），
  冻结测试集只报告经验覆盖率，不参与拟合；
- 断点续跑：run 目录已含 evaluation_manifest.json 时跳过。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from xgboost import XGBClassifier, XGBRegressor

from .contracts_real import (
    CLAIM_BOUNDARY_V3,
    DATA_VERSION_V3,
    DEFAULT_SEED_V3,
    HORIZON_MAP_V3,
    TaskSpecReal,
    run_id_real,
)
from .data_real import (
    ModelBundleV3 as Bundle,
    RealPreprocessor,
    ResidualIntervals,
    StationMonthSource,
    frame_digest,
    save_bundle,
)

HIGHER_IS_BETTER = {"macro_f1", "accuracy", "roc_auc", "pr_auc"}
MODEL_N_JOBS = 4


# ---------- 指标 ----------
def regression_metrics(actual: np.ndarray, prediction: np.ndarray) -> dict:
    true = np.asarray(actual, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    valid = np.isfinite(true) & np.isfinite(pred)
    true, pred = true[valid], pred[valid]
    if not len(true):
        return {"mae": None, "rmse": None, "r2": None, "log1p_mae": None, "n": 0}
    residual = true - pred
    ss_tot = float(np.sum((true - true.mean()) ** 2))
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "r2": None if ss_tot == 0 else float(1.0 - np.sum(residual**2) / ss_tot),
        # T3-density 声明的主指标（log1p 空间 MAE）；对 0-1 秩代理目标同样良定义
        "log1p_mae": float(np.mean(np.abs(np.log1p(np.maximum(true, 0.0)) - np.log1p(np.maximum(pred, 0.0))))),
        "n": int(len(true)),
    }


def _binary_counts(true: np.ndarray, decision: np.ndarray) -> dict:
    tp = float(np.sum((true == 1.0) & decision))
    fn = float(np.sum((true == 1.0) & ~decision))
    fp = float(np.sum((true == 0.0) & decision))
    return {"tp": int(tp), "fn": int(fn), "fp": int(fp)}


def probability_metrics(actual: np.ndarray, probability: np.ndarray) -> dict:
    true = np.asarray(actual, dtype=float)
    prob = np.nan_to_num(np.asarray(probability, dtype=float), nan=0.0)
    valid = np.isfinite(true)
    true, prob = np.clip(true[valid], 0.0, 1.0), np.clip(prob[valid], 0.0, 1.0)
    if not len(true):
        return {"brier_score": None, "roc_auc": None, "pr_auc": None, "recall": None, "n": 0}
    out = {
        "brier_score": float(np.mean((true - prob) ** 2)),
        "roc_auc": None,
        "pr_auc": None,
        "recall": None,
        "precision": None,
        "f1": None,
        "n": int(len(true)),
    }
    # 校准证据：期望校准误差（ECE，10 等宽桶）+ 分桶明细（预测置信 vs 实际频率）。
    # 单类样本也成立；roc/pr 仅在双类时可算。
    bin_idx = np.clip((prob * 10).astype(int), 0, 9)
    ece = 0.0
    calibration_bins = []
    for b in range(10):
        mask = bin_idx == b
        if not mask.any():
            continue
        conf = float(prob[mask].mean())
        obs = float(true[mask].mean())
        w = int(mask.sum())
        ece += (w / len(true)) * abs(obs - conf)
        calibration_bins.append({
            "bin": b,
            "mean_predicted": round(conf, 4),
            "observed_frequency": round(obs, 4),
            "n": w,
        })
    out["expected_calibration_error"] = round(float(ece), 6)
    out["calibration_bins"] = calibration_bins
    if true.min() == 0.0 and true.max() == 1.0:
        from sklearn.metrics import average_precision_score, roc_auc_score

        out["roc_auc"] = float(roc_auc_score(true, prob))
        out["pr_auc"] = float(average_precision_score(true, prob))
        counts = _binary_counts(true, prob >= 0.5)
        positives = float(np.sum(true == 1.0))
        recall = counts["tp"] / positives if positives else None
        precision = counts["tp"] / counts["tp"] if counts["tp"] + counts["fp"] else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else None
        )
        out.update({"recall": recall, "precision": precision, "f1": f1})
    return out


def ordinal_metrics(actual: np.ndarray, prediction: np.ndarray) -> dict:
    true = np.asarray([str(v) for v in actual], dtype=object)
    pred = np.asarray([str(v) for v in prediction], dtype=object)
    if not len(true):
        return {"macro_f1": None, "accuracy": None, "n": 0}
    classes = sorted(set(true.tolist()) | set(pred.tolist()))
    f1s = []
    for cls in classes:
        tp = float(np.sum((true == cls) & (pred == cls)))
        fp = float(np.sum((true != cls) & (pred == cls)))
        fn = float(np.sum((true == cls) & (pred != cls)))
        denom = 2 * tp + fp + fn
        f1s.append(2 * tp / denom if denom else 0.0)
    return {
        "macro_f1": float(np.mean(f1s)) if f1s else None,
        "accuracy": float(np.mean(true == pred)),
        "n": int(len(true)),
    }


def evaluate_real(spec: TaskSpecReal, actual, prediction, probability=None) -> dict:
    if spec.problem_type in {"binary", "probability"}:
        prob = probability if probability is not None else np.asarray(prediction, dtype=float)
        return probability_metrics(actual, prob)
    if spec.problem_type == "ordinal":
        return ordinal_metrics(actual, prediction)
    return regression_metrics(actual, prediction)


def _metric_direction(primary: str) -> str:
    return "max" if primary in HIGHER_IS_BETTER else "min"


# 非特征列（审计/标签/月份列），候选族选列时统一剔除
_NON_FEATURE_COLUMNS = frozenset({
    "actual", "month", "month_order", "row_id", "station_id", "dataset_split_frozen",
})


def _primary_value(metrics: dict, spec: TaskSpecReal) -> float | None:
    value = metrics.get(spec.primary_metric)
    if value is None and spec.primary_metric == "macro_f1":
        value = metrics.get("accuracy")
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


# ---------- 候选模型 ----------
class ConstantCandidateReal:
    name = "simple_baseline"

    def __init__(self, spec: TaskSpecReal, value: float, label: str | None = None):
        self.spec = spec
        self.value = float(value)
        self.label = label

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        size = len(frame)
        if self.spec.problem_type in {"binary", "probability"}:
            prob = np.full(size, np.clip(self.value, 0.0, 1.0))
            return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
        if self.spec.problem_type == "ordinal":
            return pd.DataFrame({"prediction": pd.Series([self.label] * size, index=frame.index)})
        return pd.DataFrame({"prediction": np.full(size, max(self.value, 0.0))})


class SklearnCandidateReal:
    name = "sklearn"

    def __init__(self, name: str, spec: TaskSpecReal, estimator, feature_columns, single_class_value=None):
        self.name = name
        self.spec = spec
        self.estimator = estimator
        self.feature_columns = tuple(feature_columns)
        self.single_class_value = single_class_value

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in self.feature_columns if c not in frame.columns]
        if missing:
            raise ValueError(f"prediction frame missing features: {missing}")
        if self.single_class_value is not None:
            size = len(frame)
            if self.spec.problem_type in {"binary", "probability"}:
                prob = np.full(size, float(self.single_class_value))
                return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
            if self.spec.problem_type == "ordinal":
                return pd.DataFrame({"prediction": pd.Series([self.single_class_value] * size, index=frame.index)})
            return pd.DataFrame({"prediction": np.full(size, float(self.single_class_value))})
        x = frame.loc[:, list(self.feature_columns)].to_numpy(dtype=float)
        if self.spec.problem_type in {"binary", "probability"} and hasattr(self.estimator, "predict_proba"):
            prob = self.estimator.predict_proba(x)[:, 1]
            return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
        if self.spec.problem_type == "ordinal":
            encoded = self.estimator.predict(x)
            return pd.DataFrame({"prediction": pd.Series(
                [self.classes[int(v)] for v in encoded], index=frame.index
            )})
        pred = np.maximum(np.asarray(self.estimator.predict(x), dtype=float), 0.0)
        if self.spec.problem_type == "probability":
            pred = np.clip(pred, 0.0, 1.0)
        return pd.DataFrame({"prediction": pred})


MECH_DESIGN_BASE = (
    "mech_temperature_factor", "mech_light_factor", "mech_phosphorus_factor",
    "mech_nitrogen_factor", "mech_nutrient_factor", "mech_net_growth_rate_d",
    "wq_tp", "wq_tn", "wq_do", "wq_nh4_n", "wq_phyto_biomass",
    "met_air_temperature_c", "met_shortwave_radiation_wm2",
    "hydro_water_level_m", "calendar_month_sin", "calendar_month_cos",
)


def _mechanism_design(frame: pd.DataFrame) -> pd.DataFrame:
    design = pd.DataFrame(index=frame.index)
    for column in MECH_DESIGN_BASE:
        if column in frame.columns:
            design[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            # 任务级剔除列（如 biomass 任务的 wq_phyto_biomass）：置 NaN，HistGB 原生支持
            design[column] = np.nan
    chla = (
        pd.to_numeric(frame["wq_chla"], errors="coerce")
        if "wq_chla" in frame.columns
        else pd.Series(0.0, index=frame.index)
    )
    design["log1p_wq_chla"] = np.log1p(np.maximum(chla, 0.0))
    return design


class MechanismCandidateReal:
    name = "mechanism"

    def __init__(self, spec: TaskSpecReal, model, feature_columns: tuple[str, ...],
                 classes: tuple[str, ...] = (), constant: float | None = None):
        self.spec = spec
        self.model = model
        self.feature_columns = feature_columns
        self.classes = classes
        self.constant = constant

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        design = _mechanism_design(frame)
        if self.constant is not None:
            size = len(frame)
            if self.spec.problem_type in {"binary", "probability"}:
                prob = np.full(size, np.clip(self.constant, 0.0, 1.0))
                return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
            if self.spec.problem_type == "ordinal":
                return pd.DataFrame({"prediction": pd.Series([self.classes[0]] * size, index=frame.index)})
            return pd.DataFrame({"prediction": np.full(size, max(self.constant, 0.0))})
        x = design.loc[:, list(self.feature_columns)].to_numpy(dtype=float)
        if self.spec.problem_type in {"binary", "probability"}:
            prob = self.model.predict_proba(x)[:, 1]
            return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
        if self.spec.problem_type == "ordinal":
            ranks = np.clip(np.rint(self.model.predict(x)).astype(int), 0, len(self.classes) - 1)
            return pd.DataFrame({"prediction": pd.Series(
                [self.classes[int(v)] for v in ranks], index=frame.index
            )})
        pred = np.maximum(np.asarray(self.model.predict(x), dtype=float), 0.0)
        if self.spec.problem_type == "probability":
            pred = np.clip(pred, 0.0, 1.0)
        return pd.DataFrame({"prediction": pred})


class MechanismFeatureCandidateReal:
    name = "mechanism_feature"

    def __init__(self, spec: TaskSpecReal, mechanism: MechanismCandidateReal, ai: SklearnCandidateReal):
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai
        self.feature_columns = ai.feature_columns

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        augmented = frame.copy()
        mech_out = self.mechanism.predict_frame(frame)
        column = "probability" if "probability" in mech_out.columns else "prediction"
        augmented["mechanism_prediction"] = mech_out[column].to_numpy(dtype=float)
        return self.ai.predict_frame(augmented)


class ResidualCandidateReal:
    name = "residual"

    def __init__(self, spec: TaskSpecReal, mechanism: MechanismCandidateReal, ai: SklearnCandidateReal):
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        mech_value = _mech_values(self.mechanism, frame)
        augmented = frame.copy()
        mech_out = self.mechanism.predict_frame(frame)
        column = "probability" if "probability" in mech_out.columns else "prediction"
        augmented["mechanism_prediction"] = mech_out[column].to_numpy(dtype=float)
        residual = self.ai.predict_frame(augmented)["prediction"].to_numpy(dtype=float)
        raw = mech_value + residual
        raw = np.maximum(raw, 0.0)
        if self.spec.problem_type in {"binary", "probability"}:
            raw = np.clip(raw, 0.0, 1.0)
        out = pd.DataFrame({"prediction": raw})
        if self.spec.problem_type in {"binary", "probability"}:
            out["probability"] = raw
        return out


class ConstrainedBlendCandidateReal:
    name = "constrained_blend"

    def __init__(self, spec: TaskSpecReal, mechanism: MechanismCandidateReal, ai: SklearnCandidateReal, weight: float):
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai
        self.weight = float(weight)

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        mech_value = _mech_values(self.mechanism, frame)
        ai_out = self.ai.predict_frame(frame)
        ai_column = "probability" if "probability" in ai_out.columns else "prediction"
        ai_value = ai_out[ai_column].to_numpy(dtype=float)
        if self.spec.problem_type == "ordinal":
            selected = np.where(self.weight >= 0.5, mech_value, ai_value)
            return pd.DataFrame({"prediction": selected})
        raw = self.weight * mech_value + (1.0 - self.weight) * ai_value
        raw = np.maximum(raw, 0.0)
        if self.spec.problem_type in {"binary", "probability"}:
            raw = np.clip(raw, 0.0, 1.0)
        out = pd.DataFrame({"prediction": raw})
        if self.spec.problem_type in {"binary", "probability"}:
            out["probability"] = raw
        return out


# ---------- 候选工厂 ----------
def _fit_single_class_guard(spec: TaskSpecReal, y: np.ndarray):
    # probability 任务同样可能只有单类训练标签（如代理阳性极稀有），退化为先验常数
    if spec.problem_type in {"binary", "ordinal", "probability"}:
        unique = pd.unique(pd.Series(y).astype(str))
        if len(unique) < 2:
            return str(unique[0]) if len(unique) else "none"
    return None


def _fit_ai(spec: TaskSpecReal, algorithm: str, features: pd.DataFrame, columns, seed: int) -> SklearnCandidateReal:
    x = features.loc[:, list(columns)].to_numpy(dtype=float)
    if spec.problem_type in {"binary", "probability"}:
        y = pd.to_numeric(features["actual"], errors="coerce").to_numpy()
        guard = _fit_single_class_guard(spec, y)
        if guard is not None:
            return SklearnCandidateReal(algorithm, spec, None, columns, single_class_value=guard)
        if algorithm == "random_forest":
            estimator = RandomForestClassifier(
                n_estimators=200, min_samples_leaf=2,
                class_weight="balanced_subsample", n_jobs=MODEL_N_JOBS, random_state=seed,
            )
        else:
            estimator = XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                tree_method="hist", n_jobs=MODEL_N_JOBS, random_state=seed,
            )
        estimator.fit(x, y)
        return SklearnCandidateReal(algorithm, spec, estimator, columns)
    if spec.problem_type == "ordinal":
        labels = features["actual"].astype(str)
        classes = tuple(sorted(labels.unique()))
        encoder = {name: index for index, name in enumerate(classes)}
        y = np.asarray([encoder[v] for v in labels])
        if algorithm == "random_forest":
            estimator = RandomForestClassifier(
                n_estimators=200, min_samples_leaf=2,
                class_weight="balanced_subsample", n_jobs=MODEL_N_JOBS, random_state=seed,
            )
        else:
            estimator = XGBClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                tree_method="hist", n_jobs=MODEL_N_JOBS, random_state=seed,
            )
        estimator.fit(x, y)
        candidate = SklearnCandidateReal(algorithm, spec, estimator, columns)
        candidate.classes = classes
        return candidate
    y = pd.to_numeric(features["actual"], errors="coerce").to_numpy()
    if algorithm == "random_forest":
        estimator = RandomForestRegressor(
            n_estimators=200, min_samples_leaf=2, n_jobs=MODEL_N_JOBS, random_state=seed,
        )
    else:
        estimator = XGBRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            tree_method="hist", n_jobs=MODEL_N_JOBS, random_state=seed,
        )
    estimator.fit(x, y)
    return SklearnCandidateReal(algorithm, spec, estimator, columns)


def _fit_mechanism(spec: TaskSpecReal, features: pd.DataFrame, seed: int) -> MechanismCandidateReal:
    design = _mechanism_design(features)
    x = design.to_numpy(dtype=float)
    valid = np.isfinite(x).all(axis=1)
    if valid.sum() < 10:
        if spec.problem_type in {"binary", "probability"}:
            prior = float(np.nanmean(pd.to_numeric(features["actual"], errors="coerce")))
            return MechanismCandidateReal(spec, None, tuple(design.columns), constant=prior)
        if spec.problem_type == "ordinal":
            mode = str(features["actual"].astype(str).mode().iloc[0])
            return MechanismCandidateReal(spec, None, tuple(design.columns), classes=(mode,), constant=0.0)
        mean = float(np.nanmean(pd.to_numeric(features["actual"], errors="coerce")))
        return MechanismCandidateReal(spec, None, tuple(design.columns), constant=mean)
    x, features = x[valid], features.loc[valid]
    if spec.problem_type in {"binary", "probability"}:
        y = pd.to_numeric(features["actual"], errors="coerce").to_numpy()
        if np.unique(y).size < 2:
            return MechanismCandidateReal(spec, None, tuple(design.columns), constant=float(y[0]))
        model = HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.05, max_leaf_nodes=8,
            min_samples_leaf=5, random_state=seed,
        ).fit(x, y)
        return MechanismCandidateReal(spec, model, tuple(design.columns))
    if spec.problem_type == "ordinal":
        labels = features["actual"].astype(str)
        classes = tuple(sorted(labels.unique()))
        encoder = {name: index for index, name in enumerate(classes)}
        y = np.asarray([encoder[v] for v in labels])
        model = HistGradientBoostingRegressor(
            max_iter=150, learning_rate=0.05, max_leaf_nodes=8,
            min_samples_leaf=5, random_state=seed,
        ).fit(x, y)
        return MechanismCandidateReal(spec, model, tuple(design.columns), classes=classes)
    y = pd.to_numeric(features["actual"], errors="coerce").to_numpy()
    model = HistGradientBoostingRegressor(
        max_iter=150, learning_rate=0.05, max_leaf_nodes=8,
        min_samples_leaf=5, random_state=seed,
    ).fit(x, y)
    return MechanismCandidateReal(spec, model, tuple(design.columns))


def _augmented(features: pd.DataFrame, mechanism: MechanismCandidateReal) -> pd.DataFrame:
    out = features.copy()
    mech_out = mechanism.predict_frame(features)
    column = "probability" if "probability" in mech_out.columns else "prediction"
    out["mechanism_prediction"] = mech_out[column].to_numpy(dtype=float)
    return out


def _mech_values(candidate: MechanismCandidateReal, frame: pd.DataFrame) -> np.ndarray:
    """机制族点值：probability 任务输出 probability 列，其余取 prediction。"""
    out = candidate.predict_frame(frame)
    column = "probability" if "probability" in out.columns else "prediction"
    return out[column].to_numpy(dtype=float)


def _fit_fusion(name: str, spec: TaskSpecReal, train: pd.DataFrame, validation: pd.DataFrame | None, seed: int):
    mechanism = _fit_mechanism(spec, train, seed)
    if name == "mechanism_feature":
        augmented = _augmented(train, mechanism)
        columns = tuple(c for c in augmented.columns if c not in _NON_FEATURE_COLUMNS)
        ai = _fit_ai(spec, "random_forest", augmented, columns, seed)
        return MechanismFeatureCandidateReal(spec, mechanism, ai)
    if name == "residual":
        mech_value = _mech_values(mechanism, train)
        actual = pd.to_numeric(train["actual"], errors="coerce").to_numpy()
        residual = actual - mech_value
        augmented = _augmented(train, mechanism).assign(actual=residual)
        columns = tuple(c for c in augmented.columns if c not in _NON_FEATURE_COLUMNS)
        ai = _fit_ai(spec, "random_forest", augmented, columns, seed)
        return ResidualCandidateReal(spec, mechanism, ai)
    # constrained_blend
    columns = tuple(c for c in train.columns if c not in _NON_FEATURE_COLUMNS)
    ai = _fit_ai(spec, "xgboost", train, columns, seed)
    weight = 0.5
    if validation is not None and len(validation):
        mech_validation = _mech_values(mechanism, validation)
        ai_out = ai.predict_frame(validation)
        ai_column = "probability" if "probability" in ai_out.columns else "prediction"
        ai_validation = ai_out[ai_column].to_numpy(dtype=float)
        actual_validation = pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
        best = None
        for candidate in (0.0, 0.25, 0.5, 0.75, 1.0):
            blended = np.clip(candidate * mech_validation + (1 - candidate) * ai_validation, 0.0, 1.0) \
                if spec.problem_type in {"binary", "probability"} \
                else np.maximum(candidate * mech_validation + (1 - candidate) * ai_validation, 0.0)
            error = float(np.mean((actual_validation - blended) ** 2))
            if best is None or error < best[0]:
                best = (error, candidate)
        weight = best[1]
    return ConstrainedBlendCandidateReal(spec, mechanism, ai, weight)


def candidate_factories_real(spec: TaskSpecReal, seed: int) -> dict[str, Callable]:
    def simple(train, validation=None):
        actual = pd.to_numeric(train["actual"], errors="coerce").dropna()
        if spec.problem_type in {"binary", "probability"}:
            return ConstantCandidateReal(spec, float(actual.mean()) if len(actual) else 0.0)
        if spec.problem_type == "ordinal":
            mode = str(actual.astype(str).mode().iloc[0]) if len(actual) else "none"
            return ConstantCandidateReal(spec, 0.0, label=mode)
        return ConstantCandidateReal(spec, float(actual.mean()) if len(actual) else 0.0)

    def rf(train, validation=None):
        columns = tuple(c for c in train.columns if c not in _NON_FEATURE_COLUMNS)
        return _fit_ai(spec, "random_forest", train, columns, seed)

    def xgb(train, validation=None):
        columns = tuple(c for c in train.columns if c not in _NON_FEATURE_COLUMNS)
        return _fit_ai(spec, "xgboost", train, columns, seed)

    def mech(train, validation=None):
        return _fit_mechanism(spec, train, seed)

    def mech_feature(train, validation=None):
        return _fit_fusion("mechanism_feature", spec, train, validation, seed)

    def residual(train, validation=None):
        return _fit_fusion("residual", spec, train, validation, seed)

    def blend(train, validation=None):
        return _fit_fusion("constrained_blend", spec, train, validation, seed)

    factories = {
        "simple_baseline": simple, "random_forest": rf, "xgboost": xgb, "mechanism": mech,
        "mechanism_feature": mech_feature, "residual": residual, "constrained_blend": blend,
    }
    if spec.problem_type == "ordinal":
        factories.pop("residual", None)
    return factories


FUSION_FAMILIES = ("mechanism_feature", "residual", "constrained_blend")
SINGLE_AI_FAMILIES = ("random_forest", "xgboost")


def _predict_output(candidate, features: pd.DataFrame, spec: TaskSpecReal) -> pd.DataFrame:
    out = candidate.predict_frame(features)
    if "probability" not in out.columns:
        out["probability"] = pd.to_numeric(out["prediction"], errors="coerce")
    return out


# ---------- 训练主流程 ----------
def _write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _fit_oof_residuals(
    train: pd.DataFrame, source: StationMonthSource, spec: TaskSpecReal,
    selected: str, factories: dict, preprocessor: RealPreprocessor, seed: int,
) -> np.ndarray:
    """时间递增 2 折折外残差（仅用 train，防测试集信息泄漏）。"""
    residuals = np.empty(0)
    months = np.sort(train["month"].unique())
    if len(months) < 3:
        return residuals
    cut = months[max(2, int(len(months) * 0.7))]
    early = train[train["month"] < cut]
    late = train[train["month"] >= cut]
    if len(early) < 5 or len(late) < 3:
        return residuals
    try:
        early_features = preprocessor.transform(early)
        late_features = preprocessor.transform(late)
        candidate = factories[selected](early, None)
        predicted = _predict_output(candidate, late_features, spec)
        actual = pd.to_numeric(late["actual"], errors="coerce").to_numpy()
        pred_values = (
            predicted["probability"].to_numpy(dtype=float)
            if spec.problem_type in {"binary", "probability"}
            else predicted["prediction"].to_numpy(dtype=float)
        )
        residuals = actual - pred_values
        residuals = residuals[np.isfinite(residuals)]
    except Exception:  # noqa: BLE001 — OOF 失败时仅用 validation 残差
        return np.empty(0)
    return residuals


def train_run_real(
    spec: TaskSpecReal,
    horizon_days: int,
    source: StationMonthSource,
    output_dir: str | Path,
    *,
    seed: int = DEFAULT_SEED_V3,
    data_manifest: dict | None = None,
) -> dict:
    """训练一个 (task, horizon) run 并落盘全部产物；返回摘要 dict。"""
    if horizon_days not in HORIZON_MAP_V3.month_map:
        raise ValueError(f"unsupported horizon: {horizon_days}")
    month_offset = HORIZON_MAP_V3.month_offset(horizon_days)
    run_id = run_id_real(spec.task_id, spec.variant, month_offset, seed)
    output = Path(output_dir)
    if (output / "evaluation_manifest.json").is_file():
        return {"run_id": run_id, "status": "skipped_completed"}
    output.mkdir(parents=True, exist_ok=True)
    run_config = {
        "run_id": run_id,
        "task_id": spec.task_id,
        "variant": spec.variant,
        "problem_type": spec.problem_type,
        "primary_metric": spec.primary_metric,
        "horizon_days": int(horizon_days),
        "month_offset": int(month_offset),
        "granularity_tier": HORIZON_MAP_V3.tier(horizon_days),
        "seed": seed,
        "data_version": CLAIM_BOUNDARY_V3 and data_manifest.get("data_version"),
        "claim_boundary": CLAIM_BOUNDARY_V3,
        "label_provenance": spec.label_provenance,
    }
    _write_json(run_config, output / "run_config.json")

    train = source.collect_split("train")
    validation = source.collect_split("validation")
    if not len(train) or not len(validation):
        raise ValueError(f"{run_id}: train/validation frames are empty")
    preprocessor = RealPreprocessor.fit(train, source.feature_columns)
    train_features = preprocessor.transform(train).assign(actual=train["actual"].to_numpy())
    train_features["month_order"] = train["month_order"].to_numpy()
    train_features["month"] = train["month"].to_numpy()
    validation_features = preprocessor.transform(validation).assign(actual=validation["actual"].to_numpy())
    validation_features["month_order"] = validation["month_order"].to_numpy()

    factories = candidate_factories_real(spec, seed)
    validation_metrics: dict[str, dict] = {}
    candidates: dict[str, object] = {}
    for name, factory in factories.items():
        try:
            candidate = factory(train_features, validation_features)
            predicted = _predict_output(
                candidate, validation_features.loc[:, list(preprocessor.output_columns)], spec
            )
        except Exception as exc:  # noqa: BLE001 — 单候选失败不阻断其它候选
            validation_metrics[name] = {"error": str(exc), "primary": None}
            continue
        actual = pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
        prob = predicted["probability"].to_numpy(dtype=float) if spec.problem_type in {"binary", "probability"} else None
        pred = predicted["prediction"].to_numpy()
        metrics = evaluate_real(spec, actual, pred, prob)
        metrics["primary"] = _primary_value(metrics, spec)
        validation_metrics[name] = metrics
        candidates[name] = candidate

    scored = {
        name: metrics["primary"]
        for name, metrics in validation_metrics.items()
        if metrics.get("primary") is not None
    }
    if not scored:
        raise ValueError(f"{run_id}: no candidate produced a usable validation primary metric")
    direction = _metric_direction(spec.primary_metric)
    selected = (max if direction == "max" else min)(scored, key=lambda name: scored[name])

    selection_manifest = {
        "run_id": run_id,
        "selected_family": selected,
        "validation_primary_metric": spec.primary_metric,
        "validation_value": scored[selected],
        "validation_metrics_by_family": validation_metrics,
        "feature_sha256": frame_digest(train_features.drop(columns=["month_order"])),
        "seed": seed,
        "claim_boundary": CLAIM_BOUNDARY_V3,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(selection_manifest, output / "selection_manifest.json")

    # ---- conformal 区间（train OOF + validation 残差池化；测试集不参与） ----
    selected_validation_pred = _predict_output(
        candidates[selected], validation_features.loc[:, list(preprocessor.output_columns)], spec
    )
    # 序数任务（风险等级带）的预测是字符串标签，没有数值残差可池化——跳过 conformal。
    if spec.problem_type in {"binary", "probability"}:
        val_point = selected_validation_pred["probability"].to_numpy(dtype=float)
    elif spec.problem_type == "regression":
        val_point = selected_validation_pred["prediction"].to_numpy(dtype=float)
    else:
        val_point = None
    val_actual = pd.to_numeric(validation["actual"], errors="coerce").to_numpy()
    val_residuals = (val_actual - val_point) if val_point is not None else np.empty(0)
    oof_residuals = _fit_oof_residuals(
        train_features, source, spec, selected, factories, preprocessor, seed
    )
    parts = [r[np.isfinite(r)] for r in (oof_residuals, val_residuals) if len(r)]
    pooled = np.concatenate(parts) if parts else np.empty(0)
    intervals = None
    if spec.problem_type in {"regression", "probability", "binary"} and len(pooled):
        intervals = ResidualIntervals(
            residual_p05=float(np.quantile(pooled, 0.05)),
            residual_p95=float(np.quantile(pooled, 0.95)),
            calibration_n=int(len(pooled)),
        )

    # ---- 冻结测试集评估（n 披露，不用于任何拟合/选择） ----
    test = source.collect_split("test")
    test_metrics_by_family: dict[str, dict] = {}
    selected_test_frame: pd.DataFrame | None = None
    selected_test_point: np.ndarray | None = None
    if len(test):
        test_features = preprocessor.transform(test)
        for name, candidate in candidates.items():
            try:
                predicted = _predict_output(candidate, test_features, spec)
            except Exception as exc:  # noqa: BLE001
                test_metrics_by_family[name] = {"error": str(exc)}
                continue
            actual = pd.to_numeric(test["actual"], errors="coerce").to_numpy()
            prob = predicted["probability"].to_numpy(dtype=float) if spec.problem_type in {"binary", "probability"} else None
            metrics = evaluate_real(spec, actual, predicted["prediction"].to_numpy(), prob)
            test_metrics_by_family[name] = metrics
            if name == selected:
                selected_test_frame = predicted.assign(
                    actual=actual, month=test["month"].to_numpy(), row_id=test["row_id"].to_numpy()
                )
                selected_test_point = (
                    predicted["probability"].to_numpy(dtype=float)
                    if spec.problem_type in {"binary", "probability"}
                    else (
                        predicted["prediction"].to_numpy(dtype=float)
                        if spec.problem_type == "regression"
                        else None  # 序数任务预测是标签字符串，无数值点/覆盖率可言
                    )
                )
        if selected_test_frame is not None:
            selected_test_frame.to_csv(output / "test_predictions.csv", index=False)
    _write_json(test_metrics_by_family, output / "test_metrics_by_family.json")

    empirical_coverage_test = None
    if intervals is not None and selected_test_point is not None and len(selected_test_point):
        actual_test = pd.to_numeric(test["actual"], errors="coerce").to_numpy()
        covered = (actual_test >= selected_test_point + intervals.residual_p05) & (
            actual_test <= selected_test_point + intervals.residual_p95
        )
        empirical_coverage_test = float(np.mean(covered))

    uncertainty_meta = {
        "method": "split_conformal_residual_quantiles",
        "is_calibrated_confidence_interval": intervals is not None,
        "coverage_target": 0.90,
        "residual_quantile_levels": [0.05, 0.95],
        "calibration_n": int(len(pooled)),
        "calibration_source": "train_expanding_fold_oof_plus_validation_residuals",
        "empirical_coverage_test": empirical_coverage_test,
        "test_n": int(len(test)),
    }
    _write_json(uncertainty_meta, output / "uncertainty.json")

    bundle = Bundle(
        run_id=run_id,
        task_id=spec.task_id,
        variant=spec.variant,
        target=spec.label_family,
        horizon_days=int(horizon_days),
        month_offset=int(month_offset),
        granularity_tier=HORIZON_MAP_V3.tier(horizon_days),
        problem_type=spec.problem_type,
        primary_metric=spec.primary_metric,
        model=candidates[selected],
        preprocessor=preprocessor,
        feature_columns=preprocessor.feature_columns,
        intervals=intervals,
        decision_threshold=None,
        uncertainty_meta=uncertainty_meta,
        selected_family=selected,
        validation_value=scored[selected],
        test_metrics=test_metrics_by_family.get(selected, {}),
        seed=seed,
    )
    save_bundle(bundle, output.parent.parent / "models")

    evaluation_manifest = {
        "run_id": run_id,
        "selected_family": selected,
        "test_rows": int(len(test)),
        "test_primary_metric": spec.primary_metric,
        "test_value": test_metrics_by_family.get(selected, {}).get(spec.primary_metric),
        "test_metrics_by_family": test_metrics_by_family,
        "uncertainty": uncertainty_meta,
        "claim_boundary": CLAIM_BOUNDARY_V3,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(evaluation_manifest, output / "evaluation_manifest.json")
    return {
        "run_id": run_id,
        "status": "trained",
        "selected_family": selected,
        "validation_value": scored[selected],
        "test_rows": int(len(test)),
        "test_value": evaluation_manifest["test_value"],
        "calibration_n": int(len(pooled)),
        "empirical_coverage_test": empirical_coverage_test,
    }
