"""Issue-time lag/rolling feature construction from contiguous grid-day series."""

from __future__ import annotations

import pandas as pd

from .contracts import (
    HISTORY_LAG_DAYS,
    HISTORY_STATE_COLUMNS,
)


def add_history_features(
    frame: pd.DataFrame,
    *,
    state_columns: tuple[str, ...] = HISTORY_STATE_COLUMNS,
    lag_days: tuple[int, ...] = HISTORY_LAG_DAYS,
) -> pd.DataFrame:
    """Return a copy with lag and rolling fields derived before issue time.

    The caller must provide contiguous ``grid_id``-``date`` observations in a
    single issue-time window.  Null values at the start of a grid's series are
    intentionally retained; the model preprocessor later learns train medians
    and explicit missing indicators.
    """
    required = {"grid_id", "date", *state_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"history frame missing columns: {missing}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    result = result.sort_values(["grid_id", "date"]).reset_index(drop=True)
    for column in state_columns:
        values = pd.to_numeric(result[column], errors="coerce")
        result[column] = values
        grouped = result.groupby("grid_id")[column]
        for lag in lag_days:
            result[f"{column}_lag_{lag}d"] = grouped.shift(int(lag))
        rolling7 = grouped.transform(
            lambda series: series.rolling(7, min_periods=1).mean()
        )
        rolling7_std = grouped.transform(
            lambda series: series.rolling(7, min_periods=1).std()
        )
        result[f"{column}_rolling7_mean"] = rolling7
        result[f"{column}_rolling7_std"] = rolling7_std
        result[f"{column}_change_1d"] = (
            values - result[f"{column}_lag_1d"]
        )
        result[f"{column}_change_7d"] = (
            values - result[f"{column}_lag_7d"]
        )
    return result
