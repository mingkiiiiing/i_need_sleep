"""Probability calibration, prediction intervals, and interval diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .data import LearnedPreprocessor


@dataclass(frozen=True)
class ProbabilityCalibrator:
    calibrator: object
    fit_split: str = "validation"

    def calibrate(self, probabilities) -> np.ndarray:
        values = np.asarray(probabilities, dtype=float)
        return np.clip(self.calibrator.predict(values), 0.0, 1.0)


def fit_probability_calibrator(
    frame: pd.DataFrame,
    *,
    score_column: str = "probability",
    label_column: str = "actual",
    fit_split: str = "validation",
) -> ProbabilityCalibrator:
    """Fit an isotonic calibrator on a validation-only frame."""
    if fit_split != "validation":
        raise ValueError("calibration accepts validation batches only")
    missing = [
        name
        for name in (score_column, label_column)
        if name not in frame.columns
    ]
    if missing:
        raise ValueError(f"calibration frame missing columns: {missing}")
    scores = pd.to_numeric(frame[score_column], errors="coerce")
    labels = pd.to_numeric(frame[label_column], errors="coerce")
    valid = scores.notna() & labels.notna()
    if not valid.any():
        raise ValueError("calibration frame has no valid score/label pairs")
    if not labels.loc[valid].isin([0.0, 1.0]).all():
        raise ValueError("calibration labels must be binary")
    calibrator = IsotonicRegression(out_of_bounds="clip", increasing=True)
    calibrator.fit(scores.loc[valid].to_numpy(), labels.loc[valid].to_numpy())
    return ProbabilityCalibrator(calibrator=calibrator, fit_split=fit_split)


@dataclass
class PredictionIntervals:
    residual_quantiles: tuple[float, float, float, float]
    model: object | None = None
    feature_columns: tuple[str, ...] | None = None

    def predict_frame(
        self,
        frame: pd.DataFrame,
        *,
        prediction: pd.Series | np.ndarray | None = None,
    ) -> pd.DataFrame:
        if prediction is None:
            if self.model is None:
                raise ValueError("interval estimator requires point predictions")
            if self.feature_columns is None:
                feature_columns = [
                    name
                    for name in frame.columns
                    if pd.api.types.is_numeric_dtype(frame[name])
                ]
            else:
                feature_columns = list(self.feature_columns)
            point = np.asarray(
                self.model.predict(
                    frame.loc[:, feature_columns].to_numpy(dtype=float)
                ),
                dtype=float,
            )
        else:
            point = np.asarray(prediction, dtype=float)
        lower_q, upper_q = self.residual_quantiles[:2], self.residual_quantiles[2:]
        lower_95 = point + lower_q[0]
        lower_80 = point + lower_q[1]
        upper_80 = point + upper_q[0]
        upper_95 = point + upper_q[1]
        # Residual quantiles are ordered [2.5, 10, 90, 97.5], so overlapping
        # intervals are monotone by construction.
        return pd.DataFrame(
            {
                "prediction": point,
                "lower_95": np.minimum(lower_95, lower_80),
                "lower_80": np.minimum(lower_80, point),
                "upper_80": np.maximum(upper_80, point),
                "upper_95": np.maximum(upper_95, upper_80),
            },
            index=frame.index,
        )


def _residual_quantiles(residuals: np.ndarray) -> tuple[float, float, float, float]:
    return tuple(
        float(value)
        for value in np.quantile(
            residuals, [0.025, 0.10, 0.90, 0.975]
        )
    )


def fit_prediction_intervals(
    model,
    validation: pd.DataFrame,
    *,
    feature_columns=None,
    target_column: str = "actual",
) -> PredictionIntervals:
    """Fit split-conformal residual intervals on the validation split."""
    if target_column not in validation.columns:
        raise ValueError(f"validation frame missing target column: {target_column}")
    if feature_columns is None:
        if hasattr(model, "feature_names_in_"):
            feature_columns = list(model.feature_names_in_)
        elif hasattr(model, "feature_columns"):
            feature_columns = list(model.feature_columns)
        else:
            feature_columns = [
                name
                for name in validation.columns
                if name not in {"actual", "dataset_split", "prediction", "probability"}
            ]
    x = validation.loc[:, list(feature_columns)]
    if isinstance(x, pd.DataFrame):
        values = x.to_numpy(dtype=float)
    else:
        values = np.asarray(x, dtype=float)
    point = np.asarray(model.predict(values), dtype=float)
    actual = pd.to_numeric(validation[target_column], errors="coerce").to_numpy()
    valid = np.isfinite(point) & np.isfinite(actual)
    if not valid.any():
        raise ValueError("interval fitting has no finite validation samples")
    residuals = actual[valid] - point[valid]
    return PredictionIntervals(
        _residual_quantiles(residuals),
        model=model,
        feature_columns=tuple(feature_columns),
    )


def predict_intervals(
    model_or_intervals,
    frame: pd.DataFrame,
    *,
    prediction=None,
) -> pd.DataFrame:
    """Predict ordered 80/95 intervals for a fitted model or interval object."""
    if isinstance(model_or_intervals, PredictionIntervals):
        return model_or_intervals.predict_frame(frame, prediction=prediction)
    if prediction is None:
        model = model_or_intervals
        if hasattr(model, "predict"):
            values = frame.to_numpy(dtype=float)
            point = np.asarray(model.predict(values), dtype=float)
        else:
            point = np.asarray(
                model.predict_frame(frame)["prediction"], dtype=float
            )
    else:
        point = np.asarray(prediction, dtype=float)
    if hasattr(model_or_intervals, "_codex_validation_residuals_"):
        residuals = np.asarray(model_or_intervals._codex_validation_residuals_)
        quantiles = _residual_quantiles(residuals)
    else:
        # Deterministic fallback for models with no validation residual state.
        scale = 0.10 * np.abs(point) + 0.10
        quantiles = (-1.96 * scale, -1.28 * scale, 1.28 * scale, 1.96 * scale)
    intervals = PredictionIntervals(quantiles)
    return intervals.predict_frame(frame, prediction=point)


def interval_diagnostics(
    out: pd.DataFrame,
    actual,
) -> dict[str, float | int]:
    """Report interval coverage and mean width for regression targets."""
    required = {
        "prediction",
        "lower_80",
        "upper_80",
        "lower_95",
        "upper_95",
    }
    missing = sorted(required - set(out.columns))
    if missing:
        raise ValueError(f"interval frame missing columns: {missing}")
    true = pd.to_numeric(actual, errors="coerce").to_numpy()
    valid = np.isfinite(true)
    true = true[valid]
    if not len(true):
        raise ValueError("interval diagnostics require finite actual values")
    subset = out.loc[valid]
    cover_80 = float(
        ((subset["lower_80"].to_numpy() <= true) & (true <= subset["upper_80"].to_numpy())).mean()
    )
    cover_95 = float(
        ((subset["lower_95"].to_numpy() <= true) & (true <= subset["upper_95"].to_numpy())).mean()
    )
    return {
        "coverage_80": cover_80,
        "coverage_95": cover_95,
        "mean_width_80": float(np.mean(subset["upper_80"] - subset["lower_80"])),
        "mean_width_95": float(np.mean(subset["upper_95"] - subset["lower_95"])),
        "sample_count": int(len(true)),
    }
