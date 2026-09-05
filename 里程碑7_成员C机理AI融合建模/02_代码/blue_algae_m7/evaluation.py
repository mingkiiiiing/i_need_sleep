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


def ordinal_classification_metrics(y_true, y_pred, n_classes):
    """多分类（含有序等级）混淆矩阵指标：accuracy、balanced_accuracy、macro F1 与逐类明细。"""

    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must have the same non-zero length")
    per_class = {}
    recalls = []
    for cls in range(n_classes):
        tp = sum(1 for true, pred in zip(y_true, y_pred) if true == cls and pred == cls)
        fp = sum(1 for true, pred in zip(y_true, y_pred) if true != cls and pred == cls)
        support = sum(1 for true in y_true if true == cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[str(cls)] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
        if support:
            recalls.append(recall)
    accuracy = sum(1 for true, pred in zip(y_true, y_pred) if true == pred) / len(y_true)
    return {
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else 0.0,
        "macro_f1": sum(item["f1"] for item in per_class.values()) / len(per_class) if per_class else 0.0,
        "per_class": per_class,
    }

