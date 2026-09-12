"""V0.3 小样本训练管线：RF / XGBoost / 机理 / 三类融合 × 可训练任务 × 7 时效。

- 候选在 validation 上按主指标选择（frozen split：train≤2021 / val 2022-2023 / test≥2024）；
- 置信区间：split-conformal 残差分位数（train 折外 OOF + validation 残差池化，P05/P95），
  冻结测试集只报告经验覆盖率，不参与拟合；
- 断点续跑：run 目录已含 evaluation_manifest.json 时跳过。
"""
from __future__ import annotations

import dataclasses
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
    BLOOM_THRESHOLD_UG_L,
    CLAIM_BOUNDARY_V3,
    DATA_VERSION_V3,
    DEFAULT_SEED_V3,
    HORIZON_MAP_V3,
    TARGET_SOURCE_FEATURE_EXCLUSIONS,
    TaskSpecReal,
    artifact_id_real,
    protocol_of_run,
    run_id_real,
)
from .data_real import (
    ModelBundleV3 as Bundle,
    RealPreprocessor,
    ResidualIntervals,
    StationMonthSource,
    bundle_slot_filename,
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
        predicted_positive = counts["tp"] + counts["fp"]
        recall = counts["tp"] / positives if positives else None
        # 查准率 = tp/(tp+fp)。此处原先写成 tp/tp：分母取了 tp+fp 判断非零、分子却是 tp，
        # 于是「有正预测但零真阳性」（补训协议引入真实测试段后必然出现）触发除零。
        precision = counts["tp"] / predicted_positive if predicted_positive else None
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


def eval_actual_values(frame: pd.DataFrame, spec: TaskSpecReal) -> np.ndarray:
    """评估用真值（L-diag-02 修复）：序数任务的标签是等级字符串（none/low/…），
    必须原样进入 ordinal_metrics——旧评估循环统一 pd.to_numeric(errors="coerce")
    会把整列转成 NaN，ordinal_metrics 再 str() 出幻影类 'nan'，与任何预测类不相交，
    macro_f1=accuracy=0（L-gate-35/37/39/41/42 假 FAIL 的根因）。数值任务口径不变。
    """
    if spec.problem_type == "ordinal":
        return frame["actual"].astype(str).to_numpy(dtype=object)
    return pd.to_numeric(frame["actual"], errors="coerce").to_numpy()


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


def _frame_month_num(frame: pd.DataFrame) -> np.ndarray:
    """由目标月日历正余弦还原月份（1-12）；无法还原时返回 0（调用方回退全局统计）。"""
    sin = pd.to_numeric(frame.get("calendar_month_sin"), errors="coerce").to_numpy(dtype=float)
    cos = pd.to_numeric(frame.get("calendar_month_cos"), errors="coerce").to_numpy(dtype=float)
    angle = np.arctan2(sin, cos)
    month = np.rint((np.mod(angle, 2.0 * np.pi)) * 12.0 / (2.0 * np.pi)).astype(int) + 1
    month = np.where(np.isfinite(sin) & np.isfinite(cos) & ((np.abs(sin) + np.abs(cos)) > 1e-6), month, 0)
    month = np.clip(month, 0, 12)
    return month


class ClimatologyCandidateReal:
    """月气候态基线：训练期「目标月份 → actual 均值/众数」（全湖口径，可回测）。

    serving 帧无站点身份，故为全局月气候态；它是中长期趋势必须超越的最低基线。
    """

    name = "climatology_global"

    def __init__(self, spec: TaskSpecReal, by_month: dict, fallback):
        self.spec = spec
        self.by_month = dict(by_month)
        self.fallback = fallback

    @classmethod
    def fit(cls, spec: TaskSpecReal, train: pd.DataFrame) -> "ClimatologyCandidateReal":
        months = _frame_month_num(train)
        actual = train["actual"]
        if spec.problem_type == "ordinal":
            labels = actual.astype(str)
            by_month = {
                int(m): str(labels[months == m].mode().iloc[0])
                for m in sorted(set(months) - {0}) if (months == m).sum() >= 1 and len(labels[months == m].mode())
            }
            fallback = str(labels.mode().iloc[0]) if len(labels.mode()) else "none"
        else:
            values = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=float)
            by_month = {
                int(m): float(np.nanmean(values[months == m]))
                for m in sorted(set(months) - {0}) if np.isfinite(values[months == m]).any()
            }
            fallback = float(np.nanmean(values)) if np.isfinite(values).any() else 0.0
        return cls(spec, by_month, fallback)

    def _values(self, frame: pd.DataFrame) -> np.ndarray:
        months = _frame_month_num(frame)
        return np.asarray([self.by_month.get(int(m), self.fallback) for m in months], dtype=object)

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        values = self._values(frame)
        if self.spec.problem_type == "ordinal":
            return pd.DataFrame({"prediction": pd.Series(list(values), index=frame.index)})
        numeric = np.asarray(values, dtype=float)
        if self.spec.problem_type in {"binary", "probability"}:
            prob = np.clip(numeric, 0.0, 1.0)
            return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
        return pd.DataFrame({"prediction": np.maximum(numeric, 0.0)})


