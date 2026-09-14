"""Mechanism-feature, residual, and constrained weighted fusion candidates."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .contracts import DEFAULT_SEED, TaskSpec
from .mechanism_adapter import (
    MechanismCandidate,
    fit_mechanism,
    mechanism_feature_frame,
)
from .models import (
    BaseCandidate,
    candidate_factories as ai_candidate_factories,
    fit_sklearn_candidate,
    physical_bounds,
)


class MechanismFeatureCandidate(BaseCandidate):
    """AI trained with the frozen mechanism prediction as an extra feature."""

    def __init__(self, name, spec, mechanism, ai, feature_columns):
        self.name = name
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai
        self.feature_columns = feature_columns

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        augmented = mechanism_feature_frame(frame, self.mechanism, self.spec)
        return self.ai.predict_frame(augmented)


class ResidualCandidate(BaseCandidate):
    """AI learns the residual between the mechanism output and target."""

    def __init__(self, name, spec, mechanism, ai):
        self.name = name
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai
        self.feature_columns = ai.feature_columns

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        mechanism_output = self.mechanism.predict_frame(frame)
        residual_input = mechanism_feature_frame(frame, self.mechanism, self.spec)
        residual_output = self.ai.predict_frame(residual_input)
        if self.spec.problem_type == "binary":
            probability = np.clip(
                mechanism_output["probability"].to_numpy(dtype=float)
                + residual_output["prediction"].to_numpy(dtype=float),
                0.0,
                1.0,
            )
            out = pd.DataFrame(
                {
                    "probability": probability,
                    "prediction": (probability >= 0.5).astype("int8"),
                },
                index=frame.index,
            )
            return out
        mechanism_values = mechanism_output["prediction"].to_numpy(dtype=float)
        residual_values = residual_output["prediction"].to_numpy(dtype=float)
        if self.spec.primary_metric == "log1p_mae":
            mechanism_log = np.log1p(np.maximum(mechanism_values, 0.0))
            raw = np.expm1(
                np.clip(
                    mechanism_log + residual_values,
                    -50.0,
                    50.0,
                )
            )
        else:
            raw = mechanism_values + residual_values
        lower, upper = physical_bounds(self.spec)
        raw = np.maximum(raw, lower if lower is not None else -np.inf)
        if upper is not None:
            raw = np.minimum(raw, upper)
        out = pd.DataFrame({"prediction": raw}, index=frame.index)
        if self.spec.problem_type == "probability":
            out["probability"] = out["prediction"]
        return out


class ConstrainedBlendCandidate(BaseCandidate):
    """Validation-selected weighted blend with physical clipping."""

    def __init__(self, name, spec, mechanism, ai, weight, ordinal_mode=False):
        self.name = name
        self.spec = spec
        self.mechanism = mechanism
        self.ai = ai
        self.weight = float(weight)
        self.ordinal_mode = ordinal_mode
        self.feature_columns = ai.feature_columns

    def predict_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        mechanism_output = self.mechanism.predict_frame(frame)
        ai_output = self.ai.predict_frame(frame)
        if self.spec.problem_type == "ordinal" or self.ordinal_mode:
            mechanism_label = mechanism_output["prediction"].to_numpy()
            ai_label = ai_output["prediction"].to_numpy()
            selected = np.where(
                self.weight >= 0.5,
                mechanism_label,
                ai_label,
            )
            return pd.DataFrame({"prediction": selected}, index=frame.index)
        if self.spec.problem_type == "binary":
            probability = (
                self.weight
                * mechanism_output["probability"].to_numpy(dtype=float)
                + (1.0 - self.weight)
                * ai_output["probability"].to_numpy(dtype=float)
            )
            out = pd.DataFrame(
                {
                    "probability": np.clip(probability, 0.0, 1.0),
                    "prediction": (probability >= 0.5).astype("int8"),
                },
                index=frame.index,
            )
            return out
        mechanism_values = mechanism_output["prediction"].to_numpy(dtype=float)
        ai_values = ai_output["prediction"].to_numpy(dtype=float)
        if self.spec.primary_metric == "log1p_mae":
            mechanism_log = np.log1p(np.maximum(mechanism_values, 0.0))
            ai_log = np.log1p(np.maximum(ai_values, 0.0))
            raw = np.expm1(
                self.weight * mechanism_log + (1.0 - self.weight) * ai_log
            )
        else:
            raw = self.weight * mechanism_values + (1.0 - self.weight) * ai_values
        lower, upper = physical_bounds(self.spec)
        raw = np.maximum(raw, lower if lower is not None else -np.inf)
        if upper is not None:
            raw = np.minimum(raw, upper)
        out = pd.DataFrame({"prediction": raw}, index=frame.index)
        if self.spec.problem_type == "probability":
            out["probability"] = out["prediction"]
        return out


def _weight_error(
    actual,
    mechanism_output: pd.DataFrame,
    ai_output: pd.DataFrame,
    spec: TaskSpec,
    weight: float,
) -> float:
    if spec.problem_type in {"binary", "probability"}:
        mechanism = mechanism_output["probability"].to_numpy(dtype=float)
        ai = ai_output["probability"].to_numpy(dtype=float)
        blended = np.clip(weight * mechanism + (1.0 - weight) * ai, 0.0, 1.0)
        if spec.problem_type == "binary":
            return float(np.mean((actual - blended) ** 2))
        return float(np.mean((actual - blended) ** 2))
    if spec.problem_type == "ordinal":
        mechanism_labels = mechanism_output["prediction"].to_numpy()
        ai_labels = ai_output["prediction"].to_numpy()
        labels = np.where(weight >= 0.5, mechanism_labels, ai_labels)
        return float(np.mean(labels != np.asarray(actual, dtype=object)))
    mechanism = mechanism_output["prediction"].to_numpy(dtype=float)
    ai = ai_output["prediction"].to_numpy(dtype=float)
    actual_values = np.asarray(actual, dtype=float)
    if spec.primary_metric == "log1p_mae":
        mechanism_log = np.log1p(np.maximum(mechanism, 0.0))
        ai_log = np.log1p(np.maximum(ai, 0.0))
        blended_log = weight * mechanism_log + (1.0 - weight) * ai_log
        return float(np.mean((np.log1p(np.maximum(actual_values, 0.0)) - blended_log) ** 2))
    blended = weight * mechanism + (1.0 - weight) * ai
    return float(np.mean((actual_values - blended) ** 2))


def fit_mechanism_feature_fusion(
    train: pd.DataFrame,
    validation: pd.DataFrame | None,
    spec: TaskSpec,
    *,
    seed: int = DEFAULT_SEED,
    horizon_days: int = 1,
) -> MechanismFeatureCandidate:
    mechanism = fit_mechanism(train, spec, horizon_days=horizon_days)
    augmented_train = mechanism_feature_frame(train, mechanism, spec)
    feature_columns = tuple(
        name
        for name in augmented_train.columns
        if name not in {"actual", "dataset_split"}
    )
    ai = fit_sklearn_candidate(
        "mechanism_feature_ai",
        spec,
        "random_forest",
        augmented_train,
        feature_columns,
        seed=seed,
    )
    return MechanismFeatureCandidate(
        "mechanism_feature",
        spec,
        mechanism,
        ai,
        feature_columns,
    )


def fit_residual_fusion(
    train: pd.DataFrame,
    validation: pd.DataFrame | None,
    spec: TaskSpec,
    *,
    seed: int = DEFAULT_SEED,
    horizon_days: int = 1,
) -> ResidualCandidate:
    mechanism = fit_mechanism(train, spec, horizon_days=horizon_days)
    mechanism_train = mechanism.predict_frame(train)
    residual_input_train = mechanism_feature_frame(
        train, mechanism, spec
    )
    feature_columns = tuple(
        name
        for name in residual_input_train.columns
        if name not in {"actual", "dataset_split"}
    )
    actual = train["actual"].to_numpy()
    mechanism_value = mechanism_train["prediction"].to_numpy(dtype=float)
    if spec.primary_metric == "log1p_mae":
        mechanism_log = np.log1p(np.maximum(mechanism_value, 0.0))
        actual_log = np.log1p(np.maximum(actual, 0.0))
        residual = actual_log - mechanism_log
    else:
        residual = actual - mechanism_value
    residual_frame = residual_input_train.assign(actual=residual)
    residual_spec = replace(spec, problem_type="regression", primary_metric="mae")
    ai = fit_sklearn_candidate(
        "residual_ai",
        residual_spec,
        "random_forest",
        residual_frame,
        feature_columns,
        seed=seed,
    )
    residual_candidate = ResidualCandidate("residual", spec, mechanism, ai)
    residual_candidate.feature_columns = feature_columns
    return residual_candidate


def fit_constrained_blend(
    train: pd.DataFrame,
    validation: pd.DataFrame | None,
    spec: TaskSpec,
    *,
    seed: int = DEFAULT_SEED,
    frozen_weight: float | None = None,
    horizon_days: int = 1,
) -> ConstrainedBlendCandidate:
    if frozen_weight is not None:
        if validation is not None:
            raise ValueError('frozen weight cannot be combined with validation')
        if not np.isfinite(frozen_weight) or not 0 <= frozen_weight <= 1:
            raise ValueError('frozen weight must be in [0, 1]')
    mechanism = fit_mechanism(train, spec, horizon_days=horizon_days)
    feature_columns = tuple(
        name for name in train.columns if name not in {"actual", "dataset_split"}
    )
    ai = fit_sklearn_candidate(
        "blend_ai",
        spec,
        "xgboost",
        train,
        feature_columns,
        seed=seed,
    )
    weight = 0.5 if frozen_weight is None else float(frozen_weight)
    if validation is not None and len(validation):
        mechanism_validation = mechanism.predict_frame(validation)
        ai_validation = ai.predict_frame(validation)
        actual_validation = validation["actual"].to_numpy()
        candidates = [0.0, 0.25, 0.5, 0.75, 1.0]
        errors = [
            (
                _weight_error(
                    actual_validation,
                    mechanism_validation,
                    ai_validation,
                    spec,
                    candidate,
                ),
                candidate,
            )
            for candidate in candidates
        ]
        weight = min(errors, key=lambda item: item[0])[1]
    return ConstrainedBlendCandidate(
        "constrained_blend",
        spec,
        mechanism,
        ai,
        weight,
        ordinal_mode=spec.problem_type == "ordinal",
    )


def candidate_factories(
    spec: TaskSpec,
    *,
    seed: int = DEFAULT_SEED,
    horizon_days: int = 1,
) -> dict[str, object]:
    """Return all candidate names and lazy factories for one task spec."""
    ai = ai_candidate_factories(spec, seed=seed)
    factories: dict[str, object] = dict(ai)

    def mechanism(train, validation=None):
        return fit_mechanism(train, spec, horizon_days=horizon_days)

    def mechanism_feature(train, validation=None):
        return fit_mechanism_feature_fusion(
            train,
            validation,
            spec,
            seed=seed,
            horizon_days=horizon_days,
        )

    def residual(train, validation=None):
        return fit_residual_fusion(
            train,
            validation,
            spec,
            seed=seed,
            horizon_days=horizon_days,
        )

    def constrained_blend(train, validation=None, *, frozen_weight=None):
        return fit_constrained_blend(
            train,
            validation,
            spec,
            seed=seed,
            frozen_weight=frozen_weight,
            horizon_days=horizon_days,
        )

    factories["mechanism_feature"] = mechanism_feature
    factories["residual"] = residual
    factories["constrained_blend"] = constrained_blend
    factories["mechanism"] = mechanism
    return factories
