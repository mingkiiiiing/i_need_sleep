def _mean(values):
    return sum(values) / len(values)


def _correlation(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var == 0 or y_var == 0:
        return 0.0
    return numerator / ((x_var * y_var) ** 0.5)


def feature_importance_by_correlation(rows, feature_keys, target_key):
    targets = [float(row[target_key]) for row in rows]
    ranking = []
    for key in feature_keys:
        values = [float(row.get(key, 0.0)) for row in rows]
        corr = _correlation(values, targets)
        ranking.append(
            {
                "feature": key,
                "importance": abs(corr),
                "direction": "positive" if corr >= 0 else "negative",
            }
        )
    return sorted(ranking, key=lambda item: item["importance"], reverse=True)


def uncertainty_interval(predictions, confidence=0.8):
    if not predictions:
        raise ValueError("predictions must not be empty")
    if not 0.0 < confidence <= 1.0:
        raise ValueError("confidence must be in (0, 1]")
    sorted_values = sorted(float(value) for value in predictions)
    tail = (1.0 - confidence) / 2.0
    low_index = int(tail * (len(sorted_values) - 1))
    high_index = int((1.0 - tail) * (len(sorted_values) - 1))
    return {
        "method": "empirical_prediction_interval",
        "confidence": confidence,
        "lower": sorted_values[low_index],
        "mean": sum(sorted_values) / len(sorted_values),
        "upper": sorted_values[high_index],
    }


def sensitivity_curve(base_row, feature_key, values, scoring_fn):
    curve = []
    for value in values:
        row = dict(base_row)
        row[feature_key] = value
        curve.append({"feature_value": value, "score": float(scoring_fn(row))})
    return curve

