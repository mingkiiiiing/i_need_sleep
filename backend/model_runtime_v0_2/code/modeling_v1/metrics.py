"""Primary, guardrail, diagnostic, spatial, dynamic, and bootstrap metrics."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    cohen_kappa_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

from .contracts import (
    DEFAULT_SEED,
    HIGH_RISK_CLASSES,
    RISK_CLASSES,
    TaskSpec,
)

_EPS = 1e-12
_GUARDED_DENOMINATOR = 1e-6


def _as_1d(values, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return array


def _require_same_length(y_true, y_pred) -> None:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must have the same length")
    if len(y_true) == 0:
        raise ValueError("metrics require a non-empty sample")


def binary_metrics(
    y_true, y_score, *, decision_threshold: float = 0.5
) -> dict[str, float | int]:
    """Return binary classification metrics and business-guardrail counts."""
    true = _as_1d(y_true, "y_true")
    score = _as_1d(y_score, "y_score")
    _require_same_length(true, score)
    valid = np.isfinite(true) & np.isfinite(score)
    true = true[valid].astype(float)
    score = score[valid]
    if len(true) == 0:
        raise ValueError("binary metrics require finite labels and scores")
    if not np.isin(true, (0.0, 1.0)).all():
        raise ValueError("binary labels must be 0 or 1")

    decision = score >= float(decision_threshold)
    tp = float(np.sum((true == 1.0) & decision))
    fn = float(np.sum((true == 1.0) & ~decision))
    fp = float(np.sum((true == 0.0) & decision))
    tn = float(np.sum((true == 0.0) & ~decision))
    positive = tp + fn
    negative = tn + fp
    recall = tp / positive if positive else math.nan
    specificity = tn / negative if negative else math.nan
    fnr = 1.0 - recall if positive else math.nan
    precision = tp / (tp + fp) if tp + fp else math.nan
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision and recall and not math.isnan(precision) and not math.isnan(recall)
        else math.nan
    )

    if positive and negative:
        pr_auc = float(average_precision_score(true, score))
        roc_auc = float(roc_auc_score(true, score))
        balanced_accuracy = 0.5 * (recall + specificity)
        if not (np.isin(true, (0.0, 1.0)).all() and (score >= 0).all() and (score <= 1).all()):
            brier = math.nan
        else:
            brier = float(brier_score_loss(true, score))
    else:
        pr_auc = math.nan
        roc_auc = math.nan
        balanced_accuracy = math.nan
        brier = math.nan

    return {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "recall": recall,
        "fnr": fnr,
        "precision": precision,
        "f1": f1,
        "balanced_accuracy": balanced_accuracy,
        "brier_score": brier,
        "decision_threshold": float(decision_threshold),
        "positive_count": int(positive),
        "negative_count": int(negative),
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
    }


def choose_decision_threshold(
    y_true,
    y_score,
    *,
    min_recall: float = 0.80,
) -> dict[str, float | int]:
    """Return the F1-best threshold that still meets a minimum recall floor."""
    if not 0.0 < float(min_recall) <= 1.0:
        raise ValueError("min_recall must be in (0, 1]")
    true = _as_1d(y_true, "y_true")
    score = _as_1d(y_score, "y_score")
    _require_same_length(true, score)
    valid = np.isfinite(true) & np.isfinite(score)
    true = true[valid].astype(float)
    score = score[valid]
    if len(true) == 0:
        raise ValueError("decision threshold calibration requires finite rows")
    if not np.isin(true, (0.0, 1.0)).all():
        raise ValueError("binary labels must be 0 or 1")
    positive = int(true.sum())
    if positive == 0:
        raise ValueError("decision threshold calibration requires positive rows")

    order = np.argsort(-score, kind="mergesort")
    sorted_score = score[order]
    sorted_true = true[order]
    unique_scores, ascending_counts = np.unique(
        sorted_score, return_counts=True
    )
    thresholds = unique_scores[::-1]
    descending_group_ends = np.cumsum(ascending_counts[::-1]) - 1
    positive_cumulative = np.cumsum(sorted_true)
    true_positive = positive_cumulative[descending_group_ends]
    alert_count = descending_group_ends + 1
    recall = true_positive / float(positive)
    precision = np.where(
        alert_count > 0, true_positive / alert_count, 0.0
    )
    f1 = np.zeros_like(precision)
    denominator = precision + recall
    np.divide(
        2.0 * precision * recall,
        denominator,
        out=f1,
        where=denominator > 0.0,
    )
    eligible = recall >= float(min_recall) - 1e-9
    if not eligible.any():
        raise ValueError(
            "no threshold reaches the recall floor; best recall: "
            f"{float(recall.max()):.6f}"
        )
    eligible_positions = np.flatnonzero(eligible)
    chosen = int(
        eligible_positions[int(np.argmax(f1[eligible_positions]))]
    )
    threshold = float(thresholds[chosen])
    metrics = binary_metrics(true, score, decision_threshold=threshold)
    alert_count = int(metrics["tp"] + metrics["fp"])
    return {
        "decision_threshold": threshold,
        "min_recall": float(min_recall),
        "recall": float(metrics["recall"]),
        "precision": float(metrics["precision"]),
        "f1": float(metrics["f1"]),
        "alert_count": alert_count,
        "alert_rate": float(alert_count) / len(true),
        "positive_count": positive,
    }


def _class_indicators(values: np.ndarray, classes: Sequence[str]) -> np.ndarray:
    rows = []
    for label in classes:
        rows.append((values == label).astype(float))
    return np.column_stack(rows) if rows else np.empty((len(values), 0))


def ordinal_metrics(
    y_true,
    y_pred,
    *,
    classes: Sequence[str] = RISK_CLASSES,
    high_risk_classes: Sequence[str] = HIGH_RISK_CLASSES,
) -> dict[str, float | int]:
    """Return macro-F1, quadratic kappa, and high-risk recall guardrails."""
    true = np.asarray([str(value) for value in y_true])
    pred = np.asarray([str(value) for value in y_pred])
    _require_same_length(true, pred)
    class_list = list(classes)
    valid = np.isin(true, class_list) & np.isin(pred, class_list)
    true = true[valid]
    pred = pred[valid]
    if len(true) == 0:
        raise ValueError("ordinal metrics require at least one valid class label")

    order = {name: index for index, name in enumerate(class_list)}
    numeric_true = np.asarray([order[value] for value in true])
    numeric_pred = np.asarray([order[value] for value in pred])
    present_classes = [
        name for name in class_list if name in set(true) or name in set(pred)
    ]
    macro_f1 = float(
        _macro_f1(
            _class_indicators(true, present_classes),
            _class_indicators(pred, present_classes),
            present_classes,
        )
    )
    high_set = set(high_risk_classes)
    true_high = np.isin(true, list(high_set))
    pred_high = np.isin(pred, list(high_set))
    high_true_count = int(true_high.sum())
    if high_true_count:
        high_recall = float(
            np.sum(true_high & pred_high) / np.sum(true_high)
        )
    else:
        high_recall = math.nan
    if len(np.unique(numeric_true)) > 1 and len(np.unique(numeric_pred)) > 1:
        kappa = float(cohen_kappa_score(numeric_true, numeric_pred, weights="quadratic"))
    else:
        kappa = math.nan
    return {
        "macro_f1": macro_f1,
        "quadratic_kappa": kappa,
        "accuracy": float(accuracy_score(true, pred)),
        "high_severe_recall": high_recall,
        "high_severe_true_count": high_true_count,
        "sample_count": int(len(true)),
    }


def _macro_f1(true_indicator: np.ndarray, pred_indicator: np.ndarray, classes) -> float:
    scores = []
    for index, _ in enumerate(classes):
        true_class = true_indicator[:, index]
        pred_class = pred_indicator[:, index]
        tp = float(np.sum((true_class == 1.0) & (pred_class == 1.0)))
        fp = float(np.sum((true_class == 0.0) & (pred_class == 1.0)))
        fn = float(np.sum((true_class == 1.0) & (pred_class == 0.0)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores.append(f1)
    return float(np.mean(scores)) if scores else math.nan


def probability_metrics(y_true, y_pred) -> dict[str, float | int]:
    """Metrics for bounded probability/risk targets and predicted scores."""
    true = _as_1d(y_true, "y_true")
    pred = _as_1d(y_pred, "y_pred")
    _require_same_length(true, pred)
    valid = np.isfinite(true) & np.isfinite(pred)
    true = true[valid].astype(float)
    pred = pred[valid].astype(float)
    if len(true) == 0:
        raise ValueError("probability metrics require finite values")
    brier = float(np.mean((true - pred) ** 2))
    spearman = float(stats.spearmanr(true, pred).statistic) if len(true) > 2 else math.nan
    return {
        "mae": float(mean_absolute_error(true, pred)),
        "rmse": float(np.sqrt(mean_squared_error(true, pred))),
        "brier_score": brier,
        "spearman": spearman,
        "sample_count": int(len(true)),
    }


def regression_metrics(
    y_true,
    y_pred,
    *,
    detection_limit: float | None = None,
    log1p: bool = False,
) -> dict[str, float | int]:
    """Return MAE/RMSE/R2/Spearman plus guarded all/effective SMAPE."""
    true = _as_1d(y_true, "y_true")
    pred = _as_1d(y_pred, "y_pred")
    _require_same_length(true, pred)
    valid = np.isfinite(true) & np.isfinite(pred)
    true = true[valid].astype(float)
    pred = pred[valid].astype(float)
    if len(true) == 0:
        raise ValueError("regression metrics require finite values")
    if log1p and ((true < 0).any() or (pred < 0).any()):
        raise ValueError("log1p regression metrics require non-negative values")

    mae = float(mean_absolute_error(true, pred))
    rmse = float(np.sqrt(mean_squared_error(true, pred)))
    r2 = float(r2_score(true, pred)) if len(true) > 1 else math.nan
    spearman = float(stats.spearmanr(true, pred).statistic) if len(true) > 2 else math.nan

    numerator = 2.0 * np.abs(pred - true)
    denominator = np.abs(true) + np.abs(pred)
    near_zero = denominator <= _GUARDED_DENOMINATOR
    guarded_denominator = np.where(
        near_zero, _GUARDED_DENOMINATOR, denominator
    )
    smape_all = float(np.mean(numerator / guarded_denominator))
    if detection_limit is not None:
        effective = (true >= detection_limit) | (pred >= detection_limit)
    else:
        effective = ~near_zero
    smape_effective = (
        float(np.mean(numerator[effective] / guarded_denominator[effective]))
        if effective.any()
        else math.nan
    )
    result = {
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "spearman": spearman,
        "smape_all": smape_all,
        "smape_effective": smape_effective,
        "near_zero_count": int(near_zero.sum()),
        "effective_sample_count": int(effective.sum()),
        "sample_count": int(len(true)),
    }
    if log1p:
        result["log1p_mae"] = float(
            np.mean(np.abs(np.log1p(true) - np.log1p(pred)))
        )
    return result


def _direction_accuracy(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual_diff = np.diff(actual)
    predicted_diff = np.diff(predicted)
    valid = (actual_diff != 0) & (predicted_diff != 0)
    if not valid.any():
        return math.nan
    return float(np.mean(np.sign(actual_diff[valid]) == np.sign(predicted_diff[valid])))


def _turning_dates(values: np.ndarray, dates: np.ndarray):
    turns = []
    for index in range(1, len(values) - 1):
        left, center, right = values[index - 1], values[index], values[index + 1]
        if center > left and center > right:
            turns.append((dates[index], "peak"))
        elif center < left and center < right:
            turns.append((dates[index], "trough"))
    return turns


def event_metrics(
    frame: pd.DataFrame,
    *,
    warning_lookback_days: int = 7,
    warning_lookahead_days: int = 7,
) -> dict[str, object]:
    """Compute daily event warnings, peak/duration errors, and turning delays."""
    required = {"grid_id", "date", "actual", "prediction"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"event frame missing columns: {missing}")
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"])
    working["actual"] = pd.to_numeric(working["actual"], errors="coerce")
    working["prediction"] = pd.to_numeric(working["prediction"], errors="coerce")
    working = working[working["actual"].notna()].sort_values(
        ["grid_id", "date"]
    )
    if working.empty:
        return {
            "event_count": 0,
            "warning_rate": math.nan,
            "direction_accuracy": math.nan,
            "mean_warning_lead_days": math.nan,
            "mean_duration_error_days": math.nan,
            "mean_peak_date_error_days": math.nan,
        }

    actual_values = working["actual"].to_numpy()
    direction = _direction_accuracy(actual_values, working["prediction"].to_numpy())
    events = []
    grid_events = {}
    for grid_id, group in working.groupby("grid_id", sort=False):
        dates = group["date"].to_numpy()
        values = group["actual"].to_numpy()
        predictions = group["prediction"].to_numpy()
        active = False
        event_id = -1
        event_start = None
        for index, (date, value) in enumerate(zip(dates, values)):
            if bool(value > 0) and not active:
                active = True
                event_id += 1
                event_start = index
            if not bool(value > 0) and active:
                active = False
                events.append(
                    _one_event_metrics(
                        grid_id,
                        dates[event_start:index],
                        values[event_start:index],
                        predictions[event_start:index],
                        group,
                        warning_lookback_days,
                        warning_lookahead_days,
                    )
                )
        if active:
            events.append(
                _one_event_metrics(
                    grid_id,
                    dates[event_start:],
                    values[event_start:],
                    predictions[event_start:],
                    group,
                    warning_lookback_days,
                    warning_lookahead_days,
                )
            )

    if not events:
        return {
            "event_count": 0,
            "warning_rate": math.nan,
            "direction_accuracy": direction,
            "mean_warning_lead_days": math.nan,
            "mean_duration_error_days": math.nan,
            "mean_peak_date_error_days": math.nan,
        }
    return {
        "event_count": len(events),
        "warning_rate": float(np.mean([event["has_warning"] for event in events])),
        "direction_accuracy": direction,
        "mean_warning_lead_days": float(
            np.nanmean([event["warning_lead_days"] for event in events])
        )
        if any(not math.isnan(event["warning_lead_days"]) for event in events)
        else math.nan,
        "mean_duration_error_days": (
            float(np.nanmean([event["duration_error_days"] for event in events]))
            if any(not math.isnan(event["duration_error_days"]) for event in events)
            else math.nan
        ),
        "mean_peak_date_error_days": float(
            np.nanmean([event["peak_date_error_days"] for event in events])
        ),
    }


def _one_event_metrics(
    grid_id,
    dates,
    values,
    predictions,
    group,
    lookback,
    lookahead,
):
    start = pd.Timestamp(dates[0])
    end = pd.Timestamp(dates[-1])
    duration_days = int((end - start).days) + 1
    full_dates = pd.DatetimeIndex(group["date"])
    full_pred = group["prediction"].to_numpy()
    window_start = start - pd.Timedelta(days=lookback)
    window_end = start + pd.Timedelta(days=lookahead)
    warning_indexes = np.flatnonzero(
        (full_dates >= window_start)
        & (full_dates <= window_end)
        & (full_pred > 0)
    )
    has_warning = bool(len(warning_indexes) > 0)
    warning_lead = math.nan
    if has_warning:
        warning_date = full_dates[int(warning_indexes[0])]
        warning_lead = float((start - warning_date).days)

    peak_index = int(np.argmax(values))
    actual_peak_date = pd.Timestamp(dates[peak_index])
    predicted_peak = full_pred[
        (full_dates >= start)
        & (full_dates <= end)
    ]
    peak_date_error = math.nan
    if len(predicted_peak):
        pred_peak_index = int(np.argmax(predicted_peak))
        predicted_peak_date = start + pd.Timedelta(days=pred_peak_index)
        peak_date_error = float(abs((actual_peak_date - predicted_peak_date).days))
    return {
        "grid_id": grid_id,
        "event_start": str(start.date()),
        "event_end": str(end.date()),
        "duration_days": duration_days,
        "has_warning": has_warning,
        "warning_lead_days": warning_lead,
        "duration_error_days": math.nan,
        "peak_date_error_days": peak_date_error,
    }


def _centroid(centroid_x, centroid_y, weights):
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0:
        return None
    x = float(np.sum(centroid_x * weights) / weight_sum)
    y = float(np.sum(centroid_y * weights) / weight_sum)
    return x, y


def spatial_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    """Return date-aggregated spatial overlap, area, and centroid metrics."""
    required = {"centroid_x_m", "centroid_y_m", "water_area_m2"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"spatial frame missing columns: {missing}")
    if "true_burden" in frame.columns and "pred_burden" in frame.columns:
        working = frame.copy()
    else:
        required_predict = {"actual", "prediction"}
        missing = sorted(required_predict - set(frame.columns))
        if missing:
            raise ValueError(f"spatial frame missing burden columns: {missing}")
        working = frame.rename(
            columns={"actual": "true_burden", "prediction": "pred_burden"}
        )
    if "date" not in working.columns:
        working["date"] = pd.Timestamp("2000-01-01")
    for column in (
        "true_burden",
        "pred_burden",
        "centroid_x_m",
        "centroid_y_m",
        "water_area_m2",
    ):
        working[column] = pd.to_numeric(working[column], errors="raise")

    daily = []
    for _, day in working.groupby("date", sort=False):
        area = day["water_area_m2"].to_numpy(dtype=float)
        true_burden = day["true_burden"].to_numpy(dtype=float)
        pred_burden = day["pred_burden"].to_numpy(dtype=float)
        true_active = true_burden > 0
        pred_active = pred_burden > 0
        true_area = float(np.sum(area[true_active]))
        pred_area = float(np.sum(area[pred_active]))
        intersection = float(np.sum(area[true_active & pred_active]))
        union = true_area + pred_area - intersection
        true_weights = np.maximum(true_burden, 0.0) * area
        pred_weights = np.maximum(pred_burden, 0.0) * area
        true_centroid = _centroid(
            day["centroid_x_m"].to_numpy(), day["centroid_y_m"].to_numpy(), true_weights
        )
        pred_centroid = _centroid(
            day["centroid_x_m"].to_numpy(), day["centroid_y_m"].to_numpy(), pred_weights
        )
        centroid_error = math.nan
        if true_centroid is not None and pred_centroid is not None:
            centroid_error = (
                math.dist(true_centroid, pred_centroid) / 1000.0
            )
        true_count = int(true_active.sum())
        pred_count = int(pred_active.sum())
        daily.append(
            {
                "iou": intersection / union if union else math.nan,
                "dice": 2.0 * intersection / (true_area + pred_area)
                if true_area + pred_area
                else math.nan,
                "area_error_km2": (pred_area - true_area) / 1_000_000.0,
                "area_relative_error": (pred_area - true_area) / true_area
                if true_area
                else math.nan,
                "affected_grid_error": pred_count - true_count,
                "missed_area_fraction": max(0.0, true_area - intersection) / true_area
                if true_area
                else math.nan,
                "overpredicted_area_fraction": max(0.0, pred_area - intersection) / pred_area
                if pred_area
                else math.nan,
                "centroid_error_km": centroid_error,
                "true_area_km2": true_area / 1_000_000.0,
                "pred_area_km2": pred_area / 1_000_000.0,
            }
        )

    result: dict[str, float | int] = {}
    keys = daily[0].keys()
    for key in keys:
        values = np.asarray([item[key] for item in daily], dtype=float)
        result[key] = (
            float(np.nanmean(values))
            if key
            in {
                "iou",
                "dice",
                "area_relative_error",
                "missed_area_fraction",
                "overpredicted_area_fraction",
                "centroid_error_km",
            }
            else float(np.mean(values))
        )
    result["date_count"] = len(daily)
    return result


def bootstrap_replicate(
    frame: pd.DataFrame, block_column: str, rng: np.random.Generator
) -> pd.DataFrame:
    """Draw whole block ids with replacement and return all their rows."""
    block_ids = sorted(pd.unique(frame[block_column]))
    if not block_ids:
        raise ValueError("block bootstrap requires at least one block")
    chosen = rng.choice(block_ids, size=len(block_ids), replace=True)
    parts = [frame.loc[frame[block_column] == block_id] for block_id in chosen]
    return pd.concat(parts, ignore_index=True)


def block_bootstrap_ci(
    frame: pd.DataFrame,
    *,
    block_column: str = "date",
    statistic: Callable[[pd.DataFrame], float],
    replicates: int = 1000,
    confidence_level: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> dict[str, object]:
    """Bootstrap by whole date/event blocks, never by individual grid rows."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("block_bootstrap_ci requires a non-empty DataFrame")
    if block_column not in frame.columns:
        raise ValueError(f"missing bootstrap block column: {block_column}")
    if confidence_level <= 0 or confidence_level >= 1:
        raise ValueError("confidence_level must be between 0 and 1")
    point = float(statistic(frame))
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(int(replicates)):
        sample = bootstrap_replicate(frame, block_column, rng)
        values.append(float(statistic(sample)))
    tail = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(values, [tail, 1.0 - tail])
    return {
        "point_estimate": point,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "confidence_level": float(confidence_level),
        "replicates": int(replicates),
        "seed": seed,
        "block_count": int(pd.unique(frame[block_column]).size),
    }


