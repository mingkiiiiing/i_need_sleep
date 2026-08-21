import math


def regression_metrics(y_true, y_pred):
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must have the same non-zero length")
    errors = [float(pred) - float(true) for true, pred in zip(y_true, y_pred)]
    abs_errors = [abs(error) for error in errors]
    squared_errors = [error * error for error in errors]
    mean_true = sum(float(value) for value in y_true) / len(y_true)
    ss_tot = sum((float(value) - mean_true) ** 2 for value in y_true)
    ss_res = sum(squared_errors)
    r2 = 0.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot
    return {
        "mae": sum(abs_errors) / len(abs_errors),
        "rmse": math.sqrt(sum(squared_errors) / len(squared_errors)),
        "r2": r2,
        "sample_count": len(y_true),
    }


def classification_metrics(y_true, y_pred):
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must have the same non-zero length")
    tp = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 1)
    fp = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 1)
    fn = sum(1 for true, pred in zip(y_true, y_pred) if true == 1 and pred == 0)
    tn = sum(1 for true, pred in zip(y_true, y_pred) if true == 0 and pred == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    balanced_accuracy = 0.5 * (
        (tp / (tp + fn) if tp + fn else 0.0)
        + (tn / (tn + fp) if tn + fp else 0.0)
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "balanced_accuracy": balanced_accuracy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }

