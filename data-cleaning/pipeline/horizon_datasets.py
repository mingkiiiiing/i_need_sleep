from __future__ import annotations

"""Truthful readiness gate for the three Taihu forecast horizons."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


HORIZON_SPECS = {
    "h1_3d": {"task_id": "P12-05", "days": [1, 3], "needs_seasonal": False},
    "h7_15d": {"task_id": "P12-06", "days": [7, 15], "needs_seasonal": False},
    "h30_90d": {"task_id": "P12-07", "days": [30, 90], "needs_seasonal": True},
}
TARGET_COLUMNS = {
    "target_chlorophyll_a",
    "target_bloom_area",
    "target_cyanobacteria_biomass",
    "target_risk_level",
    "direct_phytoplankton_biomass",
    "direct_algae_density",
    "direct_chlorophyll_a",
}


def build_supervised_horizon(frame: pd.DataFrame, horizon: str, *, target_column: str = "direct_phytoplankton_biomass") -> tuple[pd.DataFrame, dict[str, Any]]:
    if horizon not in HORIZON_SPECS:
        raise ValueError(f"unsupported horizon: {horizon}")
    if target_column not in frame:
        return frame.iloc[0:0].copy(), {"labels": 0, "target_column": target_column, "leakage_violations": 0}
    lower, upper = HORIZON_SPECS[horizon]["days"]
    source = frame.copy()
    source["feature_date"] = pd.to_datetime(source["feature_date"], errors="raise")
    targets = source.loc[source[target_column].notna(), ["feature_date", target_column]].sort_values("feature_date")
    target_dates = targets["feature_date"].to_numpy(dtype="datetime64[ns]")
    target_values = targets[target_column].to_numpy(float)
    rows = []
    for _, row in source.iterrows():
        feature_date = row["feature_date"]
        gaps = (target_dates - np.datetime64(feature_date)) / np.timedelta64(1, "D")
        candidates = np.where((gaps >= lower) & (gaps <= upper))[0]
        if not len(candidates):
            continue
        midpoint = (lower + upper) / 2.0
        selected = candidates[np.argmin(np.abs(gaps[candidates] - midpoint))]
        output = row.to_dict()
        output.update(target_value=float(target_values[selected]), target_time=pd.Timestamp(target_dates[selected]).date().isoformat(), target_gap_days=float(gaps[selected]), target_variable=target_column.removeprefix("direct_"), target_type="observed", target_source="taihu_thqbca_history", target_interpolated=0)
        rows.append(output)
    result = pd.DataFrame(rows)
    if len(result):
        result["feature_date"] = pd.to_datetime(result["feature_date"]).dt.date.astype(str)
    violations = int((pd.to_datetime(result["target_time"]) <= pd.to_datetime(result["feature_date"])).sum()) if len(result) else 0
    return result, {"labels": int(len(result)), "target_column": target_column, "target_observation_dates": int(len(targets)), "leakage_violations": violations, "target_policy": "select a real future observation inside the horizon; never interpolate or forward-fill labels"}


def assess_horizon_readiness(frame: pd.DataFrame, horizon: str, *, seasonal_ready: bool = False) -> dict[str, Any]:
    if horizon not in HORIZON_SPECS:
        raise ValueError(f"unsupported horizon: {horizon}")
    spec = HORIZON_SPECS[horizon]
    # Only base truth columns establish target readiness.  Lag/rolling/count
    # derivatives must never be mistaken for additional observed targets.
    present_targets = [column for column in frame.columns if column in TARGET_COLUMNS and frame[column].notna().any()]
    blockers: list[dict[str, str]] = []
    if not present_targets:
        blockers.append({"code": "MISSING_OBSERVED_BLOOM_TARGET", "status": "BLOCKED_DATA", "action": "deliver authorized station/float chlorophyll or calibrated remote bloom-area truth"})
    if spec["needs_seasonal"] and not seasonal_ready:
        blockers.append({"code": "MISSING_C3S_SEASONAL_HINDCAST", "status": "BLOCKED_AUTH", "action": "configure a valid CDS API account and retrieve C3S hindcasts"})
    status = "READY" if not blockers else ("BLOCKED_AUTH" if any(item["status"] == "BLOCKED_AUTH" for item in blockers) else "BLOCKED_DATA")
    return {"horizon": horizon, "task_id": spec["task_id"], "status": status, "rows": int(len(frame)), "present_targets": present_targets, "blockers": blockers}


def run_horizon_dataset_gate(input_path: Path, output_root: Path, *, horizon: str, seasonal_ready: bool = False) -> dict[str, Any]:
    frame = pd.read_parquet(input_path) if input_path.suffix.casefold() == ".parquet" else pd.read_csv(input_path)
    audit = assess_horizon_readiness(frame, horizon, seasonal_ready=seasonal_ready)
    labelled, label_audit = build_supervised_horizon(frame, horizon)
    if not label_audit["labels"]:
        audit["status"] = "BLOCKED_DATA"
        audit["blockers"].append({"code": "NO_TARGET_IN_HORIZON_WINDOWS", "status": "BLOCKED_DATA", "action": "add higher-frequency observed or calibrated remote targets"})
    output_root.mkdir(parents=True, exist_ok=True)
    candidate_path = output_root / f"candidate_dataset_{horizon}.parquet"
    manifest_path = output_root / f"dataset_{horizon}_manifest.json"
    labelled.to_parquet(candidate_path, index=False)
    final_path = output_root / f"dataset_{horizon}.parquet"
    if audit["status"] == "READY":
        labelled.to_parquet(final_path, index=False)
    manifest = {
        **audit,
        **label_audit,
        "input": str(input_path),
        "candidate_labelled_dataset": str(candidate_path),
        "final_dataset": str(final_path) if audit["status"] == "READY" else None,
        "trainable": audit["status"] == "READY",
        "truth_policy": "targets are real future observations selected inside each horizon; no synthetic or interpolated targets are created",
        "manifest": str(manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
