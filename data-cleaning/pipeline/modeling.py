from __future__ import annotations

"""Leakage-aware mechanism + AI experiments for the Taihu feature tables.

The module deliberately treats the current feature table as a *nowcast* table:
only values available at ``target_time_bucket`` are eligible.  The feature with
the same semantic name as the target and all ``target_rolling_*`` columns are
excluded, because they can contain the target value at the prediction time.
"""

import csv
import json
import math
import pickle
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .provenance import manifest_root


UTC = timezone.utc


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any) -> float | None:
    if value in (None, "", "None", "null", "nan", "NaN"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _mechanism_features(row: dict[str, Any]) -> dict[str, Any]:
    """Calculate transparent growth limitation factors.

    The parameters are conservative first-release defaults for cyanobacteria;
    they are configurable in the modelling report later after site-specific
    calibration. Missing drivers receive a neutral factor (0.5) and a flag so
    the model never silently turns an absent observation into a measurement.
    """

    water_temperature = _float(row.get("feature_water_temperature"))
    air_temperature = _float(row.get("feature_air_temperature"))
    temperature = water_temperature if water_temperature is not None else air_temperature
    temperature_basis = "water_temperature" if water_temperature is not None else "air_temperature" if air_temperature is not None else "missing"
    nitrogen = _float(row.get("feature_total_nitrogen"))
    phosphorus = _float(row.get("feature_total_phosphorus"))
    radiation = _float(row.get("feature_shortwave_radiation"))
    wind_speed = _float(row.get("feature_wind_speed"))

    missing: list[str] = []
    if temperature is None:
        f_temperature = 0.5
        missing.append("temperature")
    else:
        # Gaussian temperature response, optimum 28 degC and width 8 degC.
        f_temperature = math.exp(-((temperature - 28.0) / 8.0) ** 2)
    if nitrogen is None or nitrogen < 0:
        f_nitrogen = 0.5
        missing.append("total_nitrogen")
    else:
        f_nitrogen = nitrogen / (nitrogen + 0.20)
    if phosphorus is None or phosphorus < 0:
        f_phosphorus = 0.5
        missing.append("total_phosphorus")
    else:
        f_phosphorus = phosphorus / (phosphorus + 0.020)
    if radiation is None or radiation < 0:
        f_light = 0.5
        missing.append("shortwave_radiation")
    else:
        f_light = radiation / (radiation + 100.0)
    if wind_speed is None or wind_speed < 0:
        f_wind = 0.75
        missing.append("wind_speed")
    else:
        # Strong winds reduce surface accumulation; this is a soft factor.
        f_wind = math.exp(-max(wind_speed - 3.0, 0.0) / 5.0)
    growth_index = f_temperature * f_nitrogen * f_phosphorus * f_light * f_wind
    return {
        "mechanism_temperature_limit": f_temperature,
        "mechanism_nitrogen_limit": f_nitrogen,
        "mechanism_phosphorus_limit": f_phosphorus,
        "mechanism_light_limit": f_light,
        "mechanism_wind_limit": f_wind,
        "mechanism_growth_index": growth_index,
        "mechanism_temperature_basis": temperature_basis,
        "mechanism_missing_count": len(missing),
        "mechanism_missing_drivers": ",".join(missing),
    }


def _mechanistic_baseline(row: dict[str, Any], reference_state: float) -> tuple[float, str]:
    """One-day mechanistic state forecast used by residual learning.

    If a causal one-day target lag exists it is used as the state; otherwise
    the training median is a clearly labelled fallback. The fallback keeps the
    residual interface runnable on sparse historical data without pretending
    that a state observation was available.
    """

    lag = _float(row.get("target_lag_1d"))
    state = max(lag, 0.0) if lag is not None else max(reference_state, 0.0)
    source = "target_lag_1d" if lag is not None else "train_median_fallback"
    growth = _mechanism_features(row)["mechanism_growth_index"]
    return state * math.exp(0.08 * float(growth)), source


def _is_excluded(column: str, target_variable: str) -> bool:
    lower = column.lower()
    target_name = _safe_name(target_variable)
    if column in {
        "target_clean_value", "target_feature_row_key", "target_time_bucket",
        "target_source_id", "target_station_id", "target_scene_id",
        "target_variable_code", "target_category", "dataset_split",
        "split_time_group", "split_group", "split_reason", "quality_flags",
        "leakage_check", "temperature_degree_days_basis", "mechanism_temperature_basis",
        "mechanism_missing_drivers",
    }:
        return True
    if lower.startswith("target_rolling_"):
        return True
    if lower.startswith("feature_"):
        semantic = lower[len("feature_"):]
        if semantic == target_name:
            return True
    if lower.endswith(("_match_status", "_source_id", "_station_id", "_scene_id")):
        return True
    return False


def _numeric_feature_columns(rows: list[dict[str, Any]], target_variable: str, include_mechanism: bool) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    selected: list[str] = []
    for column in columns:
        if _is_excluded(column, target_variable):
            continue
        if not include_mechanism and column.startswith("mechanism_"):
            continue
        numeric_count = sum(_float(row.get(column)) is not None for row in rows)
        # Only use columns with at least two observed training values. This
        # avoids accidentally treating IDs or categorical values as numbers.
        if numeric_count >= 2:
            selected.append(column)
    if include_mechanism:
        selected.extend([
            "mechanism_temperature_limit", "mechanism_nitrogen_limit",
            "mechanism_phosphorus_limit", "mechanism_light_limit",
            "mechanism_wind_limit", "mechanism_growth_index",
            "mechanism_missing_count",
        ])
    return list(dict.fromkeys(selected))


def _matrix(rows: list[dict[str, Any]], columns: list[str], include_mechanism: bool) -> np.ndarray:
    values: list[list[float | None]] = []
    for row in rows:
        enriched = dict(row)
        if include_mechanism:
            enriched.update(_mechanism_features(row))
        values.append([_float(enriched.get(column)) for column in columns])
    return np.asarray(values, dtype=float)


def _metric_row(split: str, y_true: np.ndarray, y_pred: np.ndarray, model: str, target_variable: str) -> dict[str, Any]:
    if len(y_true) == 0:
        return {"target_variable": target_variable, "model": model, "dataset_split": split, "row_count": 0, "r2": None, "rmse": None, "mae": None, "smape": None}
    denominator = np.maximum(np.abs(y_true) + np.abs(y_pred), 1e-9)
    smape = float(np.mean(2 * np.abs(y_pred - y_true) / denominator))
    r2 = float(r2_score(y_true, y_pred)) if len(y_true) > 1 and np.var(y_true) > 0 else None
    return {
        "target_variable": target_variable,
        "model": model,
        "dataset_split": split,
        "row_count": int(len(y_true)),
        "r2": r2,
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "smape": smape,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not columns:
            return 0
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def _write_sqlite(path: Path, predictions: list[dict[str, Any]], metrics: list[dict[str, Any]], importance: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        for table in ("model_predictions", "model_metrics", "model_feature_importance"):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        def write_table(name: str, rows: list[dict[str, Any]]) -> None:
            if not rows:
                connection.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                return
            columns: list[str] = []
            for row in rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            definitions = []
            for column in columns:
                values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
                numeric = sum(_float(value) is not None for value in values)
                kind = "REAL" if values and numeric / len(values) >= 0.8 else "TEXT"
                definitions.append(f'"{column}" {kind}')
            connection.execute(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY AUTOINCREMENT,{",".join(definitions)})')
            quoted = ",".join(f'"{column}"' for column in columns)
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(f"INSERT INTO {name} ({quoted}) VALUES ({placeholders})", [[row.get(column) for column in columns] for row in rows])
        write_table("model_predictions", predictions)
        write_table("model_metrics", metrics)
        write_table("model_feature_importance", importance)
        connection.commit()
    finally:
        connection.close()


def train_experiment(input_dir: Path, output_root: Path | None = None, database: Path | None = None, *, target_variable: str = "phytoplankton_biomass", algorithm: str = "random_forest", fusion: str = "mechanistic_cascade", random_state: int = 42) -> dict[str, Any]:
    if algorithm not in {"random_forest", "hist_gradient_boosting"}:
        raise ValueError("algorithm must be random_forest or hist_gradient_boosting")
    if fusion not in {"none", "mechanistic_cascade", "mechanistic_residual"}:
        raise ValueError("fusion must be none, mechanistic_cascade or mechanistic_residual")
    input_dir = Path(input_dir)
    source_rows = {split: _read_csv(input_dir / f"{split}.csv") for split in ("train", "validation", "test")}
    rows_by_split = {split: [row for row in rows if row.get("target_variable_code") == target_variable and _float(row.get("target_clean_value")) is not None] for split, rows in source_rows.items()}
    if not rows_by_split["train"]:
        raise ValueError(f"no training rows for target variable {target_variable!r}")
    include_mechanism = fusion in {"mechanistic_cascade", "mechanistic_residual"}
    columns = _numeric_feature_columns(rows_by_split["train"], target_variable, include_mechanism)
    if not columns:
        raise ValueError("no usable numeric features after leakage exclusions")
    imputer = SimpleImputer(strategy="median")
    X_train = imputer.fit_transform(_matrix(rows_by_split["train"], columns, include_mechanism))
    if algorithm == "random_forest":
        model = RandomForestRegressor(n_estimators=200, max_depth=8, min_samples_leaf=2, random_state=random_state, n_jobs=-1)
    else:
        model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=0.1, random_state=random_state)
    y_train = np.asarray([float(row["target_clean_value"]) for row in rows_by_split["train"]], dtype=float)
    reference_state = float(np.median(y_train))
    mechanistic_train = np.asarray([_mechanistic_baseline(row, reference_state)[0] for row in rows_by_split["train"]], dtype=float)
    fit_target = y_train - mechanistic_train if fusion == "mechanistic_residual" else y_train
    model.fit(X_train, fit_target)
    predictions: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    median = float(np.median(y_train))
    for split in ("train", "validation", "test"):
        rows = rows_by_split[split]
        if not rows:
            metrics.append(_metric_row(split, np.asarray([]), np.asarray([]), "ai", target_variable))
            metrics.append(_metric_row(split, np.asarray([]), np.asarray([]), "median_baseline", target_variable))
            continue
        y_true = np.asarray([float(row["target_clean_value"]) for row in rows], dtype=float)
        raw_prediction = model.predict(imputer.transform(_matrix(rows, columns, include_mechanism)))
        mechanistic_predictions = np.asarray([_mechanistic_baseline(row, reference_state)[0] for row in rows], dtype=float)
        ai_pred = raw_prediction + mechanistic_predictions if fusion == "mechanistic_residual" else raw_prediction
        median_pred = np.full(len(rows), median, dtype=float)
        metrics.append(_metric_row(split, y_true, ai_pred, "ai_" + fusion, target_variable))
        metrics.append(_metric_row(split, y_true, median_pred, "median_baseline", target_variable))
        for row, truth, prediction, mechanism_prediction in zip(rows, y_true, ai_pred, mechanistic_predictions):
            output = {
                "target_variable": target_variable,
                "dataset_split": split,
                "target_feature_row_key": row.get("target_feature_row_key"),
                "target_time_bucket": row.get("target_time_bucket"),
                "target_station_id": row.get("target_station_id"),
                "y_true": float(truth),
                "y_pred": float(prediction),
                "median_baseline_pred": median,
                "model": "ai_" + fusion,
            }
            if include_mechanism:
                output.update(_mechanism_features(row))
                output["mechanism_baseline_pred"] = float(mechanism_prediction)
                output["mechanism_state_source"] = _mechanistic_baseline(row, reference_state)[1]
            predictions.append(output)
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        # HistGradientBoosting exposes no stable public importance vector;
        # leave a transparent placeholder rather than inventing values.
        importances = np.zeros(len(columns), dtype=float)
    importance_rows = [{"target_variable": target_variable, "model": "ai_" + fusion, "feature": column, "importance": float(value)} for column, value in zip(columns, importances)]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1]
    output_root = output_root or root / "storage" / "exports" / f"model_{stamp}"
    output_root.mkdir(parents=True, exist_ok=True)
    files = {
        "predictions": output_root / "predictions.csv",
        "metrics": output_root / "metrics.csv",
        "feature_importance": output_root / "feature_importance.csv",
        "model": output_root / "model.pkl",
    }
    _write_csv(files["predictions"], predictions)
    _write_csv(files["metrics"], metrics)
    _write_csv(files["feature_importance"], importance_rows)
    with files["model"].open("wb") as handle:
        pickle.dump({"model": model, "imputer": imputer, "feature_columns": columns, "target_variable": target_variable, "fusion": fusion, "algorithm": algorithm}, handle)
    database = database or root / "storage" / "data_cleaning.db"
    _write_sqlite(database, predictions, metrics, importance_rows)
    manifest = {
        "run_id": f"model_{stamp}", "status": "completed", "target_variable": target_variable,
        "algorithm": algorithm, "fusion": fusion, "random_state": random_state,
        "input_dir": str(input_dir), "train_rows": len(rows_by_split["train"]),
        "validation_rows": len(rows_by_split["validation"]), "test_rows": len(rows_by_split["test"]),
        "feature_count": len(columns), "excluded_target_feature": f"feature_{_safe_name(target_variable)}",
        "files": {key: str(value) for key, value in {**files, "database": database}.items()},
        "metrics": metrics,
    }
    manifest_path = manifest_root(root) / f"{manifest['run_id']}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = str(manifest_path)
    return manifest
