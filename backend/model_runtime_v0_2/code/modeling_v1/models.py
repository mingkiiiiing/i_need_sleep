"""Simple, Random Forest, and XGBoost candidate model factories."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier, XGBRegressor

from .contracts import DEFAULT_SEED, RISK_CLASSES, TaskSpec


MODEL_N_JOBS = int(os.environ.get("MODELING_V1_N_JOBS", "12"))


def physical_bounds(spec: TaskSpec) -> tuple[float | None, float | None]:
    """Return task-appropriate physical bounds used after every prediction."""
    if spec.target_family in {"bloom_probability", "bloom_coverage_ratio"}:
        return 0.0, 1.0
    if spec.problem_type == "binary":
        return 0.0, 1.0
    return 0.0, None


def _clip_values(values: np.ndarray, spec: TaskSpec) -> np.ndarray:
    lower, upper = physical_bounds(spec)
    if lower is not None:
        values = np.maximum(values, lower)
    if upper is not None:
        values = np.minimum(values, upper)
    return values


class BaseCandidate:
    """Common prediction contract for a fitted candidate."""

    name: str
    spec: TaskSpec
    feature_columns: tuple[str, ...]

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


@dataclass
class ConstantCandidate(BaseCandidate):
    name: str
    spec: TaskSpec
    feature_columns: tuple[str, ...]
    value: float = 0.0
    probability: float | None = None
    label: str | None = None

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        size = len(frame)
        out = pd.DataFrame(index=frame.index)
        if self.spec.problem_type == "binary":
            probability = float(self.probability if self.probability is not None else self.value)
            out["probability"] = np.full(size, probability)
            out["prediction"] = (out["probability"] >= 0.5).astype("int8")
        elif self.spec.problem_type == "ordinal":
            label = self.label or RISK_CLASSES[0]
            out["prediction"] = pd.Series([label] * size, index=frame.index)
        else:
            value = self.value
            out["prediction"] = np.full(
                size, _clip_values(np.asarray([value]), self.spec)[0]
            )
            if self.spec.problem_type == "probability":
                out["probability"] = out["prediction"].astype(float)
        return out


@dataclass
class SklearnCandidate(BaseCandidate):
    name: str
    spec: TaskSpec
    feature_columns: tuple[str, ...]
    estimator: object
    log1p_output: bool = False
    classes: tuple[str, ...] = ()
    decision_threshold: float = 0.5

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [name for name in self.feature_columns if name not in frame.columns]
        if missing:
            raise ValueError(f"prediction frame missing features: {missing}")
        x = frame.loc[:, list(self.feature_columns)].to_numpy(dtype=float)
        out = pd.DataFrame(index=frame.index)
        if self.spec.problem_type == "binary":
            probability = self.estimator.predict_proba(x)[:, 1]
            out["probability"] = probability
            out["prediction"] = (
                probability >= self.decision_threshold
            ).astype("int8")
        elif self.spec.problem_type == "ordinal":
            encoded = self.estimator.predict(x)
            out["prediction"] = pd.Series(
                [self.classes[int(value)] for value in encoded],
                index=frame.index,
            )
        else:
            raw = self.estimator.predict(x)
            if self.log1p_output:
                raw = np.expm1(raw)
            out["prediction"] = _clip_values(raw, self.spec)
            if self.spec.problem_type == "probability":
                out["probability"] = out["prediction"].astype(float)
        return out


def _class_order(values: pd.Series) -> tuple[str, ...]:
    observed = [str(value) for value in values.unique()]
    order = [name for name in RISK_CLASSES if name in observed]
    extra = sorted(set(observed) - set(RISK_CLASSES))
    return tuple(order + extra)


def fit_constant_candidate(
    name: str, spec: TaskSpec, train: pd.DataFrame, feature_columns: tuple[str, ...]
) -> ConstantCandidate:
    actual = pd.to_numeric(train["actual"], errors="coerce").dropna()
    if spec.problem_type in {"binary", "probability", "regression", "spatial"}:
        if spec.problem_type == "binary":
            probability = float((actual >= 0.5).mean()) if len(actual) else 0.0
            return ConstantCandidate(
                name=name,
                spec=spec,
                feature_columns=feature_columns,
                value=probability,
                probability=probability,
            )
        if spec.problem_type == "probability":
            value = float(actual.mean())
            return ConstantCandidate(
                name=name,
                spec=spec,
                feature_columns=feature_columns,
                value=value,
                probability=value,
            )
        value = float(actual.mean())
        return ConstantCandidate(
            name=name,
            spec=spec,
            feature_columns=feature_columns,
            value=value,
        )
    labels = train["actual"].dropna().astype(str)
    label = str(labels.mode().iloc[0]) if len(labels) else RISK_CLASSES[0]
    return ConstantCandidate(
        name=name,
        spec=spec,
        feature_columns=feature_columns,
        value=0.0,
        label=label,
    )


def _target_y(spec: TaskSpec, train: pd.DataFrame) -> np.ndarray:
    if spec.problem_type == "ordinal":
        return np.asarray(
            [str(value) for value in train["actual"]],
            dtype=object,
        )
    if spec.problem_type == "binary":
        y = pd.to_numeric(train["actual"], errors="raise").to_numpy()
        if not np.isin(y, (0.0, 1.0)).all():
            raise ValueError("binary training labels must be 0 or 1")
        return y
    y = pd.to_numeric(train["actual"], errors="raise").to_numpy()
    if spec.primary_metric == "log1p_mae":
        if (y < 0).any():
            raise ValueError("log1p density targets must be non-negative")
        return np.log1p(y)
    return y


def fit_sklearn_candidate(
    name: str,
    spec: TaskSpec,
    algorithm: str,
    train: pd.DataFrame,
    feature_columns: tuple[str, ...],
    *,
    seed: int = DEFAULT_SEED,
) -> SklearnCandidate:
    if algorithm not in {"random_forest", "xgboost"}:
        raise ValueError(f"unknown sklearn candidate algorithm: {algorithm}")
    x = train.loc[:, list(feature_columns)].to_numpy(dtype=float)
    y = _target_y(spec, train)
    classes: tuple[str, ...] = ()
    log1p_output = False
    if spec.problem_type == "ordinal":
        classes = _class_order(pd.Series(y))
        encoder = {label: index for index, label in enumerate(classes)}
        encoded_y = np.asarray([encoder[value] for value in y])
        if algorithm == "random_forest":
            estimator = RandomForestClassifier(
                n_estimators=120,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        else:
            estimator = XGBClassifier(
                n_estimators=120,
                max_depth=6,
                learning_rate=0.05,
                tree_method="hist",
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        estimator.fit(x, encoded_y)
    elif spec.problem_type == "binary":
        if algorithm == "random_forest":
            estimator = RandomForestClassifier(
                n_estimators=120,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        else:
            estimator = XGBClassifier(
                n_estimators=120,
                max_depth=6,
                learning_rate=0.05,
                tree_method="hist",
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        estimator.fit(x, y)
    else:
        if spec.primary_metric == "log1p_mae":
            log1p_output = True
        if algorithm == "random_forest":
            estimator = RandomForestRegressor(
                n_estimators=120,
                min_samples_leaf=2,
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        else:
            estimator = XGBRegressor(
                n_estimators=120,
                max_depth=6,
                learning_rate=0.05,
                tree_method="hist",
                n_jobs=MODEL_N_JOBS,
                random_state=seed,
            )
        estimator.fit(x, y)
    return SklearnCandidate(
        name=name,
        spec=spec,
        feature_columns=feature_columns,
        estimator=estimator,
        log1p_output=log1p_output,
        classes=classes,
    )


def candidate_factories(
    spec: TaskSpec,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Callable[[pd.DataFrame], BaseCandidate]]:
    """Return simple and pure-AI candidate factories for a task spec."""
    factories: dict[str, Callable[[pd.DataFrame], BaseCandidate]] = {}

    def make_constant(train: pd.DataFrame) -> ConstantCandidate:
        columns = tuple(
            name for name in train.columns if name not in {"actual", "dataset_split"}
        )
        return fit_constant_candidate("simple_baseline", spec, train, columns)

    factories["simple_baseline"] = make_constant

    def make_rf(train: pd.DataFrame) -> BaseCandidate:
        columns = tuple(
            name for name in train.columns if name not in {"actual", "dataset_split"}
        )
        return fit_sklearn_candidate(
            "random_forest", spec, "random_forest", train, columns, seed=seed
        )

    def make_xgb(train: pd.DataFrame) -> BaseCandidate:
        columns = tuple(
            name for name in train.columns if name not in {"actual", "dataset_split"}
        )
        return fit_sklearn_candidate(
            "xgboost", spec, "xgboost", train, columns, seed=seed
        )

    factories["random_forest"] = make_rf
    factories["xgboost"] = make_xgb
    return factories
