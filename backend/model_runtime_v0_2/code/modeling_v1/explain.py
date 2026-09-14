"""Permutation/SHAP attribution, driver grouping, and sensitivity analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from .contracts import FEATURE_GROUPS


MECHANISM_PRIORS: dict[str, str] = {
    "water_temperature_C": "non_monotonic_expected",
    "total_phosphorus_mg_L": "positive",
    "total_nitrogen_mg_L": "positive",
    "solar_radiation_MJ_m2_day": "positive",
    "wind_speed_m_s": "negative",
    "flow_speed_m_s": "negative",
    "mixing_index": "negative",
    "water_level_m": "mixed",
}


def _default_grouping(column: str) -> str:
    lowered = str(column).lower()
    for group, members in FEATURE_GROUPS.items():
        for member in members:
            if column == member:
                return group
            member_key = str(member).lower()
            if lowered.startswith(member_key) and (
                lowered.startswith((member_key + "_lag_", member_key + "_rolling_"))
                or lowered == member_key + "_missing"
                or (
                    lowered.startswith(member_key + "_change_")
                    and lowered.endswith(("_1d", "_7d"))
                )
            ):
                return group
    if "_lag_" in lowered or "_rolling_" in lowered or lowered.endswith("_missing"):
        stem = lowered.split("_lag_", 1)[0].split("_rolling_", 1)[0]
        return f"unmapped:{stem}"
    return "unmapped"


def grouped_driver_ranking(
    field_importance: Mapping[str, float],
    field_group: Mapping[str, str] | None = None,
) -> dict[str, float]:
    """Roll current/lag/rolling/missing fields up into driver groups."""
    grouped: dict[str, float] = {}
    for field, importance in field_importance.items():
        group = (
            field_group.get(field)
            if field_group is not None
            else _default_grouping(field)
        )
        if group is None:
            group = "unmapped"
        grouped[group] = grouped.get(group, 0.0) + float(importance)
    return dict(sorted(grouped.items(), key=lambda item: item[1], reverse=True))


def _feature_matrix(frame: pd.DataFrame, feature_columns: Sequence[str]) -> np.ndarray:
    missing = [name for name in feature_columns if name not in frame.columns]
    if missing:
        raise ValueError(f"explanation frame missing features: {missing}")
    return frame.loc[:, list(feature_columns)].to_numpy(dtype=float)


def global_importance(
    model,
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    target: Sequence[float] | None = None,
    sample_size: int | None = 5000,
    random_state: int = 20260907,
) -> dict[str, object]:
    """Permutation importance plus SHAP tree attribution when supported."""
    x = _feature_matrix(frame, feature_columns)
    if sample_size is not None and len(x) > sample_size:
        indices = np.random.default_rng(random_state).choice(
            len(x), size=sample_size, replace=False
        )
        x = x[indices]
        if target is not None:
            target = np.asarray(target)[indices]
    scorer = None
    importance = permutation_importance(
        model,
        x,
        target if target is not None else np.zeros(len(x)),
        n_repeats=5,
        random_state=random_state,
    )
    field_importance = {
        name: float(value)
        for name, value in zip(feature_columns, importance.importances_mean)
    }
    return {
        "permutation_importance": field_importance,
        "grouped_importance": grouped_driver_ranking(field_importance),
        "feature_columns": list(feature_columns),
    }


def local_shap_cases(
    model,
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    n_cases: int = 20,
    random_state: int = 20260907,
) -> pd.DataFrame:
    """Return SHAP values for deterministic representative cases."""
    from shap import Explainer

    x = _feature_matrix(frame, feature_columns)
    if len(x) > n_cases:
        indices = np.random.default_rng(random_state).choice(
            len(x), size=n_cases, replace=False
        )
        x = x[indices]
    try:
        explainer = Explainer(model, x)
        values = explainer(x).values
    except Exception:
        raise ValueError("SHAP explainer is unavailable for this model")
    if hasattr(values, "shape") and values.ndim == 3:
        values = values[..., -1]
    return pd.DataFrame(
        values,
        columns=list(feature_columns),
    )


def sensitivity_curves(
    model,
    frame: pd.DataFrame,
    feature: str,
    *,
    feature_columns: Sequence[str] | None = None,
    n_points: int = 21,
    min_quantile: float = 0.01,
    max_quantile: float = 0.99,
    random_state: int = 20260907,
) -> pd.DataFrame:
    """One-factor sensitivity inside observed training support."""
    if feature not in frame.columns:
        raise ValueError(f"sensitivity feature missing from frame: {feature}")
    if feature_columns is None:
        feature_columns = [
            name
            for name in frame.columns
            if pd.api.types.is_numeric_dtype(frame[name])
            and name not in {"actual", "prediction"}
        ]
    base = _feature_matrix(frame, feature_columns)
    values = frame[feature].to_numpy(dtype=float)
    lower = float(np.quantile(values, min_quantile))
    upper = float(np.quantile(values, max_quantile))
    levels = np.linspace(lower, upper, int(n_points))
    feature_index = list(feature_columns).index(feature)
    rows = []
    rng = np.random.default_rng(random_state)
    row_index = int(rng.integers(0, len(base)))
    point = base[row_index].copy()
    for level in levels:
        point[feature_index] = level
        prediction = model.predict(point.reshape(1, -1))
        rows.append(
            {
                "feature": feature,
                "quantile_level": float(
                    (level - lower) / (upper - lower) if upper > lower else 0.5
                ),
                "value": float(level),
                "prediction": float(np.asarray(prediction).ravel()[0]),
            }
        )
    return pd.DataFrame(rows)


def mechanism_consistency(
    direction: Mapping[str, float],
    priors: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    """Flag sensitivity directions against versioned ecological priors."""
    priors = priors or MECHANISM_PRIORS
    rows = []
    for feature, slope in direction.items():
        prior = priors.get(feature)
        if prior is None:
            rows.append(
                {
                    "feature": feature,
                    "prior": "not_specified",
                    "status": "conflict_review_required",
                }
            )
            continue
        if prior in {"mixed", "non_monotonic_expected"}:
            status = "non_monotonic_expected"
        elif (prior == "positive" and slope >= 0) or (
            prior == "negative" and slope <= 0
        ):
            status = "consistent"
        else:
            status = "conflict_review_required"
        rows.append({"feature": feature, "prior": prior, "status": status})
    return rows