def evaluate_predictions(
    spec: TaskSpec,
    frame: pd.DataFrame,
    *,
    decision_threshold: float = 0.5,
    detection_limit: float | None = None,
) -> dict[str, object]:
    """Evaluate one candidate using the task's locked primary metric family."""
    required = {"actual", "prediction"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"evaluation frame missing columns: {missing}")
    working = frame.copy()
    if spec.problem_type != "ordinal":
        working["actual"] = pd.to_numeric(working["actual"], errors="coerce")
    working = working[working["actual"].notna()]
    if working.empty:
        raise ValueError("evaluation frame has no finite target values")

    if spec.problem_type == "binary":
        scores = (
            working["probability"]
            if "probability" in working.columns
            else working["prediction"]
        )
        metrics = binary_metrics(
            working["actual"].to_numpy(),
            scores.to_numpy(dtype=float),
            decision_threshold=decision_threshold,
        )
        metrics["primary_metric"] = metrics["pr_auc"]
        return metrics
    if spec.problem_type == "ordinal":
        metrics = ordinal_metrics(
            working["actual"],
            working["prediction"],
        )
        metrics["primary_metric"] = metrics["macro_f1"]
        return metrics
    if spec.problem_type == "probability":
        metrics = probability_metrics(
            working["actual"].to_numpy(),
            pd.to_numeric(working["prediction"], errors="raise").to_numpy(),
        )
        metrics["primary_metric"] = metrics["brier_score"]
        return metrics
    if spec.problem_type == "spatial":
        regression = regression_metrics(
            working["actual"].to_numpy(),
            pd.to_numeric(working["prediction"], errors="raise").to_numpy(),
            detection_limit=detection_limit,
        )
        regression.update(spatial_metrics(working))
        regression["primary_metric"] = regression["iou"]
        return regression
    if spec.problem_type == "regression":
        log_transform = spec.primary_metric == "log1p_mae"
        metrics = regression_metrics(
            working["actual"].to_numpy(),
            pd.to_numeric(working["prediction"], errors="raise").to_numpy(),
            detection_limit=detection_limit,
            log1p=log_transform,
        )
        metrics["primary_metric"] = (
            metrics["log1p_mae"] if log_transform else metrics["mae"]
        )
        return metrics
    raise ValueError(f"unsupported problem type: {spec.problem_type}")
