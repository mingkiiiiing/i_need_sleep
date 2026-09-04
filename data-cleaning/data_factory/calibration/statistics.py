"""校准统计原语 (设计 §6.4–§6.8 分层估计)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def harmonic_climatology(doy: np.ndarray, values: np.ndarray, n_harmonics: int = 2) -> dict[str, Any]:
    """逐日气候态的调和回归（返回系数与样本量）。"""

    doy = np.asarray(doy, dtype=float)
    values = np.asarray(values, dtype=float)
    mask = ~np.isnan(values)
    doy, values = doy[mask], values[mask]
    if len(values) < 8:
        return {"a0": float(np.nanmean(values)) if len(values) else 0.0, "coef": [0.0] * (2 * n_harmonics), "n": int(len(values))}
    omega = 2.0 * np.pi / 365.25
    columns = [np.ones_like(doy)]
    for k in range(1, n_harmonics + 1):
        columns.append(np.sin(k * omega * doy))
        columns.append(np.cos(k * omega * doy))
    design = np.column_stack(columns)
    coef, *_ = np.linalg.lstsq(design, values, rcond=None)
    return {"a0": float(coef[0]), "coef": [float(c) for c in coef[1:]], "n": int(len(values))}


def eval_climatology(clim: dict[str, Any], doy: np.ndarray) -> np.ndarray:
    omega = 2.0 * np.pi / 365.25
    result = np.full(len(doy), float(clim["a0"]), dtype=float)
    coef = clim.get("coef", [])
    for k, value in enumerate(coef):
        harmonic = k // 2 + 1
        term = np.sin(harmonic * omega * doy) if k % 2 == 0 else np.cos(harmonic * omega * doy)
        result = result + value * term
    return result


def ar1(series: np.ndarray) -> tuple[float, float, float]:
    """一阶自回归 (phi, sigma, mean)；phi 钳位 [0, 0.99]。"""

    values = np.asarray(series, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) < 8:
        mean = float(np.mean(values)) if len(values) else 0.0
        return 0.5, float(np.std(values)) if len(values) > 1 else 1.0, mean
    mean = float(np.mean(values))
    delta = values - mean
    phi = float(np.sum(delta[:-1] * delta[1:]) / max(np.sum(delta[:-1] ** 2), 1e-12))
    phi = min(max(phi, 0.0), 0.99)
    resid = delta[1:] - phi * delta[:-1]
    sigma = float(np.std(resid)) if len(resid) > 1 else float(np.std(values))
    return phi, max(sigma, 1e-6), mean


def monthly_markov(dates: pd.DatetimeIndex, precip: np.ndarray) -> pd.DataFrame:
    """降水两阶段模型：月度发生概率（转移 p00/p01）。"""

    wet = (pd.Series(np.asarray(precip, dtype=float), index=dates) > 0.1).astype(int)
    frame = pd.DataFrame({"month": wet.index.month, "wet": wet.values})
    frame["prev_wet"] = frame["wet"].shift(1)
    frame["prev_month"] = frame["month"].shift(1)
    frame = frame[frame["prev_month"] == frame["month"]].dropna()
    rows = []
    for month, group in frame.groupby("month"):
        dry = group[group["prev_wet"] == 0]
        wet_prev = group[group["prev_wet"] == 1]
        rows.append(
            {
                "month": int(month),
                "p01": float(dry["wet"].mean()) if len(dry) else 0.3,
                "p11": float(wet_prev["wet"].mean()) if len(wet_prev) else 0.5,
                "n": int(len(group)),
            }
        )
    return pd.DataFrame(rows).set_index("month")


def gamma_moments(intensities: np.ndarray) -> tuple[float, float]:
    """矩估计 (shape, scale)；供 Wet 日强度抽样。"""

    values = np.asarray(intensities, dtype=float)
    values = values[~np.isnan(values)]
    values = values[values > 0]
    if len(values) < 8:
        return 0.8, 6.0
    mean = float(np.mean(values))
    var = float(np.var(values))
    scale = max(var / max(mean, 1e-6), 1e-3)
    shape = max(mean / scale, 0.1)
    return float(shape), float(scale)


def residual_corr(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    sub = frame[columns].apply(pd.to_numeric, errors="coerce")
    residualized = sub.copy()
    for column in columns:
        series = sub[column]
        doy = np.asarray(series.index.dayofyear, dtype=float)
        mask = series.notna()
        if mask.sum() > 8:
            omega = 2.0 * np.pi / 365.25
            design = np.column_stack([np.ones(mask.sum()), np.sin(omega * doy[mask]), np.cos(omega * doy[mask])])
            coef, *_ = np.linalg.lstsq(design, series[mask].to_numpy(), rcond=None)
            residualized.loc[mask, column] = series[mask].to_numpy() - design @ coef
    return residualized.corr(min_periods=30).fillna(0.0)


def lognorm_params(values: np.ndarray) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    values = values[values > 0]
    if len(values) < 4:
        return 0.0, 0.5
    logs = np.log(values)
    return float(np.mean(logs)), float(max(np.std(logs), 0.05))


def monthly_lognorm(dates: pd.DatetimeIndex, values: np.ndarray) -> pd.DataFrame:
    frame = pd.DataFrame({"month": pd.DatetimeIndex(dates).month, "value": np.asarray(values, dtype=float)})
    frame = frame.dropna()
    frame = frame[frame["value"] > 0]
    grouped = frame.groupby("month")["value"]
    rows = []
    for month, series in grouped:
        mu, sigma = lognorm_params(series.to_numpy())
        rows.append({"month": int(month), "mu": mu, "sigma": sigma, "n": int(len(series))})
    return pd.DataFrame(rows, columns=["month", "mu", "sigma", "n"]).set_index("month")


def shrink(n_group: int, group_value: float, prior_value: float, *, n_min: int = 12, prior_strength: float = 5.0) -> float:
    """分层收缩：小样本组向先验收缩 (设计 §6.7)。n 越接近 n_min 权重越大。"""

    effective = n_min / max(n_min, 1.0)
    weight = n_group / (n_group + prior_strength * effective * n_min)
    return float(weight * group_value + (1.0 - weight) * prior_value)


def monthly_stats(dates: pd.DatetimeIndex, values: np.ndarray) -> pd.DataFrame:
    frame = pd.DataFrame({"month": pd.DatetimeIndex(dates).month, "value": np.asarray(values, dtype=float)}).dropna()
    grouped = frame.groupby("month")["value"]
    return pd.DataFrame({"mean": grouped.mean(), "std": grouped.std().fillna(0.0), "n": grouped.size()})