class PersistenceCandidateReal:
    """持续性基线：目标 = 当月实测（chla 家族用 wq_chla），可回测。

    仅 month_offset≥1（当月实测相对目标月为历史量）且特征含 wq_chla 时注册。
    probability/binary 口径：当月实测已越阈则概率 1，否则 0（朴素但可回测）。
    """

    name = "persistence"

    def __init__(self, spec: TaskSpecReal, source_column: str = "wq_chla",
                 bloom_threshold: float = BLOOM_THRESHOLD_UG_L):
        self.spec = spec
        self.source_column = source_column
        self.bloom_threshold = float(bloom_threshold)

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        current = pd.to_numeric(frame[self.source_column], errors="coerce").to_numpy(dtype=float)
        if self.spec.problem_type in {"binary", "probability"}:
            prob = np.where(np.isfinite(current), (current >= self.bloom_threshold).astype(float), np.nan)
            prob = np.nan_to_num(prob, nan=0.0)
            return pd.DataFrame({"probability": prob, "prediction": (prob >= 0.5).astype("int8")})
        pred = np.maximum(np.nan_to_num(current, nan=0.0), 0.0)
        return pd.DataFrame({"prediction": pred})


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


def _mechanism_design(frame: pd.DataFrame, spec: TaskSpecReal | None = None) -> pd.DataFrame:
    """机理设计矩阵；任务级目标同源剔除列直接收缩出列集（L-data-02 修复）。

    剔除契约 TARGET_SOURCE_FEATURE_EXCLUSIONS（如 biomass/density 任务的
    wq_phyto_biomass）防止的是"目标本身当特征"的同月泄漏——它约束的是特征侧，
    不应该连坐机理设计矩阵：旧实现把缺席列置 NaN，而 _fit_mechanism 的行有效性门
    要求全部列逐行有限，于是 T3/T4 全部 576 行被判无效（valid=0）→ 机理支路必然
    常数回退（台账 L-diag-01 的退化路径）。正确口径：剔除列从设计矩阵收缩掉，
    行有效性按剩余机理列判定；机理列本身在目标任务里照常可用。
    spec=None 时保持旧口径（缺席列置 NaN），兼容无任务上下文的调用。
    """
    excluded = set(TARGET_SOURCE_FEATURE_EXCLUSIONS.get(spec.label_family, ())) if spec is not None else set()
    design = pd.DataFrame(index=frame.index)
    for column in MECH_DESIGN_BASE:
        if column in excluded:
            continue
        if column in frame.columns:
            design[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            # 非任务级剔除、仅是本帧未携带的列：置 NaN，HistGB 原生支持
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
        design = _mechanism_design(frame, self.spec)
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
        # 与训练侧共用 _augmented：序数任务的等级标签编码口径必须完全一致，
        # 否则拟合时看到的是序号、推理时喂进去的是标签，模型输入口径两套。
        return self.ai.predict_frame(_augmented(frame, self.mechanism))


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
        ai_out = self.ai.predict_frame(frame)
        ai_column = "probability" if "probability" in ai_out.columns else "prediction"
        if self.spec.problem_type == "ordinal":
            # 序数任务：两条支路都是等级标签，按权重在标签上取一（不存在"标签相加"）
            mech_labels = _mech_values(self.mechanism, frame)
            ai_labels = ai_out[ai_column].astype(str).to_numpy(dtype=object)
            selected = np.where(self.weight >= 0.5, mech_labels, ai_labels)
            return pd.DataFrame({"prediction": pd.Series(selected, index=frame.index)})
        mech_value = _mech_values(self.mechanism, frame)
        ai_value = ai_out[ai_column].to_numpy(dtype=float)
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
    design = _mechanism_design(features, spec)
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
    """特征 + 机制点值列。序数任务的机制输出是等级标签，须用等级序号数值化后入模型。

    这是融合族在风险等级上可训练的唯一前提：直接 to_numpy(dtype=float) 会因标签是
    字符串（如 'none'）而抛错，融合族因此从 test_metrics 里整族缺席。
    """
    out = features.copy()
    mech_out = mechanism.predict_frame(features)
    column = "probability" if "probability" in mech_out.columns else "prediction"
    if mechanism.spec.problem_type == "ordinal":
        out["mechanism_prediction"] = _ordinal_rank_encode(mechanism.classes, mech_out[column])
    else:
        out["mechanism_prediction"] = mech_out[column].to_numpy(dtype=float)
    return out


def _mech_values(candidate: MechanismCandidateReal, frame: pd.DataFrame) -> np.ndarray:
    """机制族点值：probability 任务输出 probability 列，其余取 prediction。

    序数任务（风险等级带）的输出是等级标签，必须原样返回字符串——转 float 会直接抛错，
    这正是"融合族在风险等级上全军覆没、门禁只能记 NA"的根因。
    """
    out = candidate.predict_frame(frame)
    column = "probability" if "probability" in out.columns else "prediction"
    if candidate.spec.problem_type == "ordinal":
        return out[column].astype(str).to_numpy(dtype=object)
    return out[column].to_numpy(dtype=float)


def _ordinal_rank_encode(classes: tuple[str, ...], values: pd.Series) -> np.ndarray:
    """等级标签 → 等级序号（保序）。未知标签落到 0，与 _fit_mechanism 内部编码一致。"""
    order = {name: index for index, name in enumerate(classes or ())}
    return values.astype(str).map(lambda v: float(order.get(v, 0))).to_numpy(dtype=float)


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
        if spec.problem_type in {"binary", "probability"}:
            # 残差是连续量：二阶段必须用回归器拟合（2026-09-12 修复）。此前把
            # binary spec 原样传给 _fit_ai，classifier.fit 收到连续残差直接抛
            # "Unknown label type: continuous"——binary 任务的 residual 融合族
            # 因此从未成功过。predict 侧同样用回归口径输出，再由
            # ResidualCandidateReal 截断回 [0,1]。
            regression_spec = dataclasses.replace(spec, problem_type="regression")
            ai = _fit_ai(regression_spec, "random_forest", augmented, columns, seed)
        else:
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
        if spec.problem_type == "ordinal":
            # 序数：候选权重在"选机制标签还是选 AI 标签"之间择一，用分类错误率挑
            ai_validation = ai_out[ai_column].astype(str).to_numpy(dtype=object)
            actual_validation = validation["actual"].astype(str).to_numpy(dtype=object)
            best = None
            for candidate in (0.0, 0.25, 0.5, 0.75, 1.0):
                blended = np.where(candidate >= 0.5, mech_validation, ai_validation)
                error = float(np.mean(actual_validation != blended))
                if best is None or error < best[0]:
                    best = (error, candidate)
            weight = best[1]
        else:
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


def candidate_factories_real(
    spec: TaskSpecReal,
    seed: int,
    month_offset: int = 0,
    climatology_history: pd.DataFrame | None = None,
) -> dict[str, Callable]:
    """候选族工厂。

    climatology_history：月气候态的拟合样本。缺省用当前 run 的拟合段——但对 month_offset≥1
    的中长期 run，拟合段可能只有几十行且目标月高度集中，据此估出的月气候态退化成"几乎全 0
    的查表"，等于没有基线可比。此时调用方应传入该任务的**历史标签序列**（目标月严格早于
    留出测试段，无前视），让气候态基线建立在真实季节循环上，再拿去和模型同台比较。
    """
    def simple(train, validation=None):
        if spec.problem_type == "ordinal":
            # 序数标签是字符串，不能走 to_numeric（全 NaN → 众数兜底成 "none" 的假口径）
            labels = train["actual"].astype(str)
            mode = str(labels.mode().iloc[0]) if len(labels) else "none"
            return ConstantCandidateReal(spec, 0.0, label=mode)
        actual = pd.to_numeric(train["actual"], errors="coerce").dropna()
        if spec.problem_type in {"binary", "probability"}:
            return ConstantCandidateReal(spec, float(actual.mean()) if len(actual) else 0.0)
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

    def climatology(train, validation=None):
        history = climatology_history if climatology_history is not None and len(climatology_history) > len(train) else train
        return ClimatologyCandidateReal.fit(spec, history)

    factories = {
        "simple_baseline": simple, "climatology_global": climatology,
        "random_forest": rf, "xgboost": xgb, "mechanism": mech,
        "mechanism_feature": mech_feature, "residual": residual, "constrained_blend": blend,
    }
    # 持续性基线：仅 month_offset≥1（当月实测相对目标月为历史量，特征契约此时
    # 才并入 wq_chla）且 chla/bloom 家族注册。month_offset=0 时预测帧没有
    # wq_chla 列，注册必然后 predict 阶段 KeyError（2026-09-12 补上漏查的条件）。
    if spec.label_family in {"chla", "bloom"} and spec.problem_type != "ordinal" and month_offset >= 1:
        def persistence(train, validation=None):
            return PersistenceCandidateReal(spec)

        factories["persistence"] = persistence
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
    if spec.problem_type == "ordinal":
        # 序数任务的预测是等级标签，无数值残差可池化（conformal 对 ordinal 不适用）
        return residuals
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
    protocol_tag: str = "",
    climatology_history: pd.DataFrame | None = None,
) -> dict:
    """训练一个 (task, horizon) run 并落盘全部产物；返回摘要 dict。

    protocol_tag：写入 run_id 的协议标记（补训协议传 "cv"），使同一槽位在不同协议下的
    评估记录可区分。模型仍写固定槽位文件名，保证推理侧一槽一份、不看巧合。
    climatology_history：月气候态基线的拟合样本（见 candidate_factories_real）。
    """
    if horizon_days not in HORIZON_MAP_V3.month_map:
        raise ValueError(f"unsupported horizon: {horizon_days}")
    month_offset = HORIZON_MAP_V3.month_offset(horizon_days)
    run_id = run_id_real(spec.task_id, spec.variant, month_offset, seed, protocol_tag)
    output = Path(output_dir)
    if (output / "evaluation_manifest.json").is_file():
        return {"run_id": run_id, "status": "skipped_completed"}
    output.mkdir(parents=True, exist_ok=True)
    # 标签来源必须由监督表逐行 actual_provenance 汇总得出，不能用任务配置的声明值顶替
    # （T5 的 567 行 T+90 标签全部来自 chla_station_proxy_v1，声明 ground_truth 与事实不符）。
    from .target_builder import provenance_summary

    provenance = provenance_summary(source.base, spec.label_provenance)
    protocol = protocol_of_run(protocol_tag)
    artifact_id = artifact_id_real(
        spec.task_id, spec.variant, month_offset, horizon_days, seed, protocol
    )
    run_config = {
        "run_id": run_id,
        "artifact_id": artifact_id,
        "protocol": protocol,
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
        # 权威口径：逐行 actual_provenance 汇总
        "label_provenance": provenance["observed"],
        "label_provenance_declared": provenance["declared"],
        "label_provenance_breakdown": provenance["breakdown"],
        "label_provenance_rows": provenance["rows"],
        "label_provenance_unresolved_rows": provenance["unresolved_rows"],
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

    factories = candidate_factories_real(
        spec, seed, month_offset=month_offset, climatology_history=climatology_history,
    )
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
        actual = eval_actual_values(validation, spec)
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
            actual = eval_actual_values(test, spec)
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
    save_bundle(
        bundle,
        output.parent.parent / "models",
        filename=bundle_slot_filename(spec.task_id, spec.variant, month_offset, horizon_days, seed),
    )

    evaluation_manifest = {
        "run_id": run_id,
        "artifact_id": artifact_id,
        "protocol": protocol,
        "label_provenance": provenance["observed"],
        "label_provenance_declared": provenance["declared"],
        "label_provenance_breakdown": provenance["breakdown"],
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
