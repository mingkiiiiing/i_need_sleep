"""Loadable model bundles and reproducible offline batch prediction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .data import LearnedPreprocessor, transform_batch


@dataclass
class ModelBundle:
    model: object
    preprocessor: LearnedPreprocessor | None
    feature_columns: tuple[str, ...]
    feature_units: dict[str, str]
    target: str
    horizon_days: int
    task_id: str
    data_version: str
    claim_boundary: str
    calibrator: object | None = None
    intervals: object | None = None
    decision_threshold: float | None = None


def _unit_mismatch(
    bundle: ModelBundle, frame: pd.DataFrame
) -> str | None:
    frame_columns = {str(name) for name in frame.columns}
    for feature in bundle.feature_columns:
        if feature in frame_columns:
            continue
        expected = bundle.feature_units.get(feature, "")
        if expected in {"mg_L", "ug_L"}:
            base = feature.removesuffix(f"_{expected}")
            candidates = [
                name
                for name in frame_columns
                if name.removesuffix("_mg_L").removesuffix("_ug_L") == base
            ]
            if candidates:
                return (
                    f"unit mismatch for {base}: expected {expected}, "
                    f"got {'/'.join(sorted(candidates))}"
                )
    return None


def predict_batch(bundle: ModelBundle, frame: pd.DataFrame) -> pd.DataFrame:
    """Apply a frozen bundle to one valid input batch."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("predict_batch requires a non-empty DataFrame")
    missing = [
        name for name in bundle.feature_columns if name not in frame.columns
    ]
    if missing:
        unit_error = _unit_mismatch(bundle, frame)
        if unit_error is not None:
            raise ValueError(unit_error)
        raise ValueError(f"input missing required feature columns: {missing}")
    if bundle.preprocessor is not None:
        features = transform_batch(bundle.preprocessor, frame)
        feature_frame = features.loc[:, list(bundle.preprocessor.output_columns)]
    else:
        feature_frame = frame.loc[:, list(bundle.feature_columns)]

    if hasattr(bundle.model, "predict_frame"):
        model_output = bundle.model.predict_frame(feature_frame)
        prediction = model_output["prediction"].to_numpy()
        probability = (
            model_output["probability"].to_numpy()
            if "probability" in model_output.columns
            else None
        )
    else:
        prediction = bundle.model.predict(
            feature_frame.to_numpy(dtype=float)
        )
        probability = None

    out = pd.DataFrame(
        {
            "prediction": np.asarray(prediction).ravel(),
            "target": bundle.target,
            "horizon_days": int(bundle.horizon_days),
            "task_id": bundle.task_id,
            "data_version": bundle.data_version,
            "claim_boundary": bundle.claim_boundary,
        },
        index=frame.index,
    )
    if probability is not None:
        out["probability"] = np.asarray(probability).ravel()
    if bundle.calibrator is not None and "probability" in out.columns:
        out["probability"] = bundle.calibrator.calibrate(out["probability"])
    if (
        bundle.decision_threshold is not None
        and "probability" in out.columns
    ):
        out["prediction"] = (
            out["probability"] >= float(bundle.decision_threshold)
        ).astype("int8")
    if bundle.intervals is not None:
        interval_output = bundle.intervals.predict_frame(
            feature_frame, prediction=out["prediction"]
        )
        for column in (
            "lower_95",
            "lower_80",
            "upper_80",
            "upper_95",
        ):
            out[column] = interval_output[column].to_numpy()
    return out


def save_bundle(bundle: ModelBundle, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "bundle.joblib"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return path


def load_bundle(path: str | Path) -> ModelBundle:
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundle):
        raise ValueError("bundle file does not contain a ModelBundle")
    return bundle
