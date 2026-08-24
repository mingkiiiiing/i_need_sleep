from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import LeaveOneGroupOut

FEATURES = ["ndci_field", "mci_field", "rrs_green_560", "rrs_red_665", "rrs_rededge_705", "rrs_nir_842"]


def _models() -> dict[str, Any]:
    return {"linear": LinearRegression(), "random_forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=23, n_jobs=1)}


def calibrate_chlorophyll(frame: pd.DataFrame) -> tuple[Any, dict[str, Any], pd.DataFrame]:
    required = FEATURES + ["chlorophyll_a_ug_l", "observed_at"]
    clean = frame.dropna(subset=required).copy()
    groups = clean["observed_at"].astype(str).str[:10]
    if len(clean) < 10 or groups.nunique() < 3:
        raise ValueError("at least 10 samples across 3 independent dates are required")
    x, y = clean[FEATURES].to_numpy(float), clean["chlorophyll_a_ug_l"].to_numpy(float)
    rows = []
    predictions: dict[str, np.ndarray] = {}
    for name, template in _models().items():
        predicted = np.full(len(clean), np.nan)
        for train, test in LeaveOneGroupOut().split(x, y, groups):
            model = _models()[name]
            model.fit(x[train], y[train])
            predicted[test] = model.predict(x[test])
        predictions[name] = predicted
        rows.append({"model": name, "rmse_ug_l": math.sqrt(mean_squared_error(y, predicted)), "mae_ug_l": mean_absolute_error(y, predicted), "r2": r2_score(y, predicted), "samples": len(clean), "date_groups": int(groups.nunique()), "validation": "leave_one_date_out"})
    metrics = pd.DataFrame(rows).sort_values(["rmse_ug_l", "mae_ug_l"]).reset_index(drop=True)
    selected = str(metrics.loc[0, "model"])
    model = _models()[selected]
    model.fit(x, y)
    residuals = y - predictions[selected]
    selected_r2 = float(metrics.loc[0, "r2"])
    status = "calibrated" if selected_r2 > 0 else "calibrated_low_generalization"
    feature_ranges = {feature: {"min": float(clean[feature].min()), "max": float(clean[feature].max())} for feature in FEATURES}
    audit = {"status": status, "selected_model": selected, "features": FEATURES, "feature_ranges": feature_ranges, "samples": len(clean), "date_groups": int(groups.nunique()), "uncertainty_residual_std_ug_l": float(np.std(residuals, ddof=1)), "validation": "leave_one_date_out; no same-date leakage", "metrics": metrics.to_dict(orient="records")}
    return model, audit, metrics


def run_chlorophyll_calibration(input_path: Path, output_root: Path) -> dict[str, Any]:
    frame = pd.read_parquet(input_path) if input_path.suffix.casefold() == ".parquet" else pd.read_csv(input_path)
    model, audit, metrics = calibrate_chlorophyll(frame)
    output_root.mkdir(parents=True, exist_ok=True)
    model_path, metrics_path, manifest_path = output_root / "chlorophyll_model.joblib", output_root / "calibration_metrics.csv", output_root / "manifest.json"
    joblib.dump({"model": model, "features": FEATURES, "feature_ranges": audit["feature_ranges"], "audit": audit}, model_path)
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    manifest = {**audit, "input": str(input_path), "outputs": {"model": str(model_path), "metrics": str(metrics_path)}, "manifest": str(manifest_path), "use_constraint": "field-spectral transfer calibration; satellite application must report domain-shift uncertainty"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
